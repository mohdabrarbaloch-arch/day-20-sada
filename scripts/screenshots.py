"""Capture real screenshots of the running app with Playwright.

Logs in as the demo account, uploads the sample audio, waits for the
transcript, and shoots the landing page, the transcript view, and mobile.
"""

import asyncio
import sys
from pathlib import Path

from playwright.async_api import async_playwright

BASE = "http://127.0.0.1:8000"
OUT = Path(__file__).resolve().parent.parent / "screenshots"
AUDIO = Path("/workspace/audios/sada_demo_karachi/sada_demo_karachi.mp3")


async def main() -> int:
    OUT.mkdir(exist_ok=True)
    async with async_playwright() as p:
        browser = await p.chromium.launch()

        # ---------- desktop ----------
        ctx = await browser.new_context(
            viewport={"width": 1440, "height": 1000}, device_scale_factor=2
        )
        page = await ctx.new_page()
        await page.goto(BASE, wait_until="networkidle")
        await page.wait_for_timeout(600)
        await page.screenshot(path=OUT / "landing.png")
        print("landing.png")

        # sign in via the demo button
        await page.click("#demoBtn")
        await page.wait_for_timeout(1500)

        # upload the sample
        await page.set_input_files("#fileInput", str(AUDIO))
        # wait for the transcript to render
        await page.wait_for_selector(".seg", timeout=120_000)
        await page.wait_for_timeout(1200)
        await page.screenshot(path=OUT / "transcript.png")
        print("transcript.png")

        # A tighter shot clipped to the workspace element. scrollIntoView alone
        # produced a byte-identical copy of the full-page shot, so clip instead.
        # The box is padded so the header buttons are not cut off at the edge.
        await page.evaluate("document.getElementById('workspace').scrollIntoView()")
        await page.wait_for_timeout(500)
        box = await page.locator("#workspace").bounding_box()
        if box:
            pad = 56
            await page.screenshot(
                path=OUT / "transcript_detail.png",
                clip={
                    "x": max(0, box["x"] - pad),
                    "y": max(0, box["y"] - pad),
                    "width": min(1440 - max(0, box["x"] - pad), box["width"] + pad * 2),
                    "height": box["height"] + pad * 2,
                },
            )
        print("transcript_detail.png")

        # history view
        await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        await page.wait_for_timeout(600)
        await page.screenshot(path=OUT / "history.png")
        print("history.png")

        await ctx.close()

        # ---------- mobile ----------
        m = await browser.new_context(
            viewport={"width": 390, "height": 844},
            device_scale_factor=2,
            is_mobile=True,
            has_touch=True,
        )
        mp = await m.new_page()
        await mp.goto(BASE, wait_until="networkidle")
        await mp.wait_for_timeout(600)
        await mp.screenshot(path=OUT / "mobile.png")
        print("mobile.png")
        await m.close()

        await browser.close()
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
