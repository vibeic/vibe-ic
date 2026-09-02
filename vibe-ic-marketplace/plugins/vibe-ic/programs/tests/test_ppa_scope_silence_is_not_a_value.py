#!/usr/bin/env python3
"""CLASS 3, third spelling: a scope field that says "nobody established this".

`PPA_INTERFACES` section 2 already settles the rule -- "A field a producer could
not establish is OMITTED and the reason is recorded outside `scope`" -- and
`_ppa/metrics.validate` already refuses two spellings of breaking it: `null` and
`""`, both as SCOPE_SENTINEL, on the ground that two of them compare EQUAL.

There is a THIRD spelling, and until v1.11.71 nothing in this system could see
it. A producer that writes the WORD `"unknown"` gets past every guard: the
required-key check is `if not scope.get(field)`, which a non-empty string
satisfies; the sentinel check tested `val is None or val == ""`; and
`_ppa/benchmark.check_scope_parity`'s own null guard tests `sc.get(k) is None or
sc.get(k) == ""` on the REQUIRED keys only. `"unknown" == "unknown"` exactly the
way `null == null` does, so it is the same defect with the refusal removed --
strictly worse than the two spellings that were fixed, because those at least
reached a refusal.

MEASURED on this host before the fix, with the shipped producers driven over
every real artefact:

  _ppa/power.py      `scope.liberty` = None on 528 records over 46 power
                     artefacts -- refused SCOPE_SENTINEL, so loud but real
  _ppa/power.py      `scope.activity_basis` = "UNSTATED" on 144 records
  _ppa/power.py      `scope.stage` = "unknown", the default, and the token both
                     `ppa-crosslayer/tools/build_arm.py` and
                     `ppa-e2e/tools/extract_run.py` pass when they cannot derive
                     a stage -- while the sentence each writes beside it says
                     the stage "is not asserted" / "NOT_MEASURED, not guessed"
  openroad backend   `scope.fill` = "unknown" on 16 of 22 records over the 15
                     distinct `openroad.log` artefacts on this host

THE HARM, run rather than reasoned about. `check_scope_parity` GRANTED parity to
two power numbers whose stage nobody could derive, and to two whose activity
basis no artefact stated -- the two comparisons section 2 names by name
("Synthesis area and post-route area are different metrics. Vectorless power and
VCD power are different metrics"), and `_ppa/power.py`'s own comment puts the
second gap at 4.3x.

WHAT THESE TESTS PROTECT
  1. The validator refuses the word, at the same code and for the same reason.
  2. A STATED field is not mistaken for a silence (positive control -- without
     it the rule above could be satisfied by refusing everything).
  3. Each of the four producer sites omits the key and records the reason
     OUTSIDE `scope`, where it cannot make anything compare equal.
  4. The end-to-end harm: two arms that establish nothing are UNDETERMINED, not
     comparable.

chip-AGNOSTIC: synthetic reports throughout; no design, PDK, vendor or node
literal.
"""
import sys
from pathlib import Path

import pytest

PLUGIN = Path(__file__).resolve().parent.parent.parent
PROGRAMS = PLUGIN / "programs"
REPO = Path(__file__).resolve().parents[5]
sys.path.insert(0, str(PROGRAMS))

from _ppa import benchmark as B                      # noqa: E402
from _ppa import metrics as M                        # noqa: E402
from _ppa import power as P                          # noqa: E402
from _ppa.backends import openroad as OR             # noqa: E402

# ── fixtures ──────────────────────────────────────────────────────────────
#: A power report that states its engine and its liberty file.
_STATED = "OpenSTA 2.5.0\n# liberty: lib_ss_125C_1v60.lib\n"
#: The activity line the artefact prints when it DOES declare what it timed.
_BASIS = "POWER_ANALYSIS_MODE: vectorless\n"
_ROWS = (
    "Group                  Internal  Switching   Leakage      Total\n"
    "Sequential             1.00e-03   2.00e-04  3.00e-08   1.20e-03\n"
    "Total                  3.00e-03   6.00e-04  9.00e-08   3.60e-03\n")

