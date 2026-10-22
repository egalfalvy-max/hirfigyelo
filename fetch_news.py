#!/usr/bin/env python3
"""Hírfigyelő: RSS-ek letöltése, szűrés, pontozás, címkézés, majd news.json (és hétfőn weekly.json).

Működés:
  1. Letölti a config.json-ban felsorolt RSS-csatornákat.
  2. Eldobja, ami nem kell (clickbait, fizetőfal, másik oldalra mutató link, kizárt kulcsszavak).
  3. Pontoz és altémát rendel minden cikkhez: Claude-dal (ha van ANTHROPIC_API_KEY), különben kulcsszavakkal.
  4. A legjobb cikkeket témánként a news.json-ba írja. Ez minden futáskor teljesen felülíródik.
  5. A napi válogatásokat egy 8 napos gyűjtőbe (weekpool.json) teszi; a hét első napján
     (vagy WEEKLY=1 kézi indításnál) ebből készül a weekly.json, a hét legjobbjai.
     A gyűjtőből a régi tételek maguktól kiesnek, korábbi listákat nem őriz.
"""
import hashlib
import html
import json
import os
import re
import sys
from datetime import datetime, timedelta, timezone
from urllib.parse import urlparse

import feedparser
import requests

ROOT = os.path.dirname(os.path.abspath(__file__))
UA = "Mozilla/5.0 (compatible; Hirfigyelo/1.1)"


# ---------- segédek ----------

