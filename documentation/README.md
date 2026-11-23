# Dokumentation: Lieferengpass-Radar

**Stand:** 11.11.2026 · öffentliche Fassung 0.1 · Einstieg auf Englisch: [README.md](../README.md), auf Deutsch: [README.de.md](../README.de.md)

Lieferengpass-Radar ist ein Frühwarnwerkzeug für Arzneimittel-Lieferengpässe in Österreich, gebaut nur aus öffentlichen Daten. Es archiviert täglich das amtliche Register der Vertriebseinschränkungen des BASG und die Engpasslisten weiterer Länder, baut daraus eine Datenbank mit Engpass-Episoden, schätzt für Wirkstoffe die Wahrscheinlichkeit einer baldigen BASG-Meldung, schreibt diese Schätzungen in ein tägliches Protokoll und erzeugt eine statische Website. Die Website läuft unter https://lieferengpass-radar.at und lässt sich auch lokal bauen.

## Wo was steht

| Dokument | Inhalt |
|---|---|
| [PROJECT_OVERVIEW.md](PROJECT_OVERVIEW.md) | schneller Einstieg: Zweck, Abläufe, Stand, Grenzen, Testergebnis, Diagramme |
| [ARCHITEKTUR.md](ARCHITEKTUR.md) | Komponenten, Modulkarte, Kontroll- und Datenfluss, Speicherorte, Datenbankschema, Fehlergrenzen |
| [DATENQUELLEN.md](DATENQUELLEN.md) | alle abgerufenen Quellen mit Format, Rhythmus, Parser, Nutzungshinweis und Sonderregeln; Unterschiede zur Referenzinstanz |
| [MODELL_UND_BEWERTUNG.md](MODELL_UND_BEWERTUNG.md) | Episoden, Verknüpfung, Vorlaufmessung, Stufen, Rückblicktests, Z3-Verfahren, Protokolle, Bewertung, Vorab-Registrierung, was geprüft ist |
| [BETRIEB.md](BETRIEB.md) | Installation, Konfiguration, Befehlsreferenz, Timer, Alarme, Kopie, Nachholen, Formatwechsel einer Quelle |
| [WEBSITE.md](WEBSITE.md) | Seiten, Inhalte, Darstellungsregeln, Datenschutz, Vorschau |
| [ENTWICKLUNG.md](ENTWICKLUNG.md) | Repository, Tests mit Ergebnis, Konventionen, neue Quelle oder neues Verfahren, Grenzen, zurückgestellte Arbeit |
| [Prüfbericht Z3 v0](../reports/Z3%20v0%20Pr%C3%BCfbericht.md) | rückblickende Prüfung des Modells vom 21.10.2026 |

## Namen

| Ebene | Name |
|---|---|
| GitHub-Repository | `lieferengpass-radar` (<https://github.com/benediktneumayer2-tech/lieferengpass-radar>) |
| Anzeigename | Lieferengpass-Radar |
| User-Agent beim Abruf | `LieferengpassRadar/0.1` ([DATENQUELLEN.md](DATENQUELLEN.md#2-gemeinsame-regeln-beim-abruf)) |
| Arbeitstitel im Code | „Stockout Forecaster AT“ (systemd-Beschreibungen); die Website heißt „Lieferengpass-Radar“ (`site.SITE_TITLE`) |
| Python-Distribution | `stockout-at` 0.1.0 (`pyproject.toml`) |
| Python-Paket | `stockout_at` (`src/stockout_at/`) |
| Kommandozeile | `stockout` (`.venv/bin/stockout`, Einstieg `stockout_at.cli:main`) |

Paket und Kommandozeile behalten die Namen aus der Arbeitsphase.

## Kennzeichnung in dieser Dokumentation

- **umgesetzt**: im Code vorhanden; mit Datei- oder Symbolangabe belegt.
- **geplant**: Ziel oder Vorschlag, im Code nicht vorhanden.
- **Referenzinstanz**: die Installation des Autors, die seit dem 17.10.2026 täglich läuft und die eingefrorenen Modelle, das Vorhersageprotokoll und die Bildschirmfotos erzeugt hat. Sie archiviert einige Quellen mehr als die öffentliche Fassung ([Unterschiede](DATENQUELLEN.md#4-unterschiede-zur-referenzinstanz)).
- **beobachtet**: aus Betrieb, Journal, Manifest oder Datenbank der Referenzinstanz, meist am 10.11.2026; kann sich ändern.
- **Rückblick**: Messung auf Vergangenheitsdaten mit zeitlicher Trennung, keine prospektive Prüfung.
- **abgeleitet**: aus dem Code geschlossen, nicht durch einen Lauf bestätigt.

## Lizenz

| Inhalt | Lizenz |
|---|---|
| Code | Apache-2.0 (`LICENSE`, `pyproject.toml`) |
| eigene Texte und abgeleitete Daten (Auswertungen) | CC BY 4.0 |
| Daten der Quellen | Bedingungen der jeweiligen Quelle ([DATENQUELLEN.md](DATENQUELLEN.md)) |

Die Fußzeile der Website sagt dasselbe: „Code: Apache-2.0 · Eigene Texte und Auswertungen: CC BY 4.0 · Daten der Quellen: nach deren Bedingungen“.

## Daten und Veröffentlichung

- Das Projekt nutzt ausschließlich öffentliche Daten, keine Daten von Apotheken, Großhändlern oder Patient:innen.
- `data/` und `site/` sind nicht in Git. Ein eigenes `data/` ist nicht zur Veröffentlichung bestimmt: Das Archiv enthält BfArM-Rohdaten, für deren Veröffentlichung keine schriftliche Zustimmung vorliegt, und die Datenbank übernimmt die BASG-Telefonspalte wörtlich.
- Der User-Agent nennt die Projektadresse; eine Kontaktadresse nur, wenn `STOCKOUT_CONTACT` gesetzt ist.

## Wie diese Dokumentation geprüft wurde

Die Beschreibungen stammen aus dem Quellcode, den Konfigurationsdateien und Beobachtungen in der Referenzinstanz ohne Schreibzugriff am 10.11.2026: `pytest`, `stockout --help` und die Hilfe aller Unterbefehle, `stockout status`, Abfragen mit `sqlite3 -readonly`, `systemctl --user list-timers 'stockout*'`, das Journal der drei Services und ein Probelauf von `build` und `site` mit einer einzelnen BASG-Datei in einem eigenen Arbeitsordner. Am 11.11.2026 wurde sie an den Code der öffentlichen Fassung angepasst; die Hashes in `models/` wurden dabei nachgerechnet ([Vorab-Registrierung](MODELL_UND_BEWERTUNG.md#12-vorab-registrierung)).