#: The minimum an OpenROAD log needs to be recognised, plus the design-area line
#: whose meaning depends on whether filler had been inserted when it printed.
_OR_HEAD = "OpenROAD 26Q3-1535-g543c33894f\nPNR_STAGE: detailed_route\n"
_OR_AREA = "Design area 12294 um^2 59% utilization.\n"
_OR_FILLER = "[INFO DPL-0001] Placed 4211 filler instances.\n"

#: The PVT keys `benchmark.REQUIRED_SCOPE["power_mw"]` demands beyond the ones
#: this module is about, so a parity refusal names the axis under test and not
#: an unrelated hole.
_PVT = {"mode": "functional", "process": "ss", "voltage_v": 1.6,
        "temperature_c": 125.0}


def _rec(scope):
    """One valid record carrying `scope`, built directly.

    `M.measured()` validates as it constructs, and what is under test here is
    the VERDICT `validate` returns -- not whether a constructor raises.
    """
    return {"schema": M.SCHEMA_ID, "metric": "power.total_w",
            "status": M.MEASURED, "value": 3.6, "unit": "W",
            "scope": dict(scope),
            "source": {"path": "p.rpt", "sha256": "sha256:" + "b" * 64,
                       "tool": "opensta"}}


def _power_total(text, *, stage="post_route", extra=None):
    """The Total-group record the shipped producer writes for `text`."""
    rep = P.parse_power_report(text, path="phase3/power.rpt",
                               sha256="sha256:" + "a" * 64)
    recs = P.metric_records(rep, stage=stage, scenario="typ",
                            extra_scope=dict(extra or _PVT))
    return [r for r in recs if r["scope"]["group"] == P.TOTAL_GROUP][0]


def _or_area_records(text):
    """`area.design_report.um2` records the backend writes for a log."""
    import tempfile
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "openroad.log"
        p.write_text(text)
        out = OR.parse_log(p)
    return [r for r in out.records if r["metric"] == "area.design_report.um2"]


def _arm(flow, value, power_scope):
    return {"flow": flow, "ppa": {
        "area_um2": {"value": 100.0, "status": "MEASURED",
                     "scope": {"stage": "post_route"}},
        "timing_wns_ns": {"value": 1.0, "status": "MEASURED",
                          "scope": dict(_PVT, stage="post_route",
                                        rc_corner="max", check="setup")},
        "power_mw": {"value": value, "status": "MEASURED",
                     "scope": dict(power_scope)}}}


# ── 1. the validator ──────────────────────────────────────────────────────
@pytest.mark.parametrize("word", ["unknown", "UNSTATED", "n/a", "TBD", "none",
                                  "  Unspecified  ", "-", "null"])
def test_the_validator_refuses_a_scope_field_spelled_as_a_word(word):
    """A word for "I did not know" is not a condition, at any capitalisation."""
    codes = [c for c, _ in M.validate(_rec({"stage": "post_route",
                                            "rc_corner": word}))]
    assert "SCOPE_SENTINEL" in codes, (
        f"`scope.rc_corner = {word!r}` was accepted. It compares EQUAL to the "
        "next record that could not read its corner either, which is the whole "
        f"defect: got {codes!r}")


def test_a_stated_scope_field_is_not_mistaken_for_a_silence():
    """POSITIVE CONTROL. Refusing everything would satisfy the test above.

    `no_fill` is in here on purpose: a producer that means "no filler was
    inserted" states a FACT about the run, and it must survive a rule aimed at
    producers that mean "I could not tell".
    """
    for value in ["post_route", "post_fill", "no_fill", "pre_fill", "max",
                  "VECTORLESS", "functional", "unknown_corner", "nominal"]:
        rec = _rec({"stage": "post_route", "rc_corner": value})
        assert M.validate(rec) == [], (
            f"{value!r} is a stated fact and was refused as a silence")


