#!/usr/bin/env python3
"""
Vibe-IC DB Importer — Import extracted design knowledge into PostgreSQL
========================================================================
Reads metadata JSON files from SSD2 and imports structured specs into
the vibe_ic PostgreSQL database.

RULES:
    1. NO file paths in DB — only extracted design knowledge
    2. NO record without a real downloaded document
    3. Specs serve datasheet-gen and appnote-gen primarily

Usage:
    python3 db_importer.py import --part ADS1115     # Import one IC
    python3 db_importer.py batch [--limit N]          # Import all metadata
    python3 db_importer.py status                     # Show import stats
"""

import json
import os
import sys
import argparse
import subprocess
from pathlib import Path
from datetime import datetime

METADATA_DIR = Path("/mnt/2a6ff798-a964-4a91-b131-e34fd4ca66ed/ic_documents/datasheets_metadata")
DB_NAME = "vibe_ic"
DB_USER = "reyerchu"


def log(msg: str):
    ts = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    print(f"[{ts}] {msg}")


def run_sql(sql: str) -> str:
    """Execute SQL and return output."""
    result = subprocess.run(
        ["psql", "-U", DB_USER, "-d", DB_NAME, "-t", "-A", "-c", sql],
        capture_output=True, text=True, timeout=10
    )
    return result.stdout.strip()


def ic_exists(part_number: str) -> bool:
    """Check if IC exists in DB."""
    result = run_sql(f"SELECT COUNT(*) FROM ics WHERE part_number = '{part_number}';")
    return result == "1"


def get_manufacturer_id(vendor: str) -> int:
    """Get or create manufacturer ID."""
    # Map common vendor names
    vendor_map = {
        "TI": "Texas Instruments",
        "ADI": "Analog Devices",
        "ST": "STMicroelectronics",
        "Microchip": "Microchip Technology",
        "NXP": "NXP Semiconductors",
        "Infineon": "Infineon Technologies",
        "onsemi": "onsemi",
        "SiLabs": "Silicon Labs",
        "Renesas": "Renesas Electronics",
        "Bosch": "Bosch Sensortec",
        "FTDI": "FTDI",
        "Nordic": "Nordic Semiconductor",
        "Espressif": "Espressif Systems",
        "GigaDevice": "GigaDevice",
        "Allwinner": "Allwinner Technology",
        "Rockchip": "Rockchip",
        "Lattice": "Lattice Semiconductor",
        "Vishay": "Vishay",
        "Sensirion": "Sensirion",
        "u-blox": "u-blox",
        "ams-OSRAM": "ams-OSRAM",
        "WCH": "WCH",
        "Rohm": "Rohm Semiconductor",
        "Qorvo": "Qorvo",
        "Semtech": "Semtech",
        "Winbond": "Winbond",
        "Solomon": "Solomon Systech",
        "Himax": "Himax Technologies",
        "Sitronix": "Sitronix Technology",
        "Puya": "Puya Semiconductor",
        "Nuvoton": "Nuvoton Technology",
        "Holtek": "Holtek Semiconductor",
        "MindMotion": "MindMotion",
        "Wolfspeed": "Wolfspeed",
        "Murata": "Murata",
        "Sharp": "Sharp",
        "Diodes": "Diodes Incorporated",
        "Nexperia": "Nexperia",
        "Cirrus Logic": "Cirrus Logic",
        "ISSI": "ISSI",
        "TDK-InvenSense": "TDK InvenSense",
        "InvenSense": "TDK InvenSense",
        "Aosong": "Aosong Electronics",
    }
    full_name = vendor_map.get(vendor, vendor)

    # Check if exists
    result = run_sql(f"SELECT id FROM manufacturers WHERE name = '{full_name}';")
    if result:
        return int(result.split('\n')[0])

    # Check short_name
    result = run_sql(f"SELECT id FROM manufacturers WHERE short_name = '{vendor}';")
    if result:
        return int(result.split('\n')[0])

    # Create new
    result = run_sql(
        f"INSERT INTO manufacturers (name, short_name, headquarters) "
        f"VALUES ('{full_name}', '{vendor}', 'Unknown') RETURNING id;"
    )
    if result:
        log(f"  Created manufacturer: {full_name} (id={result})")
        return int(result)

    return 1  # fallback


def get_or_create_category(category_name: str) -> int:
    """Get or create category ID."""
    # Map extractor categories to DB categories
    cat_map = {
        "Microcontroller": 27,
        "ADC": 1,
        "DAC": 8,
        "Op-Amp": 137,
        "Voltage Regulator": 143,
        "DC-DC Converter": 9,
        "Motor Driver": 44,
        "Temperature Sensor": 241,
        "IMU/Motion Sensor": 49,
        "Interface/Transceiver": 15,
        "Memory": 25,
        "LED/Display Driver": 294,
        "Power MOSFET": 391,
        "FPGA": 42,
        "Comparator": 365,
        "Voltage Reference": 139,
        "Timer": 298,
        "Logic": 19,
        "Battery Management": 342,
        "Digital Isolator": 338,
        "Clock/PLL": 310,
        "USB Bridge": 17,
        "Pressure Sensor": 50,
        "Humidity Sensor": 242,
        "Light Sensor": 243,
        "Proximity Sensor": 244,
        "GNSS/GPS": 279,
        "Audio": 45,
        "Magnetic Sensor": 247,
        "Multiplexer/Switch": 301,
        "PWM Controller": 235,
        "Unknown": 35,
    }
    return cat_map.get(category_name, 35)


