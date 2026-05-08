# tests

Contains the project's automated test suite.

## Structure

| Path | Framework | Covers |
|---|---|---|
| `test_build_binary.py` | pytest | `pipeline/build_binary.py` — binary encoding, round-trip correctness, header format. |
| `test_scraper.py` | pytest | `pipeline/scraper-v2.py` — address extraction, school catalog loading, slim JSON output. |
| `test_refresh_schools.py` | pytest | `pipeline/refresh_schools.py` — school normalization, time formatting, type filtering. |
| `test_main.py` | pytest | `main.py` — index date update, git push skip behavior. |
| `js/utils.test.js` | Jest | Pure utility functions from `index.js` — `getPrimarySchool`, `getSchoolColor`. |

## Running the tests

```bash
# Python tests
pip install -r requirements-dev.txt   # first time only
pytest tests/ -v

# JavaScript tests
cd tests/js
npm ci                                # first time only
npx jest
```

Tests also run automatically in the GitHub Actions monthly refresh workflow before the data pipeline executes.
