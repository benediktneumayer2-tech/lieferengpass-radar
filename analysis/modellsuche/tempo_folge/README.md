# Follow-up check: signal speed of the new countries

Fixed on **17 Nov 2026**, before any out-of-sample result with speed features existed, and independent of the result
below. It is a separate analysis question and changes nothing in the frozen models or the test plan
(`models/pruefplan.json`, plan hash `35a230a0a9bd`).

**Question.** Does the speed at which shortage reports spread across countries add to the forecast of the frozen
challenger model E_S3z_C, once the countries that have been archived daily only since October 2026 are included?

**Why a follow-up.** A retrospective search (17 Nov 2026) tested speed features on the sources with a long daily
history. Verdict: *unclear*. No candidate beat E_S3z_C; in the add-on test all odds ratios lay between 0.99 and 1.04
per standard deviation, with no lower bound above 1. A large gain is unlikely, a small one could neither be shown nor
ruled out, and the positive control failed in the rebuild step, so formally no conclusion holds. Nothing from the
search went into a model. Belgium, Spain, France, Finland and the EMA daily lists could not be tested backwards: before
October 2026 the archive holds only the reports that were still listed then.

The binding text is German: [`FOLGEPRUEFUNG.md`](FOLGEPRUEFUNG.md), machine-readable in [`regel.json`](regel.json).
In short:

- **Dates.** Every Monday from 2 Nov 2026 to 28 Jun 2027 (35 reference dates). Evaluation not before 1 Sep 2027.
- **Cases and outcome.** Substances available in Austria without an active BASG report on the reference date; outcome:
  a BASG report for the substance starts or first appears within 56 days.
- **Baseline.** The frozen E_S3z_C, not retrained.
- **Feature.** One speed index over 12 foreign sources (IT, PL, HU, EMA including its daily lists, US FDA, BE, ES, FR,
  FI, CZ, SK, SI; never the German BfArM). It sums five scaled components: change in the number of reporting countries
  over 28 and 56 days, countries with a new report in the last 28 days against the 28 before, how close the second
  country followed the first, and recent against older new reports. A report counts from the first daily archive file
  that lists it.
- **Test.** Logistic regression of the outcome on the baseline's logit and the standardised index; odds ratio per
  standard deviation, block bootstrap over reference dates (blocks of 8, B = 2000, seed 20261117), Holm correction
  over all cases and the cases with a foreign or holder signal.
- **Decision (threshold OR 1.10 per SD).** *Found* if the Holm lower bound lies above 1 on all cases; this leads to a
  separate test plan for a model with these sources, not to a direct change. *Ruled out* if the Holm upper bound lies
  below 1.10 on all cases and on the signal cases. Otherwise *unclear*.
- **Limits.** The first dates partly see only the initial stock of BE, ES and FR; 35 dates are a quarter of the
  retrospective test period, so a small effect is harder to detect.

**What is published.** The rule, the JSON file and `SHA256SUMS` are byte-identical to the reference instance. The
frozen E_S3z_C, the analysis code and the archive stay with the reference instance; the JSON file fixes the model by
SHA-256. Finland's list is archived only by the reference instance
([differences](../../../documentation/DATENQUELLEN.md#4-unterschiede-zur-referenzinstanz)).

| File | SHA-256 |
|---|---|
| `FOLGEPRUEFUNG.md` | `681a548b445ff30c4a4ed47ba0951d6468beb02a68e690a1be31342eedd47932` |
| `regel.json` | `6eb88cd8c57df18ba9952b1caf42d70bc13839b632881b3a7acfd81067e94dcf` |
| frozen E_S3z_C (not published) | `3e791fb03cbef748a701c6b1259920137e42a67ff7d0a831725c1fd53a96e69b` |

To check, in this folder:

```bash
sha256sum -c SHA256SUMS
```
