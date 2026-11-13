"""Claim checkers. Each one recognises a kind of factual sentence, runs a real calculation on the
release, and returns the verdict together with everything a reviewer needs to reproduce it.

Verdicts: supported | contradicted | insufficient_evidence | not_a_claim
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field, asdict

import pandas as pd

from .claims import Number, Sentence
from .release import FILES, LAYER_LABELS, Release, is_primary


# ---------------------------------------------------------------------------- result objects
@dataclass
class SubCheck:
    label: str            # what was measured, in plain words
    claimed: str
    observed: str
    ok: bool | None       # None = shown for context only
    rule: str = ""


@dataclass
class Result:
    verdict: str
    check: str                                  # which checker produced it
    summary: str                                # one plain-language line
    subchecks: list[SubCheck] = field(default_factory=list)
    correct_value: str | None = None
    files: list[str] = field(default_factory=list)
    fields: list[str] = field(default_factory=list)
    n: int | None = None
    population: str = ""
    limitation: str = ""
    needed: str = ""                            # for insufficient evidence: what data would settle it
    alternatives: list[dict] = field(default_factory=list)   # same question, other reasonable definitions
    code: str = ""
    confidence: str = "high"
    sample_ids: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        d = asdict(self)
        d["n_sample_ids"] = len(self.sample_ids)
        d["sample_ids"] = self.sample_ids[:50]
        return d


# ---------------------------------------------------------------------------- helpers
def pct(num: int, den: int) -> float:
    return 100.0 * num / den if den else float("nan")


def fmt_pct(num: int, den: int) -> str:
    return f"{pct(num, den):.1f}% ({num:,} of {den:,})"


def matches(claim: Number, observed: float, is_pct: bool) -> tuple[bool, str]:
    """Is the stated number consistent with the data? Returns (ok, rule text)."""
    if is_pct:
        decimals = len(claim.text.split(".")[1].rstrip("% percnt")) if "." in claim.text else 0
        tol = max(1.5, 0.05 * claim.value) if claim.approx else (0.5 if decimals == 0 else 0.15)
        return abs(claim.value - observed) <= tol, f"within ±{tol:.1f} percentage points{' (claim says about)' if claim.approx else ''}"
    if claim.approx:
        tol = max(1.0, 0.03 * observed)
        return abs(claim.value - observed) <= tol, f"within ±3%{' (claim says about)'}"
    return claim.value == round(observed), "exact count"


def nearest(text_pos: int, spans: list[tuple[int, str]], prefer_before: bool = True):
    best, best_d = None, 10 ** 9
    for pos, key in spans:
        d = text_pos - pos
        if prefer_before and d < 0:
            d = -d * 3        # mentions after the number are less likely to own it
        d = abs(d)
        if d < best_d:
            best, best_d = key, d
    return best


def find_spans(text: str, patterns: dict[str, str]) -> list[tuple[int, str]]:
    out = []
    for key, pat in patterns.items():
        for m in re.finditer(pat, text, re.I):
            out.append((m.start(), key))
    return sorted(out)


def verdict_from(subs: list[SubCheck]) -> str:
    judged = [s for s in subs if s.ok is not None]
    if not judged:
        return "insufficient_evidence"
    return "supported" if all(s.ok for s in judged) else "contradicted"


def correct_from(subs: list[SubCheck]) -> str | None:
    wrong = [s for s in subs if s.ok is False]
    return "; ".join(f"{s.observed}" if len(wrong) == 1 else f"{s.label}: {s.observed}" for s in wrong) or None


def redaction_note(r: Release) -> str:
    """Organizers: keep survival rows marked Redacted (the manifest counts them) but flag them for a person."""
    sv = r.survival
    if "Redaction" not in sv:
        return ""
    red = sv[(sv.Redaction == "Redacted") & sv["sample"].map(is_primary)]
    if red.empty:
        return ""
    ids = ", ".join(red["sample"].head(5))
    return (f"Flag for review: {len(red)} primary tumor(s) have survival rows marked Redaction = 'Redacted' but still "
            f"carry OS values ({ids}). They are kept, as the organizers advise, but a person should look at them.")


# ---------------------------------------------------------------------------- vocab
SUBTYPES = {   # key -> (regex, label in PAM50Call_RNAseq, label in PAM50_mRNA_nature2012)
    "LumA": (r"\bluminal[- ]?a\b|\blum ?a\b", "LumA", "Luminal A"),
    "LumB": (r"\bluminal[- ]?b\b|\blum ?b\b", "LumB", "Luminal B"),
    "Basal": (r"\bbasal(?:[- ]like)?\b", "Basal", "Basal-like"),
    "Her2": (r"\bher2[- ]enriched\b|\bher2[- ]e\b|\bher2 subtype\b", "Her2", "HER2-enriched"),
    "Normal": (r"\bnormal[- ]like\b", "Normal", "Normal-like"),
}
SUBTYPE_NAMES = {"LumA": "Luminal A", "LumB": "Luminal B", "Basal": "Basal-like", "Her2": "HER2-enriched", "Normal": "Normal-like"}

RECEPTORS = {  # key -> regex for "<receptor>-positive/negative"
    "ER": r"\b(?:er|estrogen[- ]receptor|oestrogen[- ]receptor)[- ]?(positive|negative|\+|-)(?!\w)",
    "PR": r"\b(?:pr|pgr|progesterone[- ]receptor)[- ]?(positive|negative|\+|-)(?!\w)",
    "HER2": r"\b(?:her2|erbb2|her2/neu)[- ]?(positive|negative|\+|-)(?!\w)",
}
RECEPTOR_COLS = {
    "ER": ("breast_carcinoma_estrogen_receptor_status", "ER_Status_nature2012"),
    "PR": ("breast_carcinoma_progesterone_receptor_status", "PR_Status_nature2012"),
    "HER2": ("lab_proc_her2_neu_immunohistochemistry_receptor_status", "HER2_Final_Status_nature2012"),
}
TRIPLE_NEG = r"triple[- ]negative|\btnbc\b"

LAYER_PATTERNS = {
    "survival": r"\bsurvival\b|follow[- ]up",
    "mutation": r"\bmutations?\b|\bmutation data\b|somatic",
    "copy_number": r"copy[- ]number|\bcnvs?\b|gistic",
    "rna": r"\brna\b|rna[- ]seq|gene expression|transcriptom",
    "protein": r"\bprotein\b|\brppa\b|proteom",
    "clinical": r"\bclinical (?:data|records?|information)\b",
    "slides": r"\bslides?\b|\bimages?\b|patholog",
}

PROTEIN_ALIASES = {
    r"\ber[- ]?alpha\b|\ber[- ]?α\b|estrogen receptor alpha|\beralpha\b": "ERALPHA",
    r"\bher2 protein\b|\bher2 \(protein\)": "HER2",
    r"\bpr protein\b|progesterone receptor protein": "PR",
    r"\be[- ]cadherin\b": "ECADHERIN",
}
UP = r"\b(higher|greater|elevated|increased|more|raised|larger|stronger)\b"
DOWN = r"\b(lower|reduced|decreased|less|smaller|weaker)\b"

RESPONSE_WORDS = r"respon(?:d|ded|ds|se|der)|benefit|work(?:s|ed)? best|effective|efficacy|guide (?:treatment|therapy)|predict(?:s|ive)? (?:response|outcome|benefit)|\bcure|improv(?:e|ed|es) (?:outcome|survival)|should (?:receive|be treated)"
THERAPY_WORDS = r"therap(?:y|ies)|treat(?:ment|ed)|chemo|tamoxifen|hormon|endocrine|radiation|radiotherapy|drug|surgery|neoadjuvant"
THERAPY_COLS = {
    r"radiation|radiotherapy": "radiation_therapy",
    r"targeted": "targeted_molecular_therapy",
    r"neoadjuvant": "history_of_neoadjuvant_treatment",
    r"pharmaceutical": "additional_pharmaceutical_therapy",
}

STOP_GENES = {"RNA", "DNA", "TCGA", "BRCA", "HER2", "ER", "PR", "PAM50", "RPPA", "IHC", "OS", "DSS", "PFI", "DFI",
              "AI", "CT", "FFPE", "IDC", "MB", "TNBC", "AJCC", "LUMA", "LUMB", "ALL", "AND", "THE", "NOT", "WITH"}


# ---------------------------------------------------------------------------- checkers
class Checker:
    name = "base"

    def applies(self, s: Sentence, r: Release) -> bool:
        raise NotImplementedError

    def run(self, s: Sentence, r: Release) -> Result:
        raise NotImplementedError


class TreatmentChecker(Checker):
    """Treatment response / benefit claims. The release has no response outcomes, so these can't be confirmed."""
    name = "treatment_response"

    def applies(self, s, r):
        t = s.lower
        return bool(re.search(RESPONSE_WORDS, t)) or (bool(re.search(THERAPY_WORDS, t)) and not s.numbers)

    def run(self, s, r):
        t = s.lower
        c = r.clinical_primary
        present = {}
        for pat, col in THERAPY_COLS.items():
            if col in c:
                vc = c[col].value_counts(dropna=False)
                present[col] = {str(k): int(v) for k, v in vc.items()}
        subs = [SubCheck(f"Field `{col}`", "—", ", ".join(f"{k}: {v}" for k, v in vc.items()), None,
                         "shown for context: yes/no whether a treatment was given, not whether it worked")
                for col, vc in present.items()]
        mentions_protein = re.search("|".join(PROTEIN_ALIASES), t)
        if mentions_protein and r.has_file("protein"):
            n_prot = len([x for x in r.protein.columns if is_primary(x)])
            subs.append(SubCheck("Primary tumors with protein (RPPA) data", "—", f"{n_prot:,}", None, "context"))
        hormone = re.search(r"hormon|endocrine|tamoxifen|aromatase", t)
        needed = ("Per-patient treatment records (which drug, e.g. hormone therapy, and when) and a response or outcome "
                  "measure linked to each sample, such as response assessment or recurrence after that treatment. "
                  "Even then, an observational association would not show that the treatment caused the response.")
        return Result(
            verdict="insufficient_evidence", check=self.name,
            summary=("The release has no treatment-response outcomes"
                     + (" and no field recording hormone therapy specifically" if hormone else "")
                     + ", so this claim cannot be checked against the data."),
            subchecks=subs, files=[FILES["clinical"]] + ([FILES["protein"]] if mentions_protein else []),
            fields=list(present), population="Primary tumors in clinical.tsv",
            n=len(c),
            limitation="Treatment fields only record whether a therapy was given (YES/NO, often missing). "
                       "This is also a clinical-sounding claim; the tool makes no treatment statements.",
            needed=needed,
            code="c = clinical[clinical.sampleID.str[13:15]=='01']\n"
                 + "\n".join(f"c['{col}'].value_counts(dropna=False)" for col in present)
                 + "\n# no column records response to therapy",
            confidence="high")


