"""The audit in plain words, for readers with no data or biology background.

Built only from the verdicts and numbers the checks already produced: it rewords, it never adds a finding.
"""
from __future__ import annotations

import re

# Short, neutral definitions. Research vocabulary only: nothing here is medical advice.
GLOSSARY = [
    (r"\bluminal a\b|\blum ?a\b", "Luminal A",
     "a common breast cancer subtype, grouped by which genes are active; usually responds to hormones and grows slowly"),
    (r"\bluminal b\b|\blum ?b\b", "Luminal B", "a hormone-sensitive breast cancer subtype that tends to grow faster than Luminal A"),
    (r"basal", "Basal-like", "a breast cancer subtype that usually lacks hormone receptors and HER2"),
    (r"triple[- ]negative|\btnbc\b", "Triple-negative",
     "a breast cancer with no estrogen receptors, no progesterone receptors and no extra HER2"),
    (r"\bher2\b", "HER2", "a protein that some breast cancers make too much of (\"HER2-positive\")"),
    (r"\ber[- ]?(?:positive|negative|\+|status)|\bestrogen|\ber-alpha", "ER (estrogen receptor)",
     "a receptor for the hormone estrogen; \"ER-positive\" tumors have it"),
    (r"\bpr[- ]?(?:positive|negative|\+|status)|progesterone", "PR (progesterone receptor)",
     "a receptor for the hormone progesterone"),
    (r"\btp53\b", "TP53", "a gene that normally helps stop damaged cells from growing; often changed in cancer"),
    (r"\bpik3ca\b", "PIK3CA", "a gene that passes on growth signals inside cells; often changed in breast cancer"),
    (r"\bcdh1\b", "CDH1", "a gene that helps cells stick together"),
    (r"\bgata3\b", "GATA3", "a gene involved in hormone-sensitive breast cells"),
    (r"mutat", "Mutation", "a change in a gene's DNA"),
    (r"pam50|rna subtype|subtype call", "Subtype (PAM50)",
     "a way of sorting breast cancers into groups based on the activity of 50 genes"),
    (r"\brna\b", "RNA data", "measurements of which genes are switched on in the tumor"),
    (r"protein", "Protein data", "measurements of the proteins found in the tumor tissue"),
    (r"copy number", "Copy number", "whether pieces of the tumor's DNA are duplicated or missing"),
    (r"primary tumou?r", "Primary tumor", "the original tumor, not a cancer that has spread and not normal tissue"),
    (r"\bslides?\b", "Slide", "a microscope image of a thin slice of the tissue"),
    (r"surviv|deaths?\b|died", "Survival data", "how long each patient was followed and whether they died in that time"),
    (r"\bmedian\b", "Median", "the middle value when everything is sorted from lowest to highest"),
    (r"\bcohort\b", "Cohort", "the group of patients included in a study"),
]

DECISION_LINE = {
    "Proceed": "The numbers we could check are right. The report can be used, keeping in mind the limits listed.",
    "Fix a problem": "Don't share or rely on this report until the wrong numbers are fixed.",
    "Narrow the question": "The report claims more than the data can show. Remove or soften those statements before using it.",
    "Stop": "Nothing in this report could be verified, so it shouldn't be relied on yet.",
}


def _short(text: str, n: int = 150) -> str:
    t = re.sub(r"\s+", " ", text).strip()
    return t if len(t) <= n else t[:n].rsplit(" ", 1)[0] + "…"


def _clean(value: str) -> str:
    """Drop column names and code formatting from a measured value; keep the first, main reading."""
    v = str(value or "").split(";")[0].split(" | ")[0]
    v = re.sub(r"`[^`]*`", "", v)
    v = re.sub(r"\s+", " ", v).strip(" :,")
    return v


def _about(value: str) -> str:
    """'49.9% (421 of 844)' -> 'about half'. Gives ordinary readers a feel for a percentage."""
    m = re.search(r"(\d+(?:\.\d+)?)\s*%", value or "")
    if not m:
        return ""
    p = float(m.group(1))
    for lo, hi, words in [(0, 3, "very few"), (3, 7, "about 1 in 20"), (7, 12, "about 1 in 10"), (12, 15, "about 1 in 8"),
                          (15, 18, "about 1 in 6"), (18, 22.5, "about 1 in 5"), (22.5, 28, "about 1 in 4"),
                          (28, 36, "about 1 in 3"), (36, 45, "about 2 in 5"), (45, 48, "a bit under half"),
                          (48, 50, "just under half"), (50, 52, "just over half"), (52, 55, "a bit over half"),
                          (55, 63, "about 3 in 5"), (63, 70, "about 2 in 3"), (70, 78, "about 3 in 4"),
                          (78, 85, "about 4 in 5"), (85, 93, "about 9 in 10"), (93, 98, "almost all"), (98, 101, "nearly all")]:
        if lo <= p < hi:
            return words
    return ""


def _reading(value: str, claimed: str = "") -> str:
    v = re.sub(r"\bmean\b", "average", _clean(value))
    a = _about(v)
    if a and a == _about(claimed):      # the hint would sound like agreement: leave it out
        a = ""
    return f"{v}, {a}" if a and a not in v else v


def _said(claimed: str) -> str:
    c = _clean(claimed)
    return c[0].lower() + c[1:] if len(c) > 1 and c[0].isupper() and not c[1].isupper() else c


def _need(r: dict) -> str:
    """What data would settle the claim, as one short phrase (or '' when the tool gave an instruction instead)."""
    need = re.split(r"\s*\(|\.\s|\.$", (r.get("needed") or "").strip())[0].strip(" ,;:")
    if not need or re.match(r"(a|the) reviewer|ask\b|check\b|mark\b", need, re.I):
        return ""
    return need[0].lower() + need[1:]


