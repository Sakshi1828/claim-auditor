"""Build the Phase 8 (final) report (simple words) as docs/redesign/phase8_report.html and .pdf.

  python tools/build_phase8_report.py
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
    "Fits every screen size": ("ic-compare", [
        ("Tested", "Phone (375 wide), tablet (768), small laptop (1024) and large screen (1440). On each one we loaded a report, opened every tab and the side panel, and checked that nothing spills off the side. Nothing did."),
        ("Fixed", "On phones and tablets every button, link and switch is now at least 44 pixels tall, a comfortable size for a finger. This covers the step links at the top, fold-outs, small chart dots and the dotted help words."),
        ("Fixed", "In 'Read the report with its sources', lines are spaced further apart on touch screens so each sentence is easy to tap.")]),
    "Easy to read for everyone": ("ic-info", [
        ("Fixed", "The small group numbers were white on light colours, which was hard to read. They are now dark on white with a coloured ring (about 14 to 1 contrast; the rule asks for 4.5 to 1)."),
        ("Tested", "Text, labels, status pills and help bubbles all pass the standard contrast rule (WCAG AA) in light and dark mode."),
        ("Tested", "Every control shows a clear outline when reached with the keyboard. Headings go in order (page title, then sections, then parts). Buttons, charts and the side panel have spoken labels for screen readers.")]),
    "Gentle motion": ("ic-next", [
        ("Tested", "Movement is short and soft (0.15 to 0.3 seconds). If a person's computer asks for less motion, the animations switch off.")]),
    "Light and fast": ("ic-data", [
        ("Tested", "No photos, no outside fonts and no outside chart library. All drawings are small built-in line drawings, so the page loads quickly and works without internet."),
        ("Unchanged", "Once results appear, the welcome banner hides to make room. This was a planned change from Phase 3, not a jump.")]),
}
sections = "".join(
    f'<div class="card"><h3>{ic(icon)}{title}</h3><table>' + "".join(
        f'<tr><td><span class="tag t-{k.lower()}">{k}</span></td><td>{v}</td></tr>' for k, v in rows) + "</table></div>"
    for title, (icon, rows) in ROWS.items())

page = f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Redesign Final Report</title>
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
.t-fixed{{background:var(--teal-soft);color:var(--teal)}} .t-found{{background:var(--sage-soft);color:var(--status-strong)}} .t-not{{background:var(--status-limited-bg);color:var(--status-limited)}} .t-surfaced{{background:var(--teal-soft);color:var(--teal)}} .t-not shown{{background:var(--status-limited-bg);color:var(--status-limited)}} .t-tested{{background:var(--sage-soft);color:var(--status-strong)}} .t-upgraded{{background:var(--teal-soft);color:var(--teal)}} .t-data{{background:var(--stone-2);color:var(--navy)}} .t-hidden{{background:var(--status-limited-bg);color:var(--status-limited)}} .t-added,.t-restyled{{background:var(--sage-soft);color:var(--status-strong)}} .t-unchanged{{background:var(--status-limited-bg);color:var(--status-limited)}}
.btn{{background:var(--teal);color:#fff;border:0;border-radius:10px;padding:12px 20px;font:600 16px var(--sans);cursor:pointer}}
.pill{{display:inline-block;background:var(--teal-soft);color:var(--teal);border-radius:999px;padding:2px 10px;font-size:13px;font-weight:600}}
@media print{{.noprint{{display:none}} body{{background:#fff}} .card{{box-shadow:none;break-inside:avoid}}}}
</style></head><body>{sprite}<main>
<span class="pill">Redesign · Phase 8 of 8 (final)</span>
<h1>Final check: it looks better, and nothing broke</h1>
<p class="lead">We polished the look for phones, tablets and laptops, made it easier to read and use with a keyboard, and then tested the whole app again from start to finish. <b>The results, the words and the buttons are exactly the same as before the redesign.</b></p>
<div class="noprint" style="margin:16px 0"><button class="btn" onclick="window.print()">Save as PDF</button>
<span style="color:#5f6873;margin-left:10px">Opens your print window: choose “Save as PDF”.</span></div>
<div class="ok">✓ Every piece of information is still there (all 574 checked), every button and link still works, the export is still
accepted by the organizers' checker, and all 5 test packs pass.</div>

<h2>What we polished</h2>
{sections}

<h2>How we proved nothing broke</h2>
<div class="card"><p>We actually ran everything, we did not assume:</p><ol>
<li><b>The app was opened and used.</b> We loaded the practice report and the demo report and opened every result, every tab and all three views (Lead, Reviewer, Researcher).</li>
<li><b>No errors.</b> The browser showed no error messages.</li>
<li><b>Every button and form.</b> Confirm, Override (with a reason), the final decision, and Export all worked. The organizers' checker said the export is <b>valid</b>.</li>
<li><b>Same words.</b> All 574 pieces of text from before the redesign are still on the page, word for word.</li>
<li><b>Same results.</b> A side-by-side comparison with the original app (the main version) found every result, button and export identical. Nothing was removed or edited.</li>
<li><b>Tests.</b> All 5 test packs pass.</li>
</ol></div>

<h2>Which files changed in the whole redesign</h2>
<div class="card"><table>
<tr><td><b>web/index.html</b></td><td>The look of the page only: colours, layout, charts, help bubbles and the source panel. The parts that check claims, save results and talk to the server were not changed.</td></tr>
<tr><td><b>tools/</b></td><td>The comparison tool and the scripts that make these reports.</td></tr>
<tr><td><b>docs/redesign/</b></td><td>These reports and the saved 'before' snapshot.</td></tr>
<tr><td><b>Everything else</b></td><td>Untouched: the server, the checker, the data, the tests and the settings. Nothing had to be put back.</td></tr>
</table></div>

<h2>What was skipped</h2>
<p>Nothing risky came up in this phase, so nothing was skipped. Earlier, we chose not to use an outside chart library: it would need internet or a server change.</p>

<h2>What is still missing</h2>
<div class="card"><ul>
<li>The redesign is on its own branch (<b>redesign</b>). The main app is unchanged, as you asked. It still needs your go-ahead to merge it.</li>
<li>It has not been tried on a real phone or with a real screen reader. The checks above used a browser set to phone and tablet sizes.</li>
<li>For the hackathon: the demo video link and team member names still need adding to the README.</li>
</ul></div>
<p style="color:#5f6873;margin-top:30px;font-size:14px">Research Claim Auditor · Team Cache us if u can · Redesign phase 8 (final)</p>
</main></body></html>"""
(OUT / "phase8_report.html").write_text(page, encoding="utf-8")
edge = next((p for p in [pathlib.Path(r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"),
                         pathlib.Path(r"C:\Program Files\Microsoft\Edge\Application\msedge.exe")] if p.exists()), None)
if edge:
    pdf = OUT / "phase8_report.pdf"
    pdf.unlink(missing_ok=True)
    subprocess.run([str(edge), "--headless=new", "--disable-gpu", "--no-pdf-header-footer",
                    f"--user-data-dir={tempfile.mkdtemp(prefix='edge_pdf_')}", f"--print-to-pdf={pdf}",
                    (OUT / "phase8_report.html").as_uri()], capture_output=True, timeout=120)
    for _ in range(60):
        if pdf.exists() and pdf.stat().st_size > 10000:
            break
        time.sleep(1)
    print("PDF:", pdf if pdf.exists() else "not created")
print("HTML:", OUT / "phase8_report.html")
