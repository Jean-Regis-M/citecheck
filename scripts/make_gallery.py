"""Build the Devpost gallery: real, high-resolution captures of the running app composed into
consistent 3:2 slides with numbered callouts. Dev tool.

  1. run the app (python -m uvicorn app.main:app --port 8000)  [or pass --url for the live site]
  2. python scripts/make_gallery.py [--url http://localhost:8000] [--out ../submission/gallery]
"""
import argparse
import base64
import json
from pathlib import Path

from playwright.sync_api import sync_playwright

DRAFT = ("Transformers dispense with recurrence and rely entirely on attention mechanisms [1]. "
         "The model reached 28.4 BLEU on the WMT 2014 English-to-German task [1]. "
         "Transformers are cheaper to train than every earlier model on every task [1]. "
         "The Transformer is built on recurrent layers at its core [1].")
SOURCE = "https://arxiv.org/abs/1706.03762"
SITE = "citecheck-p66j.onrender.com"

CSS = """
*{box-sizing:border-box;margin:0}
body{width:1500px;height:1000px;background:#f7f4ee;color:#1d1b16;font-family:'Segoe UI',system-ui,sans-serif;position:relative;overflow:hidden}
.top{position:absolute;left:70px;top:52px;display:flex;align-items:center;gap:16px}
.chip{font-weight:800;font-size:20px;letter-spacing:.12em;text-transform:uppercase;padding:9px 20px;border-radius:99px}
.ok{background:#e3f3ea;color:#1f7a4d}.pt{background:#fbf0d2;color:#8a6100}.bad{background:#fbe4e1;color:#a4261f}.nu{background:#1f4d3a;color:#fff}
.step{font-size:20px;color:#9a948a;letter-spacing:.1em}
h1{font:700 60px/1.06 Georgia,'Times New Roman',serif;letter-spacing:-1.5px}
.copy{position:absolute;left:70px;top:130px;width:520px}
.copy p{font-size:26px;line-height:1.4;color:#4a463d;margin-top:26px}
.legend{margin-top:38px;display:flex;flex-direction:column;gap:20px}
.lg{display:flex;gap:16px;align-items:flex-start;font-size:23px;line-height:1.3;color:#3a372f}
.n{flex:none;width:38px;height:38px;border-radius:50%;background:#1f4d3a;color:#fff;font-weight:800;font-size:21px;display:flex;align-items:center;justify-content:center}
.foot{position:absolute;left:0;right:0;bottom:0;height:62px;background:#1f4d3a;color:#e9f2ed;display:flex;align-items:center;justify-content:space-between;padding:0 70px;font-size:20px}
.foot b{font:700 26px Georgia,serif;color:#fff}.foot b i{font-style:normal;color:#9fd9b8}
.shot{position:absolute;border-radius:18px;background:#fffdf8;box-shadow:0 26px 60px rgba(40,35,20,.28);border:3px solid #fffdf8;overflow:visible}
.shot img{display:block;width:100%;border-radius:15px}
.pin{position:absolute;width:44px;height:44px;border-radius:50%;background:#1f4d3a;color:#fff;font-weight:800;font-size:24px;display:flex;align-items:center;justify-content:center;border:4px solid #f7f4ee;box-shadow:0 6px 14px rgba(0,0,0,.3)}
.card{background:#fffdf8;border:2px solid #e2dccd;border-radius:20px;padding:30px 34px;box-shadow:0 12px 30px rgba(40,35,20,.10)}
"""
FOOT = f'<div class=foot><b>Cite<i>Check</i></b><span>{SITE} &nbsp;&middot;&nbsp; github.com/Jean-Regis-M/citecheck</span></div>'


def b64(p):
    return base64.b64encode(Path(p).read_bytes()).decode()


def page(inner):
    return f"<!doctype html><html><head><meta charset=utf-8><style>{CSS}</style></head><body>{inner}{FOOT}</body></html>"


