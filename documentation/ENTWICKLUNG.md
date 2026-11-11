# Entwicklung

**Stand:** 11.11.2026 · öffentliche Fassung 0.1

Dieses Dokument richtet sich an alle, die am Code weiterarbeiten: Aufbau des Repositorys, Tests, Konventionen, wie man eine Quelle oder ein Verfahren ergänzt, bekannte Grenzen und zurückgestellte Arbeit.

## Repository

```text
README.md, README.de.md           Einstieg auf Englisch und Deutsch
LICENSE                           Apache-2.0
pyproject.toml                    Paket stockout-at 0.1.0, Einstieg stockout = stockout_at.cli:main
src/stockout_at/                  Paket (Module siehe ARCHITEKTUR.md)
src/stockout_at/web/              Jinja2-Vorlagen und Assets der Website
tests/                            pytest-Tests (10 Dateien)
models/                           eingefrorene Z3-Verfahren, Prüfplan und SHA256SUMS
deploy/systemd/                   drei Timer mit Services
reports/                          Prüfbericht Z3 v0
documentation/                    diese Dokumentation
.github/workflows/ci.yml          CI: Tests mit Python 3.12
```

Nicht in Git (`.gitignore`): `data/` (Archiv, Datenbank, Protokolle), `site/`, `.venv/`, `.pytest_cache/`, `__pycache__/`, `*.egg-info/`.

