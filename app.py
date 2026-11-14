"""Claim Auditor review app. Standard library web server + pandas; no other installs.

  python app.py            then open http://localhost:8501
  python app.py --port 9000 --challenge ../oncosys-hackathon-challenge
"""
from __future__ import annotations

import argparse
import json
import os
import re
import pathlib
import subprocess
import sys
import threading
import time
import traceback
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from auditor.audit import final_verdict, plan_for, run_audit, suggested_decision, to_shared_format, write_json  # noqa: E402
from auditor.impact import corrected_markdown, explain  # noqa: E402
from auditor.plain import plain_markdown, plain_summary  # noqa: E402
from auditor.envelope import opened_dir, unseal  # noqa: E402
from auditor.adapt import fingerprint  # noqa: E402
from auditor.release import Release  # noqa: E402

CHALLENGE = HERE.parent / "oncosys-hackathon-challenge"
OUT = HERE / "outputs"
_releases: dict[str, Release] = {}
_lock = threading.Lock()


def get_release(path: str | None) -> Release:
    p = str(pathlib.Path(path).resolve()) if path else str((CHALLENGE / "data/tcga-brca/raw").resolve())
    key = (p, fingerprint(p) if pathlib.Path(p).is_dir() else "")   # re-opened envelope = new contents = new release
    with _lock:
        if key not in _releases:
            _releases[key] = Release(p, CHALLENGE / "data/tcga-brca/slide_manifest.csv")
        return _releases[key]


def opened_envelopes() -> list[dict]:
    root = CHALLENGE / "envelopes/opened"
    if not root.exists():
        return []
    return [{"name": d.name, "report": str(d / "claim_auditor_report.md")}
            for d in sorted(root.iterdir()) if (d / "claim_auditor_report.md").exists()]


JUNK_REASONS = {"idk", "i dont know", "i don't know", "dunno", "test", "testing", "n/a", "na", "none", "ok", "okay",
                "asdf", "xxx", "...", "-", "no reason", "because", "yes", "no", "fine", "good", "bad", "?"}


def reason_problem(reason: str, minimum_words: int = 4) -> str | None:
    """A reviewer's reason is part of the record: refuse placeholders like "idk"."""
    r = (reason or "").strip()
    if not r:
        return "a reason is required"
    if r.lower().strip(" .!") in JUNK_REASONS or len(re.findall(r"[A-Za-z]{2,}", r)) < minimum_words or len(r) < 15:
        return (f"the reason \"{r}\" doesn't explain the decision. Write at least {minimum_words} words saying what you "
                f"checked or why, e.g. \"One subtype share is wrong; the author must correct it before we use the report.\"")
    return None


