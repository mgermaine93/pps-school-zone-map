"""
Pittsburgh Public Schools — GuideK12 Address Lookup Scraper
============================================================
Reads addresses from a GeoJSON file, looks up each one on the GuideK12
Pittsburgh school search site, and writes results to a CSV.

Requirements:
    pip install playwright asyncio aiofiles
    python -m playwright install chromium

Usage:
    python scraper.py --input addresses.geojson --output results.csv

    # Optionally limit how many addresses to process (for testing):
    python scraper.py --input addresses.geojson --output results.csv --limit 10

    # Adjust concurrency (default 3 parallel browsers — be polite):
    python scraper.py --input addresses.geojson --output results.csv --concurrency 2
"""

import asyncio
import os
import csv
import random
import json
import argparse
import sys
import time
from pathlib import Path
from playwright.async_api import async_playwright, TimeoutError as PWTimeout

# ── Configuration ──────────────────────────────────────────────────────────────

GUIDEK12_URL = "https://app.guidek12.com/pittsburghpa/school_search/current/"

# CSS selectors — these may need updating if GuideK12 changes their UI.
# Open the site in DevTools and inspect if things break.
ADDRESS_INPUT_SELECTOR  = "input[placeholder*='ddress'], input[type='search'], input[aria-label*='ddress']"
RESULTS_SELECTOR        = ".school-result, .school-card, [class*='school'], [class*='result']"
SCHOOL_NAME_SELECTOR    = "h2, h3, h4, .school-name, [class*='name'], strong"
NO_RESULTS_SELECTOR     = "[class*='no-result'], [class*='empty'], [class*='not-found']"

SEARCH_TIMEOUT_MS   = 15_000   # max ms to wait for results after typing
RESULTS_SETTLE_MS   = 2_500    # ms to wait after results appear for them to fully load
RETRY_ATTEMPTS      = 3        # retries per address on transient failures
RETRY_DELAY_S       = 5        # seconds between retries

# ── Address extraction from GeoJSON ───────────────────────────────────────────

def extract_addresses_from_geojson(path: str) -> list[dict]:
    with open(path, "r") as f:
        data = json.load(f)

    # If it's already a list (your case)
    if isinstance(data, list):
        features = data
    # If it's still GeoJSON
    elif isinstance(data, dict) and data.get("type") == "FeatureCollection":
        features = data.get("features", [])
    else:
        features = [data]

    results = []

    for i, feature in enumerate(features):
        props = feature.get("raw", feature)

        city = (props.get("city") or "").strip().upper()
        if city != "CITY OF PITTSBURGH":
            continue

        number   = (props.get("number") or "").strip()
        street   = (props.get("street") or "").strip()
        state    = (props.get("region") or "PA").strip()
        postcode = (props.get("postcode") or "").strip()

        if not number or not street:
            continue

        address = f"{number} {street}, PITTSBURGH, {state} {postcode}"

        results.append({
            "id": feature.get("id"),
            "address": address,
            "lat": feature.get("lat"),
            "lng": feature.get("lng"),
            "raw": props
        })

    print(f"✅ Loaded {len(results)} Pittsburgh addresses")
    return results


async def lookup_address(page, address: str) -> dict:
    try:
        # ── 1. Focus + clear search box ─────────────────────────────
        search = page.locator("input[placeholder*='ddress']").first
        await asyncio.sleep(random.uniform(0.2, 0.8))
        await search.click()
        await search.fill("")
        await asyncio.sleep(random.uniform(0.2, 0.6))
        await search.type(address, delay=random.randint(40, 90))

        # Use simplified address (critical!)
        simple = address.split(",")[0]
        await search.type(simple, delay=50)

        # ── 2. Wait for autocomplete dropdown ──────────────────────
        result_selector = ".search_result_container .search_result"

        try:
            await page.wait_for_selector(result_selector, timeout=8000)
        except:
            return {"schools": [], "error": "No autocomplete results"}

        # ── 3. Click first suggestion ──────────────────────────────
        await page.locator(result_selector).first.click()

        # ── 4. Wait for school cards to render ─────────────────────
        try:
            await page.wait_for_selector(".school_info", timeout=10000)
        except:
            return {"schools": [], "error": "No school results rendered"}

        await page.wait_for_timeout(800)

        # ── 5. Scrape DOM ─────────────────────────────────────────
        return await scrape_school_cards(page)

    except Exception as e:
        return {"schools": [], "error": str(e)}


