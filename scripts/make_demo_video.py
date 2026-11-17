"""Record the CiteCheck demo video: live app + slides + neural narration + burned-in captions.

Dev tool (not part of the app). Needs: pip install playwright edge-tts, ffmpeg on PATH, Microsoft Edge.
Narration is synthesised with Microsoft's neural voices via edge-tts (the narration text is sent to that service).

  python scripts/make_demo_video.py [--url https://citecheck-p66j.onrender.com] [--out ../submission]
"""
from __future__ import annotations

import argparse
import asyncio
import re
import shutil
import subprocess
import time
from pathlib import Path

import edge_tts
import httpx
from playwright.async_api import async_playwright

VOICE = "en-US-AndrewNeural"
RATE = "-4%"
W, H = 1920, 1080

DRAFT = ("Transformers dispense with recurrence and rely entirely on attention mechanisms [1]. "
         "The model reached 28.4 BLEU on the WMT 2014 English-to-German task [1]. "
         "Transformers are cheaper to train than every earlier model on every task [1]. "
         "The Transformer is built on recurrent layers at its core [1].")
SOURCE = "https://arxiv.org/abs/1706.03762"

# (id, caption text). TTS text is derived with pronunciation fixes.
NARR = [
    ("title", "CiteCheck. Does your source actually say that? An AI citation verifier for student writers, built for SLAY HACKS 2026."),
    ("problem", "Students cite papers they have only skimmed, or only read the abstract of. The result is a sentence that sounds right, carries a citation, and is not what the source says. A finding from two experiments becomes a general law. Reference managers check formatting. Plagiarism tools check copying. Nobody checks whether the source really supports the sentence."),
    ("demo1", "This is CiteCheck, running live. I paste a draft where every claim carries a citation, and give it the source: the arXiv paper, Attention Is All You Need."),
    ("demo2", "CiteCheck fetches the paper, splits it into passages, and finds the ones closest to each claim. Then an AI model judges each claim against only those passages, and it has to quote its evidence."),
    ("demo3a", "The first two claims are supported, and each comes with the exact sentence from the paper."),
    ("demo3b", "The third says transformers are cheaper to train than every model, on every task. CiteCheck marks it partly supported, because the paper only shows this on two translation tasks."),
    ("demo3c", "And the fourth says the Transformer is built on recurrence. The paper says the opposite, so it is flagged as contradicted."),
    ("demo4", "Every verdict lists the passages the model saw, so you can check the evidence yourself."),
    ("how", "The AI does one job: judging whether a passage supports a claim. Everything around it is ordinary, testable code. A verdict is only shown if its quote appears word for word in the source. If it does not, CiteCheck says it can't verify. And if only an abstract was available, it never claims that the source fails to support you."),
    ("eval", "I tested the verifier on SciFact, a public benchmark. On 168 claims, accuracy was 83 percent with a small, fast model, and 7 out of 100 unsupported claims were wrongly approved. The sample is partial because of free tier limits, and I'm saying so up front."),
    ("close", "CiteCheck is open source, deployed, and free to try. It is a writing aid, not a judge: it shows its evidence, and it says when it can't tell. Thank you."),
]


def tts_text(s: str) -> str:
    for a, b in [("arXiv", "archive"), ("CiteCheck", "Cite Check"), ("SciFact", "Sigh Fact"),
                 ("SLAY HACKS", "Slay Hacks"), ("AI", "A I")]:
        s = s.replace(a, b)
    return s


CSS = """
*{box-sizing:border-box}html,body{margin:0;height:100%;background:#f7f4ee;color:#1d1b16;
font-family:system-ui,-apple-system,'Segoe UI',sans-serif}
.s{height:100vh;display:flex;flex-direction:column;justify-content:center;align-items:center;padding:0 140px;
animation:in .8s ease both;text-align:center}
@keyframes in{from{opacity:0;transform:translateY(14px)}to{opacity:1;transform:none}}
h1{font:600 150px/1 Georgia,serif;margin:0;letter-spacing:-3px}h1 b{color:#1f4d3a}
h2{font:600 72px/1.1 Georgia,serif;margin:0 0 50px}
.sub{font-size:44px;color:#6b665b;margin-top:30px}.tag{font-size:30px;letter-spacing:.2em;text-transform:uppercase;color:#8a6100;margin-top:70px}
.row{display:flex;gap:36px;justify-content:center;margin-top:10px}
.card{background:#fffdf8;border:2px solid #e2dccd;border-radius:22px;padding:38px 40px;width:520px;font-size:38px;line-height:1.35;
animation:in .7s ease both}
.card small{display:block;color:#6b665b;font-size:28px;margin-top:14px}
.foot{font:italic 46px Georgia,serif;margin-top:60px;color:#1f4d3a;animation:in .8s ease 3.2s both}
.flow{display:flex;align-items:center;gap:14px;margin:6px 0 46px}
.box{background:#fffdf8;border:2px solid #e2dccd;border-radius:18px;padding:24px 22px;font-size:30px;width:250px;animation:in .6s ease both}
.box i{display:block;font-style:normal;font-size:22px;color:#6b665b;margin-top:8px;letter-spacing:.06em;text-transform:uppercase}
.box.ai{background:#1f4d3a;color:#fff;border-color:#1f4d3a}.box.ai i{color:#cfe6da}
.arr{font-size:40px;color:#9a948a}
ul{list-style:none;padding:0;margin:0;font-size:38px;line-height:1.7;text-align:left}li{animation:in .7s ease both}
li:before{content:'';display:inline-block;width:14px;height:14px;background:#1f4d3a;border-radius:50%;margin-right:20px}
.big{font:600 120px/1 Georgia,serif;color:#1f4d3a}.lab{font-size:30px;color:#6b665b;margin-top:14px;max-width:460px}
.note{font-size:30px;color:#6b665b;margin-top:60px;max-width:1500px;animation:in .8s ease 2s both}
.link{font-size:52px;color:#1f4d3a;margin-top:26px;font-weight:600}
"""


