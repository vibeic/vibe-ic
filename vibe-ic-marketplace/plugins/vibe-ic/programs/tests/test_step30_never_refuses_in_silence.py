"""R-0915-71 — step 30 reached a conclusion and wrote it nowhere.

MEASURED on subservient x gf180mcuD (lane icsub2, r25, main c0dcb5e27) — the
run that had nothing else wrong with it. Step 27 had just gone green under
R-0915-66, every other phase-3 row was a cascade, and the whole design failed
on a silence:

    required_outputs missing: ['phase3/stage3/spice/correlation.json OR
    reports/phase3/spice_correlation.json'] (satisfied: 1/2)

The deck was built AND simulated — `correlation.spice` 6616 B and
`correlation.log` 16807 B sat beside each other — and `spice_correlation_check`
PASSED. The driver had refused, with a precise sentence, reproduced
deterministically by re-running it on that tree:

    per-stage delay not measurable: stage 2: 0 of 2 drive polarities produced
    the declared output transition with a full swing; the arc is unresolved and
    no delay is taken from it; ngspice also exited non-zero

and that sentence went into a return value nobody persisted. The runner's own
disclosure-writer did not fire either: it is guarded on "no deck exists", and a
deck DID exist. So the step's declared record was never written.

A step that reached a conclusion and wrote it nowhere is worse than one that
failed loudly — a reader cannot tell it from a step that never ran.

The fix is ONE wrapper rather than fifteen edited `return` statements: every
early refusal in the driver, and every one added later, lands in the declared
record. Both directions are pinned here, and so is the thing the fix may not do
— overwrite a record a real correlation already left.
"""
import json
import sys
from pathlib import Path

PROG = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROG))
import spice_correlation_check as S  # noqa: E402

#: r25's exact refusal, transcribed.
_R25_REASON = (
    "per-stage delay not measurable: stage 2: 0 of 2 drive polarities produced "
    "the declared output transition with a full swing; the arc is unresolved "
    "and no delay is taken from it; ngspice also exited non-zero")

_DECLARED = ("phase3/stage3/spice/correlation.json",
             "reports/phase3/spice_correlation.json")


def _proj(tmp_path):
    p = tmp_path / "proj"
    (p / "phase3" / "stage3" / "spice").mkdir(parents=True)
    (p / "reports" / "phase3").mkdir(parents=True)
    return p


# ── the refusal reaches the declared record ───────────────────────────────

def test_a_refusal_is_written_at_the_declared_names(tmp_path):
    p = _proj(tmp_path)
    wrote = S._write_declared_correlation_refusal(p, "ERROR", _R25_REASON)
    assert len(wrote) == 2, wrote
    for rel in _DECLARED:
        d = json.loads((p / rel).read_text())
        assert d["verdict"] == "NOT_MEASURED"
        assert d["reason"] == _R25_REASON
        assert d["reason_class"] == "EXECUTION_ERROR"
        assert d["correlation_ran"] is False
        assert d["step"] == 30


def test_both_names_carry_the_SAME_dict(tmp_path):
    """Two documents describing one refusal are two things that can disagree."""
    p = _proj(tmp_path)
    S._write_declared_correlation_refusal(p, "ERROR", _R25_REASON)
    a = json.loads((p / _DECLARED[0]).read_text())
    b = json.loads((p / _DECLARED[1]).read_text())
    assert a == b


def test_a_real_correlation_record_is_never_overwritten(tmp_path):
    """THE NEGATIVE CONTROL. A refusal may not speak over a measurement."""
    p = _proj(tmp_path)
    real = {"verdict": "PASS", "correlation_ran": True, "ratio": 1.02}
    (p / _DECLARED[0]).write_text(json.dumps(real))
    wrote = S._write_declared_correlation_refusal(p, "ERROR", _R25_REASON)
    assert json.loads((p / _DECLARED[0]).read_text()) == real
    assert wrote == [str(p / _DECLARED[1])]


# ── the reason class comes from the refusal's own sentence ────────────────

def test_a_missing_tool_is_a_capability_gap_not_an_error():
    assert S._correlation_reason_class(
        "NO_TOOL", "ngspice executable absent") == "CAPABILITY_ABSENT"


def test_an_absent_upstream_artefact_is_blocked_by_upstream():
    for reason in ("routed netlist or SPEF absent", "active Liberty unreadable"):
        assert S._correlation_reason_class("ERROR", reason) \
            == "BLOCKED_BY_UPSTREAM", reason


def test_everything_else_is_an_execution_error():
    for reason in (_R25_REASON, "critical STA path unparseable",
                   "critical path not stitchable", "", None):
        assert S._correlation_reason_class("ERROR", reason) \
            == "EXECUTION_ERROR", reason


def test_the_class_is_decided_by_the_sentence_not_the_call_site():
    """The sentence is what a reader sees; the two must not be able to
    disagree, so the class is derived from it and from nothing else."""
    assert S._correlation_reason_class("ERROR", "routed netlist or SPEF absent "
                                       "(after two retries)") \
        == "BLOCKED_BY_UPSTREAM"


# ── the wrapper: every refusal lands, and a success is untouched ──────────