class NotAClaimChecker(Checker):
    """Recommendations, opinions and background statements with nothing to measure."""
    name = "not_a_claim"

    RECO = r"\bwe (?:recommend|suggest|propose|plan|hope)|\bshould\b|future work|could (?:help|guide|be used)|\bmay be useful|\bmerits?\b"
    MEASURABLE = (UP + "|" + DOWN + r"|worse|better|poorer|shorter|longer|surviv|prognos|largest|smallest|most (?:common|frequent)|majority|minority|\bhalf\b|\ball\b|\bnone\b|\bno\b \w+ (?:have|has)|differ|disagree|agree|match")

    def applies(self, s, r):
        t = s.lower
        if s.numbers:
            return False
        if re.search(self.RECO, t):
            return True
        return not re.search(self.MEASURABLE, t)

    def run(self, s, r):
        t = s.lower
        kind = "a recommendation" if re.search(self.RECO, t) else "background or opinion"
        return Result(verdict="not_a_claim", check=self.name,
                      summary=f"This sentence is {kind}, not a factual claim about the data, so it is not scored.",
                      confidence="medium",
                      limitation="A reviewer can mark it as a claim if they disagree.")


class SlidesChecker(Checker):
    name = "slide_counts"

    def applies(self, s, r):
        return bool(re.search(r"\bslides?\b", s.lower)) and bool(s.numbers) and r.slides is not None

    def run(self, s, r):
        sl = r.slides
        total = len(sl)
        frozen = int((~sl.slide_kind.str.startswith("diagnostic")).sum())
        dx = total - frozen
        spans = find_spans(s.text, {"frozen": r"frozen", "diagnostic": r"diagnostic|ffpe", "total": r"\bslides?\b"})
        obs = {"frozen": frozen, "diagnostic": dx, "total": total}
        subs = []
        for i, num in enumerate(s.numbers):
            # the words right after a number say what it counts: "1,978 are frozen", "3,111 slides"
            seg_end = s.numbers[i + 1].start if i + 1 < len(s.numbers) else len(s.text)
            after = s.text[num.end:seg_end].lower()
            if re.match(r"\W*(?:\w+\W+){0,3}?(frozen)", after):
                key = "frozen"
            elif re.match(r"\W*(?:\w+\W+){0,3}?(diagnostic|ffpe)", after):
                key = "diagnostic"
            elif re.match(r"\s*(?:pathology |tissue |whole[- ]slide )?(?:slides|images)", after):
                key = "total"
            else:
                key = nearest(num.start, [(p, k) for p, k in spans if k != "total"]) or "total"
            if num.is_percent:
                ok, rule = matches(num, pct(obs[key], total), True)
                subs.append(SubCheck(f"Share of slides that are {key}", num.text, fmt_pct(obs[key], total), ok, rule))
            else:
                ok, rule = matches(num, obs[key], False)
                subs.append(SubCheck(f"{key.capitalize()} slides", num.text, f"{obs[key]:,}", ok, rule))
        v = verdict_from(subs)
        return Result(verdict=v, check=self.name,
                      summary=f"slide_manifest.csv lists {total:,} slides: {dx:,} diagnostic (FFPE) and {frozen:,} frozen sections.",
                      subchecks=subs, correct_value=correct_from(subs) if v == "contradicted" else None,
                      files=["slide_manifest.csv"], fields=["slide_kind"], n=total, population="All TCGA-BRCA slides in IDC",
                      limitation="Counts come from the challenge's slide manifest (IDC), not from the release files.",
                      code="sl = pd.read_csv('slide_manifest.csv')\nsl.slide_kind.str.startswith('diagnostic').value_counts()")


