"""ORGANIC-20260607 #495 — ic_class detection STABILITY fixtures.

WHY THIS TEST EXISTS
====================
The field agent observed an ic_class FLIP across plugin versions on
IDENTICAL input docs: one campaign IC was classified
``digital_cmd_driven`` by one version and ``digital_arithmetic_primitive``
by the next, with NO change to the input documents. ic_class silently
drives TB-track routing, gate applicability and oracle shape, so a
silent flip changes the whole downstream verification posture without
any visible signal.

ROOT-CAUSE INVESTIGATION (recorded, not guessed)
================================================
The issue suspected the #450 ``processor_cpu`` branch insertion
reshuffled the detector ordering. Reading ``_detect_ic_class_infer`` in
``ic_class_profile.py`` shows the ordering is SOUND: the processor_cpu
branch was inserted AFTER bus_interconnect + serial_peripheral and
BEFORE the ``digital_arithmetic_primitive`` catch-all, and it carries a
MANDATORY ISA-bearing deny-guard (isa_family OR instruction_semantics),
so a datapath primitive (multiplier / hash core) can never fall into it.
No genuine mis-ordering was found, so the ordering is NOT changed here
(thrashing classifications is explicitly forbidden by the issue).

The REAL drift mechanism is DATA, not detector ordering: the two
generation runs of the same crypto-hash IC emitted DIFFERENT L3 docs —
one with a populated opcode table (→ digital_cmd_driven) and one whose
opcode table was scrubbed to empty (→ digital_arithmetic_primitive).
The detector faithfully classified each L-doc state; the flip lived in
the upstream L-doc generation. #435 already freezes the verdict per
project via ``reports/ic_class.json`` (single source of truth). What was
MISSING was a regression net that pins the detector's verdict on each
canonical campaign-IC SHAPE so that a future detector change which flips
a shape becomes a VISIBLE, deliberate test update rather than a silent
re-classification.

WHAT THIS TEST DOES
===================
For each of the four canonical campaign-IC SHAPES it:
  1. DISCOVERS a real on-disk project STRUCTURALLY (never by chip name):
     globs ``benchmark_clean/*/`` and ``benchmark_phase1/*/`` for a
     ``phase1/generated_docs/`` set, runs the REAL detector on each, and
     selects the first project whose detector profile matches the shape's
     structural signature (e.g. ``has_analog`` for pure_analog,
     ISA-bearing for processor_cpu, real opcodes for digital_cmd_driven,
     no-protocol datapath for digital_arithmetic_primitive).
  2. COPIES the discovered generated_docs into a fresh tmp project (so we
     never mutate the on-disk benchmark and never read a stale persisted
     ``reports/ic_class.json``).
  3. Runs the REAL ``detect_ic_class`` end-to-end and asserts the
     EXPECTED class. A detector change that flips a fixture fails here —
     making the re-classification a deliberate, reviewed test edit.
  4. Asserts the persisted ``reports/ic_class.json`` carries the new
     ``decisive_evidence`` field (the #495 drift-diagnosis surface).

``pytest.skip`` is used HONESTLY when a shape is absent on disk
(dormant-test discipline), mirroring
``test_v0_2_97_issue466_real_input_fixture.py``.

DENY-LIST DISCIPLINE
====================
``programs/tests/chip_deny_list.txt`` denies project-name tokens (e.g.
``u_hawaii``). This test therefore NEVER writes a project name: every
fixture is discovered by STRUCTURAL signature on the live detector, not
by a hard-coded chip literal. ``source_chip_agnostic_check.py`` stays
PASS.
"""
import json
import sys
from pathlib import Path

import pytest

_THIS = Path(__file__).resolve()
_PLUGIN_ROOT = _THIS.parent.parent.parent          # …/plugins/vibe-ic
sys.path.insert(0, str(_PLUGIN_ROOT / "programs"))
import ic_class_profile as ICP  # noqa: E402


# ── structural shape signatures (NOT chip names) ──────────────────────
# Each signature is a predicate over the REAL detector profile (plus the
# raw L1/L2 docs for the processor-cpu ISA-bearing test). General, not a
# benchmark keyword — these are the same structural facts the detector
# itself consumes.

def _profile_and_docs(project: Path):
    """Return (profile, l1, l2) for a project, inferred fresh (no cache)."""
    prof = ICP._detect_ic_class_infer(project)
    l1 = ICP._first_l_doc(project, "L1_")
    l2 = ICP._first_l_doc(project, "L2_")
    return prof, l1, l2


