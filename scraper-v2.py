"""
Pittsburgh Public Schools — GuideK12 API Lookup (FAST VERSION)
=============================================================

Replaces browser scraping with direct GuideK12 API calls using lat/lng.

Requirements:
    pip install aiohttp

Usage:
    python scraper.py --input addresses.geojson --schools school-info.json --output results.json

Optional:
    --limit 10
    --concurrency 50
"""

import asyncio
import json
import argparse
import sys
import time
from pathlib import Path

import aiohttp

# ── Configuration ─────────────────────────────────────────────

API_URL = "https://app.guidek12.com/pittsburghpa/school_search/current/api.json"

# ── Address extraction ───────────────────────────────────────

def extract_addresses_from_geojson(path: str) -> list[dict]:
    with open(path, "r") as f:
        data = json.load(f)

    if isinstance(data, list):
        features = data
    elif isinstance(data, dict) and data.get("type") == "FeatureCollection":
        features = data.get("features", [])
    else:
        features = [data]

    results = []

    for feature in features:
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
        })

    print(f"✅ Loaded {len(results)} Pittsburgh addresses")
    return results

# ── Load school catalog ──────────────────────────────────────

def load_school_catalog(path: str) -> dict:
    with open(path, "r") as f:
        data = json.load(f)

    schools = data.get("result", data)

    school_map = {}

    for s in schools:
        school_map[s["id"]] = {
            "name": s.get("school_label"),
            "address": f"{s.get('street_address', '')}, {s.get('city', '')}, {s.get('state', '')} {s.get('zip', '')}",
            "type": (s.get("attr", {}).get("SCHOOL_TYPE") or [""])[0]
        }

    print(f"✅ Loaded {len(school_map)} schools into cache")
    return school_map

# ── API lookup ───────────────────────────────────────────────

async def lookup_by_point(session, lat, lng):
    payload = {
        "mode": "schools_spatial",
        "attr": {
            "SCHOOL_TYPE": {
                "values": ["ELEM", "K8", "MIDD", "HIGH", "ONLINE", "BOARD"],
                "mode": "or",
                "itemized": False
            }
        },
        "grades": [],
        "spatial_args": {
            "wkt": f"POINT({lng} {lat})",  # IMPORTANT: lng first
            "srid": 4326,
            "type": "point"
        },
        "zones": ["attendance", "early", "online", "board"]
    }

    HEADERS = {
        "Content-Type": "application/json; charset=UTF-8",
        "Origin": "https://app.guidek12.com",
        "Referer": "https://app.guidek12.com/pittsburghpa/school_search/current/",
        "X-Requested-With": "XMLHttpRequest",
        "User-Agent": "Mozilla/5.0",
    }

    print("POSTING TO:", API_URL)
    print(json.dumps(payload, indent=2))

    async with session.post(API_URL, json=payload, headers=HEADERS) as resp:
        text = await resp.text()

        try:
            data = json.loads(text)
            print(json.dumps(data, indent=2)[:500])
        except Exception:
            print("STATUS:", resp.status)
            print("URL:", resp.url)
            print("HEADERS:", dict(resp.headers))
            print("❌ Non-JSON response:")
            print(text[:500])
            return []
                
        return data.get("result", {}).get("school_results", [])

# ── Worker ───────────────────────────────────────────────────

async def worker(queue, session, school_map,
                 progress, total, output_path, file_lock):

    while True:
        try:
            record = queue.get_nowait()
        except asyncio.QueueEmpty:
            break

        lat = record.get("lat")
        lng = record.get("lng")

        if not lat or not lng:
            result = {"schools": [], "error": "Missing lat/lng"}
        else:
            try:
                raw_results = await lookup_by_point(session, lat, lng)

                schools = []

                for r in raw_results:
                    sid = r["id"]
                    meta = school_map.get(sid, {})

                    # Optional: skip board districts
                    if meta.get("type") == "BOARD":
                        continue

                    schools.append({
                        "id": sid,
                        "name": meta.get("name"),
                        "address": meta.get("address"),
                        "type": meta.get("type"),
                        "zones": r.get("zones", [])
                    })

                result = {"schools": schools, "error": None}

            except Exception as e:
                result = {"schools": [], "error": str(e)}

        # ── Progress ─────────────────────────────
        progress[0] += 1
        pct = progress[0] / total * 100

        school_names = "; ".join(s.get("name", "?") for s in result["schools"])
        status = school_names[:70] if school_names else "(no schools)"

        print(f"[{progress[0]:4d}/{total} {pct:5.1f}%] {record['address'][:50]} → {status}")

        # ── Output ──────────────────────────────
        record_out = {
            "id": record["id"],
            "address": record["address"],
            "lat": lat,
            "lng": lng,
            "school_count": len(result["schools"]),
            "schools": result["schools"],
            "error": result["error"] or ""
        }

        async with file_lock:
            with open(output_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(record_out) + "\n")

        queue.task_done()

# ── Runner ───────────────────────────────────────────────────

async def run(input_path: str, school_path: str, output_path: str,
              concurrency: int = 50, limit: int | None = None):

    records = extract_addresses_from_geojson(input_path)

    if limit:
        records = records[:limit]
        print(f"🔬 Limiting to first {limit} addresses")

    total = len(records)
    print(f"\n🔎 Looking up {total} addresses | concurrency={concurrency}\n")

    queue = asyncio.Queue()
    for r in records:
        queue.put_nowait(r)

    progress = [0]
    start = time.time()
    file_lock = asyncio.Lock()

    # clear output
    with open(output_path, "w"):
        pass

    school_map = load_school_catalog(school_path)

    HEADERS = {
        "User-Agent": "Mozilla/5.0",
        "Origin": "https://app.guidek12.com",
        "Referer": "https://app.guidek12.com/pittsburghpa/school_search/current/",
    }

    async with aiohttp.ClientSession(headers=HEADERS) as session:

        # Establish session cookies
        async with session.get(
            "https://app.guidek12.com/pittsburghpa/school_search/current/"
        ) as resp:
            await resp.text()

        workers = [
            asyncio.create_task(
                worker(
                    queue,
                    session,
                    school_map,
                    progress,
                    total,
                    output_path,
                    file_lock
                )
            )
            for _ in range(min(concurrency, total))
        ]

        await asyncio.gather(*workers)

    elapsed = time.time() - start

    print(f"\n✅ Done in {elapsed:.0f}s ({elapsed/max(total,1):.3f}s/address)")
    print(f"📄 Output: {output_path}")

# ── CLI ──────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Fast PPS school lookup using GuideK12 API"
    )
    parser.add_argument("--input", "-i", required=True)
    parser.add_argument("--schools", "-s", required=True,
                        help="Path to school-info.json")
    parser.add_argument("--output", "-o", default="new_pps_schools_2.json")
    parser.add_argument("--concurrency", "-c", type=int, default=50)
    parser.add_argument("--limit", "-l", type=int, default=None)

    args = parser.parse_args()

    if not Path(args.input).exists():
        print(f"❌ Input file not found: {args.input}")
        sys.exit(1)

    if not Path(args.schools).exists():
        print(f"❌ School file not found: {args.schools}")
        sys.exit(1)

    asyncio.run(
        run(
            args.input,
            args.schools,
            args.output,
            args.concurrency,
            args.limit
        )
    )

if __name__ == "__main__":
    main()