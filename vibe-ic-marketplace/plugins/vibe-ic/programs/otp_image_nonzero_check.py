#!/usr/bin/env python3
"""otp_image_nonzero_check.py

Closes the silent-FAIL where Quartus / iverilog / yosys load an all-zero
placeholder OTP image into the chip's $readmemh / altsyncram init_file,
the build succeeds, the chip burns, but every byte fetched from OTP is
0x00 — making the hardware deterministically FAIL the host-tester verdict.

This gate is **chip-AGNOSTIC**: no foundry / vendor / chip / OTP-byte
hardcoded. It just enforces a generic invariant:

    When L11 (or L4) declares OTP layout, and the project ships an
    OTP image file (`*.hex` / `*.mif`) referenced from RTL via
    `$readmemh` / altsyncram `init_file`, that image MUST contain at
    least one non-zero byte at an address declared as a *reply payload*
    (not just a reserved or scratchpad region).

If the image is all-zero, FAIL with actionable error message naming
the file and pointing to the spec doc that should provide values.

Honors waiver `otp_image_intentionally_zeroed` (>= 60 chars per
declaration; one entry per zero region).

Usage:
    python3 otp_image_nonzero_check.py <project_dir>

Exit codes:
    0  PASS / SKIP (no OTP layout declared OR file not found OR all good)
    1  FAIL (image present but all-zero where spec demands non-zero)
    2  IO / parse error
"""
from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path
from typing import List, Optional, Tuple


WAIVER_KEY = "otp_image_intentionally_zeroed"
WAIVER_MIN = 60


def _rel(f: Path, project: Path) -> str:
    """Human-readable path of `f` relative to `project`, robust to symlinked
    inputs. ``Path.relative_to`` raises ``ValueError`` when `f` is not a
    subpath of `project` — which happens when the project's ``input/`` tree
    is a symlink to a shared/source location outside the project subtree
    (a common space-saving staging pattern). ``os.path.relpath`` tolerates a
    non-subpath relationship (yielding ``"../shared/otp/image.hex"``), and we
    fall back to the absolute string if even that fails. This only affects
    report formatting; the gate's verdict logic is unchanged."""
    try:
        return str(f.relative_to(project))
    except ValueError:
        try:
            return os.path.relpath(str(f), str(project))
        except Exception:
            return str(f)


_L_DOC_GLOBS = (
    "phase1/generated_docs/L11_OTP_CONTENT.json",
    "phase1/generated_docs/L11*.json",
    "phase1/generated_docs/L4_REGMAP.json",
    "phase1/generated_docs/L4*.json",
)


_HEX_FILE_GLOBS = (
    "input/otp/*.hex",
    "otp/*.hex",
    "phase2/stage2/synth/*.hex",
    "phase2/stage1/fpga/*.hex",
    "phase2/stage1/rtl/*.hex",
    "input/otp/*.mif",
    "phase2/stage1/fpga/*.mif",
    "phase2/stage2/synth/*.mif",
)


# Identifiers in L11/L4 that label the OTP region as a *reply payload*
# (must be non-zero for protocol verdict). We don't hardcode "ID" or
# "byte[6]"; instead any of these section labels triggers the check.
_PAYLOAD_LABEL_RE = re.compile(
    r"\b(ID|MSN|ASN|VID|PID|REV|SN|FCH|SMA|FUSE_ID|"
    r"IDENTITY|SERIAL|PRODUCT|VENDOR|REPLY|RESPONSE|"
    r"GET_ID|GET_INFO|GET_MSN|GET_ASN|GET_SMA)\b",
    re.IGNORECASE,
)


def _waiver_count(project: Path) -> int:
    p = project / "waivers.json"
    if not p.exists():
        return 0
    try:
        d = json.loads(p.read_text())
    except Exception:
        return 0
    v = d.get(WAIVER_KEY)
    if isinstance(v, str):
        return 1 if len(v.strip()) >= WAIVER_MIN else 0
    if isinstance(v, list):
        return sum(1 for s in v
                   if isinstance(s, str) and len(s.strip()) >= WAIVER_MIN)
    return 0


