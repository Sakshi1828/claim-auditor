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


def find_numbers(text: str) -> list[Number]:
    nums = []
    for m in NUM_RE.finditer(text):
        raw = m.group(1)
        # skip years and things like "TCGA-BRCA" codes or "2012" in column names
        val = float(raw.replace(",", "").replace("~", ""))
        is_pct = bool(m.group(2))
        if not is_pct and 1900 <= val <= 2100 and "," not in raw:
            continue
        before = text[max(0, m.start() - 14):m.start()].lower()
        approx = raw.startswith("~") or any(w in before for w in APPROX_WORDS)
        nums.append(Number(val, is_pct, approx, m.start(), m.end(), m.group(0).strip()))
    return nums
