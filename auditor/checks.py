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
from .scope import needed_for, statement_kind


# ---------------------------------------------------------------------------- result objects
@dataclass
class SubCheck:
    label: str            # what was measured, in plain words
    claimed: str
    observed: str
    ok: bool | None       # None = shown for context only
    rule: str = ""

    def __post_init__(self):
        # numpy booleans (np.False_) fail `is False` checks and JSON export: store a plain bool
        if self.ok is not None:
            self.ok = bool(self.ok)


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
    unit = " percentage points" if is_pct else ""
    if claim.lo is not None:                      # a range: "10-15%", "between 15% and 20%"
        slack = 0.5 if is_pct else 0
        return (claim.lo - slack <= observed <= claim.hi + slack,
                f"inside the stated range {claim.lo:g}–{claim.hi:g}{'%' if is_pct else ''}"
                f"{f' (±{slack:g}{unit} for rounding)' if slack else ''}")
    if claim.cmp:                                 # "more than 1,000", "fewer than 800", "more than half"
        ok = {">": observed > claim.value, ">=": observed >= claim.value,
              "<": observed < claim.value, "<=": observed <= claim.value}[claim.cmp]
        words = {">": "more than", ">=": "at least", "<": "less than", "<=": "at most"}[claim.cmp]
        return ok, f"{words} {claim.value:g}{'%' if is_pct else ''}, as the claim says"
    if is_pct:
        if claim.word:                            # "a third", "one in five": inherently loose
            tol = max(2.5, 0.10 * claim.value)
            return abs(claim.value - observed) <= tol, f"within ±{tol:.1f}{unit} (claim is written as a fraction)"
        decimals = len(claim.text.split(".")[1].rstrip("% percnt")) if "." in claim.text else 0
        tol = max(1.5, 0.05 * claim.value) if claim.approx else (0.5 if decimals == 0 else 0.15)
        return abs(claim.value - observed) <= tol, f"within ±{tol:.1f}{unit}{' (claim says about)' if claim.approx else ''}"
    if claim.approx:
        tol = max(1.0, 0.05 * observed)
        return abs(claim.value - observed) <= tol, "within ±5% (claim says about)"
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
    MEASURABLE = (UP + "|" + DOWN + r"|\bcommon\b|\brare\b|\bfrequent|worse|better|poorer|shorter|longer|surviv|prognos|largest|smallest|most (?:common|frequent)|majority|minority|\bhalf\b|\ball\b|\bnone\b|\bno\b \w+ (?:have|has)|differ|disagree|agree|match")

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


ENTITY_WORDS = r"(?:patients|participants|women|people|donors|cases|samples|tumou?rs|primary|normal|metasta\w*)"


def precision_ok(num: Number, observed: float) -> tuple[bool, str]:
    """Measured values (sizes, averages): right if the data rounds to the stated value at the precision it was written."""
    d = len(num.text.split(".")[1].rstrip("% percnt")) if "." in num.text else 0
    tol = 0.5 * 10 ** -d + 1e-9
    if num.approx:
        return abs(num.value - observed) <= max(tol, 0.05 * abs(observed)), "within 5% (claim says about)"
    return abs(num.value - observed) <= tol, f"rounds to the stated value (within {tol:.2g})"


