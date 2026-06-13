#!/usr/bin/env python3
"""
Vibe-IC Design Knowledge Extractor
====================================
Extract structured design knowledge from IC PDF datasheets.
Uses pdftotext for text extraction + regex parsing for specs.

Usage:
    python3 extractor.py extract --pdf /path/to/IC.pdf
    python3 extractor.py batch [--limit N]     # Extract from all unprocessed PDFs on SSD2
    python3 extractor.py status                # Show extraction stats
"""

import json
import os
import re
import subprocess
import sys
import argparse
from pathlib import Path
from datetime import datetime

SSD2_BASE = Path("/mnt/2a6ff798-a964-4a91-b131-e34fd4ca66ed/ic_documents")
DATASHEETS_DIR = SSD2_BASE / "datasheets"
METADATA_DIR = SSD2_BASE / "datasheets_metadata"
LOG_FILE = Path("~/AI_IC_design/tools/ic_collector/extractor.log")


def log(msg: str):
    ts = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    line = f"[{ts}] {msg}"
    print(line)
    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(LOG_FILE, 'a') as f:
        f.write(line + '\n')


def pdf_to_text(pdf_path: str, max_pages: int = 20) -> str:
    """Extract text from PDF using pdftotext."""
    try:
        result = subprocess.run(
            ["pdftotext", "-l", str(max_pages), pdf_path, "-"],
            capture_output=True, text=True, timeout=30
        )
        return result.stdout
    except Exception as e:
        log(f"  pdftotext error: {e}")
        return ""