class SubtypeChecker(Checker):
    name = "subtype_share"

    def applies(self, s, r):
        return any(re.search(p[0], s.lower) for p in SUBTYPES.values())

    def run(self, s, r):
        t = s.lower
        c = r.clinical_primary
        use_2012 = bool(re.search(r"2012|nature|mrna|microarray|original tcga", t))
        col = "PAM50_mRNA_nature2012" if use_2012 else "PAM50Call_RNAseq"
        alt_col = "PAM50Call_RNAseq" if use_2012 else "PAM50_mRNA_nature2012"
        idx = 2 if use_2012 else 1
        calls = c[col].dropna()
        counts = calls.value_counts()
        den_called, den_all = len(calls), len(c)
        all_primary = bool(re.search(r"\ball (?:\d[\d,]* )?primary|\bof (?:the )?(?:\d[\d,]* )?primary tumou?rs(?! with)", t)) \
            and not re.search(r"subtype call|subtyped|with an? (?:rna )?subtype|assigned", t)
        den = den_all if all_primary else den_called
        den_label = "all primary tumors" if all_primary else f"primary tumors with a `{col}` call"

        spans = find_spans(s.text, {k: v[0] for k, v in SUBTYPES.items()})
        mentioned = list(dict.fromkeys(k for _, k in spans))
        subs = []
        for num in s.numbers:
            key = nearest(num.start, spans)
            if key is None:
                continue
            obs = int(counts.get(SUBTYPES[key][idx], 0))
            if num.is_percent:
                ok, rule = matches(num, pct(obs, den), True)
                subs.append(SubCheck(f"{SUBTYPE_NAMES[key]} share of {den_label}", num.text, fmt_pct(obs, den), ok, rule))
            elif num.value <= den_all:
                ok, rule = matches(num, obs, False)
                subs.append(SubCheck(f"{SUBTYPE_NAMES[key]} tumors", num.text, f"{obs:,}", ok, rule))
        largest = counts.idxmax() if len(counts) else None
        if mentioned and re.search(r"largest|most common|most frequent|biggest|dominant|majority", t):
            key = mentioned[0]
            ok = SUBTYPES[key][idx] == largest
            if re.search(r"majority", t) and not re.search(r"largest|most", t):
                ok = pct(int(counts.get(SUBTYPES[key][idx], 0)), den) > 50
                subs.append(SubCheck(f"{SUBTYPE_NAMES[key]} is a majority (>50%)", "yes", fmt_pct(int(counts.get(SUBTYPES[key][idx], 0)), den), ok, "share > 50%"))
            else:
                subs.append(SubCheck(f"{SUBTYPE_NAMES[key]} is the largest subtype", "yes",
                                     f"largest is {largest} ({int(counts.max()):,})", ok, "rank by count"))
        alt = c[alt_col].dropna()
        alt_counts = alt.value_counts()
        alts = []
        for key in mentioned:
            alts.append({"definition": f"Use `{alt_col}` instead",
                         "value": fmt_pct(int(alt_counts.get(SUBTYPES[key][2 if not use_2012 else 1], 0)), len(alt)),
                         "subtype": SUBTYPE_NAMES[key]})
            alts.append({"definition": "Denominator = all primary tumors" if not all_primary else f"Denominator = tumors with a `{col}` call",
                         "value": fmt_pct(int(counts.get(SUBTYPES[key][idx], 0)), den_called if all_primary else den_all),
                         "subtype": SUBTYPE_NAMES[key]})
        both = c[[col, alt_col]].dropna()
        norm = {"Luminal A": "LumA", "Luminal B": "LumB", "Basal-like": "Basal", "HER2-enriched": "Her2", "Normal-like": "Normal"}
        a, b = (both[col], both[alt_col]) if not use_2012 else (both[alt_col], both[col])
        disagree = int((a != b.map(norm)).sum())
        v = verdict_from(subs)
        return Result(
            verdict=v, check=self.name,
            summary=f"Counted PAM50 subtype calls in `{col}`: " + ", ".join(f"{k} {fmt_pct(int(n), den_called)}" for k, n in counts.items()) + ".",
            subchecks=subs, correct_value=correct_from(subs) if v == "contradicted" else None,
            files=[FILES["clinical"]], fields=["sampleID", col], n=den, population=den_label,
            limitation=(f"{den_all - den_called:,} of {den_all:,} primary tumors have no `{col}` call. "
                        f"The two subtype columns disagree on {disagree:,} of {len(both):,} tumors that have both "
                        f"({pct(disagree, len(both)):.0f}%), so the answer depends on which call you use."),
            alternatives=alts,
            code=(f"c = clinical[clinical.sampleID.str[13:15] == '01']\n"
                  f"calls = c['{col}'].dropna()          # n = {den_called}\n"
                  f"calls.value_counts(normalize=True) * 100"),
            sample_ids=sorted(calls.index.tolist()),
            confidence="high" if subs else "low")


