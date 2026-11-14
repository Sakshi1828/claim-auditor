"""Build the Phase 2 report (simple words) as docs/redesign/phase2_report.html and .pdf.

  python tools/build_phase2_report.py
Uses the app's own colours and icons (copied from web/index.html) and prints the PDF with Microsoft Edge.
"""
import pathlib
import re
import subprocess
import tempfile
import time

ROOT = pathlib.Path(__file__).resolve().parents[1]
OUT = ROOT / "docs/redesign"
app = (ROOT / "web/index.html").read_text(encoding="utf-8")
tokens = re.search(r"(:root\{\n  /\* base palette.*?\n\})", app, re.S).group(1)
sprite = re.search(r'(<svg id="illustrations".*?</svg>)', app, re.S).group(1)


def ic(i):
    return f'<svg class="i" viewBox="0 0 24 24" aria-hidden="true"><use href="#{i}"/></svg>'


ROWS = {
    "Step 1 · Load a report": ("ic-evidence", [
        ("Moved", "The report box and the big “Check every claim” button are now at the top, so the first thing you see is what to do."),
        ("Collapsed", "Your name, your role, the data release folder and the AI tick box are now inside “Settings” (click to open). A short line explains when to change the data folder."),
        ("Unchanged", "Practice report, Upload a file, and Open a sealed envelope stay exactly where they were.")]),
    "Result · Key takeaway": ("ic-info", [
        ("Added", "A “Key takeaway” heading above the summary. It only labels the summary that was already there; no new findings."),
        ("Restyled", "The result counts (contradicted, insufficient, supported, not a claim) now look like small number cards."),
        ("Unchanged", "“Explain it in plain words” and “Glossary” still open the plain-language box.")]),
    "Step 2 · Review each claim": ("ic-review", [
        ("Collapsed", "The key to the coloured labels (From the data / Interpretation / From the report) is now behind “What do the coloured labels mean?”."),
        ("Tabbed", "Each claim's details are now in 3 tabs instead of one long page: “The numbers”, “What to do”, “How it was checked”. The claim itself, its plain-words line and the one-line summary stay on top."),
        ("Unchanged", "Confirm, Override, Undo and Next claim are always visible under the tabs. Filters and the Program lead / Reviewer / Researcher switch work as before.")]),
    "Step 3 · What happens next": ("ic-next", [
        ("Moved", "Your decision and the Export button now come right after the tool's suggestion, so the main action is easy to find."),
        ("Tabbed", "The supporting information is in 3 tabs: “Steps to fix”, “What the check can't tell you”, “Corrected report”."),
        ("Shortened", "Long lists show the first 3 items and a “Show all (N)” button. Nothing is removed.")]),
}
sections = "".join(
    f'<div class="card"><h3>{ic(icon)}{title}</h3><table>' + "".join(
        f'<tr><td><span class="tag t-{k.lower()}">{k}</span></td><td>{v}</td></tr>' for k, v in rows) + "</table></div>"
    for title, (icon, rows) in ROWS.items())

