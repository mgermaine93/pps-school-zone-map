# Pipeline

Contains the three Python scripts that make up the monthly data refresh pipeline. Each script can be run standalone via its own CLI, but in normal operation they are orchestrated in sequence by `main.py` in the project root.

## Scripts

| Script | Step | Description |
|---|---|---|
| `refresh_schools.py` | 1 | Fetches the current school list from the GuideK12 API and writes it to `data/schools.json`. |
| `scraper-v2.py` | 2 | Maps every Pittsburgh address to its assigned schools by POSTing each address's lat/lng to the GuideK12 spatial API. Writes `data/addresses_full.json` (full records) and `data/addresses_slim.json` (compact format). |
| `build_binary.py` | 3 | Encodes `data/addresses_slim.json` into the compact `data/addresses.bin` binary format consumed by the web app. |

## Running locally

### Prerequisites

- Python 3.9 or later
- pip

### Setup

```bash
git clone https://github.com/mgermaine93/pps-school-zone-map.git
cd pps-school-zone-map
python3 -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate
pip install -r requirements.txt
```

### Running the full pipeline

The raw Pittsburgh address file (`data/pittsburgh_addresses.json`) is included in the repository, so no separate data download is needed to get started. Set `SKIP_GIT_PUSH=1` to prevent the pipeline from committing and pushing to the remote after it finishes — you almost certainly want this when running locally.

```bash
SKIP_GIT_PUSH=1 python3 main.py
```

On Windows (Command Prompt):

```bat
set SKIP_GIT_PUSH=1 && python main.py
```

Pipeline logs are written to `logs/pipeline_<timestamp>.log` (this directory is gitignored).

> **Note on step 2 (scraper):** The scraper contacts the GuideK12 API once per address and runs with 50 concurrent requests by default. For the full ~116k-address dataset this step is the bottleneck — expect it to take anywhere from 20 minutes to over an hour depending on network conditions and API responsiveness. A `--limit` flag is available if you want to do a quick test run on a subset of addresses (see below).

### Running a single step

```bash
python3 pipeline/refresh_schools.py --output data/schools.json
python3 pipeline/build_binary.py --input data/addresses_slim.json --output data/addresses.bin
```

The scraper accepts several flags — run `python3 pipeline/scraper-v2.py --help` for the full list. Common options:

```bash
# Full run
python3 pipeline/scraper-v2.py \
  --input data/pittsburgh_addresses.json \
  --schools data/schools.json \
  --output data/addresses_full.json

# Quick test on the first 500 addresses
python3 pipeline/scraper-v2.py \
  --input data/pittsburgh_addresses.json \
  --schools data/schools.json \
  --output data/addresses_full.json \
  --limit 500
```

### Updating the raw address data

`data/pittsburgh_addresses.json` was sourced from [OpenAddresses.io](https://openaddresses.io/) (Allegheny County, PA). To refresh it, download the latest Allegheny County address dataset, filter to Pittsburgh addresses, and replace the file before re-running the pipeline.
