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


# ---------------------------------------------------------------------------
# the runner half: the producer can only refuse less often if it is TOLD
# ---------------------------------------------------------------------------
def _runner():
    sys.path.insert(0, str(_PROGRAMS))
    import phase3_one_shot_runner as r
    return r


def test_the_runner_hands_the_producer_the_designs_own_pdk(tmp_path, monkeypatch):
    """The other half of the fix.

    Making the producer REFUSE an ambiguous PDK_ROOT is only half a repair: on
    its own it converts a silently-wrong abstract into a step that always
    skips. The step has the run's `PdkConfig` in scope, so it can say which PDK
    the design is on — and then the refusal is the exception rather than the
    rule.
    """
    r = _runner()
    root = tmp_path / "pdks"
    (root / "somepdk" / "libs.tech" / "magic").mkdir(parents=True)
    (root / "otherpdk" / "libs.tech" / "magic").mkdir(parents=True)
    monkeypatch.setenv("PDK_ROOT", str(root))

    pdk = type("P", (), {"name": "somepdk"})()
    got = r._hardmacro_pdk_dir(pdk)
    assert got == str(root / "somepdk"), (
        f"the design is on 'somepdk' and the runner resolved {got!r}; if this "
        f"is None the producer sees only PDK_ROOT, which holds two "
        f"technologies, and refuses on every run")

    seen = {}

    def fake_run(cmd, **kw):
        seen["cmd"] = cmd
        import subprocess as sp
        return sp.CompletedProcess(cmd, 0, "ok\n", "")

    monkeypatch.setattr(r.subprocess, "run", fake_run)
    r.step_digital_hardmacro_gen(tmp_path, pdk)
    assert "--pdk-root" in seen["cmd"], (
        f"the producer was invoked without --pdk-root, so it falls back to "
        f"$PDK_ROOT: {seen['cmd']}")
    assert seen["cmd"][seen["cmd"].index("--pdk-root") + 1] == str(root / "somepdk")


def test_an_unrecognisable_layout_degrades_to_a_refusal_not_a_guess(tmp_path, monkeypatch):
    """If the standard layout does not hold, resolve NOTHING.

    The producer then sees the bare `$PDK_ROOT` and refuses with its own stated
    reason. What must never happen is this function inventing a directory: a
    reconstructed path that happens to exist is how the wrong technology got
    chosen in the first place.
    """
    r = _runner()
    root = tmp_path / "pdks"
    (root / "somepdk").mkdir(parents=True)          # no libs.tech/magic
    monkeypatch.setenv("PDK_ROOT", str(root))
    assert r._hardmacro_pdk_dir(type("P", (), {"name": "somepdk"})()) is None
    assert r._hardmacro_pdk_dir(type("P", (), {"name": ""})()) is None
    assert r._hardmacro_pdk_dir(None) is None
    monkeypatch.delenv("PDK_ROOT", raising=False)
    assert r._hardmacro_pdk_dir(type("P", (), {"name": "somepdk"})()) is None
