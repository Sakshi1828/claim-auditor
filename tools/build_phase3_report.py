"""Build the Phase 2 report (simple words) as docs/redesign/phase3_report.html and .pdf.

  python tools/build_phase3_report.py
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
    "Welcome area (new, at the top)": ("ic-info", [
        ("Added", "A calm welcome panel that says in plain words what the app does: “Is this research report right? Check it against the real data.”, with a short explanation and the 3 steps (Load, Review, Decide)."),
        ("Added", "A gentle drawing of a DNA helix that floats very slowly. It stops moving for anyone whose computer is set to reduce motion."),
        ("Added", "A very faint tissue pattern behind it (5% strength), so the text stays just as easy to read."),
        ("Hidden", "Once your results appear, the welcome panel steps aside so the results come first."),
        ("Unchanged", "The real buttons (Check every claim, practice report, upload, envelope) are the same buttons, still in Step 1.")]),
    "Top bar (navigation)": ("ic-next", [
        ("Restyled", "Each step link (Load, Review, Decide) now has a small icon, and the current step has a clear underline."),
        ("Added", "On phones and narrow windows, a “Menu” button opens a drawer with the same 3 links. Escape or choosing a link closes it."),
        ("Unchanged", "The same 3 links, going to the same places, unlocking at the same times.")]),
    "All boxes and cards": ("ic-data", [
        ("Restyled", "Every card now has the same rounded corners, the same soft shadow and the same inner spacing, so the app looks like one piece.")]),
    "Waiting and empty screens": ("ic-review", [
        ("Added", "Before you check a report, a friendly note with a cell drawing says “Your results will appear here”."),
        ("Added", "While the app is already busy checking or unsealing, grey placeholder bars show where results will appear. They only show while the app is genuinely working."),
        ("Added", "If no claim is selected in Step 2, the existing “Select a sentence on the left.” now sits under a small cell drawing.")]),
}
sections = "".join(
    f'<div class="card"><h3>{ic(icon)}{title}</h3><table>' + "".join(
        f'<tr><td><span class="tag t-{k.lower()}">{k}</span></td><td>{v}</td></tr>' for k, v in rows) + "</table></div>"
    for title, (icon, rows) in ROWS.items())

page = f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Redesign Phase 3 Report</title>
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
.t-hidden{{background:var(--status-limited-bg);color:var(--status-limited)}} .t-added,.t-restyled{{background:var(--sage-soft);color:var(--status-strong)}} .t-unchanged{{background:var(--status-limited-bg);color:var(--status-limited)}}
.btn{{background:var(--teal);color:#fff;border:0;border-radius:10px;padding:12px 20px;font:600 16px var(--sans);cursor:pointer}}
.pill{{display:inline-block;background:var(--teal-soft);color:var(--teal);border-radius:999px;padding:2px 10px;font-size:13px;font-weight:600}}
@media print{{.noprint{{display:none}} body{{background:#fff}} .card{{box-shadow:none;break-inside:avoid}}}}
</style></head><body>{sprite}<main>
<span class="pill">Redesign · Phase 3 of 8</span>
<h1>A calmer, more welcoming look</h1>
<p class="lead">We added a welcome area that explains the app in one sentence, tidied the top bar, gave every box the same
calm style, and added friendly waiting and empty screens. We used drawings in only 3 places, so it never feels busy.
<b>Nothing about how the app works was changed.</b></p>
<div class="noprint" style="margin:16px 0"><button class="btn" onclick="window.print()">Save as PDF</button>
<span style="color:#5f6873;margin-left:10px">Opens your print window: choose “Save as PDF”.</span></div>
<div class="ok">✓ Every piece of information is still there (all 574 checked), every button and link still works, the export is still
accepted by the organizers' checker, and all 5 test packs pass.</div>

<h2>What changed, part by part</h2>
{sections}

<h2>Which files changed</h2>
<div class="card"><table>
<tr><td><b>web/index.html</b></td><td>The page's look only: the welcome panel, the menu button, the empty and waiting screens, and their styles. One small view-only helper opens and closes the phone menu. Nothing that checks claims, saves results or talks to the server was touched.</td></tr>
<tr><td><b>tools/ui_baseline.py</b></td><td>Our checking tool: it now also allows the new Menu button and still fails if any old button or text disappears.</td></tr>
<tr><td><b>Everything else</b></td><td>Not touched: the checking engine, the data, the exports, the server.</td></tr>
</table></div>

<h2>How we checked that nothing broke</h2>
<div class="card"><ol>
<li>We recorded all 574 pieces of text the page shows before the change, and checked them all again after: none missing.</li>
<li>We clicked through everything: practice report, check, plain words, filters, tabs, confirm, override, the step links, the decision and export. All worked; the export said “valid”.</li>
<li>On a phone-sized screen: the Menu opens and closes, the 3 links are the same, and nothing spills off the side.</li>
<li>The waiting bars appear only while the app is checking; the welcome and empty screens step aside once results arrive.</li>
<li>Our automatic comparison against the original page: no value, button, download or text removed or edited.</li>
</ol></div>

<h2>Nothing was skipped</h2>
<p>Every change was a safe rearrangement of what was already there, so nothing had to be skipped.</p>
<p style="color:#5f6873;margin-top:30px;font-size:14px">Research Claim Auditor · Team Cache us if u can · Redesign phase 3</p>
</main></body></html>"""
(OUT / "phase3_report.html").write_text(page, encoding="utf-8")
edge = next((p for p in [pathlib.Path(r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"),
                         pathlib.Path(r"C:\Program Files\Microsoft\Edge\Application\msedge.exe")] if p.exists()), None)
if edge:
    pdf = OUT / "phase3_report.pdf"
    pdf.unlink(missing_ok=True)
    subprocess.run([str(edge), "--headless=new", "--disable-gpu", "--no-pdf-header-footer",
                    f"--user-data-dir={tempfile.mkdtemp(prefix='edge_pdf_')}", f"--print-to-pdf={pdf}",
                    (OUT / "phase3_report.html").as_uri()], capture_output=True, timeout=120)
    for _ in range(60):
        if pdf.exists() and pdf.stat().st_size > 10000:
            break
        time.sleep(1)
    print("PDF:", pdf if pdf.exists() else "not created")
print("HTML:", OUT / "phase3_report.html")