def decision_markdown(audit: dict, decision: dict) -> str:
    plan = plan_for(audit)
    scope = audit.get("scope") or {}
    cl = [it for it in audit["items"] if it["tool_verdict"] != "not_a_claim" or it.get("review")]
    done = [it for it in cl if it.get("review")]
    lines = ["# Claim audit decision record", "",
             f"*Research use only. Not a clinical decision. No patient-level conclusions.*", "",
             *plain_markdown(plain_summary(audit["items"], plan, scope, final_verdict)),
             "## What was checked", "",
             f"- **Data:** {'release ' + audit['release']['name'] + ' (' + str(len(audit['release']['files'])) + ' files, checksums in audit.json)' if scope.get('compared_with_release', True) else 'NOT compared with any release. ' + scope.get('reason', '')}",
             f"- **Claims audited:** {len(cl)}" + (f" (the report's own labelled claims; {scope.get('context_sentences', 0)} other "
                                                   f"sentences were treated as context)" if scope.get('explicit_claims') else ""),
             f"- **Confirmed by a person:** {len(done)} of {len(cl)}"
             + ("" if len(done) == len(cl) else " (the rest are exported as needing human review)"), "",
             "## 1. The tool's suggestion (automated)", "",
             f"**{plan['decision']}.** {plan['why']}", "",
             "## 2. The reviewer's decision (human)", "",
             f"- **Decision:** {decision.get('decision')}"
             + ("" if decision.get("decision") == plan["decision"] else f" (differs from the tool's suggestion: {plan['decision']})"),
             f"- **Reason:** {decision.get('reason', '')}",
             f"- **Decided by:** {decision.get('reviewer', '')} ({decision.get('reviewer_role', '')}) at {decision.get('at', '')}",
             f"- **Must also be reviewed by:** {decision.get('also_review', '')}", "",
             "## Claims", "",
             "| Claim | Report's label | Tool verdict | Final verdict | Correct value | Reviewer |", "|---|---|---|---|---|---|"]
    for it in cl:
        rv = it.get("review") or {}
        fv = rv.get('verdict', it['tool_verdict'])
        cv = (rv.get('correct_value') or it['result'].get('correct_value') or '') if fv == 'contradicted' else ''
        who = (("overridden: " if rv.get("decision") == "override" else "confirmed")
               + (rv.get("reason") or "") if rv else "NOT REVIEWED")
        lines.append(f"| {it['claim_text'][:120].replace('|', '/')} | {it.get('label') or ''} | {it['tool_verdict']} | {fv} | "
                     f"{cv.replace('|', '/')} | {who.replace('|', '/')} |")
    lines += ["", "## What happens next (tool's plan)", ""]
    lines += [f"{k}. **{s['id']} · {s['do']}.** {s['detail']}" + (f"\n   Suggested text: _{s['suggested_text']}_"
                                                                 if s.get("suggested_text") else "")
              for k, s in enumerate(plan["steps"], 1)] or ["Nothing to fix."]
    lines += ["", "## What this audit can't tell you", "", *[f"- {c}" for c in plan["cant_tell"]]]
    lim = [f"- {it['id']}: {it['result']['limitation']}" for it in audit["items"] if it["result"].get("limitation")]
    lines += ["", "## Limitations per claim", *lim]
    return "\n".join(lines) + "\n"


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        pass

    def _send(self, code: int, body: bytes, ctype: str):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _json(self, obj, code=200):
        self._send(code, json.dumps(obj, default=str).encode(), "application/json")

    def do_GET(self):
        if self.path in ("/", "/index.html"):
            return self._send(200, (HERE / "web/index.html").read_bytes(), "text/html; charset=utf-8")
        if self.path == "/api/config":
            practice = CHALLENGE / "products/research-claim-auditor/practice_brief.md"
            return self._json({
                "release_dir": str((CHALLENGE / "data/tcga-brca/raw").resolve()),
                "practice_report": practice.read_text(encoding="utf-8") if practice.exists() else "",
                "envelopes": opened_envelopes(),
            })
        self._send(404, b"not found", "text/plain")

    def do_POST(self):
        try:
            n = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.rfile.read(n) or b"{}")
            if self.path == "/api/audit":
                t0 = time.time()
                rel = get_release(body.get("release_dir"))
                audit = run_audit(body.get("report_text", ""), rel, compare=True if body.get("compare") else None)
                p = plan_for(audit)
                audit["suggested"] = {"decision": p["decision"], "reason": p["why"]}
                audit["plain"] = plain_summary(audit["items"], p, audit.get("scope"), final_verdict)
                audit["seconds"] = round(time.time() - t0, 2)
                return self._json(audit)
            if self.path == "/api/plan":     # recomputed after every review, so it follows the reviewer's verdicts
                a = body["audit"]
                plan = plan_for(a)
                plan["corrected_markdown"] = corrected_markdown(plan, a["release"]["name"])
                plan["impacts"] = {it["id"]: explain(it, final_verdict(it), a["release"]["name"], a.get("scope"))
                                   for it in a["items"]}
                plan["plain"] = plain_summary(a["items"], plan, a.get("scope"), final_verdict, plan["impacts"])
                return self._json(plan)
            if self.path == "/api/export":
                audit, decision = body["audit"], body.get("decision") or {}
                team = body.get("team") or "Cache us if u can"
                problem = reason_problem(decision.get("reason", "")) if decision.get("decision") else None
                bad_overrides = [it["id"] for it in audit["items"] if (it.get("review") or {}).get("decision") == "override"
                                 and reason_problem(it["review"].get("reason", ""), 3)]
                if problem or bad_overrides:
                    return self._json({"error": f"Not exported: {problem}" if problem else
                                       f"Not exported: the override reason on {', '.join(bad_overrides)} is too short to "
                                       f"explain the change."}, 400)
                OUT.mkdir(exist_ok=True)
                shared = to_shared_format(audit, decision if decision.get("decision") else None, team=team)
                write_json(shared, OUT / "audit.json")
                write_json({**audit, "decision": decision}, OUT / "audit_full.json")
                (OUT / "decision_summary.md").write_text(decision_markdown(audit, decision), encoding="utf-8")
                (OUT / "corrected_report.md").write_text(corrected_markdown(plan_for(audit), audit["release"]["name"]),
                                                         encoding="utf-8")
                check = subprocess.run([sys.executable, str(CHALLENGE / "format/validate.py"), str(OUT / "audit.json")],
                                       capture_output=True, text=True)
                return self._json({"paths": [str(OUT / x) for x in ("audit.json", "audit_full.json", "decision_summary.md",
                                                                    "corrected_report.md")],
                                   "validator": (check.stdout + check.stderr).strip(), "shared": shared})
            if self.path == "/api/unseal":
                num, words = str(body.get("number", "")).strip(), str(body.get("words", "")).split()
                r = unseal(CHALLENGE, num, words, capture=True)
                try:
                    rep = opened_dir(CHALLENGE, num) / "claim_auditor_report.md"
                except ValueError:
                    return self._json({"ok": False, "log": "Envelope number must be digits or 'practice'.", "report_text": ""})
                return self._json({"ok": r.returncode == 0 and rep.exists(), "log": (r.stdout + r.stderr)[-2000:],
                                   "report_text": rep.read_text(encoding="utf-8") if rep.exists() else "",
                                   "report_path": str(rep)})
            self._json({"error": "unknown endpoint"}, 404)
        except Exception as e:
            traceback.print_exc()
            self._json({"error": f"{type(e).__name__}: {e}"}, 500)