class ProteinCompareChecker(Checker):
    """'<protein> is higher in <group>' style claims."""
    name = "protein_comparison"

    def _protein(self, t, r):
        for pat, name in PROTEIN_ALIASES.items():
            if re.search(pat, t):
                return name
        return None

    def applies(self, s, r):
        t = s.lower
        return bool(self._protein(t, r)) and bool(re.search(UP + "|" + DOWN, t)) and r.has_file("protein")

    def run(self, s, r):
        t = s.lower
        prot = self._protein(t, r)
        direction = "up" if re.search(UP, t) else "down"
        c = r.clinical_primary
        P = r.protein
        samples = [x for x in P.columns if is_primary(x)]
        vals = P.loc[prot, samples].dropna()
        group_desc, a_ids, b_ids, fields = None, [], [], [f"protein_rppa row {prot}"]
        for key, pat in RECEPTORS.items():
            m = re.search(pat, t)
            if m:
                col = RECEPTOR_COLS[key][0]
                pol = "Positive" if m.group(1) in ("positive", "+") else "Negative"
                other = "Negative" if pol == "Positive" else "Positive"
                st = c[col].reindex(vals.index)
                a_ids = st[st == pol].index.tolist()
                b_ids = st[st == other].index.tolist()
                group_desc = (f"{key}-{pol.lower()}", f"{key}-{other.lower()}", col)
                fields.append(col)
                break
        if group_desc is None:
            for key, (pat, lab, _) in SUBTYPES.items():
                if re.search(pat, t):
                    st = c["PAM50Call_RNAseq"].reindex(vals.index)
                    a_ids = st[st == lab].index.tolist()
                    b_ids = st[st.notna() & (st != lab)].index.tolist()
                    group_desc = (SUBTYPE_NAMES[key], "other subtypes", "PAM50Call_RNAseq")
                    fields.append("PAM50Call_RNAseq")
                    break
        if group_desc is None or not a_ids or not b_ids:
            return Result(verdict="insufficient_evidence", check=self.name,
                          summary=f"Found {prot} protein data, but could not tell which groups the claim compares.",
                          files=[FILES["protein"]], fields=fields, confidence="low",
                          needed="Name the two groups being compared (e.g. ER-positive vs ER-negative).")
        a, b = vals[a_ids], vals[b_ids]
        diff_mean, diff_med = a.mean() - b.mean(), a.median() - b.median()
        ok = (diff_mean > 0 and diff_med > 0) if direction == "up" else (diff_mean < 0 and diff_med < 0)
        overlap = int((a < b.median()).sum()) if direction == "up" else int((a > b.median()).sum())
        subs = [SubCheck(f"{prot} in {group_desc[0]} vs {group_desc[1]}", f"{'higher' if direction == 'up' else 'lower'}",
                         f"mean {a.mean():.2f} vs {b.mean():.2f}; median {a.median():.2f} vs {b.median():.2f}", ok,
                         "both mean and median differ in the stated direction"),
                SubCheck("Tumors per group", "—", f"{len(a):,} vs {len(b):,}", None, "context")]
        v = "supported" if ok else "contradicted"
        return Result(
            verdict=v, check=self.name,
            summary=f"{prot} protein is {'higher' if diff_mean > 0 else 'lower'} in {group_desc[0]} tumors "
                    f"(median {a.median():.2f}) than {group_desc[1]} tumors (median {b.median():.2f}).",
            subchecks=subs,
            correct_value=None if ok else f"{prot} is {'higher' if diff_mean > 0 else 'lower'} in {group_desc[0]}: mean {a.mean():.2f} vs {b.mean():.2f}",
            files=[FILES["protein"], FILES["clinical"]], fields=fields, n=len(a) + len(b),
            population=f"Primary tumors with {prot} protein and a {group_desc[0]}/{group_desc[1]} label",
            limitation=(f"Groups overlap: {overlap:,} of {len(a):,} {group_desc[0]} tumors are on the other side of the "
                        f"{group_desc[1]} median. Only {len(a) + len(b):,} of {len(c):,} primary tumors have both measurements. "
                        "An association in research data, not a clinical finding."),
            code=(f"P = protein[[s for s in protein.columns if s[13:15]=='01']]\n"
                  f"st = clinical.set_index('sampleID')['{group_desc[2]}']\n"
                  f"vals = P.loc['{prot}'].dropna()\n"
                  f"vals.groupby(st.reindex(vals.index)).describe()"),
            sample_ids=sorted(a_ids + b_ids), confidence="medium")


