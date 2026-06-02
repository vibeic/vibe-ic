"""tests/test_phase1_issue8_v1673_residual.py — v1.6.73

Closes GitHub issue #8 Bug A v1.6.72 residual leaks reported by the
field agent on real-benchmark thin inputs:

  Residual #1  Markdown subsection heading `## AXI4 interface ##` plus
               `Optional AXI4-stream wrapper available` co-occurring
               with surrounding sha256-class README text. The literal
               heading-line + wrapper-line ARE rejected by v1.6.72's
               `_HEADING_PERIPHERAL_INTERFACE_RE` and `_WRAPPER_PHRASE_RE`
               on the per-line scan; this test pins that behavior so a
               future regex regression surfaces immediately.

  Residual #2  Single-wire / half-duplex bare-keyword scan in
               `gen_l2_frs` fired on PTP clock-routing prose
               `connected to the leaf clocks through a single wire that
                carries serial data for clock distribution`
               where `single wire` is the physical clock-distribution
               wire, NOT a command-bus claim. v1.6.73 requires the
               keyword to co-occur (a) with a protocol-class noun
               (protocol/bus/interface/frame/opcode/command/example_protocol/maxim/
               dallas/wake/response/transaction/payload/crc/parity/
               signaling) in the same sentence, OR (b) with the
               complementary single-wire+half-duplex pair in the same
               sentence. EXAMPLE_CHIP-class
               `single-wire half-duplex authentication IC` still
               passes via (b).

Durable rule: every regex change ships with a reject-test pair
(`feedback_general_fixes_no_false_alert.md`).
"""
from __future__ import annotations

import json
from pathlib import Path

from programs.phase1_one_shot_runner import gen_l2_frs

_GEN_DIR = Path("phase1") / "generated_docs"


def _seed(tmp_path: Path) -> Path:
    project = tmp_path
    (project / _GEN_DIR).mkdir(parents=True, exist_ok=True)
    return project


def _read(project: Path, name: str) -> dict:
    return json.loads(
        (project / _GEN_DIR / f"{name}.json").read_text()
    )


# ---------------------------------------------------------------------------
# Residual #1 — sha256 README with `## AXI4 interface ##` heading
# ---------------------------------------------------------------------------

def test_l2_protocol_overview_rejects_axi4_h2_heading_v1673(
        tmp_path: Path) -> None:
    """v1.6.72 already rejects the literal `## AXI4 interface ##`
    heading via `_HEADING_PERIPHERAL_INTERFACE_RE` and the
    `Optional AXI4-stream wrapper available` line via
    `_WRAPPER_PHRASE_RE`. v1.6.73 must continue to reject this exact
    sha256-fixture-shaped README so a future regex change can't
    re-leak it."""
    project = _seed(tmp_path)
    extracted = {
        "README.md": (
            "# SHA-256 Hash Core\n\n"
            "Pure combinational FIPS 180-4 hash core.\n"
            "Block size 512, digest 256.\n\n"
            "## AXI4 interface ##\n\n"
            "Optional AXI4-stream wrapper available "
            "in src/interfaces/axi4/.\n"
        ),
    }
    gen_l2_frs(project, extracted)
    l2 = _read(project, "L2_FRS")
    assert l2.get("protocol_overview") is None
    assert l2.get("no_protocol_overview_in_input") is True


# ---------------------------------------------------------------------------
# Residual #2 — Taxi PTP single-wire clock-routing false positive
# ---------------------------------------------------------------------------

def test_l2_single_wire_clock_routing_does_not_leak_v1673(
        tmp_path: Path) -> None:
    """v1.6.72 false positive: the bare `single wire` keyword fired
    on PTP clock-distribution prose. The sentence has no
    protocol-class noun, so v1.6.73's sentence-anchored gate must
    drop it."""
    project = _seed(tmp_path)
    extracted = {
        "README.md": (
            "# Taxi networking IP\n\n"
            "The PTP TD PHC is connected to the leaf clocks through "
            "a single wire that carries serial data for clock "
            "distribution.\n"
        ),
    }
    gen_l2_frs(project, extracted)
    l2 = _read(project, "L2_FRS")
    assert l2.get("protocol_overview") is None
    assert l2.get("no_protocol_overview_in_input") is True


