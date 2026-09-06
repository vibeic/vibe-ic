#!/usr/bin/env python3
"""The published gate census named ONE failure where TWELVE gates failed.

vibe-ic#2069.

THE MEASUREMENT
===============
One opentitan_aes run (lane rbaes2, v1.17.96, image 0.3.46, 8HD-8) published
`reports/audit/phase23_completion_audit.json` carrying:

    failed_gate_count  1
    failed_gates       ['l8_clock_domains_typed_check']

and, in the SAME file, a `gate_execution_ledger` of 64 rows holding ELEVEN
further FAILs, none of them in the P0 registry:

    coverage_closure                        flow_compliance_check
    formal_proof_evidence_check             fpga_on_board_attestation_check
    l8_clock_period_actionability_check     l8_sta_clock_period_design_owned_check
    l_doc_cross_consistency_check           spec_conformance_check
    spec_review_lint                        submission_template_check
    verilator_coverage_measure

`gate_population_reconciliation` listed all eleven under
`ledger_failures_outside_the_published_census` and DECLARED ITSELF ADVISORY, so
the file both stated the discrepancy and asserted it did not matter. Twelve
gates returned FAIL and the field a reader keys on said one.

Neither number was wrong about the question it answered — the registry and the
ledger are different populations and neither is a subset of the other. What was
wrong is that the census answered the NARROWER question under the name of the
broader one, and every consumer keyed on it inherited the subset: the mcp-eda
pre-burn guard blocks a burn on `failed_gates`, and eleven failing gates were
invisible to it.

THE SAME DEFECT, A SECOND SHAPE
===============================
A second run (lane czadcfd, v1.17.98, image 0.3.46, 8HD-6 — its own
`proj/reports/audit/phase23_completion_audit.json`, read read-only) published:

    registered 246 | invoked 0 | passed 0 | failed 0    failed_gates []

over a `gate_execution_ledger` of 72 rows holding TEN FAILs. Its P0 step is
PRESENT and its `gate_records` list is EMPTY — so the registry projection is
`[]`, correctly, and the census published zero failures for a run in which ten
gates failed. (czadcfd's own manifest line CZ-R4 records this as "11 fails";
measured from the artefact it is TEN. The names are listed in
`_CZADCFD_LEDGER_FAILS` below, which is the form that cannot be miscounted.)

This shape matters beyond being a second instance: `failed_gates: []` is what a
GENUINELY CLEAN run publishes too. Before the fix the two were byte-identical
in the field a reader keys on. `test_zero_published_over_ten_failures_is_not_a
_clean_run` below is the pair that tells them apart, and it is the sharpest
test in this file.

THE RULING (#2069): `failed_gate_count` publishes the UNION, by name, and the
reconciliation REFUSES when the published census does not name every failure —
never ADVISORY.

WHAT IS BLOCKING, AND HOW NARROW IT IS
======================================
The ADVISORY declaration this replaces objected that "making a ledger FAIL
blocking would redden runs whose gates are advisory by design". The refusal
added here is not that. It does not fire on a gate's verdict at all; it fires
when the audit PUBLISHES fewer failures than it holds. On any run whose census
is built the house way — `published_failed_gate_names` — it cannot fire,
whatever the gates returned. It is a defect in the AUDIT, the same class as
`p0_gate_census`'s `closes`, and it goes down the same `structural_fail_lines`
path.

Every fixture below is set algebra over gate names: no design, no PDK, no
vendor.
"""
import json
import subprocess
import sys
from pathlib import Path

PROGRAMS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROGRAMS))

import flow_compliance_check as F  # noqa: E402

CHECKER = PROGRAMS / "flow_compliance_check.py"

#: The rbaes2 shape, reduced to its algebra: one registry FAIL, eleven ledger
#: FAILs outside the registry, and a registry that also holds passes.
_REG_FAIL = "l8_clock_domains_typed_check"
_LEDGER_ONLY_FAILS = [
    "coverage_closure", "flow_compliance_check",
    "formal_proof_evidence_check", "fpga_on_board_attestation_check",
    "l8_clock_period_actionability_check",
    "l8_sta_clock_period_design_owned_check",
    "l_doc_cross_consistency_check", "spec_conformance_check",
    "spec_review_lint", "submission_template_check",
    "verilator_coverage_measure",
]

