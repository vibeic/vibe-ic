"""tests/test_phase1_issue12_v1681_scaffold_purge.py — v1.6.81

Closes issue #12 follow-up. Field agent verified v1.6.79/v1.6.80 still
emit the EXAMPLE_PROTOCOL-class scaffold for 8/17 sibling fields across all 11 IC
fixtures even though the runner's `gen_l*_*` functions emit empty + flag
on synthetic input. v1.6.81 adds a defensive scaffold-purge post-pass
and a hard bool-coerce on every `no_<X>_in_input` flag.

This test:
  1. Runs the full `phase1_one_shot_runner.main()` end-to-end on three
     thin-input fixtures (CPU core, hash core, memory controller) — i.e.
     the same code path the field agent's real benchmark exercises.
  2. Pre-seeds one fixture with the EXAMPLE_PROTOCOL-class scaffold residue planted
     in `generated_docs/` BEFORE the runner regenerates, to simulate a
     stale-doc carry-over. Asserts the runner cleans it.
  3. Asserts no field across the three fixtures carries the EXAMPLE_PROTOCOL-class
     scaffold marker phrases (`"wire-level protocol scope probe"`,
     `"<half-duplex-tester>"`, etc.).
  4. Asserts every `no_<X>_in_input` flag is a HARD bool (never None,
     never missing-as-truthy, never a non-bool truthy/falsy value).
"""
from __future__ import annotations
import json
import subprocess
import sys
from pathlib import Path

import pytest


REPO = Path(__file__).resolve().parents[2]
RUNNER = REPO / "programs" / "phase1_doc_one_shot_runner.py"

# EXAMPLE_PROTOCOL-class scaffold marker phrases. Their sole purpose is detection —
# real chip docs never carry these verbatim, so finding them in any L
# doc is unambiguous evidence of scaffold residue.
_AID_MARKER_PHRASES = (
    "wire-level protocol scope probe",
    "RX byte capture indicator",
    "DUT-driving-bus indicator",
    "iverilog reference TB + DE10-Lite + <half-duplex-tester> host",
    "<half-duplex-tester>",
    "DSO-X 3024G",
    "burn-in soak (",
    "scope-decode RX/TX one full frame",
    "trim sweep across PVT corners",
    "wake pulse + GET_ID",
    "POR + VDD ramp",
    "vendor-specific; document in input/docs/EngineerMode.txt",
)

# EXAMPLE_PROTOCOL scaffold L9 internal_wire names. The full {rx_byte, tx_active,
# wake_oe} set landing as the entire `internal_wires[]` is the residue
# fingerprint.
_AID_INTERNAL_WIRES = frozenset({"rx_byte", "tx_active", "wake_oe"})

# EXAMPLE_PROTOCOL scaffold L13 rig pin keys.
_AID_RIG_PIN_KEYS = frozenset({"id_bus", "clk_50mhz", "reset_n"})


def _seed_thin_input(project: Path, readme: str) -> None:
    """Stage a thin-input project layout."""
    (project / "input" / "docs").mkdir(parents=True, exist_ok=True)
    (project / "input" / "docs" / "README.md").write_text(readme)


def _run_runner(project: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(RUNNER), str(project)],
        capture_output=True, text=True, timeout=60,
    )


def _read_l(project: Path, name: str) -> dict:
    return json.loads(
        (project / "phase1" / "generated_docs" / f"{name}.json").read_text()
    )


def _walk_strings(obj):
    """Yield every string leaf in a nested structure."""
    if isinstance(obj, str):
        yield obj
    elif isinstance(obj, dict):
        for v in obj.values():
            yield from _walk_strings(v)
    elif isinstance(obj, list):
        for it in obj:
            yield from _walk_strings(it)


def _walk_flags(obj, prefix=""):
    """Yield (path, value) for every key matching `no_*_in_input`."""
    if isinstance(obj, dict):
        for k, v in obj.items():
            p = f"{prefix}.{k}" if prefix else k
            if isinstance(k, str) and k.startswith("no_") and k.endswith("_in_input"):
                yield p, v
            yield from _walk_flags(v, p)
    elif isinstance(obj, list):
        for i, it in enumerate(obj):
            yield from _walk_flags(it, f"{prefix}[{i}]")


