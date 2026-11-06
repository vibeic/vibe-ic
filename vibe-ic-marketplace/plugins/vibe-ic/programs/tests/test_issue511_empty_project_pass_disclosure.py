#!/usr/bin/env python3
"""#511 — a gate that examined NOTHING must not render as PASS.

THE MEASUREMENT THAT OPENED THIS
=================================
A deterministic sample of 41 of the 481 `programs/*_check.py`, each driven
against a structurally empty project (`input/docs/` and `reports/` created,
nothing in them), found two whose ENTIRE output was one line:

    [PASS] analog_flow_compliance_check
    [PASS] analog_netlist_include_order_check

rc 0, no report file written, no count, no reason. `analog_netlist_include_
order_check` printed the SAME line over a real corpus project carrying two
SPICE decks, so "the include order is correct" and "there was no netlist" were
byte-identical to every consumer of either channel.

WHAT IS PINNED HERE
====================
1. Both gates now disclose, and the empty case is rc 2 / VACUOUS_PASS with a
   `_gate_denominator` denominator on stdout, on stderr and in the report.
2. `dead_plugin_path_check`'s zero grew a denominator — the decision #511 asked
   for, recorded in the program and pinned here.
3. THE STANDING CHECK: `gate_discloses_denominator_check --population project`
   drives EVERY `*_check.py` against an empty project. Its dated inventory is
   its own denominator, and this file proves the ratchet fires in BOTH
   directions — a new silent gate cannot be absorbed, and a fixed one cannot
   stay on the list.
4. NO GATE GOT QUIETER: every rejection the three gates made before, they still
   make.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

PROGRAMS = Path(__file__).resolve().parent.parent
ORDER = PROGRAMS / "analog_netlist_include_order_check.py"

sys.path.insert(0, str(PROGRAMS))
import _gate_denominator as GDEN  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import _progress_run as _pr  # noqa: E402


# ── helpers ────────────────────────────────────────────────────────────────

def _empty_project(tmp_path: Path, name: str = "proj") -> Path:
    """A structurally empty project: the two directories a run scaffolds, and
    nothing else in them."""
    proj = tmp_path / name
    (proj / "input" / "docs").mkdir(parents=True)
    (proj / "reports").mkdir(parents=True)
    return proj


def _run(prog: Path, cwd: Path, *args: str) -> subprocess.CompletedProcess:
    """Drive a gate and capture its exit code DIRECTLY. Never through a pipe:
    a piped rc is the pipe's, not the gate's."""
    return _pr.run([sys.executable, str(prog), *args],
                          cwd=str(cwd), capture_output=True, text=True)


# ── 1. the two measured instances: empty project ───────────────────────────





# ── 2. no gate got quieter: the populated cases ────────────────────────────

def _analog_project_with_blocks(tmp_path: Path, blocks) -> Path:
    proj = _empty_project(tmp_path, "analog")
    bl = proj / "phase3" / "analog" / "analog_block_list.json"
    bl.parent.mkdir(parents=True)
    bl.write_text(json.dumps(list(blocks)))
    return proj


def test_flow_gate_still_fails_a_project_with_a_missing_a_step(tmp_path):
    """The rule the gate exists for, unchanged: a declared block with no A-step
    artefact is rc 1 with nine MISSING findings."""
    proj = _analog_project_with_blocks(tmp_path, ["osc"])
    out = proj / "r.json"
    rep = json.loads(out.read_text())
    assert rep["verdict"] == "FAIL"
    assert rep["passed"] is False
    assert rep["summary"]["total_missing"] == 9
    assert {f["rule"] for f in rep["findings"]} >= {"ANALOG_A1_MISSING"}




def test_fpga_stub_waiver_still_promotes_a_real_fail(tmp_path):
    """`--allow-fpga-stub` promotes exactly what it promoted before: a FAIL
    with missing per-block artefacts."""
    proj = _analog_project_with_blocks(tmp_path, ["osc"])
    out = proj / "r.json"
    rep = json.loads(out.read_text())
    assert rep["verdict"] == "PASS_WITH_WAIVERS"
    assert rep["summary"]["fpga_stub_waiver_applied"] is True


def test_fpga_stub_waiver_does_not_dress_a_vacuous_run_as_waived(tmp_path):
    """…and NOT what it never could: the waiver guard used to read
    `not result.passed`, and #511 made a vacuous run's `passed` False. Keyed on
    the VERDICT instead, so an unexamined project cannot come out wearing
    PASS_WITH_WAIVERS — there was nothing to waive."""
    proj = _empty_project(tmp_path, "stub_vacuous")
    out = proj / "r.json"
    rep = json.loads(out.read_text())
    assert rep["verdict"] == "VACUOUS_PASS"
    assert "fpga_stub_waiver_applied" not in rep["summary"]


def test_order_gate_still_fails_lib_before_include(tmp_path):
    """The ordering rule, unchanged: rc 1 and the same finding."""
    proj = _empty_project(tmp_path, "order_bad")
    d = proj / "analog" / "amp"
    d.mkdir(parents=True)
    (d / "amp.sp").write_text(
        "* deck\n"
        ".lib /pdk/libs.tech/ngspice/sm141064.ngspice typical\n"
        ".include /pdk/libs.tech/ngspice/design.ngspice\n")
    out = proj / "r.json"
    r = _run(ORDER, proj, ".", "--json", str(out))
    assert r.returncode == 1
    rep = json.loads(out.read_text())
    assert rep["verdict"] == "FAIL"
    assert "LIB_BEFORE_DESIGN_INCLUDE" in {f["rule"] for f in rep["findings"]}


def test_order_gate_pass_now_states_how_many_decks_it_read(tmp_path):
    """The sharpest half of #511: the clean case used to print the SAME line as
    the empty case. Two decks read must be visible as two."""
    proj = _empty_project(tmp_path, "order_ok")
    d = proj / "analog" / "amp"
    d.mkdir(parents=True)
    good = ("* deck\n"
            ".include /pdk/libs.tech/ngspice/design.ngspice\n"
            ".lib /pdk/libs.tech/ngspice/sm141064.ngspice typical\n")
    (d / "a.sp").write_text(good)
    (d / "b.sp").write_text(good)

    r = _run(ORDER, proj, ".")
    assert r.returncode == 0, r.stdout + r.stderr
    first = r.stdout.strip().splitlines()[0]
    assert first.startswith("[PASS] analog_netlist_include_order_check:")
    assert "examined 2" in first, first
    # The empty-project line for the same gate must not be a prefix of this
    # one: distinguishability is the whole point.
    empty = _run(ORDER, _empty_project(tmp_path, "order_empty"), ".")
    assert empty.stdout.strip() != r.stdout.strip()
    assert empty.returncode != r.returncode


def test_order_gate_non_directory_still_exits_2(tmp_path):
    r = _run(ORDER, tmp_path, str(tmp_path / "nope"))
    assert r.returncode == 2


# ── 3. dead_plugin_path_check: the recorded decision ───────────────────────







# ── 4. the disclosure predicate: the underscore-boundary repair ────────────





# ── 5. the standing check itself ───────────────────────────────────────────

def test_standing_check_drives_every_gate_and_passes(tmp_path):
    """Drives the program, not a re-implementation of it.

    Runtime measured on the authoring host: ~2.5s for all 481 gates at 8
    workers, one throwaway project each.
    """
    out = tmp_path / "pop.json"
    rep = json.loads(out.read_text())
    assert rep["verdict"] == "PASS"
    assert rep["findings"] == []

    # The census is real: the population is the whole registry, not a sample.
    #
    # WAS `len(PROGRAMS.glob("*_check.py"))`, and that line was the second half
    # of the #511 defect: it agreed with the check because BOTH said the
    # registry was one filename. `analog_netlist_path_lint` — a gate the A3
    # producer drives beside two `*_check.py` — printed the same bare `[PASS]`
    # over a clean deck and over nothing for as long as this check existed, and
    # neither the check nor this test could see it. The expectation is now
    # DERIVED the same way the population is, from the two sources in the tree.
    assert rep["gates_probed"] > 400, rep["gates_probed"]
    # …and it is strictly wider than the filename it used to be, so a run that
    # silently fell back to that glob would fail here rather than look clean.
    defn = rep["population_definition"]
    assert defn["degraded"] is False, defn
    assert defn["by_suffix"] and defn["by_behaviour"], defn
    assert rep["rc_zero"] > 0
    assert (rep["rc_zero_disclosing"] + rep["rc_zero_silent"]
            == rep["rc_zero"])
    # Every silent gate is on ONE of the two dated exemption lists and nowhere
    # else — exact-set equality in both directions, which is the mechanism: a
    # new silent gate cannot be absorbed and a fixed one cannot stay listed.
    # The second list arrived with the derived population: a population chosen
    # by RELATION reaches programs a project fixture cannot address at all, and
    # those are a different fact about the program from "it went silent".
    exempt = set(rep["inventory"]) | set(rep["not_project_driven"])
    assert set(rep["silent_gates"]) == exempt, (rep["silent_gates"], exempt)
    assert not (set(rep["inventory"])
                & set(rep["not_project_driven"])), (
        "a program on both lists has two different reasons on the record")


def test_number_only_disclosure_passes_and_is_published_not_hidden(tmp_path):
    """THE DECISION, made explicitly rather than by omission: a gate that
    discloses with a bare COUNT passes this check — a count IS a denominator,
    and it is the line the CI population has drawn since #447. What the count
    does not buy is silence about how many gates rely on it, so the residual is
    a published number.

    MEASURED 2026-07-28 over all 481: 202 rc-0 before this change, of which 151
    stated a reason, 34 disclosed with a number only, 17 disclosed nothing.
    """
    out = tmp_path / "pop.json"
    rep = json.loads(out.read_text())
    assert (rep["rc_zero_reasoned"] + rep["rc_zero_number_only"]
            == rep["rc_zero_disclosing"])
    assert rep["rc_zero_number_only"] > 0, (
        "if this is 0 the distinction has stopped being measured")
    # The residual is NAMED, not just counted.
    assert len(rep["number_only_gates"]) == rep["rc_zero_number_only"]
    assert rep["rc_zero_number_only_decision"]
    # …and visible without opening the JSON.




def test_rc_outside_the_convention_is_recorded_not_folded_in(tmp_path):
    """Three gates exit 3 over an empty project. That is not a disclosure
    defect and this check does not judge it — but the census must have no
    unexplained residue, so they are named."""
    out = tmp_path / "pop.json"
    rep = json.loads(out.read_text())
    odd = rep["rc_outside_convention"]
    assert odd, "the recorded case has gone empty — re-measure before deleting"
    assert all(e["rc"] not in (0, 1, 2) and e["note"] for e in odd)






def _fake_programs_dir(tmp_path: Path) -> Path:
    d = tmp_path / "fake_programs"
    d.mkdir()
    return d


def _write_gate(d: Path, name: str, body: str) -> None:
    (d / f"{name}.py").write_text(
        "#!/usr/bin/env python3\nimport sys\n" + body + "\n")


def test_inventory_cannot_grow_silently(tmp_path):
    """THE DEFECT THIS CHECK EXISTS TO CATCH, injected.

    A NEW gate that answers a bare PASS over an empty project must fail the
    check by name — it must not be quietly absorbed."""
    d = _fake_programs_dir(tmp_path)
    _write_gate(d, "brand_new_silent_check",
                'print("[PASS] brand_new_silent_check")\nsys.exit(0)')
    out = tmp_path / "r.json"
    rep = json.loads(out.read_text())
    kinds = {(f["gate"], f["kind"]) for f in rep["findings"]}
    assert ("brand_new_silent_check", "PASS_WITHOUT_DENOMINATOR") in kinds


def test_a_disclosing_gate_is_not_flagged(tmp_path):
    """The check must not fire on legitimate state: a gate that DOES disclose
    over an empty project passes. Without this the previous test would also
    pass for a check that simply rejects everything."""
    d = _fake_programs_dir(tmp_path)
    _write_gate(d, "brand_new_disclosing_check",
                'print("[VACUOUS_PASS] brand_new_disclosing_check: examined 0 '
                'widget(s) — no widget in this project")\nsys.exit(0)')
    out = tmp_path / "r.json"
    rep = json.loads(out.read_text())
    flagged = {f["gate"] for f in rep["findings"]
               if f["kind"] == "PASS_WITHOUT_DENOMINATOR"}
    assert "brand_new_disclosing_check" not in flagged






def _synthetic_ci_repo(tmp_path: Path, lines) -> Path:
    """A repo root carrying only a `tools/ci/repo_hygiene_gates.sh` with the
    given `run` lines.

    Driving the CI population against the REAL script takes ~57s (it re-runs
    every repo-hygiene gate, worktree probes included) and, because that set is
    currently clean, it can only ever prove the PASS branch. A synthetic script
    exercises the same parse → expand → drive → classify path in milliseconds
    AND can prove the FAIL branch, which the real one cannot.
    """
    root = tmp_path / "repo"
    (root / "tools" / "ci").mkdir(parents=True)
    (root / "tools" / "ci" / "repo_hygiene_gates.sh").write_text(
        "#!/usr/bin/env bash\n" + "\n".join(lines) + "\n")
    return root


def test_ci_population_still_flags_a_silent_gate(tmp_path):
    """The first population's rule, still enforced, and now proven on the
    branch the real gate set cannot reach."""
    probe = tmp_path / "silent_probe.py"
    probe.write_text("print('[PASS] silent_probe')\n")
    root = _synthetic_ci_repo(
        tmp_path, [f'run "silent probe" "$PLUGIN" python3 {probe}'])
    out = tmp_path / "ci.json"
    rep = json.loads(out.read_text())
    assert rep["population"] == "ci"
    assert [f["kind"] for f in rep["findings"]] == ["PASS_WITHOUT_DENOMINATOR"]


def test_ci_population_accepts_a_disclosing_gate(tmp_path):
    """…and does not fire on legitimate state, which is what keeps the
    previous test from passing for a check that rejects everything."""
    probe = tmp_path / "disclosing_probe.py"
    probe.write_text("print('PASS — examined 0 file(s): none present')\n")
    root = _synthetic_ci_repo(
        tmp_path, [f'run "disclosing probe" "$PLUGIN" python3 {probe}'])
    out = tmp_path / "ci.json"
    rep = json.loads(out.read_text())
    assert rep["verdict"] == "PASS"
    assert rep["gates_probed"] == 1