def page(body: str) -> str:
    return f"<!doctype html><html><head><meta charset=utf-8><style>{CSS}</style></head><body>{body}</body></html>"


SLIDES = {
    "title": page('<div class="s"><h1>Cite<b>Check</b></h1><div class="sub">Does your source actually say that?</div>'
                  '<div class="sub" style="font-size:36px;margin-top:14px">An AI citation verifier for student writers</div>'
                  '<div class="tag">SLAY HACKS 2026</div></div>'),
    "problem": page('<div class="s"><h2>A sentence that sounds right, and is not what the source says</h2><div class="row">'
                    '<div class="card" style="animation-delay:.6s">A finding from <b>two experiments</b><small>written as a general law</small></div>'
                    '<div class="card" style="animation-delay:1.4s">A <b>correlation</b><small>written as a cause</small></div>'
                    '<div class="card" style="animation-delay:2.2s">A <b>number</b><small>from the wrong population</small></div></div>'
                    '<div class="foot">Reference managers check formatting. Plagiarism tools check copying.<br>Nobody checks support.</div></div>'),
    "how": page('<div class="s"><h2>The AI has one job. Code audits it.</h2><div class="flow">'
                '<div class="box" style="animation-delay:.2s">Find claims<i>code</i></div><div class="arr">→</div>'
                '<div class="box" style="animation-delay:.8s">Fetch sources<i>safe code</i></div><div class="arr">→</div>'
                '<div class="box" style="animation-delay:1.4s">Retrieve passages<i>BM25</i></div><div class="arr">→</div>'
                '<div class="box ai" style="animation-delay:2.0s">Judge claim<i>Gemini</i></div><div class="arr">→</div>'
                '<div class="box" style="animation-delay:2.6s">Verify quote<i>code</i></div></div>'
                '<ul><li style="animation-delay:3.4s">No verbatim quote in the source, no verdict</li>'
                '<li style="animation-delay:4.4s">Unsure or unreachable: it says can\'t verify</li>'
                '<li style="animation-delay:5.4s">Abstract only: it never says the source fails to support</li></ul></div>'),
    "eval": page('<div class="s"><h2>Measured on a public benchmark: SciFact</h2><div class="row" style="gap:90px">'
                 '<div><div class="big">82.7%</div><div class="lab">three-way accuracy<br>(139 of 168 claims)</div></div>'
                 '<div><div class="big">88.9%</div><div class="lab">precision when it says &ldquo;supported&rdquo;</div></div>'
                 '<div><div class="big">7 / 100</div><div class="lab">unsupported claims wrongly approved</div></div></div>'
                 '<div class="note">168 of 200 sampled claims scored (free-tier API limits stopped the rest) &middot; small &ldquo;lite&rdquo; model &middot; margin of error about &plusmn;6 points &middot; short abstracts are easier than long papers</div></div>'),
    "close": page('<div class="s"><h1 style="font-size:120px">Cite<b>Check</b></h1><div class="link">citecheck-p66j.onrender.com</div>'
                  '<div class="sub" style="font-size:38px">github.com/Jean-Regis-M/citecheck &middot; open source (MIT)</div>'
                  '<div class="foot" style="animation-delay:.8s">A writing aid, not a judge. Evidence on screen, or &ldquo;can&rsquo;t verify&rdquo;.</div></div>'),
}