def _first_wrong(item: dict) -> dict | None:
    for sc in item["result"].get("subchecks") or []:
        if sc.get("ok") is False:
            return sc
    return None


def _point(item: dict, verdict: str, impact: dict, other: bool) -> dict:
    claim = f"“{_short(item['claim_text'])}”"
    who = item.get("label") or item["id"]
    r = item["result"]
    action = (impact or {}).get("action", "")
    if verdict == "contradicted":
        sc = _first_wrong(item)
        rv = item.get("review") or {}
        right = rv.get("correct_value") or (sc and sc.get("observed")) or r.get("correct_value") or ""
        claimed = sc.get("claimed", "") if sc else ""
        if action == "state_definition":
            return {"id": who, "mark": "ask", "label": "Depends how you count",
                    "text": f"{claim} Counted the usual way, the data shows {_reading(right, claimed)}, not "
                            f"{_said(claimed)}. Another reasonable way of counting comes close to the report's number, "
                            f"so the author needs to say how they counted."}
        src = "the report's own numbers show" if other else "the data shows"
        if rv.get("correct_value"):
            text = f"{claim} A reviewer checked it and found the correct value is {_reading(right, claimed)}."
        elif claimed and right:
            text = f"{claim} The report says {_said(claimed)}, but {src} {_reading(right, claimed)}."
        elif right:
            text = f"{claim} This doesn't match: {src} {_reading(right)}."
        else:
            text = f"{claim} A reviewer found this doesn't match the data."
        return {"id": who, "mark": "wrong", "label": "Wrong", "text": text}
    if verdict == "supported":
        if action == "make_precise":
            return {"id": who, "mark": "ok", "label": "Right, but vague",
                    "text": f"{claim} is consistent with the report's own figures, but should give the exact number."}
        return {"id": who, "mark": "ok", "label": "Right",
                "text": f"{claim} matches {'the report’s own figures' if other else 'the data'}."}
    if verdict == "insufficient_evidence":
        if action == "state_definition":
            return {"id": who, "mark": "ask", "label": "Depends how you count",
                    "text": f"{claim} is right if counted one way and wrong if counted another. "
                            f"The author needs to say which way they counted."}
        need = _need(r)
        why = f" Checking it would need {need}." if need else " A person needs to check it by hand."
        if other:
            return {"id": who, "mark": "unknown", "label": "Can't confirm",
                    "text": f"{claim} isn't backed up by evidence in the report itself.{why}"}
        return {"id": who, "mark": "unknown", "label": "Can't check",
                "text": f"{claim} goes beyond what this data can show, so it can be neither confirmed nor ruled out.{why}"}
    return {"id": who, "mark": "none", "label": "", "text": ""}


def plain_summary(items: list[dict], plan: dict, scope: dict | None, final_verdict, impacts: dict | None = None) -> dict:
    """A short, jargon-free reading of the audit: headline, bottom line, one sentence per claim, word list."""
    scope = scope or {}
    other = scope.get("compared_with_release") is False
    claims = [it for it in items if final_verdict(it) != "not_a_claim"]
    n = len(claims)
    count = {"contradicted": 0, "supported": 0, "insufficient_evidence": 0}
    points = []
    for it in claims:
        v = final_verdict(it)
        count[v] = count.get(v, 0) + 1
        points.append(_point(it, v, (impacts or {}).get(it["id"]) or it.get("impact") or {}, other))
    order = {"wrong": 0, "ask": 1, "unknown": 2, "ok": 3}
    points.sort(key=lambda p: order.get(p["mark"], 4))

    what = ("This report describes its own set of data, not the public breast cancer data we hold, so we only checked "
            "whether its numbers agree with each other and with the evidence it cites."
            if other else
            "We checked each factual statement in this report against TCGA-BRCA, a large public research dataset "
            "about breast cancer patients and their tumors.")
    parts = []
    if count["supported"]:
        parts.append(f"{count['supported']} {'is' if count['supported'] == 1 else 'are'} right")
    if count["contradicted"]:
        parts.append(f"{count['contradicted']} {'has' if count['contradicted'] == 1 else 'have'} a wrong number")
    if count["insufficient_evidence"]:
        parts.append(f"{count['insufficient_evidence']} can't be checked with "
                     f"{'the evidence given' if other else 'this data'}")
    tally = (f"Of {n} statement{'s' if n != 1 else ''} we could test, " + ", ".join(parts[:-1])
             + (" and " if len(parts) > 1 else "") + parts[-1] + ".") if parts else "We found no statements we could test."

    text = " ".join(it["claim_text"].lower() for it in claims)
    words = [{"term": term, "meaning": meaning} for pat, term, meaning in GLOSSARY if re.search(pat, text)]
    return {
        "what_we_did": what,
        "tally": tally,
        "bottom_line": DECISION_LINE.get(plan.get("decision"), plan.get("why", "")),
        "points": points,
        "words": words,
        "note": "This checks research numbers only. It is not medical advice and says nothing about any individual patient.",
    }


def plain_markdown(p: dict) -> list[str]:
    icon = {"wrong": "✗", "ok": "✓", "ask": "?", "unknown": "–"}
    lines = ["## In plain words", "", f"**Bottom line: {p['bottom_line']}**", "", p["what_we_did"], "", p["tally"], ""]
    lines += [f"- {icon.get(x['mark'], '-')} **{x['label']}** ({x['id']}): {x['text']}" for x in p["points"] if x["text"]]
    if p["words"]:
        lines += ["", "**Words used above:**", ""] + [f"- *{w['term']}*: {w['meaning']}" for w in p["words"]]
    return lines + ["", f"_{p['note']}_", ""]
