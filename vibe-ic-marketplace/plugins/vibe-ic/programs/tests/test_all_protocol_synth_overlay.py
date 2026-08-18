"""Universal overlay-contract sweep for EVERY ``*_protocol_synth.py``.

THE COMPOUNDING ARTIFACT for Phase-1 protocol overlays. Instead of one
hand-written direct test per protocol (``test_espi_protocol_synth.py``,
``test_lpc_protocol_synth.py``, ...), this test GLOB-discovers every
``programs/<base>_protocol_synth.py`` and asserts the four contract clauses
the 7 good per-protocol tests pin — with ZERO new test code per future
protocol. It lifts ``*_protocol_synth.py`` unit coverage from a handful of
hand-written modules to all 86 in one parametrized sweep.

Per discovered module ``<base>_protocol_synth.py`` (parametrized over the
discovered list) we seed a ``tmp_path/generated_docs`` with minimal empty
L1..L23 JSON stubs and assert:

  (1) the module exports ``apply_<base>_synth`` callable. As of v0.2.32
      (ORGANIC-20260531 CLOSED for importability) the companion content
      detector ``is_<base>`` is a module-level callable for EVERY protocol —
      the ~47 older detectors that used to live INLINE in
      ``phase1_doc_one_shot_runner.py`` were lifted into importable predicates
      (pinned by ``test_all_protocol_synth_detectors_importable.py``), so the
      ``detector_inline`` census below should now be 0. The clause-4 detector
      contract therefore applies to every module. Where the module opts into
      the generic auto-dispatch (``AUTO_DISPATCH`` / ``IC_NAME`` present),
      ``AUTO_DISPATCH`` must be a ``bool`` and ``IC_NAME`` a non-empty ``str``.
  (2) ``apply_<base>_synth(gd, False, None)`` is a NO-OP — every L-doc byte
      unchanged (the contract the 7 good tests pin). Documented exceptions
      (a synth whose flag-False path legitimately writes class-universal
      facts) are recorded in ``KNOWN_NOOP_EXCEPTIONS`` with a reason and
      xfail rather than silently passing.
  (3) ``apply_<base>_synth(gd, True, <ic_name>)`` runs WITHOUT raising,
      mutates at least ``L1_DATASHEET.json`` AND ``L9_INTEGRATION_SPEC.json``,
      every emitted JSON re-parses (``json.loads`` round-trips), and the
      passed ``<ic_name>`` appears in ``L1_DATASHEET.json``.
  (4) ``is_<base>('') == is_<base>(None) == False`` (only for modules that
      expose a module-level ``is_<base>``).

Robustness: the ``<base>`` is discovered from the file stem and cross-checked
against the actual ``apply_<stem>_synth`` / ``is_<stem>`` module members. A
module that genuinely lacks an ``apply`` overlay is xfailed-with-reason (and
counted) rather than hard-erroring; ``test_overlay_population_report`` prints
the census (total / detector-exposing / detector-inline / no-apply).
"""
import importlib
import json
from pathlib import Path

import pytest

PROGRAMS_DIR = Path(__file__).resolve().parent.parent

# The full L1..L23 layer-doc set the runner emits. ``apply_<base>_synth`` only
# writes a doc whose stub file already exists, so we must seed all of them.
# Note the TWO L8 variants (RTL constants + timing waveform) the flat-doc
# overlays both target.
L_DOCS = (
    "L1_DATASHEET", "L2_FRS", "L3_CMD_PROTOCOL", "L4_REGMAP", "L5_ADI_SPEC",
    "L6_CONTROL_LOGIC", "L7_TEST_DEBUG", "L8_RTL_CONSTANTS",
    "L8_TIMING_WAVEFORM", "L9_INTEGRATION_SPEC", "L10_TEST_CASES",
    "L11_OTP_CONTENT", "L12_BEHAVIORAL_SEQUENCES", "L13_LAB_CALIBRATION",
    "L14_PROTOCOL_VERSIONING", "L15_ENCODING_TABLES",
    "L16_COMPLIANCE_PROPERTIES", "L17_CHANNEL_SIGNAL_CATALOG",
    "L18_INTERCONNECT_TOPOLOGY", "L19_CONSTRAINTS_PDK",
    "L20_DFT_SCAN_TOPOLOGY", "L21_POWER_INTENT", "L22_VERIFICATION_PLAN",
    "L23_SECURITY_REQUIREMENTS",
)

# Documented clause-(2) exceptions: a synth whose flag-False path is, BY
# DESIGN, not a pure no-op. ``spi_protocol_synth`` applies its R53
# class-universal presence facts UNCONDITIONALLY (see the H4 comment in
# ``apply_spi_synth``) — those facts are emitted for every serial-peripheral
# IC regardless of the SPI flag, so flag-False still writes. Recorded here so
# the sweep xfails (visible) instead of the test silently weakening.
KNOWN_NOOP_EXCEPTIONS = {
    "spi": "apply_spi_synth applies R53 class-universal facts unconditionally "
           "(H4 masked-upstream-defect fix); flag-False is intentionally not a "
           "pure no-op.",
}


def _discover():
    """Sorted list of ``<base>`` for every ``<base>_protocol_synth.py``."""
    bases = []
    for p in sorted(PROGRAMS_DIR.glob("*_protocol_synth.py")):
        bases.append(p.name[: -len("_protocol_synth.py")])
    return bases


BASES = _discover()


