"""Record (or compare) everything the app displays, so a visual redesign can prove it changed nothing.

  python tools/ui_baseline.py record     # writes docs/redesign/baseline.json
  python tools/ui_baseline.py compare    # recomputes and lists any difference (none = nothing changed)
Uses the same functions the web app calls (/api/audit, /api/plan, /api/export), in rules-only mode, on the practice
brief and the demo test report. Records every verdict, number, correct value, suggested wording, next step, limit,
plain-words sentence and the exported files' text. Also records the page's buttons and inputs (their ids).
"""
from __future__ import annotations

import hashlib
import json
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app import decision_markdown  # noqa: E402
from auditor.audit import plan_for, run_audit, to_shared_format, final_verdict  # noqa: E402
from auditor.impact import corrected_markdown, explain  # noqa: E402
from auditor.plain import plain_summary  # noqa: E402
from auditor.release import Release  # noqa: E402

CH = ROOT.parent / "oncosys-hackathon-challenge"
OUT = ROOT / "docs/redesign/baseline.json"
REPORTS = {"practice brief": CH / "products/research-claim-auditor/practice_brief.md",
           "demo test report": ROOT / "tests/demo_test_report.md"}


def h(s: str) -> str:
    return hashlib.sha256(s.encode()).hexdigest()[:16]


REF = None     # set with --from <git ref> to snapshot the page as it is in that commit (e.g. main)


def page_html() -> str:
    if REF:
        import subprocess
        return subprocess.run(["git", "show", f"{REF}:web/index.html"], cwd=ROOT, capture_output=True, text=True,
                              encoding="utf-8").stdout
    return (ROOT / "web/index.html").read_text(encoding="utf-8")


PRESENTATION_IDS = ("ill-", "ic-", "pat-", "illustrations", "moreOpts", "s3tabs")   # new ids allowed: illustrations and layout wrappers, never controls


def snapshot() -> dict:
    rel = Release(CH / "data/tcga-brca/raw", CH / "data/tcga-brca/slide_manifest.csv")
    out = {"reports": {}}
    for name, path in REPORTS.items():
        a = run_audit(path.read_text(encoding="utf-8"), rel, semantic=False)
        plan = plan_for(a)
        impacts = {it["id"]: explain(it, final_verdict(it), a["release"]["name"], a.get("scope")) for it in a["items"]}
        plain = plain_summary(a["items"], plan, a.get("scope"), final_verdict, impacts)
        decision = {"decision": plan["decision"], "reason": "baseline", "reviewer": "baseline", "reviewer_role": "x",
                    "also_review": "x", "at": "fixed"}
        shared = to_shared_format(a, decision)
        out["reports"][name] = {
            "claims": [{"id": it["id"], "text": it["claim_text"], "verdict": it["tool_verdict"],
                        "summary": it["result"]["summary"], "values": [s["observed"] for s in it["result"]["subchecks"]],
                        "correct_value": it["result"]["correct_value"], "needed": it["result"]["needed"],
                        "next_step": impacts[it["id"]]["next_step"], "suggested_text": impacts[it["id"]]["suggested_text"]}
                       for it in a["items"]],
            "suggested_decision": plan["decision"], "why": plan["why"],
            "steps": [s["do"] + ": " + s["detail"] for s in plan["steps"]], "cant_tell": plan["cant_tell"],
            "plain_bottom_line": plain["bottom_line"], "plain_points": [p["text"] for p in plain["points"]],
            "glossary": [w["term"] for w in plain["words"]],
            "export_hashes": {"audit.json findings": h(json.dumps(shared["findings"], sort_keys=True)),
                              "decision_summary.md": h(re.sub(r"\d{4}-\d\d-\d\dT[\d:]+", "", decision_markdown(a, decision))),
                              "corrected_report.md": h(corrected_markdown(plan, a["release"]["name"]))},
        }
    html = page_html()
    body = re.sub(r"<!--.*?-->|<svg.*?</svg>", " ", html.split("<script>")[0], flags=re.S)   # comments/graphics aren't text
    out["page"] = {"element_ids": sorted(set(re.findall(r'id="([\w-]+)"', html))),
                   "buttons": sorted(set(re.findall(r'<button[^>]*id="([\w-]+)"', html))),
                   "api_calls": sorted(set(re.findall(r'api\("(/api/\w+)"', html))),
                   # every piece of static page text (labels, headings, help): later phases may ADD, never remove or edit
                   "static_text": sorted({t for t in (" ".join(x.split()) for x in re.split(r"<[^>]+>", re.sub(
                       r"<style.*?</style>", "", body, flags=re.S))) if t and not t.isspace()} | set())}
    return out


def diff(a, b, path=""):
    if isinstance(a, dict) and isinstance(b, dict):
        for k in sorted(set(a) | set(b)):
            yield from diff(a.get(k), b.get(k), f"{path}/{k}")
    elif isinstance(a, list) and isinstance(b, list) and len(a) == len(b):
        for i, (x, y) in enumerate(zip(a, b)):
            yield from diff(x, y, f"{path}[{i}]")
    elif a != b:
        yield f"{path}: {str(a)[:80]!r} -> {str(b)[:80]!r}"


if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else "compare"
    if "--from" in sys.argv:
        REF = sys.argv[sys.argv.index("--from") + 1]
    snap = snapshot()
    if mode == "record":
        OUT.parent.mkdir(parents=True, exist_ok=True)
        OUT.write_text(json.dumps(snap, indent=1, ensure_ascii=False), encoding="utf-8")
        n = sum(len(r["claims"]) for r in snap["reports"].values())
        print(f"baseline recorded: {n} claims, {len(snap['page']['buttons'])} buttons, "
              f"{len(snap['page']['element_ids'])} element ids -> {OUT.relative_to(ROOT)}")
    else:
        base = json.loads(OUT.read_text(encoding="utf-8"))
        old_ids, new_ids = set(base["page"]["element_ids"]), set(snap["page"]["element_ids"])
        removed, added = sorted(old_ids - new_ids), sorted(new_ids - old_ids)
        bad_added = [i for i in added if not i.startswith(PRESENTATION_IDS)]
        print(f"element ids: {len(removed)} removed, {len(added)} added (illustrations only: {not bad_added})")
        base["page"]["element_ids"] = snap["page"]["element_ids"] = []
        old_t, new_t = set(base["page"].get("static_text", [])), set(snap["page"]["static_text"])
        lost = sorted(old_t - new_t)
        print(f"static text: {len(lost)} removed or edited, {len(new_t - old_t)} added (labels and help lines)")
        base["page"]["static_text"] = snap["page"]["static_text"] = []
        base["page"].pop("visible_text_hash", None); snap["page"].pop("visible_text_hash", None)
        d = list(diff(base, snap)) + [f"removed id {i}" for i in removed] + [f"non-illustration id added {i}" for i in bad_added] + [f"static text removed/edited: {t[:70]!r}" for t in lost]
        print("NOTHING CHANGED: every value, button and export matches the baseline" if not d else
              f"{len(d)} DIFFERENCE(S):\n" + "\n".join(d[:40]))
        sys.exit(1 if d else 0)
