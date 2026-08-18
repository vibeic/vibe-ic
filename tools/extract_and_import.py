#!/usr/bin/env python3
"""
Extract metadata from IC datasheets (PDF) and import into PostgreSQL.
Only extracts FACTUAL parameters (not copyrightable).
PDFs are read but NOT stored in the database.
"""

import fitz  # PyMuPDF
import re
import json
import glob
import os
import psycopg2

DB_CONFIG = dict(dbname="vibe_ic", user="reyerchu", password="vibe_ic_2026", host="localhost")
PDF_DIR = "~/ic_documents/datasheets"

def extract_text_from_pdf(pdf_path, max_pages=5):
    """Extract text from first N pages of PDF."""
    try:
        doc = fitz.open(pdf_path)
        text = ""
        for i in range(min(max_pages, len(doc))):
            text += doc[i].get_text()
        doc.close()
        return text
    except Exception as e:
        print(f"  Error reading {pdf_path}: {e}")
        return ""

def safe_float(s):
    """Safely convert string to float, return None on failure."""
    try:
        v = float(s)
        return v if 0 < v < 1000 else None
    except (ValueError, TypeError):
        return None

def extract_voltage(text):
    """Extract supply voltage from text."""
    patterns = [
        r'(?:VCC|VDD|Supply)[^0-9]{0,30}?(\d+\.?\d*)\s*V?\s*(?:to|~|-|–)\s*(\d+\.?\d*)\s*V',
        r'(?:VCC|VDD|Supply)[^0-9]{0,30}?(\d+\.?\d*)\s*V',
        r'(\d+\.?\d*)\s*V\s*(?:to|~|-|–)\s*(\d+\.?\d*)\s*V\s*(?:supply|operating|power)',
    ]
    for p in patterns:
        m = re.search(p, text, re.IGNORECASE)
        if m:
            groups = m.groups()
            if len(groups) >= 2:
                a, b = safe_float(groups[0]), safe_float(groups[1])
                if a is not None:
                    return a, b
            else:
                a = safe_float(groups[0])
                if a is not None:
                    return a, None
    return None, None

def extract_current(text):
    """Extract supply current from text."""
    patterns = [
        r'(?:ICC|IDD|Supply Current|Quiescent)[^0-9]{0,30}?(\d+\.?\d*)\s*(µA|uA|mA|μA)',
        r'(\d+\.?\d*)\s*(µA|uA|mA|μA)\s*(?:typical|typ)',
    ]
    for p in patterns:
        m = re.search(p, text, re.IGNORECASE)
        if m:
            val = safe_float(m.group(1))
            if val is None: continue
            unit = m.group(2).lower()
            if 'ma' in unit:
                val *= 1000
            return val
    return None

def extract_frequency(text):
    """Extract max frequency from text."""
    patterns = [
        r'(\d+\.?\d*)\s*MHz\s*(?:max|clock|frequency|speed)',
        r'(?:max|clock|frequency|speed)[^0-9]{0,30}?(\d+\.?\d*)\s*MHz',
        r'(?:up to|maximum)\s*(\d+\.?\d*)\s*MHz',
        r'(\d+\.?\d*)\s*kHz\s*(?:I2C|SPI|SCL)',
    ]
    for p in patterns:
        m = re.search(p, text, re.IGNORECASE)
        if m:
            val = safe_float(m.group(1))
            if val is None: continue
            if 'kHz' in p:
                val /= 1000
            return val
    return None

def extract_resolution(text):
    """Extract ADC/DAC resolution."""
    m = re.search(r'(\d+)\s*-?\s*(?:bit|Bit)\s*(?:ADC|DAC|resolution|converter)', text, re.IGNORECASE)
    if m:
        return int(m.group(1))
    return None