# ── 2. the power producer ─────────────────────────────────────────────────
def test_power_omits_the_liberty_and_tool_it_could_not_read_and_says_why():
    """528 records on this host carried `liberty: null`. None may again."""
    rec = _power_total(_ROWS)                      # no banner, no liberty line
    assert "liberty" not in rec["scope"], (
        f"`scope.liberty` survives as {rec['scope'].get('liberty')!r}")
    assert "tool" not in rec["scope"]
    gaps = rec.get("scope_gaps") or {}
    assert "liberty" in gaps and "tool" in gaps, (
        "the key was dropped without a word about why, which is the same "
        f"silence one field over: {gaps!r}")
    # SOURCE_UNTOOLED remains and is correct: an artefact that names no engine
    # cannot support a record whose `source.tool` is required. What must be gone
    # is the SCOPE refusal, because that one was the producer inventing a value.
    assert "SCOPE_SENTINEL" not in [c for c, _ in M.validate(rec)]


def test_power_states_the_liberty_and_tool_when_the_artefact_names_them():
    """POSITIVE CONTROL for the pair above."""
    rec = _power_total(_STATED + _BASIS + _ROWS)
    assert rec["scope"]["liberty"] == "lib_ss_125C_1v60.lib"
    assert rec["scope"]["tool"] == "opensta"
    assert "liberty" not in (rec.get("scope_gaps") or {})


@pytest.mark.parametrize("passed", [None, "unknown"])
def test_power_omits_a_stage_the_caller_could_not_establish(passed):
    """`"unknown"` is accepted from a caller and never written into scope.

    Both historical callers passed the word; a producer that only understood
    `None` would have kept writing it for whichever of them was updated last.
    """
    rec = _power_total(_STATED + _BASIS + _ROWS, stage=passed)
    assert "stage" not in rec["scope"], (
        f"`scope.stage` = {rec['scope'].get('stage')!r}: a stage nobody derived "
        "compares EQUAL to every other underived stage")
    assert "stage" in (rec.get("scope_gaps") or {})


def test_power_omits_an_activity_basis_the_artefact_never_stated():
    """144 records on this host carried `activity_basis: "UNSTATED"`."""
    rec = _power_total(_STATED + _ROWS)
    assert rec["scope"].get("activity_basis") != P.BASIS_UNSTATED
    assert "activity_basis" not in rec["scope"]
    assert "activity_basis" in (rec.get("scope_gaps") or {})


def test_a_contradicted_activity_basis_is_a_finding_and_stays_in_scope():
    """The deliberate line, held in place.

    CONTRADICTED is not a silence: the artefact stated TWO bases, which is a
    determinate fact about it. Dropping it would erase a finding, and every
    record carrying it is INVALID and cannot enter a comparison regardless.
    """
    text = (_STATED + "POWER_ANALYSIS_MODE: vcd\n"
            "READ_VCD_FAIL: no such file\n" + _ROWS)
    rec = _power_total(text)
    assert rec["scope"].get("activity_basis") == P.BASIS_CONTRADICTED, (
        "NOT the point of this test, but it cannot make its point without it: "
        f"the fixture stopped contradicting itself ({rec['scope']!r})")
    assert rec["status"] == P.STATUS_INVALID
    assert "activity_basis" not in (rec.get("scope_gaps") or {})


# ── 3. the openroad producer ──────────────────────────────────────────────
def test_openroad_omits_a_fill_state_the_log_does_not_print():
    """16 of 22 records on this host carried `fill: "unknown"`."""
    recs = _or_area_records(_OR_HEAD + _OR_AREA)
    assert recs, "NOT_VERIFIED: the fixture produced no design-area record"
    for r in recs:
        assert "fill" not in r["scope"], (
            f"`scope.fill` = {r['scope'].get('fill')!r}: a pre-filler area and "
            "a post-filler area compare as one measurement")
        assert "fill" in (r.get("scope_gaps") or {})
        assert M.validate(r) == []


def test_openroad_states_the_fill_when_the_log_prints_the_filler_line():
    """POSITIVE CONTROL: the axis did not simply stop being recorded."""
    recs = _or_area_records(_OR_HEAD + _OR_FILLER + _OR_AREA)
    assert recs and all(r["scope"].get("fill") == "post_fill" for r in recs), (
        f"the log states its filler pass and the scope lost it: "
        f"{[r['scope'] for r in recs]}")


