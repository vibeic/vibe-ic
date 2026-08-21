"""tests/test_analog_per_block_pv_completeness_check.py — v1.6.24

Six cases covering the strict per-block analog PV deliverable gate:
  1. happy path — 2 blocks, both with full deliverable set         PASS
  2. one block missing drc_clean.flag                              FAIL
  3. one block missing the directory entirely                      FAIL
  4. block_list lists unicode/dict-form name; gate handles both    PASS
  5. no analog/analog_block_list.json                              VACUOUS_PASS
  6. analog_block_list.json with empty blocks: []                  VACUOUS_PASS
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from programs.analog_per_block_pv_completeness_check import (
    audit, _REQUIRED_PER_BLOCK,
)


# ---- fixture helpers --------------------------------------------------

def _full_block(project: Path, block: str) -> None:
    bdir = project / "phase3" / "analog" / block
    bdir.mkdir(parents=True, exist_ok=True)
    for pattern in _REQUIRED_PER_BLOCK:
        rel = pattern.format(block=block)
        path = bdir / rel
        # Distinguish flag files vs JSON / SPICE / GDS / Magic content.
        if path.suffix == ".flag":
            path.write_text("OK\n")
        elif path.suffix == ".json":
            path.write_text("{}\n")
        elif path.suffix == ".md":
            path.write_text(f"# {block} topology\n")
        elif path.suffix == ".sp":
            path.write_text(f"* {block} netlist stub\n.end\n")
        elif path.suffix == ".gds":
            path.write_bytes(b"\x00" * 64)
        elif path.suffix == ".mag":
            path.write_text(f"magic\ntech foo\n<< end >>\n")
        else:
            path.write_text("")


def _block_list(project: Path, blocks) -> None:
    p = project / "phase3" / "analog"
    p.mkdir(parents=True, exist_ok=True)
    (p / "analog_block_list.json").write_text(
        json.dumps({"blocks": blocks}))


# ---- tests ------------------------------------------------------------

def test_happy_path_two_full_blocks(tmp_path: Path) -> None:
    p = tmp_path / "proj"
    _block_list(p, ["bandgap", "ldo_1v8"])
    _full_block(p, "bandgap")
    _full_block(p, "ldo_1v8")
    verdict, findings = audit(p)
    assert verdict == "PASS", [(f.block, f.missing) for f in findings]
    assert all(not f.missing for f in findings)


def test_one_block_missing_drc_flag_fails(tmp_path: Path) -> None:
    p = tmp_path / "proj"
    _block_list(p, ["bandgap", "ldo_1v8"])
    _full_block(p, "bandgap")
    _full_block(p, "ldo_1v8")
    (p / "phase3" / "analog" / "ldo_1v8" / "drc_clean.flag").unlink()
    verdict, findings = audit(p)
    assert verdict == "FAIL"
    incomplete = [f for f in findings if f.missing]
    assert len(incomplete) == 1
    assert incomplete[0].block == "ldo_1v8"
    assert "drc_clean.flag" in incomplete[0].missing


def test_block_directory_missing_entirely_fails(tmp_path: Path) -> None:
    p = tmp_path / "proj"
    _block_list(p, ["bandgap", "absent_block"])
    _full_block(p, "bandgap")
    # absent_block has no directory at all
    verdict, findings = audit(p)
    assert verdict == "FAIL"
    incomplete = [f for f in findings if f.missing]
    assert len(incomplete) == 1
    assert incomplete[0].block == "absent_block"
    # Must report the directory itself as missing
    assert any("directory" in m for m in incomplete[0].missing)


def test_block_list_dict_form_supported(tmp_path: Path) -> None:
    """Some L5/A1 spec emitters write blocks as
    [{'name': 'foo', 'type': '...'}, ...] not [str, ...]. Both must
    be parsed."""
    p = tmp_path / "proj"
    _block_list(p, [
        {"name": "bandgap", "type": "voltage_reference"},
        {"name": "ldo_1v8", "type": "ldo"},
    ])
    _full_block(p, "bandgap")
    _full_block(p, "ldo_1v8")
    verdict, findings = audit(p)
    assert verdict == "PASS"
    assert {f.block for f in findings} == {"bandgap", "ldo_1v8"}


def test_no_analog_block_list_is_vacuous(tmp_path: Path) -> None:
    p = tmp_path / "proj"
    p.mkdir()
    verdict, findings = audit(p)
    assert verdict == "VACUOUS_PASS" and findings == []


def test_empty_analog_block_list_is_vacuous(tmp_path: Path) -> None:
    p = tmp_path / "proj"
    _block_list(p, [])
    verdict, findings = audit(p)
    assert verdict == "VACUOUS_PASS" and findings == []

# --- the exit code is what the flow reads, and no test drove main()

def test_main_exits_non_zero_on_a_finding(tmp_path, monkeypatch):
    """`gate_cli_mutation_probe` reported this gate SILENT: neutering `main()`
    reddened nothing in its own test file.

    Every test above drives `audit()` and asserts the VERDICT it returns. The
    flow reads the EXIT CODE, and nothing exercised the mapping between them —
    the gate could have started answering 0 to every finding with the suite
    still green.
    """
    import analog_per_block_pv_completeness_check as M
    # Empty findings with a FAIL verdict: the verdict is what main()
    # maps to the exit code, and constructing this module's own finding
    # dataclass by guessing its fields tests my guess, not the gate.
    monkeypatch.setattr(M, "audit", lambda *a, **k: ("FAIL", []))
    assert M.main([str(tmp_path)]) == 1


def test_main_exits_zero_when_clean(tmp_path, monkeypatch):
    """The other direction, or the test above is met by a gate that always
    fails."""
    import analog_per_block_pv_completeness_check as M
    monkeypatch.setattr(M, "audit", lambda *a, **k: ("PASS", []))
    assert M.main([str(tmp_path)]) == 0


def test_main_refuses_on_a_missing_project(tmp_path):
    """rc 2 — the question could not be asked, which is not a pass."""
    import analog_per_block_pv_completeness_check as M
    assert M.main([str(tmp_path / "does_not_exist")]) == 2