class ReceptorShareChecker(Checker):
    name = "receptor_share"

    def applies(self, s, r):
        t = s.lower
        return bool(s.numbers) and (any(re.search(p, t) for p in RECEPTORS.values()) or bool(re.search(TRIPLE_NEG, t)))

    def run(self, s, r):
        t = s.lower
        c = r.clinical_primary
        use_2012 = bool(re.search(r"2012|nature", t))
        spans = []
        for key, pat in RECEPTORS.items():
            for m in re.finditer(pat, t):
                pol = "Positive" if m.group(1) in ("positive", "+") else "Negative"
                spans.append((m.start(), (key, pol)))
        for m in re.finditer(TRIPLE_NEG, t):
            spans.append((m.start(), ("TNBC", "Negative")))
        spans.sort()
        subs, alts, fields = [], [], set()
        for num in s.numbers:
            hit = nearest(num.start, spans)
            if hit is None:
                continue
            key, pol = hit
            if key == "TNBC":
                cols = [RECEPTOR_COLS[k][1 if use_2012 else 0] for k in ("ER", "PR", "HER2")]
                sub = c[cols]
                definite = sub[sub.isin(["Positive", "Negative"]).all(axis=1)]
                obs = int((definite == "Negative").all(axis=1).sum())
                den = len(definite)
                label = "Triple-negative (ER-, PR-, HER2- by IHC)"
                fields.update(cols)
            else:
                col = RECEPTOR_COLS[key][1 if use_2012 else 0]
                if col not in c:
                    continue
                fields.add(col)
                vc = c[col].value_counts()
                obs = int(vc.get(pol, 0))
                den = int(vc.get("Positive", 0) + vc.get("Negative", 0))
                label = f"{key}-{pol.lower()}"
                alts.append({"definition": f"{label}, denominator = all {len(c):,} primary tumors", "value": fmt_pct(obs, len(c))})
                alts.append({"definition": f"{label}, denominator = any recorded result (incl. equivocal/indeterminate)",
                             "value": fmt_pct(obs, int(vc.sum()))})
            if num.is_percent:
                ok, rule = matches(num, pct(obs, den), True)
                ok_alt = matches(num, pct(obs, len(c)), True)[0]
                subs.append(SubCheck(f"{label} share of tumors with a definite result", num.text, fmt_pct(obs, den),
                                     ok or ok_alt, rule + ("; matches only with all primary tumors as denominator" if ok_alt and not ok else "")))
            else:
                ok, rule = matches(num, obs, False)
                subs.append(SubCheck(f"{label} tumors", num.text, f"{obs:,}", ok, rule))
        v = verdict_from(subs)
        return Result(verdict=v, check=self.name,
                      summary="Counted clinical receptor test results among primary tumors: " +
                              "; ".join(f"{sc.label}: {sc.observed}" for sc in subs) + ".",
                      subchecks=subs, correct_value=correct_from(subs) if v == "contradicted" else None,
                      files=[FILES["clinical"]], fields=sorted(fields), n=len(c), population="Primary tumors in clinical.tsv",
                      limitation="Receptor status is the clinical test result recorded at diagnosis; missing, equivocal and "
                                 "indeterminate results are left out of the main denominator.",
                      alternatives=alts,
                      code="c = clinical[clinical.sampleID.str[13:15]=='01']\n" +
                           "\n".join(f"c['{f}'].value_counts(dropna=False)" for f in sorted(fields)))