def _rel(path) -> str:
    """A path as you'd type it from the current folder (so printed hints work wherever you ran this)."""
    try:
        return os.path.relpath(pathlib.Path(path).resolve())
    except ValueError:        # another drive on Windows
        return str(pathlib.Path(path).resolve())


def main():
    global CHALLENGE
    p = argparse.ArgumentParser()
    p.add_argument("--port", type=int, default=8501)
    p.add_argument("--challenge", default=str(CHALLENGE))
    p.add_argument("--no-browser", action="store_true")
    a = p.parse_args()
    CHALLENGE = pathlib.Path(a.challenge).resolve()

    class Server(ThreadingHTTPServer):
        # On Windows, SO_REUSEADDR lets a second server bind a busy port silently; refuse instead.
        allow_reuse_address = os.name != "nt"

    try:
        srv = Server(("127.0.0.1", a.port), Handler)
    except OSError as e:
        sys.exit(f"Port {a.port} is already in use ({e.strerror or e}).\n"
                 f"Is the app already running? Then just open http://localhost:{a.port}\n"
                 f"Or start it on another port:  python {_rel(__file__)} --port {a.port + 1}")
    url = f"http://localhost:{a.port}"
    print(f"Claim Auditor running at {url}  (Ctrl+C to stop)")
    threading.Thread(target=get_release, args=(None,), daemon=True).start()   # warm the cache
    if not a.no_browser:
        threading.Timer(0.8, lambda: webbrowser.open(url)).start()
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
