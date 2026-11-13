"""Run every claim in a report through the checkers and build the shared-format audit file."""
from __future__ import annotations

import datetime as dt
import json

from .checks import check_sentence
from .claims import split_sentences
from .release import Release

TEAM = "Cache us if u can"
PRODUCT = "Research Claim Auditor"

SEVERITY = {"contradicted": "high", "insufficient_evidence": "medium", "supported": "none"}
LABEL = {"supported": "Supported", "contradicted": "Contradicted", "insufficient_evidence": "Insufficient evidence",
         "not_a_claim": "Not a claim"}


def run_audit(report_text: str, release: Release) -> dict:
    """Returns the full audit as plain data: one item per sentence, with the tool's verdict and evidence."""
    items = []
    for s in split_sentences(report_text):
        res = check_sentence(s, release)
        items.append({
            "id": f"C{len([i for i in items if i['tool_verdict'] != 'not_a_claim']) + 1:02d}" if res.verdict != "not_a_claim" else f"S{s.index + 1:02d}",
            "sentence_index": s.index,
            "claim_text": s.text,
            "numbers": [n.text for n in s.numbers],
            "tool_verdict": res.verdict,
            "result": res.to_dict(),
            "review": None,     # filled in by a person: {"decision": "accept"|"override", "verdict", "reason", "reviewer"}
        })
    return {
        "created": dt.datetime.now().isoformat(timespec="seconds"),
        "release": {"name": release.name, "dir": str(release.dir), "files": release.checksums},
        "items": items,
    }


def suggested_decision(items: list[dict]) -> tuple[str, str]:
    v = [final_verdict(i) for i in items if final_verdict(i) != "not_a_claim"]
    if not v:
        return "Stop", "No checkable claims were found."
    if "contradicted" in v:
        return "Fix a problem", f"{v.count('contradicted')} claim(s) contradict the data and must be corrected before the report is used."
    if "insufficient_evidence" in v:
        return "Narrow the question", f"{v.count('insufficient_evidence')} claim(s) go beyond what this data can show; remove or reword them."
    return "Proceed", "Every checked claim is supported by the data."


def final_verdict(item: dict) -> str:
    rv = item.get("review") or {}
    return rv.get("verdict") or item["tool_verdict"]


def to_shared_format(audit: dict, decision: dict | None = None, team: str = TEAM) -> dict:
    """The organizers' findings format v0.2: one claim_check finding per claim."""
    findings = []
    for it in audit["items"]:
        verdict = final_verdict(it)
        if verdict == "not_a_claim":
            continue
        r = it["result"]
        ev = [{"kind": "claim", "id": it["id"], "note": it["claim_text"][:300]}]
        ev += [{"kind": "file", "id": f, "release": audit["release"]["name"], "file": f,
                "note": "fields: " + ", ".join(r["fields"]) if r["fields"] else ""} for f in r["files"]]
        ev += [{"kind": "analysis", "id": f"{it['id']}-calc", "note": f"{sc['label']}: claimed {sc['claimed']}, data {sc['observed']}"}
               for sc in r["subchecks"]]
        rv = it.get("review") or {}
        f = {
            "id": it["id"],
            "kind": "claim_check",
            "summary": r["summary"],
            "severity": SEVERITY[verdict],
            "confidence": r["confidence"],
            "evidence": ev,
            "limitation": " ".join(x for x in [r["limitation"], ("Data needed: " + r["needed"]) if r["needed"] else ""] if x),
            "needs_human_review": not rv,
            "claim_text": it["claim_text"],
            "claim_verdict": verdict,
            # extra fields (allowed by the schema) so the reviewer's trail is kept
            "tool_verdict": it["tool_verdict"],
            "review": rv or None,
            "calculation": r["code"],
            "n": r["n"],
        }
        if verdict == "contradicted":
            f["correct_value"] = r.get("correct_value") or (rv.get("correct_value") if rv else None) or "see evidence"
        findings.append(f)
    out = {
        "format_version": "0.2",
        "producer": {"team": team, "product": PRODUCT, "track": "evidence-navigator"},
        "data": {"dataset": "TCGA-BRCA", "releases": [{"name": audit["release"]["name"], "files": audit["release"]["files"]}]},
        "question": "Is each factual claim in this report supported by the TCGA-BRCA release?",
        "findings": findings,
    }
    if decision:
        out["verdict"] = decision["decision"]
        out["decision_record"] = decision
    return out


def write_json(obj: dict, path) -> None:
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, indent=2, ensure_ascii=True, default=str)   # ASCII: readable with any default encoding
