"""v0.2.83 — flow v2.3 professional restructure (43 steps).

Pre-release flow correction (no backward-compat debt):
  * Step 14 (synthesis handoff gate) belongs to Stage 2 — it is the
    synthesis stage's closing QA, not a physical step; marked
    open-source-flow specific;
  * NEW Step 28 "PERC / Reliability sign-off" — the deterministic
    PERC-equivalent's conclusive categories (ESD ring/topology,
    latch-up well-tap, cross-domain) become an ENFORCED numbered gate
    instead of a memo; old 28-41 renumbered to 29-42;
  * NEW Step 43 "Reliability qualification (HTOL)" — long-duration
    qual distinct from the Step-42 burn-in screen, dormant until
    htol_results.json exists;
  * the env-unavailable step-name map is re-aligned to the YAML
    (it carried off-by-one legacy ids: drc→29 while PV was 30, …).

chip-AGNOSTIC: structural yaml/program assertions only.
"""
import json
import sys
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import flow_compliance_check as F     # noqa: E402
import htol_attestation_check as HTOL  # noqa: E402
import perc_signoff_check as PERC      # noqa: E402

PLUGIN = Path(__file__).resolve().parent.parent.parent
_FLOW = yaml.safe_load(
    (PLUGIN / "flow" / "phase1_phase2_phase3.yaml").read_text())
_STEPS = {s["id"]: s for s in _FLOW["steps"] if isinstance(s, dict)}
_INT_IDS = sorted(i for i in _STEPS if isinstance(i, int))


# ── structure ───────────────────────────────────────────────────────────────

def test_flow_is_contiguous_1_to_44():
    assert _INT_IDS == list(range(1, 45)), _INT_IDS


def test_step14_is_stage2_synthesis_handoff():
    s = _STEPS[14]
    assert s["stage"] == "stage2"
    assert "handoff" in s["name"].lower()
    assert "open-source" in s["name"].lower()


def test_step28_is_perc_reliability_signoff():
    s = _STEPS[28]
    assert s["stage"] == "stage3"
    assert "PERC" in s["name"]
    assert "perc_signoff_check" in json.dumps(s.get("gate", {}))
    assert set(s["blocks_on"]) >= {24, 25, 26, 27}


def test_renumbered_steps_kept_identity():
    # spot-pins across the shifted span (incl. the Step-35 DFM insertion)
    assert "Gate-Level Simulation" in _STEPS[29]["name"]
    assert "SPICE" in _STEPS[30]["name"]
    assert "Physical" in _STEPS[31]["name"] or "DRC" in _STEPS[31]["name"]
    # v1.8.87 renamed step 32: it was labelled an ECO step, but what it runs is
    # a multi-corner repair_design + repair_timing + reroute pass, and its skill
    # moved from eco-plan to sta-review to match. The identity this line pins is
    # "step 32 is the post-route timing repair", not the old word.
    assert "timing repair" in _STEPS[32]["name"].lower()
    assert "Power" in _STEPS[33]["name"]
    assert "fill" in _STEPS[34]["name"].lower()
    assert "DFM" in _STEPS[35]["name"]
    assert "checklist" in _STEPS[36]["name"].lower()
    assert "GDS" in _STEPS[37]["name"]
    assert "Handoff" in _STEPS[38]["name"] or "handoff" in _STEPS[38]["name"]
    assert "FPGA" in _STEPS[39]["name"]
    assert "Final Test" in _STEPS[43]["name"]


def _gate_dispatched_programs(gate):
    """Programs the gate actually RUNS, from the slots the engine executes.

    `"name" in json.dumps(gate)` is not this: a name in a comment, in a path
    argument or dropped into the dict as decoration all satisfy it, and a gate
    that NAMES a program it never invokes is worse than one that honestly says
    it only checks a file — the missing invocation stops being readable.
    """
    slots = ("program_exit_zero", "advisory_program_exit_zero",
             "optional_program_exit_zero")
    found = set()

    def walk(node):
        if isinstance(node, dict):
            for k, v in node.items():
                if k in slots:
                    cmd = v.get("command") if isinstance(v, dict) else v
                    if isinstance(cmd, str) and cmd.split():
                        found.add(cmd.split()[0])
                else:
                    walk(v)
        elif isinstance(node, list):
            for item in node:
                walk(item)

    walk(gate or {})
    return found


def _gate_blocking_files(gate):
    """Every path a BLOCKING `files_exist` clause requires."""
    out = []

    def walk(node):
        if isinstance(node, dict):
            for k, v in node.items():
                if k == "files_exist":
                    out.extend(str(x) for x in (v or []))
                else:
                    walk(v)
        elif isinstance(node, list):
            for item in node:
                walk(item)

    walk(gate or {})
    return out