CURSOR_JS = """
(() => {
  const mk = () => {
    if (document.getElementById('fc')) return;
    const c = document.createElement('div'); c.id = 'fc';
    c.style.cssText = 'position:fixed;left:-50px;top:-50px;width:34px;height:34px;z-index:2147483647;pointer-events:none;transition:transform .08s;filter:drop-shadow(0 3px 4px rgba(0,0,0,.35))';
    c.innerHTML = '<svg viewBox="0 0 24 24" width="34" height="34"><path d="M3 2l7 19 3-8 8-3z" fill="#fff" stroke="#111" stroke-width="1.6" stroke-linejoin="round"/></svg>';
    document.documentElement.appendChild(c);
    addEventListener('mousemove', e => { c.style.left = e.clientX + 'px'; c.style.top = e.clientY + 'px'; }, true);
    addEventListener('mousedown', e => { const r = document.createElement('div');
      r.style.cssText = `position:fixed;left:${e.clientX-26}px;top:${e.clientY-26}px;width:52px;height:52px;border-radius:50%;border:4px solid #1f4d3a;pointer-events:none;z-index:2147483646;opacity:.9;transition:all .5s`;
      document.documentElement.appendChild(r); requestAnimationFrame(() => { r.style.transform = 'scale(1.8)'; r.style.opacity = '0'; }); setTimeout(() => r.remove(), 600); }, true);
  };
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', mk); else mk();
})();
"""

DEMO_CSS = """
body{zoom:1.38}
.hl{outline:5px solid #1f4d3a;outline-offset:6px;border-radius:12px;transition:outline .3s}
#livepill{position:fixed;top:18px;right:22px;z-index:2147483640;background:#1f4d3a;color:#fff;font:600 24px system-ui;
padding:10px 22px;border-radius:99px;box-shadow:0 4px 14px rgba(0,0,0,.25)}
#livepill:before{content:'';display:inline-block;width:14px;height:14px;border-radius:50%;background:#7fe0a8;margin-right:12px}
"""


def run(cmd: list[str], cwd: Path | None = None) -> str:
    r = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True)
    if r.returncode:
        raise RuntimeError(f"{' '.join(cmd[:3])} failed:\n{r.stderr[-1500:]}")
    return r.stdout


def duration(p: Path) -> float:
    return float(run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(p)]).strip())


async def synth(build: Path) -> dict[str, float]:
    durs = {}
    for sid, text in NARR:
        f = build / f"{sid}.mp3"
        for attempt in range(6):
            try:
                await edge_tts.Communicate(tts_text(text), VOICE, rate=RATE).save(str(f))
                break
            except edge_tts.exceptions.NoAudioReceived:
                await asyncio.sleep(1.5 * (attempt + 1))
        else:
            raise RuntimeError(f"speech synthesis failed for {sid}")
        durs[sid] = duration(f)
    return durs


async def glide(pg, x: float, y: float, steps: int = 30):
    await pg.mouse.move(x, y, steps=steps)


async def center(pg, loc):
    b = await loc.bounding_box()
    return b["x"] + b["width"] / 2, b["y"] + b["height"] / 2


async def move_click(pg, loc):
    await loc.scroll_into_view_if_needed()
    x, y = await center(pg, loc)
    await glide(pg, x, y)
    await asyncio.sleep(0.25)
    await loc.click()


async def record(build: Path, url: str, durs: dict[str, float]):
    starts: dict[str, float] = {}
    async with async_playwright() as p:
        br = await p.chromium.launch(channel="msedge")
        ctx = await br.new_context(viewport={"width": W, "height": H}, record_video_dir=str(build / "raw"),
                                   record_video_size={"width": W, "height": H}, color_scheme="light")
        await ctx.add_init_script(CURSOR_JS)
        t0 = time.monotonic()
        pg = await ctx.new_page()

        def now(): return time.monotonic() - t0

        def speak(k, pad=0.7):
            starts[k] = now()
            return starts[k] + durs[k] + pad

        async def until(t):
            if t > now():
                await asyncio.sleep(t - now())

        async def slide(k):
            await pg.set_content(SLIDES[k], wait_until="load")
            await pg.mouse.move(-100, -100)

        e = speak("title", 1.0); await slide("title"); await until(e)
        e = speak("problem", 1.2); await slide("problem"); await until(e)

        await pg.goto(url, wait_until="networkidle")
        await pg.add_style_tag(content=DEMO_CSS)
        await pg.evaluate("document.body.insertAdjacentHTML('beforeend','<div id=livepill>LIVE &middot; citecheck-p66j.onrender.com</div>')")
        await pg.mouse.move(W / 2, 200)
        e = speak("demo1", 1.0)
        await pg.evaluate("document.getElementById('draft').spellcheck=false")
        draft = pg.locator("#draft")
        await move_click(pg, draft)
        await draft.type(DRAFT, delay=14)
        lab = pg.locator(".src input").first
        await move_click(pg, lab); await lab.type("1", delay=80)
        val = pg.locator(".src textarea").first
        await move_click(pg, val); await val.type(SOURCE, delay=35)
        await until(e)
        await pg.evaluate("document.getElementById('livepill')?.remove()")

        e = speak("demo2", 0.6)
        btn = pg.locator("#run")
        await move_click(pg, btn)
        await pg.wait_for_selector(".res", timeout=150000)
        await until(e)

        async def hl(i):
            await pg.evaluate("""i=>{document.querySelectorAll('.res').forEach(r=>r.classList.remove('hl'));
              const r=document.querySelectorAll('.res')[i]; r.classList.add('hl'); r.scrollIntoView({block:'center',behavior:'smooth'});}""", i)

        e = speak("demo3a", 0.5); await hl(0); await asyncio.sleep(durs["demo3a"] * 0.5); await hl(1); await until(e)
        e = speak("demo3b", 0.5); await hl(2); await until(e)
        e = speak("demo3c", 0.5); await hl(3); await until(e)
        e = speak("demo4", 0.9)
        summ = pg.locator(".res").nth(3).locator("summary")
        await move_click(pg, summ); await until(e)

        e = speak("how", 1.0); await slide("how"); await until(e)
        e = speak("eval", 1.0); await slide("eval"); await until(e)
        e = speak("close", 2.0); await slide("close"); await until(e)
        await ctx.close()
        raw = await pg.video.path()
        await br.close()
    return starts, Path(raw)