class ManifestChecker(Checker):
    """Claims about the two manifests: slide counts and kinds, slide sizes, scan magnification, licence, viewer links,
    slides per patient/sample, and sample_manifest.csv's own slide total. Numbers that count patients or samples
    *with* slides are checked by the cohort checker, which reads sample_manifest.csv, and merged in here."""
    name = "manifest"

    KINDS = {"diagnostic": r"diagnostic|ffpe", "frozen": r"frozen", "top section": r"\btop\b",
             "bottom section": r"\bbottom\b", "middle section": r"\bmiddle\b"}

    def applies(self, s, r):
        if r.slides is None and r.sample_manifest is None:
            return False
        t = s.lower
        return bool(re.search(r"\bslides?\b|whole[- ]slide|\bcc[ -]by\b", t)) and (
            bool(s.numbers) or bool(re.search(r"\b(?:all|every|each)\b", t)))

    @staticmethod
    def classify(s, i, num):
        """What does this number count? Decided by the words right after it ("1,978 are frozen", "338 MB")."""
        nums = s.numbers
        seg_end = nums[i + 1].start if i + 1 < len(nums) else len(s.text)
        after = s.text[num.end:seg_end].lower()
        before = s.text[:num.start].lower()
        if re.search(r"cc[ -]by[ -]?$", before) or re.search(r"\bversion\s*$", before):
            return "skip", after                                    # the "3.0" in "CC BY 3.0"
        if re.match(r"\s*(?:mb|gb|tb|megabytes?|gigabytes?|terabytes?)\b", after):
            return "size", after
        if re.match(r"(?:\s*(?:x|×)(?!\w))|(?:\s*-?\s*(?:times|fold)\s+(?:magnification|objective))", after):
            return "objective", after
        # "2.8 slides per patient", "2.8 slides are available per patient", "3 slides for each sample"
        if re.match(r"\s*(?:\w+\s+){0,2}?slides?\s+(?:\w+\s+){0,3}?(?:per|for each|for every)\s+(?:patient|sample|case|tumou?r|woman|person)", after) or (
                re.match(r"\s*(?:\w+\s+){0,2}?slides?\b", after)
                and re.search(r"average\b|\bmean\b|on average\b", s.lower) and re.search(r"\b(?:each|per|every|a)\s+(?:patient|sample|case|tumou?r)", s.lower)):
            return "average", after
        if re.fullmatch(r"\s*(?:of|out of)\s+(?:the\s+|all\s+)?", after):
            return "entity", after                                  # "1,098 of the 1,101 primary tumors ..."
        head = re.split(r"\bslides?\b|\bsections?\b|\bimages?\b", after, maxsplit=1)[0]
        if re.search(ENTITY_WORDS, head) and not re.search(r"\bof (?:the |all )?(?:\w+ )?slides\b", after):
            return "entity", after
        return "slide", after

    def run(self, s, r):
        sl, sm, t = r.slides, r.sample_manifest, s.lower
        subs, files, fields, alts, entity_nums, used_sm = [], [], set(), [], [], False
        nums = s.numbers
        kind_n, total = {}, 0
        if sl is not None:
            files.append("slide_manifest.csv")
            total = len(sl)
            kind_n["diagnostic"] = int(sl.slide_kind.str.startswith("diagnostic").sum())
            kind_n["frozen"] = total - kind_n["diagnostic"]
            for k in ("top section", "bottom section", "middle section"):
                kind_n[k] = int(sl.slide_kind.str.contains(k.split()[0]).sum())
        says_sm = bool(re.search(r"sample[_ ]manifest|slides_for_sample", t))
        obj_m = re.search(r"(\d+)\s*(?:x|×)(?!\w)", s.text)
        for i, num in enumerate(nums):
            kind, after = self.classify(s, i, num)
            if kind == "skip":
                continue
            if kind == "entity":
                entity_nums.append(num.text)
                continue
            if sl is None:
                continue
            if kind == "size":
                unit = re.match(r"\s*(\w)", after).group(1)                       # m / g / t
                pre = s.text[:num.start]
                stat = nearest(num.start, find_spans(pre, {"median": r"median|typical", "mean": r"average|mean",
                                                           "total": r"total|together|combined|altogether|in all",
                                                           "max": r"largest|biggest|maximum", "min": r"smallest|minimum"})) or (
                    "total" if re.search(r"total|together|combined|altogether|in all", after) else "median")
                mb = float({"median": sl.size_mb.median(), "mean": sl.size_mb.mean(), "total": sl.size_mb.sum(),
                            "max": sl.size_mb.max(), "min": sl.size_mb.min()}[stat])
                bases = {"m": [(1, "MB")], "g": [(1e3, "GB"), (1024, "GiB")], "t": [(1e6, "TB"), (1024 ** 2, "TiB")]}[unit]
                tries = [(mb / b, lab, *precision_ok(num, mb / b)) for b, lab in bases]
                best = next((x for x in tries if x[2]), tries[0])
                subs.append(SubCheck(f"{stat.capitalize()} slide size", f"{num.text} {bases[0][1]}",
                                     f"{best[0]:,.2f} {best[1]} ({mb:,.1f} MB)", best[2], best[3]))
                fields.add("size_mb")
            elif kind == "objective":
                fields.add("objective")
                if any(n.is_percent for n in nums):
                    continue                                                   # the % number carries the check
                v = num.value
                n_at = int((sl.objective == v).sum())
                if re.search(r"\b(?:all|every)\b", t):
                    subs.append(SubCheck(f"All slides scanned at {v:g}x", "all", f"{n_at:,} of {total:,}", n_at == total, "all rows"))
                elif re.search(r"\b(?:most|majority|mainly|mostly|usually|typically)\b", t):
                    subs.append(SubCheck(f"Most slides scanned at {v:g}x", "most", fmt_pct(n_at, total), n_at > total / 2,
                                         "more than half"))
                else:
                    subs.append(SubCheck(f"Slides scanned at {v:g}x", f"{num.text}x", fmt_pct(n_at, total), n_at > 0,
                                         "at least one slide"))
                alts.append({"definition": "Objective values in slide_manifest.csv",
                             "value": ", ".join(f"{k:g}x: {c:,}" for k, c in sl.objective.value_counts().items())
                                      + f", missing: {int(sl.objective.isna().sum())}"})
            elif kind == "average":
                ent = "patient" if re.search(r"\b(?:per|each|every|a)\s+(?:patient|case|participant|woman)", s.lower) else "sample"
                col = "patient_id" if ent == "patient" else "sample_id"
                with_sl = sl[col].nunique()
                avg = total / with_sl
                ok, rule = precision_ok(num, avg)
                subs.append(SubCheck(f"Slides per {ent} (those with at least one slide)", num.text,
                                     f"{avg:.2f} ({total:,} / {with_sl:,})", ok, rule))
                if sm is not None:
                    den = sm.patient_id.nunique() if ent == "patient" else len(sm)
                    alts.append({"definition": f"Per {ent} in sample_manifest.csv, including those with no slide",
                                 "value": f"{total / den:.2f} ({total:,} / {den:,})"})
            else:   # a count or share of slides
                if num.is_percent and obj_m and not re.search(r"cc[ -]by", t):
                    v = float(obj_m.group(1))
                    n_at = int((sl.objective == v).sum())
                    ok, rule = matches(num, pct(n_at, total), True)
                    subs.append(SubCheck(f"Share of slides scanned at {v:g}x", num.text, fmt_pct(n_at, total), ok, rule))
                    alts.append({"definition": "Only slides with a recorded objective",
                                 "value": fmt_pct(n_at, int(sl.objective.notna().sum()))})
                    fields.add("objective")
                    continue
                if num.is_percent and re.search(r"cc[ -]by", t):
                    n_l = int(sl.license.str.contains("CC BY", case=False).sum())
                    ok, rule = matches(num, pct(n_l, total), True)
                    subs.append(SubCheck("Share of slides under CC BY", num.text, fmt_pct(n_l, total), ok, rule))
                    fields.add("license")
                    continue
                seg_kind = next((k for k, pat in self.KINDS.items()
                                 if re.match(r"\W*(?:\w+\W+){0,3}?(?:" + pat + ")", after)), None)
                if seg_kind:
                    key = seg_kind
                elif re.match(r"\s*(?:\w+\s+){0,2}?(?:slides|images)", after):
                    key = None
                else:
                    key = nearest(num.start, find_spans(s.text, self.KINDS))
                fields.add("slide_kind")
                sm_total = int(sm.slides_for_sample.sum()) if sm is not None else None
                if key is None and says_sm and sm is not None:
                    obs, used_sm = sm_total, True
                    label = "Slides counted in sample_manifest.csv (sum of slides_for_sample)"
                    fields.add("slides_for_sample")
                else:
                    obs = kind_n[key] if key else total
                    label = f"{key.capitalize()} slides" if key else "Slides listed in slide_manifest.csv"
                if num.is_percent:
                    ok, rule = matches(num, pct(obs, total), True)
                    subs.append(SubCheck(f"Share of slides that are {key or 'listed'}", num.text, fmt_pct(obs, total), ok, rule))
                else:
                    ok, rule = matches(num, obs, False)
                    subs.append(SubCheck(label, num.text, f"{obs:,}", ok, rule))
                    if not ok and key is None and not says_sm and sm_total is not None and num.value == sm_total:
                        subs[-1].observed += (f" ({num.text} is the sample_manifest.csv total, which leaves out "
                                              f"{total - sm_total:,} slides)")
        # licence / viewer claims with no number of their own ("all slides are CC BY 3.0")
        if sl is not None and re.search(r"cc[ -]by", t) and re.search(r"\b(?:all|every|each)\b", t) and not any(
                n.is_percent for n in nums):
            lic = sl.license.value_counts()
            stated = re.search(r"cc[ -]by(?:[ -](?:nc|sa|nd))*(?:[ -]\d\.\d)?", t).group(0)
            ok = len(lic) == 1 and re.sub(r"[ -]", "", stated) == re.sub(r"[ -]", "", lic.index[0].lower())
            subs.append(SubCheck("Every slide has the stated licence", "all " + stated.upper(),
                                 "; ".join(f"{k}: {c:,}" for k, c in lic.items()), ok, "all rows"))
            fields.add("license")
        if sl is not None and re.search(r"viewer|link|url", t) and re.search(r"\b(?:all|every|each)\b", t):
            n_v = int(sl.viewer_url.notna().sum())
            subs.append(SubCheck("Slides with a viewer link", "all", f"{n_v:,} of {total:,}", n_v == total, "all rows"))
            fields.add("viewer_url")
        cohort = None
        if entity_nums:   # "1,062 patients have a diagnostic slide": sample_manifest.csv via the cohort checker
            cohort = CohortChecker().run(s, r)
            subs += [sc for sc in cohort.subchecks if sc.claimed in entity_nums]
            files.append("sample_manifest.csv" if sm is not None else "release files")
            fields.add("sample_id")
        if used_sm:
            files.append("sample_manifest.csv")
        if not subs:
            na = NotAClaimChecker()
            return na.run(s, r) if na.applies(s, r) else Fallback().run(s, r)
        v = verdict_from(subs)
        summary = (f"slide_manifest.csv lists {total:,} slides from {sl.patient_id.nunique():,} patients: "
                   f"{kind_n['diagnostic']:,} diagnostic (FFPE) and {kind_n['frozen']:,} frozen sections."
                   if sl is not None else "Checked against sample_manifest.csv.")
        limitation = " ".join(x for x in [
            r.manifest_note,
            cohort.limitation if cohort else "",
            "Slide facts come from the challenge's manifests (NCI Imaging Data Commons), not from the release data files.",
        ] if x)
        return Result(verdict=v, check=self.name, summary=summary, subchecks=subs,
                      correct_value=correct_from(subs) if v == "contradicted" else None,
                      files=list(dict.fromkeys(files)), fields=sorted(fields), n=total or None,
                      population="TCGA-BRCA slides and samples listed in the manifests", limitation=limitation,
                      alternatives=alts,
                      code=("sl = pd.read_csv('slide_manifest.csv'); sm = pd.read_csv('sample_manifest.csv')\n"
                            "sl.slide_kind.value_counts(); sl.size_mb.median(); sl.objective.value_counts()\n"
                            "len(sl) / sl.patient_id.nunique(); sm.slides_for_sample.sum()\n"
                            "sl[~sl.sample_id.isin(sm.sample_id)]   # slides the sample manifest doesn't list"))


