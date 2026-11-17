# Additional check: agreement of the holder model

Fixed on **16 Nov 2026**, before the prospective test starts on 1 Jan 2027. It adds one question to the test and changes
nothing in the main test (`models/pruefplan.json`, plan hash `35a230a0a9bd`).

**Question.** Do Z3 warnings that a second, independent model agrees with come true more often than warnings without
agreement?

The binding text is German: [`ZUSATZPRUEFPLAN.md`](ZUSATZPRUEFPLAN.md), machine-readable in
[`zusatzpruefplan.json`](zusatzpruefplan.json). In short:

- **List.** Every Monday from 4 Jan 2027, the 50 substances with the highest `z3_v0_p8` in the daily prediction log
  (only rows with plan `35a230a0a9bd`). Ties go by ATC5 code, ascending.
- **Agreement („bestätigt“).** The substance is also among the 50 highest values of a frozen model at the level of the
  marketing authorisation holder. Its values are combined per substance as q = 1 − Π(1 − p) and use only data from
  before that Monday. A substance without q counts as not confirmed.
- **Outcome.** As in `stockout bewertung`: a BASG report for the substance starts or first appears within 56 days.
- **Main endpoint.** Hit rate of confirmed minus not confirmed warnings within the top 50, pooled over the Mondays.
  The 95 % interval comes from a bootstrap over whole substances (B = 2000, seed 20261116). The check passes if the whole
  interval lies above 0.
- **Secondary, descriptive only.** Observed against predicted per group, horizons 28 and 84 days, and the same split
  with the challenger model E_S3z_C as the main model.
- **Dates.** Interim look at the go/no-go on 30 Apr 2027, descriptive only (at most 9 Mondays). The decisive
  evaluation covers the 26 Mondays from 4 Jan to 28 Jun 2027, once the BASG data reach 23 Aug 2027.
- **Retrospective hint, not evidence** (the test years had already been seen): confirmed warnings came true in
  21.5 / 22.4 / 27.8 % of cases, unconfirmed ones in 10.4 / 9.9 / 17.3 % (2024 / 2025 / 2026).

**What is published.** The rule, the JSON file and the evaluation script
[`../psuche/zustimmung_voraus.py`](../psuche/zustimmung_voraus.py) are byte-identical to the reference instance. The
frozen holder model, the challenger E_S3z_C and the analysis modules the script imports stay with the reference
instance; the JSON file fixes them by SHA-256, and the script refuses to evaluate if any hash differs.

| File | SHA-256 |
|---|---|
| `ZUSATZPRUEFPLAN.md` | `c5a7c610309c3839a823928e00c9281e4a3124d1b35dcf74efc723c0c22e3bb9` |
| `zusatzpruefplan.json` | `78c0cf0fa16153f8480ce26541a750aa8a080b0ad064efbb56df6a26603e714f` |
| `../psuche/zustimmung_voraus.py` | `1705b86cf33424f8965f27e4deaa76aec24c442b4d95f44f80df32559e67b81a` |
| frozen holder model (not published) | `6a501562002d09226ed673adfe13536cdd259cb0ec02d40c0361bfc3899410db` |
| frozen E_S3z_C (not published) | `3e791fb03cbef748a701c6b1259920137e42a67ff7d0a831725c1fd53a96e69b` |

To check, in this folder:

```bash
sha256sum ZUSATZPRUEFPLAN.md zusatzpruefplan.json ../psuche/zustimmung_voraus.py
```
