#!/usr/bin/env python3
"""A step named for hardware verification must not report a bare PASS with none.

Step A9 was named "Co-Simulation / HW Verification" and, on a run carrying cosim
results and ZERO hw_measurements.json, `check_step` returned status PASS with an
empty reasons list — byte-identical in the report to a bench-verified close.

Not MANDATING bench hardware is a deliberate documented decision: the A9 entry in
`flow_condition_reachability_check`'s allowlist calls the exemption "the analog
analogue of --skip-hardware", and requiring a lab measurement would make headless
and CI analog runs permanently unpassable. So the fix is disclosure, not a
mandate — simulation-only closure stays legal, it just stops being silent.

Three things were wrong, and each is pinned below:

 1. The --skip-hardware analogy was never implemented. That routing is guarded by
    `isinstance(sid, int)` and A9's id is the string "A9", so the flag silently
    did nothing for it: step 6 disclosed as WAIVED with review_required while A9
    — the step that actually needs a bench — disclosed nothing.

 2. `analog_a9_hw_verify_check` already judged hw_measurements.json correctly but
    was not wired into A9's own flow gate, so A9's STEP LINE — the line a reader
    checks to learn whether A9 is done — could not see it.

    CORRECTION to the original wording of this file, which said the checker "was
    wired only into analog_one_shot_runner ... so the flow verdict could not see
    it". It is a member of `flow_compliance_check._STRUCTURAL_RTL_GATES`, so the
    P0 umbrella step already ran it and the OVERALL flow verdict already could
    see it — the completed pure-digital ihp-sg13g2 SPM run's own transcript,
    `reports/audit/flow_compliance_check.log` line 55, shows it listed under
    "Step P0: Structural-RTL gates". Only A9's own step line was blind.
    `test_p0_umbrella_already_carried_the_checker` pins the true statement.

 3. The REQUIRED `program_exit_zero` branch did not read the stdout `VACUOUS_PASS:`
    disclosure that the OPTIONAL branch has always read. The shared analog helper
    `_analog_a_check_common.vacuous_pass()` discloses that way while exiting 0, so
    the same program disclosed a skip through an optional slot and was read as a
    bare PASS through a required one. That is general, not A9-specific.

Three more, found by adversarial re-verification of the landed change and pinned
here (v1.7.59):

 4. REGRESSION. The `--skip-hardware` branch for A9 was placed ABOVE `check_step`'s
    `condition` handling, unlike the step-6 branch it copies (step 6 declares no
    condition). A9 DOES declare one, so a design with zero analog content acquired
    a review_required analog-bench waiver — and because any WAIVED count downgrades
    the Overall verdict, an otherwise-clean digital audit run with --skip-hardware
    reported PASS_WITH_WAIVERS. Measured on the completed pure-digital ihp-sg13g2
    SPM run: A9 SKIPPED-CONDITION -> WAIVED, WAIVED 1 -> 2, SKIPPED 18 -> 17.

 5. The disclosure fired only when ZERO declared blocks were measured. Three
    declared blocks with one `hw_measurements.json` gave `PASS: ... 1/3 block(s)
    clean`, rc 0, no token — the bare PASS this file's title condemns, with two
    declared blocks carrying no bench evidence at all. Same family v1.7.49 (A5)
    and v1.7.51 (A1-A4) closed; A9 was left out.

 6. The landed YAML comment described the no-block-measured tier as "rc 2, which
    check_step surfaces as VACUOUS_PASS". Measured rc is 0 — `vacuous_pass()`
    prints the token and returns 0; rc 2 (`artefact_missing_for_block`) exists
    only in `--block` mode, which the wired command never uses. Had the tier
    really been rc 2, the required branch would already have handled it via
    `__VACUOUS_HINT__` and defect 3 would not have existed.
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

_PROGRAMS = Path(__file__).resolve().parents[1]
if str(_PROGRAMS) not in sys.path:
    sys.path.insert(0, str(_PROGRAMS))

import flow_compliance_check as FCC  # noqa: E402

_FLOW = _PROGRAMS.parent / "flow" / "phase1_phase2_phase3.yaml"
_CHECKER = _PROGRAMS / "analog_a9_hw_verify_check.py"
_A_TRACK_DOC = (_PROGRAMS.parent / "skills" / "analog-flow-orchestrate"
                / "SKILL.md")


def _a9() -> dict:
    doc = yaml.safe_load(_FLOW.read_text())
    return next(s for s in doc["steps"] if str(s.get("id")) == "A9")


def _a_track_doc_rows() -> list[tuple[str, str, str, str]]:
    """(step id, label, skill cell, gate cell) for every A-row of the canonical
    A1-A9 reference table in skills/analog-flow-orchestrate/SKILL.md."""
    rows = []
    for line in _A_TRACK_DOC.read_text(encoding="utf-8").splitlines():
        m = re.match(r"\|\s*(A\d)\s*\|", line)
        if not m:
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) >= 4:
            rows.append((m.group(1), cells[1], cells[2], cells[3]))
    assert rows, f"no A-track rows parsed from {_A_TRACK_DOC}"
    return rows


def _a9_doc_row() -> tuple[str, str, str, str]:
    return next(r for r in _a_track_doc_rows() if r[0] == "A9")


def _wired_programs(step: dict) -> set[str]:
    """Program basenames a step's gate really invokes, at any nesting depth."""
    found: set[str] = set()

    def walk(node) -> None:
        if isinstance(node, dict):
            for key, val in node.items():
                if key in ("program_exit_zero", "json_field_true") \
                        and isinstance(val, str):
                    found.add(val.split()[0])
                elif key == "command" and isinstance(val, str):
                    found.add(val.split()[0])
                else:
                    walk(val)
        elif isinstance(node, list):
            for item in node:
                walk(item)

    walk(step.get("gate") or {})
    return found