#: The czadcfd shape: the P0 step ran and recorded NO gates, so the registry
#: contributes nothing and the ledger carries every failure there is.
_CZADCFD_LEDGER_FAILS = [
    "analog_a3_netlist_gen_check", "analog_a4_corner_sweep_check",
    "analog_a5_layout_check", "analog_a6_block_pv_check",
    "analog_hardmacro_check", "flow_compliance_check",
    "fpga_on_board_attestation_check", "l_doc_cross_consistency_check",
    "rtl_unit_test_coverage_check", "spec_review_lint",
]


def _records(fails=(), passes=2):
    out = [{"name": f"passing_{i}_check", "verdict": "PASS",
            "message": "", "evidence": {}} for i in range(passes)]
    out += [{"name": n, "verdict": "FAIL", "message": "", "evidence": {}}
            for n in fails]
    return out


def _ledger(fails=(), passes=()):
    return ([{"gate": n, "verdict": "FAIL", "rc": 1} for n in fails]
            + [{"gate": n, "verdict": "PASS", "rc": 0} for n in passes])


def _historical_subset(records, ledger):
    """The publisher AS IT WAS: the P0 registry's FAILs and nothing else.

    This is the mutation every direction-proving test below reaches for, so the
    defect being re-created is written once, in the shape the artefact actually
    had, rather than paraphrased per test.
    """
    return sorted({r["name"] for r in (records or [])
                   if r.get("verdict") == "FAIL"})


# ── the union, on the measured shape ──────────────────────────────────────
def test_the_published_census_is_the_union_and_names_all_twelve():
    recs = _records(fails=[_REG_FAIL])
    led = _ledger(fails=_LEDGER_ONLY_FAILS, passes=["passing_0_check"])
    pub = F.published_failed_gate_names(recs, led)
    assert len(pub) == 12, pub
    assert set(pub) == {_REG_FAIL, *_LEDGER_ONLY_FAILS}
    # MEMBERSHIP, not the count: the historical publisher and this one must
    # differ by exactly the eleven the file listed and did not count.
    assert set(pub) - set(_historical_subset(recs, led)) == set(
        _LEDGER_ONLY_FAILS)


def test_a_gate_that_failed_in_both_populations_is_named_once():
    """A union, not a concatenation: one gate that failed is one name."""
    recs = _records(fails=["shared_check"])
    led = _ledger(fails=["shared_check", "other_check"])
    assert F.published_failed_gate_names(recs, led) == [
        "other_check", "shared_check"]


def test_the_census_is_sorted_so_the_artefact_is_byte_stable():
    recs = _records(fails=["z_check"])
    led = _ledger(fails=["a_check", "m_check"])
    pub = F.published_failed_gate_names(recs, led)
    assert pub == sorted(pub) == ["a_check", "m_check", "z_check"]


def test_an_absent_umbrella_still_publishes_the_ledgers_failures():
    """Stage 3/4: no P0 records at all. The ledger still failed."""
    assert F.published_failed_gate_names(
        None, _ledger(fails=["a_check"])) == ["a_check"]


# ── the refusal, both directions ──────────────────────────────────────────
def test_a_complete_census_does_not_refuse():
    recs = _records(fails=[_REG_FAIL])
    led = _ledger(fails=_LEDGER_ONLY_FAILS)
    pub = F.published_failed_gate_names(recs, led)
    r = F.gate_population_reconciliation(recs, led, pub)
    assert r["declared"].startswith("BLOCKING"), r["declared"]
    assert r["census_names_every_failure"] is True
    assert r["failures_missing_from_the_published_census"] == []
    assert r["refusal"] is None


def test_mutation_publishing_the_registry_subset_again_reddens_by_name():
    """THE CONTROL THIS TEST EXISTS FOR — re-create the defect and require the
    refusal to fire, naming every failure the census dropped.

    A check that cannot fail is not a check, and the only way this one fails is
    the exact regression it guards: a census narrowed back to one population.
    """
    recs = _records(fails=[_REG_FAIL])
    led = _ledger(fails=_LEDGER_ONLY_FAILS)
    r = F.gate_population_reconciliation(
        recs, led, _historical_subset(recs, led))
    assert r["census_names_every_failure"] is False
    assert r["failures_missing_from_the_published_census"] == sorted(
        _LEDGER_ONLY_FAILS)
    assert r["refusal"]
    # By NAME, not by count: a refusal that says "11 missing" and not which
    # eleven is the same defect one layer up.
    for name in _LEDGER_ONLY_FAILS:
        assert name in r["refusal"], name
    assert "1 gate(s)" in r["refusal"] and "12 returned FAIL" in r["refusal"]


