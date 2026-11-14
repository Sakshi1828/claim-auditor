"""Build the Phase 1 report (simple words) as docs/redesign/phase1_report.html and .pdf.

  python tools/build_phase1_report.py
Colours and pictures are copied from web/index.html, so the report shows exactly what the app now uses.
The PDF is printed by Microsoft Edge in headless mode (already on Windows); the HTML also has a "Save as PDF" button.
"""
import json
import pathlib
import re
import subprocess

ROOT = pathlib.Path(__file__).resolve().parents[1]
OUT = ROOT / "docs/redesign"
html_app = (ROOT / "web/index.html").read_text(encoding="utf-8")
tokens = re.search(r"(:root\{\n  /\* base palette.*?\n\})", html_app, re.S).group(1)       # light tokens only (prints well)
sprite = re.search(r'(<svg id="illustrations".*?</svg>)', html_app, re.S).group(1)
base = json.loads((OUT / "baseline.json").read_text(encoding="utf-8"))
n_claims = sum(len(r["claims"]) for r in base["reports"].values())


def use(i, w=220, h=110, vb="0 0 240 120"):
    return f'<svg width="{w}" height="{h}" viewBox="{vb}" role="img" aria-label="{i}"><use href="#{i}"/></svg>'


def icon(i, label):
    return f'<div class="ic"><svg width="34" height="34" viewBox="0 0 24 24" aria-hidden="true"><use href="#{i}"/></svg><span>{label}</span></div>'


SW = [("Deep navy", "--navy", "Main text and headings"), ("Calm teal", "--teal", "Buttons, links, highlights"),
      ("Soft sage", "--sage", "Gentle decoration"), ("Warm sand", "--sand", "Page background"),
      ("Clean white", "--white", "Cards and boxes"), ("Stone", "--stone", "Thin lines between things")]
ST = [("Strong evidence", "--status-strong", "--status-strong-bg", "Used for “Supported”: the data agrees"),
      ("Conflicting", "--status-conflict", "--status-conflict-bg", "Used for “Contradicted”: the data says something different (soft clay, not alarm red)"),
      ("Uncertain", "--status-uncertain", "--status-uncertain-bg", "Used for “Insufficient evidence”: the data can't settle it"),
      ("Limited data", "--status-limited", "--status-limited-bg", "Used for neutral items such as “Not a claim”")]

swatches = "".join(f'<div class="sw"><span style="background:var({v})"></span><b>{n}</b><small>{d}</small></div>' for n, v, d in SW)
status = "".join(f'<div class="st" style="background:var({bg});color:var({fg})"><b>{n}</b><small>{d}</small></div>'
                 for n, fg, bg, d in ST)
charts = "".join(f'<span style="background:var(--chart-{i})"></span>' for i in range(1, 7))