def _project(tmp_path: Path, hw: dict | None) -> Path:
    """A cosim-complete analog project; `hw` None == no bench measurement."""
    (tmp_path / "phase1" / "analog").mkdir(parents=True)
    (tmp_path / "phase3" / "analog" / "blk1").mkdir(parents=True)
    (tmp_path / "phase3" / "mixed_signal" / "cosim").mkdir(parents=True)
    blocks = json.dumps({"blocks": [{"name": "blk1"}]})
    (tmp_path / "phase1" / "analog" / "analog_block_list.json").write_text(blocks)
    (tmp_path / "phase3" / "analog" / "analog_block_list.json").write_text(blocks)
    cosim = tmp_path / "phase3" / "mixed_signal" / "cosim"
    (cosim / "mixed_signal_results.json").write_text(json.dumps(
        {"scenarios": [{"name": "s1", "status": "PASS"},
                       {"name": "s2", "status": "PASS"}]}))
    (cosim / "blk1_cosim_results.json").write_text(
        json.dumps({"simulation_passed": True}))
    if hw is not None:
        (tmp_path / "phase3" / "analog" / "blk1"
         / "hw_measurements.json").write_text(json.dumps(hw))
    return tmp_path


# ── the defect ───────────────────────────────────────────────────────────────

def test_simulation_only_close_is_not_a_bare_pass(tmp_path):
    """THE defect. Cosim green, no bench measurement anywhere -> the step must
    disclose. Before the fix this was status PASS with reasons == []."""
    p = _project(tmp_path, hw=None)
    assert not list(p.rglob("hw_measurements.json"))
    r = FCC.check_step(p, _a9(), {}, None)
    assert r.status != "PASS", (r.status, r.reasons)
    assert r.status == "VACUOUS_PASS", (r.status, r.reasons)
    assert any("VACUOUS" in x or "vacuous" in x for x in r.reasons), r.reasons


def test_simulation_only_close_is_still_legal(tmp_path):
    """DIRECTION 1, and the whole point of choosing disclosure over a mandate: a
    headless/CI analog run must still be able to close. VACUOUS_PASS is a
    pass-tier verdict — this must NOT become FAIL or MISSING."""
    r = FCC.check_step(_project(tmp_path, hw=None), _a9(), {}, None)
    assert r.status not in ("FAIL", "MISSING"), (r.status, r.reasons)


# ── the checker's own three tiers ────────────────────────────────────────────

def _run_checker(project: Path) -> tuple[int, str]:
    r = subprocess.run([sys.executable, str(_CHECKER), str(project)],
                       capture_output=True, text=True)
    return r.returncode, r.stdout + r.stderr


@pytest.mark.parametrize("hw,rc,token", [
    (None, 0, "VACUOUS_PASS"),                        # never measured
    ({"measurements": {}}, 1, "FAIL"),                # measured, no numbers
    ({"measurements": {"gain_db": 42.1}}, 0, "PASS"),  # really measured
])
def test_checker_tiers(tmp_path, hw, rc, token):
    """The tiers the gate depends on. A checker that could not FAIL would make
    the wiring decorative."""
    got_rc, out = _run_checker(_project(tmp_path, hw=hw))
    assert got_rc == rc, (got_rc, out[:300])
    assert token in out, out[:300]