def srt_time(t: float) -> str:
    h, rem = divmod(max(t, 0), 3600); m, s = divmod(rem, 60)
    return f"{int(h):02d}:{int(m):02d}:{int(s):02d},{int((s - int(s)) * 1000):03d}"


def build_srt(build: Path, starts, durs):
    out, n = [], 1
    for sid, text in NARR:
        parts = [x for x in re.split(r"(?<=[.!?])\s+", text) if x]
        total = sum(len(x) for x in parts)
        t = starts[sid]
        for x in parts:
            d = durs[sid] * len(x) / total
            out.append(f"{n}\n{srt_time(t)} --> {srt_time(t + d)}\n{x}\n")
            n += 1; t += d
    (build / "captions.srt").write_text("\n".join(out), encoding="utf-8")


def assemble(build: Path, starts, durs, raw: Path, final: Path, sync: float):
    inputs, filt, labels = [], [], []
    for i, (sid, _) in enumerate(NARR):
        inputs += ["-i", f"{sid}.mp3"]
        ms = int((starts[sid] + sync) * 1000)
        filt.append(f"[{i}:a]adelay={ms}|{ms}[a{i}]"); labels.append(f"[a{i}]")
    filt.append("".join(labels) + f"amix=inputs={len(NARR)}:normalize=0,highpass=f=70,lowpass=f=15000,"
                "acompressor=threshold=-18dB:ratio=3:attack=10:release=120,loudnorm=I=-16:TP=-1.5:LRA=9[aout]")
    run(["ffmpeg", "-y", *inputs, "-filter_complex", ";".join(filt), "-map", "[aout]", "-c:a", "aac", "-b:a", "192k", "narration.m4a"], cwd=build)
    shutil.copy(raw, build / "raw.webm")
    style = "FontName=Segoe UI,Fontsize=11,Bold=1,PrimaryColour=&HFFFFFF&,OutlineColour=&H00000000&,BorderStyle=1,Outline=2.2,Shadow=1,MarginV=26"
    run(["ffmpeg", "-y", "-i", "raw.webm", "-i", "narration.m4a", "-vf", f"subtitles=captions.srt:force_style='{style}',format=yuv420p",
         "-c:v", "libx264", "-crf", "18", "-preset", "medium", "-r", "30", "-c:a", "copy", "-shortest",
         "-movflags", "+faststart", str(final.resolve())], cwd=build)


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="https://citecheck-p66j.onrender.com")
    ap.add_argument("--out", default="../submission")
    ap.add_argument("--sync", type=float, default=-0.5, help="seconds to shift narration+captions relative to the script clock (video starts ~0.5 s before the first clock reading)")
    a = ap.parse_args()
    out = Path(a.out); build = out / "video_build"
    if build.exists():
        shutil.rmtree(build)
    (build / "raw").mkdir(parents=True)
    async with httpx.AsyncClient(timeout=90) as c:  # wake the free host before recording
        await c.get(a.url.rstrip("/") + "/api/health")
    durs = await synth(build)
    starts, raw = await record(build, a.url, durs)
    starts = {k: max(0.0, v + a.sync) for k, v in starts.items()}
    build_srt(build, starts, durs)
    final = out / "CiteCheck-demo.mp4"
    assemble(build, starts, durs, raw, final, 0.0)
    shutil.copy(build / "captions.srt", out / "CiteCheck-demo.srt")
    print("done:", final, f"{duration(final):.1f}s")


if __name__ == "__main__":
    asyncio.run(main())
