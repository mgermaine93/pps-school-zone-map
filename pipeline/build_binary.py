"""
Converts data/addresses_slim.json to a compact binary file (data/addresses.bin)
for faster loading in the web app (~3x smaller, near-instant parse vs JSON.parse).

Binary layout
─────────────
Header (12 bytes):
  [0-3]   magic "PPSb"
  [4-5]   schoolNameCount  Uint16LE
  [6]     typeCount        Uint8
  [7]     zoneCount        Uint8
  [8-11]  addressCount     Uint32LE

Lookup tables (variable):
  schoolNames : schoolNameCount × [Uint8 len, UTF-8 bytes]
  types       : typeCount       × [Uint8 len, UTF-8 bytes]
  zones       : zoneCount       × [Uint8 len, UTF-8 bytes]

Address records (variable, one per address):
  Int32LE  lat × 100 000 (5 decimal places of precision)
  Int32LE  lng × 100 000
  Uint8    schoolCount (N)
  N × 3:   Uint8 nameIdx, Uint8 typeIdx, Uint8 zoneIdx
  Uint16LE id byte length  + id UTF-8 bytes
  Uint16LE addr byte length + addr UTF-8 bytes

Usage:
    python3 pipeline/build_binary.py
    python3 pipeline/build_binary.py --input data/addresses_slim.json --output data/addresses.bin
"""

import argparse
import json
import struct
from pathlib import Path


def build(input_path: str, output_path: str) -> None:
    with open(input_path, encoding='utf-8') as f:
        payload = json.load(f)

    school_names  = payload['schoolNames']
    raw_addresses = payload['addresses']

    # Build type and zone lookup tables in order of first appearance
    types_list:  list[str]      = []
    types_index: dict[str, int] = {}
    zones_list:  list[str]      = []
    zones_index: dict[str, int] = {}

    for addr in raw_addresses:
        for school in addr['schools']:
            t, z = school[1], school[2]
            if t not in types_index:
                types_index[t] = len(types_list)
                types_list.append(t)
            if z not in zones_index:
                zones_index[z] = len(zones_list)
                zones_list.append(z)

    buf = bytearray()

    def write_lstr(s: str) -> None:
        b = s.encode('utf-8')
        buf.extend(struct.pack('<B', len(b)))
        buf.extend(b)

    # Header
    buf.extend(b'PPSb')
    buf.extend(struct.pack('<H', len(school_names)))   # Uint16
    buf.extend(struct.pack('<B', len(types_list)))     # Uint8
    buf.extend(struct.pack('<B', len(zones_list)))     # Uint8
    buf.extend(struct.pack('<I', len(raw_addresses)))  # Uint32

    # Lookup tables
    for name in school_names:
        write_lstr(name)
    for t in types_list:
        write_lstr(t)
    for z in zones_list:
        write_lstr(z)

    # Address records
    for addr in raw_addresses:
        buf.extend(struct.pack('<i', round(addr['lat'] * 100000)))
        buf.extend(struct.pack('<i', round(addr['lng'] * 100000)))

        schools = addr['schools']
        buf.extend(struct.pack('<B', len(schools)))
        for school in schools:
            buf.extend(struct.pack('<BBB',
                school[0],
                types_index[school[1]],
                zones_index[school[2]],
            ))

        id_bytes = str(addr['id']).encode('utf-8')
        buf.extend(struct.pack('<H', len(id_bytes)))
        buf.extend(id_bytes)

        addr_bytes = addr['address'].encode('utf-8')
        buf.extend(struct.pack('<H', len(addr_bytes)))
        buf.extend(addr_bytes)

    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, 'wb') as f:
        f.write(buf)

    in_mb  = Path(input_path).stat().st_size / 1e6
    out_mb = len(buf) / 1e6
    print(f"✅ {output_path}")
    print(f"   {len(raw_addresses):,} addresses · {len(school_names)} schools")
    print(f"   {in_mb:.1f} MB JSON → {out_mb:.1f} MB binary  ({(1 - out_mb / in_mb) * 100:.0f}% smaller)")


def main() -> None:
    parser = argparse.ArgumentParser(description="Convert addresses_slim.json to binary")
    parser.add_argument('--input',  default='data/addresses_slim.json')
    parser.add_argument('--output', default='data/addresses.bin')
    args = parser.parse_args()
    build(args.input, args.output)


if __name__ == '__main__':
    main()
