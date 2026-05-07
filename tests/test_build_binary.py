import json
import struct
from pathlib import Path

import pytest

from pipeline.build_binary import build


# ── Helpers ───────────────────────────────────────────────────


def _make_slim(tmp_path, school_names, addresses):
    p = tmp_path / "slim.json"
    p.write_text(json.dumps({"schoolNames": school_names, "addresses": addresses}))
    return str(p)


def _read_lstr(data, pos):
    length = data[pos]
    s = data[pos + 1 : pos + 1 + length].decode("utf-8")
    return s, pos + 1 + length


def _parse_binary(raw):
    """Minimal binary parser that mirrors the format defined in build_binary.py."""
    magic = raw[:4]
    school_name_count = struct.unpack_from("<H", raw, 4)[0]
    type_count        = struct.unpack_from("<B", raw, 6)[0]
    zone_count        = struct.unpack_from("<B", raw, 7)[0]
    address_count     = struct.unpack_from("<I", raw, 8)[0]
    pos = 12

    school_names = []
    for _ in range(school_name_count):
        s, pos = _read_lstr(raw, pos)
        school_names.append(s)

    types = []
    for _ in range(type_count):
        s, pos = _read_lstr(raw, pos)
        types.append(s)

    zones = []
    for _ in range(zone_count):
        s, pos = _read_lstr(raw, pos)
        zones.append(s)

    addresses = []
    for _ in range(address_count):
        lat = struct.unpack_from("<i", raw, pos)[0] / 100_000
        lng = struct.unpack_from("<i", raw, pos + 4)[0] / 100_000
        school_count = struct.unpack_from("<B", raw, pos + 8)[0]
        pos += 9

        schools = []
        for _ in range(school_count):
            ni, ti, zi = struct.unpack_from("<BBB", raw, pos)
            schools.append({
                "name":  school_names[ni],
                "type":  types[ti],
                "zones": zones[zi].split(","),
            })
            pos += 3

        id_len    = struct.unpack_from("<H", raw, pos)[0]
        record_id = raw[pos + 2 : pos + 2 + id_len].decode("utf-8")
        pos += 2 + id_len

        addr_len = struct.unpack_from("<H", raw, pos)[0]
        address  = raw[pos + 2 : pos + 2 + addr_len].decode("utf-8")
        pos += 2 + addr_len

        addresses.append({
            "id": record_id, "address": address,
            "lat": lat, "lng": lng, "schools": schools,
        })

    return {
        "magic": magic, "school_names": school_names,
        "types": types, "zones": zones, "addresses": addresses,
    }


def _build(tmp_path, school_names, addresses):
    slim = _make_slim(tmp_path, school_names, addresses)
    out  = str(tmp_path / "out.bin")
    build(slim, out)
    return _parse_binary(Path(out).read_bytes())


# ── Tests ─────────────────────────────────────────────────────


def test_header_magic(tmp_path):
    result = _build(tmp_path, ["Frick"], [
        {"id": "1", "address": "1 Main St", "lat": 40.44, "lng": -79.99,
         "schools": [[0, "ELEM", "attendance"]]}
    ])
    assert result["magic"] == b"PPSb"


def test_address_count_in_header(tmp_path):
    addresses = [
        {"id": str(i), "address": f"{i} Main St", "lat": 40.4 + i * 0.001, "lng": -80.0,
         "schools": [[0, "ELEM", "attendance"]]}
        for i in range(7)
    ]
    result = _build(tmp_path, ["Frick"], addresses)
    assert len(result["addresses"]) == 7


def test_empty_addresses_produces_valid_header(tmp_path):
    result = _build(tmp_path, [], [])
    assert result["magic"] == b"PPSb"
    assert result["addresses"] == []


def test_round_trip_lat_lng_precision(tmp_path):
    result = _build(tmp_path, ["Frick"], [
        {"id": "1", "address": "1 Main St", "lat": 40.44150, "lng": -79.99340,
         "schools": [[0, "ELEM", "attendance"]]}
    ])
    addr = result["addresses"][0]
    assert abs(addr["lat"] - 40.44150) < 1e-4
    assert abs(addr["lng"] - -79.99340) < 1e-4


def test_round_trip_school_names(tmp_path):
    result = _build(tmp_path,
        ["Frick Elementary", "Allderdice High"],
        [{"id": "1", "address": "1 Main St", "lat": 40.44, "lng": -79.99,
          "schools": [[0, "ELEM", "attendance"], [1, "HIGH", "attendance"]]}]
    )
    assert result["school_names"] == ["Frick Elementary", "Allderdice High"]
    schools = result["addresses"][0]["schools"]
    assert schools[0]["name"] == "Frick Elementary"
    assert schools[1]["name"] == "Allderdice High"


def test_round_trip_address_string(tmp_path):
    result = _build(tmp_path, ["Frick"], [
        {"id": "42", "address": "123 Oak Ave, Pittsburgh, PA 15213",
         "lat": 40.44, "lng": -79.99, "schools": [[0, "ELEM", "attendance"]]}
    ])
    assert result["addresses"][0]["address"] == "123 Oak Ave, Pittsburgh, PA 15213"


def test_round_trip_multiple_zones(tmp_path):
    result = _build(tmp_path, ["Sci Tech"], [
        {"id": "1", "address": "1 Penn Ave", "lat": 40.44, "lng": -79.99,
         "schools": [[0, "MIDD", "attendance,early"]]}
    ])
    assert result["addresses"][0]["schools"][0]["zones"] == ["attendance", "early"]


def test_type_and_zone_lookup_tables_built_correctly(tmp_path):
    result = _build(tmp_path, ["Frick", "Allderdice", "Sci Tech"], [
        {"id": "1", "address": "1 Main St", "lat": 40.44, "lng": -79.99,
         "schools": [[0, "ELEM", "attendance"], [1, "HIGH", "attendance"], [2, "MIDD", "early"]]}
    ])
    assert set(result["types"]) == {"ELEM", "HIGH", "MIDD"}
    assert set(result["zones"]) == {"attendance", "early"}


def test_address_id_stored_as_string(tmp_path):
    result = _build(tmp_path, ["Frick"], [
        {"id": 9999, "address": "1 Main St", "lat": 40.44, "lng": -79.99,
         "schools": [[0, "ELEM", "attendance"]]}
    ])
    assert result["addresses"][0]["id"] == "9999"


def test_unicode_school_name_round_trips(tmp_path):
    result = _build(tmp_path, ["École Élite — PreK–8"], [
        {"id": "1", "address": "1 Main St", "lat": 40.44, "lng": -79.99,
         "schools": [[0, "K8", "attendance"]]}
    ])
    assert result["school_names"] == ["École Élite — PreK–8"]
    assert result["addresses"][0]["schools"][0]["name"] == "École Élite — PreK–8"


def test_multiple_addresses_preserved_in_order(tmp_path):
    addresses = [
        {"id": "a", "address": "1 Alpha St", "lat": 40.44, "lng": -79.99,
         "schools": [[0, "ELEM", "attendance"]]},
        {"id": "b", "address": "2 Beta St",  "lat": 40.45, "lng": -79.98,
         "schools": [[0, "ELEM", "attendance"]]},
        {"id": "c", "address": "3 Gamma St", "lat": 40.46, "lng": -79.97,
         "schools": [[0, "ELEM", "attendance"]]},
    ]
    result = _build(tmp_path, ["Frick"], addresses)
    ids = [a["id"] for a in result["addresses"]]
    assert ids == ["a", "b", "c"]
