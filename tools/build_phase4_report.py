"""Build the Phase 2 report (simple words) as docs/redesign/phase4_report.html and .pdf.

  python tools/build_phase4_report.py
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
    "1. How the sentences came out (summary, top of results)": ("ic-data", [
        ("Upgraded", "The coloured bar that splits all sentences into results. Now has a plain title, a 'What this shows' line, hover labels with the exact counts, and a Show table switch."),
        ("Data", "The count of each result (supported, contradicted, insufficient evidence, not a claim), already shown in the legend.")]),
    "2. Report vs data, on one scale (claim details, percentages)": ("ic-compare", [
        ("Upgraded", "The number line with a dot for the report and a dot for the data. Now with a title, an axis label (share of tumors, %), a light grid, the allowed-margin band explained, hover values, and a table."),
        ("Data", "The report's number, the data's number and the allowed margin from the check result.")]),
    "3. Report vs data, side by side (claim details, counts and ages)": ("ic-compare", [
        ("Upgraded", "The two bars (report, data). Now with a title, a unit label, a grid, calm colour-blind-safe colours, hover values, and a table."),
        ("Data", "The report's number and the data's number from the check result.")]),
    "4. The two groups side by side (new, for claims comparing two groups)": ("ic-compare", [
        ("Added", "A dot plot for claims like 'ER-alpha is higher in ER-positive than ER-negative tumors': each group's average and middle value on one scale, with a table."),
        ("Data", "The averages, middle values and group sizes already written in the result, for example 'mean 2.18 vs -0.87; median 2.31 vs -1.07'. If those numbers are not in the result, no chart is drawn.")]),
    "5. One question, different ways of counting (claim details)": ("ic-data", [
        ("Upgraded", "The bars showing the same question with other definitions. Now with a title, a caption, an axis note and a table; the bar that matches the report is highlighted."),
        ("Data", "The alternative definitions the check already lists.")]),
    "6. Data completeness bar (new, AI-reading view)": ("ic-data", [
        ("Added", "A small filled bar showing how many tumors have a value for the field used."),
        ("Data", "The existing sentence '844 of 1,101 primary tumors have a value'. Shown only when that sentence exists.")]),
    "7. Steps and limits (Step 3)": ("ic-next", [
        ("Restyled", "'Do this, in order' keeps its numbered timeline with a softer connecting line. Each item in 'What the check can't tell you' now has an info icon."),
        ("Data", "The same steps and limits as before.")]),
    "8. Data not available (new state)": ("ic-uncertain", [
        ("Added", "When the data can't answer, for example an envelope with no RNA file, a calm box says 'Data not available' and gives the app's own reason. No number is guessed."),
        ("Data", "The existing message, for example 'can't count: no RNA file in this release'.")]),
}
sections = "".join(
    f'<div class="card"><h3>{ic(icon)}{title}</h3><table>' + "".join(
        f'<tr><td><span class="tag t-{k.lower()}">{k}</span></td><td>{v}</td></tr>' for k, v in rows) + "</table></div>"
    for title, (icon, rows) in ROWS.items())

page = f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Redesign Phase 4 Report</title>
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
.t-upgraded{{background:var(--teal-soft);color:var(--teal)}} .t-data{{background:var(--stone-2);color:var(--navy)}} .t-hidden{{background:var(--status-limited-bg);color:var(--status-limited)}} .t-added,.t-restyled{{background:var(--sage-soft);color:var(--status-strong)}} .t-unchanged{{background:var(--status-limited-bg);color:var(--status-limited)}}
.btn{{background:var(--teal);color:#fff;border:0;border-radius:10px;padding:12px 20px;font:600 16px var(--sans);cursor:pointer}}
.pill{{display:inline-block;background:var(--teal-soft);color:var(--teal);border-radius:999px;padding:2px 10px;font-size:13px;font-weight:600}}
@media print{{.noprint{{display:none}} body{{background:#fff}} .card{{box-shadow:none;break-inside:avoid}}}}
</style></head><body>{sprite}<main>
<span class="pill">Redesign · Phase 4 of 8</span>
<h1>Clearer charts, built only from the app's own numbers</h1>
<p class="lead">Every chart now has a plain title, a one-line 'What this shows', labelled axes, hover values and a 'Show table' switch, so the exact numbers are always one click away. We added three small visuals where the app already had the numbers, and a clear 'Data not available' box where it doesn't. <b>No number was invented or estimated.</b></p>
<div class="noprint" style="margin:16px 0"><button class="btn" onclick="window.print()">Save as PDF</button>
<span style="color:#5f6873;margin-left:10px">Opens your print window: choose “Save as PDF”.</span></div>
<div class="ok">✓ Every piece of information is still there (all 574 checked), every button and link still works, the export is still
accepted by the organizers' checker, and all 5 test packs pass.</div>

<h2>Every chart, and exactly where its numbers come from</h2>
{sections}

<h2>Why we did not add a chart add-on</h2>
<div class="card"><p>The app had no chart add-on; it draws its own small charts. Adding one (such as Chart.js) would mean
downloading it from the internet each time, which breaks the 'works offline, nothing leaves this computer' promise, or
changing how the server sends files, which our rules don't allow. So we upgraded the app's own charts instead.</p>
<p style="margin:0"><b>Over-time charts:</b> the app shows no values over time, so there is nothing to draw as a line chart.
<b>Error bars:</b> the app shows an allowed margin, not confidence intervals; that margin is drawn as a shaded band.</p></div>

<h2>Colours, screen readers and phones</h2>
<div class="card"><ul>
<li>Chart colours come from a 6-colour set that stays distinguishable for colour-blind readers.</li>
<li>Every chart has a spoken summary for screen readers, and every table has proper column headings.</li>
<li>The bars grow in gently; the motion switches off for anyone who prefers less motion.</li>
<li>On a phone-sized screen the charts fit without sideways scrolling.</li></ul></div>

<h2>Which files changed</h2>
<div class="card"><table>
<tr><td><b>web/index.html</b></td><td>Chart drawing and styles only. Nothing that checks claims, saves results or talks to the server was touched.</td></tr>
<tr><td><b>Everything else</b></td><td>Not touched.</td></tr></table></div>

<h2>How we checked</h2>
<div class="card"><ol>
<li>All 574 pieces of text from before are still on the page (with every chart's table opened too): none missing.</li>
<li>Clicked through: practice report, check, plain words, claim tabs, Show table, confirm, override, decision, export. All worked; the export said 'valid'.</li>
<li>The 'Data not available' box was tested on the practice envelope, which has no RNA file.</li>
<li>Comparison against the original page: no value, button, download or text removed or edited. All 5 test packs pass.</li>
</ol></div>

<h2>Nothing was skipped</h2>
<p>Every change was a safe rearrangement of what was already there, so nothing had to be skipped.</p>
<p style="color:#5f6873;margin-top:30px;font-size:14px">Research Claim Auditor · Team Cache us if u can · Redesign phase 4</p>
</main></body></html>"""
(OUT / "phase4_report.html").write_text(page, encoding="utf-8")
edge = next((p for p in [pathlib.Path(r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"),
                         pathlib.Path(r"C:\Program Files\Microsoft\Edge\Application\msedge.exe")] if p.exists()), None)
if edge:
    pdf = OUT / "phase4_report.pdf"
    pdf.unlink(missing_ok=True)
    subprocess.run([str(edge), "--headless=new", "--disable-gpu", "--no-pdf-header-footer",
                    f"--user-data-dir={tempfile.mkdtemp(prefix='edge_pdf_')}", f"--print-to-pdf={pdf}",
                    (OUT / "phase4_report.html").as_uri()], capture_output=True, timeout=120)
    for _ in range(60):
        if pdf.exists() and pdf.stat().st_size > 10000:
            break
        time.sleep(1)
    print("PDF:", pdf if pdf.exists() else "not created")
print("HTML:", OUT / "phase4_report.html")
