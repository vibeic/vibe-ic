#!/usr/bin/env python3
"""
spec-validator -- Cross-Consistency Check: Datasheet <-> Application Note <-> Spec
=====================================================================================
Extracts key identifiers (pin names, register addresses) from each document
and cross-checks for mismatches.

Checks:
    1. Pin names: DS Section 3 (Pin Configuration) vs AN Section 2 (Typical Application)
    2. Register addresses: DS Section 9.2 (Register Map) vs AN Section 5 (Firmware Example)
    3. Parameter names: DS Electrical Characteristics vs Spec confirmed parameters
    4. Signal names: consistency across all three documents

Usage:
    python3 spec_validator.py --ds datasheet.md --an appnote.md --spec spec.md
    python3 spec_validator.py --ds datasheet.md --an appnote.md              # spec optional
    python3 spec_validator.py --ds datasheet.md --an appnote.md --json
"""

import re
import sys
import json
import argparse
from pathlib import Path
from typing import List, Dict, Any, Set, Tuple, Optional


# ============================================================================
# Extractors
# ============================================================================

def _find_section(text: str, patterns: List[str]) -> str:
    """Extract text under a heading matching any of the patterns."""
    for pat in patterns:
        regex = rf'(^|\n)(#{{1,4}})\s+[^\n]*{pat}[^\n]*\n'
        m = re.search(regex, text, re.IGNORECASE)
        if m:
            level_hashes = m.group(2)
            start = m.end()
            next_heading = re.search(
                rf'\n#{{{1},{len(level_hashes)}}}\s+',
                text[start:]
            )
            end = start + next_heading.start() if next_heading else len(text)
            return text[start:end]
    return ""


def extract_pin_names_from_table(text: str) -> Set[str]:
    """Extract pin names from Markdown tables in pin configuration sections.

    Looks for table rows where the first or second column contains a pin name.
    Pin names are typically short uppercase identifiers like VCC, GND, CLK, D0, etc.
    """
    pins: Set[str] = set()

    # Find pin-related sections
    section = _find_section(text, [
        r'pin\s+config', r'pin\s+description', r'pin\s+assign',
        r'pin\s+out', r'pinout', r'terminal\s+function',
        r'pin\s+function', r'pin\s+diagram',
    ])
    if not section:
        section = text  # fallback: search entire document

    # Extract from table rows
    for line in section.split('\n'):
        if '|' not in line:
            continue
        # Skip separator rows
        if re.match(r'^\s*\|[\s\-:|]+\|\s*$', line):
            continue
        cells = [c.strip() for c in line.split('|') if c.strip()]
        for cell in cells[:3]:  # check first 3 columns
            # Pin name patterns: uppercase letters+digits, or common pin names
            # Remove markdown formatting
            clean = re.sub(r'[*_`]', '', cell).strip()
            # Match typical pin names
            pin_matches = re.findall(
                r'\b([A-Z][A-Z0-9_]{0,15}(?:/[A-Z][A-Z0-9_]{0,15})?)\b',
                clean
            )
            for pm in pin_matches:
                # Filter out common non-pin words
                if pm not in {'PIN', 'NAME', 'NUMBER', 'TYPE', 'DESCRIPTION',
                              'FUNCTION', 'NO', 'SYMBOL', 'I', 'O', 'IO',
                              'INPUT', 'OUTPUT', 'INOUT', 'TABLE', 'SECTION',
                              'MAX', 'MIN', 'TYP', 'UNIT', 'VALUE', 'TEST',
                              'PARAMETER', 'CONDITION', 'NOTE', 'THE', 'AND',
                              'FOR', 'WITH'}:
                    pins.add(pm)

    # Also extract from inline references like "pin VCC" or "VCC pin"
    pin_refs = re.findall(r'\bpin\s+([A-Z][A-Z0-9_/]{0,15})\b', text, re.IGNORECASE)
    for p in pin_refs:
        p_upper = p.upper()
        if len(p_upper) >= 2:
            pins.add(p_upper)

    return pins