def capture(url, raw: Path):
    raw.mkdir(parents=True, exist_ok=True)
    meta = {}
    with sync_playwright() as p:
        b = p.chromium.launch(channel="msedge")
        pg = b.new_page(viewport={"width": 1280, "height": 860}, device_scale_factor=2, color_scheme="light")
        pg.goto(url, wait_until="networkidle")
        pg.evaluate("document.getElementById('draft').spellcheck=false")
        pg.fill("#draft", DRAFT)
        pg.fill(".src input", "1")
        pg.fill(".src textarea", SOURCE)
        pg.evaluate("document.getElementById('draft').scrollTop=0")
        pg.screenshot(path=str(raw / "input.png"))
        pg.click("#run")
        pg.wait_for_selector(".res", timeout=180000)
        pg.wait_for_timeout(600)
        pg.evaluate("window.scrollTo(0,0)")
        pg.screenshot(path=str(raw / "overview.png"))
        n = pg.locator(".res").count()
        assert n == 4, f"expected 4 results, got {n}"
        for i in range(4):
            card = pg.locator(".res").nth(i)
            card.scroll_into_view_if_needed()
            card.screenshot(path=str(raw / f"card{i}.png"))
            meta[i] = pg.evaluate("""i=>{const c=document.querySelectorAll('.res')[i];const r=c.getBoundingClientRect();
              const f=(s,k=0)=>{const e=c.querySelectorAll(s)[k];if(!e)return null;const q=e.getBoundingClientRect();return {y:q.top-r.top,h:q.height}};
              return {w:r.width,h:r.height,pill:f('.pill'),claim:f('.claim'),issue:f('.issue'),quote:f('blockquote'),reason:f('.meta',1),det:f('details')}}""", i)
        m = b.new_page(viewport={"width": 390, "height": 844}, device_scale_factor=3, color_scheme="light")
        m.goto(url, wait_until="networkidle")
        m.evaluate("document.getElementById('draft').spellcheck=false")
        m.fill("#draft", DRAFT); m.fill(".src input", "1"); m.fill(".src textarea", SOURCE)
        m.evaluate("document.getElementById('draft').scrollTop=0")
        m.screenshot(path=str(raw / "m_input.png"))
        m.click("#run"); m.wait_for_selector(".res", timeout=180000); m.wait_for_timeout(500)
        m.evaluate("document.querySelector('.summary').scrollIntoView({block:'start'})")
        m.evaluate("window.scrollBy(0,-44)")
        m.screenshot(path=str(raw / "m_results.png"))
        b.close()
    (raw / "meta.json").write_text(json.dumps(meta))
    return meta


def card_slide(raw, meta, i, chip_cls, chip, headline, sub, legend, pins, step):
    m = meta[str(i)]
    scale = 760 / m["w"]
    ch = m["h"] * scale
    top = max(120, (1000 - 62 - ch) / 2 + 20)
    pin_html = ""
    for key, num in pins:
        r = m.get(key)
        if r:
            y = top + (r["y"] + r["h"] / 2) * scale - 22
            pin_html += f'<div class=pin style="left:{700-34}px;top:{y:.0f}px">{num}</div>'
    leg = "".join(f'<div class=lg><div class=n>{k}</div><div>{t}</div></div>' for k, t in legend)
    return page(f'''<div class=top><span class="chip {chip_cls}">{chip}</span><span class=step>{step}</span></div>
<div class=copy><h1>{headline}</h1><p>{sub}</p><div class=legend>{leg}</div></div>
<div class=shot style="left:700px;top:{top:.0f}px;width:760px"><img src="data:image/png;base64,{b64(raw / f"card{i}.png")}"></div>{pin_html}''')


