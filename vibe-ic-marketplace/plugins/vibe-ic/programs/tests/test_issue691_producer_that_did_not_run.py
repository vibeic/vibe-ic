"""#691 — a producer that never ran read like one that found nothing to declare.

`l21_doc_supply_rail_synth` is the INDEPENDENT producer of power-intent rail
declarations. On a real Phase-3 run it left no artefact anywhere:

    L21_POWER_INTENT.json  power_rails: 0
                           power_domains: 3, every one stamped
                           derived_by: l21_macro_supply_rail_synth

`declared_rails()` then returned [] — correctly, because
`_derived_from_the_macros_under_test()` refuses a rail synthesised from the very
macro pins it would be used to check. That filter is working as designed, on
input that should never have been the only input.

WHY IT STAYED INVISIBLE: `measured_rails()` re-derives rails from DEF
SPECIALNETS geometry, so the two rails that HAVE geometry keep working. The
third — a secondary-domain rail with no geometry BECAUSE it was never declared —
falls through to `rail_undeclared`. So the visible symptom is "one rail is
undeclared" when the fact is "the independent declaration step never ran".
Chasing the symptom leads to the rail; the cause is a missing producer.

Same family as #544 (a declared gate that returned no verdict) and #682 (a gate
whose execution nothing recorded) — except this one is a PRODUCER, upstream of
every gate that consumes it.

MEASURED after the fix:

    both producers ran              gaps=1  cause —
    the doc producer did NOT run    gaps=1  cause ['l21_doc_supply_rail_synth']
    no producer record (older run)  gaps=1  cause —
    project omitted                 gaps=1  output shape unchanged
"""
from __future__ import annotations

import importlib.util
import json
import pathlib
import sys

_PROGRAMS = pathlib.Path(__file__).resolve().parents[1]
if str(_PROGRAMS) not in sys.path:
    sys.path.insert(0, str(_PROGRAMS))

_spec = importlib.util.spec_from_file_location(
    "hardmacro_supply_intent", _PROGRAMS / "hardmacro_supply_intent.py")
H = importlib.util.module_from_spec(_spec)
sys.modules["hardmacro_supply_intent"] = H
try:
    _spec.loader.exec_module(H)
except SystemExit:
    pass

_LEF = "MACRO ip\n  PIN VPP\n    USE POWER ;\n  END VPP\nEND ip\n"
_L21 = {"power_rails": [],
        "power_domains": [{"name": "VDD", "power_net": "VDD",
                           "derived_by": "l21_macro_supply_rail_synth",
                           "derived_from": {"macro_lef_pin_use": True}}]}


def _proj(tmp_path, outcomes):
    f = H._pl.report_path(tmp_path, "phase1/l21_rail_producers.json")
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(json.dumps({"producers": [
        {"producer": n, "outcome": o} for n, o in outcomes]}))
    return tmp_path


_RAN = [("l21_doc_supply_rail_synth", "ran"),
        ("l21_macro_supply_rail_synth", "ran")]
_DEAD = [("l21_doc_supply_rail_synth", "did-not-run"),
         ("l21_macro_supply_rail_synth", "ran")]


# ── the cause is named, and only when it applies ──────────────────────────
def test_a_producer_that_did_not_run_is_NAMED(tmp_path):
    r = H.assess([_LEF], _L21, None, project=_proj(tmp_path, _DEAD))
    c = r["undeclared_cause"]
    assert c["producers_that_did_not_run"] == ["l21_doc_supply_rail_synth"]
    assert "fix the producer first" in c["note"]


def test_when_every_producer_ran_there_is_no_cause(tmp_path):
    r = H.assess([_LEF], _L21, None, project=_proj(tmp_path, _RAN))
    assert "undeclared_cause" not in r


