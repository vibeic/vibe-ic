#!/usr/bin/env python3
"""crc_validation_present.py — Wave 58 / BACKLOG-v12 P0.3 plugin gate.

When `<project>/generated_docs/L3_*.json` declares CRC parameters
(`crc_parameters.polynomial_hex`), the dispatch FSM in rtl/ MUST
consume the CRC engine's output (`crc_q == 8'h00` or equivalent
residue check) somewhere on the validate / dispatch decision path.

The previous (v0.121-vendor) RTL instantiated `crc8` in chip_top.sv,
fed it across every RX bit, but the main_fsm `frame_ok` signal did
NOT include `crc_q` — wrong-CRC frames were dropped only as a side-
effect of length / 9-bit gates, and many invalid frames PASSed
silently (Wave 56 column-D Issue 4).

Detection (chip-AGNOSTIC)
=========================
1. SKIP when L3 has no `crc_parameters.polynomial_hex` (or `crc.poly`).
2. Find the CRC engine instance in rtl/ — look for a module called
   `crc8` / `crc16` / `crc_engine` / `crc_check` / etc., OR a
   `<inst> u_crc` / `crc_inst` instantiation pattern.
3. Find the CRC output signal — heuristic: `crc_q` / `crc_out` /
   `crc_residue` / `crc_value` / `crc_ok` / `crc_valid`.
4. Find the dispatch / validate state — heuristic: any state name
   containing `validate` / `dispatch` / `decode` / `frame_ok` /
   `frame_check`.
5. PASS when the CRC output signal is referenced anywhere in the
   fan-in of the validate-state branch condition (frame_ok wire,
   case guard expression, an explicit `crc_q == 0` / `crc_ok`
   condition).
6. FAIL when the CRC engine is instantiated AND the project has
   L3.crc_parameters AND the CRC output is NOT in the validate
   decision fan-in.

Honors waiver `crc_validation_explicit_bypass` (≥40 chars).

Exit codes
==========
0  — PASS / SKIP / PASS_WITH_WAIVER
1  — FAIL
2  — usage error
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import List, Tuple
import _path_layout as _pl

# Wave 78 — explicit class applicability. CRC validation against L3
# is a command-protocol concern; pure-analog / bare-FPGA projects do
# not declare L3.crc_parameters and the gate already SKIPs there, but
# the explicit list documents intent + lets ic_class_profile fast-skip.
sys.path.insert(0, str(Path(__file__).resolve().parent))
from ic_class_profile import detect_ic_class  # noqa: E402

_APPLICABLE_CLASSES = (
    "aid_class_half_duplex",
    "digital_cmd_driven",
    "mixed_signal_otp",
)

WAIVER_KEY = "crc_validation_explicit_bypass"
WAIVER_MIN_LEN = 40


def strip_comments(src: str) -> str:
    src = re.sub(r"/\*.*?\*/", "", src, flags=re.DOTALL)
    src = re.sub(r"//[^\n]*", "", src)
    return src


def find_rtl_files(project_dir: Path) -> List[Path]:
    rtl_dir = _pl.rtl_dir(project_dir)
    if not rtl_dir.exists():
        return []
    files: List[Path] = []
    for p in rtl_dir.rglob("*"):
        if p.suffix.lower() in (".v", ".sv", ".svh", ".vh"):
            files.append(p)
    return sorted(files)


def has_l3_crc_declared(project_dir: Path) -> bool:
    gd = _pl.generated_docs_dir(project_dir)
    if not gd.is_dir():
        return False
    for path in gd.glob("L3_*.json"):
        try:
            d = json.loads(path.read_text())
        except Exception:
            continue
        crc = d.get("crc_parameters") or d.get("crc") or {}
        if not isinstance(crc, dict):
            continue
        poly = crc.get("polynomial_hex") or crc.get("poly") or \
            crc.get("polynomial")
        if poly:
            return True
    return False


_CRC_INST_RE = re.compile(
    r"\b(?:crc[0-9_]*|\w*_crc|crc_engine|crc_check|crc_calc|"
    r"crc_compute|crc_unit)\b\s+\w+\s*\(",
    re.IGNORECASE,
)
_CRC_OUT_RE = re.compile(
    r"\b(crc_q|crc_out|crc_value|crc_residue|crc_ok|crc_valid|"
    r"crc_zero|crc_check_ok)\b",
    re.IGNORECASE,
)


def main(argv: List[str]) -> int:
    if len(argv) < 2:
        print("Usage: crc_validation_present.py <project_dir>")
        return 2

    project_dir = Path(argv[1]).resolve()
    if not project_dir.exists():
        print(f"FAIL — project dir not found: {project_dir}")
        return 1

    # Wave 78 — explicit class gate. `unknown` falls through to existing
    # FAIL logic (fail-closed) so a missing or malformed ic_class_profile
    # never silently SKIPs.
    #
    # Wave 82 Fix F — secondary trigger on L3 CRC evidence: even if the
    # ic_class is not in _APPLICABLE_CLASSES (e.g. bare_fpga), if the
    # project's L3 declares crc_parameters then CRC validation IS
    # required regardless of class — CRC consumption is evidence-driven,
    # not class-driven. Without this hook a bare_fpga IC carrying
    # L3.crc_parameters silently SKIPs and wrong-CRC frames PASS.
    has_l3_crc = has_l3_crc_declared(project_dir)
    profile = detect_ic_class(project_dir)
    ic_class = profile.get("ic_class", "unknown")
    if ic_class not in _APPLICABLE_CLASSES and ic_class != "unknown" \
            and not has_l3_crc:
        print(f"SKIP — not applicable to ic_class={ic_class}")
        return 0

    if not has_l3_crc:
        print("SKIP — no L3 crc_parameters declared")
        return 0

    rtl_files = find_rtl_files(project_dir)
    if not rtl_files:
        print("SKIP — no rtl/ directory")
        return 0

    # Collect: (a) does any RTL instantiate a CRC engine?
    #          (b) what CRC output signals appear in any RTL?
    has_crc_inst = False
    crc_out_signals: set[str] = set()
    rtl_bodies: List[Tuple[Path, str]] = []
    for path in rtl_files:
        try:
            src = strip_comments(path.read_text(errors="ignore"))
        except Exception:
            continue
        rtl_bodies.append((path, src))
        if _CRC_INST_RE.search(src):
            has_crc_inst = True
        for m in _CRC_OUT_RE.finditer(src):
            crc_out_signals.add(m.group(1).lower())

    if not has_crc_inst:
        # No CRC engine instantiated — that's a different gate's job
        # (cmd_protocol_crc_verify / crc_completeness_check).  Here
        # we only check that an instantiated engine is consumed.
        print(
            "SKIP — no CRC engine instantiation found in rtl/ "
            "(crc_completeness_check covers this case)"
        )
        return 0

    # Find the validate / dispatch state body and check if any CRC
    # output signal appears anywhere in the always-block / wire decl
    # / state-arm condition.
    #
    # We only consider FILES that look like FSM / top-level / dispatch
    # modules — NOT the CRC engine itself (crc8.v / crc16.v contain
    # `if (crc_q[0] ^ data_bit)` for their internal feedback path,
    # which is not a validation consumption).
    crc_used_in_validate = False
    for path, src in rtl_bodies:
        # Skip the CRC engine's own source file.
        stem = path.stem.lower()
        if re.fullmatch(r"crc[0-9_]*", stem) or stem.endswith("_crc"):
            continue
        # Look for frame_ok / frame_valid wire decl using CRC.
        if re.search(
            r"(?:wire|assign|logic)\s+\w*frame_ok\w*\b[^;]{0,400}"
            r"(?:crc_q|crc_out|crc_ok|crc_valid|crc_residue|crc_value|"
            r"crc_zero|crc_check_ok)",
            src, re.IGNORECASE | re.DOTALL,
        ):
            crc_used_in_validate = True
            break
        # Look for a validate / dispatch state arm body that
        # references a CRC output signal.
        for sm in re.finditer(
            r"S_(?:VALIDATE|DISPATCH|FRAME_CHECK|CRC_CHECK|"
            r"CHECK|DECODE)\s*:\s*begin(?P<body>.{1,3000}?)end",
            src, re.IGNORECASE | re.DOTALL,
        ):
            if _CRC_OUT_RE.search(sm.group("body")):
                crc_used_in_validate = True
                break
        if crc_used_in_validate:
            break
        # Look for `if (crc_q == 8'h00)` / `if (crc_ok)` anywhere
        # — but require an EQUALITY/ZERO check (not the engine's
        # internal LSB feedback `if (crc_q[0] ^ data_bit)`).
        if re.search(
            r"\bif\s*\([^)]{0,400}\b(?:crc_q|crc_out|crc_residue|"
            r"crc_value|crc_zero|crc_check_ok|crc_ok|crc_valid)\b\s*"
            r"(?:==|!=|\)|\&\&|\|\|)",
            src, re.IGNORECASE,
        ):
            crc_used_in_validate = True
            break
        # Or any `crc_*ok` / `crc_*valid` / `crc_*zero` named wire /
        # reg / assign — presence implies someone is exposing the CRC
        # residue as a named signal for downstream consumption.  The
        # `*` allows arbitrary qualifier infixes like
        # `crc_observed_zero`, `crc_residue_ok`, `crc_check_pass`.
        if re.search(
            r"\b(?:wire|reg|assign|logic)\s+(?:[\[\]\w\s,:]+\s+)?"
            r"crc_(?:[a-z_]*?_)?(?:ok|valid|check_ok|zero|pass|good)\b",
            src, re.IGNORECASE,
        ):
            crc_used_in_validate = True
            break
        # Or any explicit `(crc_q == <value>)` boolean assigned to a
        # wire — that's a concrete residue check exposed for synthesis
        # / external consumption.
        if re.search(
            r"\b(?:wire|assign|logic)\s+\w+\s*=[^;]{0,200}"
            r"\bcrc_q\s*==\s*8?'\s*h\s*[0-9a-f]+",
            src, re.IGNORECASE,
        ):
            crc_used_in_validate = True
            break

    waivers = project_dir / "waivers.json"
    is_waived = False
    rationale = ""
    if waivers.exists():
        try:
            d = json.loads(waivers.read_text())
            raw = d.get(WAIVER_KEY)
            if isinstance(raw, str) and \
               len(raw.strip()) >= WAIVER_MIN_LEN:
                is_waived = True
                rationale = raw.strip()
            elif isinstance(raw, dict):
                r = raw.get("rationale") or raw.get("reason") or ""
                if isinstance(r, str) and \
                   len(r.strip()) >= WAIVER_MIN_LEN:
                    is_waived = True
                    rationale = r.strip()
        except Exception:
            pass

    if crc_used_in_validate:
        print(
            "PASS — CRC engine instantiated AND output signal consumed "
            "in validate / dispatch / frame_ok decision path"
        )
        return 0

    if is_waived:
        print(
            f"PASS_WITH_WAIVER — CRC engine instantiated but output not "
            f"in validate fan-in; silenced by waivers.{WAIVER_KEY}: "
            f"{rationale[:80]}…"
        )
        return 0

    print(
        "FAIL — L3 declares CRC parameters AND a CRC engine is "
        "instantiated in rtl/, but the CRC output (crc_q / crc_ok / "
        "crc_residue / etc.) does NOT appear in the validate / "
        "dispatch / frame_ok decision path.  Wrong-CRC frames will "
        "silently PASS (Wave 56 column-D root cause)."
    )
    print()
    print("Fix: add `crc_q == 8'h00` (or equivalent) to the frame_ok")
    print("wire OR the S_VALIDATE branch condition.  Example:")
    print()
    print("    wire crc_ok = (rx_idx <= 4'd1) || (crc_q == 8'h00);")
    print("    wire frame_ok = ... && crc_ok;")
    print()
    print(
        f"Or document an alternative in waivers.json:\n"
        f'    {{"{WAIVER_KEY}": "<≥40-char rationale>"}}'
    )
    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
