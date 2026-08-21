#!/usr/bin/env python3
"""The four fixtures for `ppa_problem_integrity_check` — the comparison gate.

WHAT IT IS PROTECTING
=====================
"The candidate is 12% smaller" is true and meaningless if the candidate ran at
a different clock, against a different corner, or from a spec somebody edited
between the two runs. Nothing in the 12% says so. This program is the thing
that says so, and these are the cases that prove it says so when it should and
stays quiet when it should not.

    problem         identical      or the two arms ran different contests
    analysis        identical      or the two numbers are not the same metric
    toolchain       identical      or the difference may be the tools
    implementation  DIFFERENT      or the difference is measurement noise

Each red case below is the green pair with ONE thing moved.

chip-AGNOSTIC: synthetic bytes and declared policy.
"""
from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from test_ppa_contract_fixtures import (  # noqa: E402
    BUILD, INTEGRITY, base_declaration, codes, make_run_tree, run_cli,
    write_json,
)


def _build_arm(tmp_path: Path, name: str, declaration=None,
               mutate_tree=None) -> Path:
    """One arm of a comparison: its own run tree, its own contract."""
    root = make_run_tree(tmp_path / name)
    if mutate_tree is not None:
        mutate_tree(root)
    decl = write_json(tmp_path / f"{name}.declaration.json",
                      declaration or base_declaration())
    out = tmp_path / f"{name}.contract.json"
    proc = run_cli(BUILD, "--declaration", str(decl), "--root", str(root),
                   "--out", str(out), "--no-image-labels")
    assert proc.returncode in (0, 1, 2), proc.stderr
    return out


def _different_rtl(root: Path) -> None:
    """The one axis a PPA experiment is allowed to move."""
    (root / "rtl" / "top.v").write_text(
        "module top(input clk); reg q; always @(posedge clk) q <= ~q;\n"
        "endmodule\n")


def _comparable_pair(tmp_path: Path):
    baseline = _build_arm(tmp_path, "baseline")
    candidate = _build_arm(tmp_path, "candidate", mutate_tree=_different_rtl)
    return baseline, candidate


# ---------------------------------------------------------------------------
# positive
# ---------------------------------------------------------------------------

def test_two_arms_that_differ_only_in_implementation_are_comparable(tmp_path):
    baseline, candidate = _comparable_pair(tmp_path)
    verdict = run_cli(INTEGRITY, "--baseline", str(baseline),
                      "--candidate", str(candidate))
    assert verdict.returncode == 0, (
        f"a legitimate comparison was refused:\n{verdict.stdout}\n"
        f"{verdict.stderr}")
    assert "[PASS]" in verdict.stdout


# ---------------------------------------------------------------------------
# negative
# ---------------------------------------------------------------------------

def test_a_moved_problem_is_refused_and_names_what_moved(tmp_path):
    baseline = _build_arm(tmp_path, "baseline")
    candidate = _build_arm(
        tmp_path, "candidate",
        mutate_tree=lambda root: (
            _different_rtl(root),
            (root / "spec" / "constraints.sdc").write_text(
                "create_clock -name clk -period 8.0 [get_ports clk]\n")))
    verdict = run_cli(INTEGRITY, "--baseline", str(baseline),
                      "--candidate", str(candidate))
    assert verdict.returncode == 1, (
        f"a candidate built against a different SDC must be refused, got rc="
        f"{verdict.returncode}\n{verdict.stdout}\n{verdict.stderr}")
    text = verdict.stdout + verdict.stderr
    assert "PPA-C-012" in text
    assert "problem identity DIFFERS" in text
    assert "artefact sdc" in text, (
        f"the refusal does not name WHICH member moved:\n{text}")


def test_a_moved_analysis_corner_is_refused(tmp_path):
    baseline = _build_arm(tmp_path, "baseline")
    moved = copy.deepcopy(base_declaration())
    moved["analysis"]["facts"][0]["value"] = "fast"
    candidate = _build_arm(tmp_path, "candidate", declaration=moved,
                           mutate_tree=_different_rtl)
    verdict = run_cli(INTEGRITY, "--baseline", str(baseline),
                      "--candidate", str(candidate))
    assert verdict.returncode == 1, verdict.stdout + verdict.stderr
    assert "PPA-C-012" in codes(verdict)
    text = verdict.stdout + verdict.stderr
    assert "analysis.corner" in text and "slow" in text and "fast" in text


def test_a_moved_toolchain_is_refused(tmp_path):
    baseline = _build_arm(tmp_path, "baseline")
    moved = copy.deepcopy(base_declaration())
    moved["toolchain"]["images"][0]["ref"] = (
        "ghcr.io/vibeic-test/contract-fixture@sha256:" + "2" * 64)
    candidate = _build_arm(tmp_path, "candidate", declaration=moved,
                           mutate_tree=_different_rtl)
    verdict = run_cli(INTEGRITY, "--baseline", str(baseline),
                      "--candidate", str(candidate))
    assert verdict.returncode == 1, verdict.stdout + verdict.stderr
    assert "PPA-C-012" in codes(verdict)
    assert "toolchain identity DIFFERS" in (verdict.stdout + verdict.stderr)


