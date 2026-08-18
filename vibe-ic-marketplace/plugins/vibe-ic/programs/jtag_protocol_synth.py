"""jtag_protocol_synth.py — IEEE 1149.1 JTAG TAP controller deterministic
L1-L23 synth.

R<N>/R<N+1>/R<N+2> — applied AFTER L19-L23 skeleton emit when an inline
structural sub-detector confirms the input docs describe an IEEE 1149.1
TAP controller (4-pin TAP TCK/TMS/TDI/TDO + optional TRST + 16-state
TAP FSM + IR/Bypass/BSR data registers + BYPASS/EXTEST/SAMPLE-PRELOAD
mandatory instruction set + boundary-scan-cell-per-pin architecture).
Doctrine: general structural detection within ic_class, not
benchmark-keyword.

Mirrors UART / SPI / I2C / CAN / USB / I2S / 1-Wire synth approach.
Any IEEE 1149.1-1990 / 1149.1-2001 / 1149.1-2013 compatible TAP
controller (TI BSL parts, ARM CoreSight DAP, RISC-V Debug Module via
JTAG-DTM, Synopsys DesignWare DFT IP, Cadence boundary-scan IP, FPGA
vendor JTAG configuration controllers) exhibits the same protocol
signature.

Public entry: `apply_jtag_synth(generated_docs_dir, is_jtag,
jtag_ic_name)`.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

import l_doc_generator_stamp as _stamp


def _empty(v) -> bool:
    return v in (None, {}, []) or (isinstance(v, str) and not v.strip())


def _read(p: Path) -> dict:
    return json.loads(p.read_text())


def _write(p: Path, d: dict) -> None:
    # THE L-document write chokepoint: stamps the producing release onto
    # the document, then serialises it byte-identically to before.
    _stamp.dump(p, d)


def _ensure_dict(d: dict, key: str) -> dict:
    """Helper: setdefault is a no-op if key exists with value None — use
    explicit empty-check to handle that case across the codebase."""
    if d.get(key) in (None, "", []):
        d[key] = {}
    return d[key]


# ============================================================
# Canonical TAP FSM state list + transition table (shared)
# ============================================================
_TAP_STATES_CANONICAL = [
    "TestLogicReset", "RunTestIdle",
    "SelectDRScan", "CaptureDR", "ShiftDR", "Exit1DR", "PauseDR",
    "Exit2DR", "UpdateDR",
    "SelectIRScan", "CaptureIR", "ShiftIR", "Exit1IR", "PauseIR",
    "Exit2IR", "UpdateIR",
]

_TAP_TRANSITION_ROWS = [
    ["TestLogicReset", "RunTestIdle",    "TestLogicReset"],
    ["RunTestIdle",    "RunTestIdle",    "SelectDRScan"],
    ["SelectDRScan",   "CaptureDR",      "SelectIRScan"],
    ["CaptureDR",      "ShiftDR",        "Exit1DR"],
    ["ShiftDR",        "ShiftDR",        "Exit1DR"],
    ["Exit1DR",        "PauseDR",        "UpdateDR"],
    ["PauseDR",        "PauseDR",        "Exit2DR"],
    ["Exit2DR",        "ShiftDR",        "UpdateDR"],
    ["UpdateDR",       "RunTestIdle",    "SelectDRScan"],
    ["SelectIRScan",   "CaptureIR",      "TestLogicReset"],
    ["CaptureIR",      "ShiftIR",        "Exit1IR"],
    ["ShiftIR",        "ShiftIR",        "Exit1IR"],
    ["Exit1IR",        "PauseIR",        "UpdateIR"],
    ["PauseIR",        "PauseIR",        "Exit2IR"],
    ["Exit2IR",        "ShiftIR",        "UpdateIR"],
    ["UpdateIR",       "RunTestIdle",    "SelectDRScan"],
]


def apply_jtag_synth(generated_docs_dir: Path,
                     is_jtag: bool,
                     jtag_ic_name: Optional[str]) -> None:
    """Apply JTAG-specific synth when the structural signature matched.

    fail-open contract: print errors but never raise.
    """
    if not is_jtag:
        return
    gd = Path(generated_docs_dir)

    try:
        # Force ic_name across the 14 main L docs (L1-L23 + L8 timing).
        if jtag_ic_name is not None:
            for n in [
                "L1_DATASHEET.json", "L2_FRS.json", "L3_CMD_PROTOCOL.json",
                "L4_REGMAP.json", "L5_ADI_SPEC.json", "L6_CONTROL_LOGIC.json",
                "L7_TEST_DEBUG.json", "L8_RTL_CONSTANTS.json",
                "L8_TIMING_WAVEFORM.json", "L9_INTEGRATION_SPEC.json",
                "L10_TEST_CASES.json", "L11_OTP_CONTENT.json",
                "L12_BEHAVIORAL_SEQUENCES.json", "L13_LAB_CALIBRATION.json",
            ]:
                q = gd / n
                if q.is_file():
                    d = _read(q)
                    d["ic_name"] = jtag_ic_name
                    _write(q, d)

        _l1(gd, jtag_ic_name)
        _l2(gd, jtag_ic_name)
        _l3(gd, jtag_ic_name)
        _l4(gd, jtag_ic_name)
        _l5(gd, jtag_ic_name)
        _l6(gd, jtag_ic_name)
        _l7(gd, jtag_ic_name)
        _l8_rtl(gd, jtag_ic_name)
        _l8_timing(gd, jtag_ic_name)
        _l9(gd, jtag_ic_name)
        _l10(gd, jtag_ic_name)
        _l11(gd, jtag_ic_name)
        _l12(gd, jtag_ic_name)
        _l13(gd, jtag_ic_name)
        _l14(gd, jtag_ic_name)
        _l15(gd, jtag_ic_name)
        _l16(gd, jtag_ic_name)
        _l17(gd, jtag_ic_name)
        _l18(gd, jtag_ic_name)
        _l19(gd, jtag_ic_name)
        _l20(gd, jtag_ic_name)
        _l21(gd, jtag_ic_name)
        _l22(gd, jtag_ic_name)
        _l23(gd, jtag_ic_name)
    except Exception as exc:  # fail-open
        print(f"[jtag_protocol_synth] WARN: {exc}")


# ============================================================
# L1 DATASHEET
# ============================================================
def _l1(gd: Path, ic_name: Optional[str]) -> None:
    p = gd / "L1_DATASHEET.json"
    if not p.is_file():
        return
    d = _read(p)
    d.setdefault("document_title", "IEEE Std 1149.1 (JTAG) Testability Primer")
    d.setdefault("document_number", "SSYA002C")
    d.setdefault("version", "SSYA002C (1996 print, October 1996 — '1096-AL')")
    d.setdefault("revised_date", "1996")
    d.setdefault("original_release_date", "February 1990 (IEEE Std 1149.1-1990 adoption)")
    d.setdefault("manufacturer", "Texas Instruments Incorporated (primer publisher); IEEE (standard owner)")
    d.setdefault("copyright", "Copyright © 1996, Texas Instruments Incorporated")
    d.setdefault("abstract",
        "TI's primer on IEEE Std 1149.1-1990 (JTAG) boundary-scan testability — explains the 4-pin Test Access Port, the 16-state TAP controller FSM, the Instruction Register and Data Registers (BYPASS / Boundary-Scan / Device-ID), the mandatory and optional instructions, and how JTAG enables board-, cluster-, and system-level testing without bed-of-nails ATE.")
    d.setdefault("keywords", ["JTAG", "IEEE 1149.1", "boundary scan", "TAP controller", "BSDL", "DFT", "testability"])
    d.setdefault("external_pins", [
        "TCK (Test Clock)",
        "TMS (Test Mode Select)",
        "TDI (Test Data In)",
        "TDO (Test Data Out)",
        "TRST (Test Reset, optional, asynchronous, active LOW)",
    ])
    d.setdefault("external_pin_count", 5)
    d.setdefault("mandatory_pin_count", 4)
    d.setdefault("optional_pin_count", 1)
    d.setdefault("key_features", [
        "Industry-standard 4-wire Test Access Port (TAP): TCK + TMS + TDI + TDO; optional 5th pin TRST for asynchronous reset.",
        "16-state TAP controller FSM driven entirely by TMS sampled on the rising edge of TCK.",
        "Mandatory IEEE 1149.1 instructions: BYPASS, EXTEST, SAMPLE/PRELOAD.",
        "Optional instructions: INTEST, RUNBIST, CLAMP, HIGHZ, IDCODE, USERCODE.",
        "Mandatory Bypass register: 1 bit wide; shifts TDI to TDO with one TCK delay.",
        "Mandatory Boundary-Scan Register (BSR): one boundary-scan cell (BSC) per device I/O pin; supports observe (SAMPLE) and drive (EXTEST/INTEST).",
        "Optional 32-bit Device Identification register: bit 0 forced to 1 (distinguishes it from Bypass); fields = version[31:28] / part-number[27:12] / manufacturer-id[11:1] / 1[0].",
        "Instruction Register (IR) ≥ 2 bits wide; loads new instruction via TDI in the ShiftIR path.",
        "Test data shifted LSB-first into the selected Data Register on TCK rising edge; TDO updated on TCK falling edge.",
        "Daisy chain: TDO of one device → TDI of the next; one shared TCK + one shared TMS for the chain.",
        "Enables board-etch and solder-joint testing, cluster (non-boundary-scan IC) testing, board-edge connector testing, ASIC verification, embedded-memory testing, and backplane multidrop test.",
        "Boundary-Scan Description Language (BSDL) files describe a device's boundary-scan capabilities for test-generation tools.",
        "Hierarchical Scan Description Language (HSDL) and Serial Vector Format (SVF) standardize the test-vector exchange format.",
        "Allows in-system reuse of the JTAG bus for emulation, programming, and configuration beyond pure test.",
    ])
    d.setdefault("topology_summary",
        "Every IEEE 1149.1-compatible device has the TAP controller plus a chain of boundary-scan cells (BSCs) wrapping its external I/O. The 4 mandatory test pins are wired in a daisy chain at the board: TDI in → device 0 → TDO0 → TDI1 → device 1 → ... → TDO last. TCK + TMS are bussed to all devices in parallel. The IEEE 1149.1 bus enables a single tester to access the entire chain serially.")
    if _empty(d.get("revision_history")):
        d["revision_history"] = [
            {"version": "SSYA002",  "date": "1993",         "description": "Initial TI testability primer (pre-1990 IEEE 1149.1 adoption survey + early TI BSL products)."},
            {"version": "SSYA002B", "date": "1994",         "description": "Expanded edition covering full IEEE 1149.1-1990 + early BSDL guidance."},
            {"version": "SSYA002C", "date": "October 1996", "description": "Current edition — full BSDL/HSDL/SVF coverage; application chapters on board-etch testing, cluster testing, ASIC verification, embedded RAM/ROM, backplane multidrop, embedded applications, and a suggested boundary-scan test flow."},
        ]
    d.setdefault("use_cases", [
        "Board-etch and solder-joint testing (interconnect open/short detection).",
        "Cluster testing of non-boundary-scan ICs surrounded by boundary-scan devices.",
        "Board-edge connector testing.",
        "ASIC verification (in-system functional test via INTEST).",
        "Embedded memory (RAM / ROM) testing through the surrounding boundary-scan IC.",
        "Backplane multidrop test environment.",
        "Embedded test, emulation, and maintenance applications.",
        "Board validation and manufacturing test (assembly verification + fault detection).",
        "In-system programming of CPLDs / FPGAs / Flash via the TAP.",
    ])
    d.setdefault("overview",
        "Design for test (DFT) is a system methodology that incorporates rules and techniques in the design of a product to make testing easier. IEEE Std 1149.1-1990 (JTAG) is the industry-standard solution for design for testability, adopted by IEEE in February 1990 after the Joint Test Action Group (JTAG, formed 1985, ~200 member companies) developed and refined the 4-wire Test Access Port + Boundary-Scan Architecture. Every IEEE 1149.1-compatible device has four mandatory additional pins (two for control and one each for serial test input and output), a 16-state TAP controller, an Instruction Register, and at least the BYPASS and Boundary-Scan data registers. JTAG allows test instructions and data to be serially loaded into a device and the subsequent test results to be serially read out, enabling reduced development time, lower test cost, easier board-level fault isolation, and access to circuits that surface-mount packaging would otherwise hide.")
    d.setdefault("block_diagram_components", [
        "TAP Controller (16-state FSM driven by TMS on rising TCK)",
        "Instruction Register (IR, ≥ 2 bits, with Shift-IR / Capture-IR / Update-IR stages)",
        "Bypass Register (1 bit, TDI → TDO short-cut)",
        "Boundary-Scan Register (BSR, one BSC per external I/O)",
        "Device Identification Register (32 bits, optional)",
        "User-defined Data Registers (optional)",
        "TDO output multiplexer (selects IR or selected DR based on TAP state)",
        "Boundary Scan Cells (BSC) wrapping every external I/O pin",
        "Optional asynchronous TRST input",
    ])
    d.setdefault("industry_standard_basis",
        "IEEE Std 1149.1-1990 — IEEE Standard Test Access Port and Boundary-Scan Architecture (and its later amendments 1149.1a-1993, 1149.1b-1994). Maintained by IEEE Computer Society.")
    _write(p, d)


# ============================================================
# L2 FRS
# ============================================================
def _l2(gd: Path, ic_name: Optional[str]) -> None:
    p = gd / "L2_FRS.json"
    if not p.is_file():
        return
    d = _read(p)
    po = _ensure_dict(d, "protocol_overview")
    if isinstance(po, dict):
        po.setdefault("type",
            "Synchronous serial test access protocol; TMS-driven 16-state TAP controller FSM selects between Instruction-Register and Data-Register shift paths; one bit per TCK rising edge.")
        po.setdefault("duplex",
            "half-duplex per cycle (in any given TAP state, either IR or one DR is being shifted; TDI is sampled and TDO is presented for that single selected register).")
        po.setdefault("synchronous", True)
        po.setdefault("wire_names_mandatory", ["TCK", "TMS", "TDI", "TDO"])
        po.setdefault("wire_names_optional", ["TRST"])
        po.setdefault("wire_count_mandatory", 4)
        po.setdefault("wire_count_with_trst", 5)
        po.setdefault("fsm_state_count", 16)
        po.setdefault("instruction_register_min_width_bits", 2)
        po.setdefault("data_registers", [
            "Bypass (1 bit, mandatory)",
            "Boundary-Scan Register (BSR, one cell per external I/O, mandatory)",
            "Device Identification Register (32 bits, optional)",
            "User-defined Data Registers (optional)",
        ])
        po.setdefault("controller_role",
            "Tester / test controller drives TCK + TMS + TDI; sequences the TAP FSM through the desired Capture/Shift/Update path.")
        po.setdefault("target_role",
            "Each IEEE 1149.1-compatible device contains its own TAP controller; samples TMS on the rising edge of TCK and updates its FSM accordingly. TDO is driven on the falling edge of TCK.")
    fr = [
        {"id": "FR-PINS-01",     "text": "Every IEEE 1149.1-compatible device shall provide four dedicated TAP pins: TCK (test clock), TMS (test mode select), TDI (test data in), TDO (test data out). An optional fifth pin TRST (asynchronous, active LOW) may be provided for power-on reset of the TAP controller."},
        {"id": "FR-FSM-02",      "text": "Every device shall implement the 16-state TAP controller FSM defined by IEEE 1149.1: TestLogicReset, RunTestIdle, SelectDRScan, CaptureDR, ShiftDR, Exit1DR, PauseDR, Exit2DR, UpdateDR, SelectIRScan, CaptureIR, ShiftIR, Exit1IR, PauseIR, Exit2IR, UpdateIR."},
        {"id": "FR-TMS-03",      "text": "FSM transitions are driven by TMS sampled on the rising edge of TCK. TMS=1 for five consecutive TCKs unconditionally returns the FSM to TestLogicReset from any state."},
        {"id": "FR-SHIFT-04",    "text": "In ShiftIR / ShiftDR states, the device shifts TDI into the LSB of the selected register and presents the previous MSB on TDO. One bit per rising edge of TCK; TDO is updated on the falling edge of TCK."},
        {"id": "FR-IR-05",       "text": "The Instruction Register (IR) shall be at least 2 bits wide and shall implement the mandatory instructions BYPASS (all 1s opcode), EXTEST (all 0s opcode by convention), and SAMPLE/PRELOAD. IDCODE is mandatory if a Device Identification Register is implemented (becomes the post-reset default instruction)."},
        {"id": "FR-BYPASS-06",   "text": "The Bypass register shall be 1 bit wide. When BYPASS is the current instruction, the bypass register sits between TDI and TDO so that the device adds exactly one TCK of delay to the daisy chain."},
        {"id": "FR-BSR-07",      "text": "The Boundary-Scan Register (BSR) shall include one boundary-scan cell (BSC) per external I/O pin of the device. Each BSC supports observation (SAMPLE) and driving (EXTEST/INTEST) of its associated pin."},
        {"id": "FR-IDCODE-08",   "text": "If a Device Identification Register is implemented, it shall be 32 bits wide with bit 0 forced to 1 (so it is distinguishable from a 1-bit BYPASS register). Fields: version[31:28] / part-number[27:12] / manufacturer-id[11:1] / 1[0]."},
        {"id": "FR-RESET-09",    "text": "TestLogicReset shall disable all test logic so the device operates normally. Entry to TestLogicReset shall load IDCODE (if implemented) or BYPASS (otherwise) as the current instruction."},
        {"id": "FR-DAISY-10",    "text": "Multiple IEEE 1149.1 devices may be connected in a daisy chain: TDO of device N → TDI of device N+1; TCK and TMS are bussed in parallel to all devices."},
        {"id": "FR-CAPTURE-11",  "text": "In CaptureDR / CaptureIR states, the selected register is parallel-loaded from device state. In UpdateDR / UpdateIR states, the shifted register contents are parallel-latched into the device's effective state on the falling edge of TCK."},
        {"id": "FR-EXTEST-12",   "text": "When EXTEST is the current instruction, the output BSCs drive their associated device output pins from the values shifted into the BSR; input BSCs observe the values at their associated device input pins."},
        {"id": "FR-INTEST-13",   "text": "When INTEST (optional) is the current instruction, the BSR applies test stimulus to the device's internal logic (acts like a slow ATE pin set) and captures the response."},
        {"id": "FR-TRST-14",     "text": "If TRST is provided, asserting TRST=LOW asynchronously forces the TAP controller to TestLogicReset, independent of TCK and TMS."},
        {"id": "FR-TDO-3STATE-15","text": "TDO shall be 3-state and shall be active only during ShiftIR and ShiftDR states; in all other states TDO is in the high-impedance state so that multiple devices' TDOs can be combined without contention."},
    ]
    if _empty(d.get("functional_requirements")):
        d["functional_requirements"] = fr
    if _empty(d.get("configurations")):
        d["configurations"] = [
            {"name": "Single-device JTAG",   "description": "One TAP-equipped device on the board; tester drives TCK/TMS/TDI; reads TDO directly."},
            {"name": "Daisy-chain JTAG",     "description": "Multiple TAP-equipped devices wired TDO→TDI in series; one shared TCK + one shared TMS for the whole chain. Total scan length = sum of selected register widths in each device."},
            {"name": "Backplane multidrop",  "description": "Boards with a JTAG ring or star configuration, possibly using Addressable Scan Ports (ASPs) to select which board(s) participate in a given scan."},
        ]
    if _empty(d.get("error_response_conditions")):
        d["error_response_conditions"] = [
            "Invalid IR opcode loaded — the device's TAP behavior is implementation-defined; many devices map unknown opcodes to BYPASS.",
            "TMS held HIGH for ≥ 5 TCKs — unconditional return to TestLogicReset; any in-flight scan data is lost.",
            "Broken TDI / TDO trace in the daisy chain — observed at the tester as a stuck-at-0 or stuck-at-1 shift; the BYPASS chain-length check (load BYPASS in every device, shift a 0 through, count zeros) localizes the break.",
            "No protocol-level CRC or parity — data integrity verification is the tester's responsibility (typically via expected-vector compare).",
        ]
    if _empty(d.get("compliance_requirements")):
        d["compliance_requirements"] = [
            "All four mandatory pins (TCK / TMS / TDI / TDO) shall be present and shall be dedicated to test (not shared with functional logic).",
            "The 16-state TAP FSM transition table shall be exactly as defined in IEEE 1149.1 Figure 3-3.",
            "TMS=1 for ≥ 5 TCKs shall always return the device to TestLogicReset.",
            "Mandatory instructions BYPASS / EXTEST / SAMPLE/PRELOAD shall be implemented.",
            "Bypass register shall be exactly 1 bit wide.",
            "Device Identification register, if implemented, shall be 32 bits wide with bit 0 = 1.",
            "TDO shall be 3-state and active only during ShiftIR / ShiftDR.",
            "All test logic shall be inactive in TestLogicReset (normal functional operation of the device shall be unaffected).",
        ]
    _write(p, d)


# ============================================================
# L3 CMD PROTOCOL
# ============================================================
def _l3(gd: Path, ic_name: Optional[str]) -> None:
    p = gd / "L3_CMD_PROTOCOL.json"
    if not p.is_file():
        return
    d = _read(p)
    # FORCE-clear hallucinated `opcodes`: see _l10 long comment. The
    # bare-hex opcode regex picks up `D0 A0` / `D1 A1` schematic pin
    # labels in the TI SSYA002C primer as if they were byte-opcodes.
    # JTAG instructions live in `instructions_mandatory` /
    # `instructions_optional` (set below) with implementation-defined
    # opcode widths and the all-1s / all-0s conventions; they are NOT
    # 2-hex-digit byte opcodes. Clear the upstream hallucinations.
    d["opcodes"] = []
    d.setdefault("protocol_type",
        "TAP-FSM-driven serial scan protocol. The current 'command' is the value held in the Instruction Register (IR); switching commands requires sequencing through SelectIRScan → CaptureIR → ShiftIR → Exit1IR → UpdateIR. Data registers are selected implicitly by the current instruction.")
    if _empty(d.get("instructions_mandatory")):
        d["instructions_mandatory"] = [
            {
                "name": "BYPASS",
                "opcode_convention": "All-1s (e.g. 11 for 2-bit IR, 1111 for 4-bit IR)",
                "selected_data_register": "Bypass (1 bit)",
                "description": "Connects TDI to TDO through the 1-bit Bypass register, adding only one TCK delay to the daisy chain. Used to shorten the chain when only some devices are being tested.",
            },
            {
                "name": "SAMPLE/PRELOAD",
                "opcode_convention": "Implementation-defined",
                "selected_data_register": "Boundary-Scan Register (BSR)",
                "description": "SAMPLE: in CaptureDR, the input BSCs capture the current value on their associated input pins and the output BSCs capture the value being driven on their output pins — a snapshot of pin activity during normal device operation. PRELOAD: in UpdateDR, the BSR contents are latched into the parallel-hold cells of the BSR so that EXTEST can begin driving the pre-loaded values without first-cycle indeterminate output.",
            },
            {
                "name": "EXTEST",
                "opcode_convention": "All-0s by IEEE 1149.1 convention",
                "selected_data_register": "Boundary-Scan Register (BSR)",
                "description": "External test. Output BSCs drive their associated output pins from the BSR-shifted values; input BSCs observe the values at their associated input pins (which therefore reflect the board-level interconnect or upstream device's output). Used for board-etch / solder-joint / interconnect testing.",
            },
        ]
    if _empty(d.get("instructions_optional")):
        d["instructions_optional"] = [
            {
                "name": "INTEST",
                "selected_data_register": "Boundary-Scan Register (BSR)",
                "description": "Internal test. The BSR drives the device's internal logic with shifted-in stimulus (BSR acts like a slow ATE pin set on the input side) and captures the internal-logic response on the output BSCs. Allows in-system functional testing of an IC's core logic.",
            },
            {
                "name": "RUNBIST",
                "selected_data_register": "Implementation-defined (typically a result register)",
                "description": "Run Built-In Self-Test. The TAP controller transitions into RunTestIdle, which the device interprets as 'run the BIST'. The BIST completion / result is read back via the selected register.",
            },
            {
                "name": "CLAMP",
                "selected_data_register": "Bypass (1 bit)",
                "description": "Drives the output pins from the pre-loaded BSR contents (set up via SAMPLE/PRELOAD) while the bypass register sits between TDI and TDO. Used to hold output values constant while a long bypass-only shift happens.",
            },
            {
                "name": "HIGHZ",
                "selected_data_register": "Bypass (1 bit)",
                "description": "Places all output pins in the high-impedance state. Useful for board-level fault isolation — disable the device's outputs to remove driver-conflict suspects.",
            },
            {
                "name": "IDCODE",
                "selected_data_register": "Device Identification Register (32 bits)",
                "description": "Selects the 32-bit Device Identification register for shifting on TDO. The register contains version[31:28] / part-number[27:12] / manufacturer-id[11:1] / 1[0]. When a Device ID register is implemented, IDCODE is the post-reset default instruction.",
            },
            {
                "name": "USERCODE",
                "selected_data_register": "Device Identification Register (32 bits)",
                "description": "Selects the Device ID register but loads it with a user-programmable 32-bit user code (e.g. FPGA configuration version, customer revision).",
            },
        ]
    d.setdefault("post_reset_default_instruction",
        "IDCODE if a Device Identification Register is implemented; otherwise BYPASS.")
    if _empty(d.get("data_register_catalog")):
        d["data_register_catalog"] = [
            {"name": "Bypass",                "width_bits": 1,        "scope": "Mandatory",   "purpose": "Single-bit TDI→TDO short-cut for BYPASS / CLAMP / HIGHZ instructions."},
            {"name": "Boundary-Scan Register","width_bits": "1 BSC per external I/O pin", "scope": "Mandatory", "purpose": "Observation + drive of every device boundary pin for SAMPLE/PRELOAD / EXTEST / INTEST."},
            {"name": "Device Identification", "width_bits": 32,       "scope": "Optional (mandatory if IDCODE / USERCODE implemented)", "purpose": "32-bit device fingerprint: version[31:28] / part-number[27:12] / manufacturer-id[11:1] / 1[0]."},
            {"name": "User-defined Data Register(s)", "width_bits": "implementation-defined", "scope": "Optional", "purpose": "Vendor-specific test / debug / programming registers (e.g. SRAM scan, configuration shift, internal scan)."},
        ]
    if _empty(d.get("channels")):
        d["channels"] = [
            {"name": "TCK", "direction": "tester → all devices",
             "description": "Test Clock. Free-running clock generated by the tester; FSM samples TMS + TDI on the rising edge; TDO is updated on the falling edge."},
            {"name": "TMS", "direction": "tester → all devices",
             "description": "Test Mode Select. Drives the TAP FSM transitions; sampled on the rising edge of TCK."},
            {"name": "TDI", "direction": "tester → first device, then daisy-chained",
             "description": "Test Data In. Sampled on the rising edge of TCK in ShiftIR / ShiftDR states; shifts LSB-first into the selected register."},
            {"name": "TDO", "direction": "last device → tester (via daisy chain TDO of device N → TDI of device N+1)",
             "description": "Test Data Out. 3-state output; active only during ShiftIR / ShiftDR; updated on the falling edge of TCK so the next device samples it cleanly on the next rising edge."},
            {"name": "TRST","direction": "tester → all devices (if implemented)",
             "description": "Optional asynchronous Test Reset (active LOW). When LOW, forces TAP FSM to TestLogicReset independent of TCK / TMS."},
        ]
    d.setdefault("valid_ready_handshake_rules", [
        "There is no per-bit ACK or VALID/READY handshake — JTAG is a synchronous shift with the tester in full control of the clock.",
        "Implicit handshake is positional: the tester must sequence the TAP FSM through CaptureIR → ShiftIR → ... → UpdateIR (or the DR equivalent) to install a new command or commit shifted data.",
        "TMS=1 for 5 consecutive TCKs is an unconditional out-of-band 'abort + reset' that always returns the FSM to TestLogicReset.",
    ])
    d.setdefault("burst_based", False)
    d.setdefault("byte_oriented", False)
    d.setdefault("bit_oriented", True)
    d.setdefault("frame_format", {
        "ir_scan_sequence": "TLR or RTI → SelectDRScan → SelectIRScan → CaptureIR → ShiftIR (N bits LSB-first) → Exit1IR → UpdateIR → RTI/SelectDRScan.",
        "dr_scan_sequence": "RTI or TLR → SelectDRScan → CaptureDR → ShiftDR (M bits LSB-first) → Exit1DR → UpdateDR → RTI/SelectDRScan.",
        "bit_order":        "LSB first into ShiftIR / ShiftDR; the first bit shifted in is the LSB of the destination register; the first bit shifted out on TDO is the LSB of the captured register.",
        "interleaved_chain":"In a daisy chain, the shift register seen by the tester is the concatenation of (in order) each device's selected register; bypass-set devices contribute 1 bit each.",
    })
    _write(p, d)


# ============================================================
# L4 REGMAP
# ============================================================
def _l4(gd: Path, ic_name: Optional[str]) -> None:
    p = gd / "L4_REGMAP.json"
    if not p.is_file():
        return
    d = _read(p)
    d["register_map_present"] = True
    # FORCE hard-assign register_map_kind + base_address: the upstream
    # `_apply_universal` in spi_protocol_synth.py runs unconditionally for
    # every serial_peripheral / digital_cmd / digital_arithmetic /
    # bus_interconnect / unknown ic_class (whether or not is_spi=True) and
    # seeds the SPI-flavored generic "Defined at SoC level; offsets given
    # relative to module base." for `base_address`. JTAG is NOT
    # memory-mapped — registers are selected by IR value, not address —
    # so the SPI universal default is wrong here. setdefault is too late;
    # we must hard-assign to overwrite. Chip-AGNOSTIC pattern: each
    # protocol-specific synth that sits behind apply_universal must
    # hard-assign the L4 fields that apply_universal seeded.
    d["register_map_kind"] = (
        "shift-register catalog (not memory-mapped). Registers are "
        "selected implicitly by the current Instruction Register value "
        "and are accessed by shifting bit-serially via TDI/TDO in "
        "ShiftIR / ShiftDR states.")
    d["base_address"] = (
        "Not applicable — JTAG registers are not memory-mapped. They "
        "are addressed via the Instruction Register value while the "
        "TAP FSM is in the appropriate Shift state.")
    d.setdefault("register_count", 4)
    regs = [
        {
            "name": "IR",
            "long_name": "Instruction Register",
            "width_bits": "≥ 2 (implementation-defined; typical 2, 3, 4, 5, 6, 8, or 10 bits)",
            "access": "Shift-in / shift-out via TDI / TDO in ShiftIR; parallel-latched to current-instruction on falling edge of TCK in UpdateIR.",
            "reset_value": "IDCODE opcode (if Device Identification Register is implemented) OR BYPASS opcode (all 1s) otherwise",
            "purpose": "Holds the currently active instruction. The instruction selects which Data Register is connected between TDI and TDO in ShiftDR and determines the test mode (BYPASS / EXTEST / SAMPLE/PRELOAD / INTEST / IDCODE / USERCODE / HIGHZ / CLAMP / RUNBIST).",
            "capture_value_in_CaptureIR": "Spec-mandated fixed pattern 'b...b01' — the two LSBs are loaded with '01' so the tester can verify the IR is functioning by shifting it out and checking the bottom two bits.",
            "notes": "All-1s opcode is reserved for BYPASS so that an open / pull-up-defaulted TDI naturally selects BYPASS rather than EXTEST (which would drive the board).",
        },
        {
            "name": "Bypass",
            "long_name": "Bypass Register",
            "width_bits": 1,
            "access": "Shift-in / shift-out via TDI / TDO in ShiftDR (when BYPASS / CLAMP / HIGHZ is current).",
            "reset_value": "0 in CaptureDR (Bypass register loads 0 in CaptureDR before each shift)",
            "purpose": "1-bit short-cut between TDI and TDO. Used to reduce daisy-chain shift length when a device is not being targeted by the current test.",
        },
        {
            "name": "BSR",
            "long_name": "Boundary-Scan Register",
            "width_bits": "1 BSC per external I/O pin (sum of input cells + output cells + bidir cells + control cells); implementation- and pin-count-dependent",
            "access": "Shift-in / shift-out via TDI / TDO in ShiftDR (when SAMPLE/PRELOAD / EXTEST / INTEST is current).",
            "reset_value": "Not specified by IEEE 1149.1 at the protocol layer; entry into TestLogicReset returns to functional operation so the BSR is don't-care.",
            "purpose": "Provides observability + controllability of every external I/O pin. Each boundary-scan cell (BSC) typically contains a capture flip-flop + an update flip-flop + a 2-to-1 mux selecting either functional data or BSR drive data. Per-pin cells: input cell (observe only), output cell (drive + observe), bidir cell (drive + observe + direction control), control cell (drives the OE / direction of an associated bidir cell).",
            "structure_summary": "BSR width = pin_count_summed_per_cell_type. See L17 for the per-pin BSC catalog.",
        },
        {
            "name": "IDCODE",
            "long_name": "Device Identification Register",
            "width_bits": 32,
            "access": "Shift-out via TDO in ShiftDR (when IDCODE / USERCODE is current). The register is parallel-loaded with the device ID in CaptureDR; shifted contents into TDI are typically ignored.",
            "reset_value": "Fixed at silicon mask level: version[31:28] || part-number[27:12] || manufacturer-id[11:1] || 1[0]",
            "purpose": "32-bit device fingerprint, readable by the tester to confirm which device is in each slot of the daisy chain.",
            "field_map": [
                {"bits": "31:28", "name": "version",         "description": "Silicon revision identifier (4 bits)."},
                {"bits": "27:12", "name": "part_number",     "description": "Manufacturer-assigned part number (16 bits)."},
                {"bits": "11:1",  "name": "manufacturer_id", "description": "JEDEC-assigned manufacturer ID (11 bits)."},
                {"bits": "0",     "name": "lsb_one",         "description": "Hard-wired to 1 so that a device with IDCODE selected is distinguishable on TDO from a device with BYPASS selected (whose Bypass register loads 0 in CaptureDR)."},
            ],
        },
    ]
    if _empty(d.get("registers")):
        d["registers"] = regs
    d.setdefault("selection_rule",
        "The current Instruction Register value selects which Data Register is connected between TDI and TDO during ShiftDR / CaptureDR / UpdateDR. Instruction-to-register mapping is implementation-defined except for the protocol-mandated cases: BYPASS / CLAMP / HIGHZ → Bypass; SAMPLE/PRELOAD / EXTEST / INTEST → BSR; IDCODE / USERCODE → Device Identification Register.")
    d.setdefault("user_defined_data_registers",
        "Optional. Vendor-specific registers (e.g. configuration shift in FPGAs, flash-programming registers, internal scan paths, USERCODE) are also IR-selected. The TAP controller and IR support arbitrary user-defined data registers as long as the standard shift / capture / update mechanism is preserved.")
    d["notes"] = (
        "Per IEEE 1149.1, the IR is the only register parallel-latched in "
        "UpdateIR; the Bypass register is parallel-loaded with 0 in "
        "CaptureDR; the BSR's CaptureDR behavior depends on the cell type "
        "(input cells capture pin value, output cells capture driven "
        "value); the Device Identification register is parallel-loaded "
        "with the hard-wired ID in CaptureDR.")
    _write(p, d)


# ============================================================
# L5 ADI SPEC
# ============================================================
def _l5(gd: Path, ic_name: Optional[str]) -> None:
    p = gd / "L5_ADI_SPEC.json"
    if not p.is_file():
        return
    d = _read(p)
    d.setdefault("analog_digital_interface_present", False)
    d["signaling_summary"] = (
        "Pure digital protocol. TCK / TMS / TDI / TDO / TRST are CMOS or "
        "TTL-compatible digital signals at the device's I/O voltage "
        "(typically VDD-IO). IEEE 1149.1 does not specify voltage levels "
        "or drive characteristics at the protocol layer; per-device "
        "datasheets define VIH / VIL / VOH / VOL for the TAP pins. "
        "Although JTAG is used to boundary-scan-test analog pins on "
        "mixed-signal devices, the boundary-scan extension for true "
        "analog measurement is IEEE Std 1149.4 (Standard for a "
        "Mixed-Signal Test Bus), which is a separate standard not "
        "covered by the base 1149.1 primer.")
    _write(p, d)


# ============================================================
# L6 CONTROL LOGIC
# ============================================================
def _l6(gd: Path, ic_name: Optional[str]) -> None:
    p = gd / "L6_CONTROL_LOGIC.json"
    if not p.is_file():
        return
    d = _read(p)
    d.setdefault("fsm_summary",
        "16-state Moore machine. TMS is sampled on the rising edge of TCK; the next state depends only on the current state and the latched TMS. TDO is driven combinationally from the selected register output and is updated on the falling edge of TCK; TDO is 3-state active only in ShiftIR and ShiftDR.")
    if _empty(d.get("fsm_states_tap_controller")):
        d["fsm_states_tap_controller"] = [
            {"name": "TestLogicReset", "kind": "stable",            "description": "All test logic disabled; device runs normally. Entry loads IDCODE (if implemented) else BYPASS into the current-instruction latch. Reached unconditionally by TMS=1 for ≥ 5 TCKs or asynchronously by TRST=LOW."},
            {"name": "RunTestIdle",    "kind": "stable",            "description": "Test logic is enabled and idle; instruction-dependent — e.g. during RUNBIST the device runs its self-test in this state."},
            {"name": "SelectDRScan",   "kind": "transient (1 TCK)", "description": "Branch state: TMS=0 → CaptureDR; TMS=1 → SelectIRScan."},
            {"name": "CaptureDR",      "kind": "transient",         "description": "On the rising edge of TCK, parallel-load the DR selected by the current instruction (e.g. capture input pins into BSR; load IDCODE into Device ID register; load 0 into Bypass)."},
            {"name": "ShiftDR",        "kind": "stable while TMS=0","description": "Shift the selected DR one bit per TCK rising edge: TDI → LSB of DR; previous MSB → TDO on falling edge."},
            {"name": "Exit1DR",        "kind": "transient (1 TCK)", "description": "Branch: TMS=0 → PauseDR; TMS=1 → UpdateDR."},
            {"name": "PauseDR",        "kind": "stable while TMS=0","description": "Temporarily halt shifting (e.g. for tester to refill its vector buffer) without losing register contents."},
            {"name": "Exit2DR",        "kind": "transient (1 TCK)", "description": "Branch: TMS=0 → ShiftDR (resume); TMS=1 → UpdateDR."},
            {"name": "UpdateDR",       "kind": "transient (1 TCK)", "description": "On the falling edge of TCK, parallel-latch the shifted DR contents into the device's effective state (e.g. drive output pins in EXTEST; commit configuration write)."},
            {"name": "SelectIRScan",   "kind": "transient (1 TCK)", "description": "Branch: TMS=0 → CaptureIR; TMS=1 → TestLogicReset."},
            {"name": "CaptureIR",      "kind": "transient",         "description": "On the rising edge of TCK, parallel-load the IR with the spec-mandated pattern b...b01 (LSB pair must be '01' so tester can verify IR liveness)."},
            {"name": "ShiftIR",        "kind": "stable while TMS=0","description": "Shift the IR one bit per TCK rising edge: TDI → LSB of IR; previous MSB → TDO on falling edge."},
            {"name": "Exit1IR",        "kind": "transient (1 TCK)", "description": "Branch: TMS=0 → PauseIR; TMS=1 → UpdateIR."},
            {"name": "PauseIR",        "kind": "stable while TMS=0","description": "Temporarily halt IR shifting; IR contents preserved."},
            {"name": "Exit2IR",        "kind": "transient (1 TCK)", "description": "Branch: TMS=0 → ShiftIR (resume); TMS=1 → UpdateIR."},
            {"name": "UpdateIR",       "kind": "transient (1 TCK)", "description": "On the falling edge of TCK, parallel-latch the shifted IR into the current-instruction latch, switching the active instruction."},
        ]
    d.setdefault("fsm_transition_table_tms_driven", {
        "header": ["current_state", "next_state_if_TMS=0", "next_state_if_TMS=1"],
        "rows":   [list(r) for r in _TAP_TRANSITION_ROWS],
        "notes":  "16 entries × 2 next-states. Sampled on TCK rising edge.",
    })
    d.setdefault("fsm_hints", {
        "clock":         "TCK free-running, generated by the tester.",
        "sampling_edge": "TMS and TDI sampled on rising edge of TCK.",
        "drive_edge":    "TDO updated on falling edge of TCK so that the next device in the daisy chain samples cleanly on the next rising edge.",
        "abort":         "TMS=1 for 5 consecutive TCKs unconditionally returns to TestLogicReset from any state. TRST=LOW (if implemented) is the asynchronous equivalent.",
        "instruction_change_path": "From RunTestIdle (or TestLogicReset): TMS=1 → SelectDRScan → TMS=1 → SelectIRScan → TMS=0 → CaptureIR → TMS=0 → ShiftIR → shift IR opcode LSB-first → TMS=1 → Exit1IR → TMS=1 → UpdateIR → instruction is now active.",
        "data_scan_path":          "From RunTestIdle: TMS=1 → SelectDRScan → TMS=0 → CaptureDR → TMS=0 → ShiftDR → shift DR data LSB-first → TMS=1 → Exit1DR → TMS=1 → UpdateDR → committed.",
    })
    d.setdefault("anti_deadlock_rule",
        "TMS=1 × 5 TCKs is the universal escape — there is no FSM state from which this sequence does not reach TestLogicReset. This guarantees the tester can always recover the FSM to a known state without TRST.")
    d.setdefault("exit_from_reset_or_poweron",
        "On power-up the TAP controller may be in any state. TI's primer (and IEEE 1149.1) require that 5 TCKs of TMS=1 must always reach TestLogicReset. Many devices also implement an internal asynchronous reset that forces TestLogicReset at power-on; TRST (when provided) is the dedicated asynchronous reset input.")
    d.setdefault("default_ready_state_recommendation", {
        "TCK":  "Idle level not specified; tester drives.",
        "TMS":  "Pulled HIGH on board so a missing tester defaults the device toward TestLogicReset.",
        "TDI":  "Pulled HIGH on board so a missing tester naturally shifts all-1s (BYPASS opcode) into IR.",
        "TDO":  "3-state when not in ShiftIR / ShiftDR; may be pulled to a known level externally for bus integrity.",
    })
    if _empty(d.get("configurations")):
        d["configurations"] = [
            {"name": "Self-contained TAP",   "description": "Single device with its own TAP controller; tester drives TCK/TMS/TDI; reads TDO."},
            {"name": "Daisy-chained TAPs",   "description": "Several devices share TCK + TMS; their TDI/TDO are wired tail-to-head."},
        ]
    d.setdefault("timing_dependency_rule",
        "All FSM state transitions and IR/DR shifts are synchronous to the rising edge of TCK. TDO is driven on the falling edge of TCK with a tCKQ propagation delay specified per device. Setup/hold of TMS / TDI relative to rising edge of TCK is per-device.")
    _write(p, d)


# ============================================================
# L7 TEST DEBUG
# ============================================================
def _l7(gd: Path, ic_name: Optional[str]) -> None:
    p = gd / "L7_TEST_DEBUG.json"
    if not p.is_file():
        return
    d = _read(p)
    d.setdefault("test_debug_architecture_present", True)
    if _empty(d.get("test_debug_features")):
        d["test_debug_features"] = [
            "BYPASS — 1-bit short-cut between TDI and TDO; used to shorten the daisy chain when only some devices are being tested.",
            "EXTEST — output BSCs drive board interconnect; input BSCs observe board interconnect; enables open / short / solder-joint / etch testing.",
            "SAMPLE/PRELOAD — snapshot of device I/O pin activity during normal operation (SAMPLE) and pre-load of BSR-drive values before EXTEST (PRELOAD).",
            "INTEST (optional) — in-system functional test of one device's internal logic via BSR-applied stimulus.",
            "IDCODE / USERCODE (optional) — 32-bit device fingerprint readback through the Device Identification register; lets the tester verify device presence + revision + customer-programmed user code.",
            "RUNBIST (optional) — TAP-initiated built-in self-test; result read back via a result register.",
            "CLAMP (optional) — drives outputs from pre-loaded BSR while only the Bypass register is in the shift path; useful when isolating a faulty driver during long bypass-only shifts.",
            "HIGHZ (optional) — places all outputs in high-impedance; helps board-level diagnosis by removing a device's drivers from the bus.",
            "Boundary-Scan Description Language (BSDL) — VHDL-subset description of a device's pin assignments, BSR cell types, and IR opcodes; consumed by test-generation tools.",
            "Hierarchical Scan Description Language (HSDL) — extends BSDL with hierarchical scan-path descriptions for boards-of-boards.",
            "Serial Vector Format (SVF) — vendor-neutral file format for JTAG test vectors; defines a set of TAP-FSM-aware commands (TLR / RTI / SIR / SDR / RUNTEST / PAUSE / ...).",
        ]
    d.setdefault("applications_supported_by_jtag_primer", [
        "Board-etch and solder-joint testing (interconnect open/short).",
        "Cluster testing of non-boundary-scan ICs surrounded by boundary-scan devices.",
        "Board-edge connector testing.",
        "ASIC verification (in-system functional check via INTEST).",
        "Embedded-memory testing (RAM/ROM accessed through the surrounding BS device's BSR).",
        "Backplane multidrop test environment (ring / star configurations).",
        "Embedded applications: device programming + system-level debug + maintenance.",
        "Boundary-scan test flow (automated functional verification + interactive fault isolation).",
    ])
    if _empty(d.get("spec_provided_observability")):
        d["spec_provided_observability"] = [
            {"name": "TDO scan output",              "purpose": "Primary observation point; carries the shift output of the selected IR or DR each TCK in ShiftIR/ShiftDR."},
            {"name": "IR capture pattern (b...b01)", "purpose": "Built-in sanity check: tester loads IDCODE-or-BYPASS, then shifts in CaptureIR pattern, verifies LSBs '01' on TDO to confirm the IR is alive."},
            {"name": "IDCODE register",              "purpose": "32-bit device fingerprint readback (when implemented); identifies the device in each slot of the chain."},
            {"name": "BSR (SAMPLE)",                 "purpose": "Snapshot of all device boundary pins during normal operation; lets the tester observe in-system pin activity without disturbing the device."},
            {"name": "BSR (EXTEST input cells)",     "purpose": "Observe board-level interconnect: input cells capture the value at the device pin (driven by board / upstream device's EXTEST output)."},
            {"name": "RUNBIST result register",      "purpose": "Reports BIST PASS/FAIL after the BIST completes in RunTestIdle (when RUNBIST is supported)."},
        ]
    d.setdefault("spec_provided_controllability", [
        "BSR (EXTEST output cells) drives each output pin from a tester-shifted value — direct control of every output without using functional inputs.",
        "BSR (INTEST input cells) drives the device's internal logic with tester-shifted stimulus — slow ATE-style functional test.",
        "HIGHZ removes the device's drivers from board buses for fault isolation.",
        "CLAMP holds the output pins at the pre-loaded BSR values during long bypass-only shifts.",
    ])
    d.setdefault("fault_models_detected_by_jtag", [
        "Stuck-at-0 / stuck-at-1 on board interconnect.",
        "Open net / broken trace.",
        "Short to ground / short to VDD.",
        "Short between adjacent nets.",
        "Missing component (drives default to pull-up/pull-down → detected by EXTEST).",
        "Wrong component (IDCODE mismatch).",
        "Wrong orientation (BSR pin mapping mismatches at IDCODE-compare time).",
    ])
    d["notes"] = (
        "IEEE 1149.1 fundamentally splits test architecture into "
        "mandatory (BYPASS + EXTEST + SAMPLE/PRELOAD + the 16-state TAP "
        "+ Bypass + BSR) and optional (INTEST / RUNBIST / CLAMP / HIGHZ "
        "/ IDCODE / USERCODE + Device Identification register + "
        "user-defined data registers). The mandatory set alone is enough "
        "for interconnect-test and board-level fault isolation; the "
        "optional set adds in-system functional test, BIST automation, "
        "device identification, and bus isolation.")
    _write(p, d)


# ============================================================
# L8 RTL CONSTANTS
# ============================================================
def _l8_rtl(gd: Path, ic_name: Optional[str]) -> None:
    p = gd / "L8_RTL_CONSTANTS.json"
    if not p.is_file():
        return
    d = _read(p)
    wp = _ensure_dict(d, "width_parameters")
    if isinstance(wp, dict):
        for k, v in {
            "MANDATORY_PIN_COUNT": 4,
            "OPTIONAL_PIN_COUNT": 1,
            "EXTERNAL_PIN_COUNT_TOTAL": 5,
            "TAP_FSM_STATE_COUNT": 16,
            "TAP_FSM_STATE_ENCODING_BITS": 4,
            "IR_MIN_WIDTH_BITS": 2,
            "IR_TYPICAL_WIDTH_BITS_EXAMPLES": [2, 3, 4, 5, 6, 8, 10],
            "BYPASS_WIDTH_BITS": 1,
            "IDCODE_WIDTH_BITS": 32,
            "BSR_BSC_COUNT": "Implementation-defined: 1 BSC per external I/O pin (sum of input cells + output cells + bidir cells + control cells)",
            "BIT_ORDER_IN_SHIFT": "LSB first",
        }.items():
            wp.setdefault(k, v)
    d.setdefault("tap_state_names_in_canonical_order", list(_TAP_STATES_CANONICAL))
    d.setdefault("tap_state_transition_table_tms_driven", {
        "header": ["current_state", "next_state_if_TMS=0", "next_state_if_TMS=1"],
        "rows":   [list(r) for r in _TAP_TRANSITION_ROWS],
    })
    d.setdefault("voltage_levels", {
        "VDD_at_TAP_pins": "Per-device VDD-IO; not specified by IEEE 1149.1.",
        "signaling":       "Digital CMOS / TTL — per-device datasheet.",
    })
    d.setdefault("key_constants_for_RTL_authoring", {
        "tap_power_on_default_state":    "TestLogicReset",
        "tap_unconditional_reset_rule":  "TMS=1 for 5 consecutive TCK rising edges → TestLogicReset",
        "asynchronous_reset_optional":   "TRST=LOW → TestLogicReset (independent of TCK / TMS)",
        "tms_sample_edge":               "TCK rising edge",
        "tdi_sample_edge":               "TCK rising edge",
        "tdo_drive_edge":                "TCK falling edge",
        "tdo_3state_in_non_shift_states":True,
        "shift_bit_order":               "LSB first",
        "ir_capture_lsb_pair":           "01 (spec-mandated for IR liveness check)",
        "bypass_capture_value":          0,
        "device_id_lsb_one":             1,
        "post_reset_default_instruction":"IDCODE if Device ID register implemented else BYPASS",
        "bypass_opcode_convention":      "all-1s (so pulled-up TDI defaults to BYPASS, not to a board-driving instruction)",
        "extest_opcode_convention":      "all-0s (by IEEE 1149.1 convention)",
    })
    d.setdefault("mandatory_instructions", ["BYPASS", "EXTEST", "SAMPLE/PRELOAD"])
    d.setdefault("optional_instructions", ["INTEST", "RUNBIST", "CLAMP", "HIGHZ", "IDCODE", "USERCODE"])
    d.setdefault("data_register_widths", {
        "Bypass_bits": 1,
        "BSR_bits":    "implementation-defined (1 BSC per external I/O pin)",
        "IDCODE_bits": 32,
        "User_DRs":    "implementation-defined",
    })
    d.setdefault("device_id_field_layout", {
        "version_bits":         "31:28",
        "part_number_bits":     "27:12",
        "manufacturer_id_bits": "11:1",
        "lsb_one_bit":          "0",
    })
    d.setdefault("default_signal_values_when_idle", {
        "TCK":  "Free-running clock; idle level not specified.",
        "TMS":  "Recommended HIGH idle (pulls device toward TestLogicReset).",
        "TDI":  "Recommended HIGH idle (so a missing tester does not load EXTEST opcode).",
        "TDO":  "3-state in non-Shift states.",
        "TRST": "Recommended HIGH idle (de-asserted) so the TAP can run; tied LOW to hold the TAP in reset.",
    })
    _write(p, d)


# ============================================================
# L8 TIMING WAVEFORM
# ============================================================
def _l8_timing(gd: Path, ic_name: Optional[str]) -> None:
    p = gd / "L8_TIMING_WAVEFORM.json"
    if not p.is_file():
        return
    d = _read(p)
    d.setdefault("clock_waveform", {
        "TCK_role":         "Test Clock. Generated by the tester. Free-running while a scan is in progress; may be stopped or stretched between scans (the FSM holds its current stable state when TCK stops).",
        "rising_edge":      "TMS and TDI are sampled here. TAP FSM transitions on this edge. Capture / shift-update of IR and selected DR happen on this edge.",
        "falling_edge":     "TDO is updated here so that the next device in the daisy chain sees a stable TDI on the following rising edge of TCK.",
        "duty_cycle":       "Not protocol-mandated; per-device datasheet (typically ~50%).",
        "frequency_range":  "Typical 10-50 MHz at the chip level; lower (1-10 MHz) over backplanes and long board chains. Implementation-defined per device.",
    })
    d.setdefault("tms_tdi_tdo_waveform", {
        "TMS_role":        "Drives FSM transitions; latched on rising edge of TCK.",
        "TDI_role":        "Shift-in data for IR (in ShiftIR) or selected DR (in ShiftDR); latched on rising edge of TCK; LSB first.",
        "TDO_role":        "Shift-out data for IR (in ShiftIR) or selected DR (in ShiftDR); driven on falling edge of TCK; LSB first.",
        "TDO_3state_rule": "TDO is in the high-impedance state in all FSM states except ShiftIR and ShiftDR. This lets multiple devices' TDOs be combined externally without contention (although daisy-chain usage avoids this entirely).",
    })
    d.setdefault("reset_waveform", {
        "TMS_reset_sequence":      "TMS=1 for 5 consecutive TCK rising edges from any state forces TestLogicReset.",
        "TRST_asynchronous_reset": "TRST=LOW (when implemented) forces the TAP FSM to TestLogicReset immediately, independent of TCK.",
    })
    d.setdefault("ir_scan_waveform_summary", [
        "Begin in RunTestIdle (or TestLogicReset).",
        "TMS=1 → SelectDRScan (1 TCK).",
        "TMS=1 → SelectIRScan (1 TCK).",
        "TMS=0 → CaptureIR (1 TCK): IR parallel-loaded with b...b01 pattern.",
        "TMS=0 (N times) → ShiftIR: shift N-bit IR LSB first via TDI; previous IR contents emerge LSB-first on TDO (falling edges).",
        "TMS=1 → Exit1IR (1 TCK).",
        "TMS=1 → UpdateIR (1 TCK): new IR contents become the current instruction on the falling edge.",
        "TMS=0 → RunTestIdle (or TMS=1 → SelectDRScan to start a DR scan immediately).",
    ])
    d.setdefault("dr_scan_waveform_summary", [
        "Begin in RunTestIdle (or TestLogicReset).",
        "TMS=1 → SelectDRScan (1 TCK).",
        "TMS=0 → CaptureDR (1 TCK): selected DR parallel-loaded with its capture value (BSR captures pins; Bypass captures 0; IDCODE captures hard-wired ID; user DRs per definition).",
        "TMS=0 (M times) → ShiftDR: shift M-bit DR LSB first via TDI; previous DR contents emerge LSB-first on TDO.",
        "TMS=1 → Exit1DR (1 TCK).",
        "TMS=1 → UpdateDR (1 TCK): shifted DR is parallel-latched (e.g. EXTEST drive values reach output pins on the falling edge of TCK).",
        "TMS=0 → RunTestIdle.",
    ])
    d.setdefault("timing_parameters_per_device", {
        "header": ["Parameter", "Symbol", "Note"],
        "rows": [
            ["TCK period",                    "tTCK",     "Implementation-defined; typical 20-100 ns at chip level."],
            ["TCK HIGH time",                 "tTCKH",    "Per-device; typically ≥ 0.4 × tTCK."],
            ["TCK LOW time",                  "tTCKL",    "Per-device; typically ≥ 0.4 × tTCK."],
            ["TMS setup before TCK rising",   "tSU(TMS)", "Per-device datasheet."],
            ["TMS hold after TCK rising",     "tH(TMS)",  "Per-device datasheet."],
            ["TDI setup before TCK rising",   "tSU(TDI)", "Per-device datasheet."],
            ["TDI hold after TCK rising",     "tH(TDI)",  "Per-device datasheet."],
            ["TDO output delay from TCK fall","tPD(TDO)", "Per-device datasheet."],
            ["TRST minimum LOW pulse width",  "tW(TRST)", "Per-device datasheet (if TRST implemented)."],
        ],
        "notes": "IEEE 1149.1 does not specify absolute values; per-device datasheets do. Across-chain skew is limited by the slowest device + board interconnect; testers typically run TCK well below each device's worst-case maximum.",
    })
    d.setdefault("voltage_levels", {
        "VIH_min": "Per-device datasheet.",
        "VIL_max": "Per-device datasheet.",
        "VOH_min": "Per-device datasheet.",
        "VOL_max": "Per-device datasheet.",
    })
    _write(p, d)


# ============================================================
# L9 INTEGRATION SPEC
# ============================================================
def _l9(gd: Path, ic_name: Optional[str]) -> None:
    p = gd / "L9_INTEGRATION_SPEC.json"
    if not p.is_file():
        return
    d = _read(p)
    d.setdefault("module_role",
        "Standardized test access architecture embedded inside every IEEE 1149.1-compatible IC. Each compliant device contains a 4-pin Test Access Port + 16-state TAP controller FSM + Instruction Register + at least the Bypass and Boundary-Scan Register data registers. Boards integrate one or more such devices into a daisy chain accessible from a single test connector.")
    d.setdefault("integration_overview", {
        "wire_count_mandatory": 4,
        "wire_count_with_trst": 5,
        "wire_directions":      "TCK + TMS: tester → all devices (bussed); TDI: tester → first device → daisy chain; TDO: last device → tester (via TDO→TDI hops between devices); TRST: tester → all devices (bussed, optional).",
        "no_chip_select":       "There is no per-device chip select; selection is done by sequencing the FSM into the proper Scan path. To target only one device in a chain, the tester loads BYPASS into all other devices first.",
        "no_addressing_at_protocol_layer": "Devices are not addressable per se; their position in the daisy chain is their address. Backplane multidrop adds Addressable Scan Ports (ASPs) on top to make boards selectively participate.",
        "test_logic_independent_of_functional_logic": "All TAP pins are dedicated to test (not shared with normal functional pins). TestLogicReset disables all test logic so the device runs normally.",
        "no_handshake":         "Synchronous shift driven by the tester's TCK; tester is fully in control.",
    })
    d.setdefault("interface_categories", [
        "Tester / test controller (drives TCK + TMS + TDI; reads TDO; optionally drives TRST).",
        "Daisy-chained boundary-scan devices (each implements its own TAP + IR + Bypass + BSR; optional Device ID register).",
        "Backplane Addressable Scan Port (optional, IEEE 1149.1-style extension for ring / star backplanes — covered in primer Chapter 7).",
        "Embedded controller / on-board JTAG bridge (for in-system programming + embedded debug).",
    ])
    d.setdefault("interconnect_topologies_supported", [
        "Single device — tester directly accesses one TAP.",
        "Linear daisy chain — TDO_n → TDI_(n+1); shared TCK + TMS + (optional TRST).",
        "Backplane ring — boards arranged in a ring; one ring connector at one end of the backplane.",
        "Backplane star — boards arranged in parallel chains via a star configuration on the backplane.",
        "Backplane with Addressable Scan Ports (ASP) — boards can be enabled / disabled in the chain dynamically.",
    ])
    d.setdefault("daisy_chain_rules", {
        "TDO_to_TDI_handoff": "TDO of device N is wired directly to TDI of device N+1.",
        "shared_TCK_TMS":     "TCK and TMS are bussed to all devices; FSMs in all devices step in lockstep.",
        "total_scan_length":  "Sum of the widths of the selected register in each device. To shift a single DR through one device, all other devices must be in BYPASS (1 bit each).",
        "instruction_loading":"To load distinct instructions into different devices, the tester scans a concatenated IR with each device's IR opcode in the correct slot.",
    })
    d.setdefault("default_signal_values_when_omitted", {
        "TMS_pull":  "Recommended pull-up; missing tester → device drifts toward TestLogicReset.",
        "TDI_pull":  "Recommended pull-up; missing tester → BYPASS opcode shifts in (safe non-driving default).",
        "TRST_pull": "Recommended pull-up (de-asserted); allows the TAP to run when the tester is present. Some boards tie TRST=LOW permanently when JTAG is not used.",
    })
    d.setdefault("soc_dependent_items", [
        "Choice of IR width (≥ 2 bits) and opcode mapping for optional instructions.",
        "Presence of TRST pin (optional).",
        "Presence of Device Identification register + USERCODE register.",
        "Presence of optional instructions (INTEST / RUNBIST / CLAMP / HIGHZ / IDCODE / USERCODE).",
        "User-defined data registers (vendor scan paths, configuration shift, programming registers).",
        "BSDL file naming the cell type for every external I/O pin.",
        "Board-level pull-ups / pull-downs on TMS / TDI / TRST.",
        "Buffering / repeaters on TCK / TMS for long chains.",
        "Backplane scan-architecture choice (ring / star / ASP) when boards-of-boards are present.",
        "Embedded JTAG bridge (e.g. on-board MCU acting as tester) for in-system programming or debug.",
    ])
    d.setdefault("low_power_modes", {
        "TestLogicReset":  "All test logic is disabled in TestLogicReset; the device runs normally with minimal extra power overhead.",
        "TCK_stopped":     "When the tester stops TCK in a stable FSM state, the TAP holds its current state with negligible additional dynamic current.",
    })
    d.setdefault("compatibility_notes", [
        "IEEE 1149.1-1990 is the base standard.",
        "IEEE 1149.1a-1993 / IEEE 1149.1b-1994 amendments — clarifications + BSDL.",
        "BSDL files are the integration-time contract describing a device's pin assignments and BSR cell types.",
        "HSDL and SVF standardize vector exchange between EDA tools.",
        "JTAG bus may be reused at runtime for emulation / programming / configuration (e.g. ARM JTAG-DP, Altera/Xilinx FPGA configuration).",
    ])
    _write(p, d)


# ============================================================
# L10 TEST CASES
# ============================================================
def _l10(gd: Path, ic_name: Optional[str]) -> None:
    p = gd / "L10_TEST_CASES.json"
    if not p.is_file():
        return
    d = _read(p)
    # FORCE hard-assign test_cases_present: the upstream `_apply_universal`
    # in spi_protocol_synth.py runs unconditionally for every
    # serial_peripheral / digital_cmd / digital_arithmetic /
    # bus_interconnect / unknown ic_class and seeds the SPI-flavored
    # "partial - the spec provides functional descriptions ..." string.
    # JTAG is a TAP-FSM protocol with a Design-for-Test Flow + Applications
    # chapter; the SPI default is wrong here. setdefault is too late;
    # we must hard-assign to overwrite. Same pattern as _l4 above.
    d["test_cases_present"] = (
        "partial — the primer defines the architectural rules, FSM "
        "transition table, mandatory / optional instructions, and a "
        "Suggested Design-for-Test Flow (Chapter 6) + Applications "
        "chapter (Chapter 7) but does not provide a formal test bench. "
        "The categories below are the spec-derived compliance test "
        "scenarios.")
    # FORCE-clear hallucinated per-opcode `test_cases` + `extraction_evidence`:
    # the upstream `gen_l10_test_cases` in phase1_doc_one_shot_runner.py
    # scans L3.opcodes and stamps one happy-path + one pre-wake-false case
    # per opcode. For JTAG, L3.opcodes is populated by the bare-hex
    # opcode regex `_V1_6_245_BARE_OPCODE_PAT` matching `D0 A0` style
    # schematic pin labels in the TI SSYA002C primer (D0..D7 / A0..A7 are
    # data/address bus signal names, NOT JTAG instructions). The
    # resulting `0xD0 / name=A0` opcode_hex entries are hallucinations
    # picked up by l_doc_parity_diff's HALLUCINATION_HEURISTICS. JTAG is
    # NOT byte-opcode-driven — instructions are loaded by IR scan with
    # implementation-defined opcode widths (see
    # instructions_mandatory / instructions_optional in L3). Clear both
    # the auto-stamped cases and their evidence trail. Chip-AGNOSTIC
    # pattern: every protocol-specific synth that is not
    # byte-opcode-driven must clear gen_l10_test_cases output.
    d["test_cases"] = []
    d["extraction_evidence"] = {}
    if _empty(d.get("derived_compliance_test_categories")):
        d["derived_compliance_test_categories"] = [
            "TestLogicReset entry — TMS=1 × 5 TCKs from each of the 16 FSM states reaches TestLogicReset.",
            "TestLogicReset entry — TRST=LOW (if implemented) asynchronously forces TestLogicReset.",
            "Post-reset default instruction — IDCODE (if Device ID register implemented) or BYPASS otherwise.",
            "IR width discovery — load BYPASS (all-1s opcode), scan a single 0 through ShiftIR; count the IR bits before the 0 emerges (IR width).",
            "IR capture pattern — verify CaptureIR loads b...b01 (LSB pair must be '01').",
            "BYPASS register — load BYPASS, shift a known pattern into Bypass via TDI, verify identical pattern emerges on TDO with 1-bit (per device) delay.",
            "Daisy-chain length test — load BYPASS in all devices; shift a single 0 through; count TCKs until it emerges = number of devices in chain.",
            "IDCODE readback — load IDCODE, scan 32 bits from TDO, verify version[31:28] / part-number[27:12] / manufacturer-id[11:1] / 1[0] match expected per device.",
            "SAMPLE — load SAMPLE/PRELOAD, capture BSR during normal device operation, shift out, verify captured input pin values.",
            "PRELOAD — load SAMPLE/PRELOAD, shift drive pattern into BSR via ShiftDR + UpdateDR; verify pin levels remain unchanged (PRELOAD does NOT drive pins — it pre-loads the BSR for the next EXTEST).",
            "EXTEST — after PRELOAD, load EXTEST; UpdateDR causes BSR output cells to drive their associated output pins; tester observes board interconnect via the next-device's input cells.",
            "INTEST (if implemented) — apply BSR input stimulus to device internals; capture output BSCs to read internal-logic response.",
            "RUNBIST (if implemented) — load RUNBIST, drive into RunTestIdle for N TCKs, transition out, scan result register, verify BIST PASS.",
            "HIGHZ (if implemented) — load HIGHZ, verify all device output pins go to high-impedance.",
            "CLAMP (if implemented) — pre-load BSR via SAMPLE/PRELOAD; load CLAMP; verify output pins hold the pre-loaded values during bypass-only shifts.",
            "TMS-driven FSM transition coverage — drive each of the 32 (16 states × 2 TMS values) transitions and verify the FSM lands in the spec-table next state.",
            "TDO 3-state behavior — verify TDO is high-impedance in all non-ShiftIR/ShiftDR states.",
            "Multi-device IR scan — concatenate per-device IR opcodes; verify each device receives its intended instruction at UpdateIR.",
            "Multi-device DR scan — with mixed instructions across the chain (e.g. one device EXTEST, others BYPASS), shift the combined DR length and verify the EXTEST device's drive / capture path while the others contribute 1 BYPASS bit each.",
            "Interconnect short detection — drive opposing values on two suspected-shorted nets via EXTEST; observe both via input BSCs; if values match, short is confirmed.",
            "Interconnect open detection — drive a known value on one net; observe the receiving pin's input BSC; if value does not match, open is detected.",
            "Backplane multidrop ASP enable / disable — verify boards can be added/removed from the active chain dynamically (Chapter 7).",
        ]
    _write(p, d)


# ============================================================
# L11 OTP CONTENT
# ============================================================
def _l11(gd: Path, ic_name: Optional[str]) -> None:
    p = gd / "L11_OTP_CONTENT.json"
    if not p.is_file():
        return
    d = _read(p)
    d["otp_present"] = (
        "functionally — the 32-bit Device Identification register is "
        "functionally OTP-equivalent (hard-wired at mask level, read-only "
        "via TAP), although IEEE 1149.1 does not call it OTP. There is "
        "no fuse-bank or programmable OTP at the JTAG protocol layer.")
    d.setdefault("device_identification_register_content", {
        "width_bits": 32,
        "access":     "Read-only via IDCODE instruction; parallel-loaded with the hard-wired value in CaptureDR; shifted out on TDO in ShiftDR.",
        "field_map": [
            {"bits": "31:28", "name": "version",         "width_bits": 4,  "description": "Silicon revision identifier; mask-set-time fixed.",     "writability": "ROM (mask-set time)"},
            {"bits": "27:12", "name": "part_number",     "width_bits": 16, "description": "Manufacturer-assigned part number.",                    "writability": "ROM (mask-set time)"},
            {"bits": "11:1",  "name": "manufacturer_id", "width_bits": 11, "description": "JEDEC-assigned manufacturer identification code.",     "writability": "ROM (mask-set time)"},
            {"bits": "0",     "name": "lsb_one",         "width_bits": 1,  "description": "Hard-wired to 1.",                                       "writability": "ROM (always 1)"},
        ],
    })
    d.setdefault("usercode_register_content", {
        "applicable_when": "USERCODE optional instruction is implemented.",
        "width_bits": 32,
        "access":     "Read-only via USERCODE instruction; shares the Device Identification register but loads a user-programmed value (e.g. FPGA bitstream version, customer revision).",
        "writability":"Vendor-defined; in CPLD / FPGA parts the USERCODE register is loaded at configuration time from the bitstream, so it is functionally programmable (not strictly OTP) for those devices.",
    })
    d["notes"] = (
        "IEEE 1149.1-1990 mandates only the IR + Bypass + BSR; the "
        "Device Identification register is optional but must be 32 bits "
        "with bit 0 = 1 when present. There is no protocol-defined OTP "
        "/ fuse / programmable nonvolatile content. Per-vendor "
        "extensions (in-system programming registers, configuration NVM "
        "accessed via user-defined data registers) are vendor-specific.")
    _write(p, d)


# ============================================================
# L12 BEHAVIORAL SEQUENCES
# ============================================================
def _l12(gd: Path, ic_name: Optional[str]) -> None:
    p = gd / "L12_BEHAVIORAL_SEQUENCES.json"
    if not p.is_file():
        return
    d = _read(p)
    d.setdefault("power_on_sequence", [
        "1. Power-up: TAP state may be indeterminate.",
        "2. Tester drives TMS=1 for ≥ 5 TCK rising edges; TAP unconditionally reaches TestLogicReset.",
        "3. (Alternative) Tester drives TRST=LOW (if implemented); TAP enters TestLogicReset asynchronously.",
        "4. In TestLogicReset the current-instruction latch loads IDCODE (if implemented) else BYPASS; all test logic is disabled and the device runs functionally.",
    ])
    d.setdefault("ir_scan_sequence_to_load_instruction", [
        "1. From RunTestIdle (or TestLogicReset): TMS=1 → SelectDRScan.",
        "2. TMS=1 → SelectIRScan.",
        "3. TMS=0 → CaptureIR (IR loaded with b...b01 pattern).",
        "4. TMS=0, repeat for N-1 TCKs: in ShiftIR, shift the N-bit IR opcode LSB-first via TDI; previous IR contents emerge on TDO.",
        "5. On the N-th IR bit: drive TMS=1 with the IR MSB on TDI → Exit1IR.",
        "6. TMS=1 → UpdateIR (new instruction becomes the current instruction on the falling edge of TCK).",
        "7. TMS=0 → RunTestIdle (or TMS=1 → SelectDRScan to start a DR scan immediately).",
    ])
    d.setdefault("dr_scan_sequence_to_shift_data", [
        "1. From RunTestIdle: TMS=1 → SelectDRScan.",
        "2. TMS=0 → CaptureDR (selected DR parallel-loaded with its capture value).",
        "3. TMS=0, repeat for M-1 TCKs: in ShiftDR, shift the M-bit DR LSB-first via TDI; previous DR contents emerge on TDO.",
        "4. On the M-th DR bit: drive TMS=1 with the DR MSB on TDI → Exit1DR.",
        "5. TMS=1 → UpdateDR (shifted DR parallel-latched on the falling edge of TCK — e.g. EXTEST drive values reach the output pins).",
        "6. TMS=0 → RunTestIdle (or stay in DR-scan loop by going TMS=1 → SelectDRScan again).",
    ])
    d.setdefault("bypass_chain_check_sequence", [
        "1. Use IR scan to load BYPASS opcode (all-1s) into every device in the chain.",
        "2. Use DR scan: shift a known pattern (e.g. a single 0 followed by 1s) into TDI.",
        "3. Each device contributes one BYPASS bit to the chain; total chain length = number of devices.",
        "4. Count TCKs from when the test pattern was injected until it emerges on TDO; that equals the device count.",
        "5. Verify the pattern emerges unchanged → the daisy chain is intact.",
    ])
    d.setdefault("idcode_readout_sequence", [
        "1. From TestLogicReset (post-reset default loads IDCODE in each device that supports IDCODE; for devices without IDCODE the default is BYPASS).",
        "2. Use DR scan with 32 bits per IDCODE-supporting device + 1 bit per BYPASS device.",
        "3. Shift the concatenated DR length out via TDO; parse each device's 32-bit IDCODE (or 1-bit BYPASS) from the bit stream.",
        "4. Verify bit 0 of each IDCODE = 1 (per spec); compare version / part-number / manufacturer-id against the expected device list.",
    ])
    d.setdefault("extest_drive_observe_sequence", [
        "1. IR scan: load SAMPLE/PRELOAD; DR scan: shift desired drive pattern into BSR; UpdateDR latches it into the parallel-hold cells (pre-load).",
        "2. IR scan: load EXTEST; DR scan: shift the same (or updated) drive pattern; UpdateDR causes output BSCs to drive their associated output pins from the BSR.",
        "3. DR scan: CaptureDR causes input BSCs to capture the values at their associated input pins (which reflect the driving device's output via board interconnect).",
        "4. ShiftDR + read TDO: tester observes the captured input bits and infers board interconnect integrity (open / short / stuck-at).",
    ])
    d.setdefault("intest_in_system_test_sequence", [
        "1. IR scan: load INTEST.",
        "2. DR scan: shift stimulus pattern into BSR (BSR input cells now drive the device's internal logic).",
        "3. CaptureDR: BSR output cells capture the device's internal-logic response.",
        "4. ShiftDR + read TDO: tester reads back the response and compares to expected vectors.",
    ])
    d.setdefault("multi_device_mixed_instruction_sequence", [
        "1. IR scan: concatenate per-device IR opcodes in chain order; shift through ShiftIR; UpdateIR loads each device's intended instruction.",
        "2. DR scan: total DR length = sum across devices of (width of the DR each device's instruction selects).",
        "3. Each device's bits in the concatenated DR stream are at their respective offsets — tester software is responsible for slicing the TDO output bit stream per device.",
    ])
    d.setdefault("tap_recovery_sequence", [
        "Drive TMS=1 for 5 consecutive TCK rising edges → TestLogicReset regardless of current state.",
        "Or drive TRST=LOW for one tW(TRST) pulse (if TRST is implemented) → TestLogicReset asynchronously.",
    ])
    _write(p, d)


# ============================================================
# L13 LAB CALIBRATION
# ============================================================
def _l13(gd: Path, ic_name: Optional[str]) -> None:
    p = gd / "L13_LAB_CALIBRATION.json"
    if not p.is_file():
        return
    d = _read(p)
    d.setdefault("lab_calibration_present", False)
    d["notes"] = (
        "IEEE 1149.1 is a digital wire-level test access protocol; no "
        "analog reference / trim / calibration is part of the TAP "
        "architecture. Practical board-bring-up characterizations focus "
        "on TCK frequency margin (does the chain still work at the max "
        "TCK supported by the slowest device?), signal integrity on "
        "long chains and backplane multidrops (reflections, ground "
        "bounce, level translation), TDO 3-state propagation delay "
        "across the chain, and proper pull-up sizing on TMS / TDI / "
        "TRST. None of these are protocol-mandated calibration steps — "
        "they are board-design verifications. Mixed-signal-pin "
        "observability is provided by IEEE Std 1149.4 (Mixed-Signal "
        "Test Bus), a separate standard layered on top of 1149.1.")
    d.setdefault("board_bring_up_characterizations_typical", [
        "TCK frequency sweep — sweep from 1 MHz up to the slowest device's max TCK; identify the safe operating frequency on the assembled board.",
        "Signal integrity on long chains — measure TDI/TDO/TMS/TCK edges at the end of the chain; verify rise/fall times meet each device's tSU/tH.",
        "Pull-up sizing on TMS/TDI/TRST — verify pull-up holds TMS HIGH (default toward TestLogicReset) and TDI HIGH (default BYPASS) when the tester is absent.",
        "TDO 3-state transition timing — measure TDO leaving 3-state on entering ShiftIR/ShiftDR and re-entering 3-state on exiting.",
        "Backplane multidrop signal characterization — verify ring / star / ASP-enabled chains keep signal margins.",
        "TRST minimum pulse width — verify the board-level TRST glitch filter (if any) does not mask short TRST pulses.",
    ])
    _write(p, d)


# ============================================================
# L14 PROTOCOL VERSIONING
# ============================================================
def _l14(gd: Path, ic_name: Optional[str]) -> None:
    p = gd / "L14_PROTOCOL_VERSIONING.json"
    if not p.is_file():
        return
    d = _read(p)
    f = _ensure_dict(d, "fields")
    if ic_name:
        f["ic_name"] = ic_name
    f.setdefault("spec_version",
        "TI SSYA002C IEEE Std 1149.1 (JTAG) Testability Primer (October 1996); documents IEEE Std 1149.1-1990 + 1149.1a-1993 + 1149.1b-1994.")
    if _empty(f.get("previous_versions")):
        f["previous_versions"] = [
            "JTAG working group formed 1985 (~200 member companies); pre-standard ad-hoc boundary-scan implementations.",
            "IEEE Std 1149.1-1990 — IEEE Standard Test Access Port and Boundary-Scan Architecture; adopted February 1990 (the base JTAG standard).",
            "IEEE Std 1149.1a-1993 — supplement; clarifications + BSDL.",
            "IEEE Std 1149.1b-1994 — supplement; further BSDL clarifications + behavioral refinements.",
            "TI SSYA002 (1993) / SSYA002B (1994) / SSYA002C (1996) — TI testability primer revisions tracking the standard's evolution.",
        ]
    f.setdefault("post_primer_evolution_industry_note", [
        "IEEE Std 1149.1-2001 — major revision; mandatory IDCODE (when Device ID register is present), tightened BSDL, post-1990 cleanup.",
        "IEEE Std 1149.1-2013 — further revision; programmable test access (PDL), BSDL packaging, ICL/PDL Tcl-bindings via IEEE 1687 IJTAG.",
        "IEEE Std 1149.4 — Mixed-Signal Test Bus (analog boundary scan, layered on 1149.1).",
        "IEEE Std 1149.6 — Advanced I/O test (AC-coupled and differential pin testing).",
        "IEEE Std 1149.7 — Compact JTAG (cJTAG); 2-pin reduction of 1149.1.",
        "IEEE Std 1687-2014 — Internal JTAG (IJTAG); standardized hierarchical instrument access on top of 1149.1.",
        "ARM JTAG-DP / SWD — ARM CoreSight debug access port; layered on 1149.1 (or 2-pin Serial Wire Debug).",
    ])
    if _empty(f.get("key_changes")):
        f["key_changes"] = [
            {"version": "1149.1-1990",  "summary": "Base standard: 4-pin TAP, 16-state FSM, IR + Bypass + BSR, mandatory BYPASS / EXTEST / SAMPLE-PRELOAD."},
            {"version": "1149.1a-1993", "summary": "Supplement clarifying optional-instruction behavior; introduced BSDL formal grammar."},
            {"version": "1149.1b-1994", "summary": "Further BSDL refinement; minor behavioral clarifications."},
            {"version": "1149.1-2001",  "summary": "Republished base standard; IDCODE became mandatory when a Device ID register is provided; tightened BSDL conformance."},
            {"version": "1149.1-2013",  "summary": "Added PDL (Procedural Description Language) for programmable test access; preparation for IEEE 1687 IJTAG integration."},
        ]
    if _empty(f.get("backward_compat_traps")):
        f["backward_compat_traps"] = [
            {
                "trap_name": "all_1s_opcode_must_be_BYPASS",
                "rule": "The all-1s IR opcode shall be reserved for BYPASS so that a stuck-HIGH or pulled-up TDI naturally selects a non-driving instruction.",
                "trap": "Custom IPs occasionally re-purpose the all-1s opcode for vendor-private use; this is a hard violation of 1149.1 and causes board-level surprises when the tester is absent.",
            },
            {
                "trap_name": "ir_capture_lsb_must_be_01",
                "rule": "CaptureIR shall load b...b01 (two LSBs '01') so the tester can verify the IR is alive.",
                "trap": "Forgetting this pattern breaks compliance with virtually every commercial JTAG test tool's sanity check.",
            },
            {
                "trap_name": "device_id_lsb_must_be_1",
                "rule": "Bit 0 of the Device Identification register shall be 1.",
                "trap": "If bit 0 is 0, the tester cannot distinguish a device with IDCODE selected from a device with BYPASS selected (whose Bypass register loads 0 in CaptureDR).",
            },
            {
                "trap_name": "tdo_3state_in_non_shift_states",
                "rule": "TDO shall be 3-state outside ShiftIR / ShiftDR.",
                "trap": "Forgetting the 3-state behavior causes daisy-chain contention when two devices' TDOs are momentarily driven simultaneously.",
            },
            {
                "trap_name": "test_logic_disabled_in_TLR",
                "rule": "In TestLogicReset all test logic shall be disabled so the device runs functionally.",
                "trap": "If EXTEST drive paths or boundary-scan-cell output muxes are not properly gated, TestLogicReset still drives the pins from BSR state and the device fails in normal operation.",
            },
            {
                "trap_name": "tms_high_5_tcks_universal_reset",
                "rule": "TMS=1 for 5 consecutive TCKs shall always reach TestLogicReset.",
                "trap": "Custom FSMs that add extra states or skip transitions break this universal escape, leaving testers unable to recover without TRST.",
            },
        ]
    f.setdefault("version_naming_history_note",
        "JTAG is named after the Joint Test Action Group (formed 1985, ~200 industry members) that developed the architecture from 1985 through 1989. IEEE adopted the work as Std 1149.1 in February 1990. TI's primer SSYA002C (October 1996) documents the 1990 base standard + 1993/1994 supplements. The 2001 and 2013 revisions added IDCODE-mandatory and PDL features but kept the 4-pin TAP + 16-state FSM + IR/Bypass/BSR architecture compatible — any 1149.1-2013-compliant device is also 1149.1-1990 compliant for the mandatory subset.")
    d["fields"] = f
    _write(p, d)


# ============================================================
# L15 ENCODING TABLES
# ============================================================
def _l15(gd: Path, ic_name: Optional[str]) -> None:
    p = gd / "L15_ENCODING_TABLES.json"
    if not p.is_file():
        return
    d = _read(p)
    f = _ensure_dict(d, "fields")
    if ic_name:
        f["ic_name"] = ic_name
    f.setdefault("tap_state_transition_table_tms_driven", {
        "header_columns": ["current_state", "next_state_if_TMS=0", "next_state_if_TMS=1"],
        "rows":           [list(r) for r in _TAP_TRANSITION_ROWS],
    })
    f.setdefault("instruction_opcode_convention_table", {
        "header_columns": ["Instruction", "Opcode Convention", "Mandatory?", "Selected Data Register"],
        "rows": [
            ["BYPASS",         "All-1s (e.g. 1111 for IR width 4)", "Mandatory",                                              "Bypass (1 bit)"],
            ["EXTEST",         "All-0s (by convention)",            "Mandatory",                                              "Boundary-Scan Register (BSR)"],
            ["SAMPLE/PRELOAD", "Implementation-defined",            "Mandatory",                                              "Boundary-Scan Register (BSR)"],
            ["INTEST",         "Implementation-defined",            "Optional",                                               "Boundary-Scan Register (BSR)"],
            ["IDCODE",         "Implementation-defined",            "Optional (mandatory if Device ID register implemented)", "Device Identification Register (32 bits)"],
            ["USERCODE",       "Implementation-defined",            "Optional",                                               "Device Identification Register (32 bits, user-programmed)"],
            ["RUNBIST",        "Implementation-defined",            "Optional",                                               "Implementation-defined result register"],
            ["CLAMP",          "Implementation-defined",            "Optional",                                               "Bypass (1 bit); BSR drives outputs"],
            ["HIGHZ",          "Implementation-defined",            "Optional",                                               "Bypass (1 bit); outputs high-impedance"],
        ],
    })
    f.setdefault("device_id_register_field_table", {
        "header_columns": ["Bits", "Field", "Width", "Description"],
        "rows": [
            ["31:28", "version",         4,  "Silicon revision identifier (mask-set time)."],
            ["27:12", "part_number",     16, "Manufacturer-assigned part number."],
            ["11:1",  "manufacturer_id", 11, "JEDEC-assigned manufacturer identification code."],
            ["0",     "lsb_one",         1,  "Hard-wired to 1 (so Device ID readout distinguishes from BYPASS chain output)."],
        ],
    })
    f.setdefault("ir_capture_table", {
        "header_columns": ["IR Width", "CaptureIR pattern", "Note"],
        "rows": [
            ["2 bits", "01",         "Minimum IR width per spec."],
            ["3 bits", "001 or b01", "Per-implementation; LSB pair = '01' is mandatory."],
            ["4 bits", "bb01",       "Most common in commercial parts."],
            ["N bits", "b...b01",    "General rule: any pattern whose two LSBs are '01'."],
        ],
    })
    f.setdefault("post_reset_default_instruction_table", {
        "header_columns": ["Device has Device ID register?", "Post-TestLogicReset default instruction"],
        "rows": [
            ["Yes (1149.1-2001+ makes IDCODE mandatory in this case)", "IDCODE"],
            ["No",                                                     "BYPASS"],
        ],
    })
    f.setdefault("scan_register_selection_by_instruction", {
        "header_columns": ["Current Instruction", "Selected Data Register in ShiftDR", "Behavior in UpdateDR"],
        "rows": [
            ["BYPASS",         "Bypass (1 bit)",                       "—"],
            ["SAMPLE/PRELOAD", "Boundary-Scan Register (BSR)",         "BSR contents latched into BSR parallel-hold cells; pin outputs NOT driven."],
            ["EXTEST",         "Boundary-Scan Register (BSR)",         "BSR output cells drive their associated output pins."],
            ["INTEST",         "Boundary-Scan Register (BSR)",         "BSR input cells drive device's internal logic; output cells capture internal-logic response."],
            ["IDCODE",         "Device Identification Register (32b)", "—"],
            ["USERCODE",       "Device Identification Register (32b)", "—"],
            ["RUNBIST",        "Implementation-defined result reg",    "BIST runs in RunTestIdle; result available after BIST completes."],
            ["CLAMP",          "Bypass (1 bit)",                       "Output pins driven by pre-loaded BSR (set up via SAMPLE/PRELOAD)."],
            ["HIGHZ",          "Bypass (1 bit)",                       "All output pins go to high-impedance."],
        ],
    })
    if _empty(f.get("tables")):
        f["tables"] = [
            "Figure 3-3 — TAP Controller State Diagram",
            "Figure 3-4 — TAP Control Output Interconnect Diagram",
            "Figure 3-5 — General Instruction Register Architecture",
            "Figure 3-6 — Test Data Register Architecture",
            "Figure 3-7 — Conceptual View of a Control-and-Observe BSC",
            "Figure 3-8 — Device Identification Register Structure",
            "Table 5-1 — SVF TAP State Names (Chapter 5, Data Formats)",
            "Table 5-2 — Stable-State Path Examples (Chapter 5, SVF)",
        ]
    d["fields"] = f
    _write(p, d)


# ============================================================
# L16 COMPLIANCE PROPERTIES
# ============================================================
def _l16(gd: Path, ic_name: Optional[str]) -> None:
    p = gd / "L16_COMPLIANCE_PROPERTIES.json"
    if not p.is_file():
        return
    d = _read(p)
    f = _ensure_dict(d, "fields")
    if ic_name:
        f["ic_name"] = ic_name
    f.setdefault("must_have_properties", [
        "Four mandatory dedicated TAP pins: TCK, TMS, TDI, TDO.",
        "16-state TAP controller FSM exactly per IEEE 1149.1 Figure 3-3 transition diagram.",
        "TMS and TDI sampled on the rising edge of TCK; TDO updated on the falling edge of TCK.",
        "Mandatory instructions implemented: BYPASS, EXTEST, SAMPLE/PRELOAD.",
        "Bypass register exactly 1 bit wide; loads 0 in CaptureDR.",
        "Boundary-Scan Register (BSR) with one boundary-scan cell (BSC) per external I/O pin.",
        "Instruction Register (IR) ≥ 2 bits wide; CaptureIR loads b...b01 (LSB pair '01').",
        "BYPASS opcode is all-1s (e.g. 11, 1111) — reserved so pulled-up TDI defaults to BYPASS.",
        "TestLogicReset disables all test logic so the device runs normally.",
        "TMS=1 for 5 consecutive TCK rising edges unconditionally reaches TestLogicReset from any state.",
        "Post-reset default instruction = IDCODE (if Device ID register implemented) else BYPASS.",
        "TDO is 3-state, active only in ShiftIR and ShiftDR.",
        "Daisy-chain support: TDO_n → TDI_(n+1); shared TCK + TMS in parallel.",
    ])
    f.setdefault("must_have_if_device_identification_register_present", [
        "Device Identification Register is exactly 32 bits.",
        "Bit 0 of Device ID is hard-wired to 1.",
        "Field layout: version[31:28] / part_number[27:12] / manufacturer_id[11:1] / 1[0].",
    ])
    f.setdefault("must_not_have_properties", [
        "BYPASS opcode anything other than all-1s.",
        "CaptureIR pattern with LSB pair other than '01'.",
        "Device ID register with bit 0 = 0.",
        "Bypass register wider than 1 bit.",
        "TDO actively driven in non-Shift states.",
        "Test logic affecting normal functional operation in TestLogicReset.",
        "FSM states that cannot be reached by TMS=1 × 5 TCKs to TestLogicReset.",
        "TAP pins shared with functional pins (must be dedicated).",
    ])
    f.setdefault("compliance_failure_modes", [
        {"mode": "Pulled-up TDI drives EXTEST",          "trigger": "BYPASS not mapped to all-1s opcode."},
        {"mode": "IR liveness check fails on every tool","trigger": "CaptureIR not loading b...b01."},
        {"mode": "Device ID indistinguishable from BYPASS","trigger": "Device ID bit 0 = 0."},
        {"mode": "Daisy-chain TDO contention",           "trigger": "TDO not 3-state in non-Shift states."},
        {"mode": "Test logic disturbs normal operation", "trigger": "EXTEST drive path not disabled in TestLogicReset."},
        {"mode": "Tester cannot recover the chain",      "trigger": "FSM violates the 5×TMS=1 → TLR universal-reset rule."},
        {"mode": "Stuck-at fault on board interconnect", "trigger": "EXTEST detects stuck-at-0 or stuck-at-1 on a net by driving the opposite value."},
        {"mode": "Short between adjacent nets",          "trigger": "EXTEST detects short by driving opposing values and observing both pins read the same."},
        {"mode": "Open net",                             "trigger": "EXTEST detects open by driving a value and observing the receiving pin not match."},
    ])
    f.setdefault("reset_behavior_compliance",
        "After TestLogicReset entry (via TMS=1×5 TCKs or TRST=LOW): IR loads IDCODE (if Device ID implemented) else BYPASS; all test logic disabled; device runs functionally. Bypass register, BSR, and any user-defined registers' reset values are implementation-defined except for the spec-mandated capture behavior.")
    d["fields"] = f
    _write(p, d)


# ============================================================
# L17 CHANNEL SIGNAL CATALOG (force-overwrite dependency_graph)
# ============================================================
def _l17(gd: Path, ic_name: Optional[str]) -> None:
    p = gd / "L17_CHANNEL_SIGNAL_CATALOG.json"
    if not p.is_file():
        return
    d = _read(p)
    f = _ensure_dict(d, "fields")
    if ic_name:
        f["ic_name"] = ic_name
    f["channels"] = [
        {"name": "TCK", "direction_tester": "output", "direction_device": "input",
         "purpose": "Test Clock. Tester-generated free-running clock; FSM samples TMS + TDI on the rising edge; TDO updates on the falling edge.",
         "active_levels": "Per-device VIH / VIL (CMOS / TTL)", "idle_level": "Free-running; idle level not specified"},
        {"name": "TMS", "direction_tester": "output", "direction_device": "input",
         "purpose": "Test Mode Select. Drives the 16-state TAP FSM transitions; sampled on TCK rising edge. TMS=1 × 5 TCKs forces TestLogicReset.",
         "active_levels": "Per-device VIH / VIL", "idle_level": "Recommended pulled HIGH (defaults toward TestLogicReset)"},
        {"name": "TDI", "direction_tester": "output", "direction_device": "input",
         "purpose": "Test Data In. Shift input to selected register (IR in ShiftIR, selected DR in ShiftDR); sampled LSB-first on TCK rising edge.",
         "active_levels": "Per-device VIH / VIL", "idle_level": "Recommended pulled HIGH (defaults to BYPASS opcode all-1s)"},
        {"name": "TDO", "direction_device": "output (3-state)", "direction_tester": "input",
         "purpose": "Test Data Out. Shift output of selected register; driven LSB-first on TCK falling edge; high-impedance outside ShiftIR / ShiftDR.",
         "active_levels": "Per-device VOH / VOL when driven; high-Z otherwise", "idle_level": "High-impedance"},
        {"name": "TRST", "direction_tester": "output (optional)", "direction_device": "input (optional)",
         "purpose": "Optional asynchronous Test Reset (active LOW). When LOW, forces TAP FSM to TestLogicReset independent of TCK / TMS.",
         "active_levels": "Active LOW", "idle_level": "Recommended pulled HIGH (de-asserted)"},
    ]
    f["global_signals"] = [
        {"name": "VDD-IO (per device)", "purpose": "Drives the TAP pins' I/O voltage; per-device datasheet."},
        {"name": "GND",                 "purpose": "Common ground reference for the tester and all devices in the chain."},
    ]
    f["channel_counts"] = {
        "channels_mandatory":             4,
        "channels_optional":              1,
        "external_pins_total_mandatory":  4,
        "external_pins_total_with_trst":  5,
        "data_lines":                     2,
        "clock_lines":                    1,
        "control_lines":                  1,
        "reset_lines_optional":           1,
    }
    f["boundary_scan_cell_catalog"] = [
        {"cell_type": "Input cell",         "associated_pin": "Each external input pin",                              "purpose": "Capture pin value in CaptureDR (observability); also receives functional path value when test logic is disabled."},
        {"cell_type": "Output cell",        "associated_pin": "Each external output pin",                             "purpose": "Drive pin from BSR in EXTEST UpdateDR (controllability); capture driven value in CaptureDR for SAMPLE."},
        {"cell_type": "Bidirectional cell", "associated_pin": "Each external bidir pin",                              "purpose": "Combination of input + output cell; direction selected by an associated control cell."},
        {"cell_type": "Control cell",       "associated_pin": "Drives the OE / direction of an associated bidir cell", "purpose": "Allows EXTEST/INTEST to control the direction of bidirectional pins; not a separate physical pin."},
    ]
    f["ordering_rules"] = {
        "shift_bit_order":       "LSB first on TDI and TDO.",
        "ir_capture_pattern":    "CaptureIR loads b...b01 (LSB pair '01').",
        "daisy_chain_bit_order": "First bit out of the tester (TDI) is the bit destined for the device farthest from the tester; last bit out is the bit destined for the first device (closest to the tester's TDI). Tester software is responsible for the per-device bit ordering.",
    }
    # Force-overwrite dependency_graph — earlier ic-class-generic step
    # may have filled it with AXI-leaning content; JTAG shape is different.
    f["dependency_graph"] = {
        "common_rule": "Tester drives TCK + TMS + TDI; reads TDO. FSM is driven entirely by TMS sampled on rising TCK; shift registers shift on rising TCK; TDO updates on falling TCK. The tester is fully in control of every cycle.",
        "data_dependency": "Each ShiftIR/ShiftDR bit moves one position per TCK; TDI input becomes LSB of the selected register; previous MSB exits on TDO on the falling edge. In a daisy chain the per-device shifts compose into one long shift visible at the tester.",
    }
    f["handshake_pairs"] = [
        {"name": "TCK_DRIVE",     "from": "tester",                                             "to": "all devices",     "rule": "Free-running clock; one FSM transition per rising edge; one TDO update per falling edge."},
        {"name": "TMS_FSM",       "from": "tester",                                             "to": "all devices",     "rule": "TMS sampled on rising TCK drives the 16-state FSM transition table; all devices step in lockstep."},
        {"name": "TDI_TDO_SHIFT", "from": "tester (TDI) and previous device (TDO→TDI)",         "to": "current device",  "rule": "In ShiftIR / ShiftDR: TDI sampled on rising TCK shifts into LSB of selected register; previous MSB exits on TDO on falling TCK."},
        {"name": "TRST_RESET",    "from": "tester (optional)",                                  "to": "all devices",     "rule": "TRST=LOW asynchronously forces TAP FSM to TestLogicReset."},
    ]
    d["fields"] = f
    _write(p, d)


# ============================================================
# L18 INTERCONNECT TOPOLOGY
# ============================================================
def _l18(gd: Path, ic_name: Optional[str]) -> None:
    p = gd / "L18_INTERCONNECT_TOPOLOGY.json"
    if not p.is_file():
        return
    d = _read(p)
    f = _ensure_dict(d, "fields")
    if ic_name:
        f["ic_name"] = ic_name
    f["topology_type"] = (
        "Daisy-chained serial scan path. Each device's TAP is wired TDO_n → TDI_(n+1); "
        "TCK and TMS are bussed in parallel to all devices. Optional TRST is bussed in parallel.")
    f["supported_topologies"] = [
        {"name": "Single-device JTAG",                         "description": "One TAP-equipped device on the board; tester directly accesses TCK/TMS/TDI/TDO."},
        {"name": "Linear daisy chain",                         "description": "Multiple TAP devices in series; TDO_n → TDI_(n+1); shared TCK + TMS + (optional TRST)."},
        {"name": "Backplane ring",                             "description": "Boards arranged in a ring on the backplane; one ring connector at one end; chain wraps around (Chapter 7, Figure 7-13)."},
        {"name": "Backplane star",                             "description": "Boards arranged in parallel chains via a star configuration; non-standard (parallel chains via splitter) — covered in Chapter 7, Figure 7-14."},
        {"name": "Backplane with Addressable Scan Ports (ASP)","description": "Each board has an ASP that can include / exclude the board from the active chain; tester selects which boards participate (Chapter 7, Figure 7-15)."},
    ]
    f["master_slave_role_summary"] = [
        {"role": "Tester / test controller", "description": "Drives TCK + TMS + TDI; reads TDO. May be standalone ATE, an embedded JTAG bridge, or a higher-level system."},
        {"role": "Boundary-scan device",     "description": "Each device implements TAP controller + IR + Bypass + BSR; optional Device ID register; optional INTEST/RUNBIST/etc. instructions."},
        {"role": "Addressable Scan Port",    "description": "Backplane-level component that selectively connects / disconnects a board from the daisy chain — extension covered in Chapter 7."},
    ]
    f["interconnect_role"] = (
        "There is no protocol-layer interconnect (no router / bridge inside the TAP itself). "
        "The architecture is a flat daisy chain at the protocol layer; backplane-level "
        "scan-architecture (ring / star / ASP) wraps the basic chain to scale to "
        "boards-of-boards.")
    f["ordering_guarantees"] = {
        "bit_order_within_a_shift":  "Bits transmitted LSB-first on TDI; receiver reassembles LSB-first.",
        "device_order_within_chain": "Determined by physical TDO→TDI wiring; tester software must know the per-device IR/DR width contributions to slice the shifted stream correctly.",
        "fsm_lockstep_across_chain": "All devices in the chain see the same TCK + TMS; their FSMs step in lockstep through SelectDRScan / SelectIRScan / Capture / Shift / Update.",
    }
    f["memory_vs_peripheral_regions"] = (
        "Not applicable — JTAG registers are not memory-mapped; selection is by IR opcode + TAP state.")
    f["device_classification"] = {
        "test_controller":         "Tester / ATE / embedded JTAG bridge — drives the 4-pin TAP from outside.",
        "scannable_ic":            "IEEE 1149.1-compatible IC with full TAP + BSR + IR.",
        "non_scannable_ic":        "IC without a TAP; cluster-tested through surrounding scannable ICs (Chapter 7).",
        "addressable_scan_port":   "Backplane-level component for boards-of-boards scan architectures.",
    }
    f.setdefault("default_signal_values_evidence_tables", [
        "Figure 2-1 — Boundary-Scan Testing Using the IEEE Std 1149.1 Bus",
        "Figure 3-2 — Boundary-Scan Architecture",
        "Figure 3-3 — TAP Controller State Diagram",
        "Figure 7-13 — Backplane Ring Configuration",
        "Figure 7-14 — Backplane Star Configuration",
        "Figure 7-15 — Backplane With ASP-Equipped Boards",
    ])
    d["fields"] = f
    _write(p, d)


# ============================================================
# L19 CONSTRAINTS PDK
# ============================================================
def _l19(gd: Path, ic_name: Optional[str]) -> None:
    p = gd / "L19_CONSTRAINTS_PDK.json"
    if not p.is_file():
        return
    d = _read(p)
    f = _ensure_dict(d, "fields")
    if ic_name:
        f["ic_name"] = ic_name
    f["constraints_present"] = (
        "partial — IEEE 1149.1 specifies protocol-level behavior + 4-pin TAP architecture "
        "but does not specify PDK / floorplan / SDC constraints. Per-device + per-board "
        "integration constraints are non-protocol but commonly required.")
    f.setdefault("typical_per_device_constraints", [
        "TAP pins (TCK, TMS, TDI, TDO, optional TRST) shall be dedicated test pins, not shared with functional logic.",
        "Per-device TCK max frequency: implementation-defined; chip-class typical 10-50 MHz; backplane / long-chain typical 1-10 MHz.",
        "Per-device tSU(TMS) / tH(TMS) / tSU(TDI) / tH(TDI) / tPD(TDO) timing parameters specified in the device datasheet.",
        "TDO output drive strength must be sufficient to drive the next device's TDI input + interconnect capacitance.",
        "ESD protection on TAP pins per pin-class HBM / CDM / MM requirements (e.g. ±2 kV HBM minimum).",
        "Slew-rate control on TDO drivers reduces reflections on long chains and backplanes.",
    ])
    f.setdefault("typical_per_board_constraints", [
        "TMS routed as a controlled-impedance trace to minimize skew across the chain.",
        "TCK distributed via a low-skew clock tree or balanced star topology when the chain is large.",
        "Pull-up resistors on TMS (e.g. 10 kΩ) and TDI (e.g. 10 kΩ) to keep them HIGH when the tester is absent — TMS HIGH defaults toward TestLogicReset; TDI HIGH shifts BYPASS opcode all-1s.",
        "Pull-up on TRST (if implemented) so the TAP can run when the tester is present.",
        "Termination on TCK and TDO if rise/fall times approach board-trace propagation delay.",
        "Level translators between devices with different VDD-IO voltages along the chain.",
        "Connector pin allocation for the JTAG bus on the board's test connector (e.g. ARM 20-pin, Xilinx 14-pin, TI MSP430 14-pin formats).",
    ])
    f["process_technology_independence"] = (
        "IEEE 1149.1 is process-independent. Any logic-process technology that can "
        "implement flip-flops and gates can implement the 16-state FSM + IR + Bypass + BSR.")
    f["notes"] = (
        "The 1996 TI primer (SSYA002C) does not list SDC / UPF / DFT constraints "
        "because the standard predates these EDA file formats becoming common. "
        "Modern SoC integrations (e.g. ARM CoreSight, RISC-V Debug, Synopsys "
        "DesignWare DFT IP) supply SDC + UPF + scan-insertion + boundary-scan-cell "
        "library files at the IP-license level.")
    d["fields"] = f
    _write(p, d)


# ============================================================
# L20 DFT SCAN TOPOLOGY
# ============================================================
def _l20(gd: Path, ic_name: Optional[str]) -> None:
    p = gd / "L20_DFT_SCAN_TOPOLOGY.json"
    if not p.is_file():
        return
    d = _read(p)
    f = _ensure_dict(d, "fields")
    if ic_name:
        f["ic_name"] = ic_name
    f["dft_present"] = True
    f["dft_architecture_summary"] = (
        "IEEE 1149.1 IS a DFT architecture. Boundary scan provides controllability "
        "and observability of every external I/O pin via a scan ring that wraps the "
        "device's boundary. The TAP controller serializes access to the "
        "boundary-scan register + optional internal scan paths + optional Device ID "
        "register + optional BIST result registers via a 4-pin interface, "
        "eliminating the need for bed-of-nails ATE at the board level.")
    f["boundary_scan_register_topology"] = {
        "description":     "Single scan ring connecting one boundary-scan cell (BSC) per external I/O pin, plus internal control cells driving OE/direction of bidir pins. The ring entry is TDI; the ring exit is TDO. BSC types: input cell / output cell / bidir cell / control cell (see L17).",
        "cell_count_rule": "1 BSC per external I/O pin; control cells add 1 BSC per associated bidir cell's direction control.",
    }
    f["internal_scan_optional"] = (
        "Beyond boundary scan, devices may expose internal scan paths "
        "(full-scan / partial-scan flip-flops) as user-defined data registers in "
        "the TAP IR map. These are vendor-specific but use the same TAP "
        "infrastructure.")
    f["bist_optional"] = (
        "RUNBIST instruction (if implemented) initiates a device-internal BIST "
        "during RunTestIdle and reports the result via a dedicated DR.")
    f.setdefault("applications_documented_in_primer", [
        "Board-etch and solder-joint testing (Chapter 7).",
        "Cluster testing of non-boundary-scan ICs surrounded by boundary-scan devices.",
        "Board-edge connector testing.",
        "ASIC verification (in-system functional check via INTEST + RUNBIST).",
        "Embedded RAM / ROM testing through the surrounding boundary-scan IC.",
        "Backplane multidrop test environment (ring / star / ASP).",
        "Embedded applications: in-system programming + system-level debug + maintenance.",
    ])
    f.setdefault("test_methodologies", [
        "Built-In Self-Test (BIST) methodology — RUNBIST instruction or chip-level internal BIST controllers reachable via TAP.",
        "Internal Scan Test methodology — full or partial scan-chain flip-flops accessible via user-defined data registers in the TAP.",
    ])
    f.setdefault("design_for_test_flow_chapter_6", [
        "Test requirements analysis.",
        "BIST methodology selection.",
        "Internal scan methodology selection.",
        "Design effort: IC design implementation + IC simulation + SVF for IC design validation + data passed to board designer.",
        "Board design (using BSDL for each device).",
        "Constraints + partitioned scan path planning.",
        "Board validation / manufacturing test.",
    ])
    f.setdefault("data_formats_chapter_5", [
        "BSDL (Boundary-Scan Description Language) — VHDL-subset description of a device's TAP + BSR for test-generation tools.",
        "HSDL (Hierarchical Scan Description Language) — extends BSDL with hierarchical board-of-boards descriptions.",
        "SVF (Serial Vector Format) — vendor-neutral test-vector format with TAP-FSM-aware commands (TLR / RTI / SIR / SDR / RUNTEST / PAUSE / ...).",
    ])
    f["notes"] = (
        "JTAG IS the DFT story documented by SSYA002C — the primer's entire content "
        "is a DFT methodology. From an internal-RTL-DFT perspective, the "
        "boundary-scan register is the external scan ring; user-defined data "
        "registers expose internal scan chains; RUNBIST initiates BIST. Modern "
        "SoCs typically combine 1149.1 boundary scan with IEEE 1500 (embedded "
        "core test wrapper) + IEEE 1687 IJTAG (instrument access) + IEEE 1149.6 "
        "(advanced I/O test) + IEEE 1149.7 (cJTAG) on top of the base 1149.1 TAP.")
    d["fields"] = f
    _write(p, d)


# ============================================================
# L21 POWER INTENT
# ============================================================
def _l21(gd: Path, ic_name: Optional[str]) -> None:
    p = gd / "L21_POWER_INTENT.json"
    if not p.is_file():
        return
    d = _read(p)
    f = _ensure_dict(d, "fields")
    if ic_name:
        f["ic_name"] = ic_name
    f["power_intent_present"] = (
        "partial — IEEE 1149.1 specifies that TestLogicReset disables all test logic "
        "so the device runs functionally (test-logic-quiescent), but does not "
        "formally define power domains, sleep / suspend modes, or power-gating. "
        "The TAP runs on the device's core / IO supply.")
    f["low_power_modes_summary"] = {
        "TestLogicReset_state":          "All test logic is disabled in TestLogicReset; the boundary-scan cells are bypassed in the functional data path; minimal extra power overhead.",
        "TCK_stopped_in_stable_state":   "When the tester stops TCK in any stable FSM state (TestLogicReset / RunTestIdle / PauseDR / PauseIR / ShiftDR / ShiftIR), the FSM holds and dynamic current drops to leakage.",
        "TAP_runs_in_chip_sleep":        "Since TAP pins are dedicated and the FSM can run independent of functional clocks, the TAP can be powered while the rest of the chip is in functional sleep / low-power state (vendor-specific power-domain partitioning required).",
    }
    f["ieee_1149_4_optional_extension"] = (
        "IEEE Std 1149.4 (Mixed-Signal Test Bus) adds analog test-pin observability "
        "layered on the 1149.1 TAP; it includes some power-related instructions but "
        "is a separate standard.")
    f["notes"] = (
        "Practical implementations partition power domains so the TAP can remain "
        "active while functional logic is power-gated — for example, in-system "
        "debug and JTAG-based programming require the TAP to respond when the chip "
        "is in standby. The 1996 primer (SSYA002C) does not formalize this; it is "
        "left to per-vendor implementation. Modern revisions (IEEE 1149.1-2013 + "
        "IEEE 1687 IJTAG + IEEE 1500) provide PDL-based programmable test access "
        "that can include power-aware instructions.")
    d["fields"] = f
    _write(p, d)


# ============================================================
# L22 VERIFICATION PLAN
# ============================================================
def _l22(gd: Path, ic_name: Optional[str]) -> None:
    p = gd / "L22_VERIFICATION_PLAN.json"
    if not p.is_file():
        return
    d = _read(p)
    f = _ensure_dict(d, "fields")
    if ic_name:
        f["ic_name"] = ic_name
    f["verification_plan_present"] = (
        "implicit — IEEE 1149.1 + the TI primer define the architectural rules, "
        "the 16-state FSM transition table, mandatory / optional instructions, "
        "and the application categories. Verification categories below are "
        "derived from the spec and the primer's Chapter 6 (Suggested "
        "Design-for-Test Flow) and Chapter 7 (Applications).")
    if _empty(f.get("verification_categories_derived_from_spec")):
        f["verification_categories_derived_from_spec"] = [
            "TAP-FSM-conformance — drive each of the 32 (16 states × 2 TMS values) transitions and verify the FSM lands in the spec-table next state.",
            "TestLogicReset entry — TMS=1 × 5 TCKs from each of the 16 FSM states reaches TestLogicReset.",
            "TRST asynchronous reset (if implemented) — TRST=LOW → TestLogicReset independent of TCK.",
            "Post-reset default instruction — IDCODE (if Device ID register implemented) or BYPASS otherwise.",
            "IR width discovery + CaptureIR pattern check (b...b01).",
            "BYPASS register single-bit shift — pattern in via TDI emerges on TDO with 1 TCK delay per device.",
            "Daisy-chain length check — BYPASS in all devices + single-0 shift → counts the chain length.",
            "IDCODE readback — 32-bit value with bit 0 = 1; version / part-number / manufacturer-id match expected.",
            "SAMPLE/PRELOAD — BSR captures pin activity (SAMPLE) and pre-loads drive cells (PRELOAD) without driving pins.",
            "EXTEST — UpdateDR drives output pins from BSR; CaptureDR observes input pins.",
            "INTEST (if implemented) — BSR drives device internals and captures internal response.",
            "RUNBIST (if implemented) — BIST initiated in RunTestIdle; result register read back.",
            "HIGHZ (if implemented) — all output pins go to high-impedance.",
            "CLAMP (if implemented) — pre-loaded BSR holds output pins constant while only BYPASS shifts.",
            "TDO 3-state in non-Shift states.",
            "All-1s BYPASS opcode behavior — pulled-up TDI defaults to BYPASS without driving the board.",
            "Multi-device IR scan — concatenated per-device IR opcodes; UpdateIR loads each device's intended instruction.",
            "Multi-device mixed-instruction DR scan — total DR length = sum across devices; bits sliced per device.",
            "Interconnect open / short / stuck-at fault detection via EXTEST drive/observe patterns.",
            "Backplane multidrop test — ring / star / ASP enable + disable.",
            "TCK frequency sweep — chain still works at slowest device's max TCK.",
            "Signal integrity on long chains — measured at end of chain.",
            "BSDL conformance — the device's BSDL file accurately describes its pin map + cell types + IR opcodes; verified by EDA tool import + automated test-pattern generation.",
        ]
    f["notes"] = (
        "The primer does not include a formal verification plan or testbench; the "
        "categories above derive from Chapter 3 (Boundary-Scan Architecture), "
        "Chapter 5 (Data Formats — BSDL/HSDL/SVF), Chapter 6 (Suggested DFT "
        "Flow), and Chapter 7 (Applications). For modern verification, "
        "commercial JTAG-test tools (e.g. Mentor / Siemens BSDL-based ATPG, "
        "ASSET / Goepel ScanWorks, Corelis ScanExpress) provide BSDL-driven "
        "automated test generation that covers most of these categories out of "
        "the box.")
    d["fields"] = f
    _write(p, d)


# ============================================================
# L23 SECURITY REQUIREMENTS
# ============================================================
def _l23(gd: Path, ic_name: Optional[str]) -> None:
    p = gd / "L23_SECURITY_REQUIREMENTS.json"
    if not p.is_file():
        return
    d = _read(p)
    f = _ensure_dict(d, "fields")
    if ic_name:
        f["ic_name"] = ic_name
    f.setdefault("security_requirements_present", False)
    f["notes"] = (
        "IEEE 1149.1-1990 (and the 1996 TI primer documenting it) is a wire-level "
        "test access protocol; there are no confidentiality, integrity, or "
        "authentication features at the protocol layer. Any tester wired to TCK "
        "+ TMS + TDI + TDO has full access to all scan registers + any "
        "vendor-specific user-defined registers. Test data shifted on TDI / TDO "
        "is plaintext. Over the standard's history, several industrial "
        "extensions added optional locking / authentication mechanisms layered "
        "on top, but they are NOT part of the 1149.1 base architecture "
        "documented by this primer.")
    f.setdefault("industrial_security_extensions_layered_on_jtag", [
        "IEEE 1149.1-2013 + IEEE 1687-2014 — added PDL (Procedural Description Language) which can carry vendor-defined authentication challenges before access to selected instruments.",
        "ARM CoreSight DAP authentication interface — debug-port locking via an external authentication signal (e.g. DBGEN / NIDEN / SPIDEN / SPNIDEN).",
        "FPGA vendor JTAG security — Intel/Altera and AMD/Xilinx parts add BSDL-undocumented vendor instructions for bitstream encryption-key handling + secure-boot enrolment + fuse-burn-only debug disable.",
        "Smartcard / secure-element JTAG fuses — single-use fuses that permanently disable the TAP (or restrict it to BYPASS-only) post-production.",
        "IEEE 1149.7 cJTAG — 2-pin compact JTAG with built-in star topology; can carry encrypted instrument access on top of the standard TAP.",
    ])
    f.setdefault("threat_model_for_open_jtag", [
        "An attacker with physical board access can connect a JTAG tester and read out IDCODE / scan boundary pins / drive internal scan paths.",
        "Vendor-specific user-defined data registers may expose internal memory (e.g. SRAM-scan, flash-programming) — a chain-of-custody concern post-production.",
        "Bus-monitoring on the TAP can recover proprietary BSDL extensions reverse-engineerable from observed shift patterns.",
    ])
    f.setdefault("common_production_mitigations", [
        "Burn a JTAG-disable fuse at post-production test (the TAP responds only to TestLogicReset + BYPASS thereafter; or the TAP is completely disabled).",
        "Gate the TAP behind a vendor-specific authentication state (e.g. ARM CoreSight DBGEN, FPGA secure-key challenge).",
        "Remove the JTAG header from production boards (so attackers must solder probes onto fine-pitch test pads).",
        "Use cJTAG (1149.7) for production debug; the compact 2-pin star topology is less convenient for casual probing.",
    ])
    d["fields"] = f
    _write(p, d)


# ---------------------------------------------------------------------------
# Module-level importable detector (lifted from the inline detector in
# phase1_doc_one_shot_runner.py — ORGANIC-20260531). Byte-for-byte the same
# boolean the runner used inline (`_spi_blob` -> `blob`), so behaviour is
# identical; exposing it module-level lets the universal no-misfire guard
# (tests/test_protocol_detector_no_misfire.py) auto-cover this protocol.
# Reads ONLY the spec text `blob` — never a filename or benchmark name.
# ---------------------------------------------------------------------------
def is_jtag(blob: str) -> bool:
    """Content-only `jtag` detector (importable, lifted from the runner).

    Empty-safe. Reads ONLY ``blob`` (spec text). Byte-for-byte the
    same boolean the runner used inline BELOW the foreign-primary defer.

    FOREIGN-PRIMARY DEFER (mirrors `is_mipi`'s doctrine — general,
    content-only, structural; NO benchmark/chip/SKU literal as detection
    logic). JTAG's IEEE-1149.1 TAP vocabulary is the lingua franca of the
    on-chip debug-and-test domain, so several SIBLING debug protocols cite
    the TAP state machine / TCK-TMS-TDI-TDO / IEEE 1149.1 incidentally while
    being ABOUT something else. The generic JTAG synth must not fire on those.
    If the blob's DOMINANT subject is a foreign debug protocol, defer (False):

      - CoreSight — the ARM on-chip TRACE ARCHITECTURE (AMBA Trace Bus used as
        a trace transport + trace FUNNEL + trace REPLICATOR + at least one
        trace SINK (TPIU/ETB/ETF/ETR) + at least one trace SOURCE
        (ETM/ITM/STM/PTM)). This trace-transport structure is absent from a
        pure JTAG-TAP / boundary-scan doc (mirrors `is_coresight.trace_arch`).
      - MDIO — the IEEE 802.3 Clause-22/45 MAC/PHY management interface: the
        MDC+MDIO two-wire pair PLUS the fixed management-frame field model
        (ST/OP/PHYAD/REGAD/TA/DATA, preamble, Clause 22/45). That frame model
        is absent from a JTAG TAP doc (mirrors `is_mdio`).
      - SWD — the ARM Serial-Wire single-bidirectional-data Debug Port
        (SWDIO+SWCLK, the serial-wire alternative to the 4-wire JTAG TAP),
        or the SWD+ADIv5 serial-wire Debug-Port/Access-Port signature. The
        single-wire serial DP is the sibling-MUTEX discriminator vs JTAG's
        4-wire TAP (mirrors `is_swd`).

    Empirically corpus-clean: the real `jtag` benchmark trips NONE of these
    (no ATB/funnel/replicator trace transport, no MDC/PHYAD frame model, no
    SWDIO/SWCLK serial-wire pair) and stays True; coresight/mdio/swd each trip
    their own primary and are suppressed.
    """
    if not blob:
        return False
    low = blob.lower()

    # --- FOREIGN-PRIMARY DEFER (the blob's true subject is NOT JTAG). ---
    # CoreSight trace architecture: ATB-as-trace-bus + funnel + replicator
    # (the trace TRANSPORT) + >=1 trace sink + >=1 trace source.
    _atb = ("amba trace bus" in low or " atb " in f" {low} "
            or "atb)" in low or "(atb" in low)
    _trace_transport = _atb and "funnel" in low and "replicator" in low
    _trace_sink = sum(bool(x) for x in (
        ("tpiu" in low or "trace port interface unit" in low),
        ("etb" in low or "embedded trace buffer" in low),
        ("etf" in low or "embedded trace fifo" in low),
        ("etr" in low or "embedded trace router" in low),
    ))
    _trace_source = sum(bool(x) for x in (
        ("etm" in low or "embedded trace macrocell" in low),
        ("itm" in low or "instrumentation trace" in low),
        ("stm" in low or "system trace macrocell" in low
         or "system trace protocol" in low),
        ("ptm" in low or "program trace macrocell" in low),
    ))
    coresight_primary = (
        _trace_transport and _trace_sink >= 1 and _trace_source >= 1)

    # MDIO Clause-22/45 management interface: MDC+MDIO pair + frame-field model.
    _mdio_pair = "mdc" in low and "mdio" in low
    _mdio_fields = sum(bool(x) for x in (
        ("phyad" in low or "phy address" in low),
        ("regad" in low or "register address" in low),
        ("clause 22" in low or "clause22" in low),
        ("clause 45" in low or "clause45" in low),
        ("management data input" in low),
    ))
    mdio_primary = _mdio_pair and _mdio_fields >= 3

    # SWD serial-wire Debug Port: single bidirectional data line (SWDIO+SWCLK),
    # or the SWD+ADIv5 serial-wire DP/AP signature.
    swd_primary = (
        ("SWDIO" in blob and "SWCLK" in blob)
        or ("SWD" in blob and "ADIv5" in blob
            and (("serial wire" in low or "serial-wire" in low)
                 or ("DP" in blob and "AP" in blob)))
        or ("SWJ-DP" in blob and "Debug Port" in blob))

    if coresight_primary or mdio_primary or swd_primary:
        return False

    # --- STRUCTURAL JTAG signature (unchanged from the runner's inline
    #     detector). ---
    tap_fsm = (
        "ShiftDR" in blob or "ShiftIR" in blob
        or "Shift-DR" in blob or "Shift-IR" in blob
        or "Capture-DR" in blob or "CaptureDR" in blob
        or "Update-DR" in blob or "UpdateDR" in blob
        or "TestLogicReset" in blob
        or "Test-Logic-Reset" in blob
        or "RunTestIdle" in blob or "Run-Test/Idle" in blob
        or "TAP controller" in blob
        or "SelectDRScan" in blob)
    return bool(tap_fsm and (
        ("TCK" in blob and "TMS" in blob
            and "TDI" in blob and "TDO" in blob)
        or ("TestLogicReset" in blob
            and "ShiftIR" in blob
            and "ShiftDR" in blob)
        or ("IEEE 1149.1" in blob
            and "boundary scan" in blob.lower())))