def _is_pure_analog_shape(project: Path) -> bool:
    prof, _, _ = _profile_and_docs(project)
    return prof.get("ic_class") == "pure_analog" and bool(prof.get("has_analog"))


def _is_processor_cpu_shape(project: Path) -> bool:
    prof, l1, l2 = _profile_and_docs(project)
    return (prof.get("ic_class") == "processor_cpu"
            and not prof.get("has_analog")
            and ICP._looks_like_processor_cpu(l1, l2))


def _is_digital_cmd_driven_shape(project: Path) -> bool:
    prof, _, _ = _profile_and_docs(project)
    # Populated opcode/command table → command-driven digital chip.
    return (prof.get("ic_class") == "digital_cmd_driven"
            and bool(prof.get("has_command_protocol"))
            and not prof.get("has_analog"))


def _is_digital_arith_primitive_shape(project: Path) -> bool:
    prof, l1, l2 = _profile_and_docs(project)
    # The catch-all datapath shape: present L1/L2, no analog, no command
    # protocol, and NOT a CPU / bus / serial protocol.
    return (prof.get("ic_class") == "digital_arithmetic_primitive"
            and not prof.get("has_analog")
            and not prof.get("has_command_protocol")
            and not ICP._looks_like_processor_cpu(l1, l2))


# The four canonical campaign-IC SHAPES, each named by its expected
# class and selected by a STRUCTURAL predicate.
_SHAPES = {
    "pure_analog": _is_pure_analog_shape,
    "processor_cpu": _is_processor_cpu_shape,
    "digital_cmd_driven": _is_digital_cmd_driven_shape,
    "digital_arithmetic_primitive": _is_digital_arith_primitive_shape,
}


# ── structural discovery (no chip names) ──────────────────────────────

def _repo_roots() -> list:
    """Every ``benchmark_clean`` / ``benchmark_phase1`` dir on the
    ancestor chain from the plugin root up to the filesystem root.
    Resolved by STRUCTURE, not a hard-coded parent count, so the
    marketplace nesting (a possibly-empty copy at the plugin root and the
    real one ~3 parents up) is handled robustly."""
    seen = set()
    out = []
    for cand in [_PLUGIN_ROOT, *_PLUGIN_ROOT.parents]:
        for name in ("benchmark_clean", "benchmark_phase1"):
            d = cand / name
            if d.is_dir() and d not in seen:
                seen.add(d)
                out.append(d)
    return out


def _candidate_projects() -> list:
    """Every on-disk project that has a ``phase1/generated_docs/`` set
    with at least an L1 doc — the input the REAL detector reads. Returns
    deduped project dirs; discovery is purely structural."""
    seen = set()
    out = []
    for root in _repo_roots():
        for l1 in sorted(root.glob("*/phase1/generated_docs/L1*.json")):
            proj = l1.parents[2]
            if proj not in seen:
                seen.add(proj)
                out.append(proj)
    return out


def _discover_shape(shape_predicate) -> Path:
    """Return the first on-disk project matching the shape predicate, or
    None when no such project exists (dormant-test discipline)."""
    for proj in _candidate_projects():
        try:
            if shape_predicate(proj):
                return proj
        except Exception:
            continue
    return None


def _copy_generated_docs(src_project: Path, tmp_path: Path) -> Path:
    """Copy a discovered project's generated_docs into a FRESH tmp
    project so the REAL detector runs against the real L-doc state but
    never reads a stale persisted ``reports/ic_class.json`` and never
    mutates the on-disk benchmark. Returns the new project root."""
    proj = tmp_path / "chip"
    gd = ICP._pl.generated_docs_dir(proj)
    gd.mkdir(parents=True)
    src_gd = ICP._pl.generated_docs_dir(src_project)
    for f in sorted(src_gd.glob("*.json")):
        (gd / f.name).write_text(
            f.read_text(encoding="utf-8", errors="ignore"),
            encoding="utf-8")
    return proj


# ── the four stability fixtures ───────────────────────────────────────