def test_an_identical_implementation_is_undetermined_not_a_result(tmp_path):
    """Both arms byte-identical. Any difference in their numbers is noise, so
    the comparison must not be reported as clean."""
    baseline = _build_arm(tmp_path, "baseline")
    candidate = _build_arm(tmp_path, "candidate")
    verdict = run_cli(INTEGRITY, "--baseline", str(baseline),
                      "--candidate", str(candidate))
    assert verdict.returncode == 2, verdict.stdout + verdict.stderr
    assert "PPA-C-013" in codes(verdict)
    assert "[CANNOT CHECK]" in verdict.stderr


def test_an_identical_implementation_can_be_promoted_to_a_refusal(tmp_path):
    baseline = _build_arm(tmp_path, "baseline")
    candidate = _build_arm(tmp_path, "candidate")
    verdict = run_cli(INTEGRITY, "--baseline", str(baseline),
                      "--candidate", str(candidate),
                      "--require-implementation-differs")
    assert verdict.returncode == 1, verdict.stdout + verdict.stderr
    assert "PPA-C-013" in codes(verdict)


def test_the_second_detector_fires_on_a_declared_forbidden_mutation(tmp_path):
    """A mutation OUTSIDE the allow-list is caught here even when the arms'
    problem identities happen to match — the two detectors do not share code,
    so one being silenced cannot silence the other."""
    baseline = _build_arm(tmp_path, "baseline")
    declared = copy.deepcopy(base_declaration())
    declared["candidate"]["mutations"] = [
        {"target": "constraints.clk.period_ns", "from": 10.0, "to": 8.0}]
    candidate = _build_arm(tmp_path, "candidate", declaration=declared,
                           mutate_tree=_different_rtl)
    verdict = run_cli(INTEGRITY, "--baseline", str(baseline),
                      "--candidate", str(candidate))
    assert verdict.returncode == 1, verdict.stdout + verdict.stderr
    assert "PPA-C-005" in codes(verdict)


def test_a_contract_edited_after_it_was_built_is_refused(tmp_path):
    baseline, candidate = _comparable_pair(tmp_path)
    document = json.loads(candidate.read_text())
    document["run_label"] = "quietly changed"
    candidate.write_text(json.dumps(document))
    verdict = run_cli(INTEGRITY, "--baseline", str(baseline),
                      "--candidate", str(candidate))
    assert verdict.returncode == 1, verdict.stdout + verdict.stderr
    assert "PPA-C-001" in codes(verdict)


def test_a_not_measured_identity_is_undetermined_not_a_match(tmp_path):
    """Two runs that each failed to measure something are not the same run."""
    broken = copy.deepcopy(base_declaration())
    broken["problem"]["artefacts"].append(
        {"role": "missing", "path": "spec/never_written.json"})
    baseline = _build_arm(tmp_path, "baseline", declaration=broken)
    candidate = _build_arm(tmp_path, "candidate", declaration=broken,
                           mutate_tree=_different_rtl)
    verdict = run_cli(INTEGRITY, "--baseline", str(baseline),
                      "--candidate", str(candidate))
    assert verdict.returncode == 2, verdict.stdout + verdict.stderr
    assert "PPA-C-007" in codes(verdict)
    assert "[CANNOT CHECK]" in verdict.stderr


# ---------------------------------------------------------------------------
# vacuous
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("which", ["baseline", "candidate"])
def test_an_absent_contract_cannot_check(tmp_path, which):
    baseline, candidate = _comparable_pair(tmp_path)
    args = {"baseline": str(baseline), "candidate": str(candidate)}
    args[which] = str(tmp_path / "nope.json")
    verdict = run_cli(INTEGRITY, "--baseline", args["baseline"],
                      "--candidate", args["candidate"])
    assert verdict.returncode == 2, (
        f"an absent {which} contract must be rc=2, not {verdict.returncode}; "
        f"rc=1 would be a claim that two designs were incomparable when "
        f"neither was read")
    assert "[CANNOT CHECK]" in verdict.stderr


def test_a_document_that_is_not_a_contract_cannot_check(tmp_path):
    baseline, _ = _comparable_pair(tmp_path)
    other = write_json(tmp_path / "other.json", {"schema": "something.else.v1"})
    verdict = run_cli(INTEGRITY, "--baseline", str(baseline),
                      "--candidate", str(other))
    assert verdict.returncode == 2, verdict.stdout + verdict.stderr
    assert "PPA-C-010" in codes(verdict)