async def scrape_school_cards(page):

    schools = []

    try:
        # ── 1. Wait for the school list container ───────────────────
        await page.wait_for_selector(".school_list", timeout=10000)

        # ── 2. Wait specifically for visible assigned schools ───────
        await page.wait_for_selector(
            ".school_list .school.assigned.visible",
            timeout=10000
        )

        await page.wait_for_timeout(500)  # allow DOM to settle

    except PWTimeout:
        return {"schools": [], "error": "No visible assigned schools found"}

    # ── 3. Select ONLY the schools we care about ────────────────────
    cards = page.locator(".school_list .school.assigned.visible")
    count = await cards.count()

    for i in range(count):
        card = cards.nth(i)
        school = {}

        # ── Name ─────────────────────────────────────────────
        try:
            school["name"] = (
                await card.locator(".label_link, .school-name, h3, h4").first.inner_text()
            ).strip()
        except:
            school["name"] = "Unknown"

        # ── Address ──────────────────────────────────────────
        try:
            lines = await card.locator(".address_line").all_inner_texts()
            print(lines)
            school["address"] = " ".join(l.strip() for l in lines)
        except:
            school["address"] = ""

        # ── Assignment label (e.g., "Assigned school") ────────
        try:
            school["assignment"] = (
                await card.locator(".assigned_text").inner_text()
            ).strip()
        except:
            school["assignment"] = ""

        # ── Drive time ───────────────────────────────────────
        try:
            school["drive_time"] = (
                await card.locator(".drive_time").inner_text()
            ).strip()
        except:
            school["drive_time"] = ""

        # ── Drive distance ───────────────────────────────────
        try:
            school["drive_distance"] = (
                await card.locator(".drive_distance").inner_text()
            ).strip()
        except:
            school["drive_distance"] = ""

        schools.append(school)

    return {"schools": schools, "error": None}


async def scrape_dom_results(page, address: str) -> dict:
    """Fallback: read school names directly from the rendered HTML."""
    try:
        # Wait for results or no-results message
        await page.wait_for_selector(
            f"{RESULTS_SELECTOR}, {NO_RESULTS_SELECTOR}",
            timeout=SEARCH_TIMEOUT_MS
        )
        await page.wait_for_timeout(RESULTS_SETTLE_MS)
    except PWTimeout:
        return {"schools": [], "error": "Timed out waiting for results"}

    # Check for no-results
    no_results = await page.locator(NO_RESULTS_SELECTOR).count()
    if no_results > 0:
        return {"schools": [], "error": None}

    # Scrape all school result cards
    cards = page.locator(RESULTS_SELECTOR)
    count = await cards.count()
    schools = []

    for i in range(count):
        card = cards.nth(i)

        # Try to get the school name
        name_el = card.locator(SCHOOL_NAME_SELECTOR).first
        try:
            name = (await name_el.inner_text()).strip()
        except Exception:
            name = f"School {i+1}"

        # Try to get extra metadata (grade levels, type, etc.)
        full_text = (await card.inner_text()).strip()
        schools.append({"name": name, "details": full_text})

    return {"schools": schools, "error": None}