class SubtypeChecker(Checker):
    name = "subtype_share"
    # "Basal" in an RPPA, Pan-Cancer, methylation or miRNA cluster is a different classification from the PAM50 call
    OTHER_CLASSIFICATION = r"\brppa\b|cluster|pancan|pan[- ]cancer|methylation|mirna|\bcna\b"

    def applies(self, s, r):
        return any(re.search(p[0], s.lower) for p in SUBTYPES.values()) and not re.search(self.OTHER_CLASSIFICATION, s.lower)

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
        # "Luminal A and Luminal B together account for 70%": one combined share, not two separate ones
        together = len(mentioned) > 1 and bool(re.search(r"\btogether\b|\bcombined\b|\bbetween them\b|\bin total\b", t))
        for num in s.numbers:
            if together:
                keys = mentioned
                obs = int(sum(counts.get(SUBTYPES[k][idx], 0) for k in keys))
                name = " + ".join(SUBTYPE_NAMES[k] for k in keys)
            else:
                key = nearest(num.start, spans)
                if key is None:
                    continue
                obs = int(counts.get(SUBTYPES[key][idx], 0))
                name = SUBTYPE_NAMES[key]
            if num.is_percent:
                ok, rule = matches(num, pct(obs, den), True)
                subs.append(SubCheck(f"{name} share of {den_label}", num.text, fmt_pct(obs, den), ok, rule))
            elif num.value <= den_all:
                ok, rule = matches(num, obs, False)
                subs.append(SubCheck(f"{name} tumors", num.text, f"{obs:,}", ok, rule))
        largest = counts.idxmax() if len(counts) else None
        # "the third most common", "second largest": a rank other than first
        ORD = {"second": 2, "2nd": 2, "third": 3, "3rd": 3, "fourth": 4, "4th": 4, "fifth": 5, "5th": 5}
        rk = re.search(r"\b(second|2nd|third|3rd|fourth|4th|fifth|5th)[- ](?:most common|most frequent|largest|biggest)", t)
        least = re.search(r"\b(?:least common|rarest|smallest)\b", t)
        if mentioned and (rk or least):
            key = mentioned[0]
            order = list(counts.sort_values(ascending=False).index)
            lab = SUBTYPES[key][idx]
            want = ORD[rk.group(1)] if rk else len(order)
            got = order.index(lab) + 1 if lab in order else None
            ranking = ", ".join(f"{k} {int(v):,}" for k, v in counts.sort_values(ascending=False).items())
            subs.append(SubCheck(f"{SUBTYPE_NAMES[key]} rank among subtypes", f"rank {want}" + (" (least common)" if least else ""),
                                 f"rank {got}: {ranking}", got == want, "rank by count"))
        elif mentioned and re.search(r"largest|most common|most frequent|biggest|dominant|majority", t):
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
            named = sorted((m.start(), key, lab) for key, (pat, lab, _) in SUBTYPES.items() for m in [re.search(pat, t)] if m)
            if named:
                st = c["PAM50Call_RNAseq"].reindex(vals.index)
                _, key, lab = named[0]
                a_ids = st[st == lab].index.tolist()
                if len(named) >= 2:          # "higher in Luminal A than in Basal-like": compare the two groups named
                    _, key2, lab2 = named[1]
                    b_ids = st[st == lab2].index.tolist()
                    group_desc = (SUBTYPE_NAMES[key], SUBTYPE_NAMES[key2], "PAM50Call_RNAseq")
                else:
                    b_ids = st[st.notna() & (st != lab)].index.tolist()
                    group_desc = (SUBTYPE_NAMES[key], "other subtypes", "PAM50Call_RNAseq")
                fields.append("PAM50Call_RNAseq")
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
                alts.append({"definition": f"Triple-negative, denominator = all {len(c):,} primary tumors",
                             "value": fmt_pct(obs, len(c))})
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
                # Judge by the main definition. If the number only fits another denominator, say so: the reviewer
                # must ask which one the author meant (the next-step logic turns this into "ask the author").
                subs.append(SubCheck(f"{label} share of tumors with a definite result", num.text, fmt_pct(obs, den),
                                     ok, rule + (f"; it would match with all {len(c):,} primary tumors as the denominator "
                                                 f"({fmt_pct(obs, len(c))}), so ask which one the author used"
                                                 if ok_alt and not ok else "")))
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
        return bool(re.search(r"mutat|\baltered\b|alteration", s.lower)) and r.has_file("mutation") \
            and bool(re.search(r"\b[A-Z][A-Z0-9]{1,9}\b", s.text)) and bool(self._genes(s, r))

    # "in 80% of basal-like tumors", "of ER-positive cases": the group the percentage is taken within
    GROUP_TAIL = r"(?:\s+(?:breast\s+)?(?:tumou?rs|cases|samples|cancers|patients))"

    def subgroup(self, text, r):
        t = text.lower()
        c = r.clinical_primary
        use_2012 = bool(re.search(r"2012|nature|pam50_mrna", t))
        for key, (pat, lab_rna, lab_2012) in SUBTYPES.items():
            if re.search(r"\b(?:of|in|among)\s+(?:all\s+|the\s+)?(?:" + pat + r")" + self.GROUP_TAIL, t):
                col, lab = ("PAM50_mRNA_nature2012", lab_2012) if use_2012 else ("PAM50Call_RNAseq", lab_rna)
                return f"{SUBTYPE_NAMES[key]} ({col})", set(c.index[c[col] == lab]), col
        if re.search(r"\b(?:of|in|among)\s+(?:all\s+|the\s+)?(?:" + TRIPLE_NEG + r")" + self.GROUP_TAIL, t):
            cols = [RECEPTOR_COLS[k][0] for k in ("ER", "PR", "HER2")]
            return "triple-negative", set(c.index[(c[cols] == "Negative").all(axis=1)]), ", ".join(cols)
        for key, pat in RECEPTORS.items():
            m = re.search(r"\b(?:of|in|among)\s+(?:all\s+|the\s+)?" + pat.replace(r"(?!\w)", "") + self.GROUP_TAIL, t)
            if m:
                col = RECEPTOR_COLS[key][0]
                val = "Positive" if m.group(1) in ("positive", "+") else "Negative"
                return f"{key}-{val.lower()}", set(c.index[c[col] == val]), col
        return None

    def run(self, s, r):
        M = r.mutation
        cols = [x for x in M.columns if is_primary(x)]
        grp = self.subgroup(s.text, r)
        group_note = ""
        if grp:
            label, ids, gcol = grp
            cols = [x for x in cols if x in ids]
            group_note = f" among {label} primary tumors with mutation data"
        mut = M[cols] > 0
        den = len(cols)
        genes = list(dict.fromkeys(self._genes(s, r)))
        spans = [(m.start(), m.group(0)) for m in re.finditer(r"\b[A-Z][A-Z0-9]{1,9}\b", s.text) if m.group(0) in genes]
        subs = []
        freq = mut.sum(axis=1)
        each = len(genes) > 1 and bool(re.search(r"\beach\b|\bboth\b|\brespectively\b", s.lower))
        for num in s.numbers:
            targets = genes if (each and num.is_percent) else [nearest(num.start, spans)]
            for g in targets:
                if g is None:
                    continue
                obs = int(freq[g])
                if num.is_percent:
                    ok, rule = matches(num, pct(obs, den), True)
                    subs.append(SubCheck(f"{g} mutated{group_note}", num.text, fmt_pct(obs, den), ok, rule))
                else:
                    ok, rule = matches(num, obs, False)
                    subs.append(SubCheck(f"Tumors with a {g} mutation{group_note}", num.text, f"{obs:,}", ok, rule))
        top = freq.sort_values(ascending=False)
        m = re.search(r"(?:the\s+)?(?:\b(two|three|four|five|2|3|4|5)\s+)?(?:most (?:frequently|commonly|often) "
                      r"(?:mutated|altered)|top(?:\s+\w+)? mutated|most common(?:ly)? mutat\w*)", s.lower)
        if m:
            k = {"two": 2, "three": 3, "four": 4, "five": 5}.get(m.group(1) or "", int(m.group(1)) if (m.group(1) or "").isdigit() else 0)
            k = k or 1
            named = genes[:max(k, 1)] if k > 1 else genes[:1]
            for g in named:
                rank = int((top > top[g]).sum()) + 1
                subs.append(SubCheck(f"{g} is among the {k} most frequently mutated genes{group_note}" if k > 1
                                     else f"{g} is the most frequently mutated gene{group_note}",
                                     f"rank <= {k}" if k > 1 else "rank 1",
                                     f"rank {rank}; top genes: " + ", ".join(f"{kk} {fmt_pct(int(v), den)}" for kk, v in top.head(max(3, k)).items()),
                                     rank <= k, "rank by number of mutated primary tumors"))
        # "GATA3 is mutated more often than MAP3K1"
        cm = re.search(r"\b(more|less)\s+(?:often|frequently|commonly)\b|\b(more|less)\s+common\b", s.lower)
        if len(genes) >= 2 and cm and "than" in s.lower:
            a, b = genes[0], genes[1]
            more = (cm.group(1) or cm.group(2)) == "more"
            fa, fb = int(freq[a]), int(freq[b])
            subs.append(SubCheck(f"{a} mutated {'more' if more else 'less'} often than {b}{group_note}",
                                 f"{a} {'>' if more else '<'} {b}",
                                 f"{a} {fmt_pct(fa, den)} vs {b} {fmt_pct(fb, den)}", fa > fb if more else fa < fb,
                                 "compare counts of mutated primary tumors"))
        v = verdict_from(subs)
        return Result(verdict=v, check=self.name,
                      summary="; ".join(f"{g}: mutated in {fmt_pct(int(freq[g]), den)} primary tumors with mutation data" for g in genes) + ".",
                      subchecks=subs, correct_value=correct_from(subs) if v == "contradicted" else None,
                      files=[FILES["mutation"]], fields=[f"gene row {g}" for g in genes], n=den,
                      population="Primary tumors in mutation_gene_level.tsv.gz" + (group_note and f", restricted to {grp[0]} tumors (field {grp[2]})"),
                      limitation=f"Only {den:,} primary tumors have mutation data. A value > 0 counts as mutated "
                                 "(gene-level non-silent calls); the file does not say which variants.",
                      alternatives=[{"definition": f"{g}, denominator = all {len(r.primary_ids):,} primary tumors",
                                     "value": fmt_pct(int(freq[g]), len(r.primary_ids))} for g in genes],
                      code=("M = mutation[[s for s in mutation.columns if s[13:15]=='01']]\n"
                            + "\n".join(f"(M.loc['{g}'] > 0).mean() * 100   # n = {den}" for g in genes)))


