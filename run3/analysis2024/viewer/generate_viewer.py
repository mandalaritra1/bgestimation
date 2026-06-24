#!/usr/bin/env python3
"""Build a self-contained HTML plot viewer for the 2024 ttbar analysis.

- "Key Results": the curated plots in analysis2024/plots/<category>/.
- "Browse all": an ORGANIZED tree of every 2024 plot under output/
  (region -> signal mass -> source folder), not a flat dump.

Features: click any thumbnail -> near-fullscreen lightbox with a Copy-image
button (clipboard API) and an Open-original link.

  python analysis2024/viewer/generate_viewer.py
  open  analysis2024/viewer/index.html      # or serve: (cd viewer && python -m http.server)
"""
import os, glob, html, re

VIEWER = os.path.dirname(os.path.abspath(__file__))
A2024  = os.path.dirname(VIEWER)                 # analysis2024/
ROOT   = os.path.dirname(A2024)                  # src/bgestimation/
def rel(p): return os.path.relpath(p, VIEWER)

# ---- curated key results -----------------------------------------------------
KEY_SECTIONS = [
    ("F-test (TF order selection)", "ftest", {
        "ftest_cen_1x1_to_2x1.png": "Central: 1×1→2×1 — 2×1 strongly preferred (p≈0)",
        "ftest_cen_2x1_to_2x2.png": "Central: 2×1→2×2 — not preferred (p=0.79) → stop at 2×1",
        "ftest_fwd_1x1_to_2x1.png": "Forward: 1×1→2×1 — 2×1 preferred (p=0.001)",
        "ftest_fwd_2x1_to_2x2.png": "Forward: 2×1→2×2 — not preferred (p=0.77) → stop at 2×1",
    }),
    ("Goodness of fit (saturated, blinded)", "gof", {
        "gof_cen_2x1.png": "Central 2×1 — p = 0.485",
        "gof_fwd_2x1_clamp.png": "Forward 2×1 (clamp-to-data) — p = 0.180",
    }),
    ("Limits (blinded expected, ZPrime 1% width)", "limits", {
        "limits_zprime_1pct.png": "95% CL upper limits — expected exclusion ≈ 5.32 TeV",
    }),
    ("Impacts (blinded Asimov, 3 TeV)", "impacts", {
        "impacts_zprime3000.png": "Two-sided data-driven TF impacts; r̂≈1.00±0.13",
    }),
    ("Transfer function — Fail QCD 2D", "transfer_functions", {
        "qcd_fail_2d_cen.png": "Central: Fail-region QCD (m_tt vs m_t)",
        "qcd_fail_2d_fwd.png": "Forward: Fail-region QCD (m_tt vs m_t)",
    }),
    ("Prefit vs postfit (QCD Pass 2D)", "prefit_postfit", {
        "qcd_pass_prefit_cen.png": "Central: QCD Pass prefit",
        "qcd_pass_postfit_cen.png": "Central: QCD Pass postfit",
        "qcd_pass_prefit_fwd.png": "Forward: QCD Pass prefit",
        "qcd_pass_postfit_fwd.png": "Forward: QCD Pass postfit",
    }),
    ("Postfit m_tt projections (data vs bkg)", "projections", {
        "postfit_projy_cen.png": "Central — Pass/Fail × m_t slices",
        "postfit_projy_fwd.png": "Forward — Pass/Fail × m_t slices",
    }),
]

def card(src, caption):
    s = html.escape(rel(src))
    cap = html.escape(caption)
    return ('<figure class="card" onclick="zoom(this)" data-src="{s}">'
            '<img loading="lazy" src="{s}" alt="{cap}">'
            '<figcaption>{cap}</figcaption></figure>').format(s=s, cap=cap)

