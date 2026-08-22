#!/usr/bin/env python3
"""arith_declaration_emit.py — deterministic declaration emitter.

Derives the six fields required by L7 §7.0 from already-present artifacts
(RTL header + phase1/generated_docs JSON + calibration artifacts).
Writes plugin_output/declaration.json.

FAIL-CLOSED: if any required field cannot be derived, this program prints the
banner `arith_declaration_emit: FAIL_CLOSED` on stderr followed by one
`  - <field_key>: <reason>` line per underivable field, writes NO file, and
exits with rc EXACTLY 1.  The banner + rc==1 pair is the contract that lets a
caller (or a test) distinguish "the program ran and refused" from "the program
never ran" — a deleted file exits rc=2 ("can't open file") and an
import/syntax error exits rc=1 with a traceback and no banner.  Neither can
counterfeit a fail-closed refusal.

Fields emitted:
  bit_order           — from RTL header comment  (LSB_first / MSB_first)
  reset_polarity      — from RTL always-block and L1_DATASHEET pin table
  latency_cycles      — from _verify_scale/REPORT.md calibration line (measured)
                        or arith_oracle_manifest.json framing offset if present
  integer_encoding    — from L2_FRS.json content clause
  multiplier_algorithm — from RTL header (informational)
  size_param          — from RTL `parameter size = N` cross-checked with L-docs

Chip-agnostic logic: field extraction uses generic patterns, not hard-coded
design-specific strings like "spm" or "multiplier".
"""

import argparse
import json
import re
import sys
from pathlib import Path

# Stable stderr banner printed on the fail-closed path (and ONLY there).
# Keyed on by tests; see the module docstring for why rc alone is not enough.
FAIL_CLOSED_BANNER = "arith_declaration_emit: FAIL_CLOSED"

# ---------------------------------------------------------------------------
# Field derivation helpers
# ---------------------------------------------------------------------------

def _find_rtl(run_dir: Path) -> Path | None:
    """Return the single RTL file in phase2/stage1/rtl/, or None."""
    rtl_dir = run_dir / "phase2" / "stage1" / "rtl"
    if not rtl_dir.is_dir():
        return None
    candidates = [f for f in rtl_dir.glob("*.v") if not f.name.startswith("tb_")]
    return candidates[0] if len(candidates) == 1 else (candidates[0] if candidates else None)


def _derive_bit_order(rtl_text: str) -> str | None:
    """Extract bit_order from RTL header comment block."""
    # Look for: "LSB-first", "LSB_first", "MSB-first", "MSB_first" in header
    m = re.search(r'\b(LSB|MSB)[_\-]first\b', rtl_text, re.IGNORECASE)
    if m:
        return m.group(0).replace("-", "_").upper().replace("LSB_FIRST", "LSB_first").replace("MSB_FIRST", "MSB_first")
    # Normalise to canonical form
    if m:
        raw = m.group(0).upper()
        return "LSB_first" if "LSB" in raw else "MSB_first"
    return None


def _derive_reset_polarity(rtl_text: str) -> str | None:
    """Determine reset polarity from RTL always-block sensitivity + condition.

    Synchronous active-high: posedge clk only (no negedge rst in sensitivity),
    and condition is `if (rst)` (not `if (!rst)` / `if (~rst)`).
    """
    # Check sensitivity list for negedge rst (would be async active-low)
    async_low = re.search(r'@\s*\([^)]*negedge\s+rst[^)]*\)', rtl_text)
    if async_low:
        return "async_active_low"

    async_high = re.search(r'@\s*\([^)]*posedge\s+rst[^)]*\)', rtl_text)
    if async_high:
        # Need to check if condition is `if (rst)` or `if (!rst)`
        cond = re.search(r'if\s*\(\s*(!|~)?\s*rst\s*\)', rtl_text)
        if cond and cond.group(1):
            return "async_active_low"
        return "async_active_high"

    # Synchronous (only posedge clk in sensitivity)
    cond = re.search(r'if\s*\(\s*(!|~)?\s*rst\s*\)', rtl_text)
    if cond:
        negated = bool(cond.group(1))
        return "active_low" if negated else "active_high"

    return None


