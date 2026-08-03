"""The PDK a run implements against must be the PDK the design declares.

Fixtures are synthetic and name no real process, foundry or design — the rule
under test is about agreement between two records, not about any one PDK.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

GATE = Path(__file__).resolve().parent.parent / "declared_pdk_is_the_pdk_used_check.py"


def _run(run_dir: Path):
    # 30s, not 120: `ci_harness_timeout_ceiling_check` caps an inner bound at
    # 60s because the harness itself dies at 180 — a bound above the ceiling
    # kills the SESSION instead of the test. MEASURED: 0.03s per call, so 30
    # leaves three orders of magnitude of headroom.
    p = subprocess.run([sys.executable, str(GATE), str(run_dir)],
                       capture_output=True, text=True, timeout=30)
    return p.returncode, p.stdout + p.stderr


def _mk(tmp: Path, *, target=None, staged=(), loaded=()):
    """A run directory with a declared target, a staged PDK, and tool logs."""
    (tmp / "phase1").mkdir(parents=True, exist_ok=True)
    if target is not None:
        (tmp / "phase1" / "pdk_staging_read.json").write_text(
            json.dumps({"adopted_pdk_target": target}), encoding="utf-8")
    for name in staged:
        f = tmp / "input" / "pdk" / "liberty" / name
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text("library (x) { }\n", encoding="utf-8")
    logs = tmp / "phase3" / "pnr"
    logs.mkdir(parents=True, exist_ok=True)
    logs.joinpath("tool.log").write_text(
        "".join(f"reading /pdks/{n}\n" for n in loaded), encoding="utf-8")
    return tmp


def test_declared_and_used_agree_is_pass(tmp_path):
    r = _mk(tmp_path, target="Example Foundry ZQ42-K3",
            staged=["zq42k3_sc.lib"], loaded=["zq42k3_sc.lef", "zq42k3_sc.lib"])
    rc, out = _run(r)
    assert rc == 0, out
    assert "PASS" in out


def test_a_different_pdk_was_used_is_fail(tmp_path):
    """The staged PDK is present and a DIFFERENT library was loaded."""
    r = _mk(tmp_path, target="Example Foundry ZQ42-K3",
            staged=["zq42k3_sc.lib"], loaded=["othernode_fd_sc_hd.lef"])
    rc, out = _run(r)
    assert rc == 1, out
    assert "was not the one used" in out or "do not match" in out


def test_nothing_staged_with_a_target_declared_is_fail_not_skip(tmp_path):
    """The shape that motivated this file: the PDK vanished and the run continued.

    A guard that treats "no PDK to check against" as "nothing to check" is switched
    off by the very condition it exists to catch.
    """
    r = _mk(tmp_path, target="Example Foundry ZQ42-K3",
            staged=[], loaded=["othernode_fd_sc_hd.lef"])
    rc, out = _run(r)
    assert rc == 1, out
    assert "NO PDK is staged" in out


def test_libraries_loaded_without_a_declared_target_is_fail(tmp_path):
    """An unanswerable question is not a pass.

    Losing the declaration is part of the failure, so "no target declared" cannot
    be a free pass for a run that went on to place and route.
    """
    r = _mk(tmp_path, target=None, staged=[], loaded=["othernode_fd_sc_hd.lef"])
    rc, out = _run(r)
    assert rc == 1, out
    assert "declares no PDK target" in out


def test_no_target_and_no_libraries_is_not_checked(tmp_path):
    """The one genuinely unaskable case — no physical implementation happened."""
    r = _mk(tmp_path, target=None, staged=[], loaded=[])
    rc, out = _run(r)
    assert rc == 2, out
    assert "NOT CHECKED" in out


def test_case_and_punctuation_do_not_defeat_the_match(tmp_path):
    """A declared target is prose; a loaded library is a filename."""
    r = _mk(tmp_path, target="Example Foundry  ZQ42-K3 / SL1.9c (180nm)",
            staged=["zq42k3_sc.lib"], loaded=["ZQ42K3_sc_hd__tt_025C.lib"])
    rc, out = _run(r)
    assert rc == 0, out


def test_generic_words_alone_never_match(tmp_path):
    """'cells', 'liberty', 'tech' appear in every PDK and carry no identity."""
    r = _mk(tmp_path, target="Example Foundry Standard Cell Library",
            staged=["othernode.lib"], loaded=["othernode_std_cell_tech.lef"])
    rc, out = _run(r)
    assert rc == 1, out


def test_the_plugins_own_tree_is_not_mistaken_for_the_run(tmp_path):
    """A snapshotted plugin under the run root carries logs of its own."""
    r = _mk(tmp_path, target="Example Foundry ZQ42-K3",
            staged=["zq42k3_sc.lib"], loaded=["zq42k3_sc.lef"])
    pw = r / "plugin_work" / "logs"
    pw.mkdir(parents=True, exist_ok=True)
    pw.joinpath("noise.log").write_text("reading /x/othernode_fd_sc_hd.lef\n",
                                        encoding="utf-8")
    rc, out = _run(r)
    assert rc == 0, out
    assert "othernode" not in out


def test_no_library_load_is_fail_but_not_an_accusation(tmp_path):
    """A target declared, a PDK staged, and NOTHING loaded.

    Reproduces the state a Phase-1-only / retarget run is in. Before this was
    split out, the gate printed "the staged PDK was not the one used" directly
    above its own "loaded : 0 distinct librar(ies)" — a claim about a load that
    never happened. It must still FAIL (nothing was demonstrated) and it must
    not say a different PDK was used.
    """
    r = _mk(tmp_path, target="Example Foundry ZQ42-K3",
            staged=["zq42k3_sc.lib"], loaded=[])
    rc, out = _run(r)
    assert rc == 1, out
    assert "was not the one used" not in out, out
    assert "whatever library was available" not in out, out
    assert "no cell-library load at all" in out, out


def test_no_library_load_is_machine_readable(tmp_path):
    """A caller must not have to parse prose to tell the two FAILs apart."""
    rec = tmp_path / "rec.json"
    r = _mk(tmp_path, target="Example Foundry ZQ42-K3",
            staged=["zq42k3_sc.lib"], loaded=[])
    p = subprocess.run([sys.executable, str(GATE), str(r), "--json", str(rec)],
                       capture_output=True, text=True, timeout=30)
    assert p.returncode == 1, p.stdout + p.stderr
    d = json.loads(rec.read_text())
    assert d["verdict"] == "FAIL"
    assert d["no_library_load_recorded"] is True
    assert d["libraries_loaded"] == []


def test_a_wrong_pdk_still_reports_a_wrong_pdk(tmp_path):
    """Control: the new branch must not swallow the case it sits in front of."""
    rec = tmp_path / "rec.json"
    r = _mk(tmp_path, target="Example Foundry ZQ42-K3",
            staged=["zq42k3_sc.lib"], loaded=["othernode_fd_sc_hd.lef"])
    p = subprocess.run([sys.executable, str(GATE), str(r), "--json", str(rec)],
                       capture_output=True, text=True, timeout=30)
    assert p.returncode == 1, p.stdout + p.stderr
    assert "was not the one used" in p.stdout
    d = json.loads(rec.read_text())
    assert d["no_library_load_recorded"] is False


def test_a_pass_records_the_field_too(tmp_path):
    """The field is present on every answered verdict, not only on the new one."""
    rec = tmp_path / "rec.json"
    r = _mk(tmp_path, target="Example Foundry ZQ42-K3",
            staged=["zq42k3_sc.lib"], loaded=["zq42k3_sc.lef"])
    p = subprocess.run([sys.executable, str(GATE), str(r), "--json", str(rec)],
                       capture_output=True, text=True, timeout=30)
    assert p.returncode == 0, p.stdout + p.stderr
    assert json.loads(rec.read_text())["no_library_load_recorded"] is False