# ── the general defect: a required gate must read the same disclosure ────────

def test_required_slot_reads_the_stdout_vacuous_disclosure(tmp_path):
    """The optional slot has always honoured a printed `VACUOUS_PASS:` at rc=0;
    the required slot ignored it. Same program, same disclosure, two answers."""
    gate = {"program_exit_zero":
            f"{_CHECKER.name[:-3]} . --json reports/gates/a9.json"}
    passed, reasons = FCC._evaluate_gate(_project(tmp_path, hw=None), gate)
    assert passed is True, reasons
    assert any(x.startswith(FCC._VACUOUS_HINT_PREFIX) for x in reasons), reasons


def test_required_slot_does_not_invent_a_vacuous_signal(tmp_path):
    """DIRECTION 1: a genuinely clean PASS must stay a clean PASS — the stdout
    fallback must key on the disclosure token, not on rc=0."""
    gate = {"program_exit_zero":
            f"{_CHECKER.name[:-3]} . --json reports/gates/a9.json"}
    p = _project(tmp_path, hw={"measurements": {"gain_db": 42.1}})
    passed, reasons = FCC._evaluate_gate(p, gate)
    assert passed is True, reasons
    assert not any(x.startswith(FCC._VACUOUS_HINT_PREFIX) for x in reasons), reasons


# ── the wiring and the naming, pinned ────────────────────────────────────────

def _required_gate_entries(step: dict) -> list[dict]:
    """A9's REQUIRED `program_exit_zero` entries, each on its own.

    Deliberately excludes `optional_program_exit_zero`: A9 wires
    analog_hw_spice_correlation_check behind exactly the
    `phase3/analog/*/hw_measurements.json` glob, so any fixture that carries a
    measurement file activates it and it fails for want of SPICE-correlation
    data — on the pre-#461 tree as well as this one. A whole-step assertion is
    therefore a free-rider that survives every mutant. Isolate the required
    slot, which is where the bench-substance judgement has to land.
    """
    return [e for e in ((step.get("gate") or {}).get("all_of") or [])
            if isinstance(e, dict) and isinstance(e.get("program_exit_zero"), str)]


def test_a9_gate_actually_runs_the_hw_verify_checker(tmp_path):
    """BEHAVIOURAL, not a YAML substring.

    The original form asserted the literal string "analog_a9_hw_verify_check"
    appears in A9's serialised gate. That passes any mutant that keeps the name
    and rejects any CORRECT alternative fix reaching the same judgement under a
    different program name. The observable property is what matters: at least
    one REQUIRED entry of A9's gate must react to hw_measurements.json
    SUBSTANCE. Feed it a block whose measurement file has an evidence key but NO
    numeric measurement — a state mixed_signal_cosim_check cannot see, since the
    cosim artefacts are green throughout — and some required entry must refuse.
    """
    p = _project(tmp_path, hw={"scope_capture": "cap.png"})   # no numerics
    entries = _required_gate_entries(_a9())
    assert entries, "A9 declares no required program_exit_zero entry at all"
    verdicts = {e["program_exit_zero"].split()[0]: FCC._evaluate_gate(p, e)[0]
                for e in entries}
    assert any(v is False for v in verdicts.values()), (
        verdicts,
        "every required entry of A9's gate passed on a block whose "
        "hw_measurements.json carries no numeric measurement — nothing "
        "required is judging bench-data substance")


def test_p0_umbrella_already_carried_the_checker():
    """The TRUE, narrower statement of what the wiring changed.

    `analog_a9_hw_verify_check` is on the P0 umbrella's gate roster, so that
    step already ran it and the OVERALL flow verdict already saw its rc=1 FAIL
    tier. What was blind was A9's OWN step line — the line a reader checks to
    learn whether A9 is done. Pinned so this file does not re-acquire the
    overstatement it used to carry ("the flow verdict could not see it").

    Asserted against `_skip_analog_p0_gates()`, the roster the umbrella derives
    for --skip-analog, because that is the artefact the evidence came from: the
    completed pure-digital ihp-sg13g2 SPM run's own
    reports/audit/flow_compliance_check.log line 55 reads
    `SKIP: analog_a9_hw_verify_check (SKIP: analog track deferred via
    --skip-analog ...)` under `Step P0: Structural-RTL gates`. The roster's own
    contract is that it "can never name a gate that the umbrella does not
    actually run".
    """
    assert "analog_a9_hw_verify_check" in FCC._skip_analog_p0_gates()


