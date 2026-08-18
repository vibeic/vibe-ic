"""v0.2.87 — #450: ic_class inference gains the processor_cpu branch.

The registry has carried processor_cpu since v1.6.522 but NO inference
branch ever returned it: every CPU (SERV/subservient shape) fell to the
digital_arithmetic_primitive catch-all, so class-gated gates, #439
tb_gen routing and oracle shapes used arithmetic semantics on cores
that verify by executing instructions + checking architectural state.

Pins (acceptance):
  * SERV-shaped L1/L2 (bit-serial RISC-V, RV32I, wishbone, register
    file) → processor_cpu;
  * spm-shaped (serial-parallel multiplier) → digital_arithmetic_
    primitive unchanged (no false positive);
  * deny-guard: "processor" prose WITHOUT ISA context never fires;
  * detector is structural (no core/vendor names).
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import ic_class_profile as ICP  # noqa: E402


def _proj(tmp_path, l1_text, l2_text=""):
    g = tmp_path / "phase1" / "generated_docs"
    g.mkdir(parents=True)
    (g / "L1_DATASHEET.json").write_text(json.dumps(
        {"fields": {"description": l1_text}}))
    (g / "L2_FRS.json").write_text(json.dumps(
        {"fields": {"summary": l2_text}}))
    return tmp_path


def test_serv_shaped_docs_detect_processor_cpu(tmp_path):
    p = _proj(tmp_path,
              "A bit-serial RISC-V CPU implementing the RV32I "
              "instruction set; wishbone instruction bus (ibus) and "
              "data bus (dbus); 32-entry register file.",
              "The processor executes one instruction bit-serially; "
              "program counter and architectural state are observable.")
    prof = ICP._detect_ic_class_infer(p)
    assert prof["ic_class"] == "processor_cpu", prof["ic_class"]


def test_multiplier_stays_arithmetic_primitive(tmp_path):
    p = _proj(tmp_path,
              "A serial-parallel multiplier (SPM) datapath primitive: "
              "32-bit multiplicand, serial multiplier input, "
              "pipelined partial-product accumulation.",
              "Pure combinational/sequential arithmetic; no command "
              "interface.")
    prof = ICP._detect_ic_class_infer(p)
    assert prof["ic_class"] == "digital_arithmetic_primitive"


def test_prose_processor_without_isa_does_not_fire(tmp_path):
    p = _proj(tmp_path,
              "A packet processor engine with a memory-mapped buffer "
              "and an ALU for checksum math.",
              "The processor core streams packets.")
    prof = ICP._detect_ic_class_infer(p)
    assert prof["ic_class"] != "processor_cpu"


def test_detector_requires_isa_bearing_feature():
    # direct detector probe: 3 hits but none ISA-bearing → False
    l1 = {"d": "CPU core with wishbone bus and an ALU"}
    assert ICP._looks_like_processor_cpu(l1, None) is False
    l1b = {"d": "RISC-V RV32IMC CPU with register file and wishbone"}
    assert ICP._looks_like_processor_cpu(l1b, None) is True


def test_detector_has_no_core_brand_names():
    src = (Path(ICP.__file__)).read_text()
    i = src.index("_PROCESSOR_CPU_FEATURES")
    window = src[i:i + 2500]
    for brand in ("serv", "subservient", "picorv", "vexriscv", "ibex",
                  "cv32e"):
        assert brand not in window.lower(), brand
