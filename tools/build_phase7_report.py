"""Build the Phase 2 report (simple words) as docs/redesign/phase7_report.html and .pdf.

  python tools/build_phase7_report.py
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
    "Step 1. What links already existed (checked before building)": ("ic-evidence", [
        ("Found", "For every sentence, the checker already records which data files it used, which fields in them, and its reason. For reports that label their claims, it also records the evidence the report itself cites."),
        ("Found", "Practice report: 3 of 6 sentences linked to data files. Demo report: 13 of 18. Labelled synthetic report: 8 of 8 linked to the report's own cited evidence."),
        ("Not linked", "Opinions, recommendations, background lines and claims the tool could not measure have no source. They now say 'No source linked for this statement.'"),
        ("Not done", "No links were made up or found by matching words. Only the links above are used.")]),
    "Step 2. Read the report with its sources (Step 2 of the app)": ("ic-review", [
        ("Added", "A fold-out 'Read the report with its sources' shows every checked sentence, word for word. Clicking a sentence, or pressing Enter on it, opens a side panel titled 'Why this is said' (a bottom sheet on phones)."),
        ("Added", "The panel shows the sentence, its result and status, the number of sources, the checker's reason, the report's cited evidence if any, the data files and fields used, and a button to open the full source and calculation."),
        ("Unchanged", "The existing list of sentences on the left still works exactly as before: clicking one opens its details.")]),
    "Groups and highlighting": ("ic-compare", [
        ("Added", "Sentences that rest on the same data files form a group. With 'Show highlights' on, each group gets a soft colour and a small number, so colour is never the only clue. A legend lists the groups."),
        ("Added", "Clicking a sentence highlights its whole group and dims the rest. Highlights are off by default, so the normal view stays clean.")]),
    "Reverse: from a source to its sentences": ("ic-data", [
        ("Added", "Clicking a group in the legend, or a data file in the panel, highlights every sentence that file supports.")]),
    "Keyboard and screen readers": ("ic-info", [
        ("Added", "Every sentence can be reached with Tab; Enter opens the panel; Escape closes it and returns you to the sentence. Each sentence and the panel have spoken labels.")]),
}
sections = "".join(
    f'<div class="card"><h3>{ic(icon)}{title}</h3><table>' + "".join(
        f'<tr><td><span class="tag t-{k.lower()}">{k}</span></td><td>{v}</td></tr>' for k, v in rows) + "</table></div>"
    for title, (icon, rows) in ROWS.items())

page = f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Redesign Phase 7 Report</title>
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
.t-found{{background:var(--sage-soft);color:var(--status-strong)}} .t-not{{background:var(--status-limited-bg);color:var(--status-limited)}} .t-surfaced{{background:var(--teal-soft);color:var(--teal)}} .t-not shown{{background:var(--status-limited-bg);color:var(--status-limited)}} .t-tested{{background:var(--sage-soft);color:var(--status-strong)}} .t-upgraded{{background:var(--teal-soft);color:var(--teal)}} .t-data{{background:var(--stone-2);color:var(--navy)}} .t-hidden{{background:var(--status-limited-bg);color:var(--status-limited)}} .t-added,.t-restyled{{background:var(--sage-soft);color:var(--status-strong)}} .t-unchanged{{background:var(--status-limited-bg);color:var(--status-limited)}}
.btn{{background:var(--teal);color:#fff;border:0;border-radius:10px;padding:12px 20px;font:600 16px var(--sans);cursor:pointer}}
.pill{{display:inline-block;background:var(--teal-soft);color:var(--teal);border-radius:999px;padding:2px 10px;font-size:13px;font-weight:600}}
@media print{{.noprint{{display:none}} body{{background:#fff}} .card{{box-shadow:none;break-inside:avoid}}}}
</style></head><body>{sprite}<main>
<span class="pill">Redesign · Phase 7 of 8</span>
<h1>Why is each sentence said? Click it to see</h1>
<p class="lead">Every checked sentence can now be clicked to see exactly why it is said: the data it was checked against and the checker's reason. <b>Only links the app already had are shown; nothing was guessed, and every sentence keeps its exact words.</b></p>
<div class="noprint" style="margin:16px 0"><button class="btn" onclick="window.print()">Save as PDF</button>
<span style="color:#5f6873;margin-left:10px">Opens your print window: choose “Save as PDF”.</span></div>
<div class="ok">✓ Every piece of information is still there (all 574 checked), every button and link still works, the export is still
accepted by the organizers' checker, and all 5 test packs pass.</div>

<h2>What we found, and what we built</h2>
{sections}

<h2>How we tested it</h2>
<div class="card"><ol>
<li>Every sentence in the new view has exactly the same words as the report (checked one by one).</li>
<li>Clicking a sentence opens 'Why this is said' with its real sources; a sentence with no source says 'No source linked for this statement.'</li>
<li>Group highlight, dimming of the other sentences, the legend, and clicking a data file to highlight every sentence it supports all worked.</li>
<li>'Show highlights' is off at first and switches on and off.</li>
<li>With real key presses: Escape closes the panel and returns to the sentence; Enter opens it again.</li>
<li>On a phone-sized screen the panel opens as a full-width bottom sheet, with nothing spilling off the side.</li>
<li>The original sentence list, the review buttons and Export still work (export said 'valid'); the results never changed.</li>
<li>All 574 pieces of text from before are still on the page; the comparison against the original page found nothing removed or edited; all 5 test packs pass.</li>
</ol></div>

<h2>Which files changed</h2>
<div class="card"><table>
<tr><td><b>web/index.html</b></td><td>The new view, the panel and their styles. Nothing that checks claims, saves results or talks to the server was touched.</td></tr>
<tr><td><b>tools/ui_baseline.py</b></td><td>Now also allows the new view's boxes and the highlight switch.</td></tr>
</table></div>

<h2>Nothing was skipped</h2>
<p>Every change was a safe rearrangement of what was already there, so nothing had to be skipped.</p>
<p style="color:#5f6873;margin-top:30px;font-size:14px">Research Claim Auditor · Team Cache us if u can · Redesign phase 7</p>
</main></body></html>"""
(OUT / "phase7_report.html").write_text(page, encoding="utf-8")
edge = next((p for p in [pathlib.Path(r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"),
                         pathlib.Path(r"C:\Program Files\Microsoft\Edge\Application\msedge.exe")] if p.exists()), None)
if edge:
    pdf = OUT / "phase7_report.pdf"
    pdf.unlink(missing_ok=True)
    subprocess.run([str(edge), "--headless=new", "--disable-gpu", "--no-pdf-header-footer",
                    f"--user-data-dir={tempfile.mkdtemp(prefix='edge_pdf_')}", f"--print-to-pdf={pdf}",
                    (OUT / "phase7_report.html").as_uri()], capture_output=True, timeout=120)
    for _ in range(60):
        if pdf.exists() and pdf.stat().st_size > 10000:
            break
        time.sleep(1)
    print("PDF:", pdf if pdf.exists() else "not created")
print("HTML:", OUT / "phase7_report.html")
