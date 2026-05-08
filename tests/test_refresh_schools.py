import pytest

from pipeline.refresh_schools import fmt_time, normalize


# ── fmt_time ──────────────────────────────────────────────────


def test_fmt_time_morning():
    assert fmt_time("8:00") == "8:00 AM"


def test_fmt_time_afternoon():
    assert fmt_time("15:30") == "3:30 PM"


def test_fmt_time_noon():
    assert fmt_time("12:00") == "12:00 PM"


def test_fmt_time_invalid_returns_raw():
    assert fmt_time("not-a-time") == "not-a-time"


def test_fmt_time_list_input():
    assert fmt_time(["8:00"]) == "8:00 AM"


# ── normalize helpers ─────────────────────────────────────────


def _raw(id_=1, name="Frick Elementary", type_="ELEM", **overrides):
    base = {
        "id": id_,
        "school_label": name,
        "street_address": "123 Frick St",
        "city": "Pittsburgh",
        "state": "PA",
        "zip": "15217",
        "attr": {
            "SCHOOL_TYPE": [type_],
            "START_TIME": "8:00",
            "END_TIME": "15:00",
            "MAIN_PHONE": "(412) 555-1234",
        },
        "lat": 40.4415,
        "lon": -79.9934,
    }
    base.update(overrides)
    return base


# ── normalize ─────────────────────────────────────────────────


def test_normalize_valid_school():
    result = normalize([_raw()])
    assert len(result) == 1
    s = result[0]
    assert s["name"] == "Frick Elementary"
    assert s["type"] == "ELEM"
    assert s["id"] == 1


def test_normalize_skips_no_id():
    raw = _raw()
    del raw["id"]
    assert normalize([raw]) == []


def test_normalize_skips_empty_name():
    raw = _raw()
    raw["school_label"] = ""
    raw.pop("name", None)
    assert normalize([raw]) == []


def test_normalize_skips_board_type():
    assert normalize([_raw(type_="BOARD")]) == []


def test_normalize_skips_ec_type():
    assert normalize([_raw(type_="EC")]) == []


def test_normalize_includes_elem_and_high():
    schools = [_raw(id_=1, name="Frick Elementary", type_="ELEM"),
               _raw(id_=2, name="Allderdice High",  type_="HIGH")]
    result = normalize(schools)
    assert len(result) == 2


def test_normalize_sorted_alphabetically():
    schools = [
        _raw(id_=1, name="Westwood Elementary"),
        _raw(id_=2, name="Arsenal K-5"),
        _raw(id_=3, name="Minadeo Elementary"),
    ]
    result = normalize(schools)
    names = [s["name"] for s in result]
    assert names == sorted(names)


def test_normalize_formats_start_end_time():
    result = normalize([_raw()])
    assert result[0]["start_time"] == "8:00 AM"
    assert result[0]["end_time"] == "3:00 PM"


def test_normalize_includes_lat_lng():
    result = normalize([_raw(lat=40.44, lon=-79.99)])
    assert abs(result[0]["lat"] - 40.44) < 1e-4
    assert abs(result[0]["lng"] - -79.99) < 1e-4


def test_normalize_omits_lat_lng_when_absent():
    raw = _raw()
    del raw["lat"]
    del raw["lon"]
    result = normalize([raw])
    assert "lat" not in result[0]
    assert "lng" not in result[0]


def test_normalize_filters_board_keeps_others():
    schools = [
        _raw(id_=1, name="Frick Elementary",         type_="ELEM"),
        _raw(id_=2, name="PPS Board of Education",   type_="BOARD"),
        _raw(id_=3, name="Early Childhood Center",   type_="EC"),
        _raw(id_=4, name="Allderdice High School",   type_="HIGH"),
    ]
    result = normalize(schools)
    names = [s["name"] for s in result]
    assert "Frick Elementary" in names
    assert "Allderdice High School" in names
    assert "PPS Board of Education" not in names
    assert "Early Childhood Center" not in names


def test_normalize_school_label_preferred_over_name():
    raw = _raw()
    raw["school_label"] = "Label Name"
    raw["name"] = "Other Name"
    result = normalize([raw])
    assert result[0]["name"] == "Label Name"


def test_normalize_falls_back_to_name_field():
    raw = _raw()
    del raw["school_label"]
    raw["name"] = "Fallback Name"
    result = normalize([raw])
    assert result[0]["name"] == "Fallback Name"