# Cache batch_sources for vendor lookup
_vendor_cache = None
def get_vendor_for_part(part: str) -> str:
    global _vendor_cache
    if _vendor_cache is None:
        batch_file = Path("~/AI_IC_design/tools/ic_collector/batch_sources.json")
        if batch_file.exists():
            with open(batch_file) as f:
                sources = json.load(f)
            _vendor_cache = {s["part"].lower(): s.get("vendor", "Unknown") for s in sources}
        else:
            _vendor_cache = {}
    return _vendor_cache.get(part.lower(), "Unknown")


def import_one(part_number: str, force: bool = False) -> dict:
    """Import one IC's metadata into DB."""
    meta_path = METADATA_DIR / f"{part_number}.json"

    if not meta_path.exists():
        for f in METADATA_DIR.glob("*.json"):
            if f.stem.lower() == part_number.lower():
                meta_path = f
                break
        if not meta_path.exists():
            return {"status": "fail", "reason": "no_metadata"}

    with open(meta_path) as f:
        data = json.load(f)

    part = data.get("part_number", part_number)

    if ic_exists(part) and not force:
        return {"status": "skip", "reason": "already_in_db"}

    vendor = data.get("manufacturer", "Unknown")
    if vendor == "Unknown":
        vendor = get_vendor_for_part(part)

    mfr_id = get_manufacturer_id(vendor)
    category = data.get("category", "Unknown")
    category_id = get_or_create_category(category)
    description = data.get("description", "")[:500].replace("'", "''")
    name = part.replace("'", "''")

    vdd_min = data.get("vdd_min_v")
    vdd_max = data.get("vdd_max_v")
    temp_min = data.get("temp_min_c")
    temp_max = data.get("temp_max_c")
    pin_count = data.get("pin_count")
    resolution = data.get("resolution_bits")
    freq = data.get("freq_mhz")

    def sql_val(v):
        return "NULL" if v is None else str(v)

    if ic_exists(part):
        sql = (
            f"UPDATE ics SET "
            f"name = '{name}', "
            f"manufacturer_id = {mfr_id}, "
            f"category_id = {category_id}, "
            f"description = '{description}', "
            f"vdd_min = {sql_val(vdd_min)}, "
            f"vdd_max = {sql_val(vdd_max)}, "
            f"pin_count = {sql_val(pin_count)}, "
            f"resolution_bits = {sql_val(resolution)}, "
            f"freq_max = {sql_val(freq)} "
            f"WHERE part_number = '{part}';"
        )
    else:
        sql = (
            f"INSERT INTO ics (part_number, name, manufacturer_id, category_id, description, "
            f"vdd_min, vdd_max, pin_count, resolution_bits, freq_max) "
            f"VALUES ('{part}', '{name}', {mfr_id}, {category_id}, '{description}', "
            f"{sql_val(vdd_min)}, {sql_val(vdd_max)}, {sql_val(pin_count)}, "
            f"{sql_val(resolution)}, {sql_val(freq)});"
        )

    try:
        run_sql(sql)
        action = "UPDATE" if ic_exists(part) else "INSERT"
        log(f"  {action}: {part} [{category}] mfr={vendor}")
        return {"status": "ok", "part": part, "category": category}
    except Exception as e:
        log(f"  FAIL: {part} — {e}")
        return {"status": "fail", "reason": str(e)}


def batch_import(limit: int = 0, force: bool = False):
    """Import all metadata files into DB."""
    if not METADATA_DIR.exists():
        log("ERROR: metadata directory not found")
        return

    meta_files = sorted(METADATA_DIR.glob("*.json"))
    results = {"ok": 0, "skip": 0, "fail": 0}

    log(f"BATCH IMPORT: {len(meta_files)} metadata files")

    for i, mf in enumerate(meta_files):
        if limit and i >= limit:
            break
        part = mf.stem
        result = import_one(part, force=force)
        results[result["status"]] = results.get(result["status"], 0) + 1

    log(f"BATCH IMPORT COMPLETE: {results}")
    return results


def show_status():
    """Show import status."""
    meta_count = len(list(METADATA_DIR.glob("*.json"))) if METADATA_DIR.exists() else 0
    db_count = run_sql("SELECT COUNT(*) FROM ics;")
    mfr_count = run_sql("SELECT COUNT(*) FROM manufacturers;")

    # Category breakdown in DB
    cat_sql = "SELECT category, COUNT(*) FROM ics GROUP BY category ORDER BY COUNT(*) DESC;"
    cat_result = run_sql(cat_sql)

    print("=== DB Import Status ===\n")
    print(f"  Metadata files:    {meta_count}")
    print(f"  ICs in DB:         {db_count}")
    print(f"  Manufacturers:     {mfr_count}")
    print(f"\n  Categories in DB:")
    if cat_result:
        for line in cat_result.split('\n'):
            if '|' in line:
                cat, cnt = line.split('|')
                print(f"    {cat.strip():30s} {cnt.strip()}")


def main():
    parser = argparse.ArgumentParser(description="Vibe-IC DB Importer")
    sub = parser.add_subparsers(dest="cmd")

    p_imp = sub.add_parser("import", help="Import one IC")
    p_imp.add_argument("--part", required=True)
    p_imp.add_argument("--force", action="store_true")

    p_batch = sub.add_parser("batch", help="Batch import all metadata")
    p_batch.add_argument("--limit", type=int, default=0)
    p_batch.add_argument("--force", action="store_true")

    sub.add_parser("status", help="Show status")

    args = parser.parse_args()

    if args.cmd == "import":
        import_one(args.part, force=args.force)
    elif args.cmd == "batch":
        batch_import(limit=args.limit, force=args.force)
    elif args.cmd == "status":
        show_status()
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
