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

from __future__ import annotations

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
    """
    Loads and filters Pittsburgh addresses from a GeoJSON or raw JSON file.

    Accepts three input shapes: a bare list of feature objects, a GeoJSON
    FeatureCollection dict, or a single feature object. Only records where
    the city field equals "CITY OF PITTSBURGH" and both house number and
    street name are present are included in the output.

    Args:
        path: Filesystem path to the input GeoJSON or JSON file.

    Returns:
        A list of dicts, each containing:
            id (any): Original feature identifier.
            address (str): Formatted string "NUMBER STREET, PITTSBURGH, STATE POSTCODE".
            lat (float | None): Latitude from the source data.
            lng (float | None): Longitude from the source data.
    """
    with open(path, "r") as f:
        data = json.load(f)

    if isinstance(data, list):
        features = data
    elif isinstance(data, dict) and data.get("type") == "FeatureCollection":
        features = data.get("features", [])
    else:
        features = [data]

    results = []
    seen_addresses: set[str] = set()

    for feature in features:
        props = feature.get("raw", feature)

        city = (props.get("city") or "").strip().upper()
        if city != "CITY OF PITTSBURGH":
            continue

        number = (props.get("number") or "").strip()
        street = (props.get("street") or "").strip()
        state = (props.get("region") or "PA").strip()
        postcode = (props.get("postcode") or "").strip()

        if not number or not street:
            continue

        address = f"{number} {street}, PITTSBURGH, {state} {postcode}"

        if address in seen_addresses:
            continue
        seen_addresses.add(address)

        results.append(
            {
                "id": feature.get("id"),
                "address": address,
                "lat": feature.get("lat"),
                "lng": feature.get("lng"),
            }
        )

    print(
        f"✅ Loaded {len(results)} Pittsburgh addresses ({len(features) - len(results)} duplicates skipped)"
    )
    return results


# ── Load school catalog ──────────────────────────────────────


def load_school_catalog(path: str) -> dict:
    """
    Builds a school metadata lookup table from a GuideK12 school-info JSON file.

    Accepts two formats: a bare JSON array (the preprocessed data/schools.json)
    or a GuideK12 raw response envelope ({"result": [...]}). Entries are indexed
    by school ID and field names are normalised across both formats.

    Args:
        path: Filesystem path to either a preprocessed schools.json or a
            raw GuideK12 school-info JSON file.

    Returns:
        A dict mapping school ID (int) to a metadata dict containing:
            name (str): Display name of the school.
            address (str): Full street address.
            type (str): School type code (e.g. 'ELEM', 'K8', 'MIDD', 'HIGH').
    """
    with open(path, "r") as f:
        data = json.load(f)

    # Accept a bare list (data/schools.json) or a {"result": [...]} envelope (GuideK12 raw)
    schools = data if isinstance(data, list) else data.get("result", [])

    school_map = {}

    for s in schools:
        # GuideK12 raw format uses street_address/school_label/attr.SCHOOL_TYPE;
        # preprocessed schools.json uses address/name/type directly
        if s.get("street_address"):
            address = f"{s.get('street_address', '')}, {s.get('city', '')}, {s.get('state', '')} {s.get('zip', '')}"
        else:
            address = s.get("address", "")

        school_map[s["id"]] = {
            "name": s.get("school_label") or s.get("name"),
            "address": address,
            "type": (s.get("attr", {}).get("SCHOOL_TYPE") or [s.get("type", "")])[0],
        }

    print(f"✅ Loaded {len(school_map)} schools into cache")
    return school_map


# ── API lookup ───────────────────────────────────────────────


