"""Run every claim in a report through the checkers and build the shared-format audit file."""
from __future__ import annotations

import datetime as dt
import re
import json

from .checks import Result, SubCheck, check_sentence
from .claims import Sentence, find_numbers, split_sentences
from .adapt import activate
from .impact import action_plan, explain
from .plain import plain_summary
from .release import Release
from .scope import detect_scope, explicit_claims, needed_for, own_arithmetic, statement_kind, table_rows

TEAM = "Cache us if u can"
PRODUCT = "Research Claim Auditor"

SEVERITY = {"contradicted": "high", "insufficient_evidence": "medium", "supported": "none"}
LABEL = {"supported": "Supported", "contradicted": "Contradicted", "insufficient_evidence": "Insufficient evidence",
         "not_a_claim": "Not a claim"}


def own_numbers_result(text: str, evidence: str, rows: list[str], scope: dict) -> Result:
    """A claim about a dataset that isn't the release: check only the report's own numbers, never the release."""
    sizes = scope.get("stated_cohort_sizes") or []
    subs = [SubCheck(lab, cl, ob, ok, rule) for lab, cl, ob, ok, rule in own_arithmetic(text, evidence, rows, sizes)]
    where = ("This report describes a different dataset, so the claim was checked only against the report's own "
             "numbers, not against TCGA-BRCA or any data release.")
    unit = " The unit of analysis (participant, sample or aliquot), the join and de-duplication are not verified."
    cited = f" Evidence the report cites: {evidence}" if evidence else ""
    if subs:
        bad = [s for s in subs if s.ok is False]
        verdict = "contradicted" if bad else "supported"
        vague = any(s.claimed in ("most", "majority", "few", "nearly") for s in subs)
        return Result(verdict=verdict, check="own_numbers", confidence="medium", subchecks=subs,
                      summary=("The report's own numbers are consistent: " if not bad else "The report's own numbers don't add up: ")
                              + "; ".join(f"{s.label} = {s.observed} (report says {s.claimed})" for s in subs) + ".",
                      correct_value="; ".join(s.observed for s in bad) or None,
                      population="The report's own dataset (not TCGA-BRCA)",
                      limitation=where + unit + (" The wording is imprecise: state the exact value." if vague else "")
                                 + cited,
                      code="# arithmetic on the numbers printed in the report\n" + "\n".join(
                          f"# {s.label}: {s.observed}" for s in subs))
    conflict = bool(re.search(r"stable|agree|concordan|consistent|conflict", text.lower()))
    return Result(verdict="insufficient_evidence", check="other_dataset", confidence="medium",
                  summary=("Nothing in the report settles this claim, and the report is about a different dataset, so the "
                           "release can't be used to check it either."
                           + (" This is a potential conflict to investigate, not a confirmed contradiction." if conflict else "")),
                  needed=needed_for(text), population="The report's own dataset (not TCGA-BRCA)",
                  limitation=where + cited)


def run_audit(report_text: str, release: Release, compare: bool | None = None) -> dict:
    """Returns the full audit as plain data: one item per claim, with the tool's verdict and evidence.

    compare=None decides from the report: a report about another dataset (e.g. a synthetic fixture) is never
    compared with the release. compare=True forces the comparison (the reviewer asked for it)."""
    ctx = activate(release)          # profile + map THIS release before anything is read or computed
    rename = {k: v["to"] for k, v in ctx.plan["renamed"].items()}
    m = release.membership
    totals = {"primary": int((m.type_code == "01").sum()), "samples": len(m), "patients": int(m.patient_id.nunique())}
    scope = detect_scope(report_text, totals)
    other = scope["mode"] == "other_dataset" and not compare
    scope["compared_with_release"] = not other
    scope["forced"] = bool(compare) and scope["mode"] == "other_dataset"
    labelled = explicit_claims(report_text)
    scope["explicit_claims"] = len(labelled)
    rows = table_rows(report_text) if other else []
    units = ([(c, Sentence(index=k, text=c["text"], numbers=find_numbers(c["text"]))) for k, c in enumerate(labelled)]
             if labelled else [(None, s) for s in split_sentences(report_text)])
    if labelled:
        scope["context_sentences"] = len(split_sentences(report_text))
    items = []
    for meta, s in units:
        if not other:
            res = check_sentence(s, release)                          # the normal path: check against the release
        elif meta:
            res = own_numbers_result(s.text, meta.get("evidence", ""), rows, scope)   # a labelled claim
        elif statement_kind(s.text):
            res = check_sentence(s, release)                          # disclaimer / instruction: not scored
        else:
            res = own_numbers_result(s.text, "", rows, scope)         # an unlabelled sentence about another dataset
            if not s.numbers and res.verdict == "insufficient_evidence" and not re.search(
                    r"\b(?:is|are|was|were|has|have|had|shows?|showed|represents?|causes?)\b", s.lower):
                res = Result(verdict="not_a_claim", check="not_a_claim", confidence="medium",
                             summary="Descriptive text with nothing to measure; not scored.")
        if meta and res.verdict == "not_a_claim":   # the report itself says this is a claim: never dismiss it
            res = Result(verdict="insufficient_evidence", check="unrecognised", confidence="low",
                         summary="The report labels this as a claim, but the tool has no automatic check for it. "
                                 "A reviewer must check it by hand.", needed=needed_for(s.text),
                         limitation="Unchecked by the tool: this is not a judgement that the data can't answer it.")
        # release-specific notes: renamed fields that were used, and data this release lacks
        used = [f for f in res.fields if f in rename]
        if used:
            res.limitation = ("In this release " + "; ".join(f"`{f}` is stored as `{rename[f]}`" for f in used)
                              + " (matched on its values, then validated). " + res.limitation)
        if res.verdict == "insufficient_evidence" and res.check in ("unrecognised", "engine") and ctx.missing_note():
            res.limitation = (res.limitation + " " + ctx.missing_note()).strip()
        n_claims = len([i for i in items if i["tool_verdict"] != "not_a_claim"])
        items.append({
            "id": f"C{n_claims + 1:02d}" if res.verdict != "not_a_claim" else f"S{s.index + 1:02d}",
            "label": (meta or {}).get("label"),             # the report's own claim number, e.g. "C3"
            "title": (meta or {}).get("title"),
            "evidence_cited": (meta or {}).get("evidence"),  # what the report says supports the claim
            "sentence_index": s.index,
            "claim_text": s.text,
            "numbers": [n.text for n in s.numbers],
            "tool_verdict": res.verdict,
            "result": res.to_dict(),
            "review": None,     # filled in by a person: {"decision": "accept"|"override", "verdict", "reason", "reviewer"}
        })
        items[-1]["impact"] = explain(items[-1], res.verdict, release.name, scope)
    return {
        "created": dt.datetime.now().isoformat(timespec="seconds"),
        "release": {"name": release.name, "dir": str(release.dir), "files": release.checksums,
                    "fingerprint": ctx.fingerprint, "adaptation": ctx.report() if ctx.changed else None},
        "scope": scope,
        "items": items,
    }