def _load(base):
    """Import the module and resolve (is_fn, apply_fn) for ``base``.

    ``apply`` follows the stem for every shipped module; ``is_<stem>`` is a
    module-level callable only for the auto-dispatch-convention protocols.
    Both are resolved by inspecting module members so a module that drifts
    from the stem convention surfaces as a missing-member xfail, not a crash.
    """
    mod = importlib.import_module(f"{base}_protocol_synth")
    is_fn = getattr(mod, f"is_{base}", None)
    apply_fn = getattr(mod, f"apply_{base}_synth", None)
    return mod, is_fn, apply_fn


def _seed(tmp_path):
    """tmp_path/generated_docs with minimal empty L1..L23 JSON stubs.

    Each stub carries a sentinel ``ic_name`` and an empty ``fields`` wrapper so
    both the flat-doc and the fields-wrapped overlay paths have a base object
    to merge into.
    """
    gd = tmp_path / "generated_docs"
    gd.mkdir(exist_ok=True)
    for n in L_DOCS:
        (gd / f"{n}.json").write_text(
            json.dumps({"ic_name": "UNKNOWN", "fields": {}}))
    return gd


def _snapshot(gd):
    return {n: (gd / f"{n}.json").read_bytes() for n in L_DOCS}


@pytest.mark.parametrize("base", BASES)
def test_protocol_synth_overlay_contract(base, tmp_path):
    mod, is_fn, apply_fn = _load(base)

    # ── clause (1): apply overlay must exist. A module that genuinely lacks
    #    one is xfailed-with-reason (counted by the census test), not errored.
    if not callable(apply_fn):
        pytest.xfail(
            f"{base}_protocol_synth.py exposes no callable apply_{base}_synth "
            f"(no overlay) — recorded by test_overlay_population_report")

    has_detector = callable(is_fn)

    # ── clause (1, auto-dispatch sub-contract): only assert AUTO_DISPATCH /
    #    IC_NAME shape WHERE THEY ARE PRESENT (the conditional in the spec).
    if "AUTO_DISPATCH" in mod.__dict__:
        assert isinstance(mod.AUTO_DISPATCH, bool), (
            f"{base}: AUTO_DISPATCH present but not a bool")
    if "IC_NAME" in mod.__dict__:
        assert isinstance(mod.IC_NAME, str) and mod.IC_NAME, (
            f"{base}: IC_NAME present but not a non-empty str")
    # Auto-dispatch opt-in implies the module-level detector must be present.
    if mod.__dict__.get("AUTO_DISPATCH") is True:
        assert has_detector, (
            f"{base}: AUTO_DISPATCH=True but no module-level is_{base}")

    # ── clause (2): flag-False is a NO-OP (L-docs byte-unchanged).
    gd = _seed(tmp_path)
    before = _snapshot(gd)
    if base in KNOWN_NOOP_EXCEPTIONS:
        apply_fn(gd, False, None)
        if _snapshot(gd) != before:
            pytest.xfail(KNOWN_NOOP_EXCEPTIONS[base])
    else:
        apply_fn(gd, False, None)
        assert _snapshot(gd) == before, (
            f"apply_{base}_synth(gd, False, None) mutated L-docs — flag-False "
            f"must be a no-op")

    # ── clause (3): flag-True runs, mutates L1 AND L9, all JSON re-parses,
    #    and the passed ic_name lands in L1.
    gd = _seed(tmp_path)
    before = _snapshot(gd)
    ic_name = f"OVERLAY_TEST_IC_{base.upper()}"
    apply_fn(gd, True, ic_name)  # must not raise

    for n in L_DOCS:
        text = (gd / f"{n}.json").read_text()
        json.loads(text)  # round-trips → raises if a doc emitted bad JSON

    after = _snapshot(gd)
    assert after["L1_DATASHEET"] != before["L1_DATASHEET"], (
        f"apply_{base}_synth(True) did not mutate L1_DATASHEET")
    assert after["L9_INTEGRATION_SPEC"] != before["L9_INTEGRATION_SPEC"], (
        f"apply_{base}_synth(True) did not mutate L9_INTEGRATION_SPEC")
    assert ic_name in (gd / "L1_DATASHEET.json").read_text(), (
        f"passed ic_name {ic_name!r} did not appear in L1_DATASHEET")

    # ── clause (4): empty-blob detector safety (only where a detector exists).
    if has_detector:
        assert is_fn("") is False, f"is_{base}('') should be False"
        assert is_fn(None) is False, f"is_{base}(None) should be False"


def test_overlay_population_report():
    """Census of the 86 protocol-synth overlays — never vacuous.

    Guards against an import regression silently emptying the discovery set
    (which would make the parametrized sweep collect nothing) and prints the
    breakdown (total / detector-exposing / detector-inline / no-apply) the
    task asks to report.
    """
    assert BASES, "no *_protocol_synth.py modules discovered"
    detector_exposing, detector_inline, no_apply = [], [], []
    for base in BASES:
        _mod, is_fn, apply_fn = _load(base)
        if not callable(apply_fn):
            no_apply.append(base)
            continue
        (detector_exposing if callable(is_fn) else detector_inline).append(base)
    total = len(BASES)
    print(
        f"\nprotocol-synth overlay census: total={total} "
        f"detector-exposing(is_<base> module-level)={len(detector_exposing)} "
        f"detector-inline(no module-level is_<base>)={len(detector_inline)} "
        f"no-apply(xfail)={len(no_apply)}")
    if no_apply:
        print(f"  no-apply modules (xfailed): {no_apply}")
    # Sanity floor: the full benchmark set is 86 protocol overlays.
    assert total >= 86, f"expected >=86 protocol-synth modules, found {total}"
    # Every discovered module must expose an apply overlay (no silent gaps).
    assert not no_apply, f"modules lacking apply_<base>_synth: {no_apply}"