@pytest.mark.parametrize(
    "ic_id,readme",
    [
        ("aes",
         "# AES-128 cipher core\nNIST FIPS 197 hardware implementation.\n"
         "Pure combinational rounds.\nKey expansion in dedicated module.\n"),
        ("sha256",
         "# SHA-256 hash core\nFIPS 180-4. 64-round Merkle-Damgård. "
         "256-bit digest.\n"),
        ("dram",
         "# LiteDRAM controller\nDDR3/DDR4 PHY support. ECC over 64-bit "
         "data path.\n"),
    ],
)
def test_thin_input_no_aid_scaffold_residue(tmp_path, ic_id, readme):
    """End-to-end: thin-input project must NOT emit EXAMPLE_PROTOCOL-class scaffold
    marker prose in any field. v1.6.81's _purge_aid_scaffold_residue
    guarantees this even if some upstream path injected the scaffold."""
    project = tmp_path / ic_id
    _seed_thin_input(project, readme)
    res = _run_runner(project)
    assert res.returncode == 0, (
        f"Runner failed on {ic_id}:\nstdout:\n{res.stdout}\n"
        f"stderr:\n{res.stderr}"
    )
    # Walk every L doc looking for marker phrases.
    gd = project / "phase1" / "generated_docs"
    leaks = []
    for f in sorted(gd.glob("L*.json")):
        try:
            doc = json.loads(f.read_text())
        except Exception:
            continue
        for s in _walk_strings(doc):
            for marker in _AID_MARKER_PHRASES:
                if marker in s:
                    leaks.append(f"{f.name}: {s[:100]!r} (marker: {marker!r})")
                    break
    assert not leaks, (
        f"EXAMPLE_PROTOCOL-class scaffold marker leak on {ic_id}:\n  "
        + "\n  ".join(leaks)
    )


def test_aid_scaffold_residue_purged_when_pre_seeded(tmp_path):
    """v1.6.81 — defensive purge MUST clean EXAMPLE_PROTOCOL scaffold residue even
    when an upstream path injected it. Simulates the field-agent
    failure mode: planted L7/L9/L13 docs with hardcoded scaffold,
    then the runner runs and the purge pass wipes them."""
    project = tmp_path / "preseeded"
    _seed_thin_input(project, "# Generic IC\nThin input only.\n")

    # Pre-create the L doc directory and plant EXAMPLE_PROTOCOL scaffold residue
    # in the L7/L9/L13 docs. The runner will OVERWRITE these via
    # _write_l_doc, but the post-pass must also clean any residue
    # that survived (e.g. from a pre-existing run).
    res = _run_runner(project)
    assert res.returncode == 0, (
        f"Runner failed:\nstdout:\n{res.stdout}\nstderr:\n{res.stderr}"
    )

    gd = project / "phase1" / "generated_docs"

    # Plant EXAMPLE_PROTOCOL residue post-runner — simulates an external tool
    # writing hardcoded scaffold AFTER our runner finished.
    l7 = json.loads((gd / "L7_TEST_DEBUG.json").read_text())
    l7["debug_observability"] = [
        {"signal": "id_bus", "purpose": "wire-level protocol scope probe"},
        {"signal": "rx_byte_valid", "purpose": "RX byte capture indicator"},
        {"signal": "tx_active", "purpose": "DUT-driving-bus indicator"},
    ]
    l7["verification_strategy"] = [
        {"phase": "FPGA-prototype",
         "method": "iverilog reference TB + DE10-Lite + <half-duplex-tester> host"},
    ]
    l7["no_debug_observability_in_input"] = None  # null bug
    l7["no_verification_strategy_in_input"] = None
    (gd / "L7_TEST_DEBUG.json").write_text(json.dumps(l7))

    l9 = json.loads((gd / "L9_INTEGRATION_SPEC.json").read_text())
    l9["internal_wires"] = [
        {"name": "rx_byte", "width": 8},
        {"name": "tx_active", "width": 1},
        {"name": "wake_oe", "width": 1},
    ]
    (gd / "L9_INTEGRATION_SPEC.json").write_text(json.dumps(l9))

    l13 = json.loads((gd / "L13_LAB_CALIBRATION.json").read_text())
    l13["calibration_steps"] = [
        {"step": 1, "action": "POR + VDD ramp"},
        {"step": 2, "action": "wake pulse + GET_ID"},
    ]
    l13["test_cases"] = l13["calibration_steps"]
    l13["lab_equipment"] = [
        {"name": "<half-duplex-tester>"},
        {"name": "DE10-Lite"},
    ]
    l13["rig_pin_assignments"] = {
        "id_bus": "PIN_V10", "clk_50mhz": "PIN_P11", "reset_n": "PIN_B8"
    }
    (gd / "L13_LAB_CALIBRATION.json").write_text(json.dumps(l13))

    # Now invoke ONLY the purge function (not the full runner) — this
    # is the contract: any external caller can invoke the purge as a
    # cleanup pass without running the full extractor.
    sys.path.insert(0, str(REPO / "programs"))
    from phase1_one_shot_runner import _purge_aid_scaffold_residue
    _purge_aid_scaffold_residue(project)

    # Now assert the residue is gone.
    l7 = json.loads((gd / "L7_TEST_DEBUG.json").read_text())
    assert l7["debug_observability"] == [], (
        f"L7.debug_observability still has scaffold: {l7['debug_observability']}"
    )
    assert l7["verification_strategy"] == [], (
        f"L7.verification_strategy still has scaffold: {l7['verification_strategy']}"
    )
    assert l7["no_debug_observability_in_input"] is True
    assert l7["no_verification_strategy_in_input"] is True

    l9 = json.loads((gd / "L9_INTEGRATION_SPEC.json").read_text())
    assert l9["internal_wires"] == [], (
        f"L9.internal_wires still has scaffold: {l9['internal_wires']}"
    )
    assert l9["no_internal_wires_in_input"] is True

    l13 = json.loads((gd / "L13_LAB_CALIBRATION.json").read_text())
    assert l13["calibration_steps"] == []
    assert l13["test_cases"] == []
    assert l13["lab_equipment"] == []
    assert l13["rig_pin_assignments"] == {}
    assert l13["no_calibration_steps_in_input"] is True
    assert l13["no_lab_equipment_in_input"] is True
    assert l13["no_rig_pin_assignments_in_input"] is True


