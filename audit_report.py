"""Command-line Claim Auditor. Writes audit.json in the organizers' shared format.

  python audit_report.py                         # the practice report
  python audit_report.py path/to/report.md       # any report
  python audit_report.py --envelope 07 amber falcon river quartz   # Saturday: unseal and audit in one go

Options: --challenge DIR (the challenge repo, default ../oncosys-hackathon-challenge)
         --release DIR   (release folder, default <challenge>/data/tcga-brca/raw)
         --out FILE      (default outputs/audit.json)
"""
from __future__ import annotations

import argparse
import os
import pathlib
import sys
import time

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from auditor.audit import LABEL, plan_for, run_audit, to_shared_format, write_json  # noqa: E402
from auditor.impact import corrected_markdown  # noqa: E402
from auditor.envelope import opened_dir, unseal  # noqa: E402
from auditor.release import Release  # noqa: E402

DEFAULT_CHALLENGE = HERE.parent / "oncosys-hackathon-challenge"
ICON = {"supported": "OK ", "contradicted": "XX ", "insufficient_evidence": "?? ", "not_a_claim": "-- "}


def cmd(path) -> str:
    """A path as you'd type it from the current folder, so printed hints work wherever you ran this."""
    try:
        return os.path.relpath(pathlib.Path(path).resolve())
    except ValueError:        # another drive on Windows
        return str(pathlib.Path(path).resolve())


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("report", nargs="?", help="Markdown or text report (default: the practice brief)")
    p.add_argument("--challenge", default=str(DEFAULT_CHALLENGE))
    p.add_argument("--release", default=None)
    p.add_argument("--out", default=str(HERE / "outputs" / "audit.json"))
    p.add_argument("--envelope", nargs=5, metavar=("NUMBER", "W1", "W2", "W3", "W4"))
    a = p.parse_args(argv)

    t0 = time.time()
    challenge = pathlib.Path(a.challenge).resolve()
    report = pathlib.Path(a.report) if a.report else challenge / "products/research-claim-auditor/practice_brief.md"
    me = cmd(__file__)
    if a.envelope:
        num, *words = a.envelope
        print(f"Unsealing envelope {num} ...")
        if unseal(challenge, num, words).returncode:
            print("\nUnsealing failed: see the message above (wrong number or words, or release A needs fetch.py).",
                  file=sys.stderr)
            sys.exit(1)
        if not a.report:
            report = opened_dir(challenge, num) / "claim_auditor_report.md"
        if not report.exists():
            rel = cmd(opened_dir(challenge, num) / "release")
            print(f"\nEnvelope {num} opened, but it holds no claim_auditor_report.md, so there is nothing to audit."
                  + (" That is expected for the practice envelope: it only holds a new release." if num == "practice" else "")
                  + f"\nTo audit any report against the envelope's release:\n"
                  f"  python {me} <report.md> --release \"{rel}\"")
            sys.exit(0 if num == "practice" else 2)
    if not report.exists():
        print(f"Report not found: {report}", file=sys.stderr)
        sys.exit(2)

    release = Release(a.release or challenge / "data/tcga-brca/raw", challenge / "data/tcga-brca/slide_manifest.csv")
    audit = run_audit(report.read_text(encoding="utf-8"), release)

    out = pathlib.Path(a.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    write_json(audit, out.with_name(out.stem + "_full.json"))      # everything, for the review app
    write_json(to_shared_format(audit), out)                       # the file the organizers' checker reads

    print(f"\nReport: {report}\nRelease: {release.name} ({release.dir})\n")
    for it in audit["items"]:
        r = it["result"]
        print(f"[{ICON[it['tool_verdict']]}] {it['id']}  {LABEL[it['tool_verdict']].upper()}")
        print(f"      \"{it['claim_text'][:140]}\"")
        for sc in r["subchecks"]:
            if sc["ok"] is not None:
                print(f"      - {sc['label']}: claimed {sc['claimed']} | data {sc['observed']}")
        if r.get("correct_value"):
            print(f"      correct value: {r['correct_value']}")
        if r.get("needed"):
            print(f"      data needed: {r['needed'][:160]}")
        imp = it.get("impact") or {}
        if it["tool_verdict"] != "not_a_claim":
            print(f"      why it matters: {imp.get('why_it_matters', '')[:220]}")
            print(f"      next step:      {imp.get('next_step', '')[:220]}")
            if imp.get("suggested_text"):
                print(f"      suggested text: {imp['suggested_text'][:220]}")
        print()
    if a.envelope and (opened_dir(challenge, a.envelope[0]) / "release").exists():
        # Saturday's report may be about release A or the envelope's new release: check both, show what moves.
        env_rel = Release(opened_dir(challenge, a.envelope[0]) / "release", challenge / "data/tcga-brca/slide_manifest.csv",
                          name=f"envelope {a.envelope[0]}")
        env_audit = run_audit(report.read_text(encoding="utf-8"), env_rel)
        env_out = out.with_name(out.stem + "_envelope_release.json")
        write_json(to_shared_format(env_audit), env_out)
        moved = [(x, y) for x, y in zip(audit["items"], env_audit["items"]) if x["tool_verdict"] != y["tool_verdict"]]
        print(f"Also checked against the envelope's own release -> {env_out.name}")
        for x, y in moved:
            print(f"   {x['id']}: release A says {LABEL[x['tool_verdict']]}, envelope release says {LABEL[y['tool_verdict']]}"
                  f"  ({(y['result'].get('correct_value') or y['result']['summary'])[:120]})")
        if not moved:
            print("   Every verdict is the same on both releases.")
        print()
    plan = plan_for(audit)
    print(f"WHAT TO DO NEXT -> {plan['decision']}. {plan['why']}")
    for k, st in enumerate(plan["steps"], 1):
        print(f"  {k}. [{st['id']}] {st['do']}: {st['detail'][:200]}")
    print()
    print("WHAT THIS AUDIT CAN'T TELL YOU")
    for c in plan["cant_tell"]:
        print(f"  - {c[:200]}")
    corr = out.with_name("corrected_report.md")
    corr.write_text(corrected_markdown(plan, release.name), encoding="utf-8")
    print()
    print(f"Suggested corrected report -> {corr}")
    print(f"Every verdict needs a person to confirm it: open the review app (python {cmd(HERE / 'app.py')}).")
    print(f"\nWrote {out} (shared format) and {out.with_name(out.stem + '_full.json').name}  in {time.time() - t0:.1f} s")


if __name__ == "__main__":
    main()
