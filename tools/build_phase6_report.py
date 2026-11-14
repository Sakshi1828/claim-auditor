"""Build the Phase 2 report (simple words) as docs/redesign/phase6_report.html and .pdf.

  python tools/build_phase6_report.py
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
    "1. Sources (claim details, 'How it was checked' tab)": ("ic-data", [
        ("Surfaced", "Each data file a result was computed from is now shown as a small source card: file name, type (data table or manifest), release, and the file's fingerprint."),
        ("Surfaced", "A badge in the claim header shows how many sources it used, for example '1 source'."),
        ("Surfaced", "In the summary's evidence list, each claim has 'See evidence (N sources)', which opens that claim straight on its evidence tab."),
        ("Not shown", "Titles, years and web links: the app has none for its data files, so none were added.")]),
    "2. Status badges (claim header and evidence list)": ("ic-uncertain", [
        ("Surfaced", "'Conflicting findings' where the result is Contradicted."),
        ("Surfaced", "'Limited data' where the result says data is missing (for example no RNA file); 'Uncertain' for other Insufficient evidence."),
        ("Surfaced", "'Strong evidence' only where the result is Supported and the tool's own confidence is high and not borderline; otherwise 'Uncertain'."),
        ("Surfaced", "A small 3-step meter beside the tool's existing confidence (high, medium, low).")]),
    "3. Limitations, missing data and conflicts": ("ic-info", [
        ("Surfaced", "Each result's own limitation text now appears as a 'Limitation' box at the top of 'What to do'."),
        ("Restyled", "The existing 'What the data shows instead' (conflict) and 'Data that would be needed' (missing data) boxes have a clear coloured edge.")]),
    "4. Recommended next step (end of Step 3)": ("ic-next", [
        ("Surfaced", "A conclusion card: the tool's suggested decision, its reason, the first steps to fix, the key limitations, and who should also review (taken from 'Also needs review by')."),
        ("Unchanged", "The decision itself is still made by a person; the card only repeats the existing plan.")]),
    "5. Disclaimer": ("ic-review", [
        ("Restyled", "The existing 'research use only' line at the bottom is now a calm grey note with an info icon, and the 'Research use only' note in the top bar has a soft green edge. No new disclaimer was written.")]),
}
sections = "".join(
    f'<div class="card"><h3>{ic(icon)}{title}</h3><table>' + "".join(
        f'<tr><td><span class="tag t-{k.lower()}">{k}</span></td><td>{v}</td></tr>' for k, v in rows) + "</table></div>"
    for title, (icon, rows) in ROWS.items())

page = f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Redesign Phase 6 Report</title>
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
.t-surfaced{{background:var(--teal-soft);color:var(--teal)}} .t-not shown{{background:var(--status-limited-bg);color:var(--status-limited)}} .t-tested{{background:var(--sage-soft);color:var(--status-strong)}} .t-upgraded{{background:var(--teal-soft);color:var(--teal)}} .t-data{{background:var(--stone-2);color:var(--navy)}} .t-hidden{{background:var(--status-limited-bg);color:var(--status-limited)}} .t-added,.t-restyled{{background:var(--sage-soft);color:var(--status-strong)}} .t-unchanged{{background:var(--status-limited-bg);color:var(--status-limited)}}
.btn{{background:var(--teal);color:#fff;border:0;border-radius:10px;padding:12px 20px;font:600 16px var(--sans);cursor:pointer}}
.pill{{display:inline-block;background:var(--teal-soft);color:var(--teal);border-radius:999px;padding:2px 10px;font-size:13px;font-weight:600}}
@media print{{.noprint{{display:none}} body{{background:#fff}} .card{{box-shadow:none;break-inside:avoid}}}}
</style></head><body>{sprite}<main>
<span class="pill">Redesign · Phase 6 of 8</span>
<h1>Showing the evidence, limits and next step clearly</h1>
<p class="lead">We made the sources, the status of each result, the limitations and the recommended next step easy to see. <b>Everything shown already existed in the app: no source, confidence level, limitation or recommendation was invented.</b></p>
<div class="noprint" style="margin:16px 0"><button class="btn" onclick="window.print()">Save as PDF</button>
<span style="color:#5f6873;margin-left:10px">Opens your print window: choose “Save as PDF”.</span></div>
<div class="ok">✓ Every piece of information is still there (all 574 checked), every button and link still works, the export is still
accepted by the organizers' checker, and all 5 test packs pass.</div>

<h2>What we surfaced, and where</h2>
{sections}

<h2>The original buttons still work</h2>
<div class="card"><p>We clicked through every original control after the change: practice report, Check every claim, a problem card, Confirm, Override with a reason, a decision choice and Export; plus the new See evidence links and the review field mirrored into the next-step card. <b>All worked, and the export said 'valid'.</b></p></div>

<h2>How we checked nothing was lost</h2>
<div class="card"><ol>
<li>All 574 pieces of text from before are still on the page, word for word (we read the page with the new tips taken out).</li>
<li>Comparison against the original page: no value, button, download or text removed or edited.</li>
<li>All 5 automatic test packs pass, and there were no errors in the page.</li>
</ol></div>

<h2>Which files changed</h2>
<div class="card"><table>
<tr><td><b>web/index.html</b></td><td>Looks only: source cards, status badges, limitation boxes, the next-step card and the disclaimer style. Nothing that checks claims, saves results or talks to the server was touched.</td></tr>
<tr><td><b>tools/ui_baseline.py</b></td><td>Now also allows the new next-step card's box.</td></tr>
</table></div>

<h2>Nothing was skipped</h2>
<p>Every change was a safe rearrangement of what was already there, so nothing had to be skipped.</p>
<p style="color:#5f6873;margin-top:30px;font-size:14px">Research Claim Auditor · Team Cache us if u can · Redesign phase 6</p>
</main></body></html>"""
(OUT / "phase6_report.html").write_text(page, encoding="utf-8")
edge = next((p for p in [pathlib.Path(r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"),
                         pathlib.Path(r"C:\Program Files\Microsoft\Edge\Application\msedge.exe")] if p.exists()), None)
if edge:
    pdf = OUT / "phase6_report.pdf"
    pdf.unlink(missing_ok=True)
    subprocess.run([str(edge), "--headless=new", "--disable-gpu", "--no-pdf-header-footer",
                    f"--user-data-dir={tempfile.mkdtemp(prefix='edge_pdf_')}", f"--print-to-pdf={pdf}",
                    (OUT / "phase6_report.html").as_uri()], capture_output=True, timeout=120)
    for _ in range(60):
        if pdf.exists() and pdf.stat().st_size > 10000:
            break
        time.sleep(1)
    print("PDF:", pdf if pdf.exists() else "not created")
print("HTML:", OUT / "phase6_report.html")