class MutationChecker(Checker):
    name = "mutation_frequency"

    def _genes(self, s, r):
        toks = set(re.findall(r"\b[A-Z][A-Z0-9]{1,9}\b", s.text)) - STOP_GENES
        return [g for g in re.findall(r"\b[A-Z][A-Z0-9]{1,9}\b", s.text) if g in toks and g in r.mutation.index]

    def applies(self, s, r):
        return bool(re.search(r"mutat", s.lower)) and r.has_file("mutation") and bool(re.search(r"\b[A-Z][A-Z0-9]{1,9}\b", s.text)) \
            and bool(self._genes(s, r))

    def run(self, s, r):
        M = r.mutation
        cols = [x for x in M.columns if is_primary(x)]
        mut = M[cols] > 0
        den = len(cols)
        genes = list(dict.fromkeys(self._genes(s, r)))
        spans = [(m.start(), m.group(0)) for m in re.finditer(r"\b[A-Z][A-Z0-9]{1,9}\b", s.text) if m.group(0) in genes]
        subs = []
        freq = mut.sum(axis=1)
        for num in s.numbers:
            g = nearest(num.start, spans)
            if g is None:
                continue
            obs = int(freq[g])
            if num.is_percent:
                ok, rule = matches(num, pct(obs, den), True)
                subs.append(SubCheck(f"{g} mutated", num.text, fmt_pct(obs, den), ok, rule))
            else:
                ok, rule = matches(num, obs, False)
                subs.append(SubCheck(f"Tumors with a {g} mutation", num.text, f"{obs:,}", ok, rule))
        top = freq.sort_values(ascending=False)
        if re.search(r"most (?:frequently|commonly|often) mutated|top mutated|most common mutation", s.lower):
            g = genes[0]
            rank = int((top > top[g]).sum()) + 1
            subs.append(SubCheck(f"{g} is the most frequently mutated gene", "rank 1",
                                 f"rank {rank}; top genes: " + ", ".join(f"{k} {fmt_pct(int(v), den)}" for k, v in top.head(3).items()),
                                 rank == 1, "rank by number of mutated primary tumors"))
        v = verdict_from(subs)
        return Result(verdict=v, check=self.name,
                      summary="; ".join(f"{g}: mutated in {fmt_pct(int(freq[g]), den)} primary tumors with mutation data" for g in genes) + ".",
                      subchecks=subs, correct_value=correct_from(subs) if v == "contradicted" else None,
                      files=[FILES["mutation"]], fields=[f"gene row {g}" for g in genes], n=den,
                      population="Primary tumors in mutation_gene_level.tsv.gz",
                      limitation=f"Only {den:,} primary tumors have mutation data. A value > 0 counts as mutated "
                                 "(gene-level non-silent calls); the file does not say which variants.",
                      alternatives=[{"definition": f"{g}, denominator = all {len(r.primary_ids):,} primary tumors",
                                     "value": fmt_pct(int(freq[g]), len(r.primary_ids))} for g in genes],
                      code=("M = mutation[[s for s in mutation.columns if s[13:15]=='01']]\n"
                            + "\n".join(f"(M.loc['{g}'] > 0).mean() * 100   # n = {den}" for g in genes)))


class AgeChecker(Checker):
    name = "age"

    def applies(self, s, r):
        return bool(re.search(r"\b(median|mean|average) age\b|\baged?\b|\byears old\b|older than|younger than", s.lower)) and bool(s.numbers)

    def run(self, s, r):
        c = r.clinical_primary
        col = "age_at_initial_pathologic_diagnosis"
        age = pd.to_numeric(c[col], errors="coerce").dropna()
        t = s.lower
        subs = []
        for num in s.numbers:
            if num.is_percent:
                m = re.search(r"(older than|over|above|younger than|under|below)\s+(\d+)", t)
                if not m:
                    continue
                cut = float(m.group(2))
                k = int((age > cut).sum()) if m.group(1) in ("older than", "over", "above") else int((age < cut).sum())
                ok, rule = matches(num, pct(k, len(age)), True)
                subs.append(SubCheck(f"Share {m.group(1)} {m.group(2)} at diagnosis", num.text, fmt_pct(k, len(age)), ok, rule))
            elif re.search(r"median age", t) and 15 < num.value < 100:
                ok = abs(num.value - age.median()) <= (2 if num.approx else 0.5)
                subs.append(SubCheck("Median age at diagnosis", num.text, f"{age.median():.1f} years", ok, "within ±0.5 years (±2 if 'about')"))
            elif re.search(r"(mean|average) age", t) and 15 < num.value < 100:
                ok = abs(num.value - age.mean()) <= (2 if num.approx else 0.5)
                subs.append(SubCheck("Mean age at diagnosis", num.text, f"{age.mean():.1f} years", ok, "within ±0.5 years (±2 if 'about')"))
        v = verdict_from(subs)
        return Result(verdict=v, check=self.name, summary=f"Age at diagnosis for {len(age):,} primary tumors: median {age.median():.0f}, "
                                                        f"range {age.min():.0f}–{age.max():.0f}.",
                      subchecks=subs, correct_value=correct_from(subs) if v == "contradicted" else None,
                      files=[FILES["clinical"]], fields=[col], n=len(age), population="Primary tumors with a recorded age",
                      limitation="Age is reported in whole years at initial diagnosis.",
                      code=f"age = pd.to_numeric(clinical[clinical.sampleID.str[13:15]=='01']['{col}'], errors='coerce')\nage.describe()")