def key_html():
    out = ['<h1>2024 ttbar all-hadronic — key results</h1>',
           '<p class="sub">ZPrime 1% width · TF 2×1 (cen &amp; fwd) · 109.95 fb⁻¹ (13.6 TeV) · <b>blinded</b></p>']
    for title, cat, caps in KEY_SECTIONS:
        d = os.path.join(A2024, "plots", cat)
        files = sorted(glob.glob(os.path.join(d, "*.png")))
        if not files: continue
        out.append('<section><h2>%s</h2><div class="grid">' % html.escape(title))
        for f in files:
            out.append(card(f, caps.get(os.path.basename(f), os.path.basename(f))))
        out.append('</div></section>')
    return "\n".join(out)

# ---- organized browse-all ----------------------------------------------------
def mass_of(name):
    m = re.search(r'signal\w*?(\d{3,4})', name)
    return int(m.group(1)) if m else 0

def browse_html():
    groups = [("Central (cen2024)", sorted(glob.glob(os.path.join(ROOT, "output/ttbarfits_cen2024_2x1_signal*")), key=mass_of)),
              ("Forward (fwd2024)", sorted(glob.glob(os.path.join(ROOT, "output/ttbarfits_fwd2024_2x1_signal*")), key=mass_of)),
              ("Combined (cen+fwd)", sorted(glob.glob(os.path.join(ROOT, "output/cards_combined_24/*_area")), key=mass_of))]
    out = ['<h1>Browse all 2024 plots</h1>',
           '<p class="sub">Organized by region → signal mass → source folder. PNGs only; PDFs linked.</p>']
    for gtitle, areas in groups:
        if not areas: continue
        out.append('<section><h2>%s</h2>' % html.escape(gtitle))
        for area in areas:
            pngs = sorted(glob.glob(os.path.join(area, "**", "*.png"), recursive=True))
            if not pngs: continue
            label = os.path.basename(area.rstrip("/"))
            out.append('<details><summary>%s <span class="count">(%d plots)</span></summary>' % (html.escape(label), len(pngs)))
            # sub-group by immediate parent folder under the area
            sub = {}
            for f in pngs:
                key = os.path.relpath(os.path.dirname(f), area) or "."
                sub.setdefault(key, []).append(f)
            for key in sorted(sub):
                out.append('<h3 class="subfolder">%s</h3><div class="grid">' % html.escape(key))
                for f in sorted(sub[key]):
                    out.append(card(f, os.path.basename(f)))
                out.append('</div>')
            out.append('</details>')
        out.append('</section>')
    return "\n".join(out)

