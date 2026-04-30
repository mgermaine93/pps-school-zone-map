"""
GuideK12 API Endpoint Discovery Tool
=====================================
Run this FIRST before the main scraper.
It opens a real Chromium browser, intercepts all network traffic,
and tells you exactly what API calls GuideK12 makes when you search.

This lets you:
  1. Confirm the API URL pattern
  2. Check what the JSON response looks like
  3. Update the scraper if needed

Usage:
    python discover_api.py
    
Then type a Pittsburgh address in the browser window that opens.
The terminal will print all matching API calls.
"""

import asyncio
import json
from playwright.async_api import async_playwright

GUIDEK12_URL = "https://app.guidek12.com/pittsburghpa/school_search/current/"
TEST_ADDRESS  = "4552 Winterburn Ave Pittsburgh PA 15207"


async def discover():
    print("🔍 GuideK12 API Discovery Tool")
    print("=" * 60)
    print(f"Opening: {GUIDEK12_URL}")
    print()

    intercepted = []

    async with async_playwright() as pw:
        # Launch NON-headless so you can watch it
        browser = await pw.chromium.launch(headless=False, slow_mo=500)
        context = await browser.new_context()
        page    = await context.new_page()

        async def log_request(request):
            url = request.url
            if "guidek12" in url and request.method in ("GET", "POST"):
                print(f"📤 REQUEST  {request.method} {url}")
                if request.method == "POST":
                    try:
                        body = request.post_data
                        if body:
                            print(f"   Body: {body[:200]}")
                    except Exception:
                        pass

        async def log_response(response):
            url = response.url
            if "guidek12" in url and response.status == 200:
                ct = response.headers.get("content-type", "")
                if "json" in ct or "javascript" in ct:
                    try:
                        body = await response.json()
                        print(f"\n✅ JSON RESPONSE from: {url}")
                        print(f"   Status: {response.status}")
                        print(f"   Body (first 800 chars):")
                        pretty = json.dumps(body, indent=2)[:800]
                        for line in pretty.split("\n"):
                            print(f"   {line}")
                        intercepted.append({"url": url, "body": body})
                    except Exception as e:
                        print(f"   (non-JSON response from {url}: {e})")

        page.on("request",  log_request)
        page.on("response", log_response)

        await page.goto(GUIDEK12_URL, wait_until="networkidle")

        print(f"\n⌨️  Now typing test address: {TEST_ADDRESS}")
        print("   Watch the terminal for intercepted API calls.\n")

        # Find and fill the search box
        selectors_to_try = [
            "input[placeholder*='ddress']",
            "input[type='search']",
            "input[aria-label*='ddress']",
            "input[class*='search']",
            "input",
        ]

        box = None
        for sel in selectors_to_try:
            try:
                await page.wait_for_selector(sel, timeout=3_000)
                box = page.locator(sel).first
                print(f"   Found input with selector: {sel}")
                break
            except Exception:
                continue

        if box:
            await box.click()
            await box.type(TEST_ADDRESS, delay=100)
            await page.wait_for_timeout(5_000)   # wait for results
        else:
            print("   ⚠️  Could not find input — please type manually in the browser")
            print("   Waiting 30s for you to interact...")
            await page.wait_for_timeout(30_000)

        print("\n" + "=" * 60)
        if intercepted:
            print(f"✅ Intercepted {len(intercepted)} JSON API call(s)")
            print("\n📋 API ENDPOINT SUMMARY:")
            for item in intercepted:
                print(f"   URL: {item['url']}")
            print("\n💡 Copy the URL pattern into the scraper.py GUIDEK12_URL area")
            print("   or update the response handler to match the JSON structure shown above.")
        else:
            print("❌ No JSON API calls intercepted.")
            print("   The app may render entirely server-side, or use WebSockets.")
            print("   Try inspecting Network tab in Chrome DevTools manually.")

        print("\nPress Ctrl+C or close the browser to exit.")
        try:
            await page.wait_for_timeout(60_000)
        except Exception:
            pass

        await browser.close()


if __name__ == "__main__":
    asyncio.run(discover())