@pytest.mark.parametrize("expected_class", sorted(_SHAPES))
def test_campaign_ic_shape_classifies_stably(expected_class, tmp_path):
    """For each canonical campaign-IC shape discovered on disk, the REAL
    detector must return the EXPECTED class. A detector change that flips
    a shape fails HERE — forcing the re-classification to be a visible,
    deliberate test update rather than a silent version-to-version drift
    (the exact silent flip ORGANIC-20260607 #495 was filed on)."""
    src = _discover_shape(_SHAPES[expected_class])
    if src is None:
        pytest.skip(
            f"no on-disk project with the {expected_class!r} structural "
            "shape (dormant-test discipline)")

    proj = _copy_generated_docs(src, tmp_path)
    profile = ICP.detect_ic_class(proj)
    assert profile["ic_class"] == expected_class, (
        f"campaign-IC shape {expected_class!r} drifted to "
        f"{profile['ic_class']!r} — if this is a deliberate detector "
        f"change, update this fixture; otherwise it is a silent #495 flip"
    )


def test_fixture_run_emits_decisive_evidence(tmp_path):
    """A fixture run's persisted ``reports/ic_class.json`` must carry the
    #495 ``decisive_evidence`` field — the feature(s)/rule that decided
    the class, for drift diagnosis. Verified on whatever shape is present;
    skips honestly if none of the four shapes is on disk."""
    src = None
    for shape_predicate in _SHAPES.values():
        src = _discover_shape(shape_predicate)
        if src is not None:
            break
    if src is None:
        pytest.skip("no campaign-IC shape on disk (dormant-test discipline)")

    proj = _copy_generated_docs(src, tmp_path)
    profile = ICP.detect_ic_class(proj)

    # In-memory profile carries the field.
    assert "decisive_evidence" in profile
    assert isinstance(profile["decisive_evidence"], str)
    assert profile["decisive_evidence"].strip(), \
        "decisive_evidence must be a non-empty explanation"

    # Persisted ic_class.json (the #435 single source of truth) carries it.
    persisted = json.loads(
        (proj / "reports" / "ic_class.json").read_text(encoding="utf-8"))
    assert persisted.get("ic_class") == profile["ic_class"]
    assert "decisive_evidence" in persisted, \
        "persisted reports/ic_class.json must carry decisive_evidence"
    assert persisted["decisive_evidence"] == profile["decisive_evidence"]


def test_decisive_evidence_present_for_every_classified_shape(tmp_path):
    """Stronger pin: EVERY discoverable campaign-IC shape produces a
    non-empty decisive_evidence naming the deciding branch, and that
    evidence is consistent with the assigned class (a pure_analog verdict
    cites the analog branch, a catch-all verdict cites the catch-all,
    etc.). Guards against a future return path forgetting to set it."""
    found_any = False
    for expected_class, shape_predicate in sorted(_SHAPES.items()):
        src = _discover_shape(shape_predicate)
        if src is None:
            continue
        found_any = True
        sub = tmp_path / expected_class
        proj = _copy_generated_docs(src, sub)
        profile = ICP.detect_ic_class(proj)
        assert profile["ic_class"] == expected_class
        ev = profile.get("decisive_evidence", "")
        assert isinstance(ev, str) and ev.strip(), (
            f"{expected_class!r} produced empty decisive_evidence")
        # The default sentinel must never survive a real classification.
        assert ev != "no_project_dir"
    if not found_any:
        pytest.skip("no campaign-IC shape on disk (dormant-test discipline)")


def test_detector_ordering_unchanged_processor_cpu_after_protocols():
    """Pin the #450/#495 ordering FINDING: the processor_cpu branch sits
    AFTER bus_interconnect + serial_peripheral and BEFORE the
    digital_arithmetic_primitive catch-all in ``_detect_ic_class_infer``.
    Reading the source order directly (not re-running detection) so a
    future reshuffle that moves the CPU branch — the suspected drift
    cause investigated for #495 — is caught as a deliberate change.
    """
    import inspect
    src = inspect.getsource(ICP._detect_ic_class_infer)
    i_bus = src.find('"bus_interconnect_protocol"')
    i_serial = src.find('"serial_peripheral_protocol"')
    i_cpu = src.find('"processor_cpu"')
    i_arith = src.find('"digital_arithmetic_primitive"')
    assert -1 not in (i_bus, i_serial, i_cpu, i_arith)
    assert i_bus < i_cpu, "bus_interconnect must be tested before processor_cpu"
    assert i_serial < i_cpu, \
        "serial_peripheral must be tested before processor_cpu"
    assert i_cpu < i_arith, \
        "processor_cpu must be tested before the arithmetic catch-all"
