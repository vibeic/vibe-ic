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
    p = subprocess.run([sys.executable, str(GATE), str(run_dir)],
                       capture_output=True, text=True, timeout=120)
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
    """'cells', 'liberty', 'tech' appear in every PDK and carry no identity.

    Nothing is staged here on purpose: with staged files present the comparison
    is filename-to-filename and the declared prose is not consulted at all. This
    exercises the fallback path, which is the only one prose matching serves.
    """
    r = _mk(tmp_path, target="Example Foundry Standard Cell Library",
            staged=[], loaded=["othernode_std_cell_tech.lef"])
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


def test_a_staged_library_counts_even_when_its_name_shares_no_word(tmp_path):
    """The regression that made the first version reject correct work.

    A declared target is a human sentence; a vendor's cell library is named on
    its own convention. They can share no whole word and still be the same PDK.
    Here the declared name and the library name have only a fragment in common,
    and the library is one the design staged for itself — which settles it.
    """
    r = _mk(tmp_path, target="Example Foundry ZQ42-K3 / SL1.9c",
            staged=["mq42kpm180su_typ.lib"], loaded=["mq42kpm180su_typ.lib"])
    rc, out = _run(r)
    assert rc == 0, out
    assert "staged filenames" in out


def test_a_derived_copy_of_a_staged_library_still_counts(tmp_path):
    """The flow re-emits a staged tech LEF with a correction applied.

    It keeps the staged stem and appends to it. That is still the staged PDK.
    """
    r = _mk(tmp_path, target="Example Foundry ZQ42-K3",
            staged=["mq42kpm180su_6lm_tech_v56.lef"],
            loaded=["mq42kpm180su_6lm_tech_v56_topmetal_fix.lef"])
    rc, out = _run(r)
    assert rc == 0, out


def test_a_foreign_library_alongside_the_right_one_is_reported_not_failed(tmp_path):
    """A flow legitimately reads something else for an unrelated step.

    Failing on that would punish correct runs; hiding it would let a substitution
    creep in beside the right PDK. So it is named under a PASS.
    """
    r = _mk(tmp_path, target="Example Foundry ZQ42-K3",
            staged=["mq42kpm180su_typ.lib"],
            loaded=["mq42kpm180su_typ.lib", "othernode_fd_sc_hd.lef"])
    rc, out = _run(r)
    assert rc == 0, out
    assert "also loaded" in out
    assert "othernode_fd_sc_hd.lef" in out


def test_staged_pdk_present_but_none_of_it_loaded_is_fail(tmp_path):
    """Staging a PDK and then implementing against a different one."""
    r = _mk(tmp_path, target="Example Foundry ZQ42-K3",
            staged=["mq42kpm180su_typ.lib"], loaded=["othernode_fd_sc_hd.lef"])
    rc, out = _run(r)
    assert rc == 1, out


def test_an_agent_transcript_at_the_run_root_is_not_a_tool_log(tmp_path):
    """The defect this rule fixes: a name an agent QUOTED, read as a name a tool LOADED.

    `agent.log` records what an agent said, and agents quote filenames while
    analysing other runs. Measured: a run whose every tool log named only the
    declared PDK was reported as also loading a foreign one, because a previous
    round's filename appeared in the agent's own narration.

    Tool logs live under the phase/step tree; transcripts live at the run root.
    """
    r = _mk(tmp_path, target="Example Foundry ZQ42-K3",
            staged=["mq42kpm180su_typ.lib"], loaded=["mq42kpm180su_typ.lib"])
    r.joinpath("agent.log").write_text(
        "Earlier I looked at another round which loaded othernode_fd_sc_hd.lef\n",
        encoding="utf-8")
    rc, out = _run(r)
    assert rc == 0, out
    assert "othernode_fd_sc_hd.lef" not in out
