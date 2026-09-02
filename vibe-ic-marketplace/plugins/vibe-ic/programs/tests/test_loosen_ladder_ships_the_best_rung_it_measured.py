"""The loosen ladder shipped the LAST rung, not the best one it measured.

The ladder explores by RESIZING the die and re-running PnR, so when it
terminates the artefacts on disk belong to whichever rung ran last. That is
the right answer only if the residual falls monotonically with die area — and
the ladder's own recorded series is what falsifies it.

MEASURED (subservient x gf180mcuD, 2026-09-02, host 8HD-9, plugin 1.15.55+3,
image ghcr.io/vibeic/vibeic-eda@sha256:66c33ff2..., OpenROAD 26Q3-1472),
straight out of `reports/orchestrator/phase3_one_shot.json`:

    rung 0   416x416   target util 0.25   residual 4
    rung 1   491x491   target util 0.18   residual 6
    rung 2   602x602   target util 0.12   residual 1    <- best MEASURED
    rung 3   738x738   target util 0.08   residual 3
    rung 4   904x904                      residual 3    <- what it SHIPPED

    ROUTE_LOOSEN_DECLINED reason=loosen_ladder_stalled kind=evidence
      die=904x904um rung=4 residual_series=[4, 6, 1, 3, 3] stall_streak=2/2

So it shipped 3 violations on a die 2.25x the AREA of one it had already
measured at 1. The sparse die is not free either: core utilisation fell to
12%, and the metal-COVERAGE rules (M2.4/M3.4, >30% of the die) are a fraction
OF THE DIE, so a sparser die pushes them further out of reach.

`_loosen_stall_streak` already reasons against best-so-far — its own docstring
says so. Only the ARTEFACT SELECTION did not.

DECLARED: ADVISORY. The revert changes which die the final PnR pass runs at
and emits a named `resize_history` record; the `pnr` verdict is still whatever
the shipped route MEASURES, and the re-run's residual is re-measured rather
than carried over from the rung that motivated the revert.

COVERAGE LIMIT, stated honestly: no PUBLISHED corpus run has ever engaged the
loosen ladder (the one corpus run below converged and carries only an upsize
record), so the positive direction cannot be driven from a checked-in
artefact. It is driven from the measured series above; the real artefact backs
the INERT direction, which is the one that would silently damage every
converged run if it were wrong.
"""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _hostpaths  # noqa: E402

_PROG = Path(__file__).resolve().parent.parent / "phase3_one_shot_runner.py"
_spec = importlib.util.spec_from_file_location("_p3r_best_rung", _PROG)
_p3r = importlib.util.module_from_spec(_spec)
sys.modules["_p3r_best_rung"] = _p3r
_spec.loader.exec_module(_p3r)

# The ladder's own record shape: rung i's record is the one that loosened AWAY
# from rung i, so its `from_die_um` IS rung i's die.
_MEASURED_DIES = ["416x416", "491x491", "602x602", "738x738"]
_MEASURED_SERIES = [4, 6, 1, 3, 3]


def _rungs(dies):
    return [{"direction": "loosen", "rung": i, "from_die_um": d}
            for i, d in enumerate(dies)]


def _die_the_ladder_ends_at(series, rungs, last_rung_die):
    """The die the PnR loop finally runs at, modelled at the one point the fix
    changes it.

    PRE-FIX there is no selection step at all: the loop `break`s and the
    artefacts on disk are whichever rung ran last, so this returns
    `last_rung_die` and the assertion below OBSERVES that value and finds it
    wrong. POST-FIX the ladder picks the best rung it measured. This is the
    control the doctrine asks for — the module exists on both sides and only
    the CHANGED behaviour is absent."""
    pick = getattr(_p3r, "_ladder_best_rung", None)
    if pick is None:
        return last_rung_die
    got = pick(series, rungs, last_rung_die)
    return (got[2], got[3]) if got else last_rung_die


# ── the defect ────────────────────────────────────────────────────────────
def test_the_ladder_ends_at_the_best_die_it_measured():
    """The defect stated as the value the operator gets: the final PnR pass
    runs at 904x904 (3 violations) although 602x602 measured 1."""
    ends_at = _die_the_ladder_ends_at(
        _MEASURED_SERIES, _rungs(_MEASURED_DIES), (904, 904))
    assert ends_at == (602, 602), (
        f"ladder measured {_MEASURED_SERIES} over dies {_MEASURED_DIES} + "
        f"904x904 and ended at {ends_at[0]}x{ends_at[1]}um; rung 2 "
        f"(602x602) had already measured 1 violation against the last "
        f"rung's 3")