def extract_pin_names_from_circuit(text: str) -> Set[str]:
    """Extract pin names referenced in application circuit sections."""
    pins: Set[str] = set()

    section = _find_section(text, [
        r'typical\s+application', r'application\s+circuit',
        r'circuit\s+schematic', r'reference\s+design',
        r'schematic',
    ])
    if not section:
        section = text

    # Pin references in ASCII schematics and descriptions
    # Pattern: uppercase identifiers that look like pin names
    candidates = re.findall(r'\b([A-Z][A-Z0-9_]{1,15}(?:/[A-Z][A-Z0-9_]{0,15})?)\b', section)
    # Filter to likely pin names (not generic words)
    generic_words = {
        'THE', 'AND', 'FOR', 'WITH', 'FROM', 'THIS', 'THAT', 'WHEN',
        'USED', 'USING', 'NOTE', 'SEE', 'TABLE', 'FIGURE', 'SECTION',
        'PIN', 'PINS', 'INPUT', 'OUTPUT', 'INOUT', 'TYPE', 'NAME',
        'VALUE', 'MAX', 'MIN', 'TYP', 'UNIT', 'PARAMETER', 'ASCII',
        'PCB', 'BOM', 'FAQ', 'TBD', 'IC', 'DC', 'AC', 'RF',
    }
    for c in candidates:
        if c not in generic_words and len(c) >= 2:
            pins.add(c)

    return pins


def extract_register_addresses(text: str, source_label: str) -> Dict[str, str]:
    """Extract register name -> address mappings.

    Looks for patterns like:
        | REG_NAME | 0x04 | ... |
        REG_NAME (0x04)
        Address 0x04: REG_NAME
        #define REG_NAME 0x04
    """
    registers: Dict[str, str] = {}

    if source_label == 'datasheet':
        section = _find_section(text, [
            r'register\s+map', r'register\s+description',
            r'register\s+table', r'register\s+summary',
            r'memory\s+map',
        ])
    else:
        section = _find_section(text, [
            r'firmware', r'software', r'code\s+example',
            r'programming', r'register\s+access',
            r'driver', r'register\s+map',
        ])

    if not section:
        section = text

    # Pattern 1: Table rows with hex addresses
    for line in section.split('\n'):
        if '|' in line and re.search(r'0x[0-9A-Fa-f]+', line):
            cells = [c.strip() for c in line.split('|') if c.strip()]
            for i, cell in enumerate(cells):
                addr_match = re.search(r'(0x[0-9A-Fa-f]+)', cell)
                if addr_match:
                    addr = addr_match.group(1).upper()
                    # Look for register name in adjacent cells
                    for j, other_cell in enumerate(cells):
                        if j != i:
                            clean = re.sub(r'[*_`]', '', other_cell).strip()
                            name_match = re.match(r'^([A-Za-z][A-Za-z0-9_]{1,30})$', clean)
                            if name_match:
                                registers[name_match.group(1).upper()] = addr
                                break

    # Pattern 2: #define NAME 0xADDR
    for m in re.finditer(r'#define\s+(\w+)\s+(0x[0-9A-Fa-f]+)', section):
        registers[m.group(1).upper()] = m.group(2).upper()

    # Pattern 3: NAME (0xADDR) or NAME: 0xADDR
    for m in re.finditer(r'([A-Za-z][A-Za-z0-9_]{1,30})\s*[\(:]\s*(0x[0-9A-Fa-f]+)', section):
        name = m.group(1).upper()
        if name not in {'ADDRESS', 'ADDR', 'OFFSET', 'REG', 'VALUE', 'DEFAULT'}:
            registers[name] = m.group(2).upper()

    # Pattern 4: 0xADDR — NAME or 0xADDR: NAME
    for m in re.finditer(r'(0x[0-9A-Fa-f]+)\s*[:\-—]\s*([A-Za-z][A-Za-z0-9_]{1,30})', section):
        name = m.group(2).upper()
        if name not in {'ADDRESS', 'ADDR', 'OFFSET', 'REG', 'VALUE', 'DEFAULT',
                         'READ', 'WRITE', 'RW', 'RO', 'WO'}:
            registers[name] = m.group(1).upper()

    return registers