class SurvivalChecker(Checker):
    name = "survival"

    def applies(self, s, r):
        t = s.lower
        if not re.search(r"\bsurviv|\bdied\b|\bdeaths?\b|follow[- ]up|prognos|mortality|alive", t):
            return False
        # "survival" used as the name of a data layer ("535 have survival, mutation and RNA data") is a coverage claim
        n_layers = sum(bool(re.search(p, t)) for p in LAYER_PATTERNS.values())
        if n_layers >= 2 or re.search(r"survival (?:data|records|information|layer)", t):
            return False
        return True

    def run(self, s, r):
        t = s.lower
        sv = r.survival
        sv = sv[sv["sample"].map(is_primary)].dropna(subset=["OS"])
        deaths, n = int(sv.OS.sum()), len(sv)
        comparative = re.search(r"worse|better|poorer|shorter|longer|higher risk|lower risk|prognos|than", t)
        subs = []
        if not comparative:
            for num in s.numbers:
                if re.search(r"follow[- ]up", t) and not num.is_percent:
                    unit = 365.25 if "year" in t else (30.44 if "month" in t else 1)
                    med = sv["OS.time"].median() / unit
                    ok = abs(num.value - med) <= max(0.5, 0.05 * med)
                    subs.append(SubCheck("Median follow-up (OS.time)", num.text, f"{med:.1f} {'years' if unit > 300 else 'months' if unit > 1 else 'days'}", ok, "within 5%"))
                elif num.is_percent:
                    ok, rule = matches(num, pct(deaths, n), True)
                    subs.append(SubCheck("Share with a recorded death (OS = 1)", num.text, fmt_pct(deaths, n), ok, rule))
                else:
                    ok, rule = matches(num, deaths, False)
                    subs.append(SubCheck("Recorded deaths (OS = 1)", num.text, f"{deaths:,}", ok, rule))
        if comparative or not subs:
            return Result(verdict="insufficient_evidence", check=self.name,
                          summary=f"Survival data exists ({n:,} primary tumors, {deaths:,} recorded deaths), but a survival comparison "
                                  "needs a time-to-event analysis with adjustment for stage and age; a simple count can't settle it.",
                          files=[FILES["survival"]], fields=["OS", "OS.time"], n=n, population="Primary tumors with overall survival",
                          limitation="Follow-up is short for many patients and events are few, so crude comparisons are unreliable. "
                                     + redaction_note(r),
                          needed="A pre-specified Kaplan–Meier / Cox analysis with confidence intervals, reviewed by a statistician.",
                          code="sv = survival[survival['sample'].str[13:15]=='01']\nsv[['OS','OS.time']].describe()",
                          confidence="medium")
        v = verdict_from(subs)
        return Result(verdict=v, check=self.name, summary=f"{deaths:,} recorded deaths among {n:,} primary tumors with survival data.",
                      subchecks=subs, correct_value=correct_from(subs) if v == "contradicted" else None,
                      files=[FILES["survival"]], fields=["OS", "OS.time"], n=n, population="Primary tumors with overall survival",
                      limitation="OS = overall survival from the TCGA Clinical Data Resource; many patients have short follow-up. "
                                 + redaction_note(r),
                      code="sv = survival[survival['sample'].str[13:15]=='01'].dropna(subset=['OS'])\nsv.OS.sum(), len(sv), sv['OS.time'].median()")


