"""
Fetches the current school list from the GuideK12 API and writes it to
data/schools.json in the preprocessed format used by scraper-v2.py.

Usage:
    python3 pipeline/refresh_schools.py
    python3 pipeline/refresh_schools.py --output data/schools.json
"""

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

PORTAL_URL = "https://app.guidek12.com/pittsburghpa/school_search/current/"
API_URL    = "https://app.guidek12.com/pittsburghpa/school_search/current/api.json"

HEADERS = {
    "User-Agent": "Mozilla/5.0",
    "Content-Type": "application/json; charset=UTF-8",
    "Origin": "https://app.guidek12.com",
    "Referer": PORTAL_URL,
    "X-Requested-With": "XMLHttpRequest",
}


def fmt_time(value) -> str:
    raw = value[0] if isinstance(value, list) else value
    try:
        return datetime.strptime(str(raw).strip(), "%H:%M").strftime("%-I:%M %p")
    except ValueError:
        return str(raw)


def normalize(raw: list[dict]) -> list[dict]:
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


async def fetch(output_path: str) -> None:
    async with aiohttp.ClientSession(headers=HEADERS) as session:
        async with session.get(PORTAL_URL) as resp:
            await resp.text()

        payload = {"mode": "list_schools"}
        async with session.post(API_URL, json=payload) as resp:
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
    parser = argparse.ArgumentParser(description="Refresh data/schools.json from GuideK12")
    parser.add_argument("--output", "-o", default="data/schools.json")
    args = parser.parse_args()
    asyncio.run(fetch(args.output))


if __name__ == "__main__":
    main()
