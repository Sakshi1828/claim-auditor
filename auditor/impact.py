"""What happens after a verdict: why it matters, what the user should do next, and what the tool can't tell them.

Finding a wrong number is the easy part; every team's checker finds the same ones. This module turns each verdict
into a decision a reviewer can act on, and is honest about where the tool stops. Everything is derived from the
measured values in the audit, so it changes when the data or the report changes. Nothing here is clinical advice.
"""
from __future__ import annotations

import re

NUM = re.compile(r"-?\d[\d,]*(?:\.\d+)?")

# Why a wrong or unsupported number of each kind matters to the person using the report.
STAKES = {
    "subtype_share": "Subtype shares set how many tumors a study can expect in each group. A wrong share changes group "
                     "sizes, statistical power and any comparison between subtypes.",
    "receptor_share": "ER, PR and HER2 shares decide which tumors fall into each receptor group. A wrong share means the "
                      "groups being compared are not the groups described.",
    "mutation_frequency": "Mutation frequencies are used to pick genes to study and to size mutant-vs-wild-type "
                          "comparisons. A wrong rate points work at the wrong gene or under-sizes the groups.",
    "cohort_coverage": "The cohort size is the number of tumors an analysis can actually use. If it's wrong, the analysis "
                       "was run on a different set of samples than the report says, or layers were joined differently.",
    "age": "Age summaries describe who is in the cohort. A wrong figure misdescribes the population the results apply to.",
    "survival": "Event counts and follow-up decide whether a survival analysis has enough deaths to say anything. Wrong "
                "counts overstate how much the data can show.",
    "protein_comparison": "A comparison that runs the wrong way reverses the report's conclusion, not just a number.",
    "manifest": "Slide counts and sizes decide how many images an imaging study can use and how much it must download. "
                "The two manifests don't count slides the same way, so the source matters.",
    "treatment_response": "A treatment-effect statement that the data can't support will be read as a finding and can be "
                          "repeated in grant text, papers or slides.",
    "unrecognised": "No one has checked this number yet. If it's wrong, nothing in this audit would have caught it.",
}

# What the tool can't tell the user, by kind of check (in addition to each claim's own limitation).
LIMITS = {
    "subtype_share": "Which subtype column or denominator the author used, or whether the author's subtyping is better.",
    "receptor_share": "Whether the receptor tests were done well. It counts the recorded result, not the lab work.",
    "mutation_frequency": "Whether a mutation is a driver or matters biologically. Counts depend on the gene-level calling.",
    "cohort_coverage": "Whether the author meant a different release or joined the files another way. Only the release "
                       "it was given is counted.",
    "age": "Anything about individual patients. Age is summarised only.",
    "survival": "Whether one group survives longer than another. That needs a pre-specified time-to-event analysis.",
    "protein_comparison": "Whether the difference is statistically significant or meaningful. Only the direction and size "
                          "are shown.",
    "manifest": "What is in the images. It reads the manifest rows, not the slides themselves.",
    "treatment_response": "Whether any treatment works. This release has no response outcomes, and that question needs a "
                          "trial or a pre-specified analysis.",
    "unrecognised": "Anything. This sentence was not checked.",
}


def _first_num(s: str | None) -> float | None:
    m = NUM.search(s or "")
    return float(m.group(0).replace(",", "")) if m else None


def _short_obs(observed: str) -> str:
    """'49.9% (421 of 844)' -> '49.9%'; '1,098' -> '1,098'; '2.83 (3,111 / 1,098)' -> '2.83'."""
    m = re.match(r"\s*(-?\d[\d,]*(?:\.\d+)?\s*%?)", observed or "")
    return m.group(1).strip() if m else ""


def _gap(claimed: str, observed: str) -> str:
    c, o = _first_num(claimed), _first_num(observed)
    if c is None or o is None:
        return ""
    if "%" in claimed:
        d = c - o
        m = re.search(r"\((\d[\d,]*) of (\d[\d,]*)\)", observed)
        extra = ""
        if m:
            den = int(m.group(2).replace(",", ""))
            extra = f", about {abs(round(d / 100 * den)):,} of {den:,} tumors"
        return f"{abs(d):.1f} percentage points {'too high' if d > 0 else 'too low'}{extra}"
    d = c - o
    rel = f" ({abs(d) / o * 100:.0f}%)" if o else ""
    return f"{abs(d):,.{0 if float(d).is_integer() else 2}f} {'too many' if d > 0 else 'too few'}{rel}"