**Historie:** Die öffentliche Fassung beginnt mit einem neuen ersten Commit; die frühere Entwicklungshistorie ist nicht enthalten. Wie das Projekt entstanden ist, steht in der [README](../README.md#how-it-was-built).

## Einrichtung

```bash
python3 -m venv .venv
.venv/bin/pip install -e '.[dev]'
```

Die editierbare Installation ist nötig, weil `modell.MODELS` den Ordner `models/` relativ zum Quellbaum sucht (`Path(__file__).resolve().parents[2] / "models"`). Für die polnische Liste braucht es zusätzlich `pdftotext` (poppler). Laufzeit und Pfade: [BETRIEB.md](BETRIEB.md).

## Tests

**Befehl und Ergebnis** (11.11.2026, öffentliche Fassung ohne `data/`, also wie in einem frischen Klon):

```text
$ .venv/bin/python -m pytest -q
....................................................................ssss [ 97%]
ss                                                                       [100%]
68 passed, 6 skipped in 0.75s
```

Die 6 übersprungenen Tests sind die Website-Tests, die eine echte Datenbank mit Auslands- und ASP-Daten brauchen. In der Referenzinstanz mit echter Datenbank liefen am 10.11.2026 alle Tests des damaligen Stands durch (72 bestanden). CI (`.github/workflows/ci.yml`) führt bei jedem Push und Pull Request `pip install -e ".[dev]"` und `pytest -q` mit Python 3.12 aus.

| Datei | Tests | Was geprüft wird |
|---|---:|---|
| `tests/test_archive.py` | 16 | Abruf mit Dubletten und Fehlversuchen, JSONL-Seiten, fehlendes `producedOn`, Wartungsseite (Wiederholung, nicht als Erfolg), EudraGMDP-Sitzung, Kennungen, 20-h-Sperre, Kopie und Prüfsummen, fehlendes Laufwerk, leere Einstellung bedeutet keine Kopie, fehlende BASG-Tage, EKO-Abendlauf, Nachholabruf, Alarmregel 36 h, keine Abrufe der Quellen, die nur die Referenzinstanz nutzt, User-Agent mit Kontakt nur bei gesetztem `STOCKOUT_CONTACT`, `import-legacy` ohne Datenpaket mit klarer Meldung |
| `tests/test_build.py` | 8 | Episodenregeln (Beginn, Verschiebung, Ende durch Status, Verschwinden als Intervall, abgeschnittene Schnappschüsse, Neumeldung, § 4 (1), Vorankündigung), Wirkstoff-Normalisierung, toleranter Parser, deterministischer Aufbau, überfällig |
| `tests/test_foreign.py` | 12 | Hilfsfunktionen, BfArM (PZN gruppiert, keine Kontaktspalten), Zusammenführen über Dateien, Ereignisprotokolle CZ/SK/SI, CIMA-JSONL, AIFA, konservative ATC-Ableitung, Vorlauf und Länderkombinationen, FDA |
| `tests/test_fruehwarnung.py` | 6 | Registerhinweise (Inhaberwechsel, andere Inhaber), Stufen, § 21-Erstsichtung, Konzernschlüssel, Hilfen von `schaerfe` |
| `tests/test_gmp_ansm.py` | 3 | ANSM-Zeilen, Wirkstoffname → alle ATC-Codes, CEP- und NCR-Zuordnung |
| `tests/test_modell.py` | 4 | Merkmale nur aus Daten vor dem Stichtag, Ridge-Fit, Einfrieren/Prüfplan/Protokoll als Rundlauf (inkl. Sperre ab 01.01.2027), Kennzahlen und Vorlauf |
| `tests/test_polen.py` | 3 | Tabellenzeilen aus PDF-Koordinaten, lateinische Wirkstoffnamen, Listungen über Ausgaben |
| `tests/test_registers.py` | 3 | SÚKL-DLP, CIMA-Antworten und Füllregel, Parser für archivierte Fimea-Registerdateien |
| `tests/test_rueckblick.py` | 12 | Ereignisfälle, Vergleich innerhalb von Schichten, Wellenstatus, MIA-Ereignisse, Marktaustritte, ASP FHIR = SVS, EKO-Parser und -Namensabgleich, EKO-Zeitfenster, 90-Tage-Regel, Verteilung des Nachladens, Wiederholung bei Serverfehler |
| `tests/test_site.py` | 7 | Kürzel; auf der echten Datenbank: Regionen je Seite, Links ohne externe Ressourcen, keine Telefonnummern, Überfällig und Suchindex, BfArM ausgeblendet, Registerhinweise |

**Aufbau:** Netzwerkzugriffe werden ersetzt, nicht ausgeführt: `fetch_source` und `fetch_all` nehmen `opener` und `sleep`, `eko.sync` nimmt `get`, `sleep`, `now`, `rand`, `legacy` und `registers` nehmen `get`. Archive entstehen in `tmp_path`; Beispieldaten stehen klein im Testcode (z. B. `BASG`, `opener_for` in `tests/test_archive.py`).

**Abhängigkeit von Echtdaten:** `tests/test_site.py` liest `data/derived/stockout.sqlite` und `data/archive/` und erwartet konkrete Seiten (`packung/2426051/`, `wirkstoff/zolpidem/`). Ohne Datenbank oder mit einer Datenbank ohne Auslands- und ASP-Daten (etwa nach dem BASG-Schnellstart) werden 6 der 7 Tests übersprungen. Ändern sich die Echtdaten stark, können diese Tests ohne Codeänderung scheitern.

**Zusätzlich geprüft** (10.11.2026, Referenzinstanz, eigener Arbeitsordner): `build` und `site` mit einem Archiv aus nur einer BASG-Datei laufen ohne Netz durch (844 Packungen, 1.133 Seiten).

**Lücken:** kein Test gegen die echten Quellen (Formate werden nur im Betrieb geprüft), kein Ende-zu-Ende-Test von `stockout daily`, keine Tests der systemd-Units, keine Tests von `bewertung` auf echten Protokollen, `schaerfe` und `rueckblick.measure` nur über Bausteine, im CI keine Website-Tests (keine Daten), keine Linter-Konfiguration.

## Konventionen

- **Sprache:** Oberfläche, Kommandozeilen-Meldungen, Dokumente und Commit-Betreffs auf Deutsch; Docstrings und Kommentare auf Englisch; Bezeichner gemischt (`fetch_all`, aber `merkmale`, `fruehwarnung`, `bewerten`).
- **Rohdaten zuerst:** Erst speichern, dann interpretieren. Parser sind tolerant; `basg.parse` wirft nie.
- **Deterministisch:** keine Laufzeit-Uhrzeiten in der Datenbank, gzip mit `mtime=0`, sortierte Ausgaben, sha256 für eingefrorene Dateien.
- **Atomar schreiben:** `.tmp` und `os.replace` bzw. Verzeichnistausch.
- **Testbar über Parameter:** Netz, Schlafen, Uhr und Zufall als Funktionsparameter.
- **Wenige Abhängigkeiten:** Standardbibliothek zuerst; Statistik in reinem Python (`modell.fit`, `schaerfe.logit`, `_bootstrap`), kein numpy, scikit-learn oder pandas.
- **Datenschutz:** keine Kontaktspalten in Auslandsmeldungen; `HIDDEN_FIELDS` und `HIDDEN_SOURCES` in `site.py`; keine Apotheken- oder Patientendaten.
- **Darstellung:** amtliche Felder wörtlich, eigene Auswertung gekennzeichnet, keine Therapie- oder Austauschempfehlung.
- **Eingefrorene Verfahren:** ab 01.01.2027 nichts mehr einfrieren oder ändern; eine neue Fassung bekommt einen neuen Namen und einen eigenen Prüfplan.
- **Arbeitsweise:** kleine Schritte, jeder mit Test; entwickelt mit KI-Coding-Agenten nach Spezifikation des Autors ([README](../README.md#how-it-was-built)).

## Eine neue Quelle ergänzen

1. **Bedingungen prüfen:** nur offizielle Downloads oder Schnittstellen, deren Nutzungsbedingungen und robots.txt den automatischen Abruf erlauben. Bedingungen und Lizenz als Kommentar bei der Quelle festhalten.
2. **Abruf:** `Source(name, url, ext, min_hours=…, expect=…)` in `archive.SOURCES` eintragen. Braucht der Abruf mehrere Schritte, eine Funktion `_get_<name>` schreiben und in `fetch_source` verzweigen. Für ein neues Format die Prüfung in `archive._check` ergänzen.
3. **Auslandsliste:** Parser `parse_<name>` in `foreign.py` (Meldungen über `_item`), Eintrag in `foreign.PARSERS` und `foreign.COUNTRY`; Ereignisprotokoll mit voller Historie → `FULL_HISTORY`; Liste ohne Daten → `DATELESS_LISTS`. Anzeige: `fruehwarnung.COUNTRY_NAMES`, `SOURCE_NAMES` (bei Bedarf `SOURCE_PAGES`), `site.FOREIGN_SOURCES` mit Nutzungshinweis. Nicht veröffentlichbar → `site.HIDDEN_SOURCES`.
4. **Produktregister:** Parser in `registers.PARSERS`, Zuordnung in `registers.FOR_SOURCE`, bei Teilantworten je Lauf `CUMULATIVE`.
5. **Zusatzsignal:** über `rueckblick._latest(archive, name)` lesen; zuerst als Schattenspalte in `merkmale.COLUMNS` protokollieren und mit einem Rückblicktest prüfen, bevor es irgendwo angezeigt wird.
6. **Tests** mit kleinem Beispiel und ersetztem `opener` (Muster `tests/test_archive.py`, `tests/test_foreign.py`).
7. **Vorgeschichte** (optional): `stockout import-legacy --wayback-only <name>` funktioniert für jede Quelle in `SOURCES`, deren Parser mindestens eine Meldung liest.
8. **Folgen für die Prüfung:** Eine neue Auslandsquelle ändert die Merkmale der eingefrorenen Verfahren ([MODELL_UND_BEWERTUNG.md](MODELL_UND_BEWERTUNG.md#14-was-geprüft-ist-und-was-nicht)). Die Referenzinstanz übernimmt solche Änderungen deshalb erst nach dem Go/No-Go am 30.04.2027.
9. **Dokumentation:** [DATENQUELLEN.md](DATENQUELLEN.md) ergänzen.

## Ein neues Verfahren ergänzen

Neues Verfahren in `modell.METHODS` eintragen (Art `logit`, `stufen` oder `mittel`; neue Merkmale in `FEATURES`). `stockout modell` misst es neben den anderen auf denselben Fällen. Einfrieren (`--einfrieren`) ist nur vor dem 01.01.2027 möglich und erzeugt einen neuen Prüfplan mit neuer sha256; danach zählen nur noch Protokollzeilen dieses Plans. Nach dem 01.01.2027 braucht ein neues Verfahren laut Prüfplan einen neuen Namen und einen eigenen Prüfplan. Der heutige Code unterstützt nur **einen** Prüfplan (`models/pruefplan.json`); mehrere parallele Pläne wären eine Codeänderung.

## Bekannte Grenzen und technische Schulden

**Betrieb**
- Keine Benachrichtigung bei Fehlern; man muss Journal, `systemctl --user --failed` oder `stockout status` ansehen.
- Ein einziger Rechner; kein zweiter Abruf in der Cloud. Verpasste BASG-Tage sind verloren.
- EKO und `cima_reg` fehlen in `stockout status`; ein EKO-Lauf ohne neues Dokument hinterlässt keinen Manifest-Eintrag.
- Parserfehler bei Auslands- und Registerdateien werden beim Aufbau still übersprungen.
- `pdftotext` ist eine Systemabhängigkeit außerhalb von `pyproject.toml`; fehlt es, bleibt Polen still leer.
- Pfade: Die systemd-Units erwarten den Projektordner unter `~/lieferengpass-radar`; `models/` wird relativ zum Quellbaum gesucht; alle übrigen Standardpfade gelten relativ zum Arbeitsverzeichnis.
- Abrufwege hängen an Details fremder Seiten: EudraGMDP über die Trefferzeile, SÚKL-DLP über Links auf der Katalogseite, Polen über Titel im ELI-Verzeichnis, SARI über eine versionierte URL.

**Daten und Methode**
- BASG-Vorgeschichte vor dem 17.10.2026 nur aus Einzelaufnahmen; Auslandslisten löschen beendete Meldungen; Verknüpfung über ATC 5 ist grob (siehe die Grenzen in [MODELL_UND_BEWERTUNG.md](MODELL_UND_BEWERTUNG.md#14-was-geprüft-ist-und-was-nicht)).
- Für die prospektive Prüfung muss an jedem Stichtag (alle 14 Tage ab 01.01.2027) ein Protokoll entstehen; ein fehlender Tag lässt sich nicht nachholen.
- Lernen und Bewerten zählen „neue Meldung“ leicht verschieden: beim Lernen der Beginn eines zusammengeführten Engpassintervalls (`Intervals.onset_within`), in der Bewertung Beginn oder erstes Sehen einer Meldung (`modell.report_days`), so wie es der Prüfplan festlegt.
- `sari_patient` wird archiviert, aber nicht gelesen.
- Die öffentliche Fassung ruft einige Quellen der Referenzinstanz nicht ab; Merkmale und Frühwarnstufen weichen deshalb ab ([DATENQUELLEN.md](DATENQUELLEN.md#4-unterschiede-zur-referenzinstanz)).

**Veröffentlichung**
- Website-Titel und systemd-Beschreibungen tragen noch den Arbeitstitel „Stockout Forecaster AT“; Impressum und Datenschutz haben Platzhalter.
- Ein eigenes `data/` darf nicht veröffentlicht werden: Die Datenbank enthält die BASG-Telefonspalte und das Archiv BfArM-Rohdaten.
- Die Website ist groß (in der Referenzinstanz 149 MB, eine Seite je Packung); für das Hosting zu bedenken.

**Code**
- Große Module (`foreign.py`, `rueckblick.py`, `modell.py`). `modell` nutzt private Hilfen aus `schaerfe`, `rueckblick` und `vorlauf` (`_solve`, `_latest`, `_signals` …).

## Zurückgestellte Arbeit (geplant, nicht umgesetzt)

- **Prognosen Z1 und Z2** (Termin hält ±7 Tage; Ende binnen 4/8/12 Wochen) mit Baselines und Validierungsbericht.
- **Anzeige einer Prognose** auf der Website, nur bei guter Kalibrierung und mit Unsicherheit.
- **Website:** öffentliche Bereitstellung, Rechtstexte ausfüllen.
- **Verbreitung:** wöchentlicher E-Mail-Überblick (`digest`), offene Datenexporte unter CC BY 4.0.
- **Ausfallsicherheit:** zweiter Abruf in der Cloud.
- **BfArM** auf der Website nach schriftlicher Zustimmung, ohne Kontaktspalten.
- **Quellen der Referenzinstanz** in der öffentlichen Fassung, sobald die Nutzung geklärt ist ([DATENQUELLEN.md](DATENQUELLEN.md#4-unterschiede-zur-referenzinstanz)).
- **Weitere Quellen:** Schweden, Norwegen, Portugal, Kroatien, Produktregister für SK und SI ([DATENQUELLEN.md](DATENQUELLEN.md#5-nicht-umgesetzte-quellen)).
- **Prospektive Bewertung** monatlich ab Februar 2027 und Bericht zum Go/No-Go am 30.04.2027 (Prüfplan); Gespräche mit der Zielgruppe.
