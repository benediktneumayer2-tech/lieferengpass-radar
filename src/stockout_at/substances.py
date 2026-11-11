"""Conservative substance normalisation: salt and hydrate forms -> base substance.

Only explicit, reviewable rules: whole salt/hydrate words are dropped, a few fused German
suffixes are cut (ZOLPIDEMTARTRAT -> ZOLPIDEM), and a small alias table handles complexes.
Esters (…PROPIONAT, …VALERAT, CILEXETIL, …) are kept because they are distinct substances.
A rule never applies if only a metal/counter-ion would remain (NATRIUMCHLORID stays).
German BASG names and English ASP names are both handled; they are not cross-matched.
"""
from __future__ import annotations

import re

# Hydrate/solvate words: always dropped after the first word.
HYDRATE_WORDS = frozenset(
    """
    HYDRAT MONOHYDRAT DIHYDRAT TRIHYDRAT TETRAHYDRAT PENTAHYDRAT HEXAHYDRAT HEMIHYDRAT SESQUIHYDRAT
    HEMIHEPTAHYDRAT PROPANDIOL WASSERFREI WASSERFREIES
    HYDRATE MONOHYDRATE DIHYDRATE TRIHYDRATE HEMIHYDRATE SESQUIHYDRATE ANHYDROUS
    """.split()
)
# Salt words: dropped after the first word unless the first word is itself an ion (MAGNESIUM DIGLUCONAT).
SALT_WORDS = HYDRATE_WORDS | frozenset(
    """
    HYDROCHLORID DIHYDROCHLORID HYDROBROMID HYDROGENTARTRAT TARTRAT HEMITARTRAT BITARTRAT
    MALEAT HYDROGENMALEAT FUMARAT HEMIFUMARAT SUCCINAT BESILAT MESILAT METHANSULFONAT
    SULFAT HEMISULFAT HYDROGENSULFAT CITRAT DIHYDROGENCITRAT PHOSPHAT DINATRIUMPHOSPHAT
    NATRIUMPHOSPHAT ACETAT GLUCONAT DIGLUCONAT NITRAT BROMID CHLORID IODID
    NATRIUM DINATRIUM KALIUM CALCIUM MAGNESIUM
    HYDROCHLORIDE DIHYDROCHLORIDE HYDROBROMIDE TARTRATE HEMITARTRATE BITARTRATE MALEATE FUMARATE
    HEMIFUMARATE SUCCINATE BESILATE BESYLATE MESILATE MESYLATE SULFATE SULPHATE CITRATE PHOSPHATE
    ACETATE GLUCONATE NITRATE BROMIDE CHLORIDE IODIDE SODIUM DISODIUM POTASSIUM
    """.split()
)
# Counter-ions that may lead a name of 3+ words ("NATRIUM PREDNISOLON SUCCINAT").
LEADING_WORDS = frozenset({"NATRIUM", "DINATRIUM", "KALIUM", "SODIUM", "POTASSIUM"})
# Fused German suffixes, longest first. Cut only if the stem has >= 4 letters, does not start with
# an ion (NATRIUMTHIOSULFAT, KUPFERDICHLORID) and is no alkyl ester (DIMETHYLFUMARAT, …ETHYLSUCCINAT).
FUSED_SUFFIXES = (
    "DIHYDROCHLORID",
    "HYDROCHLORID",
    "HYDROBROMID",
    "HYDROGENTARTRAT",
    "HYDROGENSULFAT",
    "HYDROGENSUCCINAT",
    "TARTRAT",
    "MALEAT",
    "FUMARAT",
    "SUCCINAT",
    "BESILAT",
    "MESILAT",
    "SULFAT",
    "DIGLUCONAT",
    "BROMID",
    "CHLORID",
)
# Stems that are themselves counter-ions: NATRIUMCHLORID, BARIUMSULFAT, … stay unchanged.
ION_STEMS = frozenset(
    """NATRIUM KALIUM CALCIUM MAGNESIUM BARIUM ZINK ZINN EISEN LITHIUM ALUMINIUM AMMONIUM
    CHROM KUPFER MANGAN SELEN KOBALT COBALT SILBER""".split()
)
# Explicit aliases (applied to one component after uppercasing).
ALIASES = {
    "ETHINYLESTRADIOL X BETADEX": "ETHINYLESTRADIOL",
    "ALPROSTADIL X ALFADEX": "ALPROSTADIL",
}


def split_components(wirkstoffe: str | None) -> list[str]:
    """Split a BASG `Wirkstoffe` string on commas outside parentheses."""
    parts, depth, buf = [], 0, []
    for ch in wirkstoffe or "":
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth = max(depth - 1, 0)
        if ch == "," and depth == 0:
            parts.append("".join(buf))
            buf = []
        else:
            buf.append(ch)
    parts.append("".join(buf))
    return [p.strip() for p in parts if p.strip()]


def base_substance(name: str) -> str:
    """Normalise one substance name to its base form (uppercase)."""
    text = re.sub(r"\s+", " ", name.upper()).strip()
    if text in ALIASES:
        return ALIASES[text]
    words = text.split(" ")
    while len(words) > 2 and words[0] in LEADING_WORDS:
        words = words[1:]
    drop = HYDRATE_WORDS if words[0] in ION_STEMS else SALT_WORDS
    kept = [words[0]] + [w for w in words[1:] if w not in drop]
    if len(kept) == 1:
        kept[0] = _cut_fused(kept[0])
    return " ".join(kept)


def _cut_fused(word: str) -> str:
    for suffix in FUSED_SUFFIXES:
        if word.endswith(suffix):
            stem = word[: -len(suffix)]
            ion = any(stem.startswith(i) for i in ION_STEMS)
            if len(stem) >= 4 and stem[-1].isalpha() and not ion and not stem.endswith("YL"):
                return stem
            return word
    return word


def normalise(wirkstoffe: str | None) -> tuple[str, ...]:
    """Return the sorted set of base substances; qualifiers like WASSERFREI(ES) are dropped."""
    out = set()
    for comp in split_components(wirkstoffe):
        if comp.upper() in SALT_WORDS:
            continue  # stray qualifier after a comma, e.g. "CALCIPOTRIOL, WASSERFREI"
        out.add(base_substance(comp))
    return tuple(sorted(out))


def substance_label(bases: tuple[str, ...]) -> str:
    """Stable key/label: single substance or ' + '-joined combination."""
    return " + ".join(bases)


def atc_groups(atc: str | None) -> tuple[str | None, str | None]:
    """Return (level 5, level 3) for the first ATC code, e.g. N05CF02 -> (N05CF02, N05C)."""
    code = (atc or "").split(",")[0].strip().upper()
    if not code:
        return None, None
    return (code if len(code) >= 7 else None), (code[:4] if len(code) >= 4 else None)