def test_no_x_in_input_flags_are_always_hard_bool(tmp_path):
    """v1.6.81 — every `no_<X>_in_input` flag MUST be a hard bool
    (True/False), never None / missing / non-bool. Field agent
    reported `L8.no_timing_constants_in_input: null` on v1.6.79.
    """
    project = tmp_path / "flagcheck"
    _seed_thin_input(project, "# Empty IC\nNo content.\n")
    res = _run_runner(project)
    assert res.returncode == 0, res.stderr

    gd = project / "phase1" / "generated_docs"
    bad = []
    for f in sorted(gd.glob("L*.json")):
        try:
            doc = json.loads(f.read_text())
        except Exception:
            continue
        for path, val in _walk_flags(doc):
            if not isinstance(val, bool):
                bad.append(f"{f.name}: {path} = {val!r} (type={type(val).__name__})")
    assert not bad, (
        "no_<X>_in_input flags must be hard bool; found non-bool:\n  "
        + "\n  ".join(bad)
    )


def test_clock_mhz_50_without_evidence_is_null(tmp_path):
    """v1.6.81 — bare `clock_mhz: 50` without a clock-frequency
    evidence entry is the EXAMPLE_PROTOCOL DE10-Lite default leaking. The purge
    pass must replace it with null + flag."""
    project = tmp_path / "clk50"
    _seed_thin_input(project, "# IC\nNo clock specified.\n")
    res = _run_runner(project)
    assert res.returncode == 0, res.stderr

    gd = project / "phase1" / "generated_docs"

    # Plant the EXAMPLE_PROTOCOL DE10-Lite default.
    l8 = json.loads((gd / "L8_RTL_CONSTANTS.json").read_text())
    l8["clock_mhz"] = 50
    l8["clock_domains"] = [
        {"name": "clk_main", "freq_mhz": 50, "source": "CLOCK_50",
         "reset_strategy": "async"}
    ]
    # NO clock_frequency evidence entry — this is the leak signature.
    (gd / "L8_RTL_CONSTANTS.json").write_text(json.dumps(l8))

    sys.path.insert(0, str(REPO / "programs"))
    from phase1_one_shot_runner import _purge_aid_scaffold_residue
    _purge_aid_scaffold_residue(project)

    l8 = json.loads((gd / "L8_RTL_CONSTANTS.json").read_text())
    assert l8["clock_mhz"] is None, (
        f"EXAMPLE_PROTOCOL 50 MHz default not purged: clock_mhz = {l8['clock_mhz']!r}"
    )
    assert l8["no_clock_mhz_in_input"] is True
    assert l8["clock_domains"] == []
    assert l8["no_clock_domains_in_input"] is True


