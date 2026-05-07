# Address Data

This is the Pittsburgh address data parsed directly from [OpenAddresses.io](https://openaddresses.io/)

## Steps

1. Parse out the Pittsburgh address data from OpenAddresses.
2. Remove duplicate Pittsburgh addresses.
3. Retrieve and store PPS school data from the PPS school search tool (?).
4. Scrape/API requests to the PPS search tool to determine which schools each address feeds into.
5. Save the file from Step #4.

## Will ultimately need three data files:

1. The raw Pittsburgh address data from OpenAddresses (`pittsburgh_addresses.json`).
2. The address data that includes the schools that each address feeds into.
3. The school data (e.g., each individual school).