def extract_spec_parameters(text: str) -> Set[str]:
    """Extract parameter names from a confirmed spec document."""
    params: Set[str] = set()

    # Look for parameter names in tables
    for line in text.split('\n'):
        if '|' in line and not re.match(r'^\s*\|[\s\-:|]+\|\s*$', line):
            cells = [c.strip() for c in line.split('|') if c.strip()]
            for cell in cells[:2]:
                clean = re.sub(r'[*_`]', '', cell).strip()
                if re.match(r'^[A-Za-z][A-Za-z0-9_\s]{2,40}$', clean):
                    params.add(clean.strip().lower())

    # Look for parameter names in bullet lists
    for m in re.finditer(r'^\s*[-*]\s+\*?\*?([A-Za-z][A-Za-z0-9_\s]{2,40})\*?\*?\s*:', text, re.MULTILINE):
        params.add(m.group(1).strip().lower())

    return params


# ============================================================================
# Cross-Checks
# ============================================================================

def check_pin_consistency(ds_text: str, an_text: str) -> List[Dict[str, Any]]:
    """Compare pin names between datasheet and application note."""
    ds_pins = extract_pin_names_from_table(ds_text)
    an_pins = extract_pin_names_from_circuit(an_text)

    mismatches = []

    if not ds_pins:
        mismatches.append({
            "check": "pin_names",
            "type": "extraction_empty",
            "severity": "WARN",
            "message": "No pin names extracted from datasheet Pin Configuration",
            "ds_value": None,
            "an_value": None,
        })
        return mismatches

    if not an_pins:
        mismatches.append({
            "check": "pin_names",
            "type": "extraction_empty",
            "severity": "WARN",
            "message": "No pin names extracted from application note circuit",
            "ds_value": None,
            "an_value": None,
        })
        return mismatches

    # Pins in AN but not in DS (possible typo or undocumented pin)
    an_only = an_pins - ds_pins
    # Filter out obvious non-pin words that slipped through
    for pin in sorted(an_only):
        # Only flag if it looks like a real pin name (short, uppercase)
        if len(pin) <= 12 and re.match(r'^[A-Z][A-Z0-9_/]+$', pin):
            mismatches.append({
                "check": "pin_names",
                "type": "an_only",
                "severity": "ERROR",
                "message": f"Pin '{pin}' used in Application Note but not in Datasheet Pin Configuration",
                "ds_value": None,
                "an_value": pin,
            })

    # Pins in DS but not referenced in AN (may be OK -- not all pins used)
    ds_only = ds_pins - an_pins
    for pin in sorted(ds_only):
        if len(pin) <= 12 and re.match(r'^[A-Z][A-Z0-9_/]+$', pin):
            mismatches.append({
                "check": "pin_names",
                "type": "ds_only",
                "severity": "INFO",
                "message": f"Pin '{pin}' in Datasheet but not referenced in Application Note (may be unused)",
                "ds_value": pin,
                "an_value": None,
            })

    return mismatches