def extract_basic_specs(text: str, part_name: str) -> dict:
    """Extract basic specs from datasheet text using regex patterns."""
    specs = {
        "part_number": part_name,
        "extracted_at": datetime.now().isoformat(),
        "extraction_method": "pdftotext+regex",
    }

    # Description — first meaningful line with the part number
    lines = text.split('\n')
    for line in lines[:50]:
        line = line.strip()
        if len(line) > 20 and (part_name.lower() in line.lower() or
            any(w in line.lower() for w in ['bit', 'channel', 'mhz', 'ghz', 'interface',
                'converter', 'controller', 'driver', 'sensor', 'regulator', 'amplifier',
                'processor', 'microcontroller', 'transceiver', 'timer', 'counter'])):
            specs["description"] = line[:200]
            break

    # Supply voltage
    vdd_patterns = [
        r'[Ss]upply\s+[Vv]oltage.*?(\d+\.?\d*)\s*V?\s*to\s*(\d+\.?\d*)\s*V',
        r'V[DCS]{2}\s*[:=]?\s*(\d+\.?\d*)\s*V?\s*to\s*(\d+\.?\d*)\s*V',
        r'[Oo]perating\s+[Vv]oltage.*?(\d+\.?\d*)\s*V?\s*to\s*(\d+\.?\d*)\s*V',
        r'(\d+\.?\d*)\s*V\s*to\s*(\d+\.?\d*)\s*V\s*[Ss]upply',
    ]
    for pat in vdd_patterns:
        m = re.search(pat, text)
        if m:
            v1, v2 = float(m.group(1)), float(m.group(2))
            if 0.5 <= v1 <= 10 and 0.5 <= v2 <= 10:
                specs["vdd_min_v"] = min(v1, v2)
                specs["vdd_max_v"] = max(v1, v2)
                break

    # Operating temperature
    temp_pat = r'[-–](\d+)\s*°?\s*C\s*to\s*\+?(\d+)\s*°?\s*C'
    m = re.search(temp_pat, text)
    if m:
        specs["temp_min_c"] = -int(m.group(1))
        specs["temp_max_c"] = int(m.group(2))

    # Interface detection
    interfaces = []
    if re.search(r'\bI2C\b|\bI²C\b|\bIIC\b', text, re.IGNORECASE):
        interfaces.append("I2C")
    if re.search(r'\bSPI\b', text):
        interfaces.append("SPI")
    if re.search(r'\bUART\b', text, re.IGNORECASE):
        interfaces.append("UART")
    if re.search(r'\bUSB\b', text):
        interfaces.append("USB")
    if re.search(r'\bCAN\b', text):
        interfaces.append("CAN")
    if re.search(r'\bJTAG\b', text):
        interfaces.append("JTAG")
    if re.search(r'\bEthernet\b', text, re.IGNORECASE):
        interfaces.append("Ethernet")
    if re.search(r'\bBluetooth\b|\bBLE\b', text, re.IGNORECASE):
        interfaces.append("Bluetooth")
    if re.search(r'\bWi-?Fi\b|\b802\.11\b', text, re.IGNORECASE):
        interfaces.append("WiFi")
    if re.search(r'\bLoRa\b', text, re.IGNORECASE):
        interfaces.append("LoRa")
    if interfaces:
        specs["interfaces"] = interfaces

    # Package detection
    packages = set()
    pkg_patterns = [
        r'(SOIC|SOP|SSOP|TSSOP|MSOP|VSOP)-(\d+)',
        r'(QFP|LQFP|TQFP|QFN|DFN|VQFN|WQFN)-(\d+)',
        r'(BGA|FBGA|WLCSP|CSP)-(\d+)',
        r'(DIP|PDIP|CDIP)-(\d+)',
        r'(SOT)-(\d+)',
        r'(TO)-(\d+)',
    ]
    for pat in pkg_patterns:
        for m in re.finditer(pat, text):
            packages.add(f"{m.group(1)}-{m.group(2)}")
    if packages:
        specs["packages"] = sorted(packages)

    # Pin count
    pin_pat = r'(\d+)\s*-?\s*[Pp]in'
    pin_counts = [int(m.group(1)) for m in re.finditer(pin_pat, text) if 2 <= int(m.group(1)) <= 500]
    if pin_counts:
        specs["pin_count"] = max(set(pin_counts), key=pin_counts.count)

    # Resolution (for ADC/DAC)
    res_pat = r'(\d+)\s*-?\s*[Bb]it\s*(ADC|DAC|[Rr]esolution|[Cc]onverter|[Dd]igital)'
    m = re.search(res_pat, text)
    if m:
        bits = int(m.group(1))
        if 4 <= bits <= 32:
            specs["resolution_bits"] = bits

    # Frequency/clock
    freq_patterns = [
        (r'(\d+)\s*MHz\s*(?:clock|frequency|oscillator|CPU|core)', 'freq_mhz'),
        (r'(\d+)\s*GHz', 'freq_ghz'),
        (r'(\d+)\s*kSPS|(\d+)\s*KSPS', 'sample_rate_ksps'),
        (r'(\d+)\s*MSPS', 'sample_rate_msps'),
        (r'(\d+)\s*SPS', 'sample_rate_sps'),
    ]
    for pat, key in freq_patterns:
        m = re.search(pat, text)
        if m:
            val = int(m.group(1)) if m.group(1) else int(m.group(2))
            if val > 0:
                specs[key] = val
                break

    # IC category detection
    text_lower = text[:3000].lower()
    if any(w in text_lower for w in ['microcontroller', 'mcu', 'cortex', 'risc-v', 'processor']):
        specs["category"] = "Microcontroller"
    elif any(w in text_lower for w in ['analog-to-digital', 'adc', 'a/d converter']):
        specs["category"] = "ADC"
    elif any(w in text_lower for w in ['digital-to-analog', 'dac', 'd/a converter']):
        specs["category"] = "DAC"
    elif any(w in text_lower for w in ['operational amplifier', 'op amp', 'op-amp']):
        specs["category"] = "Op-Amp"
    elif any(w in text_lower for w in ['voltage regulator', 'ldo', 'linear regulator']):
        specs["category"] = "Voltage Regulator"
    elif any(w in text_lower for w in ['dc-dc', 'buck', 'boost', 'switching regulator']):
        specs["category"] = "DC-DC Converter"
    elif any(w in text_lower for w in ['motor driver', 'h-bridge']):
        specs["category"] = "Motor Driver"
    elif any(w in text_lower for w in ['temperature sensor', 'thermometer']):
        specs["category"] = "Temperature Sensor"
    elif any(w in text_lower for w in ['accelerometer', 'gyroscope', 'imu', 'inertial']):
        specs["category"] = "IMU/Motion Sensor"
    elif any(w in text_lower for w in ['transceiver', 'uart', 'rs-485', 'rs-232', 'can ']):
        specs["category"] = "Interface/Transceiver"
    elif any(w in text_lower for w in ['flash memory', 'eeprom', 'sram', 'dram']):
        specs["category"] = "Memory"
    elif any(w in text_lower for w in ['led driver', 'display driver']):
        specs["category"] = "LED/Display Driver"
    elif any(w in text_lower for w in ['power mosfet', 'n-channel', 'p-channel']):
        specs["category"] = "Power MOSFET"
    elif any(w in text_lower for w in ['fpga', 'programmable logic', 'gate array']):
        specs["category"] = "FPGA"
    elif any(w in text_lower for w in ['comparator']):
        specs["category"] = "Comparator"
    elif any(w in text_lower for w in ['voltage reference']):
        specs["category"] = "Voltage Reference"
    elif any(w in text_lower for w in ['timer', '555']):
        specs["category"] = "Timer"
    elif any(w in text_lower for w in ['shift register', 'latch', 'flip-flop', 'logic gate']):
        specs["category"] = "Logic"
    elif any(w in text_lower for w in ['battery charger', 'battery management']):
        specs["category"] = "Battery Management"
    elif any(w in text_lower for w in ['isolator', 'isolation']):
        specs["category"] = "Digital Isolator"
    elif any(w in text_lower for w in ['clock generator', 'pll', 'oscillator']):
        specs["category"] = "Clock/PLL"
    elif any(w in text_lower for w in ['usb-to', 'uart bridge', 'usb bridge']):
        specs["category"] = "USB Bridge"
    elif any(w in text_lower for w in ['pressure sensor', 'barometer']):
        specs["category"] = "Pressure Sensor"
    elif any(w in text_lower for w in ['humidity', 'hygrometer']):
        specs["category"] = "Humidity Sensor"
    elif any(w in text_lower for w in ['light sensor', 'ambient light', 'photodiode', 'lux']):
        specs["category"] = "Light Sensor"
    elif any(w in text_lower for w in ['proximity', 'gesture']):
        specs["category"] = "Proximity Sensor"
    elif any(w in text_lower for w in ['gps', 'gnss', 'positioning']):
        specs["category"] = "GNSS/GPS"
    elif any(w in text_lower for w in ['audio codec', 'audio amplifier', 'class-d']):
        specs["category"] = "Audio"
    elif any(w in text_lower for w in ['magnetic', 'hall effect', 'magnetometer']):
        specs["category"] = "Magnetic Sensor"
    elif any(w in text_lower for w in ['multiplexer', 'mux', 'analog switch']):
        specs["category"] = "Multiplexer/Switch"
    elif any(w in text_lower for w in ['pwm', 'pulse width']):
        specs["category"] = "PWM Controller"

    # Count extracted fields (excluding meta fields)
    meta_keys = {"part_number", "extracted_at", "extraction_method"}
    specs["fields_extracted"] = len([k for k in specs if k not in meta_keys])

    return specs