def test_a_run_with_no_failures_publishes_zero_and_does_not_refuse():
    """THE NEGATIVE CONTROL. A clean run must not be reddened by a guard whose
    subject is the census, and `[]` must be read as a census that is complete
    rather than as one that is absent."""
    recs = _records(fails=[], passes=5)
    led = _ledger(fails=[], passes=["passing_0_check", "passing_1_check"])
    pub = F.published_failed_gate_names(recs, led)
    assert pub == []
    r = F.gate_population_reconciliation(recs, led, pub)
    assert r["published_failed_gates"] == []
    assert r["census_names_every_failure"] is True
    assert r["refusal"] is None


def test_an_empty_registry_over_a_failing_ledger_publishes_the_ledger():
    """THE SECOND MEASURED SHAPE (czadcfd). P0 ran and recorded no gates, so
    `gate_records` is `[]` — a real, empty projection, not an absent one. The
    census must then be exactly the ledger's failures."""
    recs = []
    led = _ledger(fails=_CZADCFD_LEDGER_FAILS, passes=["some_passing_check"])
    pub = F.published_failed_gate_names(recs, led)
    assert len(pub) == 10, pub
    assert set(pub) == set(_CZADCFD_LEDGER_FAILS)
    r = F.gate_population_reconciliation(recs, led, pub)
    assert r["refusal"] is None
    assert r["p0_registry_failed_gates"] == []


def test_zero_published_over_ten_failures_is_not_a_clean_run():
    """THE PAIR THAT TELLS THE TWO `[]`s APART.

    Before #2069 a run with ten failing gates and a run with none published the
    SAME `failed_gates: []`. Both arms below publish `[]`; only one of them is
    entitled to. If this test ever passes on both, the field has stopped
    carrying the distinction again.
    """
    led_failing = _ledger(fails=_CZADCFD_LEDGER_FAILS)
    led_clean = _ledger(fails=[], passes=["some_passing_check"])

    refused = F.gate_population_reconciliation([], led_failing, [])
    clean = F.gate_population_reconciliation([], led_clean, [])

    assert refused["published_failed_gates"] == clean[
        "published_failed_gates"] == []
    assert refused["census_names_every_failure"] is False
    assert clean["census_names_every_failure"] is True
    assert clean["refusal"] is None
    for name in _CZADCFD_LEDGER_FAILS:
        assert name in refused["refusal"], name
    assert "0 gate(s) where 10 returned FAIL" in refused["refusal"]


def test_a_caller_that_said_nothing_gets_not_measured_not_a_pass():
    """`published=None` is "did not say", and the difference from `[]` is the
    whole point: an unmeasured census must not read as a complete one."""
    recs = _records(fails=["a_check"])
    led = _ledger(fails=["b_check"])
    r = F.gate_population_reconciliation(recs, led, None)
    assert r["census_names_every_failure"] is None
    assert r["failures_missing_from_the_published_census"] is None
    assert r["refusal"] is None
    assert "NOT_MEASURED" in r["not_measured"]
    # and it still names both populations — refusing to assert is not refusing
    # to look.
    assert r["ledger_failed_gates"] == ["b_check"]
    assert r["p0_registry_failed_gates"] == ["a_check"]


def test_both_populations_are_still_told_apart_by_name():
    """The union is published; it does not REPLACE the two populations. A
    reader who needs the registry-only view must still find it."""
    recs = _records(fails=["shared_check"], passes=1)
    led = _ledger(fails=["outside_a_check", "outside_b_check"],
                  passes=["shared_check"])
    pub = F.published_failed_gate_names(recs, led)
    r = F.gate_population_reconciliation(recs, led, pub)
    assert r["p0_registry_failed_gates"] == ["shared_check"]
    assert r["ledger_failed_gates"] == ["outside_a_check", "outside_b_check"]
    assert r["ledger_failures_outside_the_published_census"] == [
        "outside_a_check", "outside_b_check"]
    assert r["in_both"] == ["shared_check"]
    assert r["every_gate_that_failed"] == [
        "outside_a_check", "outside_b_check", "shared_check"]


