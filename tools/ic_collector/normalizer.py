#!/usr/bin/env python3
"""
Vibe-IC Design Knowledge Normalizer
=====================================
Normalizes IC design JSON files to conform to the canonical ic_schema.json.

Fixes inconsistencies:
  - vdd_min_v → basic_specs.vdd_min  (drop unit suffixes)
  - temp_min_c → basic_specs.temp_min
  - interface (string) → interfaces (list)
  - Flat spec keys → nested under basic_specs
  - register_map as list → register_map.registers[]
  - pin_configuration without pins[] → add pins[]
  - design_notes as string → [string]
  - Missing canonical fields → null

Usage:
    python3 normalizer.py normalize --file X.json          # Normalize one file (in-place)
    python3 normalizer.py normalize --file X.json --dry-run # Preview changes without writing
    python3 normalizer.py batch                            # Normalize all design JSONs on SSD2
    python3 normalizer.py batch --dry-run                  # Preview batch without writing
    python3 normalizer.py validate --file X.json           # Check conformance only
    python3 normalizer.py stats                            # Show normalization statistics
"""

import json
import os
import sys
import copy
import argparse
from pathlib import Path
from datetime import datetime

SCRIPT_DIR = Path(__file__).parent
SCHEMA_PATH = SCRIPT_DIR / "ic_schema.json"
SSD2_METADATA = Path("/mnt/2a6ff798-a964-4a91-b131-e34fd4ca66ed/ic_documents/datasheets_metadata")
LOG_FILE = SCRIPT_DIR / "normalizer.log"

# ---------------------------------------------------------------------------
# Key alias maps — canonical name is always the VALUE
# ---------------------------------------------------------------------------

# Flat top-level keys that should be moved into basic_specs
FLAT_TO_BASIC_SPECS = {
    "vdd_min_v": "vdd_min",
    "vdd_max_v": "vdd_max",
    "vdd_typ_v": "vdd_typ",
    "supply_min": "vdd_min",
    "supply_max": "vdd_max",
    "supply_typ": "vdd_typ",
    "supply_voltage_min": "vdd_min",
    "supply_voltage_max": "vdd_max",
    "operating_voltage_min": "vdd_min",
    "operating_voltage_max": "vdd_max",
    "temp_min_c": "temp_min",
    "temp_max_c": "temp_max",
    "temp_operating_min": "temp_min",
    "temp_operating_max": "temp_max",
    "operating_temp_min": "temp_min",
    "operating_temp_max": "temp_max",
    "icc_typ_ua": "icc_typ",
    "icc_max_ua": "icc_max",
    "icc_operating_typ_ua": "icc_typ",
    "icc_operating_max_ua": "icc_max",
    "supply_current_typical_uA": "icc_typ",
    "supply_current_max_uA": "icc_max",
    "icc_powerdown_typ_ua": "icc_powerdown_typ",
    "icc_powerdown_max_ua": "icc_powerdown_max",
    # Keys that already have the right name but are at the wrong level
    "pin_count": "pin_count",
    "interfaces": "interfaces",
    "packages": "packages",
    "resolution_bits": "resolution_bits",
    "freq_mhz": "freq_mhz",
    "freq_ghz": "freq_ghz",
    "sample_rate_sps": "sample_rate_sps",
    "sample_rate_ksps": "sample_rate_ksps",
    "sample_rate_msps": "sample_rate_msps",
}

