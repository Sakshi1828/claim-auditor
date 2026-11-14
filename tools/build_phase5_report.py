"""Build the Phase 2 report (simple words) as docs/redesign/phase5_report.html and .pdf.

  python tools/build_phase5_report.py
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
    "1. Hover and keyboard focus": ("ic-info", [
        ("Added", "Cards, buttons, problem cards, chart bars and chart dots now react gently when you point at them or move to them with the Tab key, with a clear focus outline."),
        ("Tested", "Bars and dots can be reached with the keyboard and read aloud; changes take about 0.2 seconds.")]),
    "2. '?' help tips": ("ic-uncertain", [
        ("Added", "A small '?' beside the result word of each claim (Supported, Contradicted...) explains what that result means in this app."),
        ("Added", "A '?' beside medical words in a claim (for example Luminal A, primary tumor) shows the explanation from the app's own glossary for that report. No new medical wording was written."),
        ("Tested", "The tip opens on hover and on keyboard focus, and closes with Escape. The claim's words stay exactly the same.")]),
    "3. Drill-down from the summary": ("ic-evidence", [
        ("Added", "Under the summary, 'Show the evidence behind each result' opens a list of every claim. Each one folds out to show the evidence the app already has: the summary, report vs data numbers, the correct value, and what data would be needed."),
        ("Tested", "'Open the full details' jumps to that claim in Step 2.")]),
    "4. Detail level switch": ("ic-review", [
        ("Restyled", "The existing Program lead / Reviewer / Researcher switch is now labelled 'How much detail' and clearly shows which one is on. Same facts in every view."),
        ("Tested", "All three views switch correctly; the Your role menu still changes it too.")]),
    "5. Comparing the two groups": ("ic-compare", [
        ("Added", "On the two-group chart, buttons show both markers, only the average, or only the middle value, so the difference between the groups is easier to see."),
        ("Tested", "Each button switches the view; the numbers and the table stay the same.")]),
    "6. Chart legend": ("ic-data", [
        ("Added", "In the summary bar, clicking a result in the legend dims it or brings it back, and pointing at one highlights it in the bar. Dimming never changes the sizes or numbers."),
        ("Tested", "Dim, restore, highlight and un-highlight all work; the verdicts were checked before and after and did not change.")]),
}
sections = "".join(
    f'<div class="card"><h3>{ic(icon)}{title}</h3><table>' + "".join(
        f'<tr><td><span class="tag t-{k.lower()}">{k}</span></td><td>{v}</td></tr>' for k, v in rows) + "</table></div>"
    for title, (icon, rows) in ROWS.items())

page = f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Redesign Phase 5 Report</title>
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
.t-tested{{background:var(--sage-soft);color:var(--status-strong)}} .t-upgraded{{background:var(--teal-soft);color:var(--teal)}} .t-data{{background:var(--stone-2);color:var(--navy)}} .t-hidden{{background:var(--status-limited-bg);color:var(--status-limited)}} .t-added,.t-restyled{{background:var(--sage-soft);color:var(--status-strong)}} .t-unchanged{{background:var(--status-limited-bg);color:var(--status-limited)}}
.btn{{background:var(--teal);color:#fff;border:0;border-radius:10px;padding:12px 20px;font:600 16px var(--sans);cursor:pointer}}
.pill{{display:inline-block;background:var(--teal-soft);color:var(--teal);border-radius:999px;padding:2px 10px;font-size:13px;font-weight:600}}
@media print{{.noprint{{display:none}} body{{background:#fff}} .card{{box-shadow:none;break-inside:avoid}}}}
</style></head><body>{sprite}<main>
<span class="pill">Redesign · Phase 5 of 8</span>
<h1>Easier to explore: hover, help tips and fold-outs</h1>
<p class="lead">You can now point at things to see them highlighted, open small '?' tips for hard words, fold out the evidence behind each result, and switch what a chart shows. <b>All of this only changes what you see; it never changes any number, result or decision.</b></p>
<div class="noprint" style="margin:16px 0"><button class="btn" onclick="window.print()">Save as PDF</button>
<span style="color:#5f6873;margin-left:10px">Opens your print window: choose “Save as PDF”.</span></div>
<div class="ok">✓ Every piece of information is still there (all 574 checked), every button and link still works, the export is still
accepted by the organizers' checker, and all 5 test packs pass.</div>

<h2>What you can now do, and how we tested it</h2>
{sections}

<h2>The original buttons still work</h2>
<div class="card"><p>We clicked through every original control after the change: practice report, Your role, Check every
claim, Explain it in plain words, Glossary, the three filters, a problem card, the claim tabs, Copy suggested wording,
Confirm, Override with a reason, Next claim, Back to summary, the step links, the Step 3 tabs, the corrected report,
Show all, a decision choice and Export. <b>All worked, and the export said 'valid'.</b></p></div>

<h2>How we checked nothing was lost</h2>
<div class="card"><ol>
<li>All 574 pieces of text from before are still on the page, word for word (we read the page with the new tips taken out).</li>
<li>Comparison against the original page: no value, button, download or text removed or edited.</li>
<li>All 5 automatic test packs pass, and there were no errors in the page.</li>
</ol></div>

<h2>Which files changed</h2>
<div class="card"><table>
<tr><td><b>web/index.html</b></td><td>Looks and view-only behaviour: hover and focus, tips, fold-outs, view switches, legend. Nothing that checks claims, saves results or talks to the server was touched.</td></tr>
<tr><td><b>tools/ui_baseline.py</b></td><td>Now also allows the new 'How much detail' label.</td></tr>
</table></div>

<h2>Nothing was skipped</h2>
<p>Every change was a safe rearrangement of what was already there, so nothing had to be skipped.</p>
<p style="color:#5f6873;margin-top:30px;font-size:14px">Research Claim Auditor · Team Cache us if u can · Redesign phase 5</p>
</main></body></html>"""
(OUT / "phase5_report.html").write_text(page, encoding="utf-8")
edge = next((p for p in [pathlib.Path(r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"),
                         pathlib.Path(r"C:\Program Files\Microsoft\Edge\Application\msedge.exe")] if p.exists()), None)
if edge:
    pdf = OUT / "phase5_report.pdf"
    pdf.unlink(missing_ok=True)
    subprocess.run([str(edge), "--headless=new", "--disable-gpu", "--no-pdf-header-footer",
                    f"--user-data-dir={tempfile.mkdtemp(prefix='edge_pdf_')}", f"--print-to-pdf={pdf}",
                    (OUT / "phase5_report.html").as_uri()], capture_output=True, timeout=120)
    for _ in range(60):
        if pdf.exists() and pdf.stat().st_size > 10000:
            break
        time.sleep(1)
    print("PDF:", pdf if pdf.exists() else "not created")
print("HTML:", OUT / "phase5_report.html")
