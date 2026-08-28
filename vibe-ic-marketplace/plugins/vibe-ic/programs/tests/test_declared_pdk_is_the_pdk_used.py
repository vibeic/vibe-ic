"""The PDK a run implements against must be the PDK the design declares.

Fixtures are synthetic and name no real process, foundry or design — the rule
under test is about agreement between two records, not about any one PDK.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

GATE = Path(__file__).resolve().parent.parent / "declared_pdk_is_the_pdk_used_check.py"


def _run(run_dir: Path):
    # 30s, not 120: `ci_harness_timeout_ceiling_check` caps an inner bound at
    # 60s because the harness itself dies at 180 — a bound above the ceiling
    # kills the SESSION instead of the test. MEASURED: 0.03s per call, so 30
    # leaves three orders of magnitude of headroom.
    p = _pr.run([sys.executable, str(GATE), str(run_dir)],
                       capture_output=True, text=True)
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


def test_no_library_load_refuses_it_does_not_fail(tmp_path):
    """A target declared, a PDK staged, and NOTHING loaded — vibe-ic#1002.

    THIS TEST REVERSES A DECISION THIS FILE USED TO PIN. Through #710 the same
    fixture asserted ``rc == 1``: the gate printed "0 librar(ies) across 0
    log(s) — nothing to compare" and then returned FAIL. That is the shape
    ``gate_zero_denominator_refuses_check`` exists to name — a zero beside a
    POPULATION word is not a result — and the repo rejects it elsewhere. A FAIL
    says "I looked and it was wrong"; this state looked at nothing.

    The refusal must NAME what it lacked, which is the other half of the house
    rule: rc 2 alone is a shrug.
    """
    r = _mk(tmp_path, target="Example Foundry ZQ42-K3",
            staged=["zq42k3_sc.lib"], loaded=[])
    rc, out = _run(r)
    assert rc == 2, out
    assert "NOT CHECKED" in out, out
    # it must not state a conclusion it has no evidence for, in either direction
    assert "was not the one used" not in out, out
    assert "whatever library was available" not in out, out
    assert "PASS" not in out, out
    # and it must say what it lacked
    assert "MISSING" in out, out
    assert "cell-library load" in out, out


def test_the_refusal_is_machine_readable(tmp_path):
    """A caller must be able to tell "not asked" from "asked and answered"."""
    rec = tmp_path / "rec.json"
    r = _mk(tmp_path, target="Example Foundry ZQ42-K3",
            staged=["zq42k3_sc.lib"], loaded=[])
    p = _pr.run([sys.executable, str(GATE), str(r), "--json", str(rec)],
                       capture_output=True, text=True)
    assert p.returncode == 2, p.stdout + p.stderr
    d = json.loads(rec.read_text())
    assert d["verdict"] == "NOT CHECKED"
    assert d["no_library_load_recorded"] is True
    assert d["libraries_loaded"] == []
    assert "cell-library load" in d["missing_input"]
    # the declaration it could not judge is still recorded, so the refusal is
    # actionable rather than merely quiet
    assert d["declared_target"] == "Example Foundry ZQ42-K3"


def test_refusing_the_empty_case_does_not_disarm_the_motivating_defect(tmp_path):
    """The docstring's own case: the PDK vanished and PnR ran on the image's.

    This is the CONTROL for the change above. The motivating defect always
    leaves library names in the log — it is a load that happened, of the wrong
    library — so it can never reach the refusal branch. If this ever goes green
    at rc 2, the refusal has been widened past its evidence.
    """
    r = _mk(tmp_path, target="Example Foundry ZQ42-K3",
            staged=[], loaded=["othernode_fd_sc_hd.lef",
                               "othernode_fd_sc_hd__tt.lib"])
    rc, out = _run(r)
    assert rc == 1, out
    assert "NO PDK is staged" in out, out


def test_a_declaration_contradicted_by_a_real_load_still_fails(tmp_path):
    """The one substantive corpus red's shape: staged, loaded, contradicted."""
    r = _mk(tmp_path, target="Example Foundry ZQ42-K3",
            staged=["zq42k3_sc.lib"], loaded=["othernode_fd_sc_hd.lef"])
    rc, out = _run(r)
    assert rc == 1, out
    assert "was not the one used" in out, out


def test_a_wrong_pdk_still_reports_a_wrong_pdk(tmp_path):
    """Control: the new branch must not swallow the case it sits in front of."""
    rec = tmp_path / "rec.json"
    r = _mk(tmp_path, target="Example Foundry ZQ42-K3",
            staged=["zq42k3_sc.lib"], loaded=["othernode_fd_sc_hd.lef"])
    p = _pr.run([sys.executable, str(GATE), str(r), "--json", str(rec)],
                       capture_output=True, text=True)
    assert p.returncode == 1, p.stdout + p.stderr
    assert "was not the one used" in p.stdout
    d = json.loads(rec.read_text())
    assert d["no_library_load_recorded"] is False


def test_a_pass_records_the_field_too(tmp_path):
    """The field is present on every answered verdict, not only on the new one."""
    rec = tmp_path / "rec.json"
    r = _mk(tmp_path, target="Example Foundry ZQ42-K3",
            staged=["zq42k3_sc.lib"], loaded=["zq42k3_sc.lef"])
    p = _pr.run([sys.executable, str(GATE), str(r), "--json", str(rec)],
                       capture_output=True, text=True)
    assert p.returncode == 0, p.stdout + p.stderr
    assert json.loads(rec.read_text())["no_library_load_recorded"] is False


# ── vibe-ic#709 / #713 — a partial match is not a declaration ───────────────
# Synthetic names throughout: no real PDK, foundry or part number appears.

import sys as _sys, tempfile as _tf, json as _json
from pathlib import Path as _P

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import _progress_run as _pr  # noqa: E402

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
    r = _pr.run([_sys.executable, str(_GATE), str(root), "--json", str(out)],
                capture_output=True, text=True)
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
