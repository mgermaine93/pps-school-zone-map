import logging
import os
from datetime import datetime
from pathlib import Path

import main
from main import update_index_date, git_push_changes

logger = logging.getLogger("test")

_TEMPLATE = "<p><em>Data last updated: {date}.</em></p>"


def _write_index(root, date_str):
    (root / "index.html").write_text(_TEMPLATE.format(date=date_str))


def _read_index(root):
    return (root / "index.html").read_text()


# ── update_index_date ─────────────────────────────────────────


def test_update_replaces_old_date(tmp_path, monkeypatch):
    monkeypatch.setattr(main, "ROOT", tmp_path)
    _write_index(tmp_path, "January 2020")
    update_index_date(logger)
    expected = datetime.now().strftime("%B %Y")
    assert expected in _read_index(tmp_path)


def test_update_no_change_when_already_current(tmp_path, monkeypatch):
    monkeypatch.setattr(main, "ROOT", tmp_path)
    current = datetime.now().strftime("%B %Y")
    _write_index(tmp_path, current)
    before = _read_index(tmp_path)
    update_index_date(logger)
    assert _read_index(tmp_path) == before


def test_update_preserves_surrounding_html(tmp_path, monkeypatch):
    monkeypatch.setattr(main, "ROOT", tmp_path)
    _write_index(tmp_path, "January 2020")
    update_index_date(logger)
    content = _read_index(tmp_path)
    assert content.startswith("<p>")
    assert content.endswith("</p>")
    assert "<em>Data last updated:" in content
    assert "</em>" in content


def test_update_no_op_when_pattern_absent(tmp_path, monkeypatch):
    monkeypatch.setattr(main, "ROOT", tmp_path)
    html = "<p>No date marker here.</p>"
    (tmp_path / "index.html").write_text(html)
    update_index_date(logger)
    assert _read_index(tmp_path) == html


def test_update_date_format_is_month_year(tmp_path, monkeypatch):
    monkeypatch.setattr(main, "ROOT", tmp_path)
    _write_index(tmp_path, "January 2020")
    update_index_date(logger)
    content = _read_index(tmp_path)
    now = datetime.now()
    assert now.strftime("%B") in content   # full month name
    assert str(now.year) in content


# ── git_push_changes ──────────────────────────────────────────


def test_git_push_skip_env_var(monkeypatch):
    # SKIP_GIT_PUSH=1 must return early without touching git or the filesystem.
    monkeypatch.setenv("SKIP_GIT_PUSH", "1")
    # If the function tries to run git it will raise FileNotFoundError on a
    # path that doesn't exist — the absence of any exception confirms the early exit.
    git_push_changes(logger, {})