# ---- page --------------------------------------------------------------------
PAGE = """<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>2024 ttbar plots</title>
<style>
:root {{ --bg:#0f1216; --panel:#171b21; --fg:#e6e6e6; --muted:#9aa4b2; --accent:#6db33f; --line:#2a313a; }}
* {{ box-sizing:border-box; }}
body {{ margin:0; font-family:-apple-system,Segoe UI,Roboto,Helvetica,Arial,sans-serif; background:var(--bg); color:var(--fg); }}
header {{ position:sticky; top:0; z-index:5; background:var(--panel); border-bottom:1px solid var(--line); padding:10px 18px; display:flex; gap:14px; align-items:center; }}
header b {{ color:var(--accent); }}
header a {{ color:var(--fg); text-decoration:none; padding:6px 12px; border-radius:6px; border:1px solid var(--line); }}
header a:hover {{ background:#222; }}
main {{ padding:18px 22px 80px; max-width:1500px; margin:0 auto; }}
h1 {{ font-size:22px; margin:18px 0 4px; }}
h2 {{ font-size:17px; margin:26px 0 10px; border-left:3px solid var(--accent); padding-left:10px; }}
h3.subfolder {{ font-size:13px; color:var(--muted); margin:14px 0 6px; font-weight:600; }}
.sub {{ color:var(--muted); margin:0 0 8px; font-size:13px; }}
.grid {{ display:grid; grid-template-columns:repeat(auto-fill,minmax(230px,1fr)); gap:12px; }}
.card {{ margin:0; background:var(--panel); border:1px solid var(--line); border-radius:8px; padding:8px; cursor:zoom-in; transition:.12s; }}
.card:hover {{ border-color:var(--accent); transform:translateY(-2px); }}
.card img {{ width:100%; height:165px; object-fit:contain; background:#fff; border-radius:4px; }}
.card figcaption {{ font-size:11.5px; color:var(--muted); margin-top:6px; line-height:1.35; }}
details {{ background:#12151a; border:1px solid var(--line); border-radius:8px; margin:10px 0; padding:6px 12px; }}
summary {{ cursor:pointer; font-weight:600; padding:6px 0; }}
.count {{ color:var(--muted); font-weight:400; font-size:12px; }}
/* lightbox */
#lb {{ position:fixed; inset:0; background:rgba(0,0,0,.92); display:none; z-index:50; flex-direction:column; }}
#lb.open {{ display:flex; }}
#lbbar {{ padding:10px 16px; display:flex; gap:10px; align-items:center; color:var(--fg); }}
#lbbar .name {{ color:var(--muted); font-size:13px; margin-right:auto; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }}
#lbbar button, #lbbar a {{ background:var(--accent); color:#06210a; border:none; padding:8px 14px; border-radius:6px; font-weight:700; cursor:pointer; text-decoration:none; font-size:13px; }}
#lbbar a.sec {{ background:#2a313a; color:var(--fg); }}
#lbimg {{ flex:1; display:flex; align-items:center; justify-content:center; padding:0 20px 20px; min-height:0; }}
#lbimg img {{ max-width:96%; max-height:100%; object-fit:contain; background:#fff; border-radius:6px; }}
#toast {{ position:fixed; bottom:24px; left:50%; transform:translateX(-50%); background:#222; color:#fff; padding:10px 18px; border-radius:8px; opacity:0; transition:.2s; z-index:60; border:1px solid var(--line); }}
#toast.show {{ opacity:1; }}
</style></head><body>
<header><b>2024 ttbar plots</b>
<a href="#key">Key results</a><a href="#browse">Browse all</a>
<span style="color:var(--muted);font-size:12px;margin-left:auto">click a plot → enlarge + copy</span></header>
<main>
<a id="key"></a>{key}
<a id="browse"></a>{browse}
</main>
<div id="lb" onclick="if(event.target.id==='lb')closeLb()">
  <div id="lbbar">
    <span class="name" id="lbname"></span>
    <button onclick="copyImg()">Copy image</button>
    <a class="sec" id="lbopen" href="#" target="_blank">Open original</a>
    <button onclick="closeLb()">Close ✕</button>
  </div>
  <div id="lbimg"><img id="lbfull" src="" alt=""></div>
</div>
<div id="toast"></div>
<script>
function zoom(el){{ var s=el.getAttribute('data-src');
  document.getElementById('lbfull').src=s; document.getElementById('lbopen').href=s;
  document.getElementById('lbname').textContent=s; document.getElementById('lb').classList.add('open'); }}
function closeLb(){{ document.getElementById('lb').classList.remove('open'); }}
document.addEventListener('keydown',function(e){{ if(e.key==='Escape')closeLb(); }});
function toast(m){{ var t=document.getElementById('toast'); t.textContent=m; t.classList.add('show'); setTimeout(function(){{t.classList.remove('show');}},1800); }}
async function copyImg(){{
  var src=document.getElementById('lbfull').src;
  try {{
    var blob=await (await fetch(src)).blob();
    await navigator.clipboard.write([new ClipboardItem({{[blob.type]: blob}})]);
    toast('Image copied to clipboard');
  }} catch(e) {{
    toast('Copy blocked on file:// — run "python -m http.server" here, or right-click the image');
  }}
}}
</script></body></html>"""

with open(os.path.join(VIEWER, "index.html"), "w") as fh:
    fh.write(PAGE.format(key=key_html(), browse=browse_html()))
print("wrote", os.path.join(VIEWER, "index.html"))