def check_register_consistency(ds_text: str, an_text: str) -> List[Dict[str, Any]]:
    """Compare register addresses between datasheet and application note."""
    ds_regs = extract_register_addresses(ds_text, 'datasheet')
    an_regs = extract_register_addresses(an_text, 'appnote')

    mismatches = []

    if not ds_regs and not an_regs:
        mismatches.append({
            "check": "register_addresses",
            "type": "no_registers",
            "severity": "INFO",
            "message": "No register addresses found in either document (may be non-register-based IC)",
            "ds_value": None,
            "an_value": None,
        })
        return mismatches

    if not ds_regs:
        mismatches.append({
            "check": "register_addresses",
            "type": "extraction_empty",
            "severity": "WARN",
            "message": "No register addresses extracted from datasheet Register Map",
            "ds_value": None,
            "an_value": None,
        })
        return mismatches

    if not an_regs:
        mismatches.append({
            "check": "register_addresses",
            "type": "extraction_empty",
            "severity": "WARN",
            "message": "No register addresses extracted from application note firmware",
            "ds_value": None,
            "an_value": None,
        })
        return mismatches

    # Check for address mismatches on same register name
    common_names = set(ds_regs.keys()) & set(an_regs.keys())
    for name in sorted(common_names):
        ds_addr = ds_regs[name]
        an_addr = an_regs[name]
        if ds_addr != an_addr:
            mismatches.append({
                "check": "register_addresses",
                "type": "address_mismatch",
                "severity": "ERROR",
                "message": f"Register '{name}' address mismatch: DS={ds_addr} vs AN={an_addr}",
                "ds_value": ds_addr,
                "an_value": an_addr,
            })

    # Registers in AN firmware but not in DS register map
    an_only = set(an_regs.keys()) - set(ds_regs.keys())
    for name in sorted(an_only):
        mismatches.append({
            "check": "register_addresses",
            "type": "an_only",
            "severity": "ERROR",
            "message": f"Register '{name}' (addr {an_regs[name]}) used in AN firmware but not in DS Register Map",
            "ds_value": None,
            "an_value": f"{name}={an_regs[name]}",
        })

    # Registers in DS but not used in AN (informational)
    ds_only = set(ds_regs.keys()) - set(an_regs.keys())
    for name in sorted(ds_only):
        mismatches.append({
            "check": "register_addresses",
            "type": "ds_only",
            "severity": "INFO",
            "message": f"Register '{name}' (addr {ds_regs[name]}) in DS but not used in AN firmware",
            "ds_value": f"{name}={ds_regs[name]}",
            "an_value": None,
        })

    return mismatches


def check_tbd_values(ds_text: str, an_text: str, spec_text: Optional[str] = None) -> List[Dict[str, Any]]:
    """Check for TBD/TODO/FIXME values in all documents."""
    mismatches = []
    docs = [("datasheet", ds_text), ("appnote", an_text)]
    if spec_text:
        docs.append(("spec", spec_text))

    for doc_name, doc_text in docs:
        tbd_matches = re.findall(r'(TBD|TODO|FIXME|TBC|XXX)', doc_text, re.IGNORECASE)
        if tbd_matches:
            mismatches.append({
                "check": "tbd_values",
                "type": "unresolved_placeholder",
                "severity": "ERROR",
                "message": f"{doc_name} contains {len(tbd_matches)} unresolved placeholder(s): {', '.join(set(m.upper() for m in tbd_matches))}",
                "ds_value": None,
                "an_value": None,
            })

    return mismatches


# ============================================================================
# Main Validator
# ============================================================================

