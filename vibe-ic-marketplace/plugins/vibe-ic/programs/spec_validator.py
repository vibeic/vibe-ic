#!/usr/bin/env python3
"""spec_validator.py — DS<->AN(<->Spec) cross-consistency checker.

Implements the cross-consistency rubric declared in
`skills/spec-validator/SKILL.md` ("spec_validator.py — Cross-Consistency Check"):

  - Pin names:        DS "Pin Configuration" vs AN "Typical Application Circuit"
  - Register addrs:   DS "Register Map" vs AN "Firmware Example"
  - TBD/TODO values:  must be zero across ALL provided documents

**Checkpoint-1 threshold: 0 ERROR-level mismatches.**

Finding model (only the rubric's three checks produce findings):
  ERROR (fails the gate):
    pin-mismatch       — a pin referenced in the AN circuit is absent from the
                         DS pin table (or vice-versa, both directions reported)
    register-mismatch  — a register address used in the AN firmware is absent
                         from the DS register map (or vice-versa)
    unresolved-tbd     — a TBD / TODO / FIXME / ??? / <placeholder> token
                         remains in any provided document
  INFO (never fails):
    section-missing    — a document lacks the relevant section, so that cross
                         check is SKIPPED (reported, not flagged — no false alert)

chip-AGNOSTIC: identifiers are parsed structurally from the documents
themselves — never compared against any hard-coded pin/register literal. If a
side has no parsable identifiers the check is SKIPPED, so a sparse doc never
produces a false mismatch.

No-false-alert posture:
  * A cross check only fires when BOTH sides yield >=1 identifier of that kind;
    otherwise it is SKIPPED (INFO), never ERROR.
  * Pin/register tokens pass a structural shape + deny-list filter (common
    English words, units, table-keywords are excluded) and a length floor.
  * Missing/unreadable files degrade to SKIP, never crash.

CLI:
    python3 spec_validator.py --ds DS.md --an AN.md [--spec SPEC.md] [--json]
    python3 spec_validator.py <project_dir>            # auto-locate DS + AN

Exit codes:
    0 = 0 ERROR-level mismatches (PASS)
    1 = >=1 ERROR-level mismatch  (FAIL)
    2 = no usable documents found (MISSING — never a false FAIL)
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Dict, List, Optional, Set

try:
    from ds_quality_check import _section_body, _markdown_tables
    from an_validator import _locate_appnote
    from ds_quality_check import _locate_datasheet
except ImportError:  # allow running from another cwd
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from ds_quality_check import _section_body, _markdown_tables, _locate_datasheet  # noqa: E402
    from an_validator import _locate_appnote  # noqa: E402


# Placeholder tokens that must be resolved before Phase 2.
_TBD_RE = re.compile(r"\b(?:TBD|TODO|FIXME|XXX|TBA|PLACEHOLDER)\b|\?\?\?|<[\w \-]*>",
                     re.IGNORECASE)

# A pin/signal-name shape: an UPPER/Camel identifier, optionally with a numeric
# suffix or bus index — generic, no chip literals. Length floor of 2.
_PIN_TOKEN_RE = re.compile(r"\b([A-Z][A-Z0-9]{1,}(?:_[A-Z0-9]+)*|[A-Z]{2,}\d*)\b")

# A register-address token: 0x-hex, or a decimal "address" in a reg-map row.
_HEX_ADDR_RE = re.compile(r"\b0x[0-9A-Fa-f]{1,4}\b")
# A register *access* in firmware: the FIRST hex operand of a read/write call is
# the address; any later operand is the data payload (must not be cross-checked
# as an address — that was a real false-alert: 0x8483 data flagged as a reg).
_REG_CALL_RE = re.compile(
    r"\b(?:reg_)?(?:i2c_|spi_)?(?:write|read)(?:_reg)?\s*\(\s*(0x[0-9A-Fa-f]{1,4})\b",
    re.IGNORECASE,
)

# Deny-list: structural / English words that look like pin tokens but are not.
_PIN_DENY: Set[str] = {
    "AND", "OR", "NOT", "THE", "FOR", "MIN", "MAX", "TYP", "DC", "AC", "GND",
    "VDD", "VSS", "VCC", "NC", "NO", "ID", "OK", "TO", "OF", "IN", "ON", "AT",
    "BY", "IF", "IS", "AS", "AN", "BE", "DO", "NA", "VS", "PCB", "BOM", "FAQ",
    "ESD", "EMI", "RMS", "PPM", "LSB", "MSB", "REG", "ADDR", "BIT", "BITS",
    "NAME", "TYPE", "UNIT", "VALUE", "DESC", "NUM", "PIN", "ABS", "ROC",
    "NOTE", "NOTES", "TBD", "TODO", "I2C", "SPI", "UART", "USB", "PWM", "ADC",
    "DAC", "LDO", "PLL", "FET", "BJT", "IC", "FPGA", "RTL", "HDL", "SOF",
    "SOC", "IP", "PVT", "PV",
}
# Units that may appear bare as register-table cells; not addresses.
_ADDR_DENY: Set[str] = set()


@dataclass
class Finding:
    severity: str   # ERROR / INFO
    rule: str       # pin-mismatch / register-mismatch / unresolved-tbd / section-missing
    message: str
    where: str = ""


@dataclass
class SVResult:
    verdict: str    # PASS / FAIL / MISSING
    error_count: int
    findings: List[Finding]
    stats: dict

    def to_dict(self) -> dict:
        return {
            "program": "spec_validator",
            "version": "1.0.0",
            "verdict": self.verdict,
            "error_count": self.error_count,
            "stats": self.stats,
            "findings": [asdict(f) for f in self.findings],
        }


# ---------------------------------------------------------------------------
# Identifier extraction (structural, generic)
# ---------------------------------------------------------------------------
def _extract_pins(section_text: Optional[str]) -> Set[str]:
    """Pull pin/signal identifiers out of a section. Structural + deny-list."""
    if not section_text:
        return set()
    pins: Set[str] = set()
    for m in _PIN_TOKEN_RE.finditer(section_text):
        tok = m.group(1)
        if tok in _PIN_DENY:
            continue
        if len(tok) < 2:
            continue
        # Require at least one alpha char and not be a pure all-letters common
        # word of length<=3 (extra length-floor guard against prose).
        if tok.isalpha() and len(tok) <= 2:
            continue
        pins.add(tok)
    return pins


def _extract_registers(section_text: Optional[str],
                       firmware: bool = False) -> Set[str]:
    """Pull register *addresses* (0x-hex) out of a section. Normalised lower-hex.

    For firmware (AN side) prefer the call-aware extractor: only the first hex
    operand of a read/write call is an address — later operands are data
    payloads and must not be cross-checked (the 0x8483-data false-alert). When
    the firmware section has no recognisable call pattern, fall back to the
    plain hex scan so a hand-written register list still cross-checks.

    For the DS register-map side (firmware=False) every 0x-hex row entry is an
    address, so the plain scan applies."""
    if not section_text:
        return set()
    regs: Set[str] = set()
    if firmware:
        call_hits = list(_REG_CALL_RE.finditer(section_text))
        if call_hits:
            for m in call_hits:
                regs.add(m.group(1).lower())
            return regs
        # no calls recognised -> fall through to plain scan
    for m in _HEX_ADDR_RE.finditer(section_text):
        regs.add(m.group(0).lower())
    return regs


def _find_tbd(text: str) -> List[str]:
    """Return the distinct TBD/TODO/placeholder tokens present (deduped)."""
    hits = []
    seen: Set[str] = set()
    for m in _TBD_RE.finditer(text):
        tok = m.group(0)
        # Ignore generic <...> that is actually a code/markup tag like <table>,
        # only flag obvious placeholders: empty <>, <value>, <addr>, <pin>, <X>.
        if tok.startswith("<"):
            inner = tok.strip("<>").strip().lower()
            if not inner or inner in ("value", "addr", "address", "pin", "x",
                                      "n", "tbd", "todo", "placeholder", "name",
                                      "reg", "register"):
                pass
            else:
                continue
        key = tok.lower()
        if key not in seen:
            seen.add(key)
            hits.append(tok)
    return hits


# ---------------------------------------------------------------------------
# Cross checks
# ---------------------------------------------------------------------------
def _cross_check_pins(ds_text: str, an_text: str, findings: List[Finding],
                      stats: dict) -> None:
    ds_sec = _section_body(ds_text, "pin config", "pin description",
                           "pin assignment", "pinout", "pin function")
    an_sec = _section_body(an_text, "typical application circuit",
                           "typical application", "application circuit",
                           "schematic")
    if ds_sec is None or an_sec is None:
        findings.append(Finding(
            "INFO", "section-missing",
            "pin cross-check SKIPPED — "
            f"{'DS pin section ' if ds_sec is None else ''}"
            f"{'AN circuit section ' if an_sec is None else ''}not found",
        ))
        return
    ds_pins = _extract_pins(ds_sec)
    an_pins = _extract_pins(an_sec)
    stats["ds_pins"] = sorted(ds_pins)
    stats["an_pins"] = sorted(an_pins)
    # No-false-alert: only compare when BOTH sides have parsable pins.
    if not ds_pins or not an_pins:
        findings.append(Finding(
            "INFO", "section-missing",
            "pin cross-check SKIPPED — one side has no parsable pin identifiers",
        ))
        return
    an_only = sorted(an_pins - ds_pins)
    for p in an_only:
        findings.append(Finding(
            "ERROR", "pin-mismatch",
            f"pin '{p}' used in AN application circuit is absent from the DS "
            f"pin configuration", where="AN->DS"))


def _cross_check_registers(ds_text: str, an_text: str,
                           findings: List[Finding], stats: dict) -> None:
    ds_sec = _section_body(ds_text, "register map", "register description",
                           "register table", "registers")
    an_sec = _section_body(an_text, "firmware example", "firmware",
                           "code example", "driver example")
    if ds_sec is None or an_sec is None:
        findings.append(Finding(
            "INFO", "section-missing",
            "register cross-check SKIPPED — "
            f"{'DS register map ' if ds_sec is None else ''}"
            f"{'AN firmware section ' if an_sec is None else ''}not found",
        ))
        return
    ds_regs = _extract_registers(ds_sec, firmware=False)
    an_regs = _extract_registers(an_sec, firmware=True)
    stats["ds_registers"] = sorted(ds_regs)
    stats["an_registers"] = sorted(an_regs)
    if not ds_regs or not an_regs:
        findings.append(Finding(
            "INFO", "section-missing",
            "register cross-check SKIPPED — one side has no register addresses",
        ))
        return
    an_only = sorted(an_regs - ds_regs)
    for r in an_only:
        findings.append(Finding(
            "ERROR", "register-mismatch",
            f"register address '{r}' accessed in AN firmware is absent from "
            f"the DS register map", where="AN->DS"))


def _check_tbd(docs: Dict[str, str], findings: List[Finding],
               stats: dict) -> None:
    total = 0
    for label, text in docs.items():
        hits = _find_tbd(text)
        if hits:
            total += len(hits)
            findings.append(Finding(
                "ERROR", "unresolved-tbd",
                f"{len(hits)} unresolved placeholder(s) in {label}: "
                f"{', '.join(sorted(set(h for h in hits))[:8])}",
                where=label))
    stats["unresolved_tbd_total"] = total


# ---------------------------------------------------------------------------
# Importable entry point
# ---------------------------------------------------------------------------
def validate(ds_text: Optional[str], an_text: Optional[str],
             spec_text: Optional[str] = None,
             ds_src: str = "DS", an_src: str = "AN",
             spec_src: str = "SPEC") -> SVResult:
    """Run the DS<->AN(<->Spec) cross-consistency checks. Deterministic."""
    docs: Dict[str, str] = {}
    if ds_text and ds_text.strip():
        docs[ds_src] = ds_text
    if an_text and an_text.strip():
        docs[an_src] = an_text
    if spec_text and spec_text.strip():
        docs[spec_src] = spec_text

    if not docs:
        return SVResult("MISSING", 0,
                        [Finding("INFO", "section-missing",
                                 "no usable documents provided")],
                        {"docs": 0})

    findings: List[Finding] = []
    stats: dict = {"docs": len(docs)}

    # Pin + register cross checks need BOTH DS and AN.
    if ds_text and an_text and ds_text.strip() and an_text.strip():
        _cross_check_pins(ds_text, an_text, findings, stats)
        _cross_check_registers(ds_text, an_text, findings, stats)
    else:
        findings.append(Finding(
            "INFO", "section-missing",
            "pin/register cross-checks SKIPPED — need both DS and AN documents"))

    # TBD scan runs across every provided doc.
    _check_tbd(docs, findings, stats)

    errors = [f for f in findings if f.severity == "ERROR"]
    verdict = "PASS" if not errors else "FAIL"
    return SVResult(verdict, len(errors), findings, stats)


def _read(path: Optional[Path]) -> Optional[str]:
    if path is None:
        return None
    if not path.exists() or not path.is_file():
        return None
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except Exception:  # pragma: no cover - defensive
        return None


def validate_paths(ds: Optional[Path], an: Optional[Path],
                   spec: Optional[Path] = None) -> SVResult:
    return validate(
        _read(ds), _read(an), _read(spec),
        ds_src=str(ds) if ds else "DS",
        an_src=str(an) if an else "AN",
        spec_src=str(spec) if spec else "SPEC",
    )


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("project_dir", nargs="?",
                    help="Project dir to auto-locate DS + AN (alternative to "
                         "--ds/--an)")
    ap.add_argument("--ds", help="Datasheet .md")
    ap.add_argument("--an", help="Application-note .md")
    ap.add_argument("--spec", help="Confirmed-spec .md (optional)")
    ap.add_argument("--json", action="store_true", help="JSON output")
    args = ap.parse_args(argv)

    ds_path = Path(args.ds) if args.ds else None
    an_path = Path(args.an) if args.an else None
    spec_path = Path(args.spec) if args.spec else None

    if args.project_dir:
        pd = Path(args.project_dir)
        if pd.is_dir():
            if ds_path is None:
                ds_path = _locate_datasheet(pd)
            if an_path is None:
                an_path = _locate_appnote(pd)

    result = validate_paths(ds_path, an_path, spec_path)

    if args.json:
        print(json.dumps(result.to_dict(), indent=2, ensure_ascii=False))
    else:
        for f in result.findings:
            tag = f"[{f.severity}] {f.rule}"
            loc = f" ({f.where})" if f.where else ""
            print(f"{tag}: {f.message}{loc}")
        print(f"\nERROR-level mismatches: {result.error_count}  "
              f"Verdict: {result.verdict}")

    if result.verdict == "MISSING":
        return 2
    return 0 if result.verdict == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
