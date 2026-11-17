# Z3 v0: Prüfbericht 2026

**Stand:** 21.10.2026 · **Prüfplan:** `models/pruefplan.json` (sha256 `35a230a0a9bd…`) mit fünf eingefrorenen Verfahren · **Erzeugen:** `stockout modell` (Prüfung), `stockout modell --einfrieren` (Fassungen und Prüfplan), `stockout bewertung` (Bewertung des Vorhersageprotokolls)

## Frage und Fall

Z3 schätzt die Wahrscheinlichkeit, dass ein Wirkstoff (ATC Ebene 5) binnen 4, 8 oder 12 Wochen eine neue BASG-Meldung bekommt. Gefragt ist das für Wirkstoffe, die laut ASP-Liste lieferbar sind und noch keine aktive Meldung haben. Ein Fall ist ein Wirkstoff an einem Stichtag; Stichtage liegen alle 14 Tage. Alle Merkmale stammen aus Daten, die vor dem Stichtag datiert sind:

- **Auslandsmeldungen:** Zahl der Länder; derselbe österreichische Zulassungsinhaber im Ausland, in einem bzw. in drei Ländern; eine neue Meldung in den letzten 4 Wochen.
- **Vorgeschichte in Österreich:** ein früherer Engpass, einer im letzten Jahr, einer, der vor höchstens 90 Tagen endete.
- **Markt:** Zahl der lieferbaren Produkte in der ASP-Fassung vor dem Stichtag.
- **Register:** in den letzten 8 Wochen eine Änderung beim Zulassungsinhaber, ein Marktaustritt bzw. eine EKO-Streichung eines anderen Produkts.
- **Sonst:** ATC-Hauptgruppe, Quartal.

Das Modell ist eine regularisierte logistische Regression, eine je Horizont. Die Stärke der Regularisierung wurde mit einer zeitlichen Teilung innerhalb der Lernzeit gewählt (2024 lernen, 2025 bewerten). Korrektur vom 21.10.: In der ersten Fassung flossen in diese Wahl auch Stichtage aus 2026 ein; ohne sie ändert sich nur das 4-Wochen-Modell (Ridge 30 statt 10), 8 und 12 Wochen bleiben gleich. BfArM-Meldungen bleiben wie auf der Website draußen.

## Ergebnis: gelernt 2024–2025, geprüft 2026

Die Prüfung umfasst 8 Wochen, 23.461 Fälle und 714 Meldungen (3,0 %). „Top 50“ heißt: die 50 Wirkstoffe mit der höchsten Schätzung je Stichtag.

| Verfahren | Brier | Skill gegen Grundrate | AUC | Top 25 | Top 50 | Top 100 | Anteil aller Meldungen in Top 100 |
|---|---|---|---|---|---|---|---|
| **Modell Z3 v0** | 0,02742 | +7,1 % | 0,819 | 24,9 % | 20,2 % | 16,6 % | 40 % |
| Stufenregel (A 5+, B 3–4, C 2 Länder) | 0,02861 | +3,1 % | 0,728 | 15,7 % | 13,8 % | 10,9 % | 26 % |
| Frühere Engpässe in Österreich | 0,02868 | +2,8 % | 0,733 | 7,2 % | 7,2 % | 7,2 % | 17 % |
| Grundrate | 0,02952 | 0 | 0,5 | 3,0 % | 3,0 % | 3,0 % | 7 % |

Das Modell schlägt die Stufenregel deutlich. Die Intervalle ziehen ganze Wirkstoffe neu (95 %):

- AUC: +0,091 [+0,065 bis +0,118]
- Brier-Gewinn: +0,0012 [+0,0007 bis +0,0017] (die erste Fassung des Berichts rundete das Intervall zu grob auf +0,0010 bis +0,0020)
- Top 50 je Stichtag: +6,4 Prozentpunkte [+1,9 bis +10,3]

Bei 4 Wochen (AUC 0,812 gegenüber 0,732) und 12 Wochen (0,814 gegenüber 0,720) sieht es ähnlich aus.

