"""Before checking a single number: which dataset is this report about, and which sentences are claims?

A research auditor must never compare a report's numbers with a dataset the report isn't about. A synthetic test
fixture describing "120 fictional tumor-sample records" is not wrong because TCGA-BRCA has 1,101 primary tumors.
This module decides the report's scope, pulls out explicitly labelled claims ("Claim: ..."), recognises
non-claim text (headings, instructions, safety disclaimers, stated limitations), and checks a report's own
arithmetic against its own tables. Deterministic and rule-based, like the rest of the tool.
"""
from __future__ import annotations

import re

# ---------------------------------------------------------------------------- dataset identity
FICTION = r"\b(?:synthetic|fictional|fictitious|invented|simulated|mock|made[- ]up|test fixture|hypothetical)\b"
NOT_OURS = (r"tcga[- ]brca[- ]like|\b(?:-like|like) (?:research )?cohort|no real patient|not real research|"
            r"do(?:es)? not describe actual|invented for|not (?:a )?(?:real|actual) (?:dataset|cohort|data)|"
            r"fictional (?:\w+[- ])?(?:cohort|dataset|data|records|analysis)")
ABOUT_RELEASE = (r"release a\b|this repository|fetch\.py|frozen (?:event )?release|tcga-brca files in|"
                 r"the tcga-brca release|ucsc xena")
COHORT_SIZE = re.compile(r"\b(?:begins with|starts with|consists of|comprises|includes|contains|cohort of|total of)\s+"
                         r"(\d[\d,]*)\s+(?:\w+[- ])?(?:tumou?r[- ]sample |sample |patient |tumou?r )?(?:records|samples|patients|"
                         r"participants|tumou?rs|cases)", re.I)


def detect_scope(text: str, release_totals: dict | None = None) -> dict:
    """mode "release": the report is about the data release (check its numbers against it).
    mode "other_dataset": it describes a different (e.g. synthetic) dataset, so its numbers must not be compared."""
    t = text.lower()
    fiction = [m.group(0) for m in re.finditer(FICTION, t)]
    not_ours = [m.group(0) for m in re.finditer(NOT_OURS, t)]
    about_release = [m.group(0) for m in re.finditer(ABOUT_RELEASE, t)]
    sizes = [int(m.group(1).replace(",", "")) for m in COHORT_SIZE.finditer(text)]
    quotes = []
    for pat in (NOT_OURS, FICTION):
        m = re.search(r"[^.\n]*(?:" + pat + r")[^.\n]*", text, re.I)
        if m:
            quotes.append(m.group(0).strip()[:200])
    known = set((release_totals or {}).values())
    size_mismatch = bool(sizes) and known and all(min(abs(s - k) for k in known) > 0.05 * max(known) for s in sizes)
    if about_release and not not_ours:
        return {"mode": "release", "reason": "The report says it describes the TCGA-BRCA release.",
                "quotes": quotes, "stated_cohort_sizes": sizes}
    if (fiction and not_ours) or (not_ours and size_mismatch) or (fiction and size_mismatch and not about_release):
        why = "The report describes a different dataset"
        if fiction:
            why += f" and calls itself {fiction[0]}"
        if sizes:
            why += f" (its own cohort: {sizes[0]:,} records)"
        return {"mode": "other_dataset", "reason": why + ". Its numbers are not about TCGA-BRCA, so they are checked "
                "only against the report's own tables and arithmetic, never against the release.",
                "quotes": quotes, "stated_cohort_sizes": sizes}
    return {"mode": "release", "reason": "No sign that the report describes another dataset.", "quotes": quotes,
            "stated_cohort_sizes": sizes}


# ---------------------------------------------------------------------------- explicitly labelled claims
_Q = r"[\"“”'‘’]"
CLAIM_RE = re.compile(r"Claim:\s*" + _Q + r"(.+?)" + _Q + r"\s*(?=\n|$|Evidence)", re.S)
LABEL_RE = re.compile(r"^\s*(C\d+|Claim\s+\d+)\s*[—–:-]+\s*(.*)$", re.M)