class CopyNumberChecker(Checker):
    """'<GENE> is amplified / deeply deleted / gained / lost in N% of tumors' from GISTIC thresholded calls."""
    name = "copy_number_frequency"
    EVENTS = [("amplified", r"amplif", lambda x: x == 2, "high-level amplification (GISTIC = 2)"),
              ("deeply deleted", r"deep(?:ly)?[- ]delet|homozygous(?:ly)?[- ]delet", lambda x: x == -2,
               "deep deletion (GISTIC = -2)"),
              ("gained", r"\bgain(?:ed|s)?\b", lambda x: x >= 1, "any copy-number gain (GISTIC >= 1)"),
              ("lost", r"\bloss(?:es)?\b|\blost\b|\bdelet", lambda x: x <= -1, "any copy-number loss (GISTIC <= -1)")]

    @staticmethod
    def table(r):
        if getattr(r, "_cn_table", None) is None:
            r._cn_table = pd.read_csv(r.path("copy_number"), sep="\t", index_col=0)
        return r._cn_table

    def _genes(self, s, r):
        idx = self.table(r).index
        return [(m.start(), m.group(0)) for m in re.finditer(r"\b[A-Z][A-Z0-9-]{1,14}\b", s.text)
                if m.group(0) not in STOP_GENES and m.group(0) in idx]

    def _event(self, t):
        return next((e for e in self.EVENTS if re.search(e[1], t)), None)

    def applies(self, s, r):
        return bool(s.numbers) and r.has_file("copy_number") and self._event(s.lower) is not None and bool(self._genes(s, r))

    def run(self, s, r):
        cn = self.table(r)
        word, _, test, label = self._event(s.lower)
        prim = [x for x in cn.columns if is_primary(x)]
        group = MutationChecker().subgroup(s.text, r)
        cols = [x for x in prim if x in group[1]] if group else prim
        genes = self._genes(s, r)
        subs, fields = [], [f"copy_number_gistic row(s)"]
        for num in s.numbers:
            gene = nearest(num.start, genes, prefer_before=True)
            if gene is None:
                continue
            k = int(cn.loc[gene, cols].map(test).sum())
            where = f" within {group[0]}" if group else ""
            if num.is_percent:
                ok, rule = matches(num, pct(k, len(cols)), True)
                subs.append(SubCheck(f"{gene} {word}{where}: share of primary tumors with copy-number calls", num.text,
                                     fmt_pct(k, len(cols)), ok, rule))
            else:
                ok, rule = matches(num, k, False)
                subs.append(SubCheck(f"{gene} {word}{where}: primary tumors", num.text, f"{k:,}", ok, rule))
            fields.append(gene)
        v = verdict_from(subs)
        return Result(verdict=v, check=self.name,
                      summary=f"Counted {label} in copy_number_gistic among {len(cols):,} primary tumors"
                              + (f" ({group[0]})" if group else "") + ": "
                              + "; ".join(f"{sc.label.split(':')[0]}: {sc.observed}" for sc in subs) + ".",
                      subchecks=subs, correct_value=correct_from(subs) if v == "contradicted" else None,
                      files=[FILES["copy_number"]] + ([FILES["clinical"]] if group else []),
                      fields=fields + ([group[2]] if group else []), n=len(cols),
                      population="Primary tumors with copy-number calls" + (f", {group[0]}" if group else ""),
                      limitation="GISTIC2 thresholded calls: 2 = high-level amplification, -2 = deep deletion, +1/-1 = "
                                 "low-level gain/loss (noisier). Copy number is not expression: an amplified gene is not "
                                 "proven to be overexpressed.",
                      code="cn = copy_number.set_index('Gene Symbol')\nprim = [c for c in cn.columns if c[13:15]=='01']\n"
                           + "\n".join(f"(cn.loc['{g}', prim] {'== 2' if word == 'amplified' else '== -2' if word == 'deeply deleted' else '>= 1' if word == 'gained' else '<= -1'}).mean()"
                                       for g in fields[1:]),
                      confidence="high")


