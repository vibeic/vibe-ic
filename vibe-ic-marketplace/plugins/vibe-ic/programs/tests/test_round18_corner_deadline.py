"""A killed corner run is not an absent measurement — and the deadline has to
know how long the DECK asks for.

MEASURED (u_hawaii_adc, ihp-sg13g2, round 18). An INCREMENTAL delta-sigma's
measurement unit is one CONVERSION WINDOW, and the window is the design's
DECLARED oversampling ratio: 256 clocks. The topology entry's own testbench
therefore asks for `tran 0.5n 51200n`. `analog_real_corner_sweep` gave every
run the same fixed 120 seconds, so all nine corners were killed having reached
30.3 us of the 51.2 us asked for; the sweep wrote no `corner_results.json`;
and A4 reported the block WAIVED for a MISSING ARTEFACT.

That is "I could not look" reported as "it is not there" — the defect
`test_issue1283_probe_timeout_is_not_absence` exists to catch one layer up,
arriving here through a deadline instead of a probe.

Two things follow, and this module pins both:

  1. THE DEADLINE SCALES WITH THE DECK. A deck that asks for fifty times more
     transient gets more wall clock. The floor is the old fixed value, so
     nothing that passed before gets less; the ceiling is stated, so a runaway
     deck still ends.
  2. A KILL SAYS SO. When the deadline fires, the log carries
     `SIMULATION_DEADLINE_EXCEEDED` with the two numbers a reader needs — what
     the deck asked for and what it was given — so no consumer downstream can
     read a stopped run as a measurement that came back empty.
"""
import sys
from pathlib import Path

import pytest

_PROGRAMS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_PROGRAMS))

import analog_real_corner_sweep as S  # noqa: E402


# ── 1. the deck's own transient span is read, not guessed ─────────────────
@pytest.mark.parametrize("line,ns", [
    ("tran 0.5n 51200n uic", 51200.0),
    ("tran 1n 1000n", 1000.0),
    ("tran 1n 10u", 10000.0),
    ("tran 1n 1m", 1000000.0),
    ("  TRAN 1N 250N  ", 250.0),
    # A bare number with no unit is seconds in SPICE.
    ("tran 1n 1", 1e9),
])
def test_the_transient_span_is_read_off_the_deck(line, ns):
    assert S.tran_stop_ns(line + "\n") == pytest.approx(ns)


def test_a_deck_with_no_transient_reads_as_unknown_not_as_zero():
    """`None` and 0 are different answers: one is "no transient analysis
    here", the other would be "it asked for nothing"."""
    assert S.tran_stop_ns(".end\n") is None
    assert S.tran_stop_ns("") is None


# ── the deadline that follows ─────────────────────────────────────────────
def test_the_declaration_that_broke_this_now_gets_more_than_120_seconds():
    """The measured case: two conversion windows of the declared OSR."""
    assert S.sim_deadline_s("tran 0.5n 51200n uic") > 120


def test_a_longer_deck_gets_a_longer_deadline():
    short = S.sim_deadline_s("tran 1n 1000n")
    long_ = S.sim_deadline_s("tran 1n 20000n")
    assert long_ > short


def test_nothing_that_passed_before_gets_less_time():
    """The floor is the historical fixed value, so this change can only ever
    give a run MORE room — never turn a passing corner into a killed one."""
    for deck in ("tran 1n 10n", "tran 1n 1n", ".end", ""):
        assert S.sim_deadline_s(deck) >= S.SIM_DEADLINE_FLOOR_S


def test_a_runaway_deck_still_ends():
    assert S.sim_deadline_s("tran 1n 1") == S.SIM_DEADLINE_CEILING_S
    assert S.SIM_DEADLINE_CEILING_S > S.SIM_DEADLINE_FLOOR_S


def test_an_unreadable_deck_falls_back_to_the_floor_and_not_the_ceiling():
    """Not knowing how long a deck needs is not a reason to give it two
    hours; it is a reason to give it what the flow always gave."""
    assert S.sim_deadline_s("something that is not a deck") == \
        S.SIM_DEADLINE_FLOOR_S


# ── 2. a kill is reported as a kill ───────────────────────────────────────
class _Killed:
    """A container exec that reports the deadline the way `_container_exec`
    does: rc 124, with whatever the tool had printed before it was stopped."""
    returncode = 124
    stdout = "Reference value :  3.02833e-05\n"


def test_a_deadline_kill_is_named_in_the_log(monkeypatch):
    seen = {}

    def fake_docker(container, cmd, timeout=120):
        seen["timeout"] = timeout
        return _Killed()

    monkeypatch.setattr(S, "_docker", fake_docker)
    monkeypatch.setattr(S, "_resolve_ngspice", lambda c: "ngspice")
    monkeypatch.setattr(S, "_supports_json_measure", lambda c, b: False)
    _ok, _meas, raw, _status = S._run_ngspice(
        "ctr", "/tmp/d.sp", deck_text="tran 0.5n 51200n uic\n")
    assert "SIMULATION_DEADLINE_EXCEEDED" in raw
    # the two numbers a reader needs
    assert "51200" in raw
    assert str(seen["timeout"]) in raw


def test_a_deadline_kill_yields_no_measurement(monkeypatch):
    """The CONTROL that matters: a stopped run must not also come back
    carrying numbers. `ok` false, and nothing measured."""
    monkeypatch.setattr(S, "_docker",
                        lambda c, cmd, timeout=120: _Killed())
    monkeypatch.setattr(S, "_resolve_ngspice", lambda c: "ngspice")
    monkeypatch.setattr(S, "_supports_json_measure", lambda c, b: False)
    ok, meas, _raw, _status = S._run_ngspice(
        "ctr", "/tmp/d.sp", deck_text="tran 0.5n 51200n uic\n")
    assert not ok
    assert not [v for v in (meas or {}).values() if v is not None]


class _Fine:
    returncode = 0
    stdout = "vavg = 6.000000e-01\nMEAS density= 0.6  swing= 1.0\n"


def test_a_run_that_completes_says_nothing_about_deadlines(monkeypatch):
    """The other CONTROL: the disclosure must not appear on a healthy run,
    or it means nothing when it does."""
    monkeypatch.setattr(S, "_docker",
                        lambda c, cmd, timeout=120: _Fine())
    monkeypatch.setattr(S, "_resolve_ngspice", lambda c: "ngspice")
    monkeypatch.setattr(S, "_supports_json_measure", lambda c, b: False)
    _ok, _meas, raw, _status = S._run_ngspice(
        "ctr", "/tmp/d.sp", deck_text="tran 0.5n 51200n uic\n")
    assert "SIMULATION_DEADLINE_EXCEEDED" not in raw


def test_the_deck_reaches_the_deadline_calculation_from_the_sweep(monkeypatch):
    """A deadline that scales with the deck is worth nothing if the caller
    never hands the deck over. Measured: it did not, and every corner of a
    51 us deck was cut at the 120 s default."""
    src = (_PROGRAMS / "analog_real_corner_sweep.py").read_text()
    assert "deck_text=tb" in src
