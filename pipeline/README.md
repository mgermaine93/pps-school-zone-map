# Pipeline

Contains the three Python scripts that make up the monthly data refresh pipeline. Each script can be run standalone via its own CLI, but in normal operation they are orchestrated in sequence by `main.py` in the project root.

## Scripts

| Script | Step | Description |
|---|---|---|
| `refresh_schools.py` | 1 | Fetches the current school list from the GuideK12 API and writes it to `data/schools.json`. |
| `scraper-v2.py` | 2 | Maps every Pittsburgh address to its assigned schools by POSTing each address's lat/lng to the GuideK12 spatial API. Writes `data/addresses_full.json` (full records) and `data/addresses_slim.json` (compact format). |
| `build_binary.py` | 3 | Encodes `data/addresses_slim.json` into the compact `data/addresses.bin` binary format consumed by the web app. |

## Running a single step

```bash
python3 pipeline/refresh_schools.py --output data/schools.json
python3 pipeline/build_binary.py --input data/addresses_slim.json --output data/addresses.bin
```

The scraper requires `--input`, `--schools`, and `--output` arguments; run `python3 pipeline/scraper-v2.py --help` for details.