class AgeChecker(Checker):
    name = "age"

    def applies(self, s, r):
        return bool(re.search(r"\b(median|mean|average) age\b|\baged?\b|\byears old\b|older than|younger than|"
                              r"(?:before|after) (?:the )?age", s.lower)) and bool(s.numbers)

    def run(self, s, r):
        c = r.clinical_primary
        col = "age_at_initial_pathologic_diagnosis"
        age = pd.to_numeric(c[col], errors="coerce").dropna()
        t = s.lower
        subs = []
        for num in s.numbers:
            if num.is_percent:
                m = re.search(r"(older than|over|above|after (?:the )?age(?: of)?|younger than|under|below|"
                              r"before (?:the )?age(?: of)?)\s+(\d+)", t[num.end:]) or \
                    re.search(r"(older than|over|above|after (?:the )?age(?: of)?|younger than|under|below|"
                              r"before (?:the )?age(?: of)?)\s+(\d+)", t)
                if not m:
                    continue
                cut = float(m.group(2))
                older = m.group(1).startswith(("older", "over", "above", "after"))
                k = int((age > cut).sum()) if older else int((age < cut).sum())
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

    # which endpoint a claim is about: progression -> PFI, recurrence / disease-free -> DFI, cancer death -> DSS, else OS
    ENDPOINTS = [("PFI", r"progression|progressed", "a progression event (PFI = 1)"),
                 ("DFI", r"recurren|relapse|disease[- ]free", "a recurrence (DFI = 1)"),
                 ("DSS", r"disease[- ]specific|died (?:of|from) (?:breast )?cancer|cancer[- ](?:related |specific )?deaths?",
                  "a disease-specific death (DSS = 1)")]
    EVENT_WORDS = r"\bdied\b|\bdeaths?\b|deceased|mortality|progression|progressed|recurren|relapse|disease[- ]free|disease[- ]specific"

    def applies(self, s, r):
        t = s.lower
        if re.search(r"lost (?:to )?follow|follow[- ]?up (?:case|form|submission)|report form|submission reason", t):
            return False          # record-keeping fields, not outcomes
        if not re.search(r"\bsurviv|\bdied\b|\bdeaths?\b|follow[- ]up|prognos|mortality|alive|progression|progressed|"
                         r"recurren|relapse|disease[- ]free|disease[- ]specific", t):
            return False
        # "survival" used as the name of a data layer ("535 have survival, mutation and RNA data") is a coverage claim
        n_layers = sum(bool(re.search(p, t)) for p in LAYER_PATTERNS.values())
        if n_layers >= 2:
            return False
        # "...with survival data had a recorded death": the deaths are the claim, survival data is the population
        if re.search(r"survival (?:data|records|information|layer)", t) and not re.search(self.EVENT_WORDS, t):
            return False
        return True

    def run(self, s, r):
        t = s.lower
        ep, ep_label = "OS", "a recorded death (OS = 1)"
        for key, pat, label in self.ENDPOINTS:
            if re.search(pat, t):
                ep, ep_label = key, label
                break
        sv = r.survival
        sv = sv[sv["sample"].map(is_primary)].dropna(subset=[ep])
        deaths, n = int(sv[ep].sum()), len(sv)
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
                    subs.append(SubCheck(f"Share with {ep_label}", num.text, fmt_pct(deaths, n), ok, rule))
                else:
                    ok, rule = matches(num, deaths, False)
                    subs.append(SubCheck(f"Tumors with {ep_label}", num.text, f"{deaths:,}", ok, rule))
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
        return Result(verdict=v, check=self.name,
                      summary=f"{deaths:,} of {n:,} primary tumors with {ep} status have {ep_label}.",
                      subchecks=subs, correct_value=correct_from(subs) if v == "contradicted" else None,
                      files=[FILES["survival"]], fields=[ep, f"{ep}.time"], n=n, population=f"Primary tumors with {ep} status",
                      limitation=f"{ep} from the TCGA Clinical Data Resource; follow-up length differs between patients, so this "
                                 "is a raw count, not a survival probability. " + redaction_note(r),
                      code=f"sv = survival[survival['sample'].str[13:15]=='01'].dropna(subset=['{ep}'])\n"
                           f"sv['{ep}'].sum(), len(sv), sv['OS.time'].median()")


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
        segs = [s.text[n.end:(nums[i + 1].start if i + 1 < len(nums) else len(s.text))] for i, n in enumerate(nums)]
        # "1,098 of the 1,101 primary tumors have a slide": the first number is the count, the second the denominator
        denom = {i + 1 for i in range(len(nums) - 1)
                 if re.fullmatch(r"\s*(?:of|out of)\s+(?:the\s+|all\s+)?", segs[i], re.I) and not nums[i].is_percent}
        for i, num in enumerate(nums):
            # "grade 3 tumors", "stage 2 cases": the number is a label, not a count
            if re.search(r"\b(?:grade|stage|type|phase|level|class|cluster|version|tier|pt|t|n|m)\s*$", s.text[:num.start], re.I):
                continue
            after = segs[i + 1] if (i + 1) in denom else segs[i]
            if i in denom:
                ent = next((k for k, pat in self.ENTITIES if re.match(pat, after, re.I)), None) or default
                ok, rule = matches(num, totals[ent], False)
                subs.append(SubCheck(f"Number of {ent if ent != 'primary' else 'primary tumors'} (denominator)", num.text,
                                     f"{totals[ent]:,}", ok, rule))
                continue
            # "21% of tumors WITH copy number data are amplified": the layer only says which tumors are counted; the claim
            # is about something else (amplification, events, stage...), so this checker must not answer it.
            if num.is_percent and re.match(r"\s*of\s+(?:the\s+|all\s+)?(?:\w+\s+){0,2}?(?:tumou?rs|samples|patients|cases)"
                                           r"\s+(?:with|that have|having)\b", after, re.I):
                continue
            # "21.6% of the RPPA clusters": the layer name is part of a classification, not data availability
            if num.is_percent and re.search(r"cluster|subtype|classif|\bgroups?\b", after, re.I):
                continue
            entity = next((k for k, pat in self.ENTITIES if re.match(pat, after, re.I)), None)
            layers = [k for k, pat in LAYER_PATTERNS.items() if re.search(pat, after, re.I)]
            if re.search(r"\b(?:all|every) (?:five|5|six|6) (?:data )?layers|every (?:data )?layer|all (?:data )?layers", after, re.I):
                layers = ["survival", "mutation", "copy_number", "rna", "protein"]
            if not layers and i == 0:
                # "Copy number data is available for over 1,000 primary tumors": the layer is named before the number
                lead = s.text[:num.start]
                if re.search(r"\b(?:data|measurements?|profiles?|calls?)\b.*\b(?:available|measured|profiled|present|exists?)\b|"
                             r"\b(?:available|measured|profiled)\b", lead, re.I):
                    layers = [k for k, pat in LAYER_PATTERNS.items() if k != "slides" and re.search(pat, lead, re.I)]
            if entity is None and not layers:
                continue
            ent = entity or last_entity or default
            last_entity = ent
            base = {"primary": prim, "samples": m, "normal": m[m.type_code == "11"], "metastatic": m[m.type_code == "06"],
                    "patients": m}[ent]
            if layers:
                mask = pd.Series(True, index=base.index)
                slide_desc = "slides"
                for L in layers:
                    if L == "slides":
                        if "n_slides" in base:
                            col = ("n_diagnostic_slides" if re.search(r"diagnostic|ffpe", after, re.I) else
                                   "n_frozen_slides" if re.search(r"frozen", after, re.I) else "n_slides")
                            kind = {"n_diagnostic_slides": "diagnostic ", "n_frozen_slides": "frozen "}.get(col, "")
                            if re.search(r"\b(?:no|without|lack\w*|missing)\b(?:\s+\w+){0,2}?\s+(?:slides?|images?)", after, re.I):
                                mask &= base[col] == 0
                                slide_desc = f"no {kind}slides"
                            else:
                                mask &= base[col] > 0
                                slide_desc = f"at least one {kind}slide"
                    elif f"has_{L}" in base:
                        if not r.has_file(L):
                            missing.add(L)
                            continue
                        mask &= base[f"has_{L}"]
                used_layers.update(layers)
                sel = base[mask]
                obs = sel.patient_id.nunique() if ent == "patients" else len(sel)
                label = f"{ent.capitalize()} with " + ", ".join(slide_desc if L == "slides" else LAYER_LABELS.get(L, L)
                                                                for L in layers)
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
        source = "sample_manifest.csv" if r.membership_note.startswith("Sample list and data layers from sample_manifest")             else "the release files"
        if "slides" in used_layers and "n_slides" in prim:
            layer_counts += f", slides {int((prim.n_slides > 0).sum()):,}"
        return Result(verdict=v, check=self.name,
                      summary=f"Sample membership from {source}: {totals['primary']:,} primary tumors "
                              f"({layer_counts}).",
                      subchecks=subs, correct_value=correct_from(subs) if v == "contradicted" else None,
                      files=(["sample_manifest.csv"] if source == "sample_manifest.csv" else [])
                            + (["slide_manifest.csv"] if "slides" in used_layers else [])
                            + [FILES[k] for k in FILES if r.has_file(k)],
                      fields=["sample barcode (chars 14–15 = sample type)"]
                            + ([f"has_{L}" for L in sorted(used_layers) if L != "slides"] if source == "sample_manifest.csv" else [])
                            + (["slides_for_sample / slide_kind"] if "slides" in used_layers else []),
                      n=totals["primary"], population="Samples in the release (01 = primary tumor)",
                      limitation=" ".join(x for x in [
                          r.membership_note,
                          r.manifest_note if "slides" in used_layers else "",
                          "Values inside a file may still be missing. Each extra layer you require shrinks the cohort.",
                          redaction_note(r) if "survival" in used_layers else ""] if x),
                      needed=needed,
                      code=("# membership = which files each sample barcode appears in\n"
                            "prim = membership[membership.sample_id.str[13:15] == '01']\n"
                            + (f"prim[{' & '.join(f'prim.{f}' for f in flags.split(' & '))}].shape[0]" if flags else "len(prim)")),
                      sample_ids=sorted(prim.sample_id) if not used_layers else [])