def _clean(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip()


def explicit_claims(text: str) -> list[dict]:
    """A report that labels its claims ("C1 — ...  Claim: “...”  Evidence cited: ...") is audited claim by claim."""
    found = list(CLAIM_RE.finditer(text))
    if len(found) < 2:
        return []
    out = []
    labels = list(LABEL_RE.finditer(text))
    for i, m in enumerate(found):
        lab = [l for l in labels if l.start() < m.start()]
        label, title = (lab[-1].group(1).replace(" ", ""), _clean(lab[-1].group(2))) if lab else (f"C{i + 1}", "")
        nxt = found[i + 1].start() if i + 1 < len(found) else len(text)
        block = text[m.end():nxt]
        ev = re.search(r"Evidence cited:\s*(.+?)(?:\n\s*\n|Audit focus:|$)", block, re.S)
        out.append({"label": label, "title": title, "text": _clean(m.group(1)),
                    "evidence": _clean(ev.group(1)) if ev else "", "start": m.start()})
    return out


# ---------------------------------------------------------------------------- text tables
RULER = re.compile(r"^\s*[-=+|:]{5,}[-=+|: ]*$")


def is_table_line(line: str) -> bool:
    """Plain-text tables: ruler lines, or lines laid out in columns (2+ gaps of 3+ spaces)."""
    s = line.rstrip()
    return bool(RULER.match(s)) or len(re.findall(r"\S {3,}\S", s)) >= 2 or s.lstrip().startswith("|")


def table_rows(text: str) -> list[str]:
    """Rows of plain-text tables, with wrapped cells joined back to their row (best effort)."""
    rows, cur = [], ""
    for line in text.splitlines():
        if RULER.match(line.rstrip()):
            if cur:
                rows.append(cur)
            cur = ""
            continue
        if is_table_line(line) or (cur and line.startswith("  ") and line.strip()):
            if re.match(r"^\s{0,4}\S", line) and cur and re.search(r"\d", line):
                rows.append(cur)
                cur = ""
            cur = (cur + " " + line.strip()).strip()
        elif cur and not line.strip():
            rows.append(cur)
            cur = ""
    if cur:
        rows.append(cur)
    return [re.sub(r"\s+", " ", r) for r in rows if r]


# ---------------------------------------------------------------------------- what kind of statement is it?
DISCLAIMER = (r"\b(?:not|never|no)\b[^.]{0,80}\b(?:intended|meant|a substitute|validated|clinical validation|"
              r"diagnos\w*|treatment (?:advice|selection|decisions?)|prognos\w*|risk (?:scores?|prediction)|"
              r"medical (?:advice|recommendations?)|patient-level|cite)\b|research use only|for research purposes only|"
              r"not a (?:scientific publication|clinical)|do not cite|software testing")
INSTRUCTION = (r"^(?:feed|ask|use|treat|check|verify|obtain|compare|provide|require|explain|create|point|show|make|"
               r"recommend|audit|identify|distinguish|preserve|mark|request|rerun|document|resolve|test|do not|don't)\b|"
               r"\bthe (?:system|application|tool|copilot|auditor) (?:should|must|will)\b|\b(?:your|a strong|a good) "
               r"(?:system|application|tool)\b|\bthis checklist\b|\bexpected (?:challenge|behaviou?r)\b")
LIMITATION = (r"\bthe (?:report|analyst|authors?) (?:does not|doesn't|did not|provides? no|states)\b|\b(?:is|are) not "
              r"(?:provided|reported|documented|specified|supplied|demonstrated)\b|\bnot (?:specified|documented|reported)\b|"
              r"\bomission is\b|\bno (?:data dictionary|release identifier|statistical test|agreement table)\b")


def statement_kind(text: str) -> str | None:
    """None if it may be a factual claim; otherwise what it is."""
    t = text.strip()
    tl = t.lower()
    if t.endswith("?"):
        return "a question"
    # "97% of patients had no distant metastasis at diagnosis" states a finding: a percentage or a count of patients /
    # tumors means it is a claim, even if it contains "no ... diagnosis"
    finding = re.search(r"\d\s*(?:%|percent)|\b\d[\d,]*\s+(?:of\s+(?:the\s+|all\s+)?)?(?:\w+\s+){0,2}"
                        r"(?:patients|tumou?rs|samples|cases|women|participants)\b", tl)
    if re.search(DISCLAIMER, tl) and not finding:
        return "a safety or scope disclaimer"
    if re.search(INSTRUCTION, tl):
        return "an instruction to the reader or the system"
    if re.search(LIMITATION, tl):
        return "a statement of what the report leaves out (a limitation to keep visible)"
    if re.match(r"^(?:working title|research question|intended use|population represented|purpose)\b", tl):
        return "a description of the study's scope"
    return None


# ---------------------------------------------------------------------------- data needed, by claim type
NEEDS = [   # order matters: a causal claim usually also mentions a difference
    (r"\bcaus\w*|\bdrive[sn]?\b|\blead[s]? to\b|\bresult(?:s|ed)? in\b|\bbecause\b",
     "A design that can support causation (temporal order, adjustment for confounders) and the group results "
     "themselves. A descriptive data set can't show cause and effect."),
    (r"significan|differ\w* (?:between|across|by)|compared? with|higher|lower|more .* than|less .* than",
     "Group-level values for each group, a pre-specified statistical test, an effect size and a confidence interval. "
     "Counts of how many records are available can't show a difference."),
    (r"stable|agree\w*|concordan\w*|consistent|conflict\w*|reproducib",
     "Both calls on the same matched records, a cross-tabulation and an agreement statistic (e.g. Cohen's kappa). "
     "Two calls existing is not, by itself, evidence that they agree or disagree."),
    (r"pipeline|version\b|validated|generated (?:using|with|by)|algorithm|software",
     "The pipeline name and version, its validation record and a source manifest. Nothing in the report shows "
     "which method produced the labels."),
    (r"\ball\b.*(?:patients|people|women)|represent\w*|generali[sz]|population",
     "A sampling frame and a representativeness analysis. A sample cohort can't stand for all patients."),
]


def needed_for(text: str) -> str:
    tl = text.lower()
    for pat, msg in NEEDS:
        if re.search(pat, tl):
            return msg
    return "A reviewer should identify the field(s) this claim refers to, or mark it as not a claim."


# ---------------------------------------------------------------------------- the report's own arithmetic
NUM = r"(\d[\d,]*(?:\.\d+)?)"


def _f(s):
    return float(s.replace(",", ""))


def own_arithmetic(claim: str, evidence: str, rows: list[str], cohort_sizes: list[int]):
    """Check a claim against the report's own numbers. Returns (subchecks, status) where each subcheck is
    (label, claimed, observed, ok, rule) and status says what could be established."""
    subs = []
    tl = claim.lower()
    # 1. "108 of the 120 tumor-sample records (90.0%)": is the percentage right?
    for m in re.finditer(NUM + r"\s+(?:of|out of)\s+(?:the\s+)?" + NUM + r"[^()%]{0,80}\(\s*" + NUM + r"\s*%\s*\)", claim):
        a, b, p = _f(m.group(1)), _f(m.group(2)), _f(m.group(3))
        calc = 100 * a / b if b else float("nan")
        dec = len(m.group(3).split(".")[1]) if "." in m.group(3) else 0
        tol = 0.5 * 10 ** -dec + 0.05
        subs.append((f"{m.group(1)} / {m.group(2)}", f"{m.group(3)}%", f"{calc:.1f}%", abs(calc - p) <= tol,
                     "the report's own numbers"))
    # 2. a percentage of "the starting cohort", with the counts given in the cited evidence
    if not subs:
        pm = re.search(NUM + r"\s*%", claim)
        ev = re.sub(r"\b(?:table|figure|fig\.?|section|row|column|check)\s*\d+[a-z]?\b", " ", evidence, flags=re.I)
        nums = [_f(x) for x in re.findall(NUM, ev)]
        if pm and len(nums) >= 2:
            p = _f(pm.group(1))
            a, b = nums[0], nums[1]
            if b and b >= a:
                calc = 100 * a / b
                subs.append((f"{fmt(a)} / {fmt(b)} (from the cited evidence)", f"{pm.group(1)}%", f"{calc:.1f}%",
                             abs(calc - p) <= 0.15, "the report's own numbers"))
    # 3. a vague quantifier ("most records") checked against the cited table row
    if not subs and re.search(r"\bmost\b|\bmajority\b|\bmore than half\b|\bnearly all\b|\bfew\b|\bminority\b", tl):
        row = _cited_row(evidence, rows)
        if row:
            pct = re.findall(NUM + r"\s*%", row)
            if pct:
                v = _f(pct[0])
                want = 95 if "nearly all" in tl else 50
                ok = v < 50 if re.search(r"\bfew\b|\bminority\b", tl) else v > want
                cnts = [x for x in re.findall(r"(?<![\d.])(\d[\d,]*)(?![\d.%])", row)]
                base = f" ({cnts[0]} of {cohort_sizes[0]:,})" if cnts and cohort_sizes else ""
                subs.append(("Share in the cited table row", "most" if "most" in tl else tl.split()[0],
                             f"{v:g}%{base}", ok, "more than half" if want == 50 else "at least 95%"))
    return subs


def fmt(v: float) -> str:
    return f"{int(v):,}" if float(v).is_integer() else f"{v:g}"


def _cited_row(evidence: str, rows: list[str]) -> str | None:
    m = re.search(r"row\s*[\"“”'‘’]([^\"“”'‘’]+)[\"“”'‘’]", evidence, re.I)
    if not m:
        return None
    words = [w.lower() for w in re.findall(r"[A-Za-z]{3,}", m.group(1))]
    best, score = None, 0
    for r in rows:
        rl = r.lower()
        s = sum(w in rl for w in words)
        if s > score:
            best, score = r, s
    return best if score >= max(1, len(words) - 1) else None