def parse_api_response(data: dict) -> dict:
    """
    Parse GuideK12's JSON API response.
    The schema varies slightly by district; this handles the common patterns.
    """
    schools = []

    # Pattern A: {"schools": [{name: ..., grades: ...}, ...]}
    if isinstance(data.get("schools"), list):
        for s in data["schools"]:
            schools.append({
                "name":   s.get("name") or s.get("school_name") or str(s),
                "type":   s.get("school_type") or s.get("type", ""),
                "grades": s.get("grades") or s.get("grade_range") or s.get("grades_served", ""),
                "phone":  s.get("phone") or s.get("phone_number", ""),
            })
        return {"schools": schools, "error": None}

    # Pattern B: {"results": [...]}
    if isinstance(data.get("results"), list):
        for s in data["results"]:
            schools.append({
                "name":   s.get("name") or s.get("school", str(s)),
                "type":   s.get("type", ""),
                "grades": s.get("grades", ""),
            })
        return {"schools": schools, "error": None}

    # Pattern C: flat list at root
    if isinstance(data, list):
        for s in data:
            schools.append({
                "name":   s.get("name") or s.get("school_name") or str(s),
                "type":   s.get("type", ""),
                "grades": s.get("grades", ""),
            })
        return {"schools": schools, "error": None}

    # Unknown schema — store raw for manual inspection
    return {"schools": [], "error": None, "raw_api": json.dumps(data)[:500]}


async def parse_school_dom(page) -> dict:
    """
    Extract schools directly from rendered GuideK12 results DOM.
    """

    try:
        await page.wait_for_selector(".school_list .school", timeout=15000)
        await page.wait_for_timeout(1500)
    except PWTimeout:
        return {"schools": [], "error": "No school results rendered"}

    cards = page.locator(".school_list .school")
    count = await cards.count()

    schools = []

    for i in range(count):
        card = cards.nth(i)

        # school name
        try:
            name = await card.locator(".label_link").inner_text()
        except:
            name = "Unknown"

        # address lines
        address_lines = await card.locator(".address_line").all_inner_texts()

        # optional travel stats
        try:
            drive_time = await card.locator(".drive_time").inner_text()
        except:
            drive_time = ""

        try:
            drive_distance = await card.locator(".drive_distance").inner_text()
        except:
            drive_distance = ""

        schools.append({
            "name": name.strip(),
            "address": " ".join(address_lines).strip(),
            "drive_time": drive_time,
            "drive_distance": drive_distance
        })

    return {"schools": schools, "error": None}


async def worker(browser, queue: asyncio.Queue, results: list,
                 progress: list, total: int, output_path: str,
                 file_lock: asyncio.Lock):

    page = await browser.new_page()

    await page.goto(GUIDEK12_URL, wait_until="networkidle", timeout=30000)

    print("Loaded URL:", page.url)
    print("Page title:", await page.title())

    try:
        await page.wait_for_selector(ADDRESS_INPUT_SELECTOR, timeout=15000)
    except PWTimeout:
        print("❌ Search input never appeared — page likely didn't load correctly")
        await page.close()
        return

    await page.wait_for_timeout(1000)

    try:
        while True:
            try:
                record = queue.get_nowait()
            except asyncio.QueueEmpty:
                break

            address = record["address"]
            simple_address = address.split(",")[0].strip()

            result = None
            last_error = None

            for attempt in range(1, RETRY_ATTEMPTS + 1):
                try:
                    search = page.locator(ADDRESS_INPUT_SELECTOR).first
                    await search.click()
                    await search.fill("")
                    await page.wait_for_timeout(200)

                    await search.type(simple_address, delay=50)

                    result_selector = ".search_result_container .search_result"

                    await page.wait_for_selector(result_selector, timeout=8000)

                    await page.locator(result_selector).first.click()

                    await page.wait_for_selector(".school_info", timeout=10000)

                    result = await scrape_school_cards(page)
                    await page.wait_for_timeout(800)

                    break

                except Exception as e:
                    last_error = str(e)

                    if attempt < RETRY_ATTEMPTS:
                        await asyncio.sleep(RETRY_DELAY_S)
                    else:
                        result = {
                            "schools": [],
                            "error": f"Failed after {RETRY_ATTEMPTS} attempts: {last_error}"
                        }

            progress[0] += 1
            pct = progress[0] / total * 100

            school_names = "; ".join(
                s.get("name", "?") for s in result.get("schools", [])
            )
            err = result.get("error")

            if err:
                status = f"ERROR: {err[:60]}"
            elif school_names:
                status = f"→ {school_names[:70]}"
            else:
                status = "(no schools)"

            print(f"  [{progress[0]:4d}/{total}  {pct:5.1f}%]  {address[:60]:<60s}  {status}")

            # ── LIVE NDJSON WRITE ───────────────────────────────
            record_out = {
                "id": record["id"],
                "address": address,
                "lat": record.get("lat", ""),
                "lng": record.get("lng", ""),
                "school_count": len(result.get("schools", [])),
                "schools": result.get("schools", []),
                "error": err or ""
            }

            async with file_lock:
                with open(output_path, "a", encoding="utf-8") as f:
                    f.write(json.dumps(record_out) + "\n")
                    f.flush()

            queue.task_done()

            # human-like delay
            await asyncio.sleep(random.uniform(1.0, 3.5))

            # periodic refresh
            if progress[0] % 200 == 0:
                print("🔄 Refreshing page...")
                await page.goto(GUIDEK12_URL, wait_until="networkidle")
                await page.wait_for_selector(ADDRESS_INPUT_SELECTOR)

    finally:
        await page.close()