def _matching_alternative(result: dict) -> dict | None:
    """Does the claimed number match the same question under another reasonable definition? Then the report may be
    right about a different thing, and the fix is to state the definition, not to change the number."""
    wrong = [s for s in result["subchecks"] if s["ok"] is False]
    if len(wrong) != 1:
        return None
    c = _first_num(wrong[0]["claimed"])
    if c is None:
        return None
    for a in result.get("alternatives") or []:
        a = {**a, "definition": re.sub(r"^use\s+|\s+instead$", "", a.get("definition", ""), flags=re.I)}
        o = _first_num(a.get("value"))
        if o is None:
            continue
        tol = 1.5 if "%" in wrong[0]["claimed"] else 0
        if abs(c - o) <= tol:
            return a
    return None


def _replace_numbers(sentence: str, result: dict) -> str:
    out = sentence
    for s in result["subchecks"]:
        if s["ok"] is False:
            new = _short_obs(s["observed"])
            old = s["claimed"].split(" ")[0] if " " in s["claimed"] and NUM.match(s["claimed"]) else s["claimed"]
            if new and NUM.match(old or "") and old in out:
                full = s["observed"] if re.fullmatch(r"[\d.,]+%? \([\d,]+ (?:of|/) [\d,]+\)", s["observed"]) else new
                approx = re.compile(r"(?:about|approximately|around|roughly|nearly|almost|~)\s*" + re.escape(old), re.I)
                out = approx.sub(full, out, count=1) if approx.search(out) else out.replace(old, full, 1)
            elif s["claimed"] in ("most", "all") or not new:
                return ""       # a wording claim: no safe automatic rewrite
    return out if out != sentence else ""


