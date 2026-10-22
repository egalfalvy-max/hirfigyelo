# Hírfigyelő: telepítés lépésről lépésre

Egyszeri beállítás, kb. 15 perc. Utána minden reggel magától frissül, hétfőn heti válogatás is készül. Az oldal telefonról is megnyitható.

## 1. GitHub-fiók és tároló
1. Regisztrálj a github.com-on (ingyenes).
2. Új tároló (New repository): név `hirfigyelo`, **Public**. (Az ingyenes oldalhoz a tárolónak nyilvánosnak kell lennie. A témáid, forrásaid és a cikklista így látszanak, de jelszó vagy titok nem kerül bele.)

## 2. Fájlok feltöltése
Az **Add file → Upload files** gombbal töltsd fel: `index.html`, `config.json`, `feedback.json`, `fetch_news.py`, `requirements.txt`, `README.md`.

Az időzítő fájlt külön kell létrehozni (a rejtett mappa miatt): **Add file → Create new file**, a név mezőbe írd be pontosan: `.github/workflows/update.yml`, majd másold bele a fájl tartalmát.

## 3. Engedélyek
- **Settings → Actions → General → Workflow permissions:** Read and write permissions → Save.
- **Settings → Pages:** Source: Deploy from a branch, Branch: `main`, mappa: `/ (root)` → Save. Pár perc múlva megjelenik az oldal címe (`https://FELHASZNALO.github.io/hirfigyelo/`). Ezt mentsd el a telefonod kezdőképernyőjére.

## 4. Első futtatás
**Actions → Hírfigyelő frissítés → Run workflow.** Egy-két perc múlva megjelennek a cikkek. A „Heti válogatás most” = `true` választással a heti fül is azonnal megtelik.
Utána naponta 05:00 UTC-kor (kb. 6-7 óra magyar idő szerint) magától fut; hétfőn a heti válogatást is elkészíti.

## 5. Okosabb szűrés Claude-dal (ajánlott, nem kötelező)
Kulcsszavas szűréssel is működik, de a Claude sokkal pontosabban érti, mi az „izgalmas”, és pontosabban rendeli a cikkeket az altémákhoz.
1. Kérj API-kulcsot a console.anthropic.com oldalon.
2. A tárolóban: **Settings → Secrets and variables → Actions → New repository secret**, név: `ANTHROPIC_API_KEY`, érték: a kulcs.
3. A kis modell (Haiku) napi néhány tíz cikknél centekbe kerül. Ha a `config.json`-ban megadott modell nem érhető el, a szkript a `fallback_models` listából próbál másikat.

## 6. Gombok az oldalról (ajánlott)
A Frissítés fülön megadhatod a tároló nevét és egy tokent, így a gyűjtés indítása, a források és témák mentése és a visszajelzések mentése egy kattintás.
Token: GitHub → Settings → Developer settings → Fine-grained tokens → csak a `hirfigyelo` tárolóra, jogok: **Actions: Read and write**, **Contents: Read and write**. Token nélkül a gombok letöltik a módosított fájlt, azt kell feltölteni.

## Az oldal fülei
- **Témafülek (pl. AI):** a napi válogatás kártyákon, legfeljebb 10 cikk. Fent altéma-szűrő (Modellek & motion, Reklám & film, AI artistok, Szabályozás). Minden kártyán cím, forrás, idő, link, altémacímke és az RSS-ben talált előnézeti kép (ha nincs, generált borító).
- **Heti válogatás:** a hét legjobb 10 cikke témánként, hétfő reggel frissül.
- **Források:** források listája állapottal, új forrás hozzáadása bármelyik témához, törlés.
- **Frissítés:** kézi gyűjtés, heti válogatás azonnal, visszajelzések mentése, utolsó futás részletei.
- **+ Új téma:** új fül (pl. Magyar belpolitika). Altémák soronként, `Címke: mi érdekel benne` formában.
- Ha egy forrás kiesik, vagy a pontozás hibára fut, az oldal megnyitáskor felugró ablakban jelzi.

## Mit hol szerkesztesz?
- `config.json`: témák, altémák (címke, leírás, kulcsszavak, fontosság), források, kizárások, heti beállítások (vagy az oldalról).
- `feedback.json`: az Érdekel / Nem érdekel jelzések. Ebből tanul a szűrő: a kedvelt cikkekhez hasonlók, a kedvelt altémák és források előrébb kerülnek.
- `news.json`: a napi eredmény, minden futáskor felülíródik.
- `weekpool.json`: a napi válogatások gyűjtője a heti listához; a 8 napnál régebbi tételek maguktól kiesnek.
- `weekly.json`: a heti válogatás, hetente felülíródik.