def test_step35_dfm_screen():
    """Step 35's producer record is kept, and the step blocks on its artefact.

    THIS ASSERTION WAS REWRITTEN, and the reason is recorded here rather than
    dropped. It used to require `"dfm_screen_check" in json.dumps(gate)`, and
    that went red because the flow no longer names it there. The flow is
    RIGHT: `dfm_screen_check` is a producer/classifier with PASS /
    PASS_WITH_ADVISORIES / SKIP and NO refusal predicate (its only rc 1 is an
    argument error -- `not a directory`), and vibe-ic#1980 deliberately moved
    it out of the gate denominator. The flow says so in an AUDIT NOTE at the
    clause, and `matrix_mutation_ledger` already depends on step 35 carrying
    no advisory clause ("step 35 is one, since #1980 moved `dfm_screen_check`
    out of its gate entirely"). Re-promoting it would put a blocking clause on
    a program that can never refuse.

    So the old string test is replaced by the invariant #1980 actually left in
    place, which is stronger than the string it replaces: a declared producer
    is EITHER dispatched by the gate OR recorded in `program_outputs` with its
    verdict field AND blocked on by artefact presence. Never neither -- that
    is the state in which a step whose producer never ran certifies clean.
    """
    s = _STEPS[35]
    assert s["stage"] == "stage4"
    assert s["blocks_on"] == [34]
    assert "dfm_screen_check" in (s.get("programs") or []), s.get("programs")

    dispatched = _gate_dispatched_programs(s.get("gate"))
    if "dfm_screen_check" in dispatched:
        return          # re-promoted to a gate clause; that satisfies it too

    # Not dispatched -> the producer record and the presence block must both
    # be there, and on the SAME path.
    rows = [r for r in (s.get("program_outputs") or [])
            if r.get("program") == "dfm_screen_check"]
    assert len(rows) == 1, (
        "step 35's gate does not dispatch dfm_screen_check, so its verdict "
        f"has to survive in program_outputs; found {rows}")
    assert rows[0].get("verdict_field"), (
        "the retained producer record names no verdict_field, so nothing "
        "reads the classification it exists to publish")
    path = str(rows[0].get("path") or "")
    assert path, rows[0]
    assert path in _gate_blocking_files(s.get("gate")), (
        f"the gate does not block on {path!r}, the artefact the retained "
        "producer record declares — a step whose screen never ran would be "
        f"certified done. gate blocks on: {_gate_blocking_files(s.get('gate'))}")
    assert path in [str(x) for x in (s.get("required_outputs") or [])], (
        "the blocked-on artefact is not among required_outputs")


def test_a_name_in_a_gate_must_be_a_program_the_gate_runs():
    """THE DECORATION DIRECTION, over EVERY step, not just 35.

    The rewrite above stops requiring a name in step 35's gate. The way that
    could be abused is to satisfy it -- or any sibling -- by dropping a
    program name into a gate dict without wiring it, which reads as coverage
    and makes the missing invocation unreadable. So: every top-level program
    named anywhere inside a gate must be one the gate DISPATCHES through an
    executing slot.

    Population is behavioural: the names come from `programs/*.py` that the
    flow's own `programs:` lists reference, not from a hand-typed list.
    """
    import re
    shipped = {p.stem for p in (PLUGIN / "programs").glob("*.py")
               if not p.name.startswith("_")}
    declared = {name for st in _STEPS.values()
                for name in (st.get("programs") or [])} & shipped
    assert len(declared) > 20, f"declared-producer set collapsed to {len(declared)}"
    offenders = []
    for sid, st in _STEPS.items():
        gate = st.get("gate")
        if not gate:
            continue
        blob = json.dumps(gate)
        dispatched = _gate_dispatched_programs(gate)
        for name in declared:
            if re.search(r"(?<![A-Za-z0-9_])" + re.escape(name)
                         + r"(?![A-Za-z0-9_])", blob) and name not in dispatched:
                offenders.append(f"step {sid}: {name}")
    assert offenders == [], (
        "these gates NAME a program they do not dispatch — a gate that cites "
        "a program it never runs is less readable than one that admits it "
        "only checks a file:\n  " + "\n  ".join(sorted(offenders)))


def test_step44_htol_conditional():
    s = _STEPS[44]
    assert "HTOL" in s["name"]
    assert s["blocks_on"] == [43]
    # Step 44 stays CONDITIONAL — reliability qual is genuinely N/A for a
    # design that was never fabricated. What changed in vibe-ic#220 is WHICH
    # artefact scopes it. This used to assert the condition named
    # `htol_results.json`, which is also step 44's own required_output, so the
    # assertion pinned the self-disabling shape: missing HTOL results are the
    # defect the attestation exists to catch, and naming them in the condition
    # meant the step vanished exactly when it had something to report. The
    # scope now comes from the silicon-intake declaration that steps 40-43
    # already use, so an absent htol_results.json reaches the required_outputs
    # check and reports MISSING.
    cond = json.dumps(s.get("condition", {}))
    assert "silicon_received.json" in cond
    assert "htol_results.json" not in cond, (
        "step 44 must not be gated on its own required_output")
    assert "htol_results.json" in json.dumps(s.get("required_outputs", []))


