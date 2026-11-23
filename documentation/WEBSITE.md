# Website

**Stand:** 23.11.2026 · öffentliche Fassung · Generator: `src/stockout_at/site.py` `generate`, Seitendaten in `src/stockout_at/seiten/`, Grafiken in `src/stockout_at/charts/`, Vorlagen in `src/stockout_at/web/templates/`

## Status

- Die Referenzinstanz läuft unter https://lieferengpass-radar.at. Jeder Tageslauf erzeugt die Website in den Ordner `site/` (nicht in Git).
- Der Anzeigename ist **Lieferengpass-Radar** (`site.SITE_TITLE`).
- Die Gestaltung folgt dem Agent-Unity-Look im Thema Mist, matt.
- Impressum und Datenschutzerklärung enthalten in dieser Fassung Platzhalter; die Referenzinstanz trägt die ausgefüllten Texte.
- Navigation: Die linke Leiste zeigt die App (Übersicht, Frühwarnung, Überfällig, Woche, Wirkstoffe A–Z) und darunter den einzelnen Punkt **Projekt**. Die Projektseiten sind nur über Reiter erreichbar.

## Seiten

| Pfad | Vorlage | Inhalt |
|---|---|---|
| `/` | `index.html` | App-Startseite: Suche, Lage am Stichtag, Grafik „Vorhersage gegen Meldung“ (F22), Kurzfassung der Frühwarnung, Veränderungen der letzten 7 Tage |
| `/projekt/` | `projekt.html` | Überblick in drei Schritten (Archivieren, Verknüpfen, Prüfen), Prüfstand |
| `/projekt/idee/` | `idee.html` | Problem, Aufbau, Archiv, Beispielpackung, Datenintegrität, Grenzen |
| `/projekt/modell/` | `modell.html` | Modell, Vergleich, Kalibrierung, Reihung, benannte Schwäche, Vorab-Registrierung |
| `/projekt/befunde/` | `befunde.html` | Ergebnisliste aller geprüften Ideen, auch der negativen und unklaren |
| `/projekt/ueber/` | `ueber.html` | Name, Wien, Repository |
| `/packung/<PZN>/` | `package.html` | amtlicher BASG-Eintrag wörtlich („Quelle: BASG, Stand …“), Zeitleiste als SVG mit Textfassung, eigene Auswertung je Episode (Beginn, Ende, Dauer, Verschiebungen), Link zum Wirkstoff, Meldungen im Ausland, Abschnitt „Prognose“ mit „Noch keine Prognose“ |
| `/wirkstoff/<slug>/` | `substance.html` | gemeldete Packungen des Wirkstoffs, nicht gemeldete gleichwertige Packungen laut ASP-Liste, Meldungen im Ausland, Hinweis „keine Austauschempfehlung“ |
| `/wirkstoffe/` | `substances.html` | Wirkstoffe A–Z |
| `/ueberfaellig/` | `overdue.html` | aktive Meldungen, deren angekündigter Termin vor dem Stichtag liegt |
| `/woche/` | `week.html` | neue und beendete Meldungen der letzten 7 Tage |
| `/fruehwarnung/` | `fruehwarnung.html` | Frühwarnliste (Stufen A/B/C mit bisheriger Trefferquote), Hinweise aus den BASG-Registern (anderer Inhaber gemeldet; die Änderung beim Zulassungsinhaber ist ausgeblendet, `site.SITE_HOLDER_CHANGES`, [Unterschiede](DATENQUELLEN.md#4-unterschiede-zur-referenzinstanz)), Lesehilfe |
| `/methodik/` | `method.html` | Methodik, Archivabdeckung je Quelle, Frühwarnung, Quellen und Lizenzen der Auslandslisten (`site.FOREIGN_SOURCES`); beschreibt nur die Quellen, die die öffentliche Fassung abruft |
| `/impressum/`, `/datenschutz/` | `impressum.html`, `datenschutz.html` | Rechtstexte |
| `/search-index.json` | – | Suchindex für die clientseitige Suche |
| `/assets/` | `web/assets/` | `style.css`, `search.js` |

Packungen ohne PZN (alte Dateien) bekommen den Pfad `packung/z-<hash>/` (`site.package_slug`). Wirkstoff-Pfade sind ASCII-Kürzel des normalisierten Namens (`site.substance_slug`).

## Woher die Inhalte kommen

- Lage, überfällige Termine, Woche, gleichwertige Packungen: `metrics.collect` ([MODELL_UND_BEWERTUNG.md](MODELL_UND_BEWERTUNG.md#2-engpass-episoden-basg)).
- Zeitleisten: `timeline.timeline_svg` (880 px und 300 px breit) und `timeline.events` als Textfassung. Nicht beobachtete Zeiträume (vor dem ersten Sehen, Ende zwischen zwei Schnappschüssen) sind schraffiert.
- Frühwarnliste und Registerhinweise: `fruehwarnung.build` mit Quoten aus `vorlauf.measure` und `data/derived/json/rueckblick.json` ([MODELL_UND_BEWERTUNG.md](MODELL_UND_BEWERTUNG.md#5-frühwarnliste-und-registerhinweise)).
- Archivabdeckung auf der Methodikseite: `status.collect` ohne Kopie.

## Regeln der Darstellung (umgesetzt)

- **Amtlich und eigen getrennt:** amtliche BASG-Felder wörtlich mit Quelle und Stand; abgeleitete Werte mit dem Kennzeichen „Eigene Auswertung“ (`_macros.html` `own()`).
- **Ausgeblendet:** das BASG-Feld `Zulassungsinhaber_Tel` (`site.HIDDEN_FIELDS`, Test `test_no_phone_numbers`) und alle BfArM-Meldungen (`site.HIDDEN_SOURCES`, Test `test_early_warning_hides_bfarm_and_lists_only_unreported`). Nur auf der Website blendet `site.SITE_HIDDEN_SOURCES` außerdem `fimea` aus, für den Fall archivierter finnischer Dateien, die die öffentliche Fassung nicht abruft; Merkmals- und Vorhersageprotokoll nutzen weiter `site.HIDDEN_SOURCES`.
- **Keine Vorhersage für einzelne Wirkstoffe:** Die Z3-Wahrscheinlichkeiten je Wirkstoff stehen nur in den Protokollen. Die Website zeigt sie nur gebündelt in Klassen und Rangbändern.
- **Nüchterne Sprache:** Die Frühwarnliste heißt ausdrücklich „Hinweis … Keine Prognose, keine Bestellempfehlung“.
- **Veraltete Daten:** Liegt der letzte erfolgreiche BASG-Abruf beim Erzeugen mehr als 36 Stunden zurück, erscheint ein Hinweis. Ein kleines Skript in `base.html` prüft dasselbe beim Lesen im Browser.
- **Fußzeile:** Stand der BASG-Liste (`producedOn`), Stichtag, Erzeugungszeit, letzter erfolgreicher BASG-Abruf, Quellen, Haftungshinweis und die Lizenzen: „Code: Apache-2.0 · Eigene Texte und Auswertungen: CC BY 4.0 · Daten der Quellen: nach deren Bedingungen“ ([Lizenz](README.md#lizenz)).

## Festgeschriebene Darstellung der Startgrafik

Festgelegt am 23.11.2026, vor Beginn der prospektiven Prüfung. Bis zum Bericht zum Go/No-Go am 30.04.2027 ändert sich daran nichts:

- **Horizont:** 8 Wochen, Modell `z3_v0`.
- **Klassen der Vorhersage:** unter 1 %, 1–2 %, 2–4 %, 4–8 %, 8–16 %, ab 16 %, untere Grenze eingeschlossen.
- **Phasen nach dem Tag der Vorhersage, nie zusammengerechnet:** Rückblick 2026 (simuliert), Einlaufphase 21.10.–31.12.2026 (jeder Protokolltag), Prüfung ab 01.01.2027 (nur die Stichtage des Prüfplans, im Kalibrierungsfeld dieselben Fälle wie `modell.bewerten`).
- **95-%-Bereich:** über Wirkstoffe geclustert, auf der Logit-Skala, ohne Zufallszahlen (`live.py`).
- **Zusammenlegen:** Ein Punkt braucht mindestens 30 Wirkstoffe. Kleinere Randklassen werden mit der Nachbarklasse zur Mitte hin zusammengelegt, nie weggelassen.
- **Kein Urteil vor dem 30.04.2027**, kein Vergleich mit der Stufenregel auf der Startseite. Die Grafik bleibt auch stehen, wenn sie schlecht aussieht.

## Datenschutz und Technik

- Statisches HTML, keine Cookies, kein Tracking, keine Analysewerkzeuge, keine Anfragen an Dritte; Schriften, Skripte und Grafiken kommen von der eigenen Seite (Datenschutzseite; Test `test_links_resolve_and_no_external_assets`).
- Die Suche (`search.js`) lädt `search-index.json` und sucht im Browser über Produktname, Wirkstoff und PZN; ohne JavaScript führt das Formular zur A–Z-Liste.
- Alle Links sind relativ; die Website funktioniert unter jedem Pfad.
- Aufbau in ein Temporärverzeichnis neben `site/`, danach Austausch; ein gescheiterter Lauf hinterlässt keine halbe Website.

## Lokal ansehen

`stockout preview --port 8000` (nur `127.0.0.1`), siehe [BETRIEB.md](BETRIEB.md#preview). Alternativ `site/index.html` direkt im Browser öffnen; die Suche braucht dann je nach Browser einen Webserver, weil sie `search-index.json` per `fetch` lädt (nicht geprüft).

## Tests

`tests/test_site.py` erzeugt die Website aus der echten Datenbank `data/derived/stockout.sqlite` mit Stichtag 17.10.2026 in ein Temporärverzeichnis und prüft: feste Regionen je Seite, Projektseiten nur über Reiter, auflösbare Links ohne externe Ressourcen, keine Telefonnummern, überfällige Zeilen und Suchindex, BfArM ausgeblendet, Registerhinweise. `tests/test_charts.py` und `tests/test_seite_u*.py` prüfen die Grafiken und Seitendaten. Fehlt die Datenbank oder enthält sie keine Auslands- oder ASP-Daten (etwa nach dem BASG-Schnellstart), werden die betroffenen Tests übersprungen.

## Noch offen (geplant)

Anzeige einer Prognose je Wirkstoff nach bestandener Prüfung, wöchentlicher E-Mail-Überblick, offene Datenexporte. BfArM-Einträge erst nach schriftlicher Zustimmung und ohne Kontaktspalten.