def test_unparseable_json_cannot_check(tmp_path):
    baseline, _ = _comparable_pair(tmp_path)
    bad = tmp_path / "bad.json"
    bad.write_text("{not json")
    verdict = run_cli(INTEGRITY, "--baseline", str(baseline),
                      "--candidate", str(bad))
    assert verdict.returncode == 2
    assert "[CANNOT CHECK]" in verdict.stderr


def test_nothing_is_written_unless_json_is_asked_for(tmp_path):
    baseline, candidate = _comparable_pair(tmp_path)
    before = sorted(p.name for p in tmp_path.iterdir())
    run_cli(INTEGRITY, "--baseline", str(baseline), "--candidate", str(candidate))
    assert sorted(p.name for p in tmp_path.iterdir()) == before

    out = tmp_path / "report.json"
    run_cli(INTEGRITY, "--baseline", str(baseline), "--candidate",
            str(candidate), "--json", str(out))
    report = json.loads(out.read_text())
    assert report["program"] == "ppa_problem_integrity_check"
    assert report["rc"] == 0


# ── F-13: which artefacts belong to `analysis` ──────────────────────────────
# PPA_INTERFACES §3.1. An artefact that varies with the implementation may not
# sit in `analysis`. The rule was implicit until v1.11.33 and its most natural
# reading -- "analysis artefacts" = "the artefacts the analysis produced" --
# makes the gate refuse EVERY legitimate comparison, because sign-off reports
# are outputs of the implementation and of course they differ.

def _different_rtl_and_its_sta(root: Path) -> None:
    """What really happens: change the RTL and the STA report changes too.

    The stock `_different_rtl` moves only `rtl/top.v`, so the misfiled report
    stays byte-identical and the defect stays hidden. A design whose RTL moved
    and whose timing report did NOT is not a run anybody has.
    """
    _different_rtl(root)
    (root / "sta" / "setup.rpt").write_text("wns -0.087\n")


def test_a_report_declared_under_analysis_is_named_as_MISFILED(tmp_path):
    """The negative arm. Two runs that ARE comparable -- same problem, same
    toolchain, different implementation -- are refused because a sign-off
    report was declared under `analysis`, and the reader must be told that is
    the cause rather than handed a bare digest mismatch."""
    baseline = _build_arm(tmp_path, "baseline")
    candidate = _build_arm(tmp_path, "candidate",
                           mutate_tree=_different_rtl_and_its_sta)
    verdict = run_cli(INTEGRITY, "--baseline", str(baseline),
                      "--candidate", str(candidate),
                      "--require-implementation-differs")
    assert verdict.returncode == 1, verdict.stdout + verdict.stderr
    seen = codes(verdict)
    assert "PPA-C-012" in seen, seen
    assert "PPA-C-016" in seen, (
        "the analysis identity moved WITH the implementation and nothing said "
        "the artefact was misfiled:\n" + verdict.stdout + verdict.stderr)
    text = verdict.stdout + verdict.stderr
    assert "sta_setup" in text, text
    assert "may not sit in `analysis`" in text, text


def test_moving_that_report_to_implementation_makes_the_pair_COMPARABLE(tmp_path):
    """The positive arm, and the whole point of the rule: with `analysis`
    holding the measurement CONFIGURATION only and the report moved to
    `implementation`, the same two runs compare cleanly. Nothing about the runs
    changed -- only where the artefact was declared."""
    fixed = copy.deepcopy(base_declaration())
    report = fixed["analysis"]["artefacts"].pop()
    assert report["role"] == "sta_setup", report
    fixed["implementation"]["artefacts"].append(report)

    baseline = _build_arm(tmp_path, "baseline", declaration=fixed)
    candidate = _build_arm(tmp_path, "candidate", declaration=fixed,
                           mutate_tree=_different_rtl_and_its_sta)
    verdict = run_cli(INTEGRITY, "--baseline", str(baseline),
                      "--candidate", str(candidate),
                      "--require-implementation-differs")
    assert verdict.returncode == 0, verdict.stdout + verdict.stderr
    assert "PPA-C-016" not in codes(verdict)
    assert "PPA-C-012" not in codes(verdict)


def test_analysis_moving_ALONE_is_not_reported_as_misfiling(tmp_path):
    """The discriminator. `analysis` differing while the implementation does
    NOT is a real difference in how the two numbers were taken -- a moved
    corner -- and calling that a misfiled artefact would send the reader to fix
    the wrong thing."""
    moved = copy.deepcopy(base_declaration())
    moved["analysis"]["facts"][0]["value"] = "fast"
    baseline = _build_arm(tmp_path, "baseline")
    candidate = _build_arm(tmp_path, "candidate", declaration=moved)
    verdict = run_cli(INTEGRITY, "--baseline", str(baseline),
                      "--candidate", str(candidate))
    assert verdict.returncode == 1, verdict.stdout + verdict.stderr
    assert "PPA-C-012" in codes(verdict)
    assert "PPA-C-016" not in codes(verdict), verdict.stdout + verdict.stderr