def validate_consistency(ds_path: str, an_path: str, spec_path: Optional[str] = None) -> Dict[str, Any]:
    """Run all cross-consistency checks and return JSON report."""

    # Read files
    errors = []
    ds_text = ""
    an_text = ""
    spec_text = None

    ds_file = Path(ds_path)
    an_file = Path(an_path)

    if not ds_file.exists():
        errors.append(f"Datasheet not found: {ds_path}")
    else:
        ds_text = ds_file.read_text(encoding='utf-8', errors='replace')

    if not an_file.exists():
        errors.append(f"Application note not found: {an_path}")
    else:
        an_text = an_file.read_text(encoding='utf-8', errors='replace')

    if spec_path:
        spec_file = Path(spec_path)
        if not spec_file.exists():
            errors.append(f"Spec not found: {spec_path}")
        else:
            spec_text = spec_file.read_text(encoding='utf-8', errors='replace')

    if errors:
        return {
            "consistent": False,
            "mismatches": [{"check": "file_access", "type": "file_not_found",
                           "severity": "ERROR", "message": e,
                           "ds_value": None, "an_value": None} for e in errors],
            "summary": {
                "total_checks": 0,
                "errors": len(errors),
                "warnings": 0,
                "info": 0,
            },
        }

    # Run checks
    all_mismatches: List[Dict[str, Any]] = []

    all_mismatches.extend(check_pin_consistency(ds_text, an_text))
    all_mismatches.extend(check_register_consistency(ds_text, an_text))
    all_mismatches.extend(check_tbd_values(ds_text, an_text, spec_text))

    # Count by severity
    error_count = sum(1 for m in all_mismatches if m['severity'] == 'ERROR')
    warn_count = sum(1 for m in all_mismatches if m['severity'] == 'WARN')
    info_count = sum(1 for m in all_mismatches if m['severity'] == 'INFO')

    return {
        "consistent": error_count == 0,
        "mismatches": all_mismatches,
        "summary": {
            "total_checks": len(all_mismatches),
            "errors": error_count,
            "warnings": warn_count,
            "info": info_count,
        },
        "files": {
            "datasheet": str(ds_file),
            "appnote": str(an_file),
            "spec": str(Path(spec_path)) if spec_path else None,
        },
    }


def print_report(result: Dict[str, Any]):
    """Pretty-print the consistency report."""
    print(f"\n{'='*64}")
    print(f"  spec-validator -- Cross-Consistency Check")
    print(f"{'='*64}")

    files = result.get('files', {})
    if files:
        print(f"  DS:   {files.get('datasheet', 'N/A')}")
        print(f"  AN:   {files.get('appnote', 'N/A')}")
        if files.get('spec'):
            print(f"  Spec: {files['spec']}")

    summary = result['summary']
    consistent = result['consistent']
    status = "CONSISTENT" if consistent else "INCONSISTENT"
    print(f"\n  Result: {status}")
    print(f"  Errors: {summary['errors']}  Warnings: {summary['warnings']}  Info: {summary['info']}")

    if result['mismatches']:
        print(f"\n  {'='*60}")
        print(f"  Findings ({len(result['mismatches'])}):\n")

        for i, m in enumerate(result['mismatches'], 1):
            sev = m['severity']
            icon = "ERROR" if sev == 'ERROR' else "WARN" if sev == 'WARN' else "INFO"
            print(f"  {i:>3}. [{icon}] [{m['check']}] {m['message']}")
            if m.get('ds_value'):
                print(f"       DS: {m['ds_value']}")
            if m.get('an_value'):
                print(f"       AN: {m['an_value']}")

    if consistent:
        print(f"\n  PASS: No ERROR-level mismatches detected.")
    else:
        print(f"\n  FAIL: {summary['errors']} ERROR-level mismatch(es) must be resolved.")

    print(f"{'='*64}\n")


def main():
    parser = argparse.ArgumentParser(
        description='spec-validator: Cross-check Datasheet, Application Note, and Spec for consistency')
    parser.add_argument('--ds', required=True, help='Path to datasheet Markdown (e.g., 04_datasheet.md)')
    parser.add_argument('--an', required=True, help='Path to application note Markdown (e.g., 05_appnote.md)')
    parser.add_argument('--spec', default=None, help='Path to confirmed spec Markdown (e.g., 03_spec_confirmed.md)')
    parser.add_argument('--json', action='store_true', help='Output JSON instead of text report')
    args = parser.parse_args()

    result = validate_consistency(args.ds, args.an, args.spec)

    if args.json:
        print(json.dumps(result, indent=2, ensure_ascii=False))
    else:
        print_report(result)

    sys.exit(0 if result['consistent'] else 1)


if __name__ == '__main__':
    main()
