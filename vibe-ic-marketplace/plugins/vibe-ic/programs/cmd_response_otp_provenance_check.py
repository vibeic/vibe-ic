#!/usr/bin/env python3
"""
cmd_response_otp_provenance_check.py — for opcodes whose response
example bytes match a slice of the project's OTP image, refuse a
`response_source: "literal"` (or unspecified) declaration. Force
the L3 to declare `response_source: "otp_range"` with `otp_base` and
`otp_len` so the RTL streams live OTP bytes rather than fabricated
constants.

Why this gate exists
====================
Surfaced by ROOT_CAUSE_ANALYSIS Area 3 (<benchmark> fresh agent vs vendor).
The vendor docs presented a per-opcode response table next to an OTP
table in the same xlsx; the example bytes in the response table are
the expected response *given that one example OTP image*, NOT the
response definition. The fresh agent's cmd-protocol-gen extractor
read the example as the answer and emitted hard-coded literal bytes.
Result: real silicon's CRC-over-OTP fails because the chip sends
fabricated bytes that don't match what the host computes against the
factory OTP image. Symptom: byte[6]=0x02 fallback fingerprint.

Rule
----
For each opcode in L3_CMD_PROTOCOL.json with an example response
payload of ≥3 bytes:
  Look for ≥3 consecutive bytes in input/otp/*.ver or rtl/*.hex
  matching the example bytes. If found AND the opcode's
  `response_source` is missing OR equal to "literal", FAIL with a
  hint to set `response_source: "otp_range"` with the discovered
  base address and length.

Skips silently when:
  - L3_CMD_PROTOCOL.json absent
  - no opcode has any usable example bytes
  - no .ver / .hex OTP image present
  - every opcode already declares a non-literal response_source

Honors waivers.json key `cmd_response_otp_provenance_alternative`
(≥20-char rationale).

Usage
-----
python3 cmd_response_otp_provenance_check.py <project_dir>

Returns 0 on PASS / silent-skip / waived, 1 on FAIL.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path
import _path_layout as _pl


HEX_BYTE = re.compile(r"\b([0-9a-fA-F]{2})\b")


def _load_json(p: Path) -> dict:
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text())
    except Exception:
        return {}


def _find_l3(project: Path) -> Path | None:
    for base in (project, _pl.generated_docs_dir(project)):
        p = base / "L3_CMD_PROTOCOL.json"
        if p.exists():
            return p
    return None


def _load_otp_image(project: Path) -> bytes:
    """Concatenate every .ver/.hex/.mem image we can find under
    project/{input,otp,rtl,fpga}/. Returns the *raw* byte stream the
    image describes (one byte per `XX` hex pair). Verilog
    $readmemh-format files use `@addr` lines to set the cursor; we
    collapse out @-directives and read every byte sequentially — that
    is enough for a substring search for ≥3 consecutive bytes."""
    out = bytearray()
    for sub in ("phase2/stage1/rtl", "phase2/stage1/fpga", "input", "otp", "rtl", "fpga"):
        d = project / sub
        if not d.exists():
            continue
        for ext in ("*.ver", "*.hex", "*.mem"):
            for f in d.rglob(ext):
                try:
                    txt = f.read_text(errors="replace")
                except Exception:
                    continue
                # strip comments, @-directives
                txt = re.sub(r"//[^\n]*", "", txt)
                txt = re.sub(r"/\*.*?\*/", "", txt, flags=re.DOTALL)
                txt = re.sub(r"@\s*[0-9a-fA-F]+", "", txt)
                for m in HEX_BYTE.finditer(txt):
                    out.append(int(m.group(1), 16))
    return bytes(out)


def _opcode_examples(l3: dict) -> list[tuple[str, list[int],
                                             str | None,
                                             dict | None]]:
    """Return [(opcode_str, example_bytes, response_source,
                otp_range_dict)] for every opcode that has an example
    response payload of ≥3 bytes. response_source / otp_range may be
    None if not declared."""
    out: list[tuple[str, list[int], str | None, dict | None]] = []
    for cmd in (l3.get("commands") or l3.get("command_table") or []):
        if not isinstance(cmd, dict):
            continue
        opcode = (cmd.get("opcode") or cmd.get("code") or
                  cmd.get("name") or "?")
        rs = cmd.get("response_source")
        otp_range = cmd.get("otp_range")
        # Try a variety of example field names.
        ex = (cmd.get("response_example") or cmd.get("rsp_example") or
              cmd.get("example_response") or cmd.get("response_hex"))
        bytes_list: list[int] = []
        if isinstance(ex, dict):
            hexstr = (ex.get("response_hex") or ex.get("bytes_hex") or
                      ex.get("hex") or "")
            if isinstance(hexstr, str):
                bytes_list = [int(m.group(1), 16)
                              for m in HEX_BYTE.finditer(hexstr)]
        elif isinstance(ex, list):
            for item in ex:
                if isinstance(item, str):
                    m = re.match(r"0?x?([0-9a-fA-F]{1,2})$", item.strip())
                    if m:
                        bytes_list.append(int(m.group(1), 16))
                elif isinstance(item, int) and 0 <= item <= 0xFF:
                    bytes_list.append(item)
        elif isinstance(ex, str):
            bytes_list = [int(m.group(1), 16)
                          for m in HEX_BYTE.finditer(ex)]
        if len(bytes_list) >= 3:
            out.append((str(opcode), bytes_list, rs,
                        otp_range if isinstance(otp_range, dict) else None))
    return out


def _find_consecutive(needle: list[int],
                      haystack: bytes,
                      min_run: int = 3) -> tuple[int, int] | None:
    """Find the longest consecutive run (≥min_run bytes) of `needle`
    that appears in `haystack`. Try the largest contiguous prefix
    first, then shorter prefixes. Returns (otp_base, run_len) or
    None."""
    if not haystack:
        return None
    n = len(needle)
    for run_len in range(n, min_run - 1, -1):
        for start in range(0, n - run_len + 1):
            run = bytes(needle[start:start + run_len])
            idx = haystack.find(run)
            if idx >= 0:
                return idx, run_len
    return None


def _waived(project: Path) -> bool:
    waivers = project / "waivers.json"
    if not waivers.exists():
        return False
    try:
        d = json.loads(waivers.read_text())
        v = d.get("cmd_response_otp_provenance_alternative", "")
        return isinstance(v, str) and len(v.strip()) >= 20
    except Exception:
        return False


def main() -> int:
    if len(sys.argv) < 2:
        print("Usage: cmd_response_otp_provenance_check.py <project_dir>")
        return 2
    project = Path(sys.argv[1]).resolve()
    if not project.is_dir():
        print(f"FAIL — not a directory: {project}")
        return 1

    l3_path = _find_l3(project)
    if l3_path is None:
        print("PASS — no L3_CMD_PROTOCOL.json (gate not applicable)")
        return 0
    l3 = _load_json(l3_path)
    if not l3 or l3.get("protocol_present") is False:
        print("PASS — L3 declares no protocol (gate not applicable)")
        return 0

    examples = _opcode_examples(l3)
    if not examples:
        print("PASS — no opcode has an example response payload of "
              "≥3 bytes (gate not applicable)")
        return 0

    otp = _load_otp_image(project)
    if not otp:
        print("PASS — no .ver / .hex / .mem OTP image present (gate "
              "not applicable)")
        return 0

    fails: list[tuple[str, int, int, str | None]] = []  # opcode, base, run, current_source
    passes: list[str] = []
    for opcode, bytes_list, rs, otp_range in examples:
        hit = _find_consecutive(bytes_list, otp, min_run=3)
        if hit is None:
            passes.append(f"{opcode} (no OTP overlap; literal acceptable)")
            continue
        # Overlap found: response_source must be NOT literal, NOT missing.
        if rs in (None, "", "literal"):
            fails.append((opcode, hit[0], hit[1], rs))
        else:
            passes.append(f"{opcode} (OTP overlap, response_source="
                          f"{rs!r}; OK)")

    if not fails:
        print(f"PASS — all {len(examples)} opcode example(s) either "
              "lack OTP overlap or already declare a non-literal "
              "response_source")
        for p in passes:
            print(f"  • {p}")
        return 0

    if _waived(project):
        print(f"PASS_WITH_WAIVER — {len(fails)} opcode(s) have OTP "
              "overlap with literal response_source but waiver is set:")
        for op, base, run, src in fails:
            print(f"  • opcode {op}: example matches OTP[0x{base:02x}.."
                  f"0x{base+run-1:02x}] ({run} bytes) but "
                  f"response_source={src!r}")
        return 0

    print(f"FAIL — {len(fails)} opcode(s) have example response bytes "
          "that match an OTP slice but declare literal response_source:")
    for op, base, run, src in fails:
        print(f"  • opcode {op}: example matches OTP[0x{base:02x}.."
              f"0x{base+run-1:02x}] ({run} bytes); current "
              f"response_source={src!r}")
    print()
    print("Why this matters:")
    print("  The vendor doc's example bytes are the expected response")
    print("  given the *example* OTP image; the response definition is")
    print("  'stream OTP[base..base+len-1] then CRC'. Hard-coding the")
    print("  example as a literal payload makes the chip send the same")
    print("  bytes regardless of the factory-programmed OTP, so real")
    print("  silicon's CRC-over-OTP fails on every host that programs a")
    print("  different OTP. Symptom: response byte[N] fallback to a")
    print("  CRC-mismatch sentinel value.")
    print()
    print("Fix: regenerate L3 with `response_source: \"otp_range\"`")
    print("  for each affected opcode and the discovered (base,len):")
    for op, base, run, _ in fails:
        print(f'    "{op}": {{"response_source": "otp_range", '
              f'"otp_range": {{"base": {base}, "length": {run}}} }}')
    print("Or document an exception in waivers.json (≥20 chars):")
    print('    {"cmd_response_otp_provenance_alternative": "<reason>"}')
    return 1


if __name__ == "__main__":
    sys.exit(main())