def explain(item: dict, verdict: str, release_name: str) -> dict:
    """Why it matters, what to do next, what the tool can't tell, and a suggested rewrite for one claim."""
    r = item["result"]
    check = r["check"]
    text = item["claim_text"]
    wrong = [s for s in r["subchecks"] if s["ok"] is False]
    stakes = STAKES.get(check, STAKES["unrecognised"])
    limits = [LIMITS.get(check, "")]
    if r.get("limitation"):
        limits.append(r["limitation"])
    out = {"why_it_matters": "", "next_step": "", "cant_tell": [x for x in limits if x], "suggested_text": "",
           "ask_author": "", "action": ""}

    if verdict == "contradicted":
        gaps = "; ".join(f"{s['label']}: report says {s['claimed']}, data says {s['observed']} "
                         f"({_gap(s['claimed'], s['observed']) or 'does not match'})" for s in wrong)
        out["why_it_matters"] = f"{gaps}. {stakes}" if gaps else stakes
        alt = _matching_alternative(r)
        if alt:
            out["action"] = "state_definition"
            out["ask_author"] = (f"Your number matches \"{alt['definition']}\" ({alt['value']}). Is that the definition you "
                                 f"used? If so, say so in the sentence.")
            out["next_step"] = ("Ask the author which definition they used before changing anything. The number may be right "
                                "under another definition, and then the fix is to name that definition in the sentence.")
        else:
            out["action"] = "fix_number"
            out["ask_author"] = ("How was this number calculated: which file, column, denominator and release? "
                                 "Send the calculation so it can be rerun.")
            cv = (item.get("review") or {}).get("correct_value") or r.get("correct_value") or "the value the data gives"
            out["next_step"] = (f"Correct the number to {cv} before the "
                                f"report is shared, then rerun the audit. Anything built on the old number (sample sizes, "
                                f"figures, abstract text) needs the same fix.")
        if alt:   # don't change a number that may be right: ask for the definition to be named
            out["next_step"] += " " + out["ask_author"]
            out["suggested_text"] = (f"{text} [Name the definition: this matches {alt['definition']} ({alt['value']}). "
                                     f"Under the tool's default it is {r.get('correct_value')}.]")
        else:
            out["suggested_text"] = _replace_numbers(text, r)
        out["cant_tell"].insert(0, "Why the author's number differs: a different column, denominator or release, a "
                                   "filtering step, or a typo. Only the author can say.")
    elif verdict == "insufficient_evidence":
        out["why_it_matters"] = stakes
        if check == "unrecognised":
            out["action"] = "check_by_hand"
            out["next_step"] = ("A reviewer must check this sentence by hand, or mark it as not a claim, before the report is "
                                "used. The tool has no rule for it, so this is not a finding either way.")
        elif r.get("needed", "").startswith("This release has no"):
            out["action"] = "rerun_other_release"
            out["next_step"] = f"Rerun this check on a release that includes the missing file. {r['needed']}"
        else:
            out["action"] = "remove_or_reword"
            out["next_step"] = ("Remove the sentence or reword it as an open question. Don't present it as a result of this "
                                "dataset." + (f" To answer it, you would need: {r['needed']}" if r.get("needed") else ""))
            out["suggested_text"] = "[Remove, or reword as an open question: this release cannot show it.]"
        out["ask_author"] = "What data or analysis supports this statement? If none, it should come out of the results."
    elif verdict == "supported":
        out["action"] = "keep"
        definition = ", ".join(r.get("fields") or []) or "the fields shown"
        out["why_it_matters"] = (f"It matches release {release_name}, so it can stay. Readers can only reproduce it if the "
                                 f"definition is stated.")
        out["next_step"] = (f"Keep it. Cite release {release_name} and the definition used ({definition}"
                            f"{'; n = ' + format(r['n'], ',') if r.get('n') else ''}).")
        if r.get("confidence") == "medium":
            out["action"] = "decide_rounding"
            out["next_step"] = ("Borderline: the number is close to the tolerance. Decide whether the rounding is acceptable, "
                                "or replace it with the exact value: " + "; ".join(s["observed"] for s in r["subchecks"]
                                                                                   if s["ok"] is not None) + ".")
        out["cant_tell"].insert(0, "Whether the author's own analysis was done this way. The tool checks the number, "
                                   "not their method.")
        if r.get("alternatives"):
            out["cant_tell"].append("The answer changes under other reasonable definitions (shown on the claim), so the "
                                    "definition must be stated.")
    return out