def extract_package(text):
    """Extract package type."""
    packages = ['SOT-23', 'SOIC-8', 'SOIC-16', 'SSOP', 'TSSOP', 'QFN', 'QFP', 'LQFP',
                'BGA', 'DIP-8', 'DIP-14', 'DIP-16', 'PDIP', 'MSOP', 'WSON', 'VQFN',
                'TQFP', 'UFBGA', 'WLCSP', 'CSP']
    for pkg in packages:
        if pkg.lower() in text.lower():
            return pkg
    return None

def extract_interfaces(text):
    """Extract communication interfaces."""
    ifaces = []
    for iface in ['I2C', 'SPI', 'UART', 'USB', 'CAN', 'JTAG', 'I2S', 'SDIO', 'Ethernet', 'WiFi', 'Bluetooth', 'BLE']:
        if re.search(rf'\b{iface}\b', text, re.IGNORECASE):
            ifaces.append(iface)
    return ifaces

def extract_pin_count(text):
    """Extract pin count."""
    m = re.search(r'(\d+)\s*-?\s*(?:pin|Pin|PIN)\b', text)
    if m:
        val = int(m.group(1))
        if 2 <= val <= 1000:
            return val
    return None

def extract_part_number(filename):
    """Get part number from filename."""
    return os.path.splitext(os.path.basename(filename))[0]

def extract_manufacturer(text):
    """Guess manufacturer from text."""
    mfrs = {
        'Texas Instruments': ['Texas Instruments', 'TI ', 'www.ti.com'],
        'Microchip': ['Microchip', 'www.microchip.com'],
        'NXP': ['NXP', 'www.nxp.com', 'Philips Semiconductors'],
        'STMicroelectronics': ['STMicroelectronics', 'www.st.com'],
        'Analog Devices': ['Analog Devices', 'www.analog.com', 'Maxim Integrated'],
        'Espressif': ['Espressif', 'www.espressif.com'],
        'Nordic Semiconductor': ['Nordic', 'www.nordicsemi.com'],
        'Raspberry Pi': ['Raspberry Pi'],
        'FTDI': ['FTDI', 'ftdichip.com'],
        'Winbond': ['Winbond', 'www.winbond.com'],
        'Renesas': ['Renesas', 'www.renesas.com'],
        'Silicon Labs': ['Silicon Labs', 'Silicon Laboratories', 'www.silabs.com'],
        'WCH': ['WCH', 'Jiangsu Qin Heng', 'wch.cn'],
        'Advanced Monolithic': ['Advanced Monolithic', 'AMS'],
    }
    for mfr, keywords in mfrs.items():
        for kw in keywords:
            if kw.lower() in text.lower():
                return mfr
    return "Unknown"

def extract_description(text, part_number):
    """Extract one-line description from first page."""
    lines = text.split('\n')
    for line in lines[1:20]:
        line = line.strip()
        if len(line) > 20 and len(line) < 200 and part_number.lower() not in line.lower():
            if any(w in line.lower() for w in ['sensor', 'controller', 'converter', 'regulator',
                    'driver', 'amplifier', 'timer', 'counter', 'interface', 'transceiver',
                    'processor', 'memory', 'flash', 'eeprom', 'multiplexer', 'comparator',
                    'microcontroller', 'mcu', 'adc', 'dac', 'oscillator']):
                return line
    # Fallback: first substantial line
    for line in lines[:10]:
        line = line.strip()
        if len(line) > 15:
            return line[:150]
    return part_number