def _stage_group(v: str) -> str | None:
    m = re.match(r"stage (iv|iii|ii|i)[abc]?\b", str(v).lower())    # "Stage IIA" -> II, "Stage IIIC" -> III
    return m.group(1).upper() if m else None


# topic -> (pattern in the sentence, column, does a recorded value belong to the category?, label, unknown values)
_UNKNOWN = r"discrepancy|not available|unknown|^nan$"
CLINICAL_TOPICS = {
    "ductal": (r"\bductal\b|\bidc\b", "histological_type", lambda v: v == "Infiltrating Ductal Carcinoma",
               "Infiltrating ductal carcinoma", _UNKNOWN),
    "lobular": (r"\blobular\b|\bilc\b", "histological_type", lambda v: v == "Infiltrating Lobular Carcinoma",
                "Infiltrating lobular carcinoma", _UNKNOWN),
    "mucinous": (r"\bmucinous\b", "histological_type", lambda v: v == "Mucinous Carcinoma", "Mucinous carcinoma", _UNKNOWN),
    "metaplastic": (r"\bmetaplastic\b", "histological_type", lambda v: v == "Metaplastic Carcinoma", "Metaplastic carcinoma", _UNKNOWN),
    "medullary": (r"\bmedullary\b", "histological_type", lambda v: "Medullary" in v, "Medullary carcinoma", _UNKNOWN),
    "stage_3plus": (r"stages? iii (?:or|and) (?:higher|above|iv|later)|stages? iii[-–/ ]+iv\b|(?:late|advanced)[- ]stage",
                    "pathologic_stage", lambda v: _stage_group(v) in ("III", "IV"), "Stage III or IV", _UNKNOWN + r"|stage x"),
    "stage_early": (r"stages? i (?:or|and) ii\b|stages? i[-–/ ]+ii\b|early[- ]stage", "pathologic_stage",
                    lambda v: _stage_group(v) in ("I", "II"), "Stage I or II", _UNKNOWN + r"|stage x"),
    "stage_iv": (r"\bstage iv\b", "pathologic_stage", lambda v: _stage_group(v) == "IV", "Stage IV", _UNKNOWN + r"|stage x"),
    "stage_iii": (r"\bstage iii\b(?! ?(?:or|and|[-–/]))", "pathologic_stage", lambda v: _stage_group(v) == "III", "Stage III",
                  _UNKNOWN + r"|stage x"),
    "stage_ii": (r"\bstage ii\b(?! ?(?:or|and|[-–/]))", "pathologic_stage", lambda v: _stage_group(v) == "II", "Stage II",
                 _UNKNOWN + r"|stage x"),
    "stage_i": (r"\bstage i\b(?! ?(?:or|and|[-–/]))", "pathologic_stage", lambda v: _stage_group(v) == "I", "Stage I",
                _UNKNOWN + r"|stage x"),
    "node_neg": (r"node[- ]negative|no (?:lymph )?node (?:involvement|spread|metastas)|without (?:lymph )?node",
                 "pathologic_N", lambda v: v.startswith("N0"), "Lymph-node negative (N0)", _UNKNOWN + r"|^nx$"),
    "node_pos": (r"node[- ]positive|(?:lymph )?node (?:involvement|spread|metastas)|(?:spread|metastas\w*) to (?:the )?(?:axillary |regional )?lymph nodes?|positive (?:lymph )?nodes",
                 "pathologic_N", lambda v: v[:2] in ("N1", "N2", "N3"), "Lymph-node positive (N1-N3)", _UNKNOWN + r"|^nx$"),
    "distant": (r"distant metastas|\bm1\b|metastatic (?:disease |cancer )?at (?:diagnosis|presentation)",
                "pathologic_M", lambda v: v.startswith("M1"), "Distant metastasis at diagnosis (M1)", _UNKNOWN + r"|^mx$"),
    "female": (r"\bfemales?\b|\bwomen\b", "gender", lambda v: v == "FEMALE", "Female", _UNKNOWN),
    "male": (r"(?<!fe)\bmales?\b|\bmen\b", "gender", lambda v: v == "MALE", "Male", _UNKNOWN),
    "postmeno": (r"post[- ]?menopausal", "menopause_status", lambda v: v.startswith("Post"), "Postmenopausal",
                 _UNKNOWN + r"|indeterminate"),
    "premeno": (r"pre[- ]?menopausal", "menopause_status", lambda v: v.startswith("Pre"), "Premenopausal",
                _UNKNOWN + r"|indeterminate"),
    "perimeno": (r"peri[- ]?menopausal", "menopause_status", lambda v: v.startswith("Peri"), "Perimenopausal",
                 _UNKNOWN + r"|indeterminate"),
    "margin_pos": (r"positive (?:surgical |resection )?margins?|margins? (?:was|were) positive", "margin_status",
                   lambda v: v == "Positive", "Positive surgical margin", _UNKNOWN),
    "margin_neg": (r"(?:negative|clear) (?:surgical |resection )?margins?|margins? (?:was|were) (?:negative|clear)",
                   "margin_status", lambda v: v == "Negative", "Negative surgical margin", _UNKNOWN),
    "radiation": (r"radiation|radiotherapy", "radiation_therapy", lambda v: v == "YES", "Received radiation therapy",
                  _UNKNOWN),
}
for _st in ("IA", "IB", "IIA", "IIB", "IIIA", "IIIB", "IIIC"):     # sub-stages: "Stage IIA" exactly
    CLINICAL_TOPICS[f"stage_{_st.lower()}"] = (rf"\bstage {_st.lower()}\b", "pathologic_stage",
                                               lambda v, _s=_st: v == f"Stage {_s}", f"Stage {_st}", _UNKNOWN + r"|stage x")
