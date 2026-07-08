"""v1.3.43 candidate #1 — the triangle/sawtooth peak-hold GENRE CONVENTION is
SPEC-GATED with a STRONG/WEAK forbid precedence (Step-2.7-hardened).

The ic-expert §4-E "hold the peak" lesson is a GENRE DEFAULT. It must fire when
the prose is SILENT / consistent-with-hold, and must NOT fire when the spec
EXPLICITLY describes a plain single-cycle-peak triangle. The deterministic gate
`spec_conformance_check._spec_requires_peak_hold` is the single source of that
decision. §4-E precedence:
  1. a STRONG explicit no-hold ("no peak hold", "one cycle wide", "appears for
     exactly one cycle", "hold forbidden") overrides the convention outright;
  2. else an EXPLICIT hold-require (any sentence) FIRES the convention — a WEAK
     motion phrase ("advances every cycle …", "then immediately reverse") does
     NOT disarm it: such a phrase usually just describes the RAMP phase / a
     post-dwell reversal (the #776-class LEAK the Step-2.7 review caught);
  3. else a WEAK motion no-dwell phrase disarms (plain-triangle spec);
  4. else silent → gate stays False.

REGRESSION GUARD: the REAL RTLLM signal_generator spec is UNAFFECTED (#776
protected — its golden holds BOTH peak `1f 1f` and trough `00 00`).
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import spec_conformance_check as scc  # noqa: E402

_WGEN = "triangle wave generator. "

_RTLLM_SIGNAL_GENERATOR = (
    "Implement a Triangle Wave signal generator module that generates a "
    "waveform by incrementing and decrementing a 5-bit signal named \"wave\". "
    "The waveform cycles between 0 and 31, which is incremented or decremented "
    "by 1. If the state is 0, the waveform (wave) is incremented by 1. If the "
    "waveform reaches 31 (wave == 31), the state is transitioned to 1. If the "
    "state is 1, the waveform is decremented by 1. If the waveform reaches 0 "
    "(wave == 0), the state is transitioned back to 0."
)

# an EXPLICIT hold-require — the convention MUST fire (True).
_REQUIRE = [
    "hold the peak for two cycles before reversing",
    "the maximum value is held for 3 clocks",
    "dwell at the top for one extra cycle",
    "the peak is held for one extra cycle",
]

# an EXPLICIT plain-triangle / no-dwell spec (NO hold-require) — convention must
# NOT fire (False). Covers the ic-expert §4-E lesson's own documented example.
_PLAIN_TRIANGLE = [
    "advances every single cycle including the turn",
    "the counter increments every cycle, even at the peak",
    "at the peak it immediately decrements the next cycle",
    "the peak value appears for exactly one cycle",
    "the maximum is output for just one cycle",
    "the peak is one cycle wide",
    "reverses immediately with no dwell",
    "no peak hold",
    "increment then decrement without dwelling at the maximum",
]

# STRONG no-hold statements — GENERIC/DIRECT only (branch 1 "no/without hold",
# branch 4 "hold forbidden") — that override EVEN an explicit hold-require. The
# EXTREME-SPECIFIC one-cycle phrases ("one cycle wide", "appears exactly one
# cycle") are NOT strong (they were moved to WEAK — see the asymmetric-dwell
# regression below).
_STRONG = [
    "no peak hold",
    "the peak hold is forbidden",
    "without any dwell",
]

# The Step-2.7 §4.05 HIGH reproductions: a hold-require phrased alongside a ramp
# "every cycle" clause, or a post-dwell "immediately reverse". The bare motion
# MUST NOT disarm the explicit hold-require (this was the HIGH leak).
_HOLD_WITH_RAMP_MOTION = [
    "The ramp advances every clock cycle and is held at the top for two cycles.",
    "The counter increments every cycle and pauses at the maximum for one extra clock.",
    "The counter increments every cycle; the output dwells at the peak for two cycles.",
    "Hold the peak for two cycles, then immediately decrement.",
    "The output ramps up every clock and is held at the maximum, then reverses.",
]

# The Step-2.7 §4.05 MED reproduction (asymmetric-dwell triangle): a required
# hold at ONE extreme phrased alongside a no-dwell statement about the OPPOSITE
# extreme. The extreme-specific no-dwell (about the trough) MUST NOT disarm the
# required PEAK hold — this is the same #776 class. (Root cause: the
# extreme-specific one-cycle branches were STRONG "anywhere"; now WEAK.)
_ASYMMETRIC_DWELL = [
    "hold the peak for two cycles; the trough appears for exactly one cycle.",
    "The maximum is held for three clocks. The minimum stays for exactly one cycle.",
    "dwell at the top for 2 cycles, but the bottom is output for just one cycle.",
    "The peak dwells for two clocks; the bottom stays for just a single cycle.",
    "hold the peak for two cycles; the trough is only one cycle wide.",
]


def test_A_convention_fires_on_explicit_hold_require():
    for ex in _REQUIRE:
        assert scc._spec_requires_peak_hold(_WGEN + ex + ".") is True, ex


def test_B_plain_triangle_no_holdrequire_disarms_convention():
    for ex in _PLAIN_TRIANGLE:
        assert scc._spec_requires_peak_hold(_WGEN + ex + ".") is False, ex


def test_B_documented_lesson_example_now_caught():
    """The lesson's own forbid example 'advances every single cycle including the
    turn' (a plain-triangle spec, no hold-require) disarms the gate — it
    previously did NOT (the single-source-drift this fix closes)."""
    assert scc._spec_requires_peak_hold(
        _WGEN + "advances every single cycle including the turn.") is False


def test_STRONG_forbid_overrides_even_a_hold_require():
    for ex in _STRONG:
        txt = _WGEN + "hold the peak. " + ex + "."
        assert scc._spec_requires_peak_hold(txt) is False, ex


def test_step27_weak_motion_does_NOT_override_hold_require():
    """§4.05 NO-LEAK (the Step-2.7 HIGH finding): a bare ramp/motion phrase must
    NOT disarm an EXPLICIT hold-require — that re-opens the #776 class (a
    required hold silently dropped -> 0/100)."""
    for ex in _HOLD_WITH_RAMP_MOTION:
        assert scc._spec_requires_peak_hold(_WGEN + ex) is True, ex


def test_step27_asymmetric_dwell_opposite_extreme_no_dwell_does_NOT_disarm():
    """§4.05 NO-LEAK (the Step-2.7 MED finding): a no-dwell statement about the
    OPPOSITE extreme (e.g. 'the trough appears for exactly one cycle') must NOT
    disarm a REQUIRED hold at the peak on an asymmetric-dwell triangle. The
    extreme-specific one-cycle branches are WEAK (disarm only absent a
    hold-require), not STRONG-anywhere."""
    for ex in _ASYMMETRIC_DWELL:
        assert scc._spec_requires_peak_hold(_WGEN + ex) is True, ex


def test_C_regression_rtllm_signal_generator_unaffected():
    """The canonical RTLLM signal_generator golden HOLDS the peak; the fix must
    not disarm it (#776: dropping the hold was a real 0/100 regression). No
    explicit hold-require + no explicit forbid => gate silent (False); the
    authoring peak-hold default is NOT disarmed for it."""
    assert scc._spec_requires_peak_hold(_RTLLM_SIGNAL_GENERATOR) is False
    assert scc._HOLD_FORBID_STRONG_RE.search(_RTLLM_SIGNAL_GENERATOR) is None
    assert scc._HOLD_FORBID_WEAK_RE.search(_RTLLM_SIGNAL_GENERATOR) is None


def test_C_no_leak_hold_require_clauses_not_strong_forbidden():
    """LEAK GUARD: 'held for one extra cycle' / 'held for one cycle' / 'stays for
    one cycle' are HOLDS — the STRONG forbid detector must NOT match them (bare
    'for one cycle' is deliberately excluded, only 'exactly/only/just')."""
    for keep in [
        "the maximum value is held for one cycle",
        "the peak remains held for a single extra cycle",
        "hold the peak; dwell at the top for 3 clocks",
        "the peak stays for one cycle",
        "increment every cycle until it reaches the peak, then hold for one extra cycle",
    ]:
        assert scc._HOLD_FORBID_STRONG_RE.search(_WGEN + keep + ".") is None, keep