def extract_one(pdf_path: str, force: bool = False) -> dict:
    """Extract specs from one PDF and save metadata JSON."""
    pdf_path = Path(pdf_path)
    part_name = pdf_path.stem

    METADATA_DIR.mkdir(parents=True, exist_ok=True)
    meta_path = METADATA_DIR / f"{part_name}.json"

    if meta_path.exists() and not force:
        return {"status": "skip", "reason": "already_extracted"}

    log(f"EXTRACT {part_name}")
    text = pdf_to_text(str(pdf_path))
    if len(text) < 100:
        log(f"  FAIL: too little text extracted ({len(text)} chars)")
        return {"status": "fail", "reason": "no_text"}

    specs = extract_basic_specs(text, part_name)

    with open(meta_path, 'w') as f:
        json.dump(specs, f, indent=2, ensure_ascii=False)

    n = specs["fields_extracted"]
    cat = specs.get("category", "Unknown")
    log(f"  OK: {n} fields extracted, category={cat}")
    return {"status": "ok", "fields": n, "category": cat}


def batch_extract(limit: int = 0, force: bool = False):
    """Extract specs from all unprocessed PDFs on SSD2."""
    if not DATASHEETS_DIR.exists():
        log("ERROR: datasheets directory not found")
        return

    pdfs = sorted(DATASHEETS_DIR.glob("*.pdf"))
    results = {"ok": 0, "skip": 0, "fail": 0}

    log(f"BATCH EXTRACT: {len(pdfs)} PDFs found")

    for i, pdf in enumerate(pdfs):
        if limit and i >= limit:
            break

        result = extract_one(str(pdf), force=force)
        results[result["status"]] = results.get(result["status"], 0) + 1

    log(f"BATCH COMPLETE: {results}")
    return results


def show_status():
    """Show extraction status."""
    pdf_count = len(list(DATASHEETS_DIR.glob("*.pdf"))) if DATASHEETS_DIR.exists() else 0
    meta_count = len(list(METADATA_DIR.glob("*.json"))) if METADATA_DIR.exists() else 0

    # Analyze metadata quality
    categories = {}
    total_fields = 0
    if METADATA_DIR.exists():
        for mf in METADATA_DIR.glob("*.json"):
            try:
                with open(mf) as f:
                    data = json.load(f)
                cat = data.get("category", "Unknown")
                categories[cat] = categories.get(cat, 0) + 1
                total_fields += data.get("fields_extracted", 0)
            except Exception:
                pass

    print("=== Design Knowledge Extractor Status ===\n")
    print(f"  PDFs on SSD2:      {pdf_count}")
    print(f"  Metadata files:    {meta_count}")
    print(f"  Unprocessed:       {pdf_count - meta_count}")
    print(f"  Avg fields/IC:     {total_fields/meta_count:.1f}" if meta_count else "  Avg fields/IC:     N/A")
    print(f"\n  Categories:")
    for cat, cnt in sorted(categories.items(), key=lambda x: -x[1]):
        print(f"    {cat:30s} {cnt}")


def main():
    parser = argparse.ArgumentParser(description="Vibe-IC Design Knowledge Extractor")
    sub = parser.add_subparsers(dest="cmd")

    p_ext = sub.add_parser("extract", help="Extract from one PDF")
    p_ext.add_argument("--pdf", required=True, help="Path to PDF")
    p_ext.add_argument("--force", action="store_true")

    p_batch = sub.add_parser("batch", help="Batch extract from all PDFs")
    p_batch.add_argument("--limit", type=int, default=0)
    p_batch.add_argument("--force", action="store_true")

    sub.add_parser("status", help="Show status")

    args = parser.parse_args()

    if args.cmd == "extract":
        extract_one(args.pdf, force=args.force)
    elif args.cmd == "batch":
        batch_extract(limit=args.limit, force=args.force)
    elif args.cmd == "status":
        show_status()
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