_HW_VERIFICATION_CLAIM = re.compile(
    r"\b(h/?w|hardware|bench|silicon)\b[^|]{0,24}?"
    r"\b(verif\w*|validat\w*|measur\w*|correlat\w*)\b",
    re.IGNORECASE)


def test_a9_name_does_not_claim_verification_it_never_enforces():
    """The claim, not one spelling of it.

    The original form asserted `"HW Verification" not in name`, which a rename
    to "Hardware Verification" would satisfy while restoring the exact
    over-claim. Match the CLAIM instead — and allow the one honest phrasing, an
    explicitly conditional one ("when bench data exists"), because that is what
    the gate actually does.
    """
    name = _a9()["name"]
    claim = _HW_VERIFICATION_CLAIM.search(name)
    if claim:
        assert re.search(r"when .*(bench|hardware|measur)", name, re.I), (
            f"A9 is named {name!r}, which asserts {claim.group(0)!r}, but its "
            "gate never mandates a hardware measurement: with no bench data "
            "the step closes on cosim alone (a disclosed VACUOUS_PASS). "
            "State the condition or drop the claim")


def test_a9_reference_doc_makes_the_same_claim_as_the_flow():
    """The rename must reach the plugin's own canonical A1-A9 reference.

    skills/analog-flow-orchestrate/SKILL.md is the doc an agent reads to learn
    what each A-step enforces. It carried "HW Verification + Mixed-Signal" —
    the exact over-claim deleted from the flow YAML — verbatim, for the whole
    life of the landed change.
    """
    row = _a9_doc_row()
    label = row[1]
    claim = _HW_VERIFICATION_CLAIM.search(label)
    if claim:
        assert re.search(r"when .*(bench|hardware|measur)", label, re.I), (
            f"the A1-A9 reference doc labels A9 {label!r}, asserting "
            f"{claim.group(0)!r}, which A9's gate does not enforce")


def test_reference_doc_names_only_gates_the_flow_actually_wires():
    """GENERAL freshness guard for the A-track reference table.

    Every `*_check` the doc cites for an A-step must be a program that step's
    gate really invokes in the flow YAML. This is the cheap check that would
    have caught the A9 leftover's sibling: the A4 row cited
    `analog_corner_sweep_check` long after the flow moved to
    `analog_a4_corner_sweep_check` — the LEGACY gate, which the YAML's own
    comment records as exiting 0 on a fabricated stub corner_results.json.
    """
    doc = yaml.safe_load(_FLOW.read_text())
    by_id = {str(s.get("id")): s for s in doc["steps"]}
    stale: list[str] = []
    for sid, _label, _skill, gate_cell in _a_track_doc_rows():
        wired = _wired_programs(by_id.get(sid, {}))
        for named in re.findall(r"`([a-z0-9_]*_check)`", gate_cell):
            if named not in wired:
                stale.append(f"{sid}: doc says {named}, flow wires {wired}")
    assert not stale, "A-track reference doc names gates the flow does not run: " \
                      + "; ".join(stale)


def test_skip_hardware_reaches_the_lettered_analog_step(tmp_path):
    """BEHAVIOURAL, not the private constant.

    The original form asserted `"A9" in FCC._ANALOG_BENCH_STEP_IDS` plus a
    shape assertion on that set — implementation, which a correct alternative
    fix (a per-step `bench_hardware: true` YAML key, say) would fail while
    delivering the same behaviour. The property is that a LETTERED step id
    reaches the routing at all, which the `isinstance(sid, int)` guard made
    impossible.
    """
    p = _project(tmp_path, hw=None)
    a9 = _a9()
    assert not isinstance(a9["id"], int), a9["id"]     # the id really is lettered
    r = FCC.check_step(p, a9, {}, None, skip_hardware=True)
    assert r.status == "WAIVED", (r.status, r.reasons)


def test_skip_hardware_waives_a9_like_step_6(tmp_path):
    r = FCC.check_step(_project(tmp_path, hw=None), _a9(), {}, None,
                       skip_hardware=True)
    assert r.status == "WAIVED", (r.status, r.reasons)
    assert any("skip-hardware" in x for x in r.reasons), r.reasons