def test_the_area_actually_shipped_is_the_smaller_one():
    """Same control, in the quantity the coverage rules are a fraction of."""
    w, h = _die_the_ladder_ends_at(
        _MEASURED_SERIES, _rungs(_MEASURED_DIES), (904, 904))
    assert w * h == 602 * 602, (
        f"shipped {w * h} um2 of die; the best measured rung is "
        f"{602 * 602} um2 ({(w * h) / (602 * 602):.2f}x smaller)")
def test_picks_the_best_rung_out_of_the_measured_series():
    """The whole finding, in the numbers the run actually recorded."""
    got = _p3r._ladder_best_rung(
        _MEASURED_SERIES, _rungs(_MEASURED_DIES), (904, 904))
    assert got is not None, (
        f"ladder measured {_MEASURED_SERIES} and would ship its LAST rung "
        f"(904x904, 3 violations) although rung 2 (602x602) measured 1")
    best_i, best_v, w, h = got
    assert (best_i, best_v, w, h) == (2, 1, 602, 602)


def test_the_die_that_comes_back_is_smaller_than_the_one_shipped():
    """The consequence, as a value: area, not just index."""
    got = _p3r._ladder_best_rung(
        _MEASURED_SERIES, _rungs(_MEASURED_DIES), (904, 904))
    w, h = (got[2], got[3]) if got else (904, 904)
    assert w * h < 904 * 904, (
        f"came back with {w}x{h}um, not smaller than the shipped 904x904um")


# ── the directions that must NOT move ─────────────────────────────────────
def test_no_revert_when_the_last_rung_is_already_the_best():
    assert _p3r._ladder_best_rung(
        [6, 4, 1], _rungs(["416x416", "491x491"]), (602, 602)) is None


def test_no_revert_on_a_tie():
    """STRICTLY better only — a tie is not evidence to spend a PnR pass on."""
    assert _p3r._ladder_best_rung(
        [3, 5, 3], _rungs(["416x416", "491x491"]), (602, 602)) is None


def test_no_revert_without_a_series_to_reason_over():
    assert _p3r._ladder_best_rung([], [], (416, 416)) is None
    assert _p3r._ladder_best_rung([4], [], (416, 416)) is None


def test_no_revert_when_the_record_cannot_name_the_die():
    """A missing or malformed die is 'nothing better was measured', never a
    silent guess at one."""
    bad = [{"direction": "loosen", "rung": 0, "from_die_um": ""},
           {"direction": "loosen", "rung": 1, "from_die_um": "491x491"}]
    assert _p3r._ladder_best_rung([1, 6, 3], bad, (602, 602)) is None
    assert _p3r._ladder_best_rung(
        [1, 6, 3], _rungs(["nonsense", "491x491"]), (602, 602)) is None


def test_no_revert_when_the_best_die_is_the_one_already_installed():
    assert _p3r._ladder_best_rung(
        [1, 6, 3], _rungs(["602x602", "491x491"]), (602, 602)) is None


# ── driven by a real published corpus run ─────────────────────────────────
def test_inert_on_a_real_corpus_run_that_never_engaged_the_ladder():
    """`spm x gf180mcuD` converged: its `resize_history` carries an UPSIZE and
    no loosen rung at all. The helper must return None over that real record —
    if it did not, every converged run in the corpus would pay a spurious
    extra PnR pass at a die nobody chose."""
    art = _hostpaths.require_repo(
        "benchmark-data", "ic", "spm", "v1.14.88_gf180mcuD",
        "reports", "orchestrator", "phase3_one_shot.json")
    doc = json.loads(art.read_text())
    histories = [ex.get("resize_history")
                 for st in doc.get("steps", [])
                 for ex in [st.get("extras") or {}]
                 if ex.get("resize_history")]
    assert histories, "corpus run carries no resize_history to reason over"
    for hist in histories:
        loosen = [r for r in hist if r.get("direction") == "loosen"]
        assert loosen == [], (
            "this corpus run was chosen because it never loosened; it now "
            "does, so it is the wrong negative control")
        # a converged run reaches the decline path with a one-element series
        assert _p3r._ladder_best_rung([0], loosen, (285, 285)) is None
