# Modell und Bewertung

**Stand:** 11.11.2026 · öffentliche Fassung 0.1 · Eingefrorene Verfahren: `models/` (Prüfplan sha256 `35a230a0a9bd…`, eingefroren am 21.10.2026; [Vorab-Registrierung](#12-vorab-registrierung))

Dieses Dokument beschreibt, was aus den Rohdaten abgeleitet wird (Episoden, Verknüpfung, Stufen), welche Messungen es gibt, wie die Z3-Verfahren gebaut und eingefroren sind, wie das Vorhersageprotokoll aussieht und wie es bewertet wird. Am Ende steht, was geprüft ist und was nicht.

> **Wichtig:** Alle Zahlen zur Güte in diesem Dokument sind **Rückblicke** (zeitlich getrennt gelernt und geprüft, aber auf Vergangenheitsdaten) und stammen aus der Referenzinstanz ([Unterschiede zur öffentlichen Fassung](DATENQUELLEN.md#4-unterschiede-zur-referenzinstanz)). Die **prospektive Prüfung beginnt erst am 01.01.2027**. Keine Vorhersage wird auf der Website gezeigt.

## 1. Begriffe

| Begriff | Bedeutung im Code |
|---|---|
| Packung | BASG-Eintrag, identifiziert über die PZN; in alten Dateien ohne PZN über Zulassungsnummer und Packungsangaben (`basg.package_key`) |
| Produkt | Zulassungsnummer (mehrere Packungen) |
| Wirkstoff | für Prognosen: **ATC Ebene 5**; für die Website zusätzlich der normalisierte Wirkstoffname (`substances.normalise`) |
| Stichtag | Tag, an dem eine Vorhersage oder ein Fall gilt; in Lernen und Bewertung alle 14 Tage |
| Neue Meldung (Onset) | Beginn eines zusammengeführten österreichischen Engpassintervalls eines Wirkstoffs (`vorlauf.Intervals`) |
| Horizonte | 28, 56 und 84 Tage (4, 8, 12 Wochen; `vorlauf.HORIZONS`) |

## 2. Engpass-Episoden (BASG)

`episodes.derive` bildet aus der zeitlich sortierten Folge der BASG-Schnappschüsse Episoden je Packung. Die Regeln (Docstring von `episodes.py`, getestet in `tests/test_build.py`):

- **Beginn:** `Beginn_Vertriebseinschraenkung`, sonst `Datum_Meldung`, sonst das erste Sehen im Archiv (`start_source` = `beginn`, `meldung`, `first_seen`). Ein Beginn, der nicht nach dem Ende der vorigen Episode derselben Packung liegt, fällt auf das erste Sehen zurück.
- **Ende:** erster Schnappschuss im Status „verfügbar“ (`end_reason = status`), Verschwinden aus einem *vollständigen* Schnappschuss (`disappeared`, Ende als Intervall zwischen letztem Sehen und erstem Fehlen) oder eine neuere Meldung derselben Packung (`rereported`). Abgeschnittene Schnappschüsse belegen nur Anwesenheit, nie Fehlen.
- **„verfügbar gemäß §4 (1)“ beendet keine Episode**: Das BASG listet solche Packungen selbst, weil der Bedarf nicht gedeckt ist (§ 4 Abs. 1 der Verordnung BGBl. II Nr. 30/2020).
- Zeilen „verfügbar“ ohne Beginn am Anfang einer Listung eröffnen nichts (Vorankündigungen oder ungesehene Engpässe zwischen seltenen Schnappschüssen).
- **Verschiebung:** jede Änderung des angekündigten Wiederbelieferungstermins.
- **Qualität:** `history_quality = daily`, wenn Beginn und Ende aus täglichen Daten stammen, sonst `sparse`; `end_interval_censored = 1`, wenn das Ende nur als Intervall von mehr als einem Tag bekannt ist.

Stand 10.11.2026: 5.503 Episoden, davon 658 aktiv und 98 mit täglicher Qualität; Endgründe: 4.017 `disappeared`, 519 `status`, 309 `rereported`.

**Abgeleitete Kennzahlen** (`metrics.py`, als JSON in `data/derived/json/` und auf der Website):
- **Lage:** Packungen der neuesten Datei nach Status; „aktiv“ heißt Status „Nicht verfügbar“ oder „eingeschränkt verfügbar“ (`metrics.RESTRICTED`). Am 10.11.2026: 844 Packungen gemeldet, 612 aktiv.
- **Überfällig:** aktive Packung, deren angekündigter Termin vor dem Stichtag liegt; angezeigt mit Tagen seit dem Termin. Am 10.11.2026: 57.
- **Woche:** Episoden mit Beginn bzw. Ende in den letzten 7 Tagen.
- **Dauern:** Verteilung beendeter Episoden; intervallzensierte werden nach der Intervallmitte eingeteilt.
- **Gleichwertige Packungen:** gleiche normalisierte Wirkstoffe, Stärke und Darreichungsform laut ASP-Liste (`asp.concept_row`, `equiv_key`); ausdrücklich keine Austauschempfehlung.

## 3. Auslandsmeldungen und Verknüpfung mit Österreich

**Einheitliche Meldung** (`foreign_items`): Quelle, Land, Meldungs-ID, Produkt, Wirkstoffe, ATC 5 und Herkunft des ATC-Codes, Stärke, Form, Inhaber, Signaldatum, Beginn, erwartetes Ende, Ende, Grund, Status, erstes und letztes Sehen im Archiv, Zahl der Dateien, `still_listed` (in der neuesten Datei), nationale Codes.

- **Zusammenführen** (`foreign.aggregate`): Eine Meldung wird über alle archivierten Dateien ihrer Quelle verfolgt. So bleiben Meldungen erhalten, die die Behörde später löscht.
- **Ereignisprotokolle** (CZ, SK, SI; `foreign._cases`): Unterbrechung eröffnet einen Fall, Wiederaufnahme oder Ende schließt ihn; eine dauerhafte Einstellung ist ein eigener Fall mit Status `einstellung` und zählt nie als Signal.
- **Signaldatum:** die erste Veröffentlichung, wo die Quelle sie nennt (BfArM, EMA, CZ, SI, BE, SK), sonst der Beginn (IT, HU, ES); bei Polen die erste Ausgabe einer ununterbrochenen Listung; bei AIFA das frühere von Beginn und Listendatum (angekündigte künftige Engpässe sind ab dem Listendatum öffentlich).
- **Lücken füllen** (`registers.fill`): Produktregister ergänzen nur leere Felder (CZ Inhaber/ATC, FI Produkt/ATC/Inhaber, ES ATC/Inhaber/Wirkstoffe).
- **ATC ableiten** (`foreign.derive_atc`), wenn die Quelle keinen ATC-Code hat: über den Wirkstoffnamen (sprachtoleranter Schlüssel `foreign.skeleton`), die ersten Wörter des Produktnamens oder einen Handelsnamen aus der ASP-Liste. Es zählt nur ein eindeutiger ATC-Code; Kombinationen bekommen keinen ATC aus dem Produktnamen. `atc_method` hält die Herkunft fest (`quelle`, `register`, `wirkstoff`, `wirkstoff_wort`, `produktname`, `handelsname`).
- **Verknüpfung** (`foreign.link`): Jede *laufende* Meldung (in der neuesten Datei, keine Einstellung, kein Ende) wird mit allen gültigen österreichischen ASP-Packungen gleichen ATC 5 verbunden. Jede Verbindung sagt, ob eine Stärke übereinstimmt (`strength_match`) und ob der Zulassungsinhaber derselbe Konzern ist (`holder_match`, über `foreign.holder_key` und die Konzerntabelle `foreign.GROUPS`, z. B. Hexal/1 A Pharma → Sandoz, ratiopharm/Actavis → Teva).

## 4. Vorlaufmessung (`stockout vorlauf`)

`vorlauf.measure` prüft deterministisch auf der Datenbank, ob Auslandsmeldungen österreichischen Meldungen vorausgehen. Einheit ist der Wirkstoff (ATC 5). Standardzeitraum: 01.01.2024 bis zum letzten Schnappschuss.

- **Vorausgehen:** Für jede neue österreichische Meldung im Zeitraum: Gab es im Jahr davor eine Auslandsmeldung zum selben ATC 5, und wie viele Tage früher (Median, Quartile, Verteilung)? Gegenprobe: nur danach im Ausland. Dasselbe auf Ebene Wirkstoff + Inhaber.
- **Trefferquote:** Nach einem Auslandssignal auf einen in Österreich nicht gemeldeten Wirkstoff: Wie oft folgt binnen 4, 8, 12 Wochen eine BASG-Meldung? Verglichen mit der **Grundrate** aller vermarkteten Wirkstoffe an Stichtagen alle 14 Tage und mit Wirkstoffen, die schon einmal knapp waren (Lift). 95-%-Intervalle nach Wilson.
- **Mehrere Länder:** Quoten nach Zahl und Kombination der Länder mit laufender Meldung, Zusatznutzen je Land und **Hinweisstufen** (`vorlauf.tier`): **A** = 5 oder mehr Länder, **B** = 3–4, **C** = 2, „1“ = ein Land.
- Die Messung nennt ihre Grenzen selbst (`grenzen` im Ergebnis): Auslandslisten löschen beendete Meldungen, die BASG-Vorgeschichte vor dem 17.10.2026 besteht aus Einzelaufnahmen, die Verknüpfung über ATC 5 ist grob, Fälle desselben Wirkstoffs sind nicht unabhängig.

Gemessene Zusatzwerte einzelner Länder (Rückblick der Referenzinstanz, 19./20.10.2026, ohne BfArM, 8 Wochen): Frankreich 12,3 %, bei 3+ Ländern mit FR 15,8 % gegenüber 12,4 % ohne; Finnland bei 3+ Ländern mit FI 19,9 % gegenüber 7,4 % ohne; Polen 7,4 % aus 54 Fällen, bei 3+ Ländern mit PL 16,1 % gegenüber 12,3 % ohne. Finnland fehlt in der öffentlichen Fassung ([Unterschiede](DATENQUELLEN.md#4-unterschiede-zur-referenzinstanz)).

## 5. Frühwarnliste und Registerhinweise

`fruehwarnung.build` erzeugt die Liste der Website (Darstellung in [WEBSITE.md](WEBSITE.md)):

- **Kandidaten:** Wirkstoffe (ATC 5) mit mindestens einer lieferbaren ASP-Packung und ohne aktive BASG-Meldung, zu denen laufende Auslandsmeldungen existieren (ohne die Quellen in `site.HIDDEN_SOURCES`, also ohne BfArM).
- **Stufe** nach Zahl der Länder (A/B/C wie oben). Ein Land allein wird nicht gelistet. Derselbe Inhaber im Ausland wird angezeigt, bestimmt die Stufe aber nicht (Ergebnis von `schaerfe`, Abschnitt 6).
- **Trefferquote je Stufe:** aus `vorlauf.measure` ohne BfArM, bei jedem Website-Aufbau neu berechnet.
- **Registerhinweise:** (a) lieferbares Produkt nach einer Änderung beim Zulassungsinhaber in den letzten 56 Tagen (MIA-Verlautbarungen; entfällt in der öffentlichen Fassung ohne archivierte Verlautbarungen und ist auf der Website ausgeblendet, `site.SITE_HOLDER_CHANGES`, [Unterschiede](DATENQUELLEN.md#4-unterschiede-zur-referenzinstanz)), Wirkstoff nicht gemeldet; (b) gemeldeter Wirkstoff mit noch lieferbaren Produkten anderer Inhaber. Ihre Quoten kommen aus `rueckblick.json`.

**Beobachtet auf der am 10.11.2026 erzeugten Website der Referenzinstanz** (Rückblick 01.01.2024 bis 10.11.2026): Stufe A 96 Wirkstoffe, BASG-Meldung binnen 8 Wochen bisher 18,4 % [15,5–21,7 %]; Stufe B 181, 10,7 %; Stufe C 173, 8,1 %; Vergleich (Wirkstoffe mit früherem Engpass, ohne Auslandsblick) 6,8 %. 269 Wirkstoffe mit nur einem meldenden Land (4,1 %) sind nicht gelistet. Diese Zahlen ändern sich täglich.

## 6. Schärfung der Stufen (`stockout schaerfe`)

`schaerfe.measure` lernt mögliche Verfeinerungen auf 2024–2025 und prüft sie auf 2026, jeweils gegen die Stufe desselben Falls (Bootstrap über ganze Wirkstoffe, 500 Ziehungen). Ergebnis des Laufs vom 20.10.2026:

- **Fünf oder mehr Länder** schlagen die frühere Stufe A („gleicher Inhaber in 3+ Ländern“): 2026 41 statt 25 spätere BASG-Meldungen (+16 [+2 bis +32]) bei ähnlicher Quote (17,7 % gegenüber 16,1 %). Deshalb übernommen.
- Ländergewichte verbessern die Reihung nicht (AUC −0,017 [−0,044 bis +0,008]).
- Grund der Auslandsmeldung (Herstellung, Nachfrage, Logistik, kommerziell), Stärke und Darreichungsform: kein Gewinn gegenüber der Stufe.

## 7. Rückblicktests weiterer Signale (`stockout rueckblick`)

`rueckblick.measure` (Standardzeitraum ab 01.01.2022) vergleicht für Wirkstoffe ohne aktive Meldung den Anteil der Fälle mit einer neuen BASG-Meldung binnen 4/8/12 Wochen mit einer Vergleichsgruppe. „Bereinigt“ heißt: beobachtete durch erwartete Treffer, erwartet aus Wirkstoffen gleicher Produktzahl, gleicher Engpass-Vorgeschichte und gleichen Jahres (SIR, Intervall nach Byar). Ergebnisse der Läufe vom 19./20.10.2026:

| Test | Signal | Ergebnis (8 Wochen, bereinigt, sofern nicht anders genannt) | Verwendung |
|---|---|---|---|
| T1 | Änderung beim Zulassungsinhaber (MIA) | ≈2× für das betroffene Produkt (2,08× [1,41–2,96]); nur andere Produkte 1,10× | Registerhinweis auf der Website, Merkmal in Z3 |
| T1 | Zulassung auf Antrag aufgehoben; Standort gestrichen | 1,41× [1,00–1,94], bei vermarkteten Produkten 1 von 40, also kein Frühsignal; Standort 0,99× | – |
| T2 | Preisband-Runden 2017–2025 | keine Häufung | – |
| T4 | Infektionswelle (ERVISS-ILI, SARI) | hohe ILI-Wochen 7,5× für Mehrbedarf-Meldungen (4 Wochen), aber nur durch die Saison 2022/23; SARI ab 2023 ohne Effekt | – |
| T6 | Engpass bei einem ATC-4-Nachbarn | in AT 1,08× [1,03–1,12], im Ausland 0,67× | – |
| T6b | anderer Inhaber desselben Wirkstoffs gemeldet | 1,69× [1,62–1,75] | Registerhinweis auf der Website |
| T7 | GMP: EDQM-Aussetzung bzw. EudraGMDP-Bericht | 22 bzw. 58 Fälle; nach 12 Wochen 2,1× [0,7–5,0] bzw. 1,8× [0,95–3,2]; nicht belastbar | nur Merkmalsprotokoll |
| T8 | Marktaustritt eines anderen Produkts (ASP-Historie) | 1,18× [0,82–1,66] | Merkmal in Z3, Merkmalsprotokoll |
| T9 | EKO-Streichung (Grüner/Gelber Bereich) | 269 Änderungen 2004–2026; 1,27× [0,77–1,99]; keine Häufung nach Preisband-Runden | Merkmal in Z3, Merkmalsprotokoll |

Die Nummern T3 und T5 fehlen, weil sie nicht als eigene Tests im Code stehen; nach Lage des Codes entsprechen sie der Länderbreite mit FR und PL in `vorlauf` bzw. der Aufteilung von T7 nach Zahl gültiger CEP-Halter (Zuordnung abgeleitet).

## 8. Merkmalsprotokoll (täglich)

`merkmale.run` schreibt seit 19.10.2026 bei jedem Tageslauf `<Archiv>/protokoll/merkmale/<Jahr>/<Tag>.csv.gz` (UTF-8, gzip). Eine Zeile je Produkt (Zulassungsnummer) der ASP-Liste; am 10.11.2026 waren es 8.522. Ein späterer Lauf am selben Tag ersetzt die Datei. Das Protokoll hält fest, was an diesem Tag bekannt war und was die Liste zeigte; es ist Datengrundlage für spätere Modelle. Gelesen wird es nur für das erste Sehen der § 21-Meldung.

| Spalten | Inhalt |
|---|---|
| `datum`, `basg_stand` | Kalendertag (Wien) und BASG-Stand |
| `zulassungsnummer`, `name`, `atc5`, `inhaber`, `packungen`, `lieferbar` | Produkt laut ASP-Liste |
| `basg_produkt_aktiv`, `basg_wirkstoff_aktiv`, `basg_wirkstoff_frueher` | BASG-Status von Produkt und Wirkstoff |
| `ausland_laender`, `ausland_gleicher_inhaber`, `ausland_stufe` | Länder mit laufender Meldung (alle Quellen, auch BfArM), Länder mit demselben Inhaber, Stufe |
| `inhaberwechsel_am`, `inhaberwechsel_gleiche_firma`, `anderer_inhaber_gemeldet` | Registerereignisse |
| `hinweis` | was die Website zeigte (ohne BfArM): `A`/`B`/`C`, `inhaberwechsel`, `anderer_inhaber`, mit `+` verbunden |
| `vertrieb_eingestellt_gemeldet`, `vertrieb_eingestellt_seit` | Schattenmerkmal § 21 AMG und Tag des ersten Sehens |
| `cep_halter_gueltig`, `cep_gmp_aussetzung_am`, `gmp_ncr_am` | Schattenmerkmale GMP je Wirkstoff |
| `marktaustritt_anderes_produkt_am`, `eko_streichung_anderes_produkt_am` | Schattenmerkmale T8 und T9 |
| `z3_fassung`, `z3_p4`, `z3_p8`, `z3_p12` | Wahrscheinlichkeiten von `z3_v0` für den Wirkstoff; leer bei aktiver Meldung |

Ohne die zusätzlichen Quellen der Referenzinstanz bleiben `inhaberwechsel_*`, `vertrieb_eingestellt_*` und die `cep_*`-Spalten leer ([Unterschiede](DATENQUELLEN.md#4-unterschiede-zur-referenzinstanz)).

## 9. Z3-Verfahren

**Frage:** Wie wahrscheinlich bekommt ein Wirkstoff (ATC 5), der laut ASP-Liste lieferbar ist und keine aktive BASG-Meldung hat, binnen 4, 8 oder 12 Wochen eine neue BASG-Meldung?

**Fall:** Wirkstoff an einem Stichtag. Zum Universum gehört ein Wirkstoff, wenn er in der ASP-Fassung *vor* dem Stichtag mindestens ein lieferbares Produkt hat und am Stichtag keine aktive Meldung (`modell.Knowledge.marketed`, `features`).

**Zeitpunktgenau (Schalter seit 16.11.2026, Standard aus = wie eingefroren):** `Knowledge(..., zeitpunktgenau=True)`, `stockout modell --zeitpunktgenau` und `stockout bewertung --rueckblick --zeitpunktgenau`. Eine BASG-Meldung gilt erst ab ihrer Veröffentlichung als bekannt (`modell.published`: im täglichen Archiv die erste Sichtung, in den Lücken davor eine Schätzung). Das gilt für die Fallauswahl, die Vorgeschichte und das Ziel; das Ziel zählt wie im Prüfplan, wenn eine Meldung in (t, t+h] beginnt oder erstmals erscheint. Die ASP-Fassung zählt erst ab dem Tag ihrer ersten Erfassung (`AspHistory.known_before`; die Fassung vom 22.10.2026 kam am 30.10.2026). Der tägliche Pfad nutzt den Schalter nicht: Am Tag selbst kennt die Datenbank ohnehin nur Veröffentlichtes und schon Erfasstes. Fälle, Ziele und Vorgeschichte stimmen auf dem 14-Tage-Raster 2024–2026 mit dem Panel der Modellsuche vom November 2026 überein (nicht Teil der öffentlichen Fassung; geprüft am 16.11.2026); abweichen können nur Tage mit spät erfasster ASP-Fassung, weil das Panel sie nach Datum wählt.

**Merkmale** (`modell.FEATURES`, alle binär, nur aus Daten vor dem Stichtag; Test `test_features_only_before_the_day`):

| Gruppe | Merkmale |
|---|---|
| Ausland (`FOREIGN`) | Zahl der Länder mit laufender Meldung (`laender_1`, `laender_2`, `laender_3_4`, `laender_5plus`); derselbe österreichische Inhaber im Ausland in 1+ bzw. 3+ Ländern (`inhaber_1plus`, `inhaber_3plus`); neue Auslandsmeldung in den letzten 28 Tagen (`ausland_neu_28`) |
| Vorgeschichte AT | früherer Engpass, einer im letzten Jahr, einer endete in den letzten 90 Tagen (`frueher_engpass`, `engpass_365`, `ende_90`) |
| Markt | 1, 2–3 oder 10+ lieferbare Produkte (`groesse_1`, `groesse_2_3`, `groesse_10plus`) |
| Register | in den letzten 56 Tagen: Änderung beim Inhaber, Marktaustritt bzw. EKO-Streichung eines anderen Produkts (`inhaberwechsel_56`, in der öffentlichen Fassung immer 0; `marktaustritt_56`, `eko_56`) |
| Sonst | ATC-Hauptgruppe (14 Gruppen), Quartal |

**Verfahren** (`modell.METHODS`; Dateien in `models/`):

| Verfahren | Art | Rolle |
|---|---|---|
| `z3_v0` | regularisierte logistische Regression (Ridge), ohne BfArM | **Hauptmodell** |
| `z3_v0_ohne_ausland` | dasselbe ohne die Auslandsmerkmale | Diagnose: bringt das Ausland etwas? |
| `z3_v0_mit_de` | dasselbe mit BfArM-Meldungen | Herausforderer, **nur intern** |
| `stufen_v0` | Trefferquote je Stufe der Frühwarnliste (`-`, `1`, `C`, `B`, `A`) | **Vergleich** im Hauptvergleich |
| `mittel_v0` | Mittel der Wahrscheinlichkeiten von `z3_v0`, `z3_v0_mit_de`, `stufen_v0` | Herausforderer |

**Lernen** (`modell.measure`, `learn_methods`): Stichtage alle 14 Tage ab 01.01.2024. Gelernt wird auf 2024–2025, geprüft auf 2026. Die Ridge-Stärke wird innerhalb der Lernzeit gewählt (2024 lernen, 2025 bewerten; Werte 0,3 bis 100). Die Regression ist in reinem Python umgesetzt (gruppierte Newton-Schritte, `modell.fit`; Test `test_fit_recovers_log_odds`). Jede eingefrorene Datei enthält zwei Parametersätze je Horizont: `gewichte_geprueft` bzw. `quoten_geprueft` (gelernt 2024–2025, für die Prüfung) und `gewichte` bzw. `quoten` (gleiche Einstellung, gelernt an allen Stichtagen mit bekanntem Ergebnis). **Die täglichen Vorhersagen nutzen die zweiten.** Beispiel `stufen_v0`, 8 Wochen, endgültige Quoten: A 16,4 %, B 8,1 %, C 5,2 %, ein Land 3,0 %, ohne Auslandsmeldung 1,1 %.

**Einfrieren** (`stockout modell --einfrieren`, `modell.freeze`): schreibt je Verfahren `models/<name>.json` mit eigener sha256 und den Prüfplan `models/pruefplan.json`, der die Verfahren über ihre sha256 festlegt. Ab dem 01.01.2027 verweigert `freeze` das Einfrieren (Test `test_freeze_plan_log_round_trip`). Eine neue Fassung bekommt laut Prüfplan einen neuen Namen und einen eigenen Prüfplan. Wie sich die Hashes nachrechnen lassen: [Abschnitt 12](#12-vorab-registrierung).

**Prüfplan** (`models/pruefplan.json`, Auszug):
- Beginn **01.01.2027**; Stichtage alle 14 Tage ab Beginn; je Stichtag alle Wirkstoffe des Vorhersageprotokolls dieses Tages.
- Ergebnis: Eine Meldung zum Wirkstoff beginnt oder erscheint erstmals binnen 28, 56 bzw. 84 Tagen; ein Horizont zählt erst, wenn er im BASG-Stand abgelaufen ist.
- **Hauptvergleich:** `z3_v0` gegen `stufen_v0`, 8 Wochen. Bestanden, wenn der Brier-Score niedriger **und** die Trefferquote der 50 höchsten Wirkstoffe je Stichtag höher ist (Punktschätzer); 95-%-Intervalle über Wirkstoffe werden berichtet.
- Nebenkennzahlen: Log-Loss, Kalibrierung (Zehntel, Achsenabschnitt, Steigung), AUC, Average Precision, Top 25/50/100, Vorlauf, Listenstabilität; „Menge der besten“ nach Brier.
- Es zählen nur Zeilen, die mit diesem Prüfplan geschrieben wurden; `z3_v0_mit_de` dient nur der internen Bewertung.

## 10. Vorhersageprotokoll (täglich)

`modell.write_log` schreibt seit 21.10.2026 bei jedem Tageslauf `<Archiv>/protokoll/vorhersagen/<Jahr>/<Tag>.csv.gz` (UTF-8, gzip, wird mitkopiert). Eine Zeile je Wirkstoff des Tagesuniversums (10.11.2026: 1.382). Ein späterer Lauf am selben Tag ersetzt die Datei.

```text
datum,atc5,stufe,z3_v0_p4,z3_v0_p8,z3_v0_p12,z3_v0_ohne_ausland_p4,…,mittel_v0_p12,pruefplan
```

- `stufe`: Stufe wie auf der Website (ohne BfArM): `-` (keine Auslandsmeldung), `1`, `C`, `B`, `A`.
- `<verfahren>_p4|p8|p12`: Wahrscheinlichkeit für 4/8/12 Wochen, fünf Nachkommastellen, für alle fünf Verfahren.
- `pruefplan`: die ersten 12 Zeichen der sha256 des Prüfplans (`35a230a0a9bd`).

Vorhersagen gelten für den letzten BASG-Stand; der Dateiname ist der Kalendertag (Wien). Gleicher Archivstand und Code ergeben dieselben Dateien (gzip ohne Zeitstempel).

## 11. Bewertung (`stockout bewertung`)

`modell.bewerten` liest das Protokoll, wählt die Stichtage (Tage im Abstand von 14 Tagen ab Beginn, **für die ein Protokoll genau an diesem Tag existiert**) und bewertet alle Verfahren an denselben Fällen.

| Aufruf | Wirkung |
|---|---|
| `stockout bewertung` | gültige Bewertung ab Beginn des Prüfplans (01.01.2027), nur Zeilen mit dessen sha256 |
| `stockout bewertung --von JJJJ-MM-TT` | Bewertung ab einem frei gewählten Tag, **ohne** Filter auf den Prüfplan; nur für informelle Blicke |
| `stockout bewertung --rueckblick` | schreibt ein simuliertes Protokoll für jeden Tag 2026 mit den geprüften Parametern nach `data/derived/vorhersagen_rueckblick/` und bewertet es (Probelauf) |
| `stockout bewertung --rueckblick --zeitpunktgenau` | derselbe Probelauf mit zeitpunktgenauen Fällen und Merkmalen (Abschnitt 9) nach `data/derived/vorhersagen_rueckblick_zeitpunktgenau/` |
| `--json DATEI` | Ergebnis zusätzlich als JSON |

Ausgegeben werden je Horizont: Zahl der Fälle, Stichtage und Meldungen; je Verfahren Brier-Score und Skill gegenüber `stufen_v0`, AUC, Average Precision, Kalibrierung (Achsenabschnitt/Steigung, Zehntel), Top 25/50/100 je Stichtag; für 8 Wochen der Hauptvergleich mit Bootstrap-Intervallen über ganze Wirkstoffe (500 Ziehungen) und die Menge der besten Verfahren; dazu Vorlauf und Listenstabilität der Top 50 (`modell.lead_and_churn`). Ohne eingefrorenen Prüfplan endet der Befehl mit Exit-Code 1.

**Zeitplan** (abgeleitet aus dem Code): Ein Fall zählt erst, wenn sein Horizont im BASG-Stand abgelaufen ist. Erste 4-Wochen-Fälle sind ab 29.01.2027 auswertbar, erste 8-Wochen-Fälle (Hauptvergleich) ab 26.02.2027. Bis zum Go/No-Go am 30.04.2027 haben höchstens fünf Stichtage (01.01. bis 26.02.2027) einen abgelaufenen 8-Wochen-Horizont. Der Prüfplan nennt eine monatliche Bewertung und einen Bericht zum Go/No-Go; der Prüfbericht schätzt bis dahin rund 80–110 neue Meldungen. Fehlt das Protokoll an einem Stichtag (z. B. Rechner ganztägig aus), fällt dieser Stichtag weg.

## 12. Vorab-Registrierung

Die fünf Verfahren und der Prüfplan wurden am **21.10.2026** eingefroren, vor Beginn der prospektiven Prüfung am **01.01.2027**. Alles, was die Prüfung festlegt, liegt in `models/`:

| Datei | Inhalt |
|---|---|
| `z3_v0.json`, `z3_v0_ohne_ausland.json`, `z3_v0_mit_de.json`, `stufen_v0.json`, `mittel_v0.json` | Parameter je Verfahren; das Feld `sha256` ist der Hash der Datei ohne dieses Feld |
| `pruefplan.json` | Beginn, Stichtage, Ergebnis, Hauptvergleich mit Bestehensregel, Nebenkennzahlen und Regeln; legt jedes Verfahren über seine sha256 fest |
| `SHA256SUMS` | Ausgabe von `sha256sum` über `models/*.json`, beim Export der öffentlichen Fassung erzeugt |

**Zusatzprüfung Zustimmung (festgelegt 16.11.2026).** Ein zusätzlicher, vorab festgelegter Punkt der Prüfung fragt, ob Top-50-Warnungen von z3_v0 öfter eintreffen, wenn ein eingefrorenes Modell auf Ebene der Zulassungsinhaber zustimmt. Regel, Termine und sha256: `analysis/paketsuche/zusatzpruefung/` ([Regeltext](../analysis/paketsuche/zusatzpruefung/ZUSATZPRUEFPLAN.md)). Die Hauptprüfung nach `pruefplan.json` bleibt unberührt.

**Der Prüfplan-Hash.** Die sha256 von `pruefplan.json` beginnt mit **`35a230a0a9bd`**. Jede Zeile des Vorhersageprotokolls trägt diese 12 Zeichen in der Spalte `pruefplan` ([Abschnitt 10](#10-vorhersageprotokoll-täglich)), und `stockout bewertung` wertet nur solche Zeilen aus.

**Nachrechnen**, im Repository-Ordner:

1. Die Dateien sind unverändert:

   ```console
   $ (cd models && sha256sum -c SHA256SUMS)
   mittel_v0.json: OK
   pruefplan.json: OK
   stufen_v0.json: OK
   z3_v0.json: OK
   z3_v0_mit_de.json: OK
   z3_v0_ohne_ausland.json: OK
   ```

2. Die Hashes in den Dateien stimmen. `modell._write_json` bildet die sha256 über `json.dumps(daten, ensure_ascii=False, indent=1, sort_keys=True)` in UTF-8, solange `daten` noch kein Feld `sha256` hat, und schreibt sie dann dazu. Eine Eigenheit betrifft die drei Logit-Dateien `z3_v0`, `z3_v0_mit_de` und `z3_v0_ohne_ausland`: Die λ-Werte der Ridge-Wahl (`horizonte.<h>.wahl_l2.logloss_validierung`) waren beim Einfrieren Zahlen, deshalb hat `sort_keys` sie **numerisch** sortiert (0.3, 1.0, 3.0, 10.0, 30.0, 100.0). Nach dem Einlesen aus JSON sind es Zeichenketten, die als Text sortiert würden (0.3, 1.0, 10.0, 100.0, 3.0, 30.0). Wer naiv nachrechnet, bekommt deshalb für diese drei Dateien einen anderen Hash; bei den übrigen drei stimmt er auch naiv. Dieses Skript wandelt die λ-Schlüssel zurück in Zahlen und prüft auch die Einträge im Prüfplan; als Datei speichern und im Repository-Ordner mit `python3` ausführen (nur Standardbibliothek):

   ```python
   import hashlib, json, pathlib

   def nachrechnen(pfad):
       d = json.loads(pathlib.Path(pfad).read_text(encoding="utf-8"))
       gespeichert = d.pop("sha256")
       for h in d.get("horizonte", {}).values():  # nur z3_v0, z3_v0_mit_de, z3_v0_ohne_ausland
           if "wahl_l2" in h:                     # λ-Schlüssel wieder als Zahlen, also numerisch sortiert
               lv = h["wahl_l2"]["logloss_validierung"]
               h["wahl_l2"]["logloss_validierung"] = {float(k): v for k, v in lv.items()}
       text = json.dumps(d, ensure_ascii=False, indent=1, sort_keys=True)
       return hashlib.sha256(text.encode()).hexdigest() == gespeichert, gespeichert

   plan = json.loads(pathlib.Path("models/pruefplan.json").read_text(encoding="utf-8"))
   for name, eintrag in plan["verfahren"].items():
       stimmt, sha = nachrechnen(eintrag["datei"])
       print(name, stimmt and sha == eintrag["sha256"])
   stimmt, sha = nachrechnen("models/pruefplan.json")
   print("pruefplan", stimmt, sha[:12])
   ```

   Ausgabe am 11.11.2026:

   ```text
   mittel_v0 True
   stufen_v0 True
   z3_v0 True
   z3_v0_mit_de True
   z3_v0_ohne_ausland True
   pruefplan True 35a230a0a9bd
   ```

**Was der Hash belegt und was nicht.** Er belegt, dass Modelle und Prüfplan seit dem Einfrieren unverändert sind. Das Datum belegt er allein nicht: Dafür stehen diese Dateien seit dem 12.11.2026 öffentlich auf GitHub und im Zenodo-Archiv des Releases `v0.1-prereg` ([doi:10.5281/zenodo.24168687](https://doi.org/10.5281/zenodo.24168687)). `load_plan` prüft die Hashes beim Laden nicht nach. Merkmalscode, Parser, Quellenliste und Daten sind nicht eingefroren ([Abschnitt 14](#14-was-geprüft-ist-und-was-nicht)).

**Zeitplan:**

| Datum | Schritt |
|---|---|
| 21.10.2026 | Verfahren und Prüfplan eingefroren; seither täglich ein Vorhersageprotokoll |
| 01.01.2027 | Beginn der prospektiven Prüfung; ab dann verweigert `freeze` das Einfrieren |
| 26.02.2027 | erste auswertbare 8-Wochen-Fälle des Hauptvergleichs |
| 30.04.2027 | Go/No-Go: erster Bericht nach dem Prüfplan; entscheidet, ob Z3 weiterverfolgt wird |

Gewertet wird das Vorhersageprotokoll der Referenzinstanz ([Unterschiede](DATENQUELLEN.md#4-unterschiede-zur-referenzinstanz)). **Die Ergebnisse werden in jedem Fall veröffentlicht**, auch wenn Z3 die Stufenregel nicht schlägt. Geplant ist außerdem, ab Jänner 2027 monatlich die Prüfsummen der Vorhersageprotokolle und einen kurzen Zwischenstand zu veröffentlichen.

## 13. Ergebnisse des Rückblicks (Prüfbericht Z3 v0)

Quelle: [Prüfbericht Z3 v0](../reports/Z3%20v0%20Pr%C3%BCfbericht.md), Stand 21.10.2026. **Bedingungen:** gelernt 2024–2025, geprüft 2026 bis BASG-Stand 20.10.2026; 8 Wochen; 23.461 Fälle mit 714 neuen Meldungen (3,0 %); ohne BfArM (außer `z3_v0_mit_de`); Top-k je Stichtag.

| Verfahren | Brier | Skill gegenüber Grundrate | AUC | Average Precision | Top 25 | Top 50 | Top 100 |
|---|---|---|---|---|---|---|---|
| `z3_v0` | 0,02742 | +7,1 % | 0,819 | 0,155 | 24,9 % | 20,2 % | 16,6 % |
| `z3_v0_ohne_ausland` | 0,02766 | – | 0,810 | 0,145 | 21,4 % | 19,2 % | – |
| `z3_v0_mit_de` | 0,02748 | – | 0,819 | 0,150 | 23,9 % | 20,2 % | – |
| `stufen_v0` | 0,02861 | +3,1 % | 0,728 | 0,078 | 15,7 % | 13,8 % | 10,9 % |
| `mittel_v0` | 0,02760 | – | 0,810 | 0,156 | 25,8 % | 20,8 % | – |
| Grundrate | 0,02952 | 0 | 0,5 | – | 3,0 % | 3,0 % | 3,0 % |

(„–“: im Bericht nicht angegeben.)

- **Hauptvergleich `z3_v0` gegen `stufen_v0`** (95-%-Intervalle über Wirkstoffe): AUC +0,091 [+0,065 bis +0,118], Brier-Gewinn +0,0012 [+0,0007 bis +0,0017], Top 50 +6,4 Prozentpunkte [+1,9 bis +10,3]. Bei 4 und 12 Wochen ähnlich (AUC 0,812 gegenüber 0,732 bzw. 0,814 gegenüber 0,720).
- **Kalibrierung** (8 Wochen): im oberen Bereich gut (oberstes Zehntel vorhergesagt 14,2 %, beobachtet 14,9 %), unten etwas zu hoch. `mittel_v0` ist zu flach kalibriert (Steigung 1,2).
- **Was trägt:** Produktzahl (nur ein Produkt −0,9 log-Chance, 10+ Produkte +0,5) und früherer Engpass (+0,75) tragen am meisten; Auslandsmerkmale +0,3 bis +0,45; Registerereignisse wenig.
- **Ausland bringt im Rückblick weniger als erwartet:** Ohne Auslandsmerkmale erreicht das Modell AUC 0,810; das Ausland hebt vor allem die Spitze (Top 25: 24,9 % gegenüber 21,4 %). Ob das prospektiv hält, ist die wichtigste Nebenfrage.
- **BfArM bringt im Rückblick nichts dazu.**
- **Probelauf** (`bewertung --rueckblick`, 178 neue Meldungen 2026): Am Tag vor der Meldung stand der Wirkstoff bei `z3_v0` in 25 % [20–32 %] der Fälle unter den 50 höchsten (Median seit 59 Tagen, irgendwann in den 8 Wochen davor 37 %, Wechsel der Top 50 je Tag 2,3 %); `z3_v0_ohne_ausland` 26 %; `stufen_v0` 16 %.
- Korrektur vom 21.10.2026 laut Bericht: In der ersten Fassung flossen Stichtage aus 2026 in die Wahl der Ridge-Stärke ein; ohne sie änderte sich nur das 4-Wochen-Modell.
- Nachtrag vom 16.11.2026 („Änderungen nach dem Einfrieren“ im Bericht): Ganz zeitpunktgenau nachgerechnet liegt die AUC bei 0,813 für `z3_v0` und 0,715 für `stufen_v0`; die Zahlen sind nicht wesentlich zu günstig. Mit dem Ziel des Prüfplans („beginnt oder erscheint erstmals“) gibt es rund 12 % mehr Treffer, der Brier liegt bei etwa 0,030 und die Top-50-Quote bei etwa 21–22 %. Prospektive Zahlen 2027 sind mit diesem Niveau zu vergleichen, nicht mit 0,02742.

## 14. Was geprüft ist und was nicht

**Geprüft:**
- Rechenlogik durch Tests: Merkmale nur aus Daten vor dem Stichtag, Wiederfinden bekannter log-Chancen, Einfrieren/Prüfplan/Protokoll als Rundlauf, Kennzahlen und Vorlauf (`tests/test_modell.py`), Episodenregeln (`tests/test_build.py`), Vorlauf und Länderkombinationen (`tests/test_foreign.py`), Rückblick-Bausteine (`tests/test_rueckblick.py`). Ergebnis: siehe [ENTWICKLUNG.md](ENTWICKLUNG.md#tests).
- Rückblickende, zeitlich getrennte Prüfung von Z3 v0 und den Stufen (Abschnitt 13) mit den dort genannten Grenzen.

**Nicht geprüft bzw. offen:**
- **Prospektive Güte:** beginnt am 01.01.2027; vorher gibt es keine gültige Bewertung.
- **Beobachtet:** Ein früher, informeller Zwischenblick (Oktober/November 2026, wenige Ereignisse) sah `z3_v0` vor `stufen_v0`. Das ist **keine gültige Bewertung** (vor Beginn des Prüfplans, zu wenige Fälle, ohne die Regeln des Prüfplans).
- Rückblickende Zahlen sind durch die lückenhafte BASG-Vorgeschichte vor dem 17.10.2026 und durch gelöschte Auslandsmeldungen verzerrt; Fälle desselben Wirkstoffs an aufeinanderfolgenden Stichtagen sind nicht unabhängig (die Intervalle berücksichtigen das nur über Wirkstoffe).
- **Z1** (hält der angekündigte Termin, ±7 Tage) und **Z2** (endet die Meldung binnen 4/8/12 Wochen) sind geplant, aber **nicht umgesetzt**.
- **Anzeige** einer Prognose auf der Website ist geplant, aber erst nach bestandener Prüfung und guter Kalibrierung; heute zeigt die Packungsseite „Noch keine Prognose“.
- Der Nutzen für Fachleute ist nicht geprüft; geplant sind Gespräche mit der Zielgruppe.

**Achtung bei Änderungen (Ableitung aus dem Code):** Die eingefrorenen Verfahren speichern nur Gewichte. Ihre Merkmale werden täglich aus der aktuellen Datenbank berechnet (`modell.Knowledge` nutzt alle `foreign_items` außer den in `ohne_quellen` genannten). Eine neue Auslandsquelle, ein geänderter Parser oder eine geänderte ATC-Ableitung ändert deshalb die Eingaben von `z3_v0` und `stufen_v0` während der prospektiven Prüfung. Deshalb ändert die Referenzinstanz Quellen und Parser bis zum Go/No-Go am 30.04.2027 nur, wenn eine Quelle ihr Format ändert. Ausnahme seit 16.11.2026: Veraltete Abrufe gehen nicht mehr in die Datenbank; das ändert die Eingaben nur an Tagen, an denen eine Quelle eine alte Fassung liefert ([BETRIEB.md](BETRIEB.md), Alarmregel). Die Hashes in `models/` sichern nur die Gewichte, nicht diesen Code.