def test_without_the_flag_a9_is_not_waived(tmp_path):
    """DIRECTION 1: the waiver is the run MODE's, not a standing exemption."""
    r = FCC.check_step(_project(tmp_path, hw=None), _a9(), {}, None)
    assert r.status != "WAIVED", (r.status, r.reasons)


# ── the regression: --skip-hardware waived a step the design never needed ────

def _digital_only(tmp_path: Path) -> Path:
    """A project with NO analog content at all — A9's condition cannot be met."""
    (tmp_path / "phase1").mkdir(parents=True, exist_ok=True)
    (tmp_path / "phase3").mkdir(parents=True, exist_ok=True)
    assert not (tmp_path / "phase1" / "analog").exists()
    return tmp_path


def test_skip_hardware_does_not_waive_a9_on_a_design_with_no_analog(tmp_path):
    """THE regression. A9 declares
    `condition: files_exist: [phase1/analog/analog_block_list.json]`; the
    --skip-hardware branch was placed ABOVE the condition handling, so a
    pure-digital design acquired a review_required analog-bench waiver for
    hardware it never needed — and any WAIVED count downgrades the Overall
    verdict to PASS_WITH_WAIVERS.

    Measured on the completed pure-digital ihp-sg13g2 SPM run
    (`--phase 3 --skip-hardware`): A9 SKIPPED-CONDITION -> WAIVED,
    WAIVED-DEFERRED 1 -> 2, SKIPPED 18 -> 17.
    """
    r = FCC.check_step(_digital_only(tmp_path), _a9(), {}, None,
                       skip_hardware=True)
    assert r.status == "SKIPPED-CONDITION", (r.status, r.reasons)
    assert not any("skip-hardware" in x for x in r.reasons), r.reasons


_PROBE_CONDITION = {"files_exist": ["phase9/probe/trigger.json"]}


def _flow_step_ids() -> list:
    return [s["id"] for s in yaml.safe_load(_FLOW.read_text())["steps"]]


def _probe_skip_hardware(project: Path, sid) -> str:
    """check_step's --skip-hardware verdict for a synthetic step carrying id
    `sid` and one declared condition. No private symbol is consulted: which ids
    the flag waives is DISCOVERED from behaviour, so this guard survives any
    reimplementation (a per-step `bench_hardware:` YAML key, a different set
    name) that keeps the behaviour."""
    step = {"id": sid, "name": f"probe {sid}", "stage": "stage_analog",
            "condition": _PROBE_CONDITION}
    return FCC.check_step(project, step, {}, None, skip_hardware=True).status


def test_no_hardware_waiver_for_any_step_whose_condition_is_unmet(tmp_path):
    """GENERAL, over EVERY id in the flow, not just A9.

    A --skip-hardware waiver says "this run had no bench, carry the obligation
    forward". A step whose declared `condition` is unmet carries no obligation:
    the design never needed it, and a waiver invents a review_required item plus
    a PASS_WITH_WAIVERS downgrade out of nothing. Sweeping the whole flow also
    covers the FPGA pair (6, 39), which declares no condition today — a measured
    no-op now, but the latent shape is identical and a future condition on an
    FPGA step must not re-open the hole.
    """
    proj = _digital_only(tmp_path)   # phase9/probe/trigger.json does NOT exist
    waived = [sid for sid in _flow_step_ids()
              if _probe_skip_hardware(proj, sid) == "WAIVED"]
    assert waived == [], (
        f"--skip-hardware waived {waived} despite an unmet condition — those "
        "steps do not apply to this design at all")


def test_hardware_waiver_survives_when_the_condition_is_met(tmp_path):
    """DIRECTION 1 for the guard above: the steps that DO apply are still waived.

    Without this, the regression fix could be "satisfied" by disabling the
    hardware waiver outright. Asserts the discovered set still carries A9 (the
    step this change is about) and the FPGA pair (untouched by it).
    """
    proj = _digital_only(tmp_path)
    (proj / "phase9" / "probe").mkdir(parents=True)
    (proj / "phase9" / "probe" / "trigger.json").write_text("{}")
    waived = {str(sid) for sid in _flow_step_ids()
              if _probe_skip_hardware(proj, sid) == "WAIVED"}
    assert "A9" in waived, waived
    assert {"6", "39"} <= waived, waived


# ── partial block coverage is not a close ────────────────────────────────────