async def run(input_path: str, output_path: str,
              concurrency: int = 8, limit: int | None = None):

    # ── Load data ─────────────────────────────────────────────
    with open(input_path, "r") as f:
        records = json.load(f)

    if not isinstance(records, list):
        raise ValueError("Input JSON must be a list of records")

    if limit:
        records = records[:limit]
        print(f"🔬 Limiting to first {limit} addresses")

    total = len(records)
    print(f"\n🔎 Looking up {total} addresses | concurrency={concurrency}\n")

    # ── Queue ────────────────────────────────────────────────
    queue = asyncio.Queue()
    for r in records:
        if "address" not in r:
            continue
        queue.put_nowait(r)

    # ── Shared state ─────────────────────────────────────────
    results = []
    progress = [0]
    start = time.time()

    # ── FILE LOCK + OUTPUT INIT ──────────────────────────────
    file_lock = asyncio.Lock()

    with open(output_path, "w", encoding="utf-8") as f:
        f.write("")  # truncate file (NDJSON format)

    # ── Playwright ───────────────────────────────────────────
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=False)

        try:
            workers = [
                asyncio.create_task(
                    worker(
                        browser,
                        queue,
                        results,
                        progress,
                        total,
                        output_path,
                        file_lock
                    )
                )
                for _ in range(min(concurrency, total))
            ]

            await asyncio.gather(*workers)

        finally:
            await browser.close()

    # ── Summary ─────────────────────────────────────────────
    elapsed = time.time() - start
    print(f"\n✅ Done in {elapsed:.0f}s ({elapsed/max(total,1):.2f}s/address)")
    print(f"\n📄 Live NDJSON written to: {output_path}")

    errors = sum(1 for r in results if r.get("error"))
    no_schools = sum(
        1 for r in results
        if r.get("school_count") == 0 and not r.get("error")
    )

    print(f"\n   Total:         {len(results)}")
    print(f"   With schools:  {len(results) - errors - no_schools}")
    print(f"   No schools:    {no_schools}")
    print(f"   Errors:        {errors}")


def main():
    parser = argparse.ArgumentParser(
        description="Look up Pittsburgh Public Schools for a list of GeoJSON addresses."
    )
    parser.add_argument("--input",  "-i", required=True,  help="Path to input .geojson file")
    parser.add_argument("--output", "-o", default="pps_schools.json", help="Output CSV path (default: pps_schools.json)")
    parser.add_argument("--concurrency", "-c", type=int, default=8,
                        help="Parallel browsers (default: 8 — be polite!)")
    parser.add_argument("--limit", "-l", type=int, default=None,
                        help="Only process the first N addresses (for testing)")
    args = parser.parse_args()

    if not Path(args.input).exists():
        print(f"❌ Input file not found: {args.input}")
        sys.exit(1)

    asyncio.run(run(args.input, args.output, args.concurrency, args.limit))


if __name__ == "__main__":
    main()