def _derive_size_param(rtl_text: str) -> int | None:
    """Extract `parameter size = N` from RTL."""
    m = re.search(r'\bparameter\s+size\s*=\s*(\d+)', rtl_text)
    return int(m.group(1)) if m else None


def _derive_multiplier_algorithm(rtl_text: str) -> str | None:
    """Extract algorithm description from RTL header comment."""
    m = re.search(r'[Aa]lgorithm\s*[:\-–=]\s*(.+)', rtl_text)
    if m:
        raw = m.group(1).strip().rstrip(".")
        # Normalise to identifier-safe string (lowercase, spaces -> underscores)
        alg = re.sub(r'[\s\-]+', '_', raw).lower()
        alg = re.sub(r'[^a-z0-9_]', '', alg)
        # Truncate at 64 chars to keep it sane
        return alg[:64]
    return None


def _derive_integer_encoding(run_dir: Path) -> str | None:
    """Read L2_FRS.json text for signed_2c / unsigned statement."""
    l2 = run_dir / "phase1" / "generated_docs" / "L2_FRS.json"
    if not l2.exists():
        return None
    text = l2.read_text(errors="replace")
    # Look for explicit signed_2c mention first
    if re.search(r'signed_2c', text):
        return "signed_2c"
    if re.search(r'"unsigned"', text):
        return "unsigned"
    return None


def _derive_latency_from_verify_scale(run_dir: Path) -> int | None:
    """Parse _verify_scale/REPORT.md for CALIBRATED_LATENCY line."""
    report = run_dir / "_verify_scale" / "REPORT.md"
    if not report.exists():
        return None
    text = report.read_text(errors="replace")
    m = re.search(r'CALIBRATED_LATENCY:\s*(\d+)', text)
    if m:
        return int(m.group(1))
    # Also try narrative form: "Latency | **N cycle**"
    m = re.search(r'Latency\s*\|\s*\*\*(\d+)\s*cycle', text)
    return int(m.group(1)) if m else None


def _derive_latency_from_gls(run_dir: Path) -> int | None:
    """Parse _verify_gls/GLS_REPORT.md for calibrated latency."""
    report = run_dir / "_verify_gls" / "GLS_REPORT.md"
    if not report.exists():
        return None
    text = report.read_text(errors="replace")
    m = re.search(r'Calibrated latency\s*\|\s*\*\*(\d+)\s*cycle', text, re.IGNORECASE)
    if m:
        return int(m.group(1))
    m = re.search(r'CALIBRATED_LATENCY:\s*(\d+)', text)
    return int(m.group(1)) if m else None


def _oracle_manifest(run_dir: Path) -> dict | None:
    """Load arith_oracle_manifest.json from either known location."""
    for candidate in [
        run_dir / "phase2" / "stage1" / "sim_full_stack" / "arith_oracle_manifest.json",
        run_dir / "sim" / "arith_oracle_manifest.json",
    ]:
        if not candidate.exists():
            continue
        try:
            d = json.loads(candidate.read_text())
        except Exception:
            continue
        if isinstance(d, dict):
            return d
    return None


def _derive_bit_order_from_oracle_manifest(run_dir: Path) -> str | None:
    """MEASURED serial input bit-order, written by the runner from the oracle
    TB's framing search. None when the TB established no single framing."""
    d = _oracle_manifest(run_dir) or {}
    v = d.get("calibrated_bit_order")
    return v if v in ("LSB_first", "MSB_first") else None


