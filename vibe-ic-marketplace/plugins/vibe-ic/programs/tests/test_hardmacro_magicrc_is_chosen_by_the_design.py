#!/usr/bin/env python3
"""The technology a macro is abstracted against must be the DESIGN'S, not the alphabet's.

MEASURED IN THE SHIPPED IMAGE, on `ghcr.io/vibeic/vibeic-eda:0.3.16`, where
`PDK_ROOT` is the PARENT of every installed PDK — which is what the program's
own `--pdk-root` default reads:

    PDK_ROOT                             = /foss/pdks
    _magicrc_for("/foss/pdks")           -> gf180mcuD/…/gf180mcuD.magicrc
    _magicrc_for("/foss/pdks/sky130A")   -> None
    _magicrc_for("/foss/pdks/gf180mcuD") -> None

The body was `sorted(root.glob("*/libs.tech/magic/*.magicrc"))[0]`. Two defects,
and they compound into a third:

1. EVERY DESIGN GOT ONE TECHNOLOGY — whichever sorted first. A design on any
   other PDK is abstracted against a technology that does not define its layers.
2. PASSING THE CORRECT SPECIFIC PDK RETURNED None, because the glob requires a
   `*/` level. The one call that could have been right was the one that failed.
3. SO THE FAILURE IS SILENT. Magic does not refuse an unknown layer; it reports
   `Unknown layer/datatype` and writes a LEF with an OUTLINE AND NO PINS. That
   is a delivered-looking view of nothing, and it is the exact artefact
   `test_a_pinless_abstract_is_never_staged` exists to stop being staged. The
   pin-less abstract is the SYMPTOM; picking the wrong technology is a cause.

WHY REFUSING IS THE FIX AND CHOOSING IS NOT. `run()` receives `pdk_root` and
reads the design name off the DEF. It has NO input naming the design's PDK, so
it cannot choose correctly even in principle. A program that cannot know must
not pick — it must say so. `write_lef_with_magic` already treats a missing
magicrc as an ABSENT capability with a stated reason, so refusing costs nothing
that was ever trustworthy and removes an answer that looked delivered.

chip/PDK-AGNOSTIC: the fixtures below invent PDK directory names; no real PDK
name is required for any assertion, and the rule is about HOW MANY technologies
are in scope, never which.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_TESTS = Path(__file__).resolve().parent
_PROGRAMS = _TESTS.parent
sys.path.insert(0, str(_PROGRAMS))

import digital_hardmacro_gen as mod  # noqa: E402


def _pdk(root: Path, name: str) -> Path:
    d = root / name / "libs.tech" / "magic"
    d.mkdir(parents=True, exist_ok=True)
    (d / f"{name}.magicrc").write_text("# technology\n")
    return root / name


def test_the_pdk_directory_itself_is_accepted(tmp_path):
    """The obviously-right call. It used to return None.

    A caller that knows the design's PDK passes THAT directory. The old glob
    required a `*/` level, so the correct call found nothing and the capability
    read as ABSENT — while the vague call silently succeeded with the wrong
    technology. Exactly backwards.
    """
    pdk = _pdk(tmp_path, "aaa_pdk")
    got = mod._magicrc_for(str(pdk))
    assert got is not None, (
        "passing the PDK directory itself returns no magicrc, so the one call "
        "that names the design's technology unambiguously is the one that "
        "fails")
    assert got.endswith("aaa_pdk.magicrc"), got


def test_a_root_holding_exactly_one_pdk_is_unambiguous(tmp_path):
    """One installed technology is not a choice, so it is not a guess."""
    _pdk(tmp_path, "only_pdk")
    got = mod._magicrc_for(str(tmp_path))
    assert got is not None and got.endswith("only_pdk.magicrc"), got


def test_a_root_holding_TWO_pdks_refuses_instead_of_picking_one(tmp_path):
    """THE DEFECT, pinned.

    Nothing reaching this function says which PDK the design is on. With two
    installed, the old code returned the alphabetically first and the caller
    could not tell it had been chosen for it.
    """
    _pdk(tmp_path, "aaa_pdk")
    _pdk(tmp_path, "zzz_pdk")
    got = mod._magicrc_for(str(tmp_path))
    assert got is None, (
        f"two PDK technologies are installed and nothing here says which one "
        f"the design uses, yet a magicrc was chosen: {got}. That is how a "
        f"design gets abstracted against another PDK's technology and comes "
        f"out as an outline with no pins.")


def test_the_refusal_names_what_it_was_choosing_between(tmp_path, monkeypatch):
    """A refusal nobody can act on is a new silence.

    The caller has to be told there were candidates and that the remedy is to
    pass the PDK directory — otherwise "no magicrc" reads as "this image has no
    PDK installed", which is a different and wrong diagnosis.
    """
    _pdk(tmp_path, "aaa_pdk")
    _pdk(tmp_path, "zzz_pdk")
    cands = mod.magicrc_candidates(str(tmp_path))
    assert len(cands) == 2, cands

    # HERMETIC. `write_lef_with_magic` checks for the binary BEFORE it resolves
    # the technology, so on a host without magic this arm would assert against
    # "magic is not on PATH" and never reach the refusal it is about — the same
    # host-dependence that made test_a_pinless_abstract_is_never_staged read
    # differently on two machines. The binary is claimed present; nothing here
    # launches it, because the refusal happens before any launch.
    monkeypatch.setattr(mod.shutil, "which", lambda _n: "/usr/bin/magic")

    ok, why = mod.write_lef_with_magic(
        "top", tmp_path / "in.gds", tmp_path / "in.def",
        tmp_path / "out.lef", str(tmp_path), False, False)
    assert ok is False
    assert "aaa_pdk" in why and "zzz_pdk" in why, (
        f"the refusal does not name the candidates it declined to choose "
        f"between: {why}")
    assert "PDK DIRECTORY" in why or "PDK directory" in why, (
        f"the refusal does not state the remedy: {why}")


def test_an_empty_or_absent_root_is_still_absent_not_a_crash(tmp_path):
    assert mod._magicrc_for(str(tmp_path / "nope")) is None
    assert mod._magicrc_for("") is None
    assert mod.magicrc_candidates(str(tmp_path / "nope")) == []


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