**Kalibrierung, 8 Wochen**, je Zehntel der Schätzungen (vorhergesagt → beobachtet): 0,7 → 0,6 %, 0,8 → 0,2 %, 0,9 → 0,4 %, 1,1 → 0,6 %, 1,3 → 1,0 %, 1,8 → 1,7 %, 2,5 → 3,0 %, 3,6 → 2,8 %, 6,0 → 5,3 %, 14,2 → 14,9 %. Im oberen Bereich, auf den es ankommt, stimmt die Schätzung gut. Unten liegt sie etwas zu hoch.

**Was trägt**, nach den Gewichten (logarithmische Chance, 8 Wochen):
- Ein Wirkstoff mit nur einem Produkt wird selten gemeldet (−0,9). Viele Produkte (10+) erhöhen die Chance (+0,5).
- Ein früherer Engpass: +0,75.
- Auslandsmeldungen: +0,4 bis +0,45 je nach Länderzahl, gleicher Inhaber im Ausland +0,4, eine neue Auslandsmeldung +0,3.
- Die Registerereignisse tragen wenig, wie schon im Rückblick.

## Herausforderer: mehrere Verfahren auf denselben Fällen

Seit dem 21.10.2026 sind fünf Verfahren nebeneinander eingefroren und schreiben täglich ins Vorhersageprotokoll (`<Archiv>/protokoll/vorhersagen/`). Gelernt wurde jeweils 2024–2025, geprüft an denselben Fällen 2026. Die folgenden Zahlen gelten für 8 Wochen.

| Verfahren | Rolle | Brier | AUC | Average Precision | Top 25 | Top 50 |
|---|---|---|---|---|---|---|
| **z3_v0** | Hauptmodell | 0,02742 | 0,819 | 0,155 | 24,9 % | 20,2 % |
| z3_v0_ohne_ausland | Diagnose: ohne Auslandsmeldungen | 0,02766 | 0,810 | 0,145 | 21,4 % | 19,2 % |
| z3_v0_mit_de | mit BfArM, nur intern | 0,02748 | 0,819 | 0,150 | 23,9 % | 20,2 % |
| stufen_v0 | Stufenregel als Quote je Stufe | 0,02861 | 0,728 | 0,078 | 15,7 % | 13,8 % |
| mittel_v0 | Mittel aus z3_v0, z3_v0_mit_de, stufen_v0 | 0,02760 | 0,810 | 0,156 | 25,8 % | 20,8 % |

- **Auslandsmeldungen bringen im Rückblick weniger als erwartet.** Dasselbe Modell ohne sie kommt nahe heran. Der größte Teil der Trennschärfe stammt aus Produktzahl und Vorgeschichte in Österreich. Die Auslandsmeldungen heben vor allem die obersten Einträge (Top 25: 24,9 % gegenüber 21,4 %). Ob das prospektiv hält, ist die wichtigste Nebenfrage der Prüfung.
- **BfArM bringt hier nichts dazu.**
- **Das Mittel trifft die Spitze etwas besser**, ist aber zu flach kalibriert (Steigung 1,2).
- **Die Menge der besten Verfahren nach Brier** umfasst die drei Modelle, die Stufenregel nicht.

Ein Probelauf schreibt das Protokoll für jeden Tag 2026 mit den geprüften Parametern und bewertet es wie später die echten Daten (`stockout bewertung --rueckblick`). Er bestätigt die Zahlen (Hauptvergleich bestanden) und misst zusätzlich, wie lange ein Wirkstoff vor einer neuen Meldung auf der Liste der 50 höchsten stand. Aus 178 neuen Meldungen:

| Verfahren | Am Tag davor auf der Liste | Davon seit (Median) | Irgendwann in den 8 Wochen davor | Wechsel der Top 50 je Tag |
|---|---|---|---|---|
| z3_v0 | 25 % [20–32 %] | 59 Tagen | 37 % | 2,3 % |
| z3_v0_ohne_ausland | 26 % | 70 Tagen | 29 % | 0,9 % |
| stufen_v0 | 16 % | 71 Tagen | 18 % | 1,3 % |