# Keys inside basic_specs that need renaming (no relocation)
BASIC_SPECS_RENAMES = {
    "vdd_min_v": "vdd_min",
    "vdd_max_v": "vdd_max",
    "vdd_typ_v": "vdd_typ",
    "supply_min": "vdd_min",
    "supply_max": "vdd_max",
    "supply_typ": "vdd_typ",
    "supply_voltage_min": "vdd_min",
    "supply_voltage_max": "vdd_max",
    "operating_voltage_min": "vdd_min",
    "operating_voltage_max": "vdd_max",
    "temp_min_c": "temp_min",
    "temp_max_c": "temp_max",
    "temp_operating_c": "_special_temp_range",
    "temp_operating_min": "temp_min",
    "temp_operating_max": "temp_max",
    "operating_temp_min": "temp_min",
    "operating_temp_max": "temp_max",
    "operating_temp_c": "_special_temp_range",
    "icc_typ_ua": "icc_typ",
    "icc_max_ua": "icc_max",
    "icc_operating_typ_ua": "icc_typ",
    "icc_operating_max_ua": "icc_max",
    "supply_current_typical_uA": "icc_typ",
    "supply_current_max_uA": "icc_max",
    "icc_powerdown_typ_ua": "icc_powerdown_typ",
    "icc_powerdown_max_ua": "icc_powerdown_max",
    "interface": "interfaces",
    "package": "packages",
    "supply_voltage_v": "_special_supply_range",
}

# Register field key renames
REGISTER_FIELD_RENAMES = {
    "type": "access",
    "pointer": "address",
}

# I2C address entry renames
I2C_ADDRESS_RENAMES = {
    "addr_pin_connection": "addr_pin",
    "7bit_addr": "address_7bit",
    "address_hex": "address_7bit",
    "slave_address_hex": "address_7bit",
}

# Top-level keys that are always kept at top level (not moved into basic_specs)
TOP_LEVEL_KEEP = {
    "part_number", "manufacturer", "category", "description",
    "extracted_from", "extracted_at", "extraction_method",
    "basic_specs", "pin_configuration", "register_map",
    "i2c_addressing", "electrical_characteristics",
    "absolute_maximum_ratings", "application_info",
    "design_notes", "timing", "functional_modes", "power_modes",
    "block_diagram_description", "fields_extracted",
    # IC-specific top-level objects that should stay
    "pga_fsr_table", "mux_configurations", "series_comparison",
    "power_domains", "memory_map", "boot_configuration",
    "clock_system", "wifi_specs", "bluetooth_specs",
    "peripheral_interfaces", "security", "thermal_information",
    "analog_peripherals", "digital_interfaces",
    "datasheet_version", "datasheet_url", "source_grade",
    "license_note", "name",
}


def log(msg: str):
    ts = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    line = f"[{ts}] {msg}"
    print(line)
    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(LOG_FILE, 'a') as f:
        f.write(line + '\n')


# ---------------------------------------------------------------------------
# Normalization helpers
# ---------------------------------------------------------------------------

def ensure_list(val):
    """Ensure value is a list. Strings become single-element lists."""
    if val is None:
        return []
    if isinstance(val, str):
        return [val]
    if isinstance(val, list):
        return val
    return [val]


def parse_range_string(val):
    """Parse range strings like '2.0 to 5.5' or '-40 to 125' into (min, max)."""
    if not isinstance(val, str):
        return None
    import re
    m = re.match(r'(-?\d+\.?\d*)\s*(?:to|~|-|–)\s*(-?\d+\.?\d*)', val)
    if m:
        return float(m.group(1)), float(m.group(2))
    return None


def normalize_basic_specs_keys(specs: dict) -> dict:
    """Rename keys inside basic_specs to canonical names."""
    result = {}
    for key, val in specs.items():
        if key in BASIC_SPECS_RENAMES:
            canonical = BASIC_SPECS_RENAMES[key]

            # Handle special range keys
            if canonical == "_special_supply_range":
                rng = parse_range_string(val) if isinstance(val, str) else None
                if rng:
                    result.setdefault("vdd_min", rng[0])
                    result.setdefault("vdd_max", rng[1])
                elif isinstance(val, (int, float)):
                    result.setdefault("vdd_typ", val)
                continue

            if canonical == "_special_temp_range":
                if isinstance(val, str):
                    rng = parse_range_string(val)
                    if rng:
                        result.setdefault("temp_min", rng[0])
                        result.setdefault("temp_max", rng[1])
                elif isinstance(val, dict):
                    result.setdefault("temp_min", val.get("min"))
                    result.setdefault("temp_max", val.get("max"))
                continue

            # Don't overwrite an existing canonical value
            if canonical not in result:
                result[canonical] = val
        else:
            result[key] = val

    return result