def test_no_record_either_producer_writes_carries_a_scope_silence():
    """Both producers, every record, through the consumer that refuses."""
    recs = []
    for text in (_ROWS, _STATED + _ROWS, _STATED + _BASIS + _ROWS):
        for stage in (None, "unknown", "post_route"):
            rep = P.parse_power_report(text, path="p.rpt",
                                       sha256="sha256:" + "a" * 64)
            recs += P.metric_records(rep, stage=stage, extra_scope=dict(_PVT))
    for text in (_OR_HEAD + _OR_AREA, _OR_HEAD + _OR_FILLER + _OR_AREA):
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "openroad.log"
            p.write_text(text)
            recs += OR.parse_log(p).records
    offenders = [(r["metric"], k, v) for r in recs
                 for k, v in (r.get("scope") or {}).items()
                 if v is None or v == "" or M.is_scope_silence(v)]
    assert not offenders, (
        f"{len(offenders)} scope field(s) still spell a silence as a value: "
        f"{offenders[:5]}")


# ── 4. the harm, end to end ───────────────────────────────────────────────
def test_two_power_numbers_with_no_derivable_stage_are_not_comparable():
    """The comparison section 2 names: synthesis against post-route."""
    a = _power_total(_STATED + _BASIS + _ROWS, stage="unknown")["scope"]
    b = _power_total(_STATED + _BASIS + _ROWS, stage="unknown")["scope"]
    with pytest.raises(B.Refusal) as exc:
        B.check_scope_parity([_arm("A", 3.6, a), _arm("B", 9.9, b)])
    assert exc.value.code in ("SCOPE_INCOMPLETE", "SCOPE_SENTINEL")


def test_two_power_numbers_with_no_stated_basis_are_not_comparable():
    """Vectorless power against VCD power -- the same rule, the other axis."""
    a = _power_total(_STATED + _ROWS)["scope"]
    b = _power_total(_STATED + _ROWS)["scope"]
    with pytest.raises(B.Refusal) as exc:
        B.check_scope_parity([_arm("A", 3.6, a), _arm("B", 9.9, b)])
    assert exc.value.code in ("SCOPE_INCOMPLETE", "SCOPE_SENTINEL")


def test_two_power_numbers_that_do_state_everything_still_compare():
    """POSITIVE CONTROL. The two tests above must not pass by refusing all."""
    sc = _power_total(_STATED + _BASIS + _ROWS)["scope"]
    B.check_scope_parity([_arm("A", 3.6, dict(sc)), _arm("B", 9.9, dict(sc))])


# ── 5. the consumer that grants parity ────────────────────────────────────
def test_the_parity_check_refuses_a_silence_in_any_key_not_only_a_required_one():
    """`check_scope_parity`'s null guard was two steps narrower than the harm.

    It tested `is None or == ""` (not the word) on `REQUIRED_SCOPE[axis]` (not
    every key) -- while the equality test one loop down compares the WHOLE scope
    dict, so a silence in `liberty`, `fill` or `tool` bought parity just as
    effectively as one in `process`.
    """
    for key, value in (("stage", "unknown"), ("process", "n/a"),
                       ("liberty", None), ("fill", "unknown"),
                       ("tool", ""), ("rc_corner", "UNSTATED")):
        sc = dict(_PVT, stage="post_route", scenario="typ", group="Total",
                  activity_basis="VECTORLESS")
        sc[key] = value
        with pytest.raises(B.Refusal) as exc:
            B.check_scope_parity([_arm("A", 3.6, sc), _arm("B", 9.9, dict(sc))])
        assert exc.value.code in ("SCOPE_SENTINEL", "SCOPE_INCOMPLETE"), (
            f"`scope.{key} = {value!r}` bought parity: {exc.value.code}")