def build(raw: Path, out: Path):
    out.mkdir(parents=True, exist_ok=True)
    meta = json.loads((raw / "meta.json").read_text())
    S = {}
    # 1 overview
    S["01-overview"] = page(f'''<div class=top><span class="chip nu">The live app</span><span class=step>01 / 07</span></div>
<div style="position:absolute;left:70px;top:112px;width:1360px"><h1 style="font-size:50px">Four cited claims, four honest verdicts</h1></div>
<div class=shot style="left:150px;top:190px;width:1200px;height:700px;overflow:hidden"><img style="border-radius:15px 15px 0 0" src="data:image/png;base64,{b64(raw / "overview.png")}"></div>''')
    # 2-4 close-ups
    S["02-supported"] = card_slide(raw, meta, 0, "ok", "Supported", "The proof, quoted from the paper",
        "CiteCheck only says a claim is supported if the evidence sentence is found, word for word, in the source.",
        [(1, "The verdict"), (2, "The claim as written"), (3, "The exact quote, verified in code"), (4, "Why the model decided this")],
        [("pill", 1), ("claim", 2), ("quote", 3), ("reason", 4)], "02 / 07")
    S["03-partly"] = card_slide(raw, meta, 2, "pt", "Partly supported", "Catches the overclaim",
        "The paper shows this on two translation tasks. The sentence says every task. CiteCheck flags the gap.",
        [(1, "Verdict: partly supported"), (2, "A one-line note on what is overstated"), (3, "The sentence from the paper that limits the claim")],
        [("pill", 1), ("issue", 2), ("quote", 3)], "03 / 07")
    S["04-contradicted"] = card_slide(raw, meta, 3, "bad", "Contradicted", "Says when the source disagrees",
        "The paper replaces recurrent layers with attention. The claim says the opposite, so it is flagged with the evidence.",
        [(1, "Verdict: contradicted"), (2, "What the source actually says"), (3, "Passages the model saw: open to check the evidence")],
        [("pill", 1), ("issue", 2), ("det", 3)], "04 / 07")
    # 5 pipeline
    def box(t, s, ai=False, d=0):
        return f'<div style="background:{"#1f4d3a" if ai else "#fffdf8"};color:{"#fff" if ai else "#1d1b16"};border:3px solid {"#1f4d3a" if ai else "#e2dccd"};border-radius:20px;padding:26px 18px;width:230px;text-align:center;font-size:27px;box-shadow:0 10px 24px rgba(40,35,20,.1)">{t}<div style="font-size:18px;letter-spacing:.1em;text-transform:uppercase;margin-top:10px;color:{"#cfe6da" if ai else "#6b665b"}">{s}</div></div>'
    arrow = '<div style="font-size:38px;color:#9a948a">&rarr;</div>'
    S["05-pipeline"] = page(f'''<div class=top><span class="chip nu">How it works</span><span class=step>05 / 07</span></div>
<div style="position:absolute;left:70px;top:112px;width:1360px"><h1 style="font-size:56px">The AI has one job. Code audits it.</h1></div>
<div style="position:absolute;left:55px;right:55px;top:290px;display:flex;align-items:center;justify-content:space-between">
{box("Find claims","code")}{arrow}{box("Fetch sources","safe code")}{arrow}{box("Rank passages","BM25")}{arrow}{box("Judge claim","Gemini",True)}{arrow}{box("Verify quote","code")}</div>
<div style="position:absolute;left:70px;right:70px;top:540px;display:flex;gap:30px">
<div class=card style="flex:1"><div style="font:700 30px Georgia,serif;color:#1f4d3a">No quote, no verdict</div><div style="font-size:23px;line-height:1.4;margin-top:12px;color:#4a463d">A verdict is shown only if its quote appears word for word in the source text.</div></div>
<div class=card style="flex:1"><div style="font:700 30px Georgia,serif;color:#1f4d3a">Honest about doubt</div><div style="font-size:23px;line-height:1.4;margin-top:12px;color:#4a463d">When evidence is thin or unreachable, it says &ldquo;can&rsquo;t verify&rdquo; instead of guessing.</div></div>
<div class=card style="flex:1"><div style="font:700 30px Georgia,serif;color:#1f4d3a">Never overreaches</div><div style="font-size:23px;line-height:1.4;margin-top:12px;color:#4a463d">If only an abstract was available, it never claims the source fails to support you.</div></div></div>
<div style="position:absolute;left:70px;right:70px;top:820px;font-size:23px;color:#6b665b">Everything except the judging step is ordinary code, covered by 11 unit tests. The judging step is measured on a public benchmark.</div>''')
    # 6 evaluation
    def stat(big, lab):
        return f'<div style="text-align:center"><div style="font:700 96px/1 Georgia,serif;color:#1f4d3a">{big}</div><div style="font-size:24px;color:#4a463d;margin-top:14px;max-width:340px">{lab}</div></div>'
    S["06-evaluation"] = page(f'''<div class=top><span class="chip nu">Measured, not assumed</span><span class=step>06 / 07</span></div>
<div style="position:absolute;left:70px;top:112px;width:1360px"><h1 style="font-size:56px">Tested on the public SciFact benchmark</h1></div>
<div style="position:absolute;left:70px;right:70px;top:300px;display:flex;justify-content:space-around">{stat("82.7%","three-way accuracy<br>(139 of 168 claims)")}{stat("88.9%","precision when it says &ldquo;supported&rdquo;<br>(56 of 63)")}{stat("7 / 100","unsupported claims wrongly passed as supported")}</div>
<div class=card style="position:absolute;left:70px;right:70px;top:640px;font-size:22px;line-height:1.5;color:#4a463d"><b style="color:#1d1b16">Read this carefully.</b> 168 of 200 randomly sampled claims were scored; free-tier API limits stopped the rest, so the margin of error is about &plusmn;6 points. The small &ldquo;lite&rdquo; model was used. SciFact abstracts are short and clean, so long papers are likely harder. Reproduce it with <code>eval/run_scifact.py</code>.</div>''')
    # 7 mobile
    def phone(img, left, label):
        return f'''<div style="position:absolute;left:{left}px;top:150px;width:330px;height:715px;border-radius:44px;background:#15140f;padding:12px;box-shadow:0 28px 60px rgba(40,35,20,.35)">
<img src="data:image/png;base64,{b64(img)}" style="width:100%;height:100%;object-fit:cover;object-position:top;border-radius:34px;display:block"></div>
<div style="position:absolute;left:{left}px;top:880px;width:330px;text-align:center;font-size:21px;color:#6b665b">{label}</div>'''
    S["07-mobile"] = page(f'''<div class=top><span class="chip nu">Responsive</span><span class=step>07 / 07</span></div>
<div class=copy style="top:130px;width:560px"><h1 style="font-size:54px">Works on a phone</h1><p>The same draft, source and verdicts on a 390 px screen. Light and dark themes follow the device.</p></div>
{phone(raw / "m_input.png", 700, "Paste a draft and add sources")}{phone(raw / "m_results.png", 1080, "Verdicts with quoted evidence")}''')
    with sync_playwright() as p:
        b = p.chromium.launch(channel="msedge")
        pg = b.new_page(viewport={"width": 1500, "height": 1000})
        for name, html in S.items():
            pg.set_content(html, wait_until="load")
            pg.wait_for_timeout(150)
            pg.screenshot(path=str(out / f"{name}.png"))
            print(out / f"{name}.png")
        b.close()


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="http://localhost:8000")
    ap.add_argument("--out", default="../submission/gallery")
    a = ap.parse_args()
    out = Path(a.out)
    raw = out / "raw"
    capture(a.url, raw)
    build(raw, out)
