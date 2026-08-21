#!/usr/bin/env python3
"""
tristate_self_rx_mask_check.py — Self-RX masking audit for tristate/open-drain
tristate bus pins.

Rule (derived from v052 rtl/pad_ctrl.v:8):

    When a module drives an inout/tri bus pin ``W`` through an output-enable
    ``W_oe`` companion, the module (or downstream hookup) MUST present a
    masked-RX tap of the form

        assign W_rx_msk = W_oe ? 1'b1 : W_rx;   // or equivalent ternary

    so the RX chain doesn't sample the local drive as an external symbol.

Static check (IC-agnostic):

  1. Scan every ``.v``/``.sv`` file for ``inout`` ports. For each inout port
     name ``W``, look for the triple ``(W, W_oe, W_<tap>)`` across the whole
     RTL set, where ``<tap>`` is one of ``rx``, ``in``, ``din``, ``sample``.
  2. FAIL when all three exist AND every assignment whose LHS matches
     ``W_<tap>`` (or ``W_<tap>_msk``/``W_<tap>_m``) has a direct RHS of
     ``W`` with NO ``W_oe ?`` ternary guard anywhere in the rtl set that
     does carry that guard.

Edge cases:
  * No inout ports found → exit 0 ("no inout ports, nothing to check").
  * Inout present but no ``<W>_oe`` signal → not a driven bus, skip.
  * Masked version present anywhere (``W_oe ? 1'b1 : W_tap``) → PASS.

Outputs:
  * Human-readable findings on stdout.
  * Optional machine-readable ``--json`` report.

Exit codes:
  * 0 = PASS (no findings, or out of scope)
  * 1 = at least one FAIL finding
  * 2 = argument / IO error

#496 — THE PUBLISHED DENOMINATOR WAS THE WRONG FIELD
---------------------------------------------------
#492 recorded this gate as ``inout_ports: []`` on all 107 tracked ``rtl``
directories under ``benchmark-data``. Re-measured for #496 by calling ``audit``
directly: it collects **24 inout ports across 4 of those 107 directories**. The
empty list was never the reason for the zero.

The real reason was one step further in and was never printed: every one of
those 24 ports was dropped by ``_has_oe_signal``, which recognised exactly ONE
spelling of an output-enable companion — ``<name>_oe``. The 4 directories then
reported ``checked: 0`` with no indication that anything had been dropped, so
the zero read as "no inout ports exist". It is the exact failure mode this gate
exists to prevent, turned inward: a probe that cannot see is indistinguishable
from a subject that is not there.

TWO CHANGES, both about seeing rather than judging:

1. ``_OE_SUFFIXES`` — the companion is now discovered under the spellings real
   RTL uses (``_oe``, ``_oeb``, ``_oen``, ``_oe_n``, ``_en``, ``_dir``, ``_t``,
   ``_out_en``, ``_drv``, ``_ts``). Witness in the tracked tree:
   ``benchmark_external/cvdp/solved_design_db/rtl/cvdp_copilot_apb_gpio_0005.sv``
   declares ``inout wire [W-1:0] gpio``, drives it through ``gpio_dir``
   (``assign gpio[gi] = gpio_dir[gi] ? reg_dout[gi] : 1'bz;``) and taps it with
   a bare ``assign gpio_in = gpio;``. That is precisely the raw self-RX tap
   this gate was written to find, and the ``_oe``-only lookup skipped it.

2. SEVERITY TRACKS POLARITY CONFIDENCE. The masked form this rule enforces —
   ``assign W_rx_msk = W_oe ? 1'b1 : W_rx;`` — assumes an ACTIVE-HIGH enable.
   For ``_oeb`` / ``_oen`` the correct mask puts the arms the other way round,
   and ``_dir`` is a configuration register rather than a per-cycle enable. A
   static reader cannot settle that, so a raw tap found through a non-``_oe``
   companion is reported at WARNING with the discovered token named, and only
   the ``_oe`` form — the one the rule was derived from — keeps ERROR. Widening
   what is EXAMINED must not silently widen what is FAILED.

Every port that is skipped now records why, so ``checked: 0`` can never again be
mistaken for ``inouts: []``.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, asdict, field
from pathlib import Path
from typing import List, Dict, Optional, Tuple

import _gate_denominator as GD

# #496 — one unit of this gate's denominator, in the gate's own terms.
_DENOM_UNIT = "driven tristate buses (inout port + output-enable companion)"


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------
@dataclass
class Finding:
    severity: str           # ERROR, WARNING, INFO
    category: str           # MISSING_MASK, RAW_TAP_ASSIGN
    message: str
    file: str = ""
    line: int = 0
    signal: str = ""
    details: str = ""


# ---------------------------------------------------------------------------
# Regexes (compiled once)
# ---------------------------------------------------------------------------
_INOUT_RE = re.compile(
    r"\binout\s+(?:wire|reg|logic|tri|tri0|tri1)?\s*(?:\[[^\]]+\]\s*)?([A-Za-z_]\w*)",
    re.IGNORECASE,
)
_IDENT_RE = re.compile(r"\b[A-Za-z_]\w*\b")

# Suffixes we consider as "RX tap" variants.
_TAP_SUFFIXES: Tuple[str, ...] = ("rx", "in", "din", "sample")

# #496 — output-enable companion spellings, most specific first so that
# `foo_oe_n` is not reported as `foo_oe`. The first entry is the ACTIVE-HIGH
# form the masked-tap rule was derived from; only it carries enough polarity
# certainty to justify an ERROR (see the module docstring).
_OE_SUFFIXES: Tuple[str, ...] = (
    "oe_n", "oeb", "oen", "out_en", "outen", "tri_en", "drv", "dir",
    "oe", "en", "ts", "t",
)
_ACTIVE_HIGH_OE_SUFFIX = "oe"


def _find_v_files(rtl_dir: Path) -> List[Path]:
    return sorted(
        [p for p in rtl_dir.rglob("*") if p.is_file()
         and p.suffix.lower() in (".v", ".sv", ".vh")]
    )


def _collect_inout_names(texts: Dict[Path, str]) -> List[str]:
    """Collect every identifier declared as an inout in any scanned file."""
    names: List[str] = []
    for t in texts.values():
        for m in _INOUT_RE.finditer(t):
            nm = m.group(1)
            if nm and nm not in names:
                names.append(nm)
    return names


def _find_oe_signal(name: str, texts: Dict[Path, str]) -> Optional[str]:
    """Return the output-enable companion of ``name``, or None.

    #496 — this used to recognise only ``<name>_oe`` and returned a bool, so a
    bus driven through ``<name>_dir`` / ``<name>_oeb`` was silently dropped and
    the drop was not recorded anywhere. Returns the token so the caller can
    both name it in findings and reason about its polarity.
    """
    for suf in _OE_SUFFIXES:
        # Verilog identifiers are case-sensitive.
        pat = re.compile(r"\b" + re.escape(name) + r"_" + suf + r"\b")
        for t in texts.values():
            if pat.search(t):
                return f"{name}_{suf}"
    return None


def _has_oe_signal(name: str, texts: Dict[Path, str]) -> bool:
    """Backwards-compatible boolean form of :func:`_find_oe_signal`."""
    return _find_oe_signal(name, texts) is not None


def _find_tap_assignments(
    name: str, texts: Dict[Path, str]
) -> List[Tuple[Path, int, str, str, str]]:
    """
    Return list of (file, line_no, lhs, rhs, raw_line) for every
    ``assign <lhs> = <rhs>;`` where lhs matches ``name_<suffix>``
    (optionally followed by ``_msk`` / ``_m``).
    """
    suffix_alt = "|".join(_TAP_SUFFIXES)
    lhs_re = re.compile(
        r"^\s*assign\s+(" + re.escape(name) + r"_(" + suffix_alt + r")(?:_msk|_m)?)\s*=\s*(.+?)\s*;",
        re.IGNORECASE,
    )
    out: List[Tuple[Path, int, str, str, str]] = []
    for path, text in texts.items():
        for i, line in enumerate(text.splitlines(), start=1):
            m = lhs_re.match(line)
            if m:
                out.append((path, i, m.group(1), m.group(3), line.rstrip()))
    return out


def _rhs_has_oe_mask(rhs: str, name: str, oe_tok: str | None = None) -> bool:
    """RHS references the output-enable companion and a ternary ``?``.

    #496 — ``oe_tok`` defaults to ``<name>_oe`` so existing callers are
    unaffected, but a bus discovered through ``<name>_dir`` must have its mask
    recognised against ``<name>_dir``, not against a token that does not exist
    in the design.
    """
    tok = oe_tok or (name + "_oe")
    return ("?" in rhs) and (tok in rhs)


def audit(rtl_dir: Path) -> Tuple[List[Finding], Dict]:
    findings: List[Finding] = []

    if not rtl_dir.exists() or not rtl_dir.is_dir():
        findings.append(Finding(
            severity="ERROR",
            category="IO",
            message=f"RTL directory not found: {rtl_dir}",
        ))
        return findings, {"inouts": [], "checked": 0, "skipped": 0,
                          "skip_reasons": {}, "files_scanned": 0,
                          "oe_companions": {}}

    v_files = _find_v_files(rtl_dir)
    texts: Dict[Path, str] = {}
    for p in v_files:
        try:
            texts[p] = p.read_text(errors="replace")
        except OSError:
            # #496 — a file that could not be read is not a file that was
            # examined. Excluding it keeps the denominator honest.
            continue

    inout_names = _collect_inout_names(texts)
    # #496 — `skip_reasons` is the field whose absence let `checked: 0` be
    # mis-attributed to `inouts: []`. Every dropped port names its reason.
    summary: Dict = {"inouts": inout_names, "checked": 0, "skipped": 0,
                     "skip_reasons": {}, "files_scanned": len(texts),
                     "oe_companions": {}}

    if not inout_names:
        return findings, summary   # out-of-scope → PASS

    for w in inout_names:
        oe_tok = _find_oe_signal(w, texts)
        if oe_tok is None:
            summary["skipped"] += 1
            summary["skip_reasons"][w] = (
                "no output-enable companion found — searched for "
                + ", ".join(f"{w}_{s}" for s in _OE_SUFFIXES)
                + ". Not a driven bus (a power/analog pad or an externally "
                  "driven pin), so the self-RX masking rule does not apply.")
            continue  # no companion OE → not a driven bus, skip
        summary["checked"] += 1
        summary["oe_companions"][w] = oe_tok
        # Only the active-high `_oe` form fixes the polarity of the masked
        # shape this rule enforces; see the module docstring.
        oe_is_active_high = oe_tok == f"{w}_{_ACTIVE_HIGH_OE_SUFFIX}"

        taps = _find_tap_assignments(w, texts)
        if not taps:
            # No explicit tap assignment in RTL body; downstream may read the
            # pad directly. We don't have enough info to flag — skip.
            summary["skip_reasons"][w] = (
                f"driven bus (enable {oe_tok}) but no RX tap assignment of "
                f"the form `assign {w}_<rx|in|din|sample>[_msk|_m] = ...;` "
                "was found; the pad may be read directly downstream, which "
                "this rule cannot see.")
            continue

        # Any masked-form present anywhere?  If yes, the design HAS the
        # pattern; we still flag individual raw taps because they may
        # shadow the masked one.
        any_masked = any(_rhs_has_oe_mask(rhs, w, oe_tok)
                         for _, _, _, rhs, _ in taps)

        for path, lno, lhs, rhs, raw in taps:
            if _rhs_has_oe_mask(rhs, w, oe_tok):
                continue
            # RHS is "raw <w>" or something else. Only flag the classic
            # pitfall: `assign W_rx = W;` — i.e. RHS is bare <w>
            # (possibly with whitespace only).
            rhs_ident = rhs.strip().rstrip(";").strip()
            if rhs_ident == w:
                # #496 — ERROR only when the enable's polarity is the
                # active-high one the masked shape assumes. For `_oeb` /
                # `_oen` the correct mask has its ternary arms reversed, and
                # `_dir` is a config register rather than a cycle enable:
                # real defect or not, this reader cannot tell, so it reports
                # rather than judges.
                findings.append(Finding(
                    severity="ERROR" if oe_is_active_high else "WARNING",
                    category="RAW_TAP_ASSIGN",
                    message=(
                        f"Tap '{lhs}' is assigned directly from inout "
                        f"'{w}' with no '{oe_tok} ? ...' guard "
                        f"(self-RX may sample our own drive)."
                        + ("" if oe_is_active_high else
                           f" Reported at WARNING because the enable is "
                           f"'{oe_tok}', whose active level this static "
                           f"reader cannot determine; confirm the intended "
                           f"mask arm before treating it as a defect.")
                    ),
                    file=str(path),
                    line=lno,
                    signal=lhs,
                    details=raw.strip(),
                ))
            elif not any_masked:
                # RHS is some expression, no masked form exists anywhere.
                # Could still be fine, but warn for manual review.
                findings.append(Finding(
                    severity="WARNING",
                    category="MISSING_MASK",
                    message=(
                        f"Tap '{lhs}' assignment does not include "
                        f"'{oe_tok} ?' guard and no masked form was "
                        f"found in the RTL set."
                    ),
                    file=str(path),
                    line=lno,
                    signal=lhs,
                    details=raw.strip(),
                ))

    return findings, summary


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def _denominator(summary: Dict) -> GD.Denominator:
    checked = summary.get("checked", 0)
    inouts = summary.get("inouts", [])
    files = summary.get("files_scanned", 0)
    details = {"files_scanned": files,
               "inout_ports": inouts,
               "oe_companions": summary.get("oe_companions", {}),
               "skip_reasons": summary.get("skip_reasons", {})}
    if checked:
        return GD.Denominator(unit=_DENOM_UNIT, examined=checked,
                              considered=len(inouts), details=details)
    if files == 0:
        reason = "no readable .v/.sv/.vh file in this directory."
    elif not inouts:
        reason = (f"{files} RTL file(s) read, none declaring an `inout` port. "
                  "There is no bidirectional pin, so no self-RX tap can "
                  "exist.")
    else:
        reason = (
            f"{len(inouts)} inout port(s) declared — {', '.join(inouts[:8])}"
            f"{' ...' if len(inouts) > 8 else ''} — but none has an "
            "output-enable companion, so none is a bus this module DRIVES. "
            "See summary.skip_reasons for the per-port reason. NOTE: a "
            "non-empty inout_ports list with checked == 0 is exactly the "
            "state #492 mis-recorded as `inout_ports: []`.")
    return GD.Denominator(unit=_DENOM_UNIT, examined=0,
                          considered=len(inouts),
                          not_applicable_reason=reason, details=details)


def build_report(findings: List[Finding], rtl_dir: Path, summary: Dict) -> Dict:
    return {
        "program": "tristate_self_rx_mask_check",
        "version": "1.0.0",
        "rtl_dir": str(rtl_dir),
        "summary": GD.attach({
            "inout_ports": summary.get("inouts", []),
            "checked": summary.get("checked", 0),
            "skipped": summary.get("skipped", 0),
            "skip_reasons": summary.get("skip_reasons", {}),
            "oe_companions": summary.get("oe_companions", {}),
            "files_scanned": summary.get("files_scanned", 0),
            "findings_count": len(findings),
            "pass": not any(f.severity == "ERROR" for f in findings),
        }, _denominator(summary)),
        "findings": [asdict(f) for f in findings],
    }


def main(argv: List[str] = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Flag tristate-bus modules whose RX tap is not masked by "
            "the companion output-enable signal."
        )
    )
    parser.add_argument("--rtl-dir", required=True,
                        help="Directory containing .v / .sv RTL files")
    parser.add_argument("--json", dest="json_out", default=None,
                        help="Optional path to write machine-readable report")
    args = parser.parse_args(argv)

    rtl_dir = Path(args.rtl_dir)
    try:
        findings, summary = audit(rtl_dir)
    except OSError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 2

    report = build_report(findings, rtl_dir, summary)
    report_json = json.dumps(report, indent=2, ensure_ascii=False)

    if args.json_out:
        Path(args.json_out).parent.mkdir(parents=True, exist_ok=True)
        Path(args.json_out).write_text(report_json)

    print(report_json)

    # IO errors (missing RTL dir etc.) → exit 2 per the gate exit-code contract
    # (0 PASS / 1 FAIL / 2 input-missing).
    if any(getattr(f, "category", "") == "IO" for f in findings):
        return 2
    # "no inout ports found" is a hard PASS (not a fail).
    if not summary.get("inouts"):
        return 0
    return 0 if report["summary"]["pass"] else 1


if __name__ == "__main__":
    sys.exit(main())