def test_file_order_is_numeric():
    seq = [s["id"] for s in _FLOW["steps"]
           if isinstance(s, dict) and isinstance(s["id"], int)]
    assert seq == sorted(seq), "yaml physical order must follow numbering"


def test_capability_gaps_follow_renumber():
    # v1.3.94 — Steps 29 (SDF sim) + 30 (SPICE corr) were CLOSED this campaign
    # with real OSS tools (iverilog $sdf_annotate; ngspice NLDM correlation), so
    # they gate normally now and are no longer cap-gaps. 28 (PERC) is enforced.
    # v1.3.99 — 5 (formal) closed via formal_property_run: the table is EMPTY.
    assert 29 not in F._PLATFORM_CAPABILITY_GAPS
    assert 30 not in F._PLATFORM_CAPABILITY_GAPS
    assert 28 not in F._PLATFORM_CAPABILITY_GAPS  # PERC is enforced, not a gap
    assert F._PLATFORM_CAPABILITY_GAPS == {}


def test_env_map_matches_yaml():
    m = F._ENV_UNAVAILABLE_STEP_NAME_TO_ID
    assert m["physical_verification"] == 31
    assert m["ir_drop"] == 24 and m["em"] == 25
    assert m["antenna"] == 26 and m["si"] == 27
    assert m["perc"] == 28 and m["htol"] == 44
    assert m["metal_fill"] == 34 and m["dfm"] == 35
    assert m["fpga_final_signoff"] == 39
    # every mapped id must exist in the yaml
    for name, sid in m.items():
        assert sid in _STEPS, (name, sid)


# ── perc_signoff_check gate ─────────────────────────────────────────────────

def _perc(tmp_path, categories):
    d = tmp_path / "reports" / "phase3"
    d.mkdir(parents=True)
    (d / "perc_equivalent.json").write_text(json.dumps(
        {"verdict": "x", "categories": categories}))
    return tmp_path


def test_perc_conclusive_fail_blocks(tmp_path):
    _perc(tmp_path, [
        {"category": "ESD discharge topology", "status": "AUTOMATED",
         "result": "FAIL", "note": "dangling clamp on vccd/vssd"},
        {"category": "IR drop", "status": "AUTOMATED", "result": "PASS"}])
    rep = PERC.audit(tmp_path)
    assert rep["rc"] == 1 and rep["verdict"] == "FAIL"
    assert "ESD discharge topology" in rep["automated_failed"]


def test_perc_incomplete_and_manual_are_named_open_items(tmp_path):
    _perc(tmp_path, [
        {"category": "EM (electromigration)", "status": "AUTOMATED",
         "result": "INCOMPLETE"},
        {"category": "ESD clamp sizing", "status": "MANUAL_REVIEW"},
        {"category": "Antenna", "status": "AUTOMATED", "result": "PASS"}])
    rep = PERC.audit(tmp_path)
    assert rep["rc"] == 0
    assert rep["verdict"] == "PASS_WITH_OPEN_ITEMS"
    assert len(rep["open_items"]) == 2


def test_perc_all_pass(tmp_path):
    _perc(tmp_path, [
        {"category": "Antenna", "status": "AUTOMATED", "result": "PASS"}])
    rep = PERC.audit(tmp_path)
    assert rep["rc"] == 0 and rep["verdict"] == "PASS"


def test_perc_absent_is_vacuous(tmp_path):
    assert PERC.audit(tmp_path)["rc"] == 2


# ── htol_attestation_check gate ─────────────────────────────────────────────

def _htol(tmp_path, payload):
    d = tmp_path / "phase3" / "stage5_manufacturing"
    d.mkdir(parents=True)
    (d / "htol_results.json").write_text(json.dumps(payload))
    return tmp_path


def test_htol_zero_failures_passes_with_fit(tmp_path):
    _htol(tmp_path, {"units_tested": 77, "stress_hours": 1000,
                     "failures": 0, "acceleration_factor": 50})
    rep = HTOL.audit(tmp_path)
    assert rep["rc"] == 0 and rep["verdict"] == "PASS"
    assert rep["device_hours"] == 77000
    assert rep["fit_point_estimate"] is not None


def test_htol_failures_fail(tmp_path):
    _htol(tmp_path, {"units_tested": 77, "stress_hours": 1000,
                     "failures": 2})
    rep = HTOL.audit(tmp_path)
    assert rep["rc"] == 1


def test_htol_inconsistent_device_hours_fail(tmp_path):
    _htol(tmp_path, {"units_tested": 77, "stress_hours": 1000,
                     "failures": 0, "device_hours": 999999})
    rep = HTOL.audit(tmp_path)
    assert rep["rc"] == 1
    assert "DEVICE_HOURS_INCONSISTENT" in rep["reason"]


def test_htol_missing_fields_fail(tmp_path):
    _htol(tmp_path, {"note": "ran fine"})
    assert HTOL.audit(tmp_path)["rc"] == 1


def test_htol_absent_is_vacuous(tmp_path):
    assert HTOL.audit(tmp_path)["rc"] == 2