def main():
    conn = psycopg2.connect(**DB_CONFIG)
    cur = conn.cursor()

    ALLOWED_TABLES = {'manufacturers', 'categories', 'packages', 'interfaces'}

    def get_or_create(table, name):
        if table not in ALLOWED_TABLES:
            raise ValueError(f"Invalid table: {table}")
        cur.execute(f"SELECT id FROM {table} WHERE name = %s", (name,))
        row = cur.fetchone()
        if row: return row[0]
        cur.execute(f"INSERT INTO {table} (name) VALUES (%s) RETURNING id", (name,))
        return cur.fetchone()[0]

    pdfs = sorted(glob.glob(f"{PDF_DIR}/*.pdf"))
    print(f"Found {len(pdfs)} PDFs to process")

    imported = 0
    updated = 0
    skipped = 0

    for pdf in pdfs:
        part = extract_part_number(pdf)
        print(f"\nProcessing: {part}")

        text = extract_text_from_pdf(pdf)
        if not text:
            print(f"  Skipped (no text)")
            skipped += 1
            continue

        # Extract all parameters (auto-sort min/max)
        vdd_min, vdd_max = extract_voltage(text)
        if vdd_min is not None and vdd_max is not None and vdd_min > vdd_max:
            vdd_min, vdd_max = vdd_max, vdd_min
        icc = extract_current(text)
        freq = extract_frequency(text)
        res = extract_resolution(text)
        pkg = extract_package(text)
        ifaces = extract_interfaces(text)
        pins = extract_pin_count(text)
        mfr = extract_manufacturer(text)
        desc = extract_description(text, part)

        print(f"  Mfr: {mfr}")
        print(f"  VDD: {vdd_min}-{vdd_max}V, ICC: {icc}µA, Freq: {freq}MHz")
        print(f"  Pkg: {pkg}, Pins: {pins}, Interfaces: {ifaces}")

        mfr_id = get_or_create("manufacturers", mfr)
        cat_id = get_or_create("categories", "Extracted/" + (ifaces[0] if ifaces else "General"))
        pkg_id = get_or_create("packages", pkg) if pkg else None

        # Check if exists
        cur.execute("SELECT id FROM ics WHERE part_number = %s", (part,))
        existing = cur.fetchone()

        if existing:
            # Update with extracted data if we have better info
            ic_id = existing[0]
            updates = []
            params_list = []
            if vdd_min and vdd_min > 0:
                updates.append("vdd_min = %s"); params_list.append(vdd_min)
            if vdd_max and vdd_max > 0:
                updates.append("vdd_max = %s"); params_list.append(vdd_max)
            if icc:
                updates.append("icc_typ = %s"); params_list.append(icc)
            if freq:
                updates.append("freq_max = %s"); params_list.append(freq)
            if res:
                updates.append("resolution_bits = %s"); params_list.append(res)
            if pins:
                updates.append("pin_count = %s"); params_list.append(pins)
            if pkg_id:
                updates.append("package_id = %s"); params_list.append(pkg_id)

            if updates:
                params_list.append(part)
                cur.execute(f"UPDATE ics SET {', '.join(updates)} WHERE part_number = %s", params_list)
                updated += 1
                print(f"  Updated existing record")
        else:
            cur.execute("""
                INSERT INTO ics (part_number, name, manufacturer_id, category_id, description,
                               vdd_min, vdd_max, icc_typ, freq_max, resolution_bits,
                               package_id, pin_count, source_grade)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id
            """, (part, desc[:200], mfr_id, cat_id, desc[:500],
                  vdd_min, vdd_max, icc, freq, res,
                  pkg_id, pins, "B"))
            ic_id = cur.fetchone()[0]
            imported += 1
            print(f"  Imported as new IC (id={ic_id})")

        # Add interfaces
        for iface in ifaces:
            iface_id = get_or_create("interfaces", iface)
            cur.execute("INSERT INTO ic_interfaces (ic_id, interface_id) VALUES (%s,%s) ON CONFLICT DO NOTHING",
                       (ic_id, iface_id))

    conn.commit()

    # Final stats
    cur.execute("SELECT COUNT(*) FROM ics")
    total = cur.fetchone()[0]

    print(f"\n{'='*50}")
    print(f"PDFs processed: {len(pdfs)}")
    print(f"New imports: {imported}")
    print(f"Updated: {updated}")
    print(f"Skipped: {skipped}")
    print(f"Total ICs in DB: {total}")
    print(f"{'='*50}")

    conn.close()

if __name__ == "__main__":
    main()