def _find_otp_layout(project: Path) -> Tuple[bool, List[Tuple[int, str]]]:
    """Scan L11/L4 for a list of (addr, label) for payload-bearing OTP regions.

    Returns (has_layout, [(addr, label) ...]). Empty list if no layout
    found OR layout doesn't mention any payload-class label.
    """
    for pat in _L_DOC_GLOBS:
        for f in project.glob(pat):
            try:
                d = json.loads(f.read_text())
            except Exception:
                continue
            # Try common shapes:
            #   d['otp_bytes'] = [{'addr': 0, 'section': 'ID', ...}, ...]
            #   d['otp_layout']['fields'] = [{'addr_start': 0, 'name': 'ID[0]'}, ...]
            entries: List[Tuple[int, str]] = []
            for collection_key in ("otp_bytes", "otp_layout", "fields",
                                   "registers", "byte_layout"):
                v = d.get(collection_key)
                if isinstance(v, dict):
                    sub = v.get("fields") or v.get("entries") or v.get("bytes")
                    if isinstance(sub, list):
                        v = sub
                if isinstance(v, list):
                    for entry in v:
                        if not isinstance(entry, dict):
                            continue
                        a = entry.get("addr")
                        if a is None:
                            a = entry.get("addr_start") or entry.get("address")
                        if isinstance(a, str):
                            try:
                                a = int(a, 0)
                            except Exception:
                                continue
                        if not isinstance(a, int):
                            continue
                        label = (entry.get("section")
                                 or entry.get("name")
                                 or entry.get("field")
                                 or "")
                        if not isinstance(label, str):
                            continue
                        if _PAYLOAD_LABEL_RE.search(label):
                            entries.append((a, label))
            if entries:
                return (True, entries)
    return (False, [])


def _read_hex_image(p: Path) -> Optional[List[int]]:
    """Parse $readmemh-style or .mif-style image. Returns list of byte
    values (one per address), or None on parse failure."""
    try:
        text = p.read_text(encoding="utf-8", errors="ignore")
    except Exception:
        return None
    if p.suffix.lower() == ".mif":
        # Quartus altsyncram MIF: lines like `  0F : 1A;` between
        # `CONTENT BEGIN` and `END;`.
        out: List[int] = []
        in_content = False
        for line in text.splitlines():
            line = line.strip().rstrip(";")
            if line.upper().startswith("CONTENT BEGIN"):
                in_content = True
                continue
            if line.upper() == "END":
                in_content = False
                continue
            if not in_content:
                continue
            m = re.match(r"^\s*([0-9a-fA-F]+)\s*:\s*([0-9a-fA-F]+)", line)
            if not m:
                continue
            try:
                _ = int(m.group(1), 16)
                v = int(m.group(2), 16)
                out.append(v)
            except Exception:
                continue
        return out if out else None
    # $readmemh: one byte per line, optional comments
    out2: List[int] = []
    for line in text.splitlines():
        line = line.split("//")[0].strip()
        if not line:
            continue
        if line.startswith("@"):
            continue   # explicit address spec; addressing not modelled here
        try:
            out2.append(int(line, 16))
        except Exception:
            continue
    return out2 if out2 else None


def _check_image_nonzero_at(image: List[int], addrs: List[int]) -> bool:
    """At least one address in `addrs` must be non-zero in `image`."""
    return any(0 <= a < len(image) and image[a] != 0 for a in addrs)


