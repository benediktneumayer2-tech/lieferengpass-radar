# Betrieb

**Stand:** 11.11.2026 · öffentliche Fassung 0.1 · Projektordner in den Beispielen: `~/lieferengpass-radar` (`<projektordner>`)

Dieses Dokument beschreibt Installation, Konfiguration, alle Befehle, die Zeitsteuerung, Alarme, die zweite Kopie, das Nachholen und das Vorgehen, wenn eine Quelle sich ändert. Wie die Teile zusammenhängen, steht in [ARCHITEKTUR.md](ARCHITEKTUR.md).

## Voraussetzungen

| Bedarf | Stand in der Referenzinstanz (beobachtet) |
|---|---|
| Linux mit systemd-Benutzersitzung und Linger (nur für die Timer) | `loginctl show-user "$USER" -p Linger` → `Linger=yes` |
| Python ≥ 3.12 (`pyproject.toml`) | `.venv` mit Python 3.12.3 |
| Python-Pakete `jinja2>=3.1`, `xlrd>=2.0`; zum Testen `pytest>=8` | jinja2 3.1.6, xlrd 2.0.1, pytest 9.1.1; Paket als editierbare Installation (`__editable__.stockout_at-0.1.0.pth`) |
| `pdftotext` (poppler) für die polnische PDF-Liste | `/usr/bin/pdftotext` Version 24.02.0 |
| Internetzugang zu den Quellen | – |
| Speicher | Archiv 577 MB nach gut drei Wochen Tagesbetrieb plus Vorgeschichte (wächst), Datenbank 107 MB, Website 149 MB |
| optional ein zweites Laufwerk für die Kopie | nur nötig, wenn `STOCKOUT_MIRROR` gesetzt ist, siehe [Zweite Kopie](#zweite-kopie) |

Ohne `pdftotext` scheitert nur das Lesen der polnischen Liste; der Aufbau überspringt diese Dateien dann ohne Meldung.

## Installation

Die folgenden Schritte entsprechen dem Aufbau der Referenzinstanz. Sie wurden für diese Dokumentation **nicht erneut ausgeführt**.

```bash
git clone https://github.com/benediktneumayer2-tech/lieferengpass-radar.git ~/lieferengpass-radar
cd ~/lieferengpass-radar
python3 -m venv .venv
.venv/bin/pip install -e '.[dev]'          # editierbar: modell.MODELS sucht models/ relativ zum Quellbaum
```

Zeitsteuerung einrichten (Units liegen in `deploy/systemd/`):

```bash
cp deploy/systemd/stockout-*.service deploy/systemd/stockout-*.timer ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now stockout-archive.timer stockout-nachholen.timer stockout-eko.timer
```

Die Units erwarten den Projektordner unter `~/lieferengpass-radar`: `WorkingDirectory` und `ExecStart` verwenden `%h/lieferengpass-radar` (`%h` ist das Home-Verzeichnis). Liegt der Ordner woanders, beide Zeilen anpassen. Damit die Timer ohne Anmeldung laufen, braucht der Benutzer Linger (`loginctl enable-linger`).

Erster Probelauf ohne Netz (am 10.11.2026 in einem Arbeitsordner außerhalb des Projekts geprüft): Ein Archiv mit nur einer BASG-Datei genügt für `build` (0,2 s, 844 Packungen, 696 Episoden) und `site` (0,3 s, 1.133 Seiten); Auslands- und Registerquellen sind dafür nicht nötig.

## Konfiguration

Es gibt keine Konfigurationsdatei, keine Zugangsdaten und keine Schlüssel. Quell-URLs stehen fest in `archive.SOURCES`.

| Option (vor dem Unterbefehl) | Umgebungsvariable | Standard |
|---|---|---|
| `--archive PFAD` | `STOCKOUT_ARCHIVE` | `data/archive` |
| `--mirror-dir PFAD` | `STOCKOUT_MIRROR` | leer: keine Kopie; `status` zeigt `Kopie: ausgeschaltet …` |
| `--mirror-mount PFAD` | `STOCKOUT_MIRROR_MOUNT` | leer: keine Prüfung; gesetzt verlangt die Kopie, dass dieser Pfad ein Einhängepunkt ist |
| `--no-mirror` | – | Kopie aus, auch wenn `STOCKOUT_MIRROR` gesetzt ist |
| `--db PFAD` (je Unterbefehl) | `STOCKOUT_DB` | `data/derived/stockout.sqlite` |
| `--out PFAD` bzw. `--dir PFAD` | `STOCKOUT_SITE` | `site` |
| `import-legacy --package PFAD` | `STOCKOUT_LEGACY_PACKAGE` | kein Standard ([`import-legacy`](#import-legacy)) |
| – | `STOCKOUT_CONTACT` | leer: User-Agent ohne Kontakt ([DATENQUELLEN.md](DATENQUELLEN.md#2-gemeinsame-regeln-beim-abruf)) |

Alle Standardpfade sind **relativ zum Arbeitsverzeichnis**. Befehle deshalb im Projektordner ausführen (die systemd-Units tun das). Globale Optionen stehen vor dem Unterbefehl, z. B. `stockout --no-mirror status`. Die systemd-Units setzen keine Umgebungsvariablen; wer eine Kopie oder einen Kontakt will, ergänzt `Environment=`-Zeilen in den Services.

## Befehlsreferenz

Quelle: `src/stockout_at/cli.py` (`main`). Hilfe: `.venv/bin/stockout --help` und `stockout <befehl> --help`.

| Befehl | Zweck | Netz | schreibt | Exit-Code |
|---|---|---|---|---|
| `fetch` | Quellen abrufen und archivieren, danach Kopie, falls eingestellt | ja | Archiv, Manifest, Kopie | 0; 1 bei FEHLER |
| `mirror` | fehlende Archivdateien aufs zweite Laufwerk kopieren | nein | Kopie, `mirror_state.json` | 0; 1 bei Fehler |
| `status` | Zustand des Archivs anzeigen | nein | nichts (legt höchstens einen fehlenden, leeren Archivordner an) | 0; 2 bei Warnungen |
| `import-legacy` | Vorgeschichte einmalig importieren | ja (außer reinem Paketimport) | Archiv, Kopie | 0; 2 ohne Datenpaket |
| `build` | Datenbank vollständig neu aus dem Archiv bauen | nein | Datenbank, optional JSON | 0 |
| `site` | statische Website aus der Datenbank erzeugen | nein | Website-Ordner | 0 |
| `daily` | Tageslauf: Abruf, Datenbank, Rückblick, Website, Protokolle | ja | alles oben | 0; 1 bei Fehler in einem Schritt |
| `vorlauf` | Vorlaufmessung | nein | nur mit `--json` | 0 |
| `rueckblick` | Rückblicktests | nein | nur mit `--json` | 0 |
| `schaerfe` | Schärfung der Stufen messen | nein | nur mit `--json` | 0 |
| `modell` | Z3-Verfahren lernen und prüfen; `--einfrieren` schreibt `models/` | nein | nur mit `--json` bzw. `--einfrieren` | 0 |
| `bewertung` | Vorhersageprotokoll bewerten | nein | mit `--rueckblick` Probelauf-Protokolle; `--json` | 0; 1 ohne Prüfplan |
| `protokoll` | Merkmals- und Vorhersageprotokoll des Tages | nein | Archiv (`protokoll/`), Kopie | 0; 1 wenn die Kopie scheitert |
| `preview` | lokale Vorschau der Website auf 127.0.0.1 | nein | nichts | 1, wenn keine Website existiert |

Ein unbehandelter Fehler (z. B. fehlende Datenbank) endet mit Python-Traceback und Exit-Code 1.

### `fetch`

```text
stockout fetch [--source QUELLE ...] [--nachholen] [--eko]
```

- **ohne Option** (planmäßiger Lauf): EKO aus dem RIS, wenn das Zeitfenster es erlaubt (sonst Meldung „außerhalb der RIS-Abfragezeiten … übersprungen“); dann alle 19 Quellen, Tagesquellen nur, wenn ihr letzter Erfolg mindestens 20 h zurückliegt; dann CIMA-Register; dann Kopie, falls eingestellt.
- `--source QUELLE` (mehrfach möglich; Auswahl aus den 19 Namen in `SOURCES`): nur diese Quellen, **ohne** 20-h-Sperre, ohne EKO; CIMA-Register nur, wenn `cima` dabei ist.
- `--nachholen`: nur Quellen ohne Tagesrhythmus, deren **letzter** Live-Versuch scheiterte (`archive.retry_due`); ohne EKO. Ist nichts offen, endet der Befehl sofort („Nachholen: nichts offen“) ohne Kopie.
- `--eko`: nur EKO (für den Abendlauf an Werktagen), danach Kopie, falls eingestellt.

Ausgabezeilen: `OK <quelle>: neu|unverändert, <Bytes>, <Pfad>`, `WARNUNG <quelle>: …`, `FEHLER <quelle>: …`, `OK cima_reg: …`, `OK eko: …`, `Kopie: <n> Dateien nach …` bzw. `FEHLER Kopie: …`.

### `mirror`

```text
stockout mirror
```

Kopiert alle Dateien, die in der Kopie fehlen, eine andere Größe haben oder älter sind, danach das Manifest; Ergebnis in `data/archive/mirror_state.json`. Ohne Ziel (`STOCKOUT_MIRROR` leer) oder mit `--no-mirror` meldet er nur `Kopie: ausgeschaltet …` und endet mit 0.

### `status`

```text
stockout status [--json] [--verify]
```

Zeigt je Quelle aus `SOURCES` den letzten Erfolg, die neueste Fassung, die Zahl der Fassungen und die Fehlversuche der letzten 7 Tage; dazu fehlende BASG-Tage seit dem 17.10.2026, die importierte Vorgeschichte und den Zustand der Kopie. `--json` gibt dasselbe als JSON aus. `--verify` vergleicht zusätzlich die SHA-256 aller Dateien mit der Kopie (liest beide Archive vollständig). Der Befehl liest nur. EKO und `cima_reg` erscheinen nicht.

### `import-legacy`

```text
stockout import-legacy [--package PFAD] [--no-wayback] [--wayback-only QUELLE ...] [--backfill pl_mz|eko ...]
```

- ohne Option: lokal gesicherte BASG-Dateien und ASP-Fassungen aus einem Ordner mit den Manifesten `manifests/basg_snapshots.csv` und `manifests/product_master_versions.csv` (wird nur gelesen), danach alle Internet-Archive-Aufnahmen der BASG-Datei; `--no-wayback` lässt Letzteres weg. Den Ordner nennt `--package` oder `STOCKOUT_LEGACY_PACKAGE` (`legacy.DEFAULT_PACKAGE`); einen Standard gibt es nicht. Fehlt beides, endet der Befehl ohne `--wayback-only` oder `--backfill` mit `FEHLER: Kein Datenpaket für die Vorgeschichte angegeben …` und Exit-Code 2.
- `--wayback-only QUELLE`: nur Internet-Archive-Aufnahmen dieser Quelle.
- `--backfill pl_mz`: alle polnischen Ausgaben seit 2015, die noch fehlen.
- `--backfill eko`: alle EKO-Änderungen seit 2004; nur im RIS-Zeitfenster, Anfragen zufällig verteilt bis 04:30 Uhr.

In der Referenzinstanz ist die Vorgeschichte bereits importiert (`stockout status`, Zeile „Vorgeschichte“); ihre Herkunft steht in [DATENQUELLEN.md](DATENQUELLEN.md#basg-österreich-grundwahrheit). Der lokal gesicherte BASG-Export ist nicht Teil des Repositorys; die Internet-Archive-Aufnahmen holt `stockout import-legacy --wayback-only basg` aus dem Netz. Der Befehl ist idempotent: Bekanntes wird übersprungen bzw. nur als Dublette vermerkt.

### `build`

```text
stockout build [--db DB] [--export-json DIR] [--ref-date JJJJ-MM-TT]
```

Baut die Datenbank vollständig neu (Temporärdatei, dann Austausch) und gibt die Zeilenzahlen aus. `--export-json` schreibt `situation.json`, `overdue.json`, `week.json`, `durations.json`, `substances.json`; `--ref-date` setzt dafür den Stichtag (Standard: letzter Schnappschuss). Beobachtet am 10.11.2026: 58,8 s.

### `site`

```text
stockout site [--db DB] [--out OUT] [--ref-date JJJJ-MM-TT]
```

Erzeugt die Website (siehe [WEBSITE.md](WEBSITE.md)); liest zusätzlich das Archiv (Abdeckung, Registerhinweise) und `<db-Ordner>/json/rueckblick.json`. Beobachtet am 10.11.2026: 5.558 Seiten in 4,4 s.

### `daily`

```text
stockout daily [--source QUELLE ...] [--db DB] [--out OUT] [--export-json DIR]
```

Abruf (wie `fetch`), Datenbank mit JSON-Export (Standard `<db-Ordner>/json`), Rückblick (`rueckblick.json`), Website, Protokolle. Ablauf und Fehlerverhalten: [ARCHITEKTUR.md](ARCHITEKTUR.md#4-kontrollfluss-des-tageslaufs-stockout-daily). Beobachtete Dauer am 10.11.2026: 06:18:39 bis 06:31:07 Uhr (gut 12 Minuten).

### `vorlauf`, `rueckblick`, `schaerfe`, `modell`

```text
stockout vorlauf    [--db DB] [--von JJJJ-MM-TT] [--bis JJJJ-MM-TT] [--json DATEI]   # Standard ab 2024-01-01
stockout rueckblick [--db DB] [--von JJJJ-MM-TT] [--bis JJJJ-MM-TT] [--json DATEI]   # Standard ab 2022-01-01
stockout schaerfe   [--db DB] [--json DATEI]
stockout modell     [--db DB] [--json DATEI] [--einfrieren]
```

Messungen auf der Datenbank (`rueckblick` und `modell` lesen auch das Archiv), Ausgabe als Text. Inhalt: [MODELL_UND_BEWERTUNG.md](MODELL_UND_BEWERTUNG.md). **`modell --einfrieren`** überschreibt `models/*.json` und `models/pruefplan.json` mit neuer sha256; danach schreibt der Tageslauf mit dem neuen Prüfplan. Ab 01.01.2027 verweigert der Code das Einfrieren. Vorher nur bewusst verwenden: Es ersetzt die veröffentlichten Modelle, danach stimmen `models/SHA256SUMS` und der Prüfplan-Hash `35a230a0a9bd` nicht mehr ([Vorab-Registrierung](MODELL_UND_BEWERTUNG.md#12-vorab-registrierung)).

### `bewertung`

```text
stockout bewertung [--db DB] [--von JJJJ-MM-TT] [--rueckblick] [--json DATEI]
```

Bewertet das Vorhersageprotokoll; Varianten und Kennzahlen in [MODELL_UND_BEWERTUNG.md](MODELL_UND_BEWERTUNG.md#11-bewertung-stockout-bewertung). Vor dem 26.02.2027 gibt es keine 8-Wochen-Fälle des Prüfplans. Für diese Dokumentation nicht ausgeführt.

### `protokoll`

```text
stockout protokoll [--db DB]
```

Schreibt das Merkmalsprotokoll des heutigen Tages (Wiener Zeit) und, mit eingefrorenem Prüfplan, das Vorhersageprotokoll; danach Kopie, falls eingestellt. Ausgabe z. B. in der Referenzinstanz am 10.11.2026: `Merkmalsprotokoll: … (8522 Produkte; Hinweise {…}; § 21 gemeldet 827)`.

### `preview`

```text
stockout preview --port PORT [--dir DIR]
```

Startet `http.server` nur auf `127.0.0.1` und dem angegebenen Port, z. B. `--port 8000`. Vorher prüfen, ob der Port frei ist (`ss -H -ltnup`). Kein Dauerbetrieb, keine öffentliche Freigabe. Beenden mit Strg+C.

## Zeitsteuerung (systemd)

| Timer | Zeit | Zufallsverzögerung | `Persistent` | Service-Befehl | Timeout |
|---|---|---|---|---|---|
| `stockout-archive.timer` | täglich 06:15 und 18:15 | bis 5 min | ja | `stockout daily` | 30 min |
| `stockout-nachholen.timer` | täglich 12:15 | bis 5 min | nein | `stockout fetch --nachholen` | 15 min |
| `stockout-eko.timer` | Mo–Fr 21:30 | bis 30 min | nein | `stockout fetch --eko` | 30 min |

Alle Services: `Type=oneshot`, `WorkingDirectory=%h/lieferengpass-radar`, `Nice=10`. `Persistent=true` beim Tageslauf holt einen verpassten Lauf nach dem Hochfahren nach.

**EKO:** Werktags liegen 06:15 und 18:15 außerhalb des RIS-Fensters (20–5 Uhr), deshalb gibt es den Abendlauf. Am Wochenende holen die beiden Tagesläufe EKO selbst, weil das RIS dann ganztägig erlaubt ist.

Beobachtet in der Referenzinstanz am 10.11.2026 (`systemctl --user list-timers 'stockout*'`): alle drei Timer aktiv; letzter Tageslauf 10.11. 06:18:39, letzter Nachholabruf 09.11. 12:17:50, letzter EKO-Lauf 09.11. 21:44:44.

## Meldungen, Alarme und Status

**Alarmregel beim Abruf** (`cli.cmd_fetch`): Ein gescheiterter Abruf ist

- **FEHLER**, wenn die Quelle `basg` ist, wenn sie noch nie erfolgreich war oder wenn ihr letzter Erfolg mehr als 36 Stunden zurückliegt (`status.STALE_HOURS`);
- sonst **WARNUNG** mit dem Alter des letzten Erfolgs, z. B. `WARNUNG ogyei: … (letzter Erfolg vor 12 h, FEHLER erst nach 36 h)`.

Als Erfolg zählt ein Live-Abruf, der die Formatprüfung bestanden hat. FEHLER entsteht außerdem bei einem gescheiterten EKO-Dokument, einem Fehler im CIMA-Register und einer gescheiterten Kopie. Jeder FEHLER führt zu Exit-Code 1, und die systemd-Unit gilt dann als `failed`. Eine WARNUNG allein lässt den Lauf erfolgreich enden.

**Benachrichtigung:** Der Code verschickt keine Nachrichten. Probleme sieht man über

- `systemctl --user --failed` und `systemctl --user status stockout-archive.service`,
- `journalctl --user -u stockout-archive.service` (bzw. `stockout-nachholen`, `stockout-eko`),
- `stockout status` (Exit-Code 2 bei Warnungen),
- den Hinweis „Daten möglicherweise veraltet“ auf der Website, wenn der letzte erfolgreiche BASG-Abruf älter als 36 Stunden ist.

**Warnungen von `stockout status`:** Quelle noch nie erfolgreich; letzter Erfolg älter als 36 h; Inhaltswarnungen in den letzten drei neuen Fassungen; fehlende BASG-Tage; bei eingestellter Kopie: Kopie nicht erreichbar oder Dateien fehlen in der Kopie, mit `--verify` abweichende Prüfsummen.

**Beobachtet in der Referenzinstanz am 10.11.2026** (`stockout --no-mirror status`, Exit-Code 0): Archiv 1.321 Dateien, 600,1 MB; alle Quellen mit Erfolg innerhalb von 36 Stunden; BASG-Tage seit 17.10.2026 lückenlos; „Warnungen: keine“.

## Zweite Kopie

Die Kopie ist optional und standardmäßig aus. Ist `STOCKOUT_MIRROR` bzw. `--mirror-dir` gesetzt, kopiert `mirror.mirror` nach jedem Abruf und nach jedem Protokoll alle fehlenden oder geänderten Archivdateien dorthin, zuletzt das Manifest. Kopiert wird über eine `.tmp`-Datei mit `fsync`. Ist zusätzlich `STOCKOUT_MIRROR_MOUNT` gesetzt und dieser Pfad kein Einhängepunkt, bricht die Kopie mit „Laufwerk … ist nicht eingehängt“ ab; der Befehl endet dann mit `FEHLER Kopie` und Exit-Code 1, und der nächste Lauf holt alles Fehlende nach. Die Datenbank und die Website werden nicht kopiert, sie lassen sich neu bauen. `stockout status --verify` vergleicht die Prüfsummen von Archiv und Kopie.

## Nachholen und Wiederherstellung

| Lage | Vorgehen |
|---|---|
| Rechner war beim Tageslauf aus | `stockout-archive.timer` hat `Persistent=true` und läuft nach dem Hochfahren nach. Nachhol- und EKO-Timer holen nichts nach. |
| Quelle mit Rhythmus „jeder Lauf“ scheiterte | Nachholabruf um 12:15 Uhr; sonst der nächste Tageslauf. |
| BASG-Tag fehlt | Das BASG zeigt nur den heutigen Stand; ein verpasster Tag ist dort verloren. Einzige Möglichkeit: eine Aufnahme im Internet Archive (`stockout import-legacy --wayback-only basg`, Netz). `stockout status` listet fehlende Tage. |
| EKO-Abendläufe verpasst | Der nächste Lauf nimmt alle Dokumente der letzten 90 Tage, die noch fehlen. |
| polnische Ausgabe verpasst | Der Tagesabruf holt nur die neueste Ausgabe; ältere über `stockout import-legacy --backfill pl_mz`. |
| Datenbank fehlt oder ist defekt | `stockout build` (deterministisch aus dem Archiv), dann `stockout build --export-json data/derived/json` bzw. der nächste Tageslauf. |
| Website fehlt | `stockout site` oder der nächste Tageslauf. |
| `rueckblick.json` fehlt | `stockout rueckblick --json data/derived/json/rueckblick.json`; ohne die Datei zeigt die Frühwarnliste keine Quoten der Registerhinweise. |
| Archiv beschädigt oder verloren | Es gibt keinen Wiederherstellungsbefehl. Aus der Kopie zurückkopieren, falls eine eingestellt ist (sie enthält Rohdateien, Protokolle und Manifest), danach `stockout build`. |
| Protokoll eines Tages fehlt | Lässt sich nicht nachträglich mit dem damaligen Wissensstand schreiben: `protokoll` schreibt immer den heutigen Tag. Für die prospektive Prüfung zählen Stichtage alle 14 Tage ab 01.01.2027 nur, wenn an genau diesem Tag ein Protokoll entstand. |

## Wenn eine Quelle Format oder Adresse ändert

1. **Erkennen:** Im Journal erscheinen `WARNUNG` bzw. nach 36 h `FEHLER <quelle>` mit `HTTP …`, `URLError …` oder `Formatprüfung: …` und dem Pfad der aufbewahrten Antwort („Antwort aufbewahrt: …“). `stockout status` zeigt Fehlversuche und nach 36 h eine Warnung. Ein Parser, der an einer *bestandenen* Datei scheitert, meldet sich nicht; Anzeichen sind ausbleibende neue Meldungen der Quelle (`foreign_items.last_seen`, `still_listed`).
2. **Ansehen:** aufbewahrte Antwort lesen, z. B. `zcat data/archive/<pfad>.gz | head`; Manifest-Einträge der Quelle in `data/archive/manifest.jsonl` prüfen.
3. **Adresse geändert:** URL in `archive.SOURCES` anpassen; bei Quellen mit eigener Abruffunktion auch dort (`_get_sukl_dlp`, `_get_pl_mz`, `_get_eudragmdp`). Beispiel: der SÚKL-Domainwechsel im Oktober 2026 ([DATENQUELLEN.md](DATENQUELLEN.md#tschechien-súkl)).
4. **Format geändert:** Parser anpassen (`foreign.parse_<quelle>`, `registers.parse_*`, `gmp.parse_*`, `eko.parse`, `asp.parse`, `basg.parse`). Alte Dateien bleiben im Archiv; der Parser muss deshalb **beide** Formate lesen, weil `build` alles neu einliest. Bei Bedarf Kennung (`expect`) oder Prüfregel in `archive._check` anpassen.
5. **Test** mit kleinem Beispiel in `tests/` ergänzen, dann `.venv/bin/python -m pytest -q`.
6. **Prüfen:** `stockout fetch --source <quelle>` (Netz), dann `stockout build` und Zeilenzahlen vergleichen.
7. **Prognoseprüfung beachten:** Änderungen an Auslandsquellen oder Parsern ändern die Eingaben der eingefrorenen Verfahren ([MODELL_UND_BEWERTUNG.md](MODELL_UND_BEWERTUNG.md#14-was-geprüft-ist-und-was-nicht)).

## Was der Betrieb bewusst nicht tut

- keine öffentliche Bereitstellung der Website (geplant);
- kein zweiter Abruf in der Cloud (geplant);
- keine Veröffentlichung von `data/`: Das Archiv enthält BfArM-Rohdaten ohne Zustimmung, die Datenbank die BASG-Telefonspalte.