def suggested_decision(items: list[dict], release_name: str = "A") -> tuple[str, str]:
    plan = action_plan(items, release_name, final_verdict)
    return plan["decision"], plan["why"]


def plan_for(audit: dict) -> dict:
    """Next steps for the whole report, using the reviewers' final verdicts."""
    plan = action_plan(audit["items"], audit["release"]["name"], final_verdict, audit.get("scope"))
    plan["scope"] = audit.get("scope")
    return plan


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
        ev = [{"kind": "claim", "id": it.get("label") or it["id"], "note": it["claim_text"][:300]}]
        if it.get("evidence_cited"):
            ev.append({"kind": "claim", "id": f"{it.get('label') or it['id']}-evidence-cited",
                       "note": "Evidence the report cites: " + it["evidence_cited"][:300]})
        ev += [{"kind": "file", "id": f, "release": audit["release"]["name"], "file": f,
                "note": "fields: " + ", ".join(r["fields"]) if r["fields"] else ""} for f in r["files"]]
        ev += [{"kind": "analysis", "id": f"{it['id']}-calc", "note": f"{sc['label']}: claimed {sc['claimed']}, data {sc['observed']}"}
               for sc in r["subchecks"]]
        rv = it.get("review") or {}
        imp = explain(it, verdict, audit["release"]["name"], audit.get("scope"))
        f = {
            "id": it["id"],
            "report_label": it.get("label"),
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
            # what happens after the verdict
            "why_it_matters": imp["why_it_matters"],
            "next_step": imp["next_step"],
            "ask_author": imp["ask_author"],
            "suggested_text": imp["suggested_text"],
            "cannot_tell": imp["cant_tell"],
        }
        if verdict == "contradicted":
            # the reviewer's number wins; else the tool's; else what the data showed in each measured check
            f["correct_value"] = ((rv.get("correct_value") if rv else None) or r.get("correct_value")
                                  or "; ".join(f"{sc['label']}: {sc['observed']}" for sc in r["subchecks"])
                                  or "not computed by the tool: see the reviewer's reason")
        findings.append(f)
    scope = audit.get("scope") or {}
    compared = scope.get("compared_with_release", True)
    out = {
        "format_version": "0.2",
        "producer": {"team": team, "product": PRODUCT, "track": "evidence-navigator"},
        "data": {"dataset": "TCGA-BRCA", "releases": [{"name": audit["release"]["name"], "files": audit["release"]["files"]}],
                 "compared_with_release": compared,
                 "note": "" if compared else ("Claims were NOT compared with this release: " + scope.get("reason", ""))},
        "question": ("Is each factual claim in this report supported by the TCGA-BRCA release?" if compared else
                     "Is each claim in this report supported by the report's own evidence? (It describes a different "
                     "dataset, so it was not compared with TCGA-BRCA.)"),
        "report_scope": scope,
        "findings": findings,
    }
    plan = plan_for(audit)
    out["next_steps"] = {"suggested_decision": plan["decision"], "why": plan["why"], "steps": plan["steps"],
                         "audit_cannot_tell": plan["cant_tell"]}
    out["plain_summary"] = plain_summary(audit["items"], plan, scope, final_verdict)
    if decision:
        out["verdict"] = decision["decision"]
        out["decision_record"] = decision
    return out


def write_json(obj: dict, path) -> None:
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, indent=2, ensure_ascii=True, default=str)   # ASCII: readable with any default encoding