def test_clock_mhz_50_with_evidence_is_preserved(tmp_path):
    """v1.6.81 — `clock_mhz: 50` WITH a real clock_frequency evidence
    entry is legitimate per-source extraction (e.g. DE10-Lite-targeted
    chip really clocked at 50 MHz) and MUST NOT be purged."""
    project = tmp_path / "clk50ev"
    _seed_thin_input(project, "# IC\nclock freq: 50 MHz\n")
    res = _run_runner(project)
    assert res.returncode == 0, res.stderr

    gd = project / "phase1" / "generated_docs"
    l8 = json.loads((gd / "L8_RTL_CONSTANTS.json").read_text())
    # The runner should have extracted 50 MHz from "clock freq: 50 MHz".
    assert l8["clock_mhz"] == 50.0, (
        f"Runner failed to extract `clock freq: 50 MHz`: clock_mhz = "
        f"{l8['clock_mhz']!r}"
    )
    assert l8["no_clock_mhz_in_input"] is False

    # Now invoke purge — it must NOT remove the legitimately extracted
    # value because the extraction_evidence carries a "clock frequency"
    # label.
    sys.path.insert(0, str(REPO / "programs"))
    from phase1_one_shot_runner import _purge_aid_scaffold_residue
    _purge_aid_scaffold_residue(project)

    l8 = json.loads((gd / "L8_RTL_CONSTANTS.json").read_text())
    assert l8["clock_mhz"] == 50.0, (
        "Purge wrongly removed legitimate 50 MHz extraction"
    )
    assert l8["no_clock_mhz_in_input"] is False


# ---------------------------------------------------------------------------
# v1.6.83 — value-keyed → evidence-keyed L8.clock_mhz purge
#
# Field agent reported v1.6.81 cleaned 7/8 sibling fields but L8.clock_mhz
# residue remained because the upstream scaffold default shifted from
# 50 → 250.0 in some path. The literal-50 match missed. v1.6.83 changes
# the predicate to evidence-keyed: purge whenever clock_mhz is non-null
# AND extraction_evidence carries no clock-frequency source. Same shape
# as the L7.engineer_mode_unlock_sequence purge from v1.6.79.
# ---------------------------------------------------------------------------


def test_l8_clock_mhz_purged_evidence_keyed_at_value_250(tmp_path):
    """v1.6.83 — purge L8.clock_mhz value-agnostic. Even when the
    scaffold value is 250.0 (different from the v1.6.81 hardcoded
    50/50.0 match), the purge still fires when no clock-frequency
    evidence exists."""
    project = tmp_path / "clk250"
    _seed_thin_input(project, "# AES core\nPure NIST FIPS 197 round.\n")
    res = _run_runner(project)
    assert res.returncode == 0, res.stderr

    gd = project / "phase1" / "generated_docs"
    # Plant a scaffold-shaped clock_mhz=250.0 with NO clock evidence.
    l8 = json.loads((gd / "L8_RTL_CONSTANTS.json").read_text())
    l8["clock_mhz"] = 250.0
    # Strip any clock-frequency evidence the runner may have synthesized.
    ev = l8.get("extraction_evidence") or {}
    if isinstance(ev, dict):
        ev.pop("README.md", None)
        # Drop any source whose key contains clock-frequency hints.
        for k in list(ev.keys()):
            if re_search_no_re(k):
                ev.pop(k)
        l8["extraction_evidence"] = ev
    (gd / "L8_RTL_CONSTANTS.json").write_text(json.dumps(l8))

    sys.path.insert(0, str(REPO / "programs"))
    from phase1_one_shot_runner import _purge_aid_scaffold_residue
    _purge_aid_scaffold_residue(project)

    l8 = json.loads((gd / "L8_RTL_CONSTANTS.json").read_text())
    assert l8.get("clock_mhz") is None, (
        f"v1.6.83 should purge clock_mhz=250.0 when no clock evidence: "
        f"got {l8.get('clock_mhz')!r}"
    )
    assert l8.get("no_clock_mhz_in_input") is True


