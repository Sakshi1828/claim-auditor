"""Split a report into sentences and pull out the numbers each one states.

Deterministic on purpose: the same report always gives the same claims, so a judge can rerun it.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

APPROX_WORDS = ("about", "approximately", "around", "roughly", "nearly", "almost", "~", "close to", "some ")

NUM_RE = re.compile(r"(?<![\w.])(~?\d{1,3}(?:,\d{3})+|~?\d+(?:\.\d+)?)(\s*(?:%|percent|per cent))?")


@dataclass
class Number:
    value: float
    is_percent: bool
    approx: bool
    start: int
    end: int
    text: str
    cmp: str | None = None          # ">", ">=", "<", "<=" for "more than 1,000", "at least", "fewer than 800"
    lo: float | None = None         # a range: "10-15%", "between 15% and 20%"
    hi: float | None = None
    word: bool = False              # written in words: "half", "a third", "one in five", "4 in 5"


# "more than 1,000", "at least 30", "fewer than 800", "under 10%" ...
CMP_WORDS = [
    (r"(?:more than|greater than|over|above|exceed(?:s|ing)?|upwards of|in excess of)", ">"),
    (r"(?:at least|no fewer than|no less than|a minimum of)", ">="),
    (r"(?:fewer than|less than|under|below|lower than)", "<"),
    (r"(?:at most|no more than|up to|a maximum of)", "<="),
]
_SMALL = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10}
_N = r"(\d+|one|two|three|four|five|six|seven|eight|nine|ten)"
# word fractions -> percent
FRACTIONS = [
    (re.compile(rf"\b{_N}\s+(?:in|out of)\s+{_N}\b", re.I), None),           # "one in five", "4 in 5", "3 out of 10"
    (re.compile(r"\b(?:two[- ]thirds)\b", re.I), 200 / 3),
    (re.compile(r"\b(?:three[- ]quarters)\b", re.I), 75.0),
    (re.compile(r"\b(?:a|one)[- ]third\b", re.I), 100 / 3),
    (re.compile(r"\b(?:a|one)[- ]quarter\b", re.I), 25.0),
    (re.compile(r"\b(?:a|one)[- ]fifth\b", re.I), 20.0),
    (re.compile(r"\b(?:a|one)[- ]tenth\b", re.I), 10.0),
    (re.compile(r"\bhalf\b(?![- ]life)", re.I), 50.0),
]
_PCT = r"\s*(?:%|percent|per cent)"
RANGE_RE = re.compile(
    rf"(?:between\s+)?(\d+(?:\.\d+)?)(?:{_PCT})?\s*(?:-|–|—|to|and)\s*(\d+(?:\.\d+)?)({_PCT})", re.I)


@dataclass
class Sentence:
    index: int
    text: str
    numbers: list[Number] = field(default_factory=list)

    @property
    def lower(self) -> str:
        return self.text.lower()


def _strip_markdown(md: str) -> list[str]:
    """Return prose paragraphs: drops headings, front-matter notes in italics, code fences and tables."""
    paras, buf, in_code = [], [], False
    for line in md.splitlines():
        s = line.strip()
        if s.startswith("```"):
            in_code = not in_code
            continue
        if in_code:
            continue
        if not s:
            if buf:
                paras.append(" ".join(buf))
                buf = []
            continue
        if s.startswith("#") or s.startswith("|") or s.startswith("---"):
            if buf:
                paras.append(" ".join(buf))
                buf = []
            continue
        # A paragraph wholly in italics is an editor's note (e.g. "*A short fictional summary...*")
        if re.fullmatch(r"\*[^*].*\*", s) or re.fullmatch(r"_[^_].*_", s):
            continue
        s = re.sub(r"^[-*+]\s+|^\d+[.)]\s+", "", s)  # list markers
        buf.append(s)
    if buf:
        paras.append(" ".join(buf))
    out = []
    for p in paras:
        p = re.sub(r"\*\*|__|`", "", p)
        p = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", p)
        out.append(p)
    return out


_ABBREV = re.compile(r"\b(e\.g|i\.e|et al|vs|approx|Fig|no)\.$", re.I)


def split_sentences(md: str) -> list[Sentence]:
    sentences: list[Sentence] = []
    for para in _strip_markdown(md):
        parts, cur = [], ""
        for piece in re.split(r"(?<=[.!?])\s+(?=[A-Z0-9\"'(])", para):
            cur = f"{cur} {piece}".strip() if cur else piece
            if _ABBREV.search(cur):
                continue
            parts.append(cur)
            cur = ""
        if cur:
            parts.append(cur)
        for p in parts:
            p = p.strip()
            if len(p) > 3:
                sentences.append(Sentence(index=len(sentences), text=p, numbers=find_numbers(p)))
    return sentences


def _comparator(text: str, start: int) -> str | None:
    before = text[max(0, start - 22):start].lower()
    for pat, sym in CMP_WORDS:
        if re.search(pat + r"\s*(?:the\s+|a\s+)?$", before):
            return sym
    return None


def find_numbers(text: str) -> list[Number]:
    nums, taken = [], []
    free = lambda a, b: all(b <= x or a >= y for x, y in taken)   # noqa: E731

    # 1. ranges: "10-15%", "between 15% and 20%", "15 to 20 percent" (one claim, checked as an interval)
    for m in RANGE_RE.finditer(text):
        if m.group(0).lower().count("and") and not m.group(0).lower().startswith("between"):
            continue                                    # "15% and 20%" without "between" is two claims
        a, b = sorted([float(m.group(1)), float(m.group(2))])
        if b > 100 or a == b:
            continue
        before = text[max(0, m.start() - 14):m.start()].lower()
        nums.append(Number((a + b) / 2, True, any(w in before for w in APPROX_WORDS), m.start(), m.end(),
                           m.group(0).strip(), lo=a, hi=b))
        taken.append((m.start(), m.end()))

    # 2. word fractions: "one in five", "4 in 5", "a third", "half"
    for rx, val in FRACTIONS:
        for m in rx.finditer(text):
            if not free(m.start(), m.end()):
                continue
            if val is None:
                a = _SMALL.get(m.group(1).lower()) or int(m.group(1))
                b = _SMALL.get(m.group(2).lower()) or int(m.group(2))
                if not b or a > b or b > 1000:
                    continue
                v = 100.0 * a / b
            else:
                v = val
            nums.append(Number(round(v, 2), True, True, m.start(), m.end(), m.group(0).strip(), word=True,
                               cmp=_comparator(text, m.start())))
            taken.append((m.start(), m.end()))

    # 3. plain numbers
    for m in NUM_RE.finditer(text):
        if not free(m.start(), m.end()):
            continue
        raw = m.group(1)
        # skip years and things like "TCGA-BRCA" codes or "2012" in column names
        val = float(raw.replace(",", "").replace("~", ""))
        is_pct = bool(m.group(2))
        if not is_pct and 1900 <= val <= 2100 and "," not in raw:
            continue
        if re.match(r"\s*most\b", text[m.end():m.end() + 6], re.I):
            continue                                    # "the 2 most frequently mutated": a rank, read with the gene
        before = text[max(0, m.start() - 14):m.start()].lower()
        approx = raw.startswith("~") or any(w in before for w in APPROX_WORDS)
        nums.append(Number(val, is_pct, approx, m.start(), m.end(), m.group(0).strip(), cmp=_comparator(text, m.start())))
    return sorted(nums, key=lambda n: n.start)