Gleichstände (etwa die vielen Wirkstoffe derselben Stufe) werden in fester Reihenfolge je Wirkstoff gebrochen, damit die Liste nicht künstlich springt.

## Grenzen

- Die BASG-Vorgeschichte vor dem 17.10.2026 stammt aus einzelnen Schnappschüssen. Kurze Engpässe fehlen, und der Beginn einer Meldung kann vor ihrer Veröffentlichung liegen.
- Auslandsmeldungen tragen das Datum ihrer ersten Veröffentlichung bzw. ihres Beginns. Ältere Meldungen kennt man teils nur aus dem Internet Archive.
- Fälle desselben Wirkstoffs an aufeinanderfolgenden Stichtagen sind nicht unabhängig. Die Intervalle berücksichtigen das nur über die Wirkstoffe, nicht über die Zeit.
- Das ist ein Rückblick. Ob die Schätzung im Voraus trägt, zeigt erst die prospektive Prüfung.

## Eingefrorene Fassungen und prospektive Prüfung

`models/` enthält je Verfahren die geprüften Parameter (gelernt 2024–2025). Dazu kommen Parameter mit denselben Einstellungen, neu gelernt an allen Stichtagen mit bekanntem Ergebnis; diese nutzen die täglichen Vorhersagen. `models/pruefplan.json` legt die Verfahren über ihren sha256 fest, dazu Hauptvergleich und Nebenkennzahlen.

Täglich entstehen zwei Protokolle:
- das Vorhersageprotokoll aller Verfahren je Wirkstoff;
- das Merkmalsprotokoll mit den Spalten `z3_p4`, `z3_p8` und `z3_p12` von z3_v0.

Mit demselben Archivstand und Code entstehen dieselben Dateien.

Prüfplan (auch in der Datei):

- **Was zählt:** nur Vorhersagen aus dem Protokoll ab dem 01.01.2027, geschrieben mit diesem Prüfplan. Stichtage liegen alle 14 Tage.
- **Ergebnis:** eine neue Meldung zum Wirkstoff beginnt oder erscheint erstmals binnen 4, 8 bzw. 12 Wochen.
- **Hauptvergleich, 8 Wochen:** z3_v0 gegen stufen_v0. Bestanden heißt: Brier niedriger und Top-50-Quote höher (Punktschätzer). Die 95-%-Intervalle über Wirkstoffe werden berichtet.
- **Sekundär:** alles andere, auch die Menge der besten Verfahren.
- **Ablauf:** `stockout bewertung` monatlich, Bericht zum Go/No-Go am 30.04.2027. Bis dahin sind rund 80–110 neue Meldungen zu erwarten. Das reicht für den Abstand zur Stufenregel, nicht für eine feine Reihung ähnlicher Modelle.
- **Danach keine Änderungen:** Ab dem 01.01.2027 verweigert `stockout modell --einfrieren` das Einfrieren. Eine neue Fassung bekommt einen neuen Namen und einen eigenen Prüfplan.

## Änderungen nach dem Einfrieren

**16.11.2026** (Sprint s24, vor Beginn der Prüfung am 01.01.2027). `models/` und der Prüfplan (`35a230a0a9bd`) bleiben unverändert. Geschriebene Protokolle werden nicht neu geschrieben, auch das vom 22.10.2026 nicht; es zählt nicht für die Prüfung.