# Words that put the claim on a different variable than the topic keyword: a later event, an additional treatment, or a
# negation the topic doesn't model ("no distant metastasis"). The checker gives up rather than measure the wrong thing.
_CLIN_OTHER_VARIABLE = r"\badditional\b|new (?:tumou?r|neoplasm)|recurren|relapse|after (?:the )?(?:initial |first )?treatment|" \
                       r"follow[- ]?up|\bhistory of\b|\bprior\b|\bother\b"
_CLIN_NEGATION = r"\b(?:no|not|without|absent|free of|none|never)\b"
# Sentences about genes, subtypes, receptors, survival, age or omics layers belong to the other checkers.
_CLIN_EXCLUDE = (r"mutat|\bsurviv|\bdeaths?\b|\bdied\b|deceased|\bage\b|years? old|\bmedian\b|\bmean\b|protein|rppa|copy[- ]number"
                 r"|\brna\b|slides?\b|pam50|subtype|luminal|basal|her2|triple[- ]negative|\btnbc\b|estrogen|progesterone"
                 r"|\ber[- ]?(?:positive|negative|\+)|\bpr[- ]?(?:positive|negative|\+)")
_QUANT = r"\b(?:most|majority|minority|few|fewer|nearly all|almost all|virtually all)\b"


class ClinicalCategoryChecker(Checker):
    """Shares of primary tumors in a clinical category: histology, stage, lymph nodes, distant metastasis, sex,
    menopause, surgical margins, radiation. `early` instances only take number-free sentences ("Most patients were
    postmenopausal") that would otherwise be read as opinion; the late instance takes the numeric ones."""
    name = "clinical_category"

    def __init__(self, early: bool = False):
        self.early = early

    def _spans(self, s):
        t = s.lower
        if re.search(_CLIN_EXCLUDE, t) or re.search(r"\b[A-Z][A-Z0-9]{2,}\d\b", s.text):
            return []
        if re.search(_CLIN_OTHER_VARIABLE, t):
            return []
        if re.search(r"2012|nature|converted|\bajcc\b|pancan|pan[- ]cancer", t):
            return []         # the claim names another source column (e.g. the 2012 study's staging): don't substitute ours
        spans, taken = [], []
        for key, (pat, *_rest) in CLINICAL_TOPICS.items():
            for m in re.finditer(pat, t):
                if any(m.start() < b and a < m.end() for a, b in taken):
                    continue          # "lymph node metastasis" is a node claim, not a distant-metastasis claim
                taken.append((m.start(), m.end()))
                spans.append((m.start(), key))
        # a negation outside the matched topic words ("no distant metastasis") flips the meaning: don't guess
        rest = t
        for a, b in sorted(taken, reverse=True):
            rest = rest[:a] + " " * (b - a) + rest[b:]
        if re.search(_CLIN_NEGATION, rest):
            return []
        # two different categories of the same variable sharing one number ("ductal and lobular: 7%") is ambiguous
        by_col = {}
        for _, key in spans:
            by_col.setdefault(CLINICAL_TOPICS[key][1], set()).add(key)
        if any(len(v) > 1 for v in by_col.values()) and len(s.numbers) < 2:
            return []
        return sorted(spans)

    def applies(self, s, r):
        if self.early and (s.numbers or not re.search(_QUANT, s.lower)):
            return False
        return bool(self._spans(s)) and any(CLINICAL_TOPICS[k][1] in r.clinical_primary for _, k in self._spans(s))

    def _claims(self, s):
        if s.numbers:
            return list(s.numbers)
        t = s.lower
        m = re.search(_QUANT, t)
        word = m.group(0)
        if word in ("most", "majority"):
            return [Number(50.0, True, False, m.start(), m.end(), word, cmp=">", word=True)]
        if word in ("minority", "few", "fewer"):
            return [Number(50.0, True, False, m.start(), m.end(), word, cmp="<", word=True)]
        return [Number(95.0, True, False, m.start(), m.end(), word, cmp=">=", word=True)]   # nearly / almost all

    def run(self, s, r):
        c = r.clinical_primary
        spans = self._spans(s)
        subs, alts, fields = [], [], []
        for num in self._claims(s):
            key = nearest(num.start, spans, prefer_before=False)
            if key is None:
                continue
            _, col, member, label, unknown = CLINICAL_TOPICS[key]
            if col not in c:
                continue
            vals = c[col].dropna().astype(str)
            known = vals[~vals.str.lower().str.contains(unknown, regex=True)]
            obs = int(known.map(member).sum())
            den = len(known)
            if col not in fields:
                fields.append(col)
            if num.is_percent:
                ok, rule = matches(num, pct(obs, den), True)
                ok_alt = matches(num, pct(obs, len(c)), True)[0]
                subs.append(SubCheck(f"{label}: share of primary tumors with a recorded `{col}`", num.text, fmt_pct(obs, den),
                                     ok, rule + (f"; it would match with all {len(c):,} primary tumors as the denominator "
                                                 f"({fmt_pct(obs, len(c))}), so ask which one the author used"
                                                 if ok_alt and not ok else "")))
                alts.append({"definition": f"{label}, denominator = all {len(c):,} primary tumors", "value": fmt_pct(obs, len(c))})
            else:
                ok, rule = matches(num, obs, False)
                subs.append(SubCheck(f"{label}: primary tumors", num.text, f"{obs:,}", ok, rule))
        v = verdict_from(subs)
        return Result(verdict=v, check=self.name,
                      summary="Counted clinical records among primary tumors: "
                              + "; ".join(f"{sc.label}: {sc.observed}" for sc in subs) + ".",
                      subchecks=subs, correct_value=correct_from(subs) if v == "contradicted" else None,
                      files=[FILES["clinical"]], fields=fields, n=len(c), population="Primary tumors in clinical.tsv",
                      limitation="Counts primary tumors with a recorded value; missing, unknown and not-assessable values "
                                 "(e.g. Stage X, NX, MX) are left out of the main denominator. Patients and primary tumors "
                                 "are treated as the same unit (one primary tumor per patient here)."
                                 + (" 'Most' is read as more than 50%; 'nearly all' as at least 95%." if not s.numbers else ""),
                      alternatives=alts,
                      code="c = clinical[clinical.sampleID.str[13:15]=='01']\n"
                           + "\n".join(f"c['{f}'].value_counts(dropna=False)" for f in fields),
                      confidence="high" if s.numbers else "medium")