class CohortChecker(Checker):
    """Counts of tumors, samples, patients, and how many have each data layer."""
    name = "cohort_coverage"

    ENTITIES = [
        ("normal", r"\s*(?:\w+\s){0,2}?(?:solid tissue )?normal"),
        ("metastatic", r"\s*(?:\w+\s){0,2}?metasta"),
        ("primary", r"\s*(?:\w+\s){0,2}?(?:primary|breast tumou?rs|tumou?rs|cases)"),
        ("patients", r"\s*(?:\w+\s){0,2}?(?:patients|participants|women|people|donors)"),
        ("samples", r"\s*(?:\w+\s){0,2}?samples"),
    ]

    def applies(self, s, r):
        t = s.lower
        return bool(s.numbers) and bool(re.search(r"tumou?rs|samples|patients|cases|cohort|participants|women", t))

    def run(self, s, r):
        m = r.membership
        t = s.lower
        prim = m[m.type_code == "01"]
        totals = {"primary": len(prim), "patients": m.patient_id.nunique(), "samples": len(m),
                  "normal": int((m.type_code == "11").sum()), "metastatic": int((m.type_code == "06").sum())}
        default = "primary" if re.search(r"primary|tumou?r", t) else ("patients" if "patient" in t else "samples")
        subs, used_layers, missing = [], set(), set()
        last_entity = None
        nums = s.numbers
        for i, num in enumerate(nums):
            seg_end = nums[i + 1].start if i + 1 < len(nums) else len(s.text)
            after = s.text[num.end:seg_end]
            entity = next((k for k, pat in self.ENTITIES if re.match(pat, after, re.I)), None)
            layers = [k for k, pat in LAYER_PATTERNS.items() if re.search(pat, after, re.I)]
            if re.search(r"\b(?:all|every) (?:five|5|six|6) (?:data )?layers|every (?:data )?layer|all (?:data )?layers", after, re.I):
                layers = ["survival", "mutation", "copy_number", "rna", "protein"]
            if entity is None and not layers:
                continue
            ent = entity or last_entity or default
            last_entity = ent
            base = {"primary": prim, "samples": m, "normal": m[m.type_code == "11"], "metastatic": m[m.type_code == "06"],
                    "patients": m}[ent]
            if layers:
                mask = pd.Series(True, index=base.index)
                for L in layers:
                    if L == "slides":
                        if "n_slides" in base:
                            col = "n_diagnostic_slides" if re.search(r"diagnostic", after, re.I) else "n_slides"
                            mask &= base[col] > 0
                    elif f"has_{L}" in base:
                        if not r.has_file(L):
                            missing.add(L)
                            continue
                        mask &= base[f"has_{L}"]
                used_layers.update(layers)
                sel = base[mask]
                obs = sel.patient_id.nunique() if ent == "patients" else len(sel)
                label = f"{ent.capitalize()} with " + ", ".join(LAYER_LABELS.get(L, L) for L in layers)
                if missing & set(layers):
                    subs.append(SubCheck(label, num.text, f"can't count: no {', '.join(LAYER_LABELS[L] for L in missing)} file "
                                         f"in this release ({len(sel):,} have the other layers)", None, "layer missing"))
                    continue
                if num.is_percent:
                    ok, rule = matches(num, pct(obs, totals[ent]), True)
                    subs.append(SubCheck(label, num.text, fmt_pct(obs, totals[ent]), ok, rule))
                else:
                    ok, rule = matches(num, obs, False)
                    subs.append(SubCheck(label, num.text, f"{obs:,}", ok, rule))
            elif not num.is_percent:
                obs = totals[ent]
                ok, rule = matches(num, obs, False)
                subs.append(SubCheck(f"Number of {ent if ent != 'primary' else 'primary tumors'}", num.text, f"{obs:,}", ok, rule))
        if not subs:
            return Fallback().run(s, r)
        v = verdict_from(subs)
        needed = ""
        if missing and v != "contradicted":
            v = "insufficient_evidence"
            needed = f"This release has no {', '.join(LAYER_LABELS[L] for L in sorted(missing))} file; use a release that includes it."
        flags =" & ".join(f"has_{L}" for L in sorted(used_layers) if L != "slides")
        layer_counts = ", ".join(f"{LAYER_LABELS[L]} {int(prim[f'has_{L}'].sum()):,}" for L in LAYER_LABELS if r.has_file(L))
        return Result(verdict=v, check=self.name,
                      summary=f"Built sample membership from the release files: {totals['primary']:,} primary tumors "
                              f"({layer_counts}).",
                      subchecks=subs, correct_value=correct_from(subs) if v == "contradicted" else None,
                      files=[FILES[k] for k in FILES if r.has_file(k)], fields=["sample barcode (chars 14–15 = sample type)"],
                      n=totals["primary"], population="Samples in the release (01 = primary tumor)",
                      limitation=" ".join(x for x in [
                          r.membership_note,
                          "Values inside a file may still be missing. Each extra layer you require shrinks the cohort.",
                          redaction_note(r) if "survival" in used_layers else ""] if x),
                      needed=needed,
                      code=("# membership = which files each sample barcode appears in\n"
                            "prim = membership[membership.sample_id.str[13:15] == '01']\n"
                            + (f"prim[{' & '.join(f'prim.{f}' for f in flags.split(' & '))}].shape[0]" if flags else "len(prim)")),
                      sample_ids=sorted(prim.sample_id) if not used_layers else [])


class Fallback(Checker):
    name = "unrecognised"

    def applies(self, s, r):
        return True

    def run(self, s, r):
        return Result(verdict="insufficient_evidence", check=self.name,
                      summary="The tool has no automatic check for this kind of statement. A reviewer must check it by hand.",
                      confidence="low",
                      needed="A reviewer should identify the field(s) this claim refers to, or mark it as not a claim.",
                      limitation="Unchecked by the tool: this is not a judgement that the data can't answer it.")


CHECKERS: list[Checker] = [TreatmentChecker(), NotAClaimChecker(), SlidesChecker(), SurvivalChecker(),
                           ProteinCompareChecker(), SubtypeChecker(), ReceptorShareChecker(), MutationChecker(), AgeChecker(),
                           CohortChecker(), Fallback()]


def borderline(res: Result) -> bool:
    """A judged number that only just passes or fails: flag it so the reviewer looks twice."""
    for sc in res.subchecks:
        if sc.ok is None:
            continue
        try:
            c = float(re.sub(r"[^\d.]", "", sc.claimed))
            o = float(re.sub(r"[^\d.]", "", sc.observed.split("%")[0].split(" ")[0]))
        except ValueError:
            continue
        if "%" in sc.claimed and 0.8 <= abs(c - o) <= 2.5:
            return True
    return False


def check_sentence(s: Sentence, r: Release) -> Result:
    for ch in CHECKERS:
        try:
            if ch.applies(s, r):
                res = ch.run(s, r)
                if borderline(res):
                    res.confidence = "medium"
                    res.limitation = ("Borderline: the stated number is close to the tolerance, so a reviewer should decide. "
                                      + res.limitation)
                return res
        except Exception as e:   # a checker bug must never crash a live audit
            return Result(verdict="insufficient_evidence", check=ch.name, confidence="low",
                          summary=f"The {ch.name} check failed on this sentence ({type(e).__name__}: {e}). Review by hand.",
                          needed="Manual check by a reviewer.")
    return Fallback().run(s, r)