def normalize_interfaces(specs: dict) -> dict:
    """Ensure interfaces is always a list of strings."""
    if "interfaces" in specs:
        val = specs["interfaces"]
        if isinstance(val, str):
            # Split compound strings like "I2C (up to 3.4 MHz)"
            # Keep as single item, but strip mode details for the list
            specs["interfaces"] = [val]
        elif isinstance(val, list):
            # Ensure all items are strings
            specs["interfaces"] = [str(x) for x in val]
    return specs


def normalize_packages(specs: dict) -> dict:
    """Ensure packages is always a list of strings."""
    if "packages" in specs:
        val = specs["packages"]
        if isinstance(val, str):
            specs["packages"] = [val]
        elif isinstance(val, list):
            specs["packages"] = [str(x) for x in val]
    return specs


def normalize_register_map(data: dict) -> dict:
    """Ensure register_map is an object with registers[] array."""
    if "register_map" not in data:
        return data

    rm = data["register_map"]

    # Case 1: register_map is a list → wrap it
    if isinstance(rm, list):
        data["register_map"] = {"registers": rm}
        rm = data["register_map"]

    # Case 2: register_map is a dict but lacks "registers" key
    if isinstance(rm, dict) and "registers" not in rm:
        # Check if there are register-like entries mixed in
        # (Some files have register data in other keys like "dac_register")
        # Don't destructively restructure, just add empty registers array
        rm["registers"] = []

    # Normalize register fields
    if isinstance(rm, dict) and "registers" in rm and isinstance(rm["registers"], list):
        for reg in rm["registers"]:
            if not isinstance(reg, dict):
                continue

            # Rename "pointer" → "address"
            if "pointer" in reg and "address" not in reg:
                reg["address"] = reg.pop("pointer")

            # Normalize fields within each register
            if "fields" in reg and isinstance(reg["fields"], list):
                for field in reg["fields"]:
                    if not isinstance(field, dict):
                        continue
                    # Rename "type" → "access" in register fields
                    if "type" in field and "access" not in field:
                        field["access"] = field.pop("type")

    return data


def normalize_pin_configuration(data: dict) -> dict:
    """Ensure pin_configuration has a 'pins' array."""
    if "pin_configuration" not in data:
        return data

    pc = data["pin_configuration"]

    if isinstance(pc, list):
        # If pin_configuration is itself a list, wrap it
        data["pin_configuration"] = {"pins": pc}
        pc = data["pin_configuration"]

    if isinstance(pc, dict) and "pins" not in pc:
        pc["pins"] = []

    # Also handle top-level "pins" key → move into pin_configuration
    if "pins" in data and "pin_configuration" not in data:
        pins = data.pop("pins")
        if isinstance(pins, list):
            data["pin_configuration"] = {"pins": pins, "total_pins": len(pins)}
    elif "pins" in data and "pin_configuration" in data:
        # Merge top-level pins into pin_configuration if pin_configuration.pins is empty
        pc = data["pin_configuration"]
        if isinstance(pc, dict) and not pc.get("pins"):
            pins = data.pop("pins")
            if isinstance(pins, list):
                pc["pins"] = pins

    return data


def normalize_i2c_addressing(data: dict) -> dict:
    """Normalize i2c_addressing structure."""
    # Detect alternate top-level key names
    for alt_key in ["i2c_address", "i2c_config"]:
        if alt_key in data and "i2c_addressing" not in data:
            data["i2c_addressing"] = data.pop(alt_key)

    if "i2c_addressing" not in data:
        return data

    ia = data["i2c_addressing"]
    if not isinstance(ia, dict):
        return data

    # Normalize addresses array entries
    if "addresses" in ia and isinstance(ia["addresses"], list):
        for addr in ia["addresses"]:
            if not isinstance(addr, dict):
                continue
            for old_key, new_key in I2C_ADDRESS_RENAMES.items():
                if old_key in addr and new_key not in addr:
                    addr[new_key] = addr.pop(old_key)

    # Handle full_address_table → addresses
    if "full_address_table" in ia and "addresses" not in ia:
        table = ia.pop("full_address_table")
        if isinstance(table, list):
            ia["addresses"] = table

    # Handle default_addresses → addresses
    if "default_addresses" in ia and "addresses" not in ia:
        defaults = ia.pop("default_addresses")
        if isinstance(defaults, list):
            ia["addresses"] = defaults

    return data


