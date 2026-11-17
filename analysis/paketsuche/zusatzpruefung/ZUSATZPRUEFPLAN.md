# Zusatzprüfplan: Zustimmung des Inhabermodells

**Festgelegt am 16.11.2026** (Owner-Entscheidung, Sprint 28). Maschinenlesbar mit allen sha256: `zusatzpruefplan.json`.
Auswertung: `analysis/paketsuche/psuche/zustimmung_voraus.py`. Das Skript prüft beim Start die sha256 aus der JSON-Datei.
Weicht eine ab, wertet es nicht aus.

**Frage:** Treffen Warnungen von z3_v0, denen das Inhabermodell zustimmt, prospektiv öfter ein als solche ohne Zustimmung?

## Regel

- **Hauptmodell und Liste.** Die Werte `z3_v0_p8` aus dem täglichen Vorhersageprotokoll, nur Zeilen mit Prüfplan
  `35a230a0a9bd`. Stichtage sind die Montage ab 04.01.2027, an denen ein Protokoll vorliegt. Die Liste sind die 50
  Wirkstoffe mit dem höchsten Wert je Stichtag. Bei Gleichstand entscheidet der ATC5-Code aufsteigend.
- **Zustimmung.** Das eingefrorene Inhabermodell `T04_I_lin_klein` (in `zusammenspiel_fest_2026-11-16.pkl`, sha256
  `6a501562…`) wird je Stichtag aus dem Archiv gerechnet, nur mit Daten vor dem Stichtag. Die Werte der Inhaber-Fälle
  werden je Wirkstoff zusammengefasst: q = 1 − Π(1 − p), roh. „Bestätigt“ heißt, dass der Wirkstoff am selben Stichtag
  auch unter den 50 höchsten q steht. Die Rangfolge gilt unter den Wirkstoffen des Protokolls. Ein Wirkstoff ohne q zählt
  als nicht bestätigt.
- **Ziel und Fälle wie in der Hauptprüfung.** Es gilt dieselbe Regel wie in `stockout bewertung`: Eine BASG-Meldung zum
  Wirkstoff beginnt oder erscheint erstmals binnen 56 Tagen. Ein Stichtag zählt erst, wenn sein Horizont im BASG-Stand
  abgelaufen ist.
- **Hauptendpunkt.** Die Trefferquote „bestätigt“ minus „nicht bestätigt“ innerhalb der Top 50, gepoolt über die
  Stichtage. Der 95-%-Bereich kommt aus einem Bootstrap über ganze Wirkstoffe (B = 2000, Seed 20261116,
  Perzentilbereich). Der Endpunkt ist erfüllt, wenn der ganze Bereich über 0 liegt.
- **Nebenpunkte (nur beschreibend).**
  - je Gruppe das Verhältnis eingetroffen zu angesagt (Summe der Treffer durch Summe der z3_v0-Werte);
  - die Horizonte 28 und 84 Tage;
  - dieselbe Teilung mit `E_S3z_C` als Hauptmodell (56 Tage, Nachrechnung aus dem Archiv).

## Zeitpunkte

| Was | Wann |
|---|---|
| Erste Montage mit abgelaufenem Horizont (Stichtag 04.01.2027) | 28 T.: BASG-Stand 01.02.2027 · 56 T.: 01.03.2027 · 84 T.: 29.03.2027 |
| Zwischenauswertung zum Go/No-Go, nur beschreibend | 30.04.2027 (Montage 04.01.–01.03.2027, höchstens 9) |
| Entscheidende Auswertung: Montage 04.01.–28.06.2027 (26 Montage) | sobald der BASG-Stand den 23.08.2027 erreicht |

## Unberührt

Die Hauptprüfung nach `models/pruefplan.json` (35a230a0a9bd) bleibt unberührt, ebenso `models/`, `src/`, `deploy/` und
`data/`. Die Website zeigt die Zustimmung frühestens nach dem Go/No-Go und nur nach Owner-Entscheidung.

## Lesarten bei der Umsetzung (16.11.2026)

- **Gleichstand bei q.** Auch hier entscheidet der ATC5-Code aufsteigend. In der Nachrechnung vom 16.11.2026
  (`rank(method="first")`) änderte das im Rückblick keine Liste und keine Zustimmung.
- **Nebenpunkt Horizonte.** Gerechnet wird mit den Werten des jeweiligen Horizonts: Liste nach `z3_v0_p4` bzw.
  `z3_v0_p12`, q für 28 bzw. 84 Tage. Daneben steht die 8-Wochen-Liste mit dem Ziel 28 bzw. 84 Tage.
- **Woher die Werte kommen.**
  - Das Inhabermodell wird je Montag aus dem ersten Stand gerechnet, dessen BASG-Stand den Montag erreicht (Rechenweg
    s27). Danach wird es nie neu gerechnet.
  - `E_S3z_C` kommt aus `msuche.spaetpruefung`, sonst aus derselben Nachrechnung.
  - Die Ziele kommen aus der Datenbank des Stands. Sie ist ein Neubau aus der Archivsicht und wird nur gelesen.
    Verwendet werden dieselben Funktionen wie in `stockout bewertung` (`read_logs`, `report_days`, `_within`).
- **Rückblick (nur Hinweis, Testjahre schon gesehen).** Der Testmodus des Skripts gibt die Nachrechnung vom 16.11.2026
  genau wieder: bestätigt 21,5 / 22,4 / 27,8 %, nicht bestätigt 10,4 / 9,9 / 17,3 % (2024/25/26). Mit den Zielen aus
  `stockout bewertung` liegt 2026 bei 27,1 % gegen 17,3 %. Der Bereich der Differenz reicht dort bis knapp unter 0
  (−0,0003). Ein halbes Jahr Montage reicht also nur knapp, um einen Unterschied dieser Größe zu belegen.