async def lookup_by_point(session, lat, lng):
    """
    Queries the GuideK12 API for schools assigned to a geographic point.

    Sends a POST request with a WKT POINT geometry (longitude first, as
    required by the API's spatial_args format) requesting all school types
    across all zone types. Returns the list of raw school result objects
    from the API response.

    Args:
        session (aiohttp.ClientSession): Active HTTP session with required
            browser-like headers already set.
        lat (float): Latitude of the address point.
        lng (float): Longitude of the address point. Sent first in WKT format
            per the GeoJSON / WKT convention (x before y).

    Returns:
        list[dict]: Raw school result objects from the API, or an empty list
            if the response is missing, malformed, or non-JSON.
    """
    payload = {
        "mode": "schools_spatial",
        "attr": {
            "SCHOOL_TYPE": {
                "values": ["ELEM", "K8", "MIDD", "HIGH", "ONLINE", "BOARD"],
                "mode": "or",
                "itemized": False,
            }
        },
        "grades": [],
        "spatial_args": {
            "wkt": f"POINT({lng} {lat})",  # IMPORTANT: lng first
            "srid": 4326,
            "type": "point",
        },
        "zones": ["attendance", "early", "online", "board"],
    }

    HEADERS = {
        "Content-Type": "application/json; charset=UTF-8",
        "Origin": "https://app.guidek12.com",
        "Referer": "https://app.guidek12.com/pittsburghpa/school_search/current/",
        "X-Requested-With": "XMLHttpRequest",
        "User-Agent": "Mozilla/5.0",
    }

    async with session.post(API_URL, json=payload, headers=HEADERS) as resp:
        text = await resp.text()

        try:
            data = json.loads(text)
        except Exception:
            print("STATUS:", resp.status)
            print("URL:", resp.url)
            print("HEADERS:", dict(resp.headers))
            print("❌ Non-JSON response:")
            print(text[:500])
            return []

        return data.get("result", {}).get("school_results", [])


# ── Worker ───────────────────────────────────────────────────


async def worker(
    queue, session, school_map, progress, total, output_path, file_lock, is_first
):
    """
    Consumes address records from the queue and appends school lookup results to disk.

    Continuously dequeues records until the queue is empty. For each record,
    calls lookup_by_point, enriches raw API results using school_map metadata,
    skips BOARD-type entries, logs progress to stdout, and appends a JSON line
    to the output file under a file lock to prevent concurrent write corruption.

    Args:
        queue (asyncio.Queue): Queue of address record dicts to process.
        session (aiohttp.ClientSession): Shared HTTP session for API requests.
        school_map (dict): School ID → metadata dict from load_school_catalog.
        progress (list[int]): Single-element list used as a shared mutable counter
            across all concurrent workers.
        total (int): Total number of records, used to compute progress percentage.
        output_path (str): Path to the output NDJSON file.
        file_lock (asyncio.Lock): Lock that serializes writes to output_path.
    """
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
                    meta = school_map.get(sid)

                    if not meta or not meta.get("name"):
                        continue

                    if meta.get("type") == "BOARD":
                        continue

                    schools.append(
                        {
                            "id": sid,
                            "name": meta["name"],
                            "address": meta.get("address") or "",
                            "type": meta.get("type") or "",
                            "zones": r.get("zones", []),
                        }
                    )

                result = {"schools": schools, "error": None}

            except Exception as e:
                result = {"schools": [], "error": str(e)}

        # ── Progress ─────────────────────────────
        progress[0] += 1
        pct = progress[0] / total * 100

        school_names = "; ".join(s["name"] for s in result["schools"])
        status = school_names[:70] if school_names else "(no schools)"

        print(
            f"[{progress[0]:4d}/{total} {pct:5.1f}%] {record['address'][:50]} → {status}"
        )

        # ── Output ──────────────────────────────
        record_out = {
            "id": record["id"],
            "address": record["address"],
            "lat": lat,
            "lng": lng,
            "school_count": len(result["schools"]),
            "schools": result["schools"],
            "error": result["error"] or "",
        }

        async with file_lock:
            with open(output_path, "a", encoding="utf-8") as f:
                prefix = "\n  " if is_first[0] else ",\n  "
                f.write(prefix + json.dumps(record_out))
                is_first[0] = False

        queue.task_done()


# ── Runner ───────────────────────────────────────────────────