# ── END TO END: the refusal is BLOCKING, driven rather than declared ──────
_DRIVER = r'''
import sys
sys.path.insert(0, {programs!r})
import flow_compliance_check as F

# ONE ledger FAIL, injected through `_gate_ledger_payload` — the single
# function both the refusal and the artefact's own `gate_execution_ledger`
# read. Seeding `_GATE_LEDGER` directly does NOT work and the reason is worth
# recording: `main()` opens with `_GATE_LEDGER.clear()`, deliberately, so that
# "one invocation owns one denominator". Injecting at the reader keeps the two
# arms byte-identical everywhere except the publisher under test.
_real_payload = F._gate_ledger_payload
F._gate_ledger_payload = lambda: _real_payload() + [
    {{"gate": "seeded_outside_check", "cmd": "seeded_outside_check",
      "rc": 1, "verdict": "FAIL", "reason_class": None}}]
{mutation}
sys.argv = ["flow_compliance_check.py", ".", "--phase", "all"]
sys.exit(F.main())
'''

_MUTATE = ("F.published_failed_gate_names = "
           "lambda records, ledger: sorted({r['name'] for r in (records or []) "
           "if r.get('verdict') == 'FAIL'})")


def _drive(tmp_path, name, mutation):
    proj = tmp_path / name
    proj.mkdir()
    script = proj / "_drive.py"
    script.write_text(_DRIVER.format(programs=str(PROGRAMS),
                                     mutation=mutation), encoding="utf-8")
    r = subprocess.run([sys.executable, str(script)], cwd=proj,
                       capture_output=True, text=True, timeout=600)
    audit = json.loads(
        (proj / "reports" / "audit" / "phase23_completion_audit.json")
        .read_text(encoding="utf-8"))
    return r, audit


def test_end_to_end_the_house_publisher_names_the_ledger_failure(tmp_path):
    """ARM A — unmutated. The seeded ledger FAIL reaches `failed_gates`, and
    nothing is reddened for it: the refusal's subject is the census, not the
    gate."""
    _r, audit = _drive(tmp_path, "arm_a", "")
    assert "seeded_outside_check" in audit["failed_gates"], audit["failed_gates"]
    assert audit["failed_gate_count"] == len(audit["failed_gates"])
    recon = audit["gate_population_reconciliation"]
    assert recon["census_names_every_failure"] is True
    assert recon["refusal"] is None
    assert not [ln for ln in audit["structural_fail_lines"]
                if "does not name every failure" in ln]


def test_end_to_end_the_narrowed_publisher_is_blocking(tmp_path):
    """ARM B — the historical publisher, restored. The refusal must reach
    `structural_fail_lines`, which is what makes it BLOCKING rather than a
    field somebody could ignore.

    The two arms are compared on the AUDIT VERDICT as well as on the line: an
    empty project with no fail lines refuses as INSUFFICIENT_DATA (#1001), so a
    fail line appearing is observable as that refusal being withdrawn. Two
    independent readings of the same wiring.
    """
    _r, audit = _drive(tmp_path, "arm_b", _MUTATE)
    assert audit["failed_gates"] == [], audit["failed_gates"]
    recon = audit["gate_population_reconciliation"]
    assert recon["census_names_every_failure"] is False
    assert "seeded_outside_check" in (recon["refusal"] or "")
    lines = [ln for ln in audit["structural_fail_lines"]
             if "does not name every failure" in ln]
    assert lines, audit["structural_fail_lines"]
    assert "seeded_outside_check" in lines[0]
    assert audit["verdict"] != "INSUFFICIENT_DATA", (
        "a run carrying a structural fail line has a finding to report")


def test_end_to_end_the_two_arms_differ_only_in_the_publisher(tmp_path):
    """The arms must DISAGREE. Two runs of the same tree that agree prove
    nothing about a mutation."""
    _ra, a = _drive(tmp_path, "cmp_a", "")
    _rb, b = _drive(tmp_path, "cmp_b", _MUTATE)
    assert a["failed_gates"] != b["failed_gates"]
    assert (a["gate_population_reconciliation"]["census_names_every_failure"]
            is not b["gate_population_reconciliation"][
                "census_names_every_failure"])