def test_l2_pure_clock_routing_single_wire_no_leak(
        tmp_path: Path) -> None:
    """Variant: shorter clock-routing sentence, still no protocol
    noun. Must reject."""
    project = _seed(tmp_path)
    extracted = {
        "README.md": (
            "PTP TD PHC connected to leaf clocks through a single "
            "wire carrying clock data for distribution.\n"
        ),
    }
    gen_l2_frs(project, extracted)
    l2 = _read(project, "L2_FRS")
    assert l2.get("protocol_overview") is None


# ---------------------------------------------------------------------------
# Positive controls — must NOT over-correct
# ---------------------------------------------------------------------------

def test_l2_single_wire_aid_bus_still_emits_dict_v1673(
        tmp_path: Path) -> None:
    """Positive control: rich-input single-wire EXAMPLE_PROTOCOL command bus
    must STILL emit the dict. Don't over-correct."""
    project = _seed(tmp_path)
    extracted = {
        "datasheet.txt": (
            "EXAMPLE_CHIP ID IC over a single-wire EXAMPLE_PROTOCOL command bus.\n"
            "Half-duplex frames carry opcodes and responses.\n"
            "Wake pulse required before each command.\n"
        ),
    }
    gen_l2_frs(project, extracted)
    l2 = _read(project, "L2_FRS")
    po = l2.get("protocol_overview")
    assert po is not None
    assert po["half_duplex"] is True
    assert po["wire_count"] == 1


def test_l2_example_chip_short_single_wire_half_duplex_pair(
        tmp_path: Path) -> None:
    """Positive control: minimal single-line description with both
    `single-wire` and `half-duplex` keywords on the same sentence
    must still emit the dict via the co-occurrence fallback. This
    is the EXAMPLE_CHIP `single-wire half-duplex authentication IC` form
    that the v1.6.73 sentence-anchored gate would otherwise reject
    (no `protocol`/`bus`/etc. noun in sentence)."""
    project = _seed(tmp_path)
    extracted = {
        "datasheet.txt": (
            "EXAMPLE_CHIP single-wire half-duplex authentication IC.\n"
        ),
    }
    gen_l2_frs(project, extracted)
    l2 = _read(project, "L2_FRS")
    po = l2.get("protocol_overview")
    assert po is not None
    assert po["half_duplex"] is True
    assert po["wire_count"] == 1


def test_l2_maxim_onewire_protocol_still_emits(
        tmp_path: Path) -> None:
    """Positive control: Maxim/Dallas 1-Wire protocol device.
    Sentence has `1-Wire` + `protocol` noun -> accept."""
    project = _seed(tmp_path)
    extracted = {
        "datasheet.txt": (
            "Maxim/Dallas 1-Wire protocol device with half-duplex "
            "frame signaling.\n"
        ),
    }
    gen_l2_frs(project, extracted)
    l2 = _read(project, "L2_FRS")
    po = l2.get("protocol_overview")
    assert po is not None
    assert po["half_duplex"] is True
    assert po["wire_count"] == 1


# ---------------------------------------------------------------------------
# Aggregate — both v1.6.72 residual classes must now reject
# ---------------------------------------------------------------------------

def test_l2_aggregate_v1673_two_residual_classes_no_leak(
        tmp_path_factory) -> None:
    """Both v1.6.72 residual leak cases must now emit null."""
    cases = [
        (
            "sha256",
            "# SHA-256\nNIST FIPS.\n\n"
            "## AXI4 interface ##\n\n"
            "Optional AXI4-stream wrapper available.\n",
        ),
        (
            "taxi",
            "PTP clocks connected through a single wire that "
            "carries serial data for clock distribution.\n",
        ),
    ]
    leaked = []
    for label, src in cases:
        proj = tmp_path_factory.mktemp(label)
        (proj / _GEN_DIR).mkdir(parents=True, exist_ok=True)
        gen_l2_frs(proj, {"spec.txt": src})
        l2 = json.loads(
            (proj / _GEN_DIR / "L2_FRS.json").read_text()
        )
        if l2.get("protocol_overview") is not None:
            leaked.append(label)
    assert not leaked, f"v1.6.73 dict leak: {leaked}"