async def run(
    input_path: str,
    school_path: str,
    output_path: str,
    concurrency: int = 50,
    limit: int | None = None,
    slim_output_path: str | None = None,
):
    """
    Orchestrates the full address-to-school lookup pipeline.

    Loads addresses from the GeoJSON input, optionally caps the list, initializes
    the async queue and worker pool, establishes a browser-like HTTP session
    (including a cookie-seeding GET request to the GuideK12 portal), and runs
    all workers concurrently. Results are written incrementally to output_path
    as newline-delimited JSON so progress is preserved if the run is interrupted.

    Args:
        input_path (str): Path to the GeoJSON file containing address records.
        school_path (str): Path to the school-info JSON catalog file.
        output_path (str): Path where NDJSON output will be written (overwritten
            at the start of each run).
        concurrency (int): Maximum number of simultaneous API requests. Default 50.
        limit (int | None): If set, caps the number of addresses processed.
            Default None (process all).
    """
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
    is_first = [True]
    start = time.time()
    file_lock = asyncio.Lock()

    with open(output_path, "w", encoding="utf-8") as f:
        f.write("[")

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
                    file_lock,
                    is_first,
                )
            )
            for _ in range(min(concurrency, total))
        ]

        await asyncio.gather(*workers)

    with open(output_path, "a", encoding="utf-8") as f:
        f.write("\n]\n")

    elapsed = time.time() - start

    print(f"\n✅ Done in {elapsed:.0f}s ({elapsed/max(total,1):.3f}s/address)")
    print(f"📄 Output: {output_path}")

    if slim_output_path:
        write_slim(output_path, slim_output_path)


# ── Slim converter ───────────────────────────────────────────


def write_slim(input_path: str, output_path: str) -> None:
    """
    Converts the full scraper output into the compact slim JSON format consumed
    by build_binary.py.

    Filters out records with missing lat/lng or empty school lists, then
    de-duplicates school names into a shared lookup list so each address stores
    an integer index rather than repeating the full name string.  Zones are
    serialized as a comma-joined string (e.g. "attendance,early"); an empty
    zones list becomes an empty string.

    Output schema:
        {
          "schoolNames": ["School A", "School B", ...],
          "addresses": [
            {
              "id": ..., "address": ..., "lat": ..., "lng": ...,
              "schools": [[nameIdx, "TYPE", "zone1,zone2"], ...]
            },
            ...
          ]
        }

    Args:
        input_path: Path to the full JSON output from the scraper (an array of
            address records each containing a 'schools' list of dicts with
            name, type, and zones fields).
        output_path: Destination path for the slim JSON file.  Parent
            directories are created automatically.
    """
    with open(input_path, encoding="utf-8") as f:
        records = json.load(f)

    records = [
        r
        for r in records
        if r.get("lat") is not None and r.get("lng") is not None and r.get("schools")
    ]

    school_name_list: list[str] = []
    school_name_index: dict[str, int] = {}
    for r in records:
        for s in r["schools"]:
            name = s["name"]
            if name not in school_name_index:
                school_name_index[name] = len(school_name_list)
                school_name_list.append(name)

    addresses = [
        {
            "id": r["id"],
            "address": r["address"],
            "lat": round(r["lat"], 5),
            "lng": round(r["lng"], 5),
            "schools": [
                [school_name_index[s["name"]], s["type"], ",".join(s["zones"])]
                for s in r["schools"]
            ],
        }
        for r in records
    ]

    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump({"schoolNames": school_name_list, "addresses": addresses}, f)

    print(
        f"📦 Slim output: {output_path} ({len(addresses)} addresses, {len(school_name_list)} unique schools)"
    )


# ── CLI ──────────────────────────────────────────────────────


def main():
    """
    Parses command-line arguments and launches the async scraper pipeline.

    Validates that the input address file and school catalog both exist before
    starting. Exits with code 1 if either file is missing.

    CLI arguments:
        --input  / -i  (required) Path to the input GeoJSON address file.
        --schools / -s (required) Path to the GuideK12 school-info JSON catalog.
        --output / -o  Output NDJSON file path. Default: new_pps_schools_3.json.
        --concurrency / -c  Max concurrent API requests. Default: 50.
        --limit / -l   Cap on number of addresses to process. Default: no limit.
    """
    parser = argparse.ArgumentParser(
        description="Fast PPS school lookup using GuideK12 API"
    )
    parser.add_argument("--input", "-i", required=True)
    parser.add_argument(
        "--schools", "-s", required=True, help="Path to school-info.json"
    )
    parser.add_argument("--output", "-o", default="new_schools_files.json")
    parser.add_argument(
        "--slim-output",
        default="data/addresses_slim.json",
        help="Path for slim encoded output (default: data/addresses_slim.json). Pass empty string to skip.",
    )
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
            args.limit,
            args.slim_output or None,
        )
    )


if __name__ == "__main__":
    main()