def main() -> int:
    if len(sys.argv) < 2:
        print("usage: otp_image_nonzero_check <project_dir>",
              file=sys.stderr)
        return 2
    project = Path(sys.argv[1]).resolve()
    if not project.is_dir():
        print(f"ERROR: {project} not a directory", file=sys.stderr)
        return 2

    has_layout, payload_entries = _find_otp_layout(project)
    if not has_layout or not payload_entries:
        print("[SKIP] otp_image_nonzero_check: "
              "no L11/L4 OTP layout declares payload-class regions "
              "(ID/MSN/ASN/SN/SMA/FCH/etc.)")
        return 0

    image_files: List[Path] = []
    for pat in _HEX_FILE_GLOBS:
        image_files.extend(project.glob(pat))
    image_files = sorted({p.resolve() for p in image_files if p.is_file()})

    if not image_files:
        # Missing entirely — distinct from all-zero stub. Caller (e.g. the
        # phase23_one_shot_runner reference_tb step) may have written a
        # zero stub into sim/, but if no image is present anywhere in
        # input/otp / fpga / synth, the spec-declared payload regions
        # cannot be loaded at runtime → hardware will reply with X-state
        # or zeros and the verdict byte will FAIL.
        waiver_n = _waiver_count(project)
        if waiver_n >= 1:
            print(f"[PASS_WITH_WAIVER] otp_image_nonzero_check: "
                  f"L11/L4 declares payload OTP regions but no image is "
                  f"staged under input/otp/ / synth/ / fpga/; "
                  f"{waiver_n} waiver(s) under '{WAIVER_KEY}'.")
            return 0
        print("[FAIL] otp_image_nonzero_check: "
              "L11/L4 declares OTP payload regions "
              f"({len(payload_entries)} entries) but no .hex / .mif image "
              "is staged under input/otp/ / synth/ / fpga/. "
              "Hardware will read X-state / zeros at fetch time and the "
              "host-tester verdict will deterministically FAIL. "
              "Fix: stage a real vendor OTP image at "
              "<project>/input/otp/<name>.hex (one byte per line, hex). "
              f"To intentionally ship without an image, add waiver "
              f"'{WAIVER_KEY}' (>= {WAIVER_MIN} chars) explaining the gap.")
        return 1

    payload_addrs = [a for a, _ in payload_entries]
    failures: List[str] = []
    images_checked: List[str] = []
    for f in image_files:
        img = _read_hex_image(f)
        if img is None or len(img) == 0:
            failures.append(
                f"{_rel(f, project)}: parse failed or empty")
            continue
        images_checked.append(f"{_rel(f, project)} ({len(img)} bytes)")
        if not _check_image_nonzero_at(img, payload_addrs):
            sample = ", ".join(f"{a:#x}" for a in payload_addrs[:5])
            failures.append(
                f"{_rel(f, project)}: ALL ZEROS at payload addresses "
                f"[{sample}{'...' if len(payload_addrs) > 5 else ''}]"
            )

    if not failures:
        print(f"[PASS] otp_image_nonzero_check: "
              f"{len(images_checked)} OTP image(s) checked, "
              f"all carry non-zero values at payload addresses "
              f"({len(payload_addrs)} addr(s) checked per image). "
              f"Images: {'; '.join(images_checked[:3])}"
              + ("..." if len(images_checked) > 3 else ""))
        return 0

    waiver_n = _waiver_count(project)
    if waiver_n >= len(failures):
        print(f"[PASS_WITH_WAIVER] otp_image_nonzero_check: "
              f"{len(failures)} all-zero image(s) but {waiver_n} waiver(s) "
              f"under '{WAIVER_KEY}'.")
        return 0

    print(f"[FAIL] otp_image_nonzero_check: "
          f"{len(failures)}/{len(image_files)} OTP image(s) are all-zero "
          f"at L11/L4-declared payload addresses. "
          f"This is typically the all-zero stub the phase23_one_shot_runner "
          f"writes when no real OTP image exists in input/otp/. "
          f"Hardware will deterministically return all-zero ID bytes "
          f"and host-tester verdict will FAIL.\n"
          f"Failures:")
    for fl in failures[:5]:
        print(f"  - {fl}")
    if len(failures) > 5:
        print(f"  ... +{len(failures)-5} more")
    print(f"Fix: stage real vendor OTP data — replace the zero stub at "
          f"input/otp/<name>.hex with bytes derived from your spec "
          f"(e.g. input/docs/<OTP-table>.xlsx + L11.otp_bytes[].value). "
          f"To intentionally ship a zero image, add waiver "
          f"'{WAIVER_KEY}' (one per failing file, "
          f">={WAIVER_MIN} chars).")
    return 1


if __name__ == "__main__":
    sys.exit(main())