page = f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Redesign Phase 1 Report</title>
<style>
{tokens}
*{{box-sizing:border-box}}
body{{margin:0;background:var(--sand);color:var(--navy);font:16px/1.65 var(--sans)}}
main{{max-width:860px;margin:0 auto;padding:32px 20px 60px}}
h1,h2{{font-family:var(--serif);font-weight:600;line-height:1.25}}
h1{{font-size:32px;margin:6px 0 4px}} h2{{font-size:23px;margin:36px 0 10px;padding-top:18px;border-top:1px solid var(--stone)}}
p,li{{color:#3a4654}} .lead{{font-size:18px}}
.card{{background:var(--white);border:1px solid var(--stone);border-radius:14px;padding:18px 20px;margin:12px 0;box-shadow:var(--shadow)}}
.ok{{background:var(--status-strong-bg);color:var(--status-strong);border-radius:12px;padding:14px 18px;font-weight:600}}
table{{width:100%;border-collapse:collapse;font-size:15px}} td,th{{text-align:left;padding:8px 10px;border-bottom:1px solid var(--stone-2);vertical-align:top}}
th{{color:var(--teal);font-size:13px;text-transform:uppercase;letter-spacing:.05em}}
.sws{{display:grid;grid-template-columns:repeat(auto-fill,minmax(180px,1fr));gap:12px}}
.sw{{display:flex;flex-direction:column;gap:2px}} .sw span{{height:46px;border-radius:10px;border:1px solid var(--stone)}} .sw small{{color:#5f6873}}
.st{{border-radius:12px;padding:12px 16px;margin:8px 0}} .st small{{display:block;opacity:.9}}
.chart{{display:flex;gap:6px}} .chart span{{flex:1;height:28px;border-radius:6px}}
.ills{{display:flex;flex-wrap:wrap;gap:14px}} .ills figure{{margin:0;background:var(--white);border:1px solid var(--stone);border-radius:12px;padding:10px}}
.ills figcaption{{font-size:14px;color:#5f6873;text-align:center}}
.icons{{display:flex;flex-wrap:wrap;gap:18px;color:var(--teal)}} .ic{{display:flex;flex-direction:column;align-items:center;gap:4px;width:92px;text-align:center;font-size:13.5px;color:var(--navy)}}
.btn{{background:var(--teal);color:#fff;border:0;border-radius:10px;padding:12px 20px;font:600 16px var(--sans);cursor:pointer}}
.tag{{display:inline-block;background:var(--teal-soft);color:var(--teal);border-radius:999px;padding:2px 10px;font-size:13px;font-weight:600}}
@media print{{ .noprint{{display:none}} body{{background:#fff}} .card,.ills figure{{box-shadow:none;break-inside:avoid}} h2{{break-after:avoid}} }}
</style></head><body>
{sprite}
<main>
<span class="tag">Redesign · Phase 1 of 8</span>
<h1>New look: what we checked and what we changed</h1>
<p class="lead">This is the first step of making the Claim Auditor easier on the eyes and easier to understand.
In this step we only <b>looked</b>, <b>measured</b>, and changed the <b>colours and letters</b>. Nothing the app does was changed.</p>
<div class="noprint" style="margin:16px 0"><button class="btn" onclick="window.print()">Save as PDF</button>
<span style="color:#5f6873;margin-left:10px">Opens your print window: choose “Save as PDF”.</span></div>

<div class="ok">✓ Everything still works exactly as before. We checked all {n_claims} test claims, every button and every
download, and all 5 test packs passed.</div>

<h2>1. What the app is made of</h2>
<div class="card"><p>The app is <b>one web page</b>, written in plain HTML, CSS and JavaScript (no extra add-ons). The checking is
done by Python on your computer. There is <b>no chart add-on</b>: the few bars you see are drawn by the page itself.</p></div>

<h2>2. The screens, top to bottom</h2>
<table>
<tr><th>Part of the page</th><th>What a person sees there</th></tr>
<tr><td>Top bar</td><td>App name, the 3 steps (Load · Review · Decide), “Research use only”.</td></tr>
<tr><td>Guide strip</td><td>One sentence telling you what to do now, and a button that does it.</td></tr>
<tr><td>Step 1 · Load</td><td>A box to paste a report, upload a file, use the practice report, or open a sealed envelope.</td></tr>
<tr><td>Summary card</td><td>The headline result, the “HOLD &amp; REVISE”-style stamp, a coloured bar of results, and the biggest problems.</td></tr>
<tr><td>In plain words</td><td>The same result in everyday language, plus a list of medical words explained.</td></tr>
<tr><td>Step 2 · Review</td><td>Left: the report, each sentence coloured by result. Right: the details for one claim (what the report says, what the data says, why it matters, what to do).</td></tr>
<tr><td>Step 3 · Decide</td><td>The suggested decision, steps to fix things, what the check can't tell you, your decision, and the Export button.</td></tr>
</table>

<h2>3. Where the numbers come from</h2>
<table>
<tr><th>What you see</th><th>Where it comes from</th></tr>
<tr><td>Verdicts, numbers like “49.9% (421 of 844)”</td><td>Python checks the report against the data files (the “check” step).</td></tr>
<tr><td>Next steps, the suggested decision, the corrected report</td><td>Worked out again each time a person confirms or changes a verdict.</td></tr>
<tr><td>Plain-words summary and word list</td><td>Rewritten from the same results; it never adds new facts.</td></tr>
<tr><td>Downloaded files (audit.json, decision record, corrected report)</td><td>Saved by the Export button into the “outputs” folder.</td></tr>
<tr><td>AI reading (only if switched on)</td><td>An AI describes each claim; the computer then checks it against the data.</td></tr>
</table>

<h2>4. Buttons and what they do (none of these were changed)</h2>
<table>
<tr><th>Button</th><th>What it does</th></tr>
<tr><td>Use the practice report · Upload a file</td><td>Puts a report into the box.</td></tr>
<tr><td>Open a sealed envelope · Unseal and check</td><td>Opens the judges’ envelope and checks its report.</td></tr>
<tr><td>Check every claim</td><td>Checks the whole report. Optional tick box: also read the claims with AI.</td></tr>
<tr><td>Explain it in plain words · Glossary</td><td>Show or hide the everyday-language summary and word list.</td></tr>
<tr><td>Program lead / Reviewer / Researcher</td><td>Show less or more detail. The facts stay the same.</td></tr>
<tr><td>Confirm · Override · Undo · Next claim</td><td>A person agrees with, changes, or undoes a verdict.</td></tr>
<tr><td>Decision choices · Export</td><td>Pick Proceed / Fix a problem / Narrow the question / Stop, write why, and save the files.</td></tr>
<tr><td>Download corrected report · Copy suggested wording</td><td>Save or copy the suggested fixes.</td></tr>
</table>

<h2>5. Where the page is hardest to read today</h2>
<div class="card"><ol>
<li><b>The claim details panel</b> (right side of Step 2) is long: many boxes stacked on top of each other.</li>
<li><b>“How this claim was analysed”</b> is a table of technical words (field names, steps).</li>
<li><b>Step 3</b> has two long lists side by side (what to do, what it can't tell you).</li>
<li><b>The guide strip</b> sentence is sometimes long and wraps onto 3 lines on small screens.</li>
<li><b>Field names</b> such as <code>PAM50Call_RNAseq</code> appear in places a normal reader doesn't need them.</li>
</ol></div>

<h2>6. Our “before” record (to prove nothing changes later)</h2>
<div class="card"><p>We saved a record of everything the app shows for two test reports: <b>{n_claims} claims</b>, every verdict,
every number, every next step, every plain-words sentence, and the text of every downloaded file, plus all
<b>{len(base['page']['buttons'])} buttons</b> and <b>{len(base['page']['element_ids'])} page parts</b>.
After today's change we compared again: <b>no difference at all</b>. We will repeat this check at the end of every phase.</p>
<p style="margin:0">Tests: main checks ✓ · calculation checks ✓ · AI-layer checks ✓ · AI-reading checks ✓ · different-data-release checks ✓</p></div>

<h2>7. The new colours (soft on the eyes)</h2>
<p>Every text colour was measured for comfortable reading (it passes the common eye-comfort reading standard, called
WCAG AA, in both light and dark mode). There is no harsh red anywhere.</p>
<div class="sws">{swatches}</div>
<h3 style="font-family:var(--serif);margin-top:22px">Colours for results (the words on screen stay the same)</h3>
{status}
<h3 style="font-family:var(--serif);margin-top:22px">Colours for future charts</h3>
<p>Six calm colours that still look different to people who are colour-blind:</p><div class="chart">{charts}</div>

<h2>8. Letters and spacing</h2>
<div class="card"><p><b>Headings:</b> an elegant book-style font (<span style="font-family:var(--serif)">like this</span>).
<b>Normal text:</b> a clear, modern font, slightly larger than before (15.5 instead of 15) with a little more space between lines.
We used fonts that are already on the computer, so the app still works <b>without internet</b> and sends nothing out.</p>
<p style="margin:0">We also set fixed sizes for gaps, rounded corners and soft shadows, so every later screen looks consistent.</p></div>

<h2>9. New pictures (ready, not shown in the app yet)</h2>
<p>Calm, respectful line drawings in the same colours. They are stored invisibly in the page and will be placed in later phases.</p>
<div class="ills">
<figure>{use('ill-cells')}<figcaption>Cells: orderly (left) and irregular (right)</figcaption></figure>
<figure>{use('ill-dna', 220, 74, '0 0 240 80')}<figcaption>DNA helix</figcaption></figure>
<figure style="opacity:.55">{use('ill-tissue')}<figcaption>Tissue background (used very faintly)</figcaption></figure>
<figure style="opacity:.55">{use('ill-molecules')}<figcaption>Molecule network background</figcaption></figure>
</div>
<div class="card"><div class="icons">{icon('ic-evidence','Evidence')}{icon('ic-compare','Comparison')}{icon('ic-uncertain','Uncertain')}{icon('ic-next','Next step')}{icon('ic-review','Person checks')}{icon('ic-data','Data')}{icon('ic-info','More info')}</div></div>

<h2>10. Plan: where pictures and charts can replace text</h2>
<table>
<tr><th>Where</th><th>Today</th><th>Idea for later phases (same facts, easier to see)</th></tr>
<tr><td>Summary card</td><td>“1 of 3 claims is contradicted…” plus a thin bar</td><td>A larger, labelled bar or ring showing how many claims agree, conflict, or can't be checked.</td></tr>
<tr><td>Claim details</td><td>Many stacked text boxes</td><td>Tabs: “What it says” · “What the data shows” · “What to do”, each with an icon.</td></tr>
<tr><td>Report vs data</td><td>A number line</td><td>Keep it, but larger, with the two values clearly labelled.</td></tr>
<tr><td>Data completeness</td><td>“844 of 1,101 have a value (23% missing)”</td><td>A small filled bar showing how complete the data is.</td></tr>
<tr><td>Step 3 · what to do</td><td>A numbered text list</td><td>Step cards with the “next step” icon, one action each.</td></tr>
<tr><td>What the check can't tell you</td><td>A bullet list</td><td>The same list with the “uncertain” icon, grouped and collapsible.</td></tr>
<tr><td>Different data release</td><td>One sentence</td><td>A small checklist: renamed ✓, missing ✕, added +.</td></tr>
<tr><td>Empty/start screen</td><td>Text only</td><td>The cell or DNA drawing as a calm welcome picture.</td></tr>
</table>

<h2>11. What changed and what did not</h2>
<div class="card"><p><b>Changed:</b> colours, fonts, text size and line spacing; the small tab icon colour; a hidden picture library.</p>
<p style="margin:0"><b>Not changed:</b> any button, box, wording, number, result, download, calculation, or anything behind the screen.
Nothing was risky, so nothing had to be skipped.</p></div>
<p style="color:#5f6873;margin-top:30px;font-size:14px">Research Claim Auditor · Team Cache us if u can · Redesign phase 1</p>
</main></body></html>"""
OUT.mkdir(parents=True, exist_ok=True)
(OUT / "phase1_report.html").write_text(page, encoding="utf-8")
edge = next((p for p in [pathlib.Path(r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"),
                         pathlib.Path(r"C:\Program Files\Microsoft\Edge\Application\msedge.exe")] if p.exists()), None)
if edge:
    pdf = OUT / "phase1_report.pdf"
    import tempfile   # its own profile, so an open Edge window doesn't swallow the request
    subprocess.run([str(edge), "--headless=new", "--disable-gpu", "--no-pdf-header-footer",
                    f"--user-data-dir={tempfile.mkdtemp(prefix='edge_pdf_')}", f"--print-to-pdf={pdf}",
                    (OUT / "phase1_report.html").as_uri()], capture_output=True, timeout=120)
    import time
    for _ in range(60):                       # Edge can hand the job to a background process: wait for the file
        if pdf.exists() and pdf.stat().st_size > 10000:
            break
        time.sleep(1)
    print("PDF:", pdf if pdf.exists() else "not created")
print("HTML:", OUT / "phase1_report.html")