def test_the_FINDING_itself_is_unchanged_either_way(tmp_path):
    """LOAD-BEARING. This annotates; it must not create or suppress a gap. A
    rail that is undeclared is undeclared whichever way the producers went."""
    dead = H.assess([_LEF], _L21, None, project=_proj(tmp_path / "a", _DEAD))
    ran = H.assess([_LEF], _L21, None, project=_proj(tmp_path / "b", _RAN))
    assert [p["status"] for p in dead["gaps"]] == [p["status"] for p in ran["gaps"]]
    assert len(dead["gaps"]) == 1


# ── it must not invent a failure ──────────────────────────────────────────
def test_no_record_at_all_does_not_become_a_failure(tmp_path):
    """Deliberately the OPPOSITE of this repo's usual rule, and the reason is
    stated: an absent record cannot prove a producer ran, but neither can it
    prove one failed. An older run has no record, and inventing a failure from
    its absence would flag every project that predates it. This is used to
    EXPLAIN a finding that already exists, never to create one."""
    assert H.rail_producers_that_did_not_run(tmp_path) == []
    r = H.assess([_LEF], _L21, None, project=tmp_path)
    assert "undeclared_cause" not in r


def test_a_corrupt_record_is_not_a_failure_either(tmp_path):
    f = H._pl.report_path(tmp_path, "phase1/l21_rail_producers.json")
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text("{not json")
    assert H.rail_producers_that_did_not_run(tmp_path) == []


def test_a_dead_producer_with_NO_gaps_says_nothing(tmp_path):
    """No gap, no explanation to give. Annotating a clean result would make the
    note noise, and noise is how a real one gets scrolled past."""
    l21 = {"power_rails": [{"name": "VPP"}]}
    r = H.assess([_LEF], l21, ["VPP"], project=_proj(tmp_path, _DEAD))
    if not r["gaps"]:
        assert "undeclared_cause" not in r


# ── the producer side actually writes it ──────────────────────────────────
def test_the_phase1_runner_records_both_producers():
    """The record has to exist for any of this to work, and it must be written
    UNCONDITIONALLY — a record written only on success is the defect."""
    src = (_PROGRAMS / "phase1_doc_one_shot_runner.py").read_text(encoding="utf-8")
    body = "\n".join(l for l in src.splitlines() if not l.lstrip().startswith("#"))
    i = body.index("l21_rail_producers.json")
    seg = body[max(0, i - 2000):i]
    # the two outcomes, however they are spelled — this is about the RECORD
    # being written on both paths, not about a particular assignment syntax
    assert "did-not-run" in seg, "the failure path leaves no record"
    assert '"ran"' in seg, "the success path leaves no record"
    # and the write must not be inside the try that could have failed
    assert "for _label, _mod in" in seg


def test_omitting_project_leaves_the_output_shape_unchanged():
    """Every existing caller passes three arguments. A new required one would
    break them all, and `undeclared_cause` — the key THIS issue added — must
    still appear only when a project is there to derive it from.

    THE KEY-SET EQUALITY THIS USED TO ASSERT OUTLIVED ITS TRUTH (#785)
    ------------------------------------------------------------------
    It read `set(r) == {5 keys}`, justified as "a new key on the old shape would
    break consumers that compare it". MEASURED at the moment #785 landed: NO
    consumer compares it — `ip_integration_check` and
    `phase3_one_shot_runner._macro_supply_preroute_decision` are the only two,
    and both read named keys. So the equality was pinning a hazard that does not
    exist, at the cost of forbidding every additive fact — including the one
    #785 exists to add, that an abstract typing NO pin is not an abstract with
    no supply pin.

    What it was really protecting is kept and made explicit: the pre-existing
    keys are all still there, and nothing derived from a project appears without
    one.
    """
    r = H.assess([_LEF], _L21, None)
    assert "undeclared_cause" not in r
    assert {"pins", "accounted", "gaps", "declared_rails",
            "measured_rails"} <= set(r)
    # Nothing that needs a project may be non-empty without one. The untyped
    # scan itself needs only the LEF text, so it still answers; its Liberty
    # CORROBORATION does not.
    assert r["scanned"]["liberty_cells"] == []
    assert r["recovered_pins"] == [] and r["recovered_gaps"] == []