def load_json(name, default):
    try:
        with open(os.path.join(ROOT, name), encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return default


def save_json(name, data):
    with open(os.path.join(ROOT, name), "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.write("\n")


def base_domain(url):
    host = (urlparse(url).hostname or "").lower()
    parts = host.split(".")
    return ".".join(parts[-2:]) if len(parts) >= 2 else host


def clean(text):
    text = re.sub(r"<[^>]+>", " ", text or "")
    return re.sub(r"\s+", " ", html.unescape(text)).strip()


def entry_time(entry):
    for key in ("published_parsed", "updated_parsed"):
        t = entry.get(key)
        if t:
            return datetime(*t[:6], tzinfo=timezone.utc)
    return None


IMG_RE = re.compile(r"<img[^>]+src=[\"']([^\"']+)[\"']", re.I)


def entry_image(entry):
    """Előnézeti kép az RSS-ből: media:content, media:thumbnail, enclosure, vagy az első <img>."""
    for key in ("media_content", "media_thumbnail"):
        for m in entry.get(key) or []:
            url = m.get("url")
            if url and (m.get("medium") in (None, "image") or key == "media_thumbnail"):
                return url
    for enc in entry.get("enclosures") or []:
        if (enc.get("type") or "").startswith("image") and enc.get("href"):
            return enc["href"]
    blobs = [c.get("value", "") for c in entry.get("content") or []] + [entry.get("summary", "")]
    for blob in blobs:
        m = IMG_RE.search(blob or "")
        if m and m.group(1).startswith("http"):
            return html.unescape(m.group(1))
    return None


def word_hits(text, keywords):
    """Hány különböző kulcsszó szerepel a szövegben (szóhatárral)."""
    hits = 0
    for kw in keywords:
        if re.search(r"(?<![\w-])" + re.escape(kw.lower()) + r"(?![\w-])", text):
            hits += 1
    return hits


def interest_label(interest, idx):
    return interest.get("label") or interest.get("text", "Altéma {}".format(idx + 1))[:28]


# ---------- letöltés ----------

def fetch_source(src):
    """Visszaadja a forrás cikkeit. Hibánál kivételt dob (ezt az oldal felugró ablakban mutatja)."""
    if not src.get("rss"):
        raise ValueError("nincs RSS link megadva")
    resp = requests.get(src["rss"], headers={"User-Agent": UA}, timeout=25)
    resp.raise_for_status()
    feed = feedparser.parse(resp.content)
    if not feed.entries:
        raise ValueError("üres vagy érvénytelen RSS-csatorna")
    items = []
    for e in feed.entries:
        link = e.get("link", "")
        title = clean(e.get("title", ""))
        if not link or not title:
            continue
        items.append({
            "title": title,
            "link": link,
            "summary": clean(e.get("summary", ""))[:600],
            "image": entry_image(e),
            "published": entry_time(e),
            "source": src["name"],
            "source_weight": src.get("weight", 3),
            "source_domain": base_domain(src.get("rss") or src.get("url", "")),
        })
    return items


# ---------- szűrés ----------

def exclusion_reason(item, cfg):
    ex = cfg.get("exclude", {})
    text = (item["title"] + " " + item["summary"]).lower()
    for phrase in ex.get("phrases", []):
        if phrase.lower() in text:
            return "kizárt kifejezés"
    if word_hits(text, ex.get("keywords", [])):
        return "kizárt kulcsszó"
    for pat in ex.get("title_patterns", []):
        if re.search(pat, item["title"], re.I):
            return "clickbait cím"
    if cfg.get("same_domain_only", True):
        if base_domain(item["link"]) != item["source_domain"]:
            return "másik oldalra mutató link"
    return None


def keyword_score(item, topic):
    """Pontszám és a legjobban illő altéma indexe."""
    text = (item["title"] + " " + item["summary"]).lower()
    total, best, best_val = 0, 0, -1
    for idx, interest in enumerate(topic.get("interests", [])):
        hits = word_hits(text, interest.get("keywords", []))
        val = interest.get("weight", 3) * min(hits, 2)
        total += val
        if hits and val > best_val:
            best, best_val = idx, val
    return total, best


# ---------- visszajelzés ----------

def source_adjustments(feedback):
    adj = {}
    for v in feedback.get("votes", []):
        delta = 1 if v.get("vote") == "up" else -1
        adj[v.get("source")] = adj.get(v.get("source"), 0) + delta
    return {k: max(-2.0, min(2.0, n * 0.3)) for k, n in adj.items()}


def label_adjustments(feedback):
    adj = {}
    for v in feedback.get("votes", []):
        if not v.get("label"):
            continue
        delta = 1 if v.get("vote") == "up" else -1
        adj[v["label"]] = adj.get(v["label"], 0) + delta
    return {k: max(-1.5, min(1.5, n * 0.25)) for k, n in adj.items()}


# ---------- Claude pontozás ----------

def call_claude(prompt, cfg, key):
    models = [cfg.get("model", "claude-haiku-4-5")] + cfg.get("fallback_models", [])
    last = None
    for model in models:
        resp = requests.post(
            "https://api.anthropic.com/v1/messages",
            headers={"x-api-key": key, "anthropic-version": "2023-06-01", "content-type": "application/json"},
            json={"model": model, "max_tokens": 4000, "messages": [{"role": "user", "content": prompt}]},
            timeout=120,
        )
        if resp.status_code in (400, 404) and "model" in resp.text.lower():
            last = "ismeretlen modell: " + model
            continue  # próbáljuk a következő modellt
        resp.raise_for_status()
        return resp.json()["content"][0]["text"]
    raise RuntimeError(last or "egyik modell sem érhető el")


def claude_scores(topic, items, cfg, feedback):
    key = os.environ.get("ANTHROPIC_API_KEY")
    if not key or not items:
        return None
    interests = "\n".join(
        "{}. {} (fontosság {}/5): {}".format(i, interest_label(it, i), it.get("weight", 3), it["text"])
        for i, it in enumerate(topic["interests"])
    )
    votes = [v for v in feedback.get("votes", []) if v.get("topic") in (None, topic["id"])][-40:]
    liked = "\n".join("- " + v["title"] for v in votes if v.get("vote") == "up")
    disliked = "\n".join("- " + v["title"] for v in votes if v.get("vote") == "down")
    listing = "\n".join(
        "{}. [{}] {} :: {}".format(i, it["source"], it["title"], it["summary"][:250])
        for i, it in enumerate(items)
    )
    prompt = (
        "Hírszűrő vagy. A felhasználó profilja:\n{profile}\n\n"
        "Téma: {topic}\nAltémák (index. címke: leírás):\n{interests}\n\n"
        "Ezeket a cikkeket kifejezetten kedvelte:\n{liked}\n\n"
        "Ezeket nem kedvelte:\n{disliked}\n\n"
        "Minden cikkhez adj 1-10 pontot (mennyire érdekes neki), és válaszd ki, melyik altémához "
        "tartozik leginkább (az altéma indexe). Magas pont: valódi hír (bejelentés, új eszköz, szabály, "
        "felvásárlás, áttörés), ami a témához és a munkájához kapcsolódik. Alacsony pont: vélemény, "
        "ismétlés, clickbait, bulvár, fizetőfal mögötti tartalom, a témához nem kapcsolódó cikk.\n\n"
        "Cikkek:\n{listing}\n\n"
        "Csak egy JSON-tömbbel válaszolj, más szöveg nélkül: "
        '[{{"id": 0, "score": 7, "label": 0}}, ...]'
    ).format(
        profile=cfg.get("profile", ""), topic=topic["name"], interests=interests,
        liked=liked or "(még nincs)", disliked=disliked or "(még nincs)", listing=listing,
    )
    text = call_claude(prompt, cfg, key)
    match = re.search(r"\[.*\]", text, re.S)
    data = json.loads(match.group(0))
    out = {}
    for d in data:
        try:
            out[int(d["id"])] = (float(d["score"]), int(d.get("label", 0)))
        except (KeyError, TypeError, ValueError):
            continue
    return out


# ---------- heti válogatás ----------

def update_pool(pool, daily, now, days):
    cutoff = (now - timedelta(days=days)).isoformat()
    by_id = {it["id"]: it for it in pool.get("items", []) if it.get("published", "") >= cutoff}
    for topic_id, items in daily.items():
        for it in items:
            prev = by_id.get(it["id"])
            if not prev or it.get("score", 0) > prev.get("score", 0):
                by_id[it["id"]] = dict(it, topic=topic_id)
    return {"items": sorted(by_id.values(), key=lambda x: x.get("published", ""), reverse=True)}


def build_weekly(pool, cfg, feedback, now):
    wk = cfg.get("weekly", {})
    limit = wk.get("max_items_per_topic", 10)
    down = {v["id"] for v in feedback.get("votes", []) if v.get("vote") == "down"}
    up = {v["id"] for v in feedback.get("votes", []) if v.get("vote") == "up"}
    start = now - timedelta(days=7)
    topics = {}
    for topic in cfg["topics"]:
        items = [it for it in pool.get("items", [])
                 if it.get("topic") == topic["id"] and it["id"] not in down
                 and it.get("published", "") >= start.isoformat()]
        items.sort(key=lambda it: (it.get("score", 0) + (1.5 if it["id"] in up else 0), it.get("published", "")),
                   reverse=True)
        topics[topic["id"]] = [{k: v for k, v in it.items() if k != "topic"} for it in items[:limit]]
    return {"generated_at": now.isoformat(), "from": start.isoformat(), "to": now.isoformat(), "topics": topics}


def is_weekly_day(cfg, now):
    if os.environ.get("WEEKLY") in ("1", "true", "yes"):
        return True
    wk = cfg.get("weekly", {})
    if not wk.get("enabled", True):
        return False
    budapest = now + timedelta(hours=1)  # elég pontos a nap meghatározásához reggeli futásnál
    return budapest.weekday() == wk.get("weekday", 0)


# ---------- fő folyamat ----------

def main():
    cfg = load_json("config.json", None)
    if cfg is None:
        print("Hiányzik a config.json", file=sys.stderr)
        return 1
    feedback = load_json("feedback.json", {"votes": []})
    src_adj = source_adjustments(feedback)
    lab_adj = label_adjustments(feedback)

    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(hours=cfg.get("max_age_hours", 36))
    errors, stats, result = [], [], {}

    for topic in cfg["topics"]:
        interests = topic.get("interests", [])
        raw = []
        for src in [s for s in cfg["sources"] if s.get("topic") == topic["id"]]:
            stat = {"name": src["name"], "topic": topic["id"], "ok": False, "fetched": 0, "kept": 0}
            try:
                items = fetch_source(src)
                stat["ok"] = True
                stat["fetched"] = len(items)
                raw.extend(items)
            except Exception as exc:  # a hiba az oldalon felugró ablakban jelenik meg
                errors.append({"source": src["name"], "message": str(exc)[:200]})
            stats.append(stat)

        seen, candidates = set(), []
        for it in raw:
            norm = re.sub(r"\W+", "", it["title"].lower())
            if it["link"] in seen or norm in seen:
                continue
            seen.update([it["link"], norm])
            if it["published"] is None or it["published"] < cutoff:
                continue
            if exclusion_reason(it, cfg):
                continue
            must = topic.get("must_match", [])
            if must and not word_hits((it["title"] + " " + it["summary"]).lower(), must):
                continue
            candidates.append(it)

        candidates.sort(key=lambda x: x["published"], reverse=True)
        candidates = candidates[:80]

        scores = None
        try:
            scores = claude_scores(topic, candidates, cfg, feedback)
        except Exception as exc:
            errors.append({"source": "Claude pontozás",
                           "message": "kulcsszavas szűrésre váltottam: " + str(exc)[:150]})

        scored = []
        for idx, it in enumerate(candidates):
            if scores is not None:
                base, label_idx = scores.get(idx, (0, 0))
                threshold = cfg.get("min_ai_score", 6)
            else:
                base, label_idx = keyword_score(it, topic)
                threshold = cfg.get("min_keyword_score", 4)
            if base < threshold:
                continue
            label_idx = label_idx if 0 <= label_idx < len(interests) else 0
            label = interest_label(interests[label_idx], label_idx) if interests else ""
            final = base + 0.4 * it["source_weight"] + src_adj.get(it["source"], 0) + lab_adj.get(label, 0)
            scored.append((final, label, it))

        scored.sort(key=lambda p: (p[0], p[2]["published"]), reverse=True)
        out = []
        for final, label, it in scored[: cfg.get("max_items_per_topic", 10)]:
            out.append({
                "id": hashlib.sha1(it["link"].encode()).hexdigest()[:10],
                "title": it["title"],
                "source": it["source"],
                "published": it["published"].isoformat(),
                "link": it["link"],
                "label": label,
                "image": it["image"],
                "score": round(final, 2),
            })
            for st in stats:
                if st["name"] == it["source"] and st["topic"] == topic["id"]:
                    st["kept"] += 1
        result[topic["id"]] = out

    payload = {
        "generated_at": now.isoformat(),
        "window_hours": cfg.get("max_age_hours", 36),
        "scoring": "claude" if os.environ.get("ANTHROPIC_API_KEY") else "kulcsszavas",
        "topics": result,
        "errors": errors,
        "sources": stats,
    }
    save_json("news.json", payload)

    wk = cfg.get("weekly", {})
    pool = update_pool(load_json("weekpool.json", {"items": []}), result, now, wk.get("pool_days", 8))
    save_json("weekpool.json", pool)
    weekly_msg = ""
    if is_weekly_day(cfg, now):
        save_json("weekly.json", build_weekly(pool, cfg, feedback, now))
        weekly_msg = ", heti válogatás elkészült"

    total = sum(len(v) for v in result.values())
    print("Kész: {} cikk, {} hiba{}".format(total, len(errors), weekly_msg))
    return 0


if __name__ == "__main__":
    sys.exit(main())