def _multi_block(tmp_path: Path, declared: int, measured: int) -> Path:
    (tmp_path / "phase1" / "analog").mkdir(parents=True)
    (tmp_path / "phase3" / "analog").mkdir(parents=True)
    blocks = json.dumps({"blocks": [f"b{i}" for i in range(1, declared + 1)]})
    (tmp_path / "phase1" / "analog" / "analog_block_list.json").write_text(blocks)
    (tmp_path / "phase3" / "analog" / "analog_block_list.json").write_text(blocks)
    for i in range(1, measured + 1):
        d = tmp_path / "phase3" / "analog" / f"b{i}"
        d.mkdir()
        (d / "hw_measurements.json").write_text(json.dumps(
            {"scope_capture": "cap.png", "measurements": {"vout_mv": 812.5}}))
    return tmp_path


def test_partial_block_coverage_is_not_a_bare_pass(tmp_path):
    """Three declared blocks, one measured. On the landed change this printed
    `PASS: analog_a9_hw_verify_check — 1/3 block(s) clean` at rc 0 with no
    disclosure token: the step certified done while two declared blocks had no
    bench evidence at all. Once a bench has demonstrably measured one block, the
    unmeasured rest are unmeasured WORK, not a disclosed capability gap.
    """
    rc, out = _run_checker(_multi_block(tmp_path, declared=3, measured=1))
    assert rc != 0, out[:400]
    assert "INCOMPLETE" in out, out[:400]
    for blk in ("b2", "b3"):
        assert blk in out, (blk, out[:400])


def test_partial_block_coverage_does_not_pass_the_required_gate_slot(tmp_path):
    """The tier reaches the gate A9 wires it into, not just the checker's rc.

    Asserted at the GATE-ENTRY level rather than the step level on purpose. The
    moment ANY hw_measurements.json exists, A9's sibling
    `optional_program_exit_zero` (analog_hw_spice_correlation_check, gated on
    exactly that glob) activates and fails for want of SPICE-correlation data —
    measured FAIL on the landed tree AND on this one — so a `check_step`
    assertion here would be a free-rider that goes red for an unrelated reason
    and survives any mutant. Isolating the required slot is what discriminates.
    """
    gate = {"program_exit_zero":
            f"{_CHECKER.name[:-3]} . --json reports/gates/a9.json"}
    passed, reasons = FCC._evaluate_gate(_multi_block(tmp_path, 3, 1), gate)
    assert passed is False, reasons


def test_full_block_coverage_still_passes_the_required_gate_slot(tmp_path):
    """DIRECTION 1 for the assertion above, same slot, same fixture shape."""
    gate = {"program_exit_zero":
            f"{_CHECKER.name[:-3]} . --json reports/gates/a9.json"}
    passed, reasons = FCC._evaluate_gate(_multi_block(tmp_path, 3, 3), gate)
    assert passed is True, reasons
    assert not any(x.startswith(FCC._VACUOUS_HINT_PREFIX) for x in reasons), reasons


def test_no_block_measured_is_still_a_disclosed_pass(tmp_path):
    """DIRECTION 1. All-blocks-missing stays the VACUOUS_PASS tier — this is the
    headless / CI analog run, and the whole reason the fix is disclosure rather
    than a mandate. It must NOT be swept into INCOMPLETE."""
    rc, out = _run_checker(_multi_block(tmp_path, declared=3, measured=0))
    assert rc == 0, out[:400]
    assert "VACUOUS_PASS" in out, out[:400]


def test_full_block_coverage_still_passes(tmp_path):
    """DIRECTION 1. Measuring every declared block must still close the step."""
    rc, out = _run_checker(_multi_block(tmp_path, declared=3, measured=3))
    assert rc == 0, out[:400]
    assert "PASS" in out and "INCOMPLETE" not in out, out[:400]


def test_vacuous_tier_is_rc_zero_with_a_printed_token(tmp_path):
    """The landed YAML comment called this tier "rc 2, which check_step surfaces
    as VACUOUS_PASS". It is rc 0 plus a PRINTED token — which is exactly why the
    required gate slot had to learn to read stdout. Had it been rc 2 the required
    branch would already have honoured it via `__VACUOUS_HINT__` and the general
    half of the change would not have been needed."""
    rc, out = _run_checker(_multi_block(tmp_path, declared=2, measured=0))
    assert rc == 0, (rc, out[:400])
    assert any(ln.startswith("VACUOUS_PASS:") for ln in out.splitlines()), out[:400]
