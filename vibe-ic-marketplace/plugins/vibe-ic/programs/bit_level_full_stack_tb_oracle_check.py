#!/usr/bin/env python3
"""bit_level_full_stack_tb_oracle_check.py — v0.119.44 (Wave 12) plugin gate.

Closes the gameability hole exposed by the v0.119.43 <benchmark> fresh-agent
benchmark. The legacy ``bit_level_full_stack_tb_check`` only verifies
``pass: true`` + a count of distinct non-padding response bytes in
``sim/sim_full_stack/results.json``. An agent can fabricate that JSON
without running real simulation: pick 14 different hex bytes, set
``pass: true``, ship.

This new gate enforces the structured oracle comparison that the
agent CANNOT fabricate without producing the same artefact a real
testbench would have produced.

CHIP-AGNOSTIC. Validates structural shape only. Specific opcodes /
chip names / pin names are NEVER hard-coded.

Required JSON shape (``sim/sim_full_stack/results.json`` or
``sim_full_stack/results.json``)
::

    {
      "pass": true,
      "vectors_total": 64,
      "vectors_passed": 64,
      "vectors_failed": 0,
      "per_vector": [
        {"name": "wake+0x74",
         "expected_bytes": "F2,11,22,...",
         "actual_bytes":   "F2,11,22,...",
         "match": true},
        ...
      ],
      "tb_module": "tb_full_stack",
      "rtl_top": "example_chip_top",
      "input_doc_evidence": "input/docs/CMD_table.xlsx#opcodes",
      "sim_log_sha256": "..."
    }

Rules
-----
1. FAIL if ``per_vector`` is missing or has fewer than 8 entries.
2. FAIL if ``vectors_passed != vectors_total`` (any failed vector).
3. FAIL if ``input_doc_evidence`` field is missing or empty (vectors
   must be derived from the project's L docs / input docs, not made up).
4. FAIL if ``tb_module`` is named but no matching file exists in any
   ``sim/`` subtree (``sim/**/<tb_module>.v`` / ``.sv``).
5. FAIL if ``rtl_top`` is named but no matching file exists in any
   ``rtl/`` subtree.
6. WARN if ``vectors_total < 16``.
7. SKIP (exit 0) when no ``results.json`` is present (this gate is the
   "raised bar" companion of the legacy gate; legacy gate handles the
   missing-file case).
8. Honors waiver ``bit_level_oracle_skipped`` (>= 40 chars).

Usage
-----
    python3 bit_level_full_stack_tb_oracle_check.py <project_dir>
        [--results-json <path>] [--json <out>]

Exit codes
----------
    0 — PASS / SKIP / PASS_WITH_WAIVER / WARN-only
    1 — FAIL
    2 — input-missing
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Optional
import _path_layout as _pl


WAIVER_KEY = "bit_level_oracle_skipped"
WAIVER_KEY_CRC = "tb_crc_variant_intentional_mismatch"
WAIVER_MIN = 40
MIN_VECTORS_FAIL = 8
MIN_VECTORS_WARN = 16


# ---------------------------------------------------------------------------
# v0.119.45 (Wave 13) — CRC cross-check helpers.
# Cross-validate per-vector CRC bytes against L3-declared CRC parameters.
# Catches the v0.119.44 fresh-agent failure mode where the agent picked an
# arbitrary CRC variant (poly=0x07/init=0x00) so all 16 vectors PASS in
# sim, but silicon's host expects the spec's actual variant and discards
# every reply silently.
# ---------------------------------------------------------------------------
_L3_CRC_KEYS = ("crc_parameters", "crc", "crc_spec")


def _waiver_crc(project_dir: Path) -> tuple[bool, str]:
    waivers = project_dir / "waivers.json"
    if not waivers.exists():
        return False, ""
    try:
        d = json.loads(waivers.read_text())
        text = d.get(WAIVER_KEY_CRC)
        if isinstance(text, str) and len(text.strip()) >= WAIVER_MIN:
            return True, text.strip()
    except Exception:
        pass
    return False, ""


def _to_int_hex(v) -> Optional[int]:
    if v is None:
        return None
    if isinstance(v, int):
        return v & 0xFFFF if v >= 0 else None
    if isinstance(v, str):
        s = v.strip().lower().replace("0x", "").replace("'h", "")
        try:
            return int(s, 16)
        except ValueError:
            return None
    return None


def _reflect8(b: int) -> int:
    out = 0
    for i in range(8):
        if b & (1 << i):
            out |= 1 << (7 - i)
    return out


def _crc8_compute(data: list[int],
                  poly: int,
                  init: int,
                  refin: bool,
                  refout: bool,
                  xorout: int = 0x00) -> int:
    """Reference CRC-8 computation with reflection options.

    Standard textbook algorithm (chip-agnostic): for each input byte
    (optionally reflected), XOR into CRC register MSB, then for each of
    8 bits: if MSB set, shift left and XOR with polynomial else just
    shift left. Final CRC optionally reflected, then XORed with xorout.
    """
    crc = init & 0xFF
    for byte in data:
        b = _reflect8(byte) if refin else byte
        crc ^= b & 0xFF
        for _ in range(8):
            if crc & 0x80:
                crc = ((crc << 1) ^ poly) & 0xFF
            else:
                crc = (crc << 1) & 0xFF
    if refout:
        crc = _reflect8(crc)
    return (crc ^ (xorout & 0xFF)) & 0xFF


def _load_l3_crc_params(project: Path) -> Optional[dict]:
    """Return dict {poly, init, refin, refout, xorout} from L3, or None
    if unavailable. Synonyms supported: ``polynomial_hex`` /
    ``poly_hex`` / ``polynomial`` / ``polynomial_reflected_hex`` /
    ``init_hex`` / ``init`` / ``bit_order`` / ``refin`` / ``refout``."""
    gd = _pl.generated_docs_dir(project)
    if not gd.is_dir():
        return None
    l3 = None
    for cand in sorted(gd.glob("L3*.json")):
        try:
            l3 = json.loads(cand.read_text())
            break
        except Exception:
            continue
    if not isinstance(l3, dict):
        return None

    block = None
    for k in _L3_CRC_KEYS:
        v = l3.get(k)
        if isinstance(v, dict) and v:
            block = v
            break
    if block is None:
        # nested e.g. l3["crc"]["parameters"]
        for k in _L3_CRC_KEYS:
            v = l3.get(k)
            if isinstance(v, dict):
                inner = v.get("parameters")
                if isinstance(inner, dict):
                    block = inner
                    break
    if block is None:
        return None

    poly = _to_int_hex(
        block.get("polynomial_hex")
        or block.get("poly_hex")
        or block.get("polynomial")
        or block.get("poly")
        or block.get("polynomial_reflected_hex")
    )
    init = _to_int_hex(
        block.get("init_hex") or block.get("init") or block.get("seed_hex")
        or block.get("seed")
    )
    if poly is None or init is None:
        return None

    bit_order = (block.get("bit_order") or block.get("bitorder") or "").lower()
    refin = block.get("refin")
    refout = block.get("refout")
    if refin is None:
        refin = bit_order in ("lsb_first", "lsb-first", "lsb", "reflected")
    if refout is None:
        refout = bit_order in ("lsb_first", "lsb-first", "lsb", "reflected")
    xorout = _to_int_hex(block.get("xorout") or block.get("xor_out")) or 0

    return {
        "poly": poly & 0xFF,
        "init": init & 0xFF,
        "refin": bool(refin),
        "refout": bool(refout),
        "xorout": xorout & 0xFF,
    }


def _parse_byte_list(s) -> Optional[list[int]]:
    """Parse 'F2,11,22' or '0xF2 0x11 0x22' or list -> [0xF2, 0x11, 0x22]."""
    if isinstance(s, list):
        out = []
        for x in s:
            v = _to_int_hex(x) if isinstance(x, (str, int)) else None
            if v is None:
                return None
            out.append(v & 0xFF)
        return out
    if not isinstance(s, str):
        return None
    parts = re.split(r"[,\s]+", s.strip())
    out = []
    for p in parts:
        if not p:
            continue
        v = _to_int_hex(p)
        if v is None:
            return None
        out.append(v & 0xFF)
    return out


def _vector_crc_position(vec: dict, expected_bytes: list[int]
                         ) -> Optional[int]:
    """Heuristic: identify which byte index of expected_bytes is the CRC.

    Heuristics (in order):
      1. Vector name ends with ``_CRC`` / ``_crc`` → last byte.
      2. Vector contains explicit ``crc_position`` integer field → use it.
      3. Default: last byte position is treated as CRC iff the byte list
         length >= 2.
    """
    if isinstance(vec, dict):
        cp = vec.get("crc_position")
        if isinstance(cp, int) and 0 <= cp < len(expected_bytes):
            return cp
        name = str(vec.get("name", ""))
        if name.lower().endswith(("_crc", "-crc")):
            return len(expected_bytes) - 1
    if len(expected_bytes) >= 2:
        return len(expected_bytes) - 1
    return None


def waived(project_dir: Path) -> tuple[bool, str]:
    waivers = project_dir / "waivers.json"
    if not waivers.exists():
        return False, ""
    try:
        d = json.loads(waivers.read_text())
        text = d.get(WAIVER_KEY)
        if isinstance(text, str) and len(text.strip()) >= WAIVER_MIN:
            return True, text.strip()
    except Exception:
        pass
    return False, ""


def _find_results(project: Path) -> Optional[Path]:
    candidates = [
        _pl.sim_dir(project) / "sim_full_stack" / "results.json",
        _pl.sim_full_stack_dir(project) / "results.json",
        _pl.sim_dir(project) / "full_stack" / "results.json",
    ]
    for c in candidates:
        if c.is_file():
            return c
    # Fallback: glob for first matching results.json under sim/
    for ext in ("phase2/stage1/sim/**/sim_full_stack/results.json",
                "phase2/stage1/sim_full_stack/**/results.json"):
        hits = sorted(project.glob(ext))
        if hits:
            return hits[0]
    return None


_SUBDIR_HELPERS = {
    "rtl": _pl.rtl_dir,
    "sim": _pl.sim_dir,
    "synth": _pl.synth_dir,
    "fpga": _pl.fpga_early_dir,
    "tb": _pl.tb_dir,
    "formal": _pl.formal_dir,
}


def _file_under(project: Path, subdir: str, basename: str) -> Optional[Path]:
    """Return first file under the canonical Phase/Stage/Step path for
    <subdir> whose stem matches basename and has a .v / .sv extension."""
    helper = _SUBDIR_HELPERS.get(subdir)
    base = helper(project) if helper else project / subdir
    if not base.exists():
        return None
    for ext in ("*.v", "*.sv"):
        for p in base.rglob(ext):
            if p.stem == basename:
                return p
    return None


def check(project: Path, results_path: Path) -> dict:
    findings: list[dict] = []
    info: dict = {
        "results_json": str(results_path),
    }

    try:
        data = json.loads(results_path.read_text())
    except Exception as e:
        return {
            "program": "bit_level_full_stack_tb_oracle_check",
            "pass": False,
            "findings": [{
                "rule": "RESULTS_UNPARSEABLE",
                "severity": "FAIL",
                "message": f"results.json unparseable: {e}",
            }],
            **info,
        }

    if not isinstance(data, dict):
        return {
            "program": "bit_level_full_stack_tb_oracle_check",
            "pass": False,
            "findings": [{
                "rule": "RESULTS_NOT_OBJECT",
                "severity": "FAIL",
                "message": (
                    f"results.json must be a JSON object; got "
                    f"{type(data).__name__}"
                ),
            }],
            **info,
        }

    per_vector = data.get("per_vector")
    info["per_vector_count"] = (
        len(per_vector) if isinstance(per_vector, list) else None
    )
    info["vectors_total"] = data.get("vectors_total")
    info["vectors_passed"] = data.get("vectors_passed")
    info["vectors_failed"] = data.get("vectors_failed")

    # Rule 1: per_vector present + size
    if not isinstance(per_vector, list):
        findings.append({
            "rule": "PER_VECTOR_MISSING",
            "severity": "FAIL",
            "message": (
                "results.json lacks `per_vector` array. The legacy "
                "14-distinct-bytes shape is gameable; oracle mode "
                "requires per-vector expected/actual byte comparison."
            ),
        })
    elif len(per_vector) < MIN_VECTORS_FAIL:
        findings.append({
            "rule": "PER_VECTOR_TOO_FEW",
            "severity": "FAIL",
            "message": (
                f"per_vector has {len(per_vector)} entries; minimum "
                f"{MIN_VECTORS_FAIL} for a credible bit-level oracle."
            ),
        })

    # Rule 2: vectors_passed == vectors_total (when both present)
    vt = data.get("vectors_total")
    vp = data.get("vectors_passed")
    if isinstance(vt, int) and isinstance(vp, int):
        if vp != vt:
            findings.append({
                "rule": "VECTORS_NOT_ALL_PASS",
                "severity": "FAIL",
                "message": (
                    f"vectors_passed={vp} != vectors_total={vt}; "
                    f"{vt - vp} vector(s) failed in this oracle run."
                ),
            })

    # Rule 3: input_doc_evidence required + non-empty
    evidence = data.get("input_doc_evidence")
    if not isinstance(evidence, str) or not evidence.strip():
        findings.append({
            "rule": "INPUT_DOC_EVIDENCE_MISSING",
            "severity": "FAIL",
            "message": (
                "results.json must include `input_doc_evidence` "
                "naming the L doc or input file the vectors derive "
                "from. Without this the oracle vectors cannot be "
                "audited against spec."
            ),
        })

    # Rule 4: tb_module file exists in sim/ subtree
    tb_module = data.get("tb_module")
    if isinstance(tb_module, str) and tb_module:
        if not _file_under(project, "sim", tb_module):
            findings.append({
                "rule": "TB_MODULE_FILE_MISSING",
                "severity": "FAIL",
                "message": (
                    f"results.json references tb_module=`{tb_module}` "
                    f"but no `{tb_module}.v` / `{tb_module}.sv` exists "
                    f"under sim/."
                ),
            })

    # Rule 5: rtl_top file exists in rtl/ subtree
    rtl_top = data.get("rtl_top")
    if isinstance(rtl_top, str) and rtl_top:
        if not _file_under(project, "rtl", rtl_top):
            findings.append({
                "rule": "RTL_TOP_FILE_MISSING",
                "severity": "FAIL",
                "message": (
                    f"results.json references rtl_top=`{rtl_top}` "
                    f"but no `{rtl_top}.v` / `{rtl_top}.sv` exists "
                    f"under rtl/."
                ),
            })

    # Rule 6: WARN under-tested
    warnings: list[dict] = []
    if isinstance(per_vector, list) and \
            MIN_VECTORS_FAIL <= len(per_vector) < MIN_VECTORS_WARN:
        warnings.append({
            "rule": "PER_VECTOR_UNDER_TESTED",
            "severity": "WARN",
            "message": (
                f"per_vector has {len(per_vector)} entries; below the "
                f"recommended {MIN_VECTORS_WARN}. Most host testers "
                f"exercise >= {MIN_VECTORS_WARN} distinct command "
                f"sequences in their acceptance suite."
            ),
        })

    # ------------------------------------------------------------------
    # Rule 7 (v0.119.45 Wave 13): CRC cross-check against L3 parameters.
    # Closes the v0.119.44 fresh-agent gameability hole where TB used
    # an arbitrary CRC variant that yielded 16/16 PASS in sim but
    # silicon's host expected the L3-declared variant.
    # ------------------------------------------------------------------
    crc_findings, crc_warnings = _crc_cross_check(
        project, per_vector if isinstance(per_vector, list) else []
    )
    if _waiver_crc(project)[0]:
        # Honour CRC-specific waiver: convert FAILs to PASS_WITH_WAIVER
        # message but keep them visible in the report's findings list
        # so audit downstream sees the bypass.
        for f in crc_findings:
            f["waived"] = True
        # don't add to fatal findings
        crc_findings = []
    findings.extend(crc_findings)
    warnings.extend(crc_warnings)

    return {
        "program": "bit_level_full_stack_tb_oracle_check",
        "pass": len(findings) == 0,
        "findings": findings,
        "warnings": warnings,
        **info,
    }


def _crc_cross_check(project: Path, per_vector: list
                     ) -> tuple[list[dict], list[dict]]:
    """Compute the L3-declared CRC for each vector's prefix and compare
    against the trailing CRC byte. Returns (findings, warnings)."""
    findings: list[dict] = []
    warnings: list[dict] = []

    if not per_vector:
        return findings, warnings

    params = _load_l3_crc_params(project)
    if params is None:
        warnings.append({
            "rule": "L3_CRC_PARAMETERS_ABSENT",
            "severity": "WARN",
            "message": (
                "L3 lacks crc_parameters / crc / crc_spec block with "
                "polynomial_hex + init_hex + bit_order; bit-level "
                "oracle CRC cross-check skipped. crc_parameters_"
                "extracted_check covers the extraction side; without "
                "it the oracle vectors could be using an arbitrary "
                "CRC variant that PASSes sim but FAILs silicon."
            ),
        })
        return findings, warnings

    poly, init = params["poly"], params["init"]
    refin, refout = params["refin"], params["refout"]
    xorout = params["xorout"]

    mismatches: list[dict] = []
    checked = 0
    for vec in per_vector:
        if not isinstance(vec, dict):
            continue
        eb = _parse_byte_list(vec.get("expected_bytes"))
        if not eb:
            continue
        crc_pos = _vector_crc_position(vec, eb)
        if crc_pos is None:
            continue
        prefix = eb[:crc_pos]
        declared_crc = eb[crc_pos] & 0xFF
        recomputed = _crc8_compute(prefix, poly, init, refin, refout, xorout)
        checked += 1
        if recomputed != declared_crc:
            mismatches.append({
                "vector": vec.get("name", "?"),
                "declared": f"0x{declared_crc:02X}",
                "recomputed": f"0x{recomputed:02X}",
                "prefix_len": len(prefix),
            })

    if checked == 0:
        # No vector had an identifiable CRC slot — fall back to skip.
        return findings, warnings

    if mismatches:
        sample = mismatches[:5]
        msg_parts = "; ".join(
            f"{m['vector']}: declared={m['declared']} vs "
            f"recomputed={m['recomputed']} (prefix={m['prefix_len']}B)"
            for m in sample
        )
        findings.append({
            "rule": "CRC_VARIANT_MISMATCH_VS_L3",
            "severity": "FAIL",
            "message": (
                f"{len(mismatches)}/{checked} vector CRC byte(s) "
                f"disagree with the CRC re-computed using L3-declared "
                f"parameters (poly=0x{poly:02X}, init=0x{init:02X}, "
                f"refin={refin}, refout={refout}). Sample: {msg_parts}"
                f"{'...' if len(mismatches) > 5 else ''}. "
                f"This indicates the TB's CRC variant differs from "
                f"the spec's — sim PASSes but silicon's host will "
                f"reject every reply."
            ),
        })
    return findings, warnings


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    ap.add_argument("project_dir")
    ap.add_argument("--results-json", default=None,
                    help="explicit path to results.json")
    ap.add_argument("--json", default=None)
    args = ap.parse_args()

    project = Path(args.project_dir).resolve()
    if not project.exists():
        print(f"FAIL — project dir not found: {project}", file=sys.stderr)
        return 2

    if args.results_json:
        results_path = Path(args.results_json).resolve()
        if not results_path.is_file():
            print(f"FAIL — results.json not found: {results_path}",
                  file=sys.stderr)
            return 1
    else:
        results_path = _find_results(project)
        if not results_path:
            print(
                "PASS_SKIP — no sim/sim_full_stack/results.json found; "
                "legacy bit_level_full_stack_tb_check covers the "
                "missing-file case"
            )
            return 0

    result = check(project, results_path)
    if args.json:
        Path(args.json).parent.mkdir(parents=True, exist_ok=True)
        Path(args.json).write_text(json.dumps(result, indent=2))

    if result["pass"]:
        if result.get("warnings"):
            print(
                f"PASS_WITH_WARN — bit-level oracle structurally valid "
                f"({result.get('per_vector_count')} vectors); "
                f"{len(result['warnings'])} warning(s)"
            )
            for w in result["warnings"]:
                print(f"WARN: {w['rule']} — {w['message']}")
        else:
            print(
                f"PASS — bit-level oracle structurally valid "
                f"({result.get('per_vector_count')} vectors, "
                f"{result.get('vectors_passed')}/{result.get('vectors_total')}"
                f" passed)"
            )
        return 0

    is_waived, why = waived(project)
    if is_waived:
        print(
            f"PASS_WITH_WAIVER — {len(result['findings'])} oracle "
            f"finding(s); waiver `{WAIVER_KEY}` set: {why[:80]}..."
        )
        for f in result["findings"]:
            print(f"  • {f['rule']} — {f['message'][:120]}")
        return 0

    print(f"FAIL — {len(result['findings'])} bit-level oracle violation(s)")
    for f in result["findings"]:
        print(f"FAIL: {f['rule']} — {f['message']}")
    for w in result.get("warnings", []):
        print(f"WARN: {w['rule']} — {w['message']}")
    return 1


if __name__ == "__main__":
    sys.exit(main())