def normalize_design_notes(data: dict) -> dict:
    """Ensure design_notes is always a list of strings."""
    if "design_notes" not in data:
        return data

    dn = data["design_notes"]
    if isinstance(dn, str):
        data["design_notes"] = [dn]
    elif isinstance(dn, list):
        # Ensure all items are strings
        data["design_notes"] = [str(x) for x in dn]
    else:
        data["design_notes"] = []

    return data


def relocate_flat_specs(data: dict) -> dict:
    """Move flat spec-like keys from top level into basic_specs."""
    if "basic_specs" not in data:
        data["basic_specs"] = {}

    bs = data["basic_specs"]
    keys_to_remove = []

    for key in list(data.keys()):
        if key in FLAT_TO_BASIC_SPECS and key not in TOP_LEVEL_KEEP:
            canonical = FLAT_TO_BASIC_SPECS[key]
            # Don't overwrite existing basic_specs values
            if canonical not in bs:
                bs[canonical] = data[key]
            keys_to_remove.append(key)

    for key in keys_to_remove:
        del data[key]

    return data


def add_missing_fields(data: dict) -> dict:
    """Add canonical top-level fields as null if missing."""
    canonical_top_level = {
        "part_number": None,
        "manufacturer": None,
        "category": None,
        "description": None,
    }

    for key, default in canonical_top_level.items():
        if key not in data:
            data[key] = default

    # Ensure basic_specs exists
    if "basic_specs" not in data:
        data["basic_specs"] = {}

    canonical_basic = {
        "vdd_min": None,
        "vdd_typ": None,
        "vdd_max": None,
        "temp_min": None,
        "temp_max": None,
        "icc_typ": None,
        "icc_max": None,
        "resolution_bits": None,
        "interfaces": [],
        "packages": [],
        "pin_count": None,
    }

    bs = data["basic_specs"]
    for key, default in canonical_basic.items():
        if key not in bs:
            bs[key] = default

    return data


def reorder_keys(data: dict) -> dict:
    """Reorder top-level keys to match canonical schema order."""
    key_order = [
        "part_number", "manufacturer", "category", "description",
        "extracted_from", "extracted_at", "extraction_method",
        "basic_specs", "pin_configuration", "register_map",
        "i2c_addressing", "electrical_characteristics",
        "absolute_maximum_ratings", "application_info",
        "design_notes", "timing", "functional_modes",
        "power_modes", "block_diagram_description",
    ]

    ordered = {}
    # First: keys in canonical order
    for key in key_order:
        if key in data:
            ordered[key] = data[key]

    # Then: remaining keys alphabetically
    for key in sorted(data.keys()):
        if key not in ordered:
            ordered[key] = data[key]

    return ordered


# ---------------------------------------------------------------------------
# Main normalize pipeline
# ---------------------------------------------------------------------------

