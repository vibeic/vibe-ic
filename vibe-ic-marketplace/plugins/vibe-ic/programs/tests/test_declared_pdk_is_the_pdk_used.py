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


# ── vibe-ic#709 / #713 — a partial match is not a declaration ───────────────
# Synthetic names throughout: no real PDK, foundry or part number appears.

import subprocess as _sp, sys as _sys, tempfile as _tf, json as _json
from pathlib import Path as _P

_FAMILY = "abc123xy456"
_LOADED = [f"{_FAMILY}_5lm_tech_v56.lef", f"{_FAMILY}_macro_v56.lef"]
_GATE = _P(__file__).resolve().parents[1] / "declared_pdk_is_the_pdk_used_check.py"


def _run_decl(declared: str):
    """rc and the JSON record, for a run whose logs load `_LOADED`."""
    td = _tf.mkdtemp()
    root = _P(td)
    (root / "phase1").mkdir(parents=True)
    (root / "input" / "pdk").mkdir(parents=True)
    (root / "logs").mkdir()
    for n in _LOADED:
        (root / "input" / "pdk" / n).write_text("# staged\n")
    (root / "phase1" / "pdk_staging_read.json").write_text(
        _json.dumps({"adopted_pdk_target": declared}))
    (root / "logs" / "pnr.log").write_text("".join(
        f"[INFO ODB-0227] LEF file: /run/input/pdk/{n}, created 1 layers\n"
        for n in _LOADED))
    out = root / "rec.json"
    r = _sp.run([_sys.executable, str(_GATE), str(root), "--json", str(out)],
                capture_output=True, text=True, timeout=55)
    rec = _json.loads(out.read_text()) if out.is_file() else {}
    return r.returncode, rec


def test_an_interior_fragment_is_not_a_declaration():
    """#709: bare `d in l` accepted any >=4-char run appearing ANYWHERE inside a
    library token, so a fragment from the middle of the family name declared
    that family."""
    rc, _ = _run_decl("c123")
    assert rc == 1, "an interior fragment must not pass as a declaration"


def test_a_foundry_length_prefix_is_not_a_declaration():
    """#709: a 4-character prefix is shared by every family a vendor ships, so
    it names the vendor and not the library that ran."""
    rc, _ = _run_decl("abc1")
    assert rc == 1


def test_the_punctuation_case_the_matcher_exists_for_still_passes():
    """The reason containment was there at all: a human writes `ABC123-XY456`,
    the vendor's filename is one token. That must keep working — the fix is
    boundary+substance, not exact equality."""
    rc, _ = _run_decl("ABC123XY456 on Foundry Q, 250nm CMOS")
    assert rc == 0


def test_a_declaration_naming_another_PDK_cannot_be_outvoted_by_a_match():
    """#713, and the worst case in it: the declaration says an OPEN-SOURCE
    process ran while a different one did. The family token matches, so the gate
    used to PASS — outvoting the half of the sentence it exists to check."""
    rc, rec = _run_decl(f"{_FAMILY} on an open-source sky130 130nm process")
    assert rc == 1
    assert "sky130" in " ".join(rec.get("contradicting_named_pdks") or [])
    assert rec.get("matching_libraries"), (
        "the partial match must still be RECORDED — the finding is that it did "
        "not settle the question, not that it did not happen")


def test_a_pass_says_what_it_did_not_check():
    """The honest half of #713. A foundry or a process node in the declaration
    is NOT derivable from a LEF filename, so this gate cannot judge it. Failing
    on it would be fabrication in the other direction; passing SILENTLY lets the
    PASS read as though it had been verified. It is disclosed instead."""
    rc, rec = _run_decl(f"{_FAMILY} on Foundry R, 55nm FinFET")
    assert rc == 0
    assert rec.get("verified") == "library identity only"
    assert "not derivable" in (rec.get("not_verified") or "")