1. **Veraltete Abrufe gehen nicht mehr in die Datenbank** (gilt im Tageslauf ab dem 16.11.2026). Liefert eine Quelle eine ältere Fassung als zuvor (Last-Modified älter als bei einem früheren Live-Abruf), lässt `build` die Datei weg; ein neuer solcher Abruf zählt als Fehlabruf und wird nachgeholt. Das Archiv bleibt unverändert. Bisher betroffen: ogyei am 22.10.2026 (Fassung vom 11.06.2026) und sukl_cz am 23.10.2026 (ohne Wirkung, weil nur die neueste CZ-Datei zählt). Ohne die ogyei-Datei ändern sich rund 1.100 HU-Einträge der Datenbank; im Rückblick galten dadurch an jedem Stichtag bis zum 22.10.2026 rund 450–470 alte HU-Meldungen zusätzlich als aktiv.
   - *Tägliche Merkmale und Vorhersageprotokoll:* Änderung nur an Tagen, an denen eine Quelle eine alte Fassung liefert; bisher war das nur der 22.10.2026. Das Protokoll vom 16.11.2026 ist mit altem und neuem Code byte-gleich, auch auf einer neu gebauten Datenbank.
   - *Ergebnis von `stockout bewertung`:* unverändert. Es nutzt nur BASG; BASG sendet kein Last-Modified, die Regel greift dort nicht.
   - *Rückblick und Lernen:* Rückblicke, frühere Frühwarnlisten und `stockout modell` sehen die alten HU-Einträge nicht mehr.
2. **Schalter `--zeitpunktgenau` für Lernen und Rückblick** (`stockout modell --zeitpunktgenau`, `stockout bewertung --rueckblick --zeitpunktgenau`; Standard bis 30.04.2027: aus, also wie eingefroren). Eine BASG-Meldung gilt erst ab ihrer Veröffentlichung als bekannt (Fallauswahl, Vorgeschichte, Ziel „beginnt oder erscheint erstmals“), die ASP-Fassung erst ab ihrer Erfassung. Ohne Schalter sind `stockout modell`, der Probelauf und das tägliche Protokoll byte-gleich mit dem Stand vor der Änderung. Auf die prospektive Prüfung wirkt der Schalter nicht: Am Tag selbst kennt die Datenbank nur Veröffentlichtes.
3. **Korrekturnotiz zu den Rückblickzahlen** (aus dem Bericht zur Modellsuche vom November 2026, nicht Teil der öffentlichen Fassung). Die eingefrorenen Gewichte, ganz zeitpunktgenau nachgerechnet (Fälle, Ziel, Vorgeschichte und Ausland, dieselben Stichtage), ergeben 8 Wochen eine AUC von **0,813 für z3_v0 und 0,715 für die Stufenregel** (oben 0,819 und 0,728). Der Abstand wird eher größer; die Zahlen oben sind nicht wesentlich zu günstig. Der Prüfplan zählt aber „beginnt *oder erscheint erstmals*“. Mit diesem Ziel gibt es rund 12 % mehr Treffer, der Brier liegt bei etwa **0,030** statt 0,0274 und die Top-50-Quote bei etwa 21–22 % statt 20 %. Prospektive Zahlen ab 2027 sind mit diesem Niveau zu vergleichen. Im Rückblick zählen Stufe und Auslandsmerkmale außerdem belgische, spanische und französische Altbestände mit (im Archiv erst seit Oktober 2026, rückblickend nur die bis dahin überlebenden, meist langen Engpässe); die AUC 0,813 / 0,715 lässt sie weg. Der Betriebscode rechnet mit dem Schalter ähnlich (`stockout bewertung --rueckblick --zeitpunktgenau`, BASG-Stand 16.11.2026, Ausland noch wie in `Knowledge`): z3_v0 AUC 0,820, Brier 0,0305, Top 50 22,2 %; Stufenregel 0,738, 0,0319, 15,3 %; Hauptvergleich bestanden.

**16.11.2026** (Sprint s26). Neue Rohquellen ohne Parser: Der Tageslauf archiviert seither weitere öffentliche Quellen nur roh (Kennzeichen „beobachtet“), als letzten Schritt nach dem Protokoll, ohne Datenbanktabelle und ohne Merkmal. Auf Merkmale, Vorhersageprotokoll und `stockout bewertung` wirkt das nicht: Das Protokoll vom 16.11.2026 ist mit altem und neuem Code byte-gleich, auch wenn beide die Datenbank aus derselben Archivkopie mit Abrufen der neuen Quellen neu bauen; die Tabellen sind gleich (Nachweis V03). `models/` und der Prüfplan (`35a230a0a9bd`) bleiben unverändert.