def test_every_driver_refusal_reaches_the_record(tmp_path):
    """EVERY early refusal, through the one helper each of them returns
    through — so a refusal added later is covered by construction."""
    p = _proj(tmp_path)
    for status, reason, klass in (
            ("ERROR", _R25_REASON, "EXECUTION_ERROR"),
            ("NO_TOOL", "ngspice executable absent", "CAPABILITY_ABSENT"),
            ("ERROR", "routed netlist or SPEF absent", "BLOCKED_BY_UPSTREAM")):
        for rel in _DECLARED:
            (p / rel).unlink(missing_ok=True)
        res = S._persist_declared_refusal(p, {"status": status,
                                              "reason": reason})
        assert res["status"] == status, "the driver's own dict is handed back"
        d = json.loads((p / _DECLARED[0]).read_text())
        assert d["reason_class"] == klass, (status, reason)


def test_all_fifteen_refusals_return_through_the_helper(tmp_path, monkeypatch):
    """Every delegated input/producer boundary persists its actual refusal.

    The historical fifteen inline returns became one shared catch. Exercise
    each present boundary rather than freezing a count of source statements.
    """
    import test_default_si_spice_power as fixture
    import librelane_postroute as lp
    import path_spice_tool as pst
    p, folder, lib = fixture.project(tmp_path)
    fixture.spice_produce(p, folder, lib, monkeypatch)
    boundaries = [(fixture.LC, 'resolve_image'), (lp, 'stapostpnr_state'),
                  (fixture.LC, 'pdk_root_resolution'), (pst, 'run_current_step30')]
    for module, name in boundaries:
        reason = 'SOFTWARE_FIXTURE_ONLY refused at ' + name
        def refused(*args, **kwargs):
            raise fixture.LC.Refusal('CURRENT_FIXTURE_REFUSAL', reason)
        with monkeypatch.context() as patch:
            patch.setattr(module, name, refused)
            result = S.run_installed_pdk_path_correlation(p, str(lib))
        assert result['status'] == 'ERROR' and reason in result['reason']
        records = [json.loads((p / relative).read_text()) for relative in _DECLARED]
        assert records[0] == records[1]
        assert records[0]['verdict'] == 'NOT_MEASURED'
        assert records[0]['correlation_ran'] is False and reason in records[0]['reason']


def test_the_success_path_is_not_routed_through_the_refusal_helper(tmp_path, monkeypatch):
    import test_default_si_spice_power as fixture
    p, folder, lib = fixture.project(tmp_path)
    def unexpected(*args, **kwargs):
        raise AssertionError('Current measurement cannot pass through refusal persistence')
    monkeypatch.setattr(S, '_persist_declared_refusal', unexpected)
    result = fixture.spice_produce(p, folder, lib, monkeypatch)
    assert result['status'] == 'RAN'
    records = [json.loads((p / relative).read_text()) for relative in _DECLARED]
    assert records[0] == records[1] == result['report']
    assert S.main([str(p), '--json', str(p / 'consumer.json')]) == 0


def test_a_driver_that_returned_no_reason_still_says_something(tmp_path):
    p = _proj(tmp_path)
    S._persist_declared_refusal(p, {"status": "ERROR"})
    d = json.loads((p / _DECLARED[0]).read_text())
    assert "no reason" in d["reason"]
    assert d["reason_class"] == "EXECUTION_ERROR"


def test_the_drivers_signature_is_unchanged():
    """Callers pass `container=`; the runner does. This fix may not move where
    the simulation runs."""
    import inspect
    sig = inspect.signature(S.run_installed_pdk_path_correlation)
    assert list(sig.parameters) == ["project", "liberty_path", "container",
                                    "max_stages"], list(sig.parameters)


# ── the defect itself, stated so BASE SOURCES can answer ─────────────────

def test_a_driver_refusal_leaves_step_30_a_declared_record(tmp_path):
    """THE DECISIVE CONTROL, and it is base-executable: no new symbol, no
    monkeypatch, just the public driver on a project it must refuse.

    Whatever it refuses on — no ngspice, no Liberty, no routed netlist — step
    30 declares a record and the refusal has to reach it. On sources without
    the fix NEITHER declared name exists and the step reads MISSING while the
    driver had a precise sentence in hand, which is exactly how r25 failed."""
    p = _proj(tmp_path)
    res = S.run_installed_pdk_path_correlation(p, str(tmp_path / "absent.lib"))
    assert res.get("status") != "RAN", (
        "this control needs a project the driver REFUSES on")
    present = [rel for rel in _DECLARED if (p / rel).is_file()]
    assert present, (
        f"the driver refused with {res.get('status')!r}: "
        f"{str(res.get('reason'))[:120]!r} and left NEITHER of step 30's "
        f"declared records — the step reads MISSING while the reason is in a "
        f"return value nobody persisted")
    d = json.loads((p / present[0]).read_text())
    assert d["verdict"] == "NOT_MEASURED"
    assert d["reason_class"] in ("CAPABILITY_ABSENT", "BLOCKED_BY_UPSTREAM",
                                "EXECUTION_ERROR")
