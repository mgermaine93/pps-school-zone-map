import json


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


def dedupe_by_address(records):
    seen = set()
    deduped = []

    for r in records:
        addr = r.get("address", "").strip().lower()

        if addr in seen:
            continue

        seen.add(addr)
        deduped.append(r)

    return deduped


# with open("./pittsburgh_addresses_2.json", "r") as f:
#     data = json.load(f)

# cleaned = dedupe_by_address(data)

# print(f"Original: {len(data)}")
# print(f"Deduped:  {len(cleaned)}")

# with open("pittsburgh_addresses_2_deduped.json", "w") as f:
#     json.dump(cleaned, f, indent=2)


import json
from collections import defaultdict


def group_addresses_by_schools(input_path):

    # Load your data
    with open(input_path, "r") as f:
        data = json.load(f)

    school_map = defaultdict(lambda: {
        "name": None,
        "points": []
    })

    for point in data:

        print(point)

        lat = point.get("lat")
        lng = point.get("lng")

        if lat is None or lng is None:
            continue

        for school in point.get("schools", []):
            school_id = school.get("id")

            # Initialize metadata once
            if school_map[school_id]["name"] is None:
                school_map[school_id]["name"] = school.get("name")

            # IMPORTANT: Geo formats typically use [lng, lat]
            school_map[school_id]["points"].append([lng, lat])

    # Optional: convert back to normal dict (useful for saving/exporting)
    school_map = dict(school_map)

    with open("schools_grouped.json", "w") as f:
        json.dump(school_map, f)


group_addresses_by_schools(input_path="./cleaned_new_pps_schools.json")