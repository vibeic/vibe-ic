"""ORGANIC #605 [MEDIUM/enh] — l_doc_structured_field_count_check relaxed the
protocol-tuned L6 (>=5 FSM states) and L8 (>=10 timing constants) floors to
>=2 / >=3 ONLY for a hardcoded `_DATAPATH_COMPUTE_CLASSES =
{digital_arithmetic_primitive, processor_cpu}`. A sparse no-command-protocol
COMPUTE/ACCELERATOR class outside that set (e.g. crypto_accelerator) inherited
the strict 5/10 protocol-genre floors it has no source to populate and FAILed.

The issue proposed keying the relaxation on `_class_no_cmd_protocol`
(command_protocol_applicable==False AND rtl_gen==None). That predicate is TOO
BROAD: a bus / serial PROTOCOL class is ALSO command_protocol_applicable==False
in the registry yet carries a RICH FSM/timing-waveform spec, so it must keep
the strict floor (v0.1.83 doctrine / test_protocol_stays_strict). The registry
has no field separating sparse-compute from rich-protocol among those classes.

Fix: a dedicated registry SEMANTIC flag `sparse_control_timing` marks only the
genuine datapath/compute/accelerator classes (digital_arithmetic_primitive,
processor_cpu, crypto_accelerator); the L6/L8 floor relaxation keys on it via
`_class_sparse_control_timing()`. Registry-driven (tracks future compute
classes) AND protocol-safe.

POSITIVE: crypto_accelerator (the observed IC) now PASSes a sparse-but-real
L6 (2 states) / L8 (3 constants). Registry-sweep: every `sparse_control_timing`
class is relaxed; the predicate is True for exactly those.

NEGATIVE no-leak (the load-bearing half, §4.05):
  - PROTOCOL classes (bus_interconnect_protocol / serial_peripheral_protocol)
    are no-cmd-protocol but NOT sparse_control_timing -> KEEP the strict 5/10
    (this is the regression the over-broad predicate introduced).
  - command-driven (digital_cmd_driven) and fail-closed (bare_fpga /
    unknown_protocol_class) keep the strict 5/10.
  - the relaxed floor is a REAL floor: an EMPTY L8 still FAILs a relaxed class.

chip-AGNOSTIC: registry semantic flag + numeric floor; no chip/class-name
literal in the relaxation decision.
"""
import json
import sys
from pathlib import Path

PLUGIN = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PLUGIN / "programs"))
import l_doc_structured_field_count_check as C  # noqa: E402

L6_SPARSE = {"fsm_states": [{"name": "IDLE"}, {"name": "RUN"}]}        # 2 states
L8_SPARSE = {"timing_parameters": {"clk_period": 10, "latency": 64,
                                   "throughput": 1}}                    # 3 consts
L8_EMPTY = {"timing_parameters": {}}                                   # 0 consts

_REGISTRY = json.loads(
    (PLUGIN / "programs" / "ic_class_registry.json").read_text())
_SPARSE_CLASSES = [e["name"] for e in _REGISTRY["classes"]
                   if e.get("sparse_control_timing") is True]


def test_crypto_accelerator_now_passes_sparse_l6_l8():
    # the exact observed IC class from #605
    assert C._class_sparse_control_timing("crypto_accelerator") is True
    ok6, _ = C._check_l_doc(6, L6_SPARSE, ic_class="crypto_accelerator")
    ok8, _ = C._check_l_doc(8, L8_SPARSE, ic_class="crypto_accelerator")
    assert ok6 and ok8, "crypto_accelerator is a sparse compute/accelerator class"


def test_registry_sweep_every_sparse_class_relaxed():
    # crypto_accelerator + the two legacy datapath/compute classes.
    assert set(_SPARSE_CLASSES) >= {
        "crypto_accelerator", "digital_arithmetic_primitive", "processor_cpu"}
    for cls in _SPARSE_CLASSES:
        assert C._class_sparse_control_timing(cls) is True, cls
        ok6, r6 = C._check_l_doc(6, L6_SPARSE, ic_class=cls)
        ok8, r8 = C._check_l_doc(8, L8_SPARSE, ic_class=cls)
        assert ok6, f"{cls} L6 still strict (#605): {r6}"
        assert ok8, f"{cls} L8 still strict (#605): {r8}"


def test_protocol_classes_keep_strict_floor():
    # NO-LEAK (the regression the over-broad `_class_no_cmd_protocol` caused):
    # a bus/serial protocol is no-cmd-protocol but has a RICH spec -> strict.
    for cls in ("bus_interconnect_protocol", "serial_peripheral_protocol"):
        assert C._class_no_cmd_protocol(cls) is True, cls  # IS no-cmd-protocol
        assert C._class_sparse_control_timing(cls) is False, cls  # but NOT sparse
        ok6, _ = C._check_l_doc(6, L6_SPARSE, ic_class=cls)
        ok8, _ = C._check_l_doc(8, L8_SPARSE, ic_class=cls)
        assert not ok6, f"{cls} must keep L6 >=5 floor (rich protocol spec)"
        assert not ok8, f"{cls} must keep L8 >=10 floor (rich protocol spec)"


def test_command_driven_and_fail_closed_keep_strict_floor():
    for cls in ("digital_cmd_driven", "bare_fpga", "unknown_protocol_class"):
        assert C._class_sparse_control_timing(cls) is False, cls
        ok6, _ = C._check_l_doc(6, L6_SPARSE, ic_class=cls)
        ok8, _ = C._check_l_doc(8, L8_SPARSE, ic_class=cls)
        assert not ok6 and not ok8, f"{cls} must keep the strict floor"


def test_relaxed_floor_is_real_not_skip():
    # The relaxation is a REAL floor (>=3), not an unconditional skip.
    ok8, _ = C._check_l_doc(8, L8_EMPTY, ic_class="crypto_accelerator")
    assert not ok8, "relaxed L8 floor is still >=3, not a free pass"