def normalize(data: dict) -> tuple[dict, list[str]]:
    """
    Apply all normalizations to a design JSON dict.
    Returns (normalized_data, list_of_changes_made).
    """
    original = json.dumps(data, sort_keys=True)
    changes = []
    result = copy.deepcopy(data)

    # Step 1: Relocate flat spec keys into basic_specs
    before_keys = set(result.keys())
    result = relocate_flat_specs(result)
    moved = before_keys - set(result.keys()) - TOP_LEVEL_KEEP
    if moved:
        changes.append(f"Relocated flat keys to basic_specs: {sorted(moved)}")

    # Step 2: Normalize key names inside basic_specs
    if "basic_specs" in result and isinstance(result["basic_specs"], dict):
        old_bs_keys = set(result["basic_specs"].keys())
        result["basic_specs"] = normalize_basic_specs_keys(result["basic_specs"])
        new_bs_keys = set(result["basic_specs"].keys())
        renamed = old_bs_keys - new_bs_keys
        if renamed:
            changes.append(f"Renamed basic_specs keys: {sorted(renamed)}")

    # Step 3: Ensure interfaces is a list
    if "basic_specs" in result and isinstance(result["basic_specs"], dict):
        if "interfaces" in result["basic_specs"]:
            before = result["basic_specs"]["interfaces"]
            result["basic_specs"] = normalize_interfaces(result["basic_specs"])
            if result["basic_specs"]["interfaces"] != before:
                changes.append(f"Converted interfaces to list")

    # Step 4: Ensure packages is a list
    if "basic_specs" in result and isinstance(result["basic_specs"], dict):
        if "packages" in result["basic_specs"]:
            before = result["basic_specs"]["packages"]
            result["basic_specs"] = normalize_packages(result["basic_specs"])
            if result["basic_specs"]["packages"] != before:
                changes.append(f"Converted packages to list")

    # Step 5: Normalize register_map
    had_rm = "register_map" in result
    if had_rm:
        rm_before = json.dumps(result.get("register_map"), sort_keys=True)
    result = normalize_register_map(result)
    if had_rm and json.dumps(result.get("register_map"), sort_keys=True) != rm_before:
        changes.append("Normalized register_map structure")

    # Step 6: Normalize pin_configuration
    had_pc = "pin_configuration" in result or "pins" in result
    if had_pc:
        pc_before = json.dumps(result.get("pin_configuration"), sort_keys=True)
    result = normalize_pin_configuration(result)
    if had_pc and json.dumps(result.get("pin_configuration"), sort_keys=True) != pc_before:
        changes.append("Normalized pin_configuration structure")

    # Step 7: Normalize i2c_addressing
    had_ia = any(k in result for k in ["i2c_addressing", "i2c_address", "i2c_config"])
    if had_ia:
        ia_before = json.dumps(result.get("i2c_addressing"), sort_keys=True)
    result = normalize_i2c_addressing(result)
    if had_ia and json.dumps(result.get("i2c_addressing"), sort_keys=True) != ia_before:
        changes.append("Normalized i2c_addressing structure")

    # Step 8: Normalize design_notes
    if "design_notes" in result:
        dn_before = result["design_notes"]
        result = normalize_design_notes(result)
        if result["design_notes"] != dn_before:
            changes.append("Normalized design_notes to list")

    # Step 9: Add missing canonical fields
    before_add = json.dumps(result, sort_keys=True)
    result = add_missing_fields(result)
    after_add = json.dumps(result, sort_keys=True)
    if before_add != after_add:
        changes.append("Added missing canonical fields with null defaults")

    # Step 10: Remove fields_extracted (will be recalculated)
    if "fields_extracted" in result:
        del result["fields_extracted"]
        changes.append("Removed stale fields_extracted")

    # Step 11: Recalculate fields_extracted
    meta_keys = {"part_number", "extracted_at", "extraction_method",
                 "fields_extracted", "manufacturer", "category",
                 "description", "extracted_from"}
    bs = result.get("basic_specs", {})
    filled_basic = sum(1 for k, v in bs.items()
                       if v is not None and v != [] and v != "")
    filled_top = sum(1 for k, v in result.items()
                     if k not in meta_keys and v is not None and v != [] and v != {} and v != "")
    result["fields_extracted"] = filled_basic + filled_top

    # Step 12: Reorder keys
    result = reorder_keys(result)

    return result, changes


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

