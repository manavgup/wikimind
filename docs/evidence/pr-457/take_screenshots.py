"""Take screenshots for PR #457 evidence."""

import asyncio
import json
import urllib.request
from pathlib import Path

from playwright.async_api import async_playwright

EVIDENCE_DIR = Path(__file__).parent
API_URL = "http://localhost:7842"


async def main():
    # Pre-fetch data
    req = urllib.request.Request(f"{API_URL}/api/wiki/share-links")
    req.add_header("Accept", "application/json")
    with urllib.request.urlopen(req) as resp:
        links = json.loads(resp.read().decode())

    token = links[0]["token"] if links else None
    if not token:
        print("No share links found!")
        return

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        ctx = await browser.new_context(viewport={"width": 1280, "height": 900})

        # Screenshot 1: Share links API
        page1 = await ctx.new_page()
        await page1.goto(f"{API_URL}/api/wiki/share-links", wait_until="load")
        await page1.wait_for_timeout(500)
        await page1.screenshot(path=str(EVIDENCE_DIR / "01-share-links-api.png"))
        await page1.close()

        # Screenshot 2: Public article (above fold)
        page2 = await ctx.new_page()
        await page2.goto(f"{API_URL}/public/articles/{token}", wait_until="load")
        await page2.wait_for_timeout(500)
        await page2.screenshot(path=str(EVIDENCE_DIR / "02-public-shared-article.png"))
        await page2.close()

        # Screenshot 3: Public article (full page)
        page3 = await ctx.new_page()
        await page3.goto(f"{API_URL}/public/articles/{token}", wait_until="load")
        await page3.wait_for_timeout(500)
        await page3.screenshot(
            path=str(EVIDENCE_DIR / "03-public-article-full.png"),
            full_page=True,
        )
        await page3.close()

        # Screenshot 4: Public article JSON
        page4 = await ctx.new_page()
        await page4.goto(f"{API_URL}/public/articles/{token}/json", wait_until="load")
        await page4.wait_for_timeout(500)
        await page4.screenshot(path=str(EVIDENCE_DIR / "04-public-article-json.png"))
        await page4.close()

        # Screenshot 5: Swagger docs for sharing endpoints
        page5 = await ctx.new_page()
        await page5.goto(f"{API_URL}/docs", wait_until="load")
        await page5.wait_for_timeout(3000)
        await page5.screenshot(path=str(EVIDENCE_DIR / "05-api-docs-sharing.png"))
        await page5.close()

        await browser.close()
        print(f"Done! Screenshots saved to {EVIDENCE_DIR}")


asyncio.run(main())
