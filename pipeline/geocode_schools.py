"""
geocode_schools.py — run once from the project root:  python3 pipeline/geocode_schools.py

Reads data/schools.json, geocodes any school missing lat/lng via
Nominatim (OpenStreetMap), and writes the coordinates back in place.
Nominatim requires 1 req/s max; the script sleeps between requests.
"""
import json, time, urllib.request, urllib.parse, sys

SCHOOLS_FILE = 'data/schools.json'
USER_AGENT   = 'PPS-School-Zone-Tool/1.0 (educational project)'

schools = json.load(open(SCHOOLS_FILE))
needs_geocoding = [s for s in schools if s.get('lat') is None]
print(f'{len(needs_geocoding)} of {len(schools)} schools need geocoding…')

for i, school in enumerate(needs_geocoding):
    query = urllib.parse.quote(f"{school['address']}, Pittsburgh, PA, USA")
    url   = f'https://nominatim.openstreetmap.org/search?q={query}&format=json&limit=1'
    req   = urllib.request.Request(url, headers={'User-Agent': USER_AGENT})

    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            results = json.loads(resp.read())
        if results:
            school['lat'] = round(float(results[0]['lat']), 5)
            school['lng'] = round(float(results[0]['lon']), 5)
            print(f"  [{i+1}/{len(needs_geocoding)}] ✓  {school['name']}")
        else:
            print(f"  [{i+1}/{len(needs_geocoding)}] ✗  {school['name']} — not found", file=sys.stderr)
    except Exception as e:
        print(f"  [{i+1}/{len(needs_geocoding)}] ✗  {school['name']} — {e}", file=sys.stderr)

    time.sleep(1)  # Nominatim rate limit

json.dump(schools, open(SCHOOLS_FILE, 'w'), indent=2)
found = sum(1 for s in schools if s.get('lat') is not None)
print(f'\nDone. {found}/{len(schools)} schools have coordinates.')