def validate(data: dict) -> list[str]:
    """
    Validate a design JSON against canonical expectations.
    Returns list of issues found (empty = valid).
    """
    issues = []

    if "part_number" not in data or not data["part_number"]:
        issues.append("Missing or empty part_number")

    bs = data.get("basic_specs", {})
    if not isinstance(bs, dict):
        issues.append("basic_specs is not a dict")
        return issues

    # Check for non-canonical key names in basic_specs
    for key in bs:
        if key in BASIC_SPECS_RENAMES:
            issues.append(f"Non-canonical key in basic_specs: '{key}' → should be '{BASIC_SPECS_RENAMES[key]}'")

    # Check for flat spec keys at top level
    for key in data:
        if key in FLAT_TO_BASIC_SPECS and key not in TOP_LEVEL_KEEP:
            issues.append(f"Flat spec key at top level: '{key}' → should be in basic_specs as '{FLAT_TO_BASIC_SPECS[key]}'")

    # Check interfaces is a list
    if "interfaces" in bs and not isinstance(bs["interfaces"], list):
        issues.append(f"basic_specs.interfaces is {type(bs['interfaces']).__name__}, should be list")

    # Check packages is a list
    if "packages" in bs and not isinstance(bs["packages"], list):
        issues.append(f"basic_specs.packages is {type(bs['packages']).__name__}, should be list")

    # Check register_map structure
    rm = data.get("register_map")
    if rm is not None:
        if isinstance(rm, list):
            issues.append("register_map is a list, should be object with registers[]")
        elif isinstance(rm, dict) and "registers" not in rm:
            issues.append("register_map missing 'registers' array")

    # Check pin_configuration structure
    pc = data.get("pin_configuration")
    if pc is not None:
        if isinstance(pc, list):
            issues.append("pin_configuration is a list, should be object with pins[]")
        elif isinstance(pc, dict) and "pins" not in pc:
            issues.append("pin_configuration missing 'pins' array")

    # Check design_notes is a list
    dn = data.get("design_notes")
    if dn is not None and not isinstance(dn, list):
        issues.append(f"design_notes is {type(dn).__name__}, should be list")

    return issues


# ---------------------------------------------------------------------------
# File I/O
# ---------------------------------------------------------------------------

def normalize_file(filepath: str, dry_run: bool = False) -> dict:
    """Normalize a single JSON file. Returns summary dict."""
    filepath = Path(filepath)
    if not filepath.exists():
        return {"status": "error", "message": f"File not found: {filepath}"}

    try:
        with open(filepath) as f:
            data = json.load(f)
    except json.JSONDecodeError as e:
        return {"status": "error", "message": f"JSON parse error: {e}"}

    part = data.get("part_number", filepath.stem)
    normalized, changes = normalize(data)
    issues_before = validate(data)
    issues_after = validate(normalized)

    summary = {
        "status": "ok",
        "file": str(filepath),
        "part_number": part,
        "changes": changes,
        "issues_before": len(issues_before),
        "issues_after": len(issues_after),
        "remaining_issues": issues_after,
    }

    if not changes:
        summary["status"] = "already_normalized"
        log(f"  {part}: already normalized ({len(issues_before)} issues)")
        return summary

    if dry_run:
        summary["status"] = "dry_run"
        log(f"  {part}: {len(changes)} changes (dry-run)")
        for c in changes:
            log(f"    - {c}")
    else:
        with open(filepath, 'w') as f:
            json.dump(normalized, f, indent=2, ensure_ascii=False)
            f.write('\n')
        log(f"  {part}: {len(changes)} changes applied, {len(issues_before)}→{len(issues_after)} issues")
        for c in changes:
            log(f"    - {c}")

    return summary


def batch_normalize(dry_run: bool = False, limit: int = 0) -> dict:
    """Normalize all design JSONs on SSD2."""
    if not SSD2_METADATA.exists():
        log("ERROR: metadata directory not found")
        return {"error": "metadata directory not found"}

    files = sorted(SSD2_METADATA.glob("*.json"))
    results = {"total": 0, "normalized": 0, "already_ok": 0, "errors": 0}

    log(f"BATCH NORMALIZE: {len(files)} JSON files found (dry_run={dry_run})")

    for i, filepath in enumerate(files):
        if limit and i >= limit:
            break

        results["total"] += 1
        summary = normalize_file(str(filepath), dry_run=dry_run)

        if summary["status"] == "ok" or summary["status"] == "dry_run":
            results["normalized"] += 1
        elif summary["status"] == "already_normalized":
            results["already_ok"] += 1
        else:
            results["errors"] += 1

    log(f"BATCH COMPLETE: {results['normalized']} normalized, "
        f"{results['already_ok']} already OK, {results['errors']} errors "
        f"(of {results['total']} total)")

    return results