def test_the_parity_check_still_compares_two_arms_that_state_everything():
    """POSITIVE CONTROL for the test above."""
    sc = dict(_PVT, stage="post_route", scenario="typ", group="Total",
              activity_basis="VECTORLESS", liberty="lib_ss_125C_1v60.lib",
              tool="opensta", fill="post_fill")
    B.check_scope_parity([_arm("A", 3.6, dict(sc)), _arm("B", 9.9, dict(sc))])


# ── 6. the schema, which holds the same rule ──────────────────────────────
_SCHEMA = (PLUGIN / "schemas" / "ppa" / "metric_record.v1.schema.json")


def _scope_pattern():
    """The `pattern` the published schema uses to refuse a silence."""
    import json
    sc = json.loads(_SCHEMA.read_text())["properties"]["scope"]
    return sc["additionalProperties"]["then"]["not"]["pattern"]


def test_the_schema_and_the_validator_hold_the_SAME_vocabulary():
    """Two copies of one rule is the defect this whole lane keeps finding.

    `metric_record.v1.schema.json` already encoded the `null` / `""` half of §2,
    so it has to encode the third spelling too -- and it has to encode the SAME
    one. This is checked with `re` rather than a JSON Schema engine on purpose:
    it is the agreement that must hold, and it must be checkable on a host with
    no `jsonschema` installed (this one has none).
    """
    import re
    pat = re.compile(_scope_pattern())
    missed = sorted(t for t in M._SCOPE_SILENCE_TOKENS if not pat.match(t))
    assert not missed, (
        f"the validator refuses {missed!r} and the published schema accepts "
        "them: two layers, one question, opposite answers")
    for cased in ("UNKNOWN", "Unknown", "  unknown  ", "N/A", "TBD"):
        assert pat.match(cased), (
            f"the schema is case- or whitespace-sensitive where the validator "
            f"is not: {cased!r}")
    for stated in ("post_route", "no_fill", "post_fill", "nominal", "max",
                   "VECTORLESS", "unknown_corner", "functional"):
        assert not pat.match(stated), (
            f"the schema would refuse the stated fact {stated!r}")


def test_the_schema_declares_the_channel_the_producers_write_gaps_to():
    """`scope_gaps` is where an omitted key says why. Undeclared, it is a hole
    a reader has no reason to look in."""
    import json
    d = json.loads(_SCHEMA.read_text())
    assert "scope_gaps" in d["properties"], (
        "the producers write `scope_gaps` and the published record schema does "
        "not mention it")
    assert d["properties"]["scope_gaps"]["type"] == "object"


# ── 7. the callers ────────────────────────────────────────────────────────
def test_the_e2e_deriver_returns_no_stage_rather_than_the_word():
    """`ppa-e2e/tools/extract_run.py` said "not asserted" and asserted one."""
    import importlib.util
    src = REPO / "docs" / "campaigns" / "ppa-e2e" / "tools" / "extract_run.py"
    if not src.is_file():
        pytest.skip(f"NOT_VERIFIED: {src} is absent")
    spec = importlib.util.spec_from_file_location("_er_under_test", src)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    import tempfile
    with tempfile.TemporaryDirectory() as d:
        run = Path(d)
        rpt = run / "power.rpt"
        rpt.write_text(_ROWS)                     # no netlist provenance header
        stage, why = mod._derive_power_stage(run, rpt)
    assert stage is None, (
        f"the deriver returned {stage!r} for a report that links no netlist; "
        "the sentence it returns beside it says the stage is not asserted")
    assert why


def test_the_crosslayer_builder_hands_the_producer_no_stage_token():
    """`ppa-crosslayer/tools/build_arm.py` -- the sibling caller, same token.

    Read rather than run: building an arm drives a whole PnR tree. What is
    asserted is the only thing that reaches `scope`.
    """
    src = REPO / "docs" / "campaigns" / "ppa-crosslayer" / "tools" / "build_arm.py"
    if not src.is_file():
        pytest.skip(f"NOT_VERIFIED: {src} is absent")
    text = src.read_text()
    assert 'stage, why = "unknown"' not in text, (
        "build_arm.py still seeds the stage with a word; its own note beside it "
        "reports \"stage NOT_MEASURED, not guessed\"")
    assert "stage, why = None" in text