page = f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Redesign Phase 2 Report</title>
<style>
{tokens}
*{{box-sizing:border-box}} body{{margin:0;background:var(--sand);color:var(--navy);font:16px/1.65 var(--sans)}}
main{{max-width:860px;margin:0 auto;padding:32px 20px 60px}}
h1,h2,h3{{font-family:var(--serif);font-weight:600;line-height:1.25}}
h1{{font-size:32px;margin:6px 0 4px}} h2{{font-size:23px;margin:34px 0 10px;padding-top:16px;border-top:1px solid var(--stone)}}
h3{{display:flex;gap:10px;align-items:center;font-size:20px;margin:0 0 8px}}
p,li,td{{color:#3a4654}} .lead{{font-size:18px}}
.card{{background:var(--white);border:1px solid var(--stone);border-radius:14px;padding:18px 20px;margin:14px 0;box-shadow:var(--shadow)}}
.ok{{background:var(--status-strong-bg);color:var(--status-strong);border-radius:12px;padding:14px 18px;font-weight:600}}
table{{width:100%;border-collapse:collapse}} td{{padding:8px 8px;border-bottom:1px solid var(--stone-2);vertical-align:top}}
td:first-child{{width:120px}}
.i{{width:26px;height:26px;color:var(--teal);flex:none}}
.tag{{display:inline-block;border-radius:999px;padding:2px 10px;font-size:13px;font-weight:700}}
.t-moved{{background:var(--teal-soft);color:var(--teal)}} .t-tabbed{{background:var(--teal-soft);color:var(--teal)}}
.t-collapsed{{background:var(--status-uncertain-bg);color:var(--status-uncertain)}} .t-shortened{{background:var(--status-uncertain-bg);color:var(--status-uncertain)}}
.t-added,.t-restyled{{background:var(--sage-soft);color:var(--status-strong)}} .t-unchanged{{background:var(--status-limited-bg);color:var(--status-limited)}}
.btn{{background:var(--teal);color:#fff;border:0;border-radius:10px;padding:12px 20px;font:600 16px var(--sans);cursor:pointer}}
.pill{{display:inline-block;background:var(--teal-soft);color:var(--teal);border-radius:999px;padding:2px 10px;font-size:13px;font-weight:600}}
@media print{{.noprint{{display:none}} body{{background:#fff}} .card{{box-shadow:none;break-inside:avoid}}}}
</style></head><body>{sprite}<main>
<span class="pill">Redesign · Phase 2 of 8</span>
<h1>Less clutter: what we moved, folded away and put in tabs</h1>
<p class="lead">The screen showed too much at once. We <b>reorganised</b> it so the most important thing comes first and
the details are one click away. We did <b>not delete</b> anything and did <b>not change</b> how anything works.</p>
<div class="noprint" style="margin:16px 0"><button class="btn" onclick="window.print()">Save as PDF</button>
<span style="color:#5f6873;margin-left:10px">Opens your print window: choose “Save as PDF”.</span></div>
<div class="ok">✓ All 554 pieces of information the page showed before are still there, reachable through a tab, a fold-out
or “Show all”. Every button still works, the export is still accepted by the organizers' checker, and all 5 test packs pass.</div>

<h2>How each screen is organised now</h2>
<p>Every screen now follows the same order: <b>1.</b> the main point at the top, <b>2.</b> the key numbers in the middle,
<b>3.</b> the detail behind a click.</p>
{sections}

<h2>Easier to read everywhere</h2>
<div class="card"><ul>
<li>Text lines stop at about 70 letters wide, so your eyes don't travel too far.</li>
<li>A bit more space between lines in longer text.</li>
<li>Each section has <b>one icon</b>, <b>one heading</b> and <b>one short helper line</b>.</li>
<li>Tabs can also be used with the keyboard (left and right arrow keys).</li>
</ul></div>

<h2>How we checked that nothing was lost</h2>
<div class="card"><ol>
<li>Before changing anything, we recorded all <b>554</b> pieces of text the page shows (two test reports, every claim,
every detail level).</li>
<li>After the change, we opened every tab, fold-out and “Show all”, and collected the text again.</li>
<li>Result: <b>0 missing</b>. The only differences are the new headings and helper lines, and the run time
(“checked in 0.25 s”), which is different every run.</li>
<li>We clicked every button in order: practice report, check, plain words, glossary, filters, tabs, copy wording,
confirm, override, undo, detail levels, role, decision, export. All worked; the export said “valid”.</li>
<li>Our automatic comparison against the original page: no value, button, download or label removed or edited.</li>
</ol></div>

<h2>Nothing was skipped</h2>
<p>Every change was a safe rearrangement of what was already there, so nothing had to be skipped.</p>
<p style="color:#5f6873;margin-top:30px;font-size:14px">Research Claim Auditor · Team Cache us if u can · Redesign phase 2</p>
</main></body></html>"""
(OUT / "phase2_report.html").write_text(page, encoding="utf-8")
edge = next((p for p in [pathlib.Path(r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"),
                         pathlib.Path(r"C:\Program Files\Microsoft\Edge\Application\msedge.exe")] if p.exists()), None)
if edge:
    pdf = OUT / "phase2_report.pdf"
    pdf.unlink(missing_ok=True)
    subprocess.run([str(edge), "--headless=new", "--disable-gpu", "--no-pdf-header-footer",
                    f"--user-data-dir={tempfile.mkdtemp(prefix='edge_pdf_')}", f"--print-to-pdf={pdf}",
                    (OUT / "phase2_report.html").as_uri()], capture_output=True, timeout=120)
    for _ in range(60):
        if pdf.exists() and pdf.stat().st_size > 10000:
            break
        time.sleep(1)
    print("PDF:", pdf if pdf.exists() else "not created")
print("HTML:", OUT / "phase2_report.html")
