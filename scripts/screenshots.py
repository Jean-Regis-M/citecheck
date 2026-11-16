"""Capture real screenshots of the running app (dev tool; needs `pip install playwright` and Edge/Chrome)."""
import sys
from playwright.sync_api import sync_playwright

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://localhost:8000"
OUT = "docs/screenshots"

with sync_playwright() as p:
    b = p.chromium.launch(channel="msedge")
    pg = b.new_page(viewport={"width": 1280, "height": 860}, color_scheme="light")
    pg.goto(BASE)
    pg.screenshot(path=f"{OUT}/01-home.png")
    pg.click("#sample")
    pg.click("#run")
    try:
        pg.wait_for_selector(".res, .err", timeout=120000)
    except Exception:
        print("no result appeared")
    ok = pg.locator(".res").count() > 0
    print("results rendered:", ok, "| error:", pg.locator(".err").all_inner_texts())
    pg.screenshot(path=f"{OUT}/02-results.png" if ok else f"{OUT}/_error.png", full_page=True)
    if ok:
        m = b.new_page(viewport={"width": 390, "height": 844}, device_scale_factor=2, color_scheme="light")
        m.goto(BASE); m.click("#sample"); m.click("#run"); m.wait_for_selector(".res, .err", timeout=120000)
        m.screenshot(path=f"{OUT}/03-mobile.png", full_page=True)
    b.close()
