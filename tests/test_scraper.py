import importlib.util
import json
from pathlib import Path

import pytest


# scraper-v2.py has a hyphen so it can't be imported with normal import syntax
def _load_scraper():
    spec = importlib.util.spec_from_file_location(
        "scraper_v2",
        Path(__file__).parent.parent / "pipeline" / "scraper-v2.py",
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


_scraper = _load_scraper()
extract    = _scraper.extract_addresses_from_geojson
load_catalog = _scraper.load_school_catalog
write_slim = _scraper.write_slim


# ── Fixtures ──────────────────────────────────────────────────


def _feature(number, street, city="CITY OF PITTSBURGH", lat=40.44, lng=-79.99, id_="1"):
    return {
        "id": id_,
        "lat": lat,
        "lng": lng,
        "raw": {
            "number": number,
            "street": street,
            "city": city,
            "region": "PA",
            "postcode": "15213",
        },
    }


def _write_json(tmp_path, name, data):
    p = tmp_path / name
    p.write_text(json.dumps(data))
    return str(p)


def _school_bare(id_, name, type_, address="1 Main St"):
    return {"id": id_, "name": name, "type": type_, "address": address}


def _school_envelope(id_, name, type_):
    return {
        "id": id_,
        "school_label": name,
        "street_address": "1 Main St",
        "city": "Pittsburgh",
        "state": "PA",
        "zip": "15213",
        "attr": {"SCHOOL_TYPE": [type_]},
    }


def _full_record(id_, address, lat, lng, schools):
    return {
        "id": id_, "address": address, "lat": lat, "lng": lng,
        "school_count": len(schools), "schools": schools, "error": "",
    }


def _school_entry(name, type_, zones):
    return {"id": 1, "name": name, "address": "1 Main St", "type": type_, "zones": zones}


# ── extract_addresses_from_geojson ────────────────────────────


def test_extract_bare_list(tmp_path):
    path = _write_json(tmp_path, "addrs.json", [_feature("100", "Main St")])
    result = extract(path)
    assert len(result) == 1
    assert result[0]["address"] == "100 Main St, PITTSBURGH, PA 15213"


def test_extract_feature_collection(tmp_path):
    path = _write_json(tmp_path, "addrs.json",
                       {"type": "FeatureCollection", "features": [_feature("200", "Oak Ave")]})
    result = extract(path)
    assert len(result) == 1
    assert result[0]["address"] == "200 Oak Ave, PITTSBURGH, PA 15213"


def test_extract_deduplication(tmp_path):
    features = [
        _feature("300", "Penn Ave", id_="1"),
        _feature("300", "Penn Ave", id_="2"),  # same address, different id
    ]
    path = _write_json(tmp_path, "addrs.json", features)
    result = extract(path)
    assert len(result) == 1


def test_extract_skips_non_pittsburgh(tmp_path):
    path = _write_json(tmp_path, "addrs.json", [_feature("100", "Main St", city="PHILADELPHIA")])
    assert extract(path) == []


def test_extract_skips_missing_number(tmp_path):
    path = _write_json(tmp_path, "addrs.json", [_feature("", "Main St")])
    assert extract(path) == []


def test_extract_skips_missing_street(tmp_path):
    path = _write_json(tmp_path, "addrs.json", [_feature("100", "")])
    assert extract(path) == []


def test_extract_preserves_lat_lng(tmp_path):
    path = _write_json(tmp_path, "addrs.json", [_feature("100", "Main St", lat=40.44150, lng=-79.99340)])
    result = extract(path)
    assert result[0]["lat"] == 40.44150
    assert result[0]["lng"] == -79.99340


def test_extract_single_feature_object(tmp_path):
    # Covers the `else: features = [data]` branch — a bare dict (not list/FC)
    path = _write_json(tmp_path, "addrs.json", _feature("100", "Main St"))
    result = extract(path)
    assert len(result) == 1
    assert result[0]["address"] == "100 Main St, PITTSBURGH, PA 15213"


def test_extract_multiple_addresses(tmp_path):
    features = [
        _feature("100", "Alpha St", id_="1"),
        _feature("200", "Beta Ave",  id_="2"),
        _feature("300", "Gamma Rd",  id_="3"),
    ]
    path = _write_json(tmp_path, "addrs.json", features)
    result = extract(path)
    assert len(result) == 3


# ── load_school_catalog ───────────────────────────────────────


def test_load_catalog_bare_list(tmp_path):
    path = _write_json(tmp_path, "schools.json", [_school_bare(1, "Frick Elementary", "ELEM")])
    catalog = load_catalog(path)
    assert 1 in catalog
    assert catalog[1]["name"] == "Frick Elementary"
    assert catalog[1]["type"] == "ELEM"


def test_load_catalog_envelope_format(tmp_path):
    path = _write_json(tmp_path, "schools.json", {"result": [_school_envelope(2, "Allderdice High", "HIGH")]})
    catalog = load_catalog(path)
    assert 2 in catalog
    assert catalog[2]["name"] == "Allderdice High"
    assert catalog[2]["type"] == "HIGH"


def test_load_catalog_multiple_schools(tmp_path):
    schools = [
        _school_bare(1, "Frick", "ELEM"),
        _school_bare(2, "Allderdice", "HIGH"),
        _school_bare(3, "Sci Tech", "MIDD"),
    ]
    path = _write_json(tmp_path, "schools.json", schools)
    catalog = load_catalog(path)
    assert len(catalog) == 3
    assert set(catalog.keys()) == {1, 2, 3}


def test_load_catalog_address_from_bare_format(tmp_path):
    path = _write_json(tmp_path, "schools.json", [_school_bare(1, "Frick", "ELEM", address="100 Frick St")])
    catalog = load_catalog(path)
    assert catalog[1]["address"] == "100 Frick St"


def test_load_catalog_address_from_envelope_format(tmp_path):
    path = _write_json(tmp_path, "schools.json", {"result": [_school_envelope(1, "Frick", "ELEM")]})
    catalog = load_catalog(path)
    assert "1 Main St" in catalog[1]["address"]


# ── write_slim ────────────────────────────────────────────────


def test_write_slim_basic(tmp_path):
    records = [_full_record("1", "100 Main St", 40.44, -79.99,
                            [_school_entry("Frick", "ELEM", ["attendance"])])]
    in_path  = _write_json(tmp_path, "full.json", records)
    out_path = str(tmp_path / "slim.json")
    write_slim(in_path, out_path)
    result = json.loads(Path(out_path).read_text())
    assert result["schoolNames"] == ["Frick"]
    assert len(result["addresses"]) == 1
    addr = result["addresses"][0]
    assert addr["address"] == "100 Main St"
    assert addr["schools"][0][0] == 0        # name index
    assert addr["schools"][0][1] == "ELEM"
    assert addr["schools"][0][2] == "attendance"


def test_write_slim_excludes_record_with_missing_lat(tmp_path):
    records = [
        _full_record("1", "100 Main St", None,  -79.99, [_school_entry("Frick", "ELEM", ["attendance"])]),
        _full_record("2", "200 Main St", 40.44, -79.99, [_school_entry("Frick", "ELEM", ["attendance"])]),
    ]
    in_path  = _write_json(tmp_path, "full.json", records)
    out_path = str(tmp_path / "slim.json")
    write_slim(in_path, out_path)
    result = json.loads(Path(out_path).read_text())
    assert len(result["addresses"]) == 1
    assert result["addresses"][0]["id"] == "2"


def test_write_slim_excludes_record_with_empty_schools(tmp_path):
    records = [
        _full_record("1", "100 Main St", 40.44, -79.99, []),
        _full_record("2", "200 Main St", 40.44, -79.99, [_school_entry("Frick", "ELEM", ["attendance"])]),
    ]
    in_path  = _write_json(tmp_path, "full.json", records)
    out_path = str(tmp_path / "slim.json")
    write_slim(in_path, out_path)
    result = json.loads(Path(out_path).read_text())
    assert len(result["addresses"]) == 1


def test_write_slim_deduplicates_school_names(tmp_path):
    records = [
        _full_record("1", "100 Main St", 40.44, -79.99, [_school_entry("Frick", "ELEM", ["attendance"])]),
        _full_record("2", "200 Main St", 40.45, -79.99, [_school_entry("Frick", "ELEM", ["attendance"])]),
    ]
    in_path  = _write_json(tmp_path, "full.json", records)
    out_path = str(tmp_path / "slim.json")
    write_slim(in_path, out_path)
    result = json.loads(Path(out_path).read_text())
    assert result["schoolNames"] == ["Frick"]   # one entry despite two addresses
    assert len(result["addresses"]) == 2


def test_write_slim_empty_zones_encodes_as_empty_string(tmp_path):
    # Documents current behavior: empty zones list → "" via ",".join([]).
    # index.js decodes "" as [""] not [] — see the zones bug note in the review.
    records = [_full_record("1", "100 Main St", 40.44, -79.99,
                            [_school_entry("Frick", "ELEM", [])])]
    in_path  = _write_json(tmp_path, "full.json", records)
    out_path = str(tmp_path / "slim.json")
    write_slim(in_path, out_path)
    result = json.loads(Path(out_path).read_text())
    assert result["addresses"][0]["schools"][0][2] == ""


def test_write_slim_lat_lng_rounded_to_5dp(tmp_path):
    records = [_full_record("1", "100 Main St", 40.441501234, -79.993401234,
                            [_school_entry("Frick", "ELEM", ["attendance"])])]
    in_path  = _write_json(tmp_path, "full.json", records)
    out_path = str(tmp_path / "slim.json")
    write_slim(in_path, out_path)
    result = json.loads(Path(out_path).read_text())
    addr = result["addresses"][0]
    assert addr["lat"] == round(40.441501234, 5)
    assert addr["lng"] == round(-79.993401234, 5)