def validate_file(filepath: str) -> dict:
    """Validate a single JSON file against the schema."""
    filepath = Path(filepath)
    if not filepath.exists():
        return {"status": "error", "message": f"File not found: {filepath}"}

    try:
        with open(filepath) as f:
            data = json.load(f)
    except json.JSONDecodeError as e:
        return {"status": "error", "message": f"JSON parse error: {e}"}

    issues = validate(data)
    part = data.get("part_number", filepath.stem)

    if issues:
        log(f"VALIDATE {part}: {len(issues)} issues")
        for issue in issues:
            log(f"  - {issue}")
    else:
        log(f"VALIDATE {part}: OK")

    return {
        "status": "pass" if not issues else "fail",
        "part_number": part,
        "issues": issues,
        "issue_count": len(issues),
    }


def show_stats():
    """Show normalization statistics for all metadata files."""
    if not SSD2_METADATA.exists():
        log("ERROR: metadata directory not found")
        return

    files = sorted(SSD2_METADATA.glob("*.json"))
    total = len(files)
    conforming = 0
    non_conforming = 0
    issue_counts = {}

    for filepath in files:
        try:
            with open(filepath) as f:
                data = json.load(f)
            issues = validate(data)
            if issues:
                non_conforming += 1
                for issue in issues:
                    # Extract issue type (first word up to colon)
                    issue_type = issue.split(":")[0].strip() if ":" in issue else issue
                    issue_counts[issue_type] = issue_counts.get(issue_type, 0) + 1
            else:
                conforming += 1
        except Exception:
            non_conforming += 1

    log(f"STATS: {total} files, {conforming} conforming, {non_conforming} non-conforming")
    if issue_counts:
        log("Common issues:")
        for issue, count in sorted(issue_counts.items(), key=lambda x: -x[1]):
            log(f"  {count:4d}x  {issue}")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Vibe-IC Design Knowledge Normalizer",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python3 normalizer.py normalize --file ADS1115.json
  python3 normalizer.py normalize --file ADS1115.json --dry-run
  python3 normalizer.py batch
  python3 normalizer.py batch --dry-run --limit 10
  python3 normalizer.py validate --file ADS1115.json
  python3 normalizer.py stats
        """
    )

    subparsers = parser.add_subparsers(dest="command", help="Command to run")

    # normalize
    norm_parser = subparsers.add_parser("normalize", help="Normalize one JSON file (in-place)")
    norm_parser.add_argument("--file", required=True, help="Path to JSON file")
    norm_parser.add_argument("--dry-run", action="store_true",
                             help="Preview changes without writing")

    # batch
    batch_parser = subparsers.add_parser("batch", help="Normalize all design JSONs on SSD2")
    batch_parser.add_argument("--dry-run", action="store_true",
                              help="Preview changes without writing")
    batch_parser.add_argument("--limit", type=int, default=0,
                              help="Limit number of files to process")

    # validate
    val_parser = subparsers.add_parser("validate", help="Validate one JSON file")
    val_parser.add_argument("--file", required=True, help="Path to JSON file")

    # stats
    subparsers.add_parser("stats", help="Show normalization statistics")

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        sys.exit(1)

    if args.command == "normalize":
        filepath = args.file
        # If just a filename, look in SSD2 metadata dir
        if not os.path.sep in filepath and not Path(filepath).exists():
            filepath = str(SSD2_METADATA / filepath)
        result = normalize_file(filepath, dry_run=args.dry_run)
        if result["status"] == "error":
            print(f"ERROR: {result['message']}")
            sys.exit(1)
        print(json.dumps(result, indent=2, ensure_ascii=False))

    elif args.command == "batch":
        result = batch_normalize(dry_run=args.dry_run, limit=args.limit)
        print(json.dumps(result, indent=2, ensure_ascii=False))

    elif args.command == "validate":
        filepath = args.file
        if not os.path.sep in filepath and not Path(filepath).exists():
            filepath = str(SSD2_METADATA / filepath)
        result = validate_file(filepath)
        print(json.dumps(result, indent=2, ensure_ascii=False))
        if result["status"] == "fail":
            sys.exit(1)

    elif args.command == "stats":
        show_stats()


if __name__ == "__main__":
    main()
