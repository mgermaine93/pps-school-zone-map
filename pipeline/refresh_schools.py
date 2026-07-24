"""
Fetches the current school list from the GuideK12 API and writes it to
data/schools.json in the preprocessed format used by scraper-v2.py.

Usage:
    python3 pipeline/refresh_schools.py
    python3 pipeline/refresh_schools.py --output data/schools.json
"""

from __future__ import annotations

import argparse
import asyncio
import json
import shutil
import sys
from datetime import datetime
from pathlib import Path
import phonenumbers
from phonenumbers import PhoneNumberFormat

import aiohttp

BASE = "https://app.guidek12.com/pittsburghpa/school_search/"


def _urls(year: str) -> tuple[str, str]:
    portal = f"{BASE}{year}/"
    return portal, f"{portal}api.json"


def fmt_time(value) -> str:
    """
    Parses a 24-hour time value and returns a formatted 12-hour string.

    Accepts either a bare "HH:MM" string or a single-element list containing
    one, the latter being the format GuideK12 returns for START_TIME and
    END_TIME attributes.  Falls back to returning the raw value as a string if
    parsing fails, so unexpected formats degrade gracefully rather than raising.

    Args:
        value: A "HH:MM" string or a list whose first element is such a string.

    Returns:
        A 12-hour formatted string such as "8:00 AM" or "3:30 PM", or the raw
        input stringified if the value cannot be parsed as a time.
    """
    raw = value[0] if isinstance(value, list) else value
    try:
        return datetime.strptime(str(raw).strip(), "%H:%M").strftime("%-I:%M %p")
    except ValueError:
        return str(raw)


def normalize(raw: list[dict]) -> list[dict]:
    """
    Filters and normalizes raw GuideK12 school dicts into the preprocessed
    format written to data/schools.json.

    Skips entries that lack an id or a usable name, and filters out BOARD and
    EC (early childhood) school types which are not relevant to the map.  Phone
    numbers are formatted to NANP national format via the phonenumbers library;
    unparseable numbers are stored as-is.  Start and end times are converted
    from 24-hour to 12-hour format via fmt_time().

    Accepts dicts in either GuideK12 API format (street_address / school_label
    / attr.SCHOOL_TYPE) or the preprocessed format (address / name / type),
    so the function works against both live API responses and existing
    schools.json files.

    Args:
        raw: List of school dicts from the GuideK12 'list_schools' API response
            or an existing schools.json file.

    Returns:
        A list of normalized school dicts sorted alphabetically by name, each
        containing: id, name, address, type, main_phone, start_time, end_time,
        and optionally lat and lng when coordinates are present in the source.
    """
    schools = []
    for s in raw:
        sid = s.get("id")
        if sid is None:
            continue

        name = s.get("school_label") or s.get("name") or ""
        if not name:
            continue

        attr = s.get("attr", {})
        type_list = attr.get("SCHOOL_TYPE") if isinstance(attr, dict) else None
        school_type = (type_list[0] if type_list else None) or s.get("type", "")

        # filter out board and early childhood data for now
        if school_type == "BOARD" or school_type == "EC":
            continue

        if s.get("street_address"):
            address = (
                f"{s['street_address']}, {s.get('city', '')}, "
                f"{s.get('state', '')} {s.get('zip', '')}"
            ).strip(", ")
        else:
            address = s.get("address", "")

        attr_data = s.get("attr") or {}
        start_time = fmt_time(attr_data["START_TIME"]) if "START_TIME" in attr_data else ""
        end_time   = fmt_time(attr_data["END_TIME"])   if "END_TIME"   in attr_data else ""

        raw_phone = str(attr_data.get("MAIN_PHONE", "")).strip()
        try:
            parsed = phonenumbers.parse(raw_phone, "US")
            main_phone = phonenumbers.format_number(parsed, PhoneNumberFormat.NATIONAL)
        except phonenumbers.NumberParseException:
            main_phone = raw_phone

        entry: dict = {
            "id": sid,
            "name": name,
            "address": address,
            "type": school_type,
            "main_phone": main_phone,
            "start_time": start_time,
            "end_time": end_time
        }

        lat = s.get("lat") or s.get("latitude")
        lng = s.get("lon") or s.get("lng") or s.get("longitude")
        if lat is not None:
            entry["lat"] = round(float(lat), 5)
        if lng is not None:
            entry["lng"] = round(float(lng), 5)

        schools.append(entry)

    return sorted(schools, key=lambda s: s["name"])


async def fetch(output_path: str, year: str = "current") -> None:
    """
    Fetches the school list for the given year from the GuideK12 API and
    writes it to disk.

    Performs a session-seeding GET to the GuideK12 portal first to acquire
    session cookies, then POSTs a 'list_schools' request to the JSON API.
    The raw response is passed through normalize() to strip irrelevant types
    and standardize field names.

    If the output file already exists it is backed up with a timestamp suffix
    before being overwritten, preserving the previous school list in case the
    new fetch is incomplete or the API returns unexpected data.

    Exits with code 1 via sys.exit() on a non-JSON response, an unexpected
    response shape, or an empty normalized result, so the GitHub Actions step
    fails loudly rather than silently writing an empty file.

    Args:
        output_path: Destination path for the normalized schools.json file.
            Parent directories are created automatically.
        year: GuideK12 school year slug, e.g. 'current' or '2027'.
            Determines which portal URL is used. Defaults to 'current'.
    """
    portal_url, api_url = _urls(year)
    headers = {
        "User-Agent": "Mozilla/5.0",
        "Content-Type": "application/json; charset=UTF-8",
        "Origin": "https://app.guidek12.com",
        "Referer": portal_url,
        "X-Requested-With": "XMLHttpRequest",
    }
    async with aiohttp.ClientSession(headers=headers) as session:
        async with session.get(portal_url) as resp:
            await resp.text()

        payload = {"mode": "list_schools"}
        async with session.post(api_url, json=payload) as resp:
            text = await resp.text()

        try:
            data = json.loads(text)
        except Exception:
            print(f"❌ Non-JSON response (HTTP {resp.status}):")
            print(text[:500])
            sys.exit(1)

    raw = data.get("result", data) if isinstance(data, dict) else data
    if not isinstance(raw, list):
        print("❌ Unexpected response shape:")
        print(json.dumps(data, indent=2)[:500])
        sys.exit(1)

    schools = normalize(raw)
    if not schools:
        print("❌ Response parsed but contained no usable schools.")
        sys.exit(1)

    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)

    if output.exists():
        backup_dir = Path("backups") / output.parent
        backup_dir.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_path = backup_dir / f"{output.stem}_{timestamp}{output.suffix}"
        shutil.copy2(output, backup_path)
        print(f"📁 Backed up existing file to {backup_path}")

    with open(output, "w", encoding="utf-8") as f:
        json.dump(schools, f, indent=2)

    print(f"✅ {len(schools)} schools written to {output_path}")


def main() -> None:
    """
    CLI entry point for the school list refresh.

    Parses the --output / -o argument (defaulting to data/schools.json) and
    runs fetch() via asyncio.run().  Intended for standalone use and debugging;
    the pipeline normally calls fetch() directly via step_refresh_schools().
    """
    parser = argparse.ArgumentParser(description="Refresh data/2027-schools.json from GuideK12")
    parser.add_argument("--output", "-o", default="data/2027-schools.json")
    parser.add_argument("--year", "-y", default="current",
                        help="GuideK12 school year slug (default: current). Use e.g. '2027' for future data.")
    args = parser.parse_args()
    asyncio.run(fetch(args.output, year=args.year))


if __name__ == "__main__":
    main()
