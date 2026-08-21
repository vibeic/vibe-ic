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

ROUND-2 FIX (ORGANIC-20260607 #495 REOPENED)
============================================
The round-1 test discovered the four canonical shapes by globbing the
on-disk ``benchmark_clean/`` and ``benchmark_phase1/`` directories. The
field agent's counter-evidence: those directories exist on NEITHER the
review-cache tree NOR the marketplace source tree — they live only in
the core agent's own monorepo. So everywhere else the four shape
fixtures SKIPPED (``1 passed, 6 skipped``), and the anti-drift power of
the test was ≈ 0 (only the source-order pin actually ran).

This round replaces the external-directory dependence with EMBEDDED
minimal L-doc shapes: for each of the four campaign IC classes we
extracted the DECISIVE fields that the live detector consumes (read off
the real ``generated_docs`` on the monorepo) and inlined them as fixture
dicts INSIDE this test under synthetic, deny-list-safe names. Each
embedded fixture writes its shape into ``tmp_path`` as ``L*.json`` and
runs the REAL ``detect_ic_class`` → asserts the expected class. These
fixtures RUN (do not skip) on ANY tree — the always-on primary pin.

The four DECISIVE SHAPES (derived from real generated_docs, minimal):
  * pure_analog                  — L5 with an ``analog_blocks`` list
    carrying a positive analog marker (high-confidence block, or a
    low-confidence block with an instance count); no commands, no FSM,
    no protocol. → is_pure_analog branch.
  * processor_cpu                — L1/L2 prose with ≥3 processor-cpu
    structural features INCLUDING an ISA-bearing one (RISC-V / ISA /
    instruction set). No analog. → processor_cpu branch.
  * digital_cmd_driven           — L3 with a real (non-scrubbed) opcode
    table. No analog. → is_pure_digital + has_command_protocol branch.
  * digital_arithmetic_primitive — L1/L2 present, no analog, no command
    protocol, and no bus / serial / cpu signature. → arithmetic-
    primitive catch-all.

The real-docs discovery fixtures are KEPT as a clearly-labelled
SECONDARY parametrize that skips honestly off-monorepo, so when the run
IS on the monorepo we still pin the verdict against the genuine L-doc
state (not just the embedded distillation). The embedded set is the
primary always-on pin; the discovery set is the on-monorepo bonus.

DENY-LIST DISCIPLINE
====================
``programs/tests/chip_deny_list.txt`` denies project-name tokens (e.g.
``u_hawaii``). The embedded fixtures use synthetic generic names
(``generic_part_a`` …) and the discovery set NEVER writes a project
name (every fixture is discovered by STRUCTURAL signature on the live
detector). ``source_chip_agnostic_check.py`` stays PASS.
"""
import json
import sys
from pathlib import Path

import pytest

_THIS = Path(__file__).resolve()
_PLUGIN_ROOT = _THIS.parent.parent.parent          # …/plugins/vibe-ic
sys.path.insert(0, str(_PLUGIN_ROOT / "programs"))
import ic_class_profile as ICP  # noqa: E402


# ════════════════════════════════════════════════════════════════════
# PRIMARY (ALWAYS-ON): embedded minimal decisive L-doc shapes.
#
# Each shape is the MINIMAL set of decisive fields the live detector
# consumes for that class, distilled from the real campaign-IC
# generated_docs. Synthetic, deny-list-safe names only. These run on
# ANY tree (no benchmark_clean / benchmark_phase1 dependence) — closing
# the field agent's "≈ 0 anti-drift power off-monorepo" gap.
# ════════════════════════════════════════════════════════════════════

# pure_analog: L5 carries a positive analog marker (high-confidence
# block ⇒ marker regardless of count); no commands, no FSM, no protocol.
_EMBEDDED_PURE_ANALOG = {
    "L1_DATASHEET.json": {
        "schema_version": "1.0",
        "doc_class": "L1_DATASHEET",
        "ic_name": "generic_part_a",
    },
    "L5_ADI_SPEC.json": {
        "schema_version": "1.0",
        "doc_class": "L5_ADI_SPEC",
        "no_analog": False,
        "analog_blocks": [
            {
                "name": "front_end",
                "type": "adc",
                "spec": {"resolution_bits": 12},
                "low_confidence": False,
            }
        ],
    },
}

# processor_cpu: ≥3 processor features incl. an ISA-bearing one. The
# detector harvests ALL string leaves of L1+L2, so the decisive prose
# can live in any text field.
_EMBEDDED_PROCESSOR_CPU = {
    "L1_DATASHEET.json": {
        "schema_version": "1.0",
        "doc_class": "L1_DATASHEET",
        "ic_name": "generic_part_b",
        "description": (
            "A small RISC-V soft-core processor (RV32I base ISA) with a "
            "program counter and register file."
        ),
    },
    "L2_FRS.json": {
        "schema_version": "1.0",
        "doc_class": "L2_FRS",
        "functional_requirements": (
            "The CPU executes the RV32I instruction set; an instruction "
            "fetch unit drives the memory bus; the ALU performs "
            "load/store and branch instruction handling."
        ),
    },
}

# digital_cmd_driven: L3 with a real (non-scrubbed) opcode table.
_EMBEDDED_DIGITAL_CMD_DRIVEN = {
    "L1_DATASHEET.json": {
        "schema_version": "1.0",
        "doc_class": "L1_DATASHEET",
        "ic_name": "generic_part_c",
    },
    "L2_FRS.json": {
        "schema_version": "1.0",
        "doc_class": "L2_FRS",
    },
    "L3_CMD_PROTOCOL.json": {
        "schema_version": "1.0",
        "doc_class": "L3_CMD_PROTOCOL",
        "opcodes": [
            {"hex": "0x00", "name": "READ_STATUS",
             "payload_bytes": 1, "direction": "read"},
            {"hex": "0x01", "name": "WRITE_CTRL",
             "payload_bytes": 2, "direction": "write"},
        ],
    },
}

# digital_arithmetic_primitive: L1/L2 present, no analog, no command
# protocol, and no bus / serial / cpu signature → the catch-all.
_EMBEDDED_DIGITAL_ARITH = {
    "L1_DATASHEET.json": {
        "schema_version": "1.0",
        "doc_class": "L1_DATASHEET",
        "ic_name": "generic_part_d",
        "description": (
            "A fixed-function combinational datapath block computing a "
            "digest over a fixed-width input word."
        ),
    },
    "L2_FRS.json": {
        "schema_version": "1.0",
        "doc_class": "L2_FRS",
        "functional_requirements": (
            "Pure datapath primitive: pipelined message-schedule and "
            "compression rounds. No external command interface, no "
            "analog content."
        ),
    },
}

# data_converter (ORGANIC #613): analog content (L5 analog_blocks + L1
# declares an analog/mixed-signal class) AND a DIGITAL serial readout
# (1-bit serial / dout-style bitstream) but NO command protocol and NO
# FSM. The serial-readout signature is what separates this from
# _EMBEDDED_PURE_ANALOG (which has analog_blocks but NO digital readout):
# it must classify as data_converter, NOT collapse to pure_analog (which
# SKIPs RTL entirely). Generic data-converter vocabulary only, deny-safe.
_EMBEDDED_DATA_CONVERTER = {
    "L1_DATASHEET.json": {
        "schema_version": "1.0",
        "doc_class": "L1_DATASHEET",
        "ic_name": "generic_part_e",
        "class": "mixed_signal_adc",
        "description": (
            "Multi-channel sigma-delta converter front-end with "
            "Digital serial outputs OUT1..OUT6 (+ dout serial)."
        ),
    },
    "L5_ADI_SPEC.json": {
        "schema_version": "1.0",
        "doc_class": "L5_ADI_SPEC",
        "no_analog": False,
        "analog_blocks": [
            {
                "name": "modulator_ch",
                "type": "delta_sigma",
                "spec": {"order": 2},
                "low_confidence": False,
            }
        ],
        "signaling_summary": (
            "Each channel: output 1-bit serial (OUTn / dout) — a digital "
            "bitstream per channel from the decimation datapath."
        ),
    },
}

_EMBEDDED_SHAPES = {
    "pure_analog": _EMBEDDED_PURE_ANALOG,
    "processor_cpu": _EMBEDDED_PROCESSOR_CPU,
    "digital_cmd_driven": _EMBEDDED_DIGITAL_CMD_DRIVEN,
    "digital_arithmetic_primitive": _EMBEDDED_DIGITAL_ARITH,
    "data_converter": _EMBEDDED_DATA_CONVERTER,
}


def _write_embedded_project(docs: dict, tmp_path: Path) -> Path:
    """Write an embedded shape's L*.json into a FRESH tmp project's
    generated_docs and return the project root. The project carries no
    persisted reports/ic_class.json, so the REAL detector infers fresh."""
    proj = tmp_path / "chip"
    gd = ICP._pl.generated_docs_dir(proj)
    gd.mkdir(parents=True)
    for fname, body in docs.items():
        (gd / fname).write_text(json.dumps(body), encoding="utf-8")
    return proj


@pytest.mark.parametrize("expected_class", sorted(_EMBEDDED_SHAPES))
def test_embedded_campaign_ic_shape_classifies_stably(expected_class,
                                                      tmp_path):
    """PRIMARY always-on pin: the REAL detector must return the EXPECTED
    class for each embedded minimal decisive shape. Unlike the discovery
    fixtures this NEVER skips — it does not depend on benchmark_clean /
    benchmark_phase1 existing, so it has full anti-drift power on the
    review-cache tree, the marketplace source tree, and any other tree
    (the gap ORGANIC-20260607 #495 was REOPENED on). A detector change
    that flips a shape fails HERE, forcing the re-classification to be a
    visible, deliberate test update."""
    proj = _write_embedded_project(_EMBEDDED_SHAPES[expected_class],
                                   tmp_path)
    profile = ICP.detect_ic_class(proj)
    assert profile["ic_class"] == expected_class, (
        f"embedded campaign-IC shape {expected_class!r} drifted to "
        f"{profile['ic_class']!r} — if this is a deliberate detector "
        f"change, update the embedded shape; otherwise it is a silent "
        f"#495 flip"
    )


def test_embedded_shapes_emit_decisive_evidence(tmp_path):
    """Every embedded shape produces a non-empty ``decisive_evidence``
    naming the deciding branch, both in the in-memory profile and the
    persisted ``reports/ic_class.json`` (#435 single source of truth +
    #495 drift-diagnosis surface). Always-on — no monorepo dependence."""
    for expected_class, docs in sorted(_EMBEDDED_SHAPES.items()):
        sub = tmp_path / expected_class
        proj = _write_embedded_project(docs, sub)
        profile = ICP.detect_ic_class(proj)

        assert profile["ic_class"] == expected_class
        ev = profile.get("decisive_evidence", "")
        assert isinstance(ev, str) and ev.strip(), (
            f"{expected_class!r} produced empty decisive_evidence")
        # The default sentinel must never survive a real classification.
        assert ev != "no_project_dir"

        persisted = json.loads(
            (proj / "reports" / "ic_class.json").read_text(
                encoding="utf-8"))
        assert persisted.get("ic_class") == expected_class
        assert "decisive_evidence" in persisted, (
            "persisted reports/ic_class.json must carry decisive_evidence")
        assert persisted["decisive_evidence"] == ev


def test_embedded_shapes_are_deny_list_safe():
    """The embedded fixtures must never carry a denied chip/vendor token.
    Pins the chip-AGNOSTIC discipline at the data level so a future edit
    that pastes a real chip name into a fixture is caught here as well as
    by source_chip_agnostic_check.py."""
    deny_file = _THIS.parent / "chip_deny_list.txt"
    denied = []
    for line in deny_file.read_text(encoding="utf-8").splitlines():
        line = line.split("#", 1)[0].strip().lower()
        if line:
            denied.append(line)
    blob = json.dumps(_EMBEDDED_SHAPES).lower()
    for tok in denied:
        assert tok not in blob, (
            f"embedded fixture leaks denied token {tok!r}")


# ════════════════════════════════════════════════════════════════════
# SECONDARY (ON-MONOREPO BONUS): real-docs discovery fixtures.
#
# When the run IS on the core agent's monorepo, also pin the verdict
# against the GENUINE on-disk L-doc state (not just the embedded
# distillation). These skip HONESTLY off-monorepo (dormant-test
# discipline) — they are a bonus, NOT the primary anti-drift net.
# ════════════════════════════════════════════════════════════════════

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
# class and selected by a STRUCTURAL predicate (no chip names).
_DISCOVERY_SHAPES = {
    "pure_analog": _is_pure_analog_shape,
    "processor_cpu": _is_processor_cpu_shape,
    "digital_cmd_driven": _is_digital_cmd_driven_shape,
    "digital_arithmetic_primitive": _is_digital_arith_primitive_shape,
}


def _repo_roots() -> list:
    """Every ``benchmark_clean`` / ``benchmark_phase1`` dir on the
    ancestor chain from the plugin root up to the filesystem root.
    Resolved by STRUCTURE, not a hard-coded parent count, so the
    marketplace nesting (a possibly-empty copy at the plugin root and the
    real one ~3 parents up) is handled robustly. Returns [] off-monorepo
    — then the discovery fixtures skip honestly and the embedded set
    above carries the anti-drift load."""
    seen = set()
    out = []
    for cand in [_PLUGIN_ROOT, *_PLUGIN_ROOT.parents]:
        for name in ("benchmark-data/ic", "benchmark-data/evaluation/phase1_parity"):
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


@pytest.mark.parametrize("expected_class", sorted(_DISCOVERY_SHAPES))
def test_real_docs_campaign_ic_shape_classifies_stably(expected_class,
                                                       tmp_path):
    """SECONDARY on-monorepo bonus: for each canonical campaign-IC shape
    discovered on disk, the REAL detector must return the EXPECTED class
    against the GENUINE L-doc state. SKIPS HONESTLY off-monorepo — the
    embedded set above is the primary always-on pin. A detector change
    that flips a real shape fails HERE when run on the monorepo."""
    src = _discover_shape(_DISCOVERY_SHAPES[expected_class])
    if src is None:
        pytest.skip(
            f"no on-disk project with the {expected_class!r} structural "
            "shape (dormant-test discipline; embedded set carries the "
            "anti-drift load off-monorepo)")

    proj = _copy_generated_docs(src, tmp_path)
    profile = ICP.detect_ic_class(proj)
    assert profile["ic_class"] == expected_class, (
        f"real-docs campaign-IC shape {expected_class!r} drifted to "
        f"{profile['ic_class']!r} — if this is a deliberate detector "
        f"change, update this fixture; otherwise it is a silent #495 flip"
    )


def test_real_docs_run_emits_decisive_evidence(tmp_path):
    """SECONDARY: a real-docs fixture run's persisted
    ``reports/ic_class.json`` must carry the #495 ``decisive_evidence``
    field. Verified on whatever shape is present; skips honestly if none
    of the four shapes is on disk (the embedded set already pins this
    off-monorepo)."""
    src = None
    for shape_predicate in _DISCOVERY_SHAPES.values():
        src = _discover_shape(shape_predicate)
        if src is not None:
            break
    if src is None:
        pytest.skip("no campaign-IC shape on disk (dormant-test "
                    "discipline; embedded set pins this off-monorepo)")

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


# ════════════════════════════════════════════════════════════════════
# SOURCE-ORDER PIN (always-on, KEPT from round-1).
# ════════════════════════════════════════════════════════════════════

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