class Fallback(Checker):
    name = "unrecognised"

    def applies(self, s, r):
        return True

    def run(self, s, r):
        return Result(verdict="insufficient_evidence", check=self.name,
                      summary="The tool has no automatic check for this kind of statement. A reviewer must check it by hand.",
                      confidence="low",
                      needed=needed_for(s.text),
                      limitation="Unchecked by the tool: this is not a judgement that the data can't answer it.")


class StatementKindChecker(Checker):
    """Safety disclaimers, instructions, questions and stated limitations are not research findings. They are kept
    (and never flagged for removal): a disclaimer like "not intended for diagnosis" is what a report should say."""
    name = "not_a_claim"

    def applies(self, s, r):
        return statement_kind(s.text) is not None

    def run(self, s, r):
        kind = statement_kind(s.text)
        keep = "disclaimer" in kind or "limitation" in kind
        return Result(verdict="not_a_claim", check=self.name, confidence="medium",
                      summary=f"This sentence is {kind}, not a factual claim about the data, so it is not scored."
                              + (" Keep it in the report." if keep else ""),
                      limitation="A reviewer can mark it as a claim if they disagree.")


# Mutation runs before subtype/receptor shares: "TP53 is mutated in 80% of basal-like tumors" is a mutation rate
# within a subtype, not a claim about how common basal-like tumors are.
# The clinical-category checker comes last (before the fallback) so it only gets sentences no other checker takes;
# its early copy only takes number-free "most / nearly all" sentences that would otherwise be read as opinion.
CHECKERS: list[Checker] = [StatementKindChecker(), TreatmentChecker(), ManifestChecker(), ClinicalCategoryChecker(early=True),
                           NotAClaimChecker(), SurvivalChecker(), ProteinCompareChecker(), MutationChecker(),
                           CopyNumberChecker(), SubtypeChecker(),
                           ReceptorShareChecker(), AgeChecker(), CohortChecker(), ClinicalCategoryChecker(), Fallback()]


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
    gave_up = None
    for ch in CHECKERS:
        try:
            if ch.applies(s, r):
                res = ch.run(s, r)
                if res.check == "unrecognised" and not isinstance(ch, Fallback):
                    gave_up = gave_up or res     # this checker found nothing to measure: let the later ones try
                    continue
                if isinstance(ch, Fallback) and gave_up:
                    return gave_up
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