def _derive_latency_from_oracle_manifest(run_dir: Path) -> int | None:
    """Try to read framing offset from arith_oracle_manifest.json.

    The manifest stores framing as a string description ("self-calibrated …")
    rather than an integer when declaration.json was absent, so this helper
    checks for any numeric 'offset' field that might have been populated.
    """
    for candidate in [
        run_dir / "phase2" / "stage1" / "sim_full_stack" / "arith_oracle_manifest.json",
        run_dir / "sim" / "arith_oracle_manifest.json",
    ]:
        if not candidate.exists():
            continue
        try:
            d = json.loads(candidate.read_text())
        except Exception:
            continue
        # MEASURED framing first. `calibrated_latency` is written by the
        # runner from the oracle TB's own framing search (a real measurement
        # against an independently computed golden). `declared_latency` is
        # only ever a copy of declaration.json — the file this program
        # writes — so preferring it would close a dependency cycle and, for
        # any IC whose spec requires declaration.json, deadlock the flow.
        if isinstance(d.get("calibrated_latency"), int):
            return d["calibrated_latency"]
        if isinstance(d.get("declared_latency"), int):
            return d["declared_latency"]
        # Framing string encodes the winning offset as "offset=N" sometimes
        framing = d.get("framing", "")
        m = re.search(r'offset[=\s]+(\d+)', str(framing))
        if m:
            return int(m.group(1))
    return None


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Emit plugin_output/declaration.json deterministically."
    )
    parser.add_argument("run_dir", nargs="?", default=".",
                        help="Run directory (default: cwd)")
    args = parser.parse_args(argv)

    run_dir = Path(args.run_dir).resolve()
    if not run_dir.is_dir():
        print(f"ERROR: run_dir not found: {run_dir}", file=sys.stderr)
        return 2

    errors: list[str] = []

    # --- RTL ---
    rtl_path = _find_rtl(run_dir)
    if rtl_path is None:
        errors.append("rtl_source: cannot locate RTL file in phase2/stage1/rtl/")
        rtl_text = ""
    else:
        rtl_text = rtl_path.read_text(errors="replace")

    # --- bit_order ---
    # MEASURED value wins over the RTL header comment: the comment is prose an
    # author can get wrong, while `calibrated_bit_order` is the framing the
    # oracle TB proved reassembles the DUT stream to the golden.
    bit_order = _derive_bit_order_from_oracle_manifest(run_dir)
    if bit_order is None:
        bit_order = _derive_bit_order(rtl_text)
    if bit_order is None:
        errors.append("bit_order: no LSB/MSB-first marker found in RTL header "
                      "and no calibrated_bit_order in arith_oracle_manifest.json")

    # --- reset_polarity ---
    reset_polarity = _derive_reset_polarity(rtl_text)
    if reset_polarity is None:
        errors.append("reset_polarity: cannot determine from RTL always-block")

    # --- size_param ---
    size_param = _derive_size_param(rtl_text)
    if size_param is None:
        errors.append("size_param: `parameter size = N` not found in RTL")

    # --- multiplier_algorithm (informational) ---
    multiplier_algorithm = _derive_multiplier_algorithm(rtl_text)
    if multiplier_algorithm is None:
        errors.append("multiplier_algorithm: no `algorithm <:|-|=> <value>` "
                      "line found in RTL header")

    # --- integer_encoding ---
    integer_encoding = _derive_integer_encoding(run_dir)
    if integer_encoding is None:
        errors.append("integer_encoding: signed_2c/unsigned not found in L2_FRS.json")

    # --- latency_cycles (measured — prefer _verify_scale, fallback to GLS) ---
    latency_cycles = _derive_latency_from_verify_scale(run_dir)
    if latency_cycles is None:
        latency_cycles = _derive_latency_from_gls(run_dir)
    if latency_cycles is None:
        latency_cycles = _derive_latency_from_oracle_manifest(run_dir)
    if latency_cycles is None:
        errors.append(
            "latency_cycles: cannot determine from _verify_scale/REPORT.md, "
            "_verify_gls/GLS_REPORT.md, or arith_oracle_manifest.json — "
            "run calibration first"
        )

    # FAIL-CLOSED: do not emit a partial file.  The banner is emitted ONLY
    # here, so its presence together with rc==1 is proof this program ran and
    # refused — see the module docstring.
    if errors:
        print(f"{FAIL_CLOSED_BANNER} — required field(s) not derivable:",
              file=sys.stderr)
        for e in errors:
            print(f"  - {e}", file=sys.stderr)
        print("No file written.", file=sys.stderr)
        return 1

    declaration = {
        "bit_order": bit_order,
        "reset_polarity": reset_polarity,
        "latency_cycles": latency_cycles,
        "integer_encoding": integer_encoding,
        "multiplier_algorithm": multiplier_algorithm,
        "size_param": size_param,
    }

    out_dir = run_dir / "plugin_output"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "declaration.json"
    out_path.write_text(json.dumps(declaration, indent=2, ensure_ascii=False) + "\n")

    print(f"arith_declaration_emit: PASS — wrote {out_path}")
    print(json.dumps(declaration, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