def action_plan(items: list[dict], release_name: str, final_verdict) -> dict:
    """Report-level next steps, the corrected report, and what the audit can't tell the reader."""
    claims = [(it, final_verdict(it)) for it in items]
    checkable = [(it, v) for it, v in claims if v != "not_a_claim"]
    by = lambda k: [(it, v) for it, v in checkable if v == k]      # noqa: E731
    con, ins, sup = by("contradicted"), by("insufficient_evidence"), by("supported")
    unrec = [(it, v) for it, v in ins if it["result"]["check"] == "unrecognised"]
    unreviewed = [it for it, _ in checkable if not it.get("review")]
    steps = []
    for it, v in con:
        e = explain(it, v, release_name)
        steps.append({"id": it["id"], "priority": 1, "do": "Ask the author which definition" if e["action"] == "state_definition"
                      else "Fix the number", "detail": e["next_step"], "suggested_text": e["suggested_text"],
                      "correct_value": (it.get("review") or {}).get("correct_value") or it["result"].get("correct_value")})
    for it, v in ins:
        e = explain(it, v, release_name)
        label = {"check_by_hand": "Check by hand", "rerun_other_release": "Rerun on a fuller release"}.get(
            e["action"], "Remove or reword")
        steps.append({"id": it["id"], "priority": 2 if e["action"] != "check_by_hand" else 3, "do": label,
                      "detail": e["next_step"], "suggested_text": e["suggested_text"]})
    for it, v in sup:
        if it["result"].get("confidence") == "medium":
            steps.append({"id": it["id"], "priority": 3, "do": "Decide on rounding", "detail": explain(it, v, release_name)["next_step"],
                          "suggested_text": ""})
    steps.sort(key=lambda s: s["priority"])

    if not checkable:
        decision, why = "Stop", "No checkable claims were found, so nothing in this report has been verified."
    elif con:
        decision = "Fix a problem"
        why = (f"{len(con)} of {len(checkable)} claims {'contradicts' if len(con) == 1 else 'contradict'} release {release_name}. The report shouldn't be shared, "
               f"cited or used to plan work until they are corrected and the audit is rerun.")
    elif ins:
        decision = "Narrow the question"
        why = (f"No numbers are wrong, but {len(ins)} claim(s) go beyond what release {release_name} can show. Remove or "
               f"reword them, and the rest of the report can proceed.")
    else:
        decision, why = "Proceed", f"All {len(sup)} checked claims match release {release_name}."
    if unreviewed:
        why += f" {len(unreviewed)} verdict(s) still need a person to confirm them."

    cant = [
        "Whether the analyses behind the supported numbers were done correctly. The tool reproduces each number from the "
        "data; it does not review the author's methods.",
        "Anything clinical: whether a result matters for patients, diagnosis or treatment. This is a research-data check only.",
        "Whether differences are statistically significant. Comparisons are shown by direction and size only.",
        f"Whether the report was written about another release or definition. Everything here is checked against release "
        f"{release_name}; each claim card shows the other reasonable definitions.",
        "Whether the source data itself is right. The tool trusts the frozen files and only flags known problems "
        "(redacted survival rows, the gap between the two manifests).",
    ]
    if unrec:
        cant.insert(0, f"{len(unrec)} sentence(s) the tool could not read ({', '.join(it['id'] for it, _ in unrec)}). "
                       f"Nothing has checked them yet.")
    cant.append("Claims stated without numbers, or spread across several sentences, may be missed: the tool reads one "
                "sentence at a time.")

    # The corrected report: the same sentences, with fixes applied and unsupported claims marked.
    corrected = []
    for it, v in claims:
        if v == "contradicted":
            e = explain(it, v, release_name)
            rv = it.get("review") or {}
            new = e["suggested_text"] if (e["action"] == "fix_number" and e["suggested_text"]) else ""
            if rv.get("correct_value") and not new:
                new = f"{it['claim_text']} [Correct value: {rv['correct_value']}]"
            corrected.append({"id": it["id"], "status": "fixed" if new else "needs_author", "old": it["claim_text"],
                              "new": new or f"{it['claim_text']} [CHECK WITH AUTHOR: {e['ask_author']}]"})
        elif v == "insufficient_evidence":
            e = explain(it, v, release_name)
            corrected.append({"id": it["id"], "status": "check_by_hand" if e["action"] == "check_by_hand" else "remove",
                              "old": it["claim_text"], "new": it["claim_text"] + " " + (
                                  "[NOT CHECKED: verify by hand]" if e["action"] == "check_by_hand" else
                                  "[UNSUPPORTED BY THIS RELEASE: remove or reword]")})
        else:
            corrected.append({"id": it["id"], "status": "kept", "old": it["claim_text"], "new": it["claim_text"]})
    return {"decision": decision, "why": why, "steps": steps, "cant_tell": cant, "corrected": corrected,
            "counts": {"supported": len(sup), "contradicted": len(con), "insufficient_evidence": len(ins),
                       "unreviewed": len(unreviewed)}}


def corrected_markdown(plan: dict, release_name: str) -> str:
    lines = [f"# Corrected report (suggested by the Research Claim Auditor, release {release_name})", "",
             "*Suggested edits for the author. Each change must be confirmed by the author and a reviewer. "
             "Research use only.*", ""]
    for c in plan["corrected"]:
        lines.append(c["new"])
        lines.append("")
    changes = [c for c in plan["corrected"] if c["status"] != "kept"]
    if changes:
        lines += ["---", "## Changes", ""]
        for c in changes:
            lines.append(f"- **{c['id']}** ({c['status'].replace('_', ' ')}): \"{c['old']}\"")
    return "\n".join(lines) + "\n"