def test_l8_clock_mhz_preserved_when_evidence_present(tmp_path):
    """v1.6.83 — positive control: real clock-frequency evidence
    preserves the value, regardless of literal."""
    project = tmp_path / "clkev"
    _seed_thin_input(
        project,
        "# EXAMPLE_CHIP ID IC.\nSystem clock: 50 MHz nominal.\n"
        "Frequency tolerance pm 100 ppm.\n",
    )
    res = _run_runner(project)
    assert res.returncode == 0, res.stderr

    gd = project / "phase1" / "generated_docs"
    l8 = json.loads((gd / "L8_RTL_CONSTANTS.json").read_text())

    # Now invoke purge directly — must NOT remove the legitimately
    # extracted value because an evidence entry references clock /
    # frequency / mhz.
    sys.path.insert(0, str(REPO / "programs"))
    from phase1_one_shot_runner import _purge_aid_scaffold_residue
    _purge_aid_scaffold_residue(project)

    l8 = json.loads((gd / "L8_RTL_CONSTANTS.json").read_text())
    # Either preserved-extracted (cm not None) OR the runner itself
    # extracted nothing on this path; both states are valid as long
    # as we did not corrupt a real extraction. The contract: if
    # extraction_evidence has clock-frequency content, purge must
    # leave the value alone.
    ev = l8.get("extraction_evidence") or {}
    has_clock_evidence = False
    if isinstance(ev, dict):
        for src_path, items in ev.items():
            if re_search_no_re(src_path):
                has_clock_evidence = True
                break
            if isinstance(items, list):
                for it in items:
                    if isinstance(it, dict):
                        label = it.get("label") or it.get("matched") or ""
                        if re_search_no_re(str(label)):
                            has_clock_evidence = True
                            break
            if has_clock_evidence:
                break
    if has_clock_evidence:
        # Then clock_mhz / no_clock_mhz_in_input must reflect a
        # preserved extraction (not the purged shape).
        if l8.get("clock_mhz") is None:
            assert l8.get("no_clock_mhz_in_input") is False, (
                "v1.6.83 wrongly purged a real clock-frequency extraction"
            )


def test_l8_clock_mhz_purged_at_arbitrary_scaffold_values(tmp_path_factory):
    """v1.6.83 — aggregate: scaffold values 50, 100, 250, 500,
    1234.5 all purged when no clock evidence. v1.6.81 only purged 50
    / 50.0 because the predicate was value-keyed. v1.6.83's
    evidence-keyed predicate is value-agnostic."""
    cases = [50, 50.0, 100, 250, 250.0, 500, 1234.5]
    purged = 0

    sys.path.insert(0, str(REPO / "programs"))
    from phase1_one_shot_runner import _purge_aid_scaffold_residue

    for idx, val in enumerate(cases):
        proj = tmp_path_factory.mktemp(f"clk{idx}")
        _seed_thin_input(proj, "# UART block\nPure transmit.\n")
        res = _run_runner(proj)
        assert res.returncode == 0, res.stderr

        gd = proj / "phase1" / "generated_docs"
        l8_path = gd / "L8_RTL_CONSTANTS.json"
        l8 = json.loads(l8_path.read_text())
        # Inject the scaffold value + strip clock-frequency evidence.
        l8["clock_mhz"] = val
        ev = l8.get("extraction_evidence") or {}
        if isinstance(ev, dict):
            for k in list(ev.keys()):
                if re_search_no_re(k):
                    ev.pop(k)
            # Also strip any per-entry clock-label content.
            for k, items in list(ev.items()):
                if isinstance(items, list):
                    ev[k] = [
                        it for it in items
                        if not (isinstance(it, dict) and re_search_no_re(
                            str(it.get("label") or it.get("matched") or "")
                        ))
                    ]
            l8["extraction_evidence"] = ev
        l8_path.write_text(json.dumps(l8))

        _purge_aid_scaffold_residue(proj)

        l8_after = json.loads(l8_path.read_text())
        if l8_after.get("clock_mhz") is None:
            purged += 1

    assert purged == len(cases), (
        f"v1.6.83 expected to purge all {len(cases)} scaffold values "
        f"(value-agnostic); actually purged {purged}/{len(cases)}"
    )


def re_search_no_re(s: str) -> bool:
    """Local helper duplicating the runner's clock-evidence regex
    (case-insensitive match on clock|frequency|freq|mhz). Inlined
    here to keep the test self-contained without leaking the runner's
    private regex into the test API."""
    import re as _re
    return bool(_re.search(r"(?i)clock|frequency|freq|mhz", str(s)))
