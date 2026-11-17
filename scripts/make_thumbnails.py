"""Render the YouTube thumbnail (1280x720) and Devpost cover image (1500x1000) from the real app screenshot.

  python scripts/make_thumbnails.py [--out ../submission/thumbnails]
"""
import argparse
import base64
from pathlib import Path

from playwright.sync_api import sync_playwright

SHOT = Path(__file__).resolve().parent.parent / "docs" / "screenshots" / "02-results.png"

HTML = """<!doctype html><html><head><meta charset=utf-8><style>
*{box-sizing:border-box;margin:0}
body{width:%(w)dpx;height:%(h)dpx;background:#f7f4ee;font-family:'Segoe UI',system-ui,sans-serif;color:#1d1b16;overflow:hidden;position:relative}
.bgblob{position:absolute;right:-%(blob)dpx;top:-%(blob)dpx;width:%(bw)dpx;height:%(bw)dpx;border-radius:50%%;background:#1f4d3a}
.left{position:absolute;left:%(pad)dpx;top:0;bottom:0;width:%(lw)dpx;display:flex;flex-direction:column;justify-content:center}
.tag{font-size:%(tag)dpx;letter-spacing:.22em;text-transform:uppercase;color:#8a6100;font-weight:700;margin-bottom:%(g1)dpx}
h1{font:700 %(h1)dpx/1.02 Georgia,'Times New Roman',serif;letter-spacing:-2px}
h1 em{font-style:normal;color:#1f4d3a;text-decoration:underline;text-decoration-thickness:%(ul)dpx;text-underline-offset:%(uo)dpx;text-decoration-color:#c9a227}
.brand{font:700 %(brand)dpx Georgia,serif;margin-top:%(g2)dpx}.brand b{color:#1f4d3a}
.sub{font-size:%(sub)dpx;color:#6b665b;margin-top:10px}
.card{position:absolute;right:%(cr)dpx;top:%(ct)dpx;width:%(cw)dpx;height:%(ch)dpx;border-radius:26px;overflow:hidden;
box-shadow:0 30px 70px rgba(0,0,0,.35);border:6px solid #fffdf8;transform:rotate(2.5deg);background:#fffdf8}
.card img{position:absolute;left:%(ix)dpx;top:%(iy)dpx;width:%(iw)dpx}
.pills{position:absolute;right:%(pr)dpx;bottom:%(pb)dpx;display:flex;flex-direction:column;gap:14px;align-items:flex-end}
.p{font-weight:800;font-size:%(pill)dpx;padding:12px 26px;border-radius:99px;box-shadow:0 10px 26px rgba(0,0,0,.3);border:4px solid #fffdf8}
.ok{background:#e3f3ea;color:#1f7a4d}.pt{background:#fbf0d2;color:#8a6100}.bad{background:#fbe4e1;color:#a4261f}
</style></head><body>
<div class=bgblob></div>
<div class=left><div class=tag>SLAY HACKS 2026</div>
<h1>Does your source <em>actually</em> say that?</h1>
<div class=brand>Cite<b>Check</b></div><div class=sub>AI citation verifier &middot; quotes the proof</div></div>
<div class=card><img src="data:image/png;base64,%(img)s"></div>
<div class=pills><div class="p ok">Supported</div><div class="p pt">Partly supported</div><div class="p bad">Contradicted</div></div>
</body></html>"""

CFG = {
    "youtube-thumbnail.png": dict(w=1280, h=720, blob=220, bw=720, pad=60, lw=640, tag=22, g1=22, h1=76, ul=6, uo=8, brand=46, g2=30, sub=26,
                                  cr=70, ct=120, cw=520, ch=420, ix=-535, iy=-140, iw=1114, pr=90, pb=40, pill=30),
    "devpost-cover.png": dict(w=1500, h=1000, blob=260, bw=860, pad=80, lw=760, tag=26, g1=26, h1=92, ul=7, uo=10, brand=56, g2=40, sub=30,
                              cr=90, ct=170, cw=600, ch=520, ix=-615, iy=-165, iw=1280, pr=110, pb=70, pill=34),
}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="../submission/thumbnails")
    out = Path(ap.parse_args().out); out.mkdir(parents=True, exist_ok=True)
    img = base64.b64encode(SHOT.read_bytes()).decode()
    with sync_playwright() as p:
        b = p.chromium.launch(channel="msedge")
        for name, c in CFG.items():
            pg = b.new_page(viewport={"width": c["w"], "height": c["h"]})
            pg.set_content(HTML % {**c, "img": img}, wait_until="load")
            pg.screenshot(path=str(out / name))
            print(out / name)
        b.close()


if __name__ == "__main__":
    main()
