#!/usr/bin/env python3
"""Tests for regression_issue_intake_check.py.

The module's main() fetches a live GitHub issue, so we exercise its pure
helpers directly (no network): the H3-form parser, the mandatory-field
validator (the issue-#5 enforcement core), the fixture emitter, and the
token reader.
"""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

_HERE = Path(__file__).resolve().parent
_PROG = _HERE.parent / "regression_issue_intake_check.py"

_spec = importlib.util.spec_from_file_location(
    "regression_issue_intake_check", _PROG)
mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(mod)


# A well-formed GitHub form-issue body with every mandatory H3 field.
_GOOD_BODY = """### Project name

spm

### Affected layer

L3

### Specific JSON field

opcodes[0].name

### Verbatim input snippet (MANDATORY)

```
line one of the spec
line two of the spec
line three of the spec
line four of the spec
```

### Filename of the snippet

datasheet.txt

### Expected output (MANDATORY)

WRITE

### Actual output (MANDATORY)

OPCODE_NAME_UNKNOWN

### Plugin version where the bug was observed

v1.6.130
"""


# ----------------------------------------------------------------------
# parser
# ----------------------------------------------------------------------
def test_parse_extracts_all_fields():
    parsed = mod._parse_form_issue(_GOOD_BODY)
    assert parsed["project"] == "spm"
    assert parsed["layer"] == "L3"
    assert parsed["field_path"] == "opcodes[0].name"
    assert parsed["input_filename"] == "datasheet.txt"
    assert parsed["expected"] == "WRITE"
    assert parsed["actual"] == "OPCODE_NAME_UNKNOWN"
    assert parsed["version_observed"] == "v1.6.130"
    # Fenced code markers stripped; the four lines preserved.
    assert "line one of the spec" in parsed["input_snippet"]
    assert "```" not in parsed["input_snippet"]


def test_parse_drops_no_response_sentinel():
    body = "### Project name\n\n_No response_\n"
    parsed = mod._parse_form_issue(body)
    assert parsed.get("project", "") == ""


# ----------------------------------------------------------------------
# validate — PASS path
# ----------------------------------------------------------------------
def test_validate_passes_complete_issue():
    parsed = mod._parse_form_issue(_GOOD_BODY)
    assert mod._validate(parsed) == []


# ----------------------------------------------------------------------
# validate — the issue-#5 defect: missing mandatory fields
# ----------------------------------------------------------------------
def test_validate_flags_missing_expected_and_actual():
    parsed = mod._parse_form_issue(_GOOD_BODY)
    del parsed["expected"]
    del parsed["actual"]
    missing = mod._validate(parsed)
    assert "expected" in missing
    assert "actual" in missing


def test_validate_flags_short_snippet():
    parsed = mod._parse_form_issue(_GOOD_BODY)
    parsed["input_snippet"] = "only one line\n"
    missing = mod._validate(parsed)
    assert any("input_snippet" in m for m in missing)


def test_validate_flags_bad_project_name():
    parsed = mod._parse_form_issue(_GOOD_BODY)
    parsed["project"] = "Bad Name/With Slash"
    missing = mod._validate(parsed)
    assert any(m.startswith("project") for m in missing)


def test_validate_flags_path_in_filename():
    parsed = mod._parse_form_issue(_GOOD_BODY)
    parsed["input_filename"] = "../etc/passwd"
    missing = mod._validate(parsed)
    assert any(m.startswith("input_filename") for m in missing)


# ----------------------------------------------------------------------
# emit_fixture — writes the snippet + appends pending sidecar
# ----------------------------------------------------------------------
def test_emit_fixture_writes_snippet_and_pending(tmp_path):
    # The emitter writes under
    # <repo_root>/vibe-ic-marketplace/plugins/vibe-ic/programs/tests/phase1_fixtures/.
    parsed = mod._parse_form_issue(_GOOD_BODY)
    fixture = mod._emit_fixture(tmp_path, parsed, issue_number=5)
    assert fixture.is_file()
    assert fixture.name == "datasheet.txt"
    assert "line one of the spec" in fixture.read_text()

    pending = (tmp_path / "vibe-ic-marketplace/plugins/vibe-ic/tests"
               / "phase1_fixtures" / "_pending.json")
    records = json.loads(pending.read_text())
    assert records[-1]["issue"] == 5
    assert records[-1]["project"] == "spm"
    assert records[-1]["expected"] == "WRITE"
    assert records[-1]["actual"] == "OPCODE_NAME_UNKNOWN"


# ----------------------------------------------------------------------
# token reader — honest error when no token anywhere
# ----------------------------------------------------------------------
def test_read_token_from_file(tmp_path, monkeypatch):
    tf = tmp_path / "tok"
    tf.write_text("ghp_secret\n")
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    assert mod._read_token(str(tf)) == "ghp_secret"


def test_read_token_from_env(monkeypatch):
    monkeypatch.setenv("GITHUB_TOKEN", "env_token")
    assert mod._read_token(None) == "env_token"


def test_read_token_raises_when_absent(tmp_path, monkeypatch):
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    monkeypatch.setattr(mod.os.path, "expanduser",
                        lambda p: str(tmp_path / "no_such_token"))
    # Also redirect the default ~/.config path lookup.
    monkeypatch.setattr(mod.Path, "expanduser",
                        lambda self: tmp_path / "no_such_token")
    with pytest.raises(RuntimeError):
        mod._read_token(None)
