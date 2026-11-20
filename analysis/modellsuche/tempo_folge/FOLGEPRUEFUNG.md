# Folgeprüfung Signaltempo: neue Länder (festgelegt in s29, 17.11.2026)

Diese Regel steht fest, bevor eine äußere Zahl mit Tempomerkmalen vorlag. Sie gilt unabhängig vom Ergebnis von s29.
Maschinenlesbar: `regel.json` (sha256 in `SHA256SUMS` und im Bericht `reports/Signaltempo 2026-11.md`).

## Warum

BE (famhp), ES (cima), FR (ansm), FI (Fimea) und die EMA-Tageslisten haben erst seit Oktober 2026 eine saubere tägliche
Geschichte im Archiv. Ihre ältere Geschichte besteht nur aus Meldungen, die bis dahin überlebt haben, und darf in keine
Rückschau. Ob das Tempo dieser Signale die Prognose ergänzt, lässt sich deshalb nur vorwärts prüfen.

## Regel

- **Stichtage:** alle Montage 02.11.2026–28.06.2027 (35 Stichtage). Auswertung frühestens September 2027.
- **Fälle und Ziel:** wie s23/s29 (`fall`, `y56`: Meldung beginnt oder erscheint erstmals in (t, t + 56]).
- **Ausgangsmodell:** das eingefrorene E_S3z_C (`work/spaet/modell_E_S3z_C_2026-10-20.pkl`, sha256
  `3e791fb03cbef748a701c6b1259920137e42a67ff7d0a831725c1fd53a96e69b`), nicht neu gelernt.
- **Merkmal:** G1 Auslandstempo über alle Länder (IT, PL, HU, EMA, US, BE, ES, FR, FI, CZ, SK, SI; nie BfArM), Form
  `dif` fest: `dl28`, `dl56` (aktive Länder jetzt gegen vor 28/56 Tagen), `nc` (Länder mit neuer Meldung, 28 gegen
  28 davor), `gap` (Nähe vom ersten zum zweiten aktiven Land, τ 91), `ew` (abklingende neue Meldungen, 28 gegen 91).
  Index `tpi_G1` = Summe der durch ihre Streuung geteilten Komponenten.
- **Zeitregel:** eine Meldung zählt ab der ersten täglichen Archivdatei, in der sie steht; aktiv ist, was in der letzten
  Archivdatei vor t steht. Einträge der ersten Datei einer Quelle (Altbestand) behalten ihr Signaldatum.
- **E1:** `y56 ~ logit(p_E) + z(tpi_G1)`, Odds Ratio je Standardabweichung, Block-Bootstrap über Stichtage (8er-Blöcke,
  B = 2000), Holm über alle Zeilen und Signalzeilen.
- **Entscheidung (Schwelle wie s29, OR 1,10 je SD):** *gefunden*, wenn die Holm-Untergrenze auf allen Zeilen über 1 liegt
  (Folge: eigener Prüfplan für ein Modell mit diesen Quellen); *ausgeschlossen*, wenn die Holm-Obergrenze auf allen
  Zeilen und auf den Signalzeilen unter 1,10 liegt; sonst *unklar*.
- **Beschreibend:** dasselbe nur mit den neuen Quellen und nur mit den alten Quellen der sauberen Variante.

## Grenzen

- Die ersten Stichtage sehen für BE/ES/FR bei Rückblicken von 28/56 Tagen teils nur den Altbestand; vor dem
  Archivbeginn beendete Meldungen fehlen dort.
- 35 Stichtage sind ein Viertel der s29-Testzeit; ein kleiner Effekt (OR 1,10) ist dort schwerer nachzuweisen.
