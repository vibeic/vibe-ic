"""tests/test_chip_gds_canonical_real_file_check.py — v1.6.29

Five cases:
  1. happy path — real GDS at canonical path                    PASS
  2. symlink at phase3/stage4/gds/                              FAIL
  3. mixed: real foundry_handoff GDS + symlink stage4/gds       FAIL
  4. real GDS in mixed_signal AND foundry_handoff               PASS
  5. no .gds files at any canonical path                        VACUOUS_PASS
"""
from __future__ import annotations

import os
from pathlib import Path

import pytest

from programs.chip_gds_canonical_real_file_check import audit


def _real_gds(path: Path, kbytes: int = 4) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"\x00\x06\x00\x02" + b"\x00" * (kbytes * 1024 - 4))


def test_happy_path_real_gds(tmp_path: Path) -> None:
    p = tmp_path / "proj"
    _real_gds(p / "phase3" / "stage4" / "gds" / "chip_top.gds")
    verdict, findings = audit(p)
    assert verdict == "PASS"
    assert findings == []


def test_symlink_at_stage4_gds_fails(tmp_path: Path) -> None:
    p = tmp_path / "proj"
    _real_gds(p / "phase3" / "stage3" / "pnr" / "chip_top.gds", kbytes=8)
    # Create symlink at canonical destination (the v10627 anti-pattern)
    canonical = p / "phase3" / "stage4" / "gds" / "chip_top.gds"
    canonical.parent.mkdir(parents=True, exist_ok=True)
    os.symlink(p / "phase3" / "stage3" / "pnr" / "chip_top.gds", canonical)
    verdict, findings = audit(p)
    assert verdict == "FAIL"
    assert len(findings) == 1
    assert findings[0].rel_path == "phase3/stage4/gds/chip_top.gds"


def test_mixed_real_and_symlink(tmp_path: Path) -> None:
    """Real GDS in foundry_handoff + symlink in stage4/gds → still
    FAIL because at least one canonical path is a symlink."""
    p = tmp_path / "proj"
    _real_gds(p / "phase3" / "stage3" / "pnr" / "chip_top.gds", kbytes=8)
    _real_gds(p / "phase3" / "stage4" / "foundry_handoff" / "scribe.gds",
              kbytes=2)
    canonical = p / "phase3" / "stage4" / "gds" / "chip_top.gds"
    canonical.parent.mkdir(parents=True, exist_ok=True)
    os.symlink(p / "phase3" / "stage3" / "pnr" / "chip_top.gds", canonical)
    verdict, findings = audit(p)
    assert verdict == "FAIL"
    assert len(findings) == 1


def test_real_gds_at_mixed_signal_and_foundry(tmp_path: Path) -> None:
    p = tmp_path / "proj"
    _real_gds(p / "phase3" / "stage4" / "gds" / "chip_top.gds")
    _real_gds(p / "phase3" / "mixed_signal" / "top_merged.gds")
    _real_gds(p / "phase3" / "stage4" / "foundry_handoff" / "scribe.gds")
    verdict, findings = audit(p)
    assert verdict == "PASS"


def test_no_canonical_gds_is_vacuous(tmp_path: Path) -> None:
    p = tmp_path / "proj"
    p.mkdir()
    verdict, findings = audit(p)
    assert verdict == "VACUOUS_PASS"
    assert findings == []


# ------ v1.6.30 recursive + broken-symlink tests ------

def test_recursive_subdir_symlink_caught(tmp_path: Path) -> None:
    """v1.6.30 recursive glob catches a symlink in a subdir of a canonical
    GDS path (e.g. cell-library reference under phase3/stage4/gds/cells/)."""
    p = tmp_path / "proj"
    real = p / "phase3" / "stage3" / "pnr" / "ref_cell.gds"
    _real_gds(real, kbytes=2)
    # Symlink inside a nested subdir of a canonical path
    canonical = p / "phase3" / "stage4" / "gds" / "cells" / "ref_cell.gds"
    canonical.parent.mkdir(parents=True, exist_ok=True)
    os.symlink(real, canonical)
    # Real top-level GDS still present so VACUOUS_PASS doesn't apply
    _real_gds(p / "phase3" / "stage4" / "gds" / "chip_top.gds")
    verdict, findings = audit(p)
    assert verdict == "FAIL"
    assert any(f.rel_path == "phase3/stage4/gds/cells/ref_cell.gds"
               for f in findings)


def test_broken_symlink_is_separate_rule(tmp_path: Path) -> None:
    """A symlink whose target is missing must report BROKEN_SYMLINK and
    size 0 — not silently pass via the previous resolve-then-size
    behaviour."""
    p = tmp_path / "proj"
    target_real = p / "phase3" / "stage3" / "pnr" / "missing.gds"
    # Do NOT create the target — symlink is broken
    canonical = p / "phase3" / "stage4" / "gds" / "chip_top.gds"
    canonical.parent.mkdir(parents=True, exist_ok=True)
    os.symlink(target_real, canonical)
    verdict, findings = audit(p)
    assert verdict == "FAIL"
    assert len(findings) == 1
    assert findings[0].rule == "BROKEN_SYMLINK"
    assert findings[0].size_bytes == 0


def test_recursive_mixed_signal_subdir(tmp_path: Path) -> None:
    """Recursive coverage applies to mixed_signal/ subtree too."""
    p = tmp_path / "proj"
    real = p / "phase3" / "stage3" / "pnr" / "ams_block.gds"
    _real_gds(real, kbytes=2)
    canonical = p / "phase3" / "mixed_signal" / "blocks" / "ams_block.gds"
    canonical.parent.mkdir(parents=True, exist_ok=True)
    os.symlink(real, canonical)
    verdict, findings = audit(p)
    assert verdict == "FAIL"
    assert findings[0].rel_path == "phase3/mixed_signal/blocks/ams_block.gds"


def test_real_gds_in_subdir_passes(tmp_path: Path) -> None:
    """A REAL GDS in a subdir of a canonical path still passes."""
    p = tmp_path / "proj"
    _real_gds(p / "phase3" / "stage4" / "gds" / "cells" / "stdcell.gds",
              kbytes=2)
    verdict, findings = audit(p)
    assert verdict == "PASS"
    assert findings == []

# --- the exit code is what the flow reads, and no test drove main()

def test_main_exits_non_zero_on_a_finding(tmp_path, monkeypatch):
    """`gate_cli_mutation_probe` reported this gate SILENT: neutering `main()`
    reddened nothing in its own test file.

    Every test above drives `audit()` and asserts the VERDICT it returns. The
    flow reads the EXIT CODE, and nothing exercised the mapping between them —
    the gate could have started answering 0 to every finding with the suite
    still green.
    """
    import chip_gds_canonical_real_file_check as M
    # Empty findings with a FAIL verdict: the verdict is what main()
    # maps to the exit code, and constructing this module's own finding
    # dataclass by guessing its fields tests my guess, not the gate.
    monkeypatch.setattr(M, "audit", lambda *a, **k: ("FAIL", []))
    assert M.main([str(tmp_path)]) == 1


def test_main_exits_zero_when_clean(tmp_path, monkeypatch):
    """The other direction, or the test above is met by a gate that always
    fails."""
    import chip_gds_canonical_real_file_check as M
    monkeypatch.setattr(M, "audit", lambda *a, **k: ("PASS", []))
    assert M.main([str(tmp_path)]) == 0


def test_main_refuses_on_a_missing_project(tmp_path):
    """rc 2 — the question could not be asked, which is not a pass."""
    import chip_gds_canonical_real_file_check as M
    assert M.main([str(tmp_path / "does_not_exist")]) == 2
