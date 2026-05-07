# tests/js

Contains Jest unit tests for the pure utility functions in `index.js`.

Because `index.js` is a monolithic browser script that depends on Leaflet and the DOM, it cannot be imported directly in Node. The functions under test (`getPrimarySchool`, `getSchoolColor`) are declared inline in the test file. If `index.js` is ever refactored into modules, replace those inline declarations with imports.

## Running the tests

```bash
cd tests/js
npm ci          # install Jest (first time only)
npx jest        # run all tests
```

Tests also run automatically as part of the GitHub Actions monthly refresh workflow before the data pipeline executes.
