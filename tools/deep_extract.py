#!/usr/bin/env python3
"""
Deep metadata extractor — extracts pins, timing, features, temp range, etc.
from IC datasheets to fill the enhanced PostgreSQL schema.
Upgrades ICs from 'partial' to 'ready' status.
"""

import fitz
import re
import json
import glob
import os
import psycopg2

DB_CONFIG = dict(dbname="vibe_ic", user="reyerchu", password="vibe_ic_2026", host="localhost")
PDF_DIR = "~/ic_documents/datasheets"

def get_text(pdf_path, max_pages=10):
    try:
        doc = fitz.open(pdf_path)
        text = ""
        for i in range(min(max_pages, len(doc))):
            text += doc[i].get_text()
        doc.close()
        return text
    except:
        return ""

def extract_features(text):
    """Extract feature bullet points from first 2 pages."""
    features = []
    in_features = False
    for line in text.split('\n'):
        line = line.strip()
        if re.match(r'^(Features|FEATURES|Key Features)', line, re.IGNORECASE):
            in_features = True
            continue
        if in_features:
            if re.match(r'^(Description|DESCRIPTION|Applications|Pin|General|Overview|Absolute)', line, re.IGNORECASE):
                break
            if line.startswith(('•', '–', '-', '■', '►', '●')) or (len(line) > 10 and len(line) < 150):
                clean = re.sub(r'^[•–\-■►●\s]+', '', line).strip()
                if len(clean) > 5:
                    features.append(clean)
            if len(features) > 15:
                break
    return features[:12]

def extract_applications(text):
    """Extract application domains."""
    apps = []
    in_apps = False
    for line in text.split('\n'):
        line = line.strip()
        if re.match(r'^(Applications|APPLICATIONS|Typical Applications)', line, re.IGNORECASE):
            in_apps = True
            continue
        if in_apps:
            if re.match(r'^(Description|Features|Pin|Ordering|Package|Absolute)', line, re.IGNORECASE):
                break
            if line.startswith(('•', '–', '-', '■')) or (len(line) > 5 and len(line) < 100):
                clean = re.sub(r'^[•–\-■\s]+', '', line).strip()
                if len(clean) > 3:
                    apps.append(clean)
            if len(apps) > 10:
                break
    return apps[:8]

def extract_temp_range(text):
    """Extract operating temperature range."""
    patterns = [
        r'(?:Operating|Ambient)\s*(?:Temperature|Temp)[^0-9]*?(-?\d+)\s*°?C?\s*(?:to|~|-|–)\s*(-?\d+)',
        r'(-?\d+)\s*°?C?\s*(?:to|~|-|–)\s*(-?\d+)\s*°?C?\s*(?:operating|ambient)',
        r'T[Aa]\s*[:=]?\s*(-?\d+)\s*(?:to|~|-|–)\s*\+?(\d+)\s*°?C',
    ]
    for p in patterns:
        m = re.search(p, text, re.IGNORECASE)
        if m:
            return int(m.group(1)), int(m.group(2))
    return None, None

def extract_abs_max_vdd(text):
    """Extract absolute maximum VDD."""
    for p in [
        r'(?:VCC|VDD|Supply)[^0-9]{0,30}?(?:Absolute|Maximum)[^0-9]{0,30}?(\d+\.?\d*)\s*V',
        r'(?:Absolute|Maximum)[^0-9]{0,30}?(?:VCC|VDD|Supply)[^0-9]{0,30}?(\d+\.?\d*)\s*V',
    ]:
        m = re.search(p, text, re.IGNORECASE)
        if m:
            try:
                val = float(m.group(1))
                if 0.5 < val < 100:
                    return val
            except:
                pass
    return None

def extract_esd(text):
    """Extract ESD HBM rating."""
    m = re.search(r'(\d+)\s*(?:k?V)\s*(?:HBM|Human Body)', text, re.IGNORECASE)
    if m:
        val = int(m.group(1))
        if val < 100: val *= 1000  # Convert kV to V
        return val
    return None

def extract_io_levels(text):
    """Extract VOH, VOL, VIH, VIL."""
    results = {}
    for param, patterns in {
        'voh': [r'VOH[^0-9]{0,20}?(\d+\.?\d+)\s*V'],
        'vol': [r'VOL[^0-9]{0,20}?(\d+\.?\d+)\s*V'],
        'vih': [r'VIH[^0-9]{0,20}?(\d+\.?\d+)\s*V'],
        'vil': [r'VIL[^0-9]{0,20}?(\d+\.?\d+)\s*V'],
    }.items():
        for p in patterns:
            m = re.search(p, text, re.IGNORECASE)
            if m:
                try:
                    val = float(m.group(1))
                    if 0 < val < 50:
                        results[param] = val
                except:
                    pass
                break
    return results

def extract_pins_from_table(text, part_number):
    """Extract pin definitions from pin table in text."""
    pins = []
    # Look for pin table patterns
    pin_section = False
    for line in text.split('\n'):
        line = line.strip()
        if re.match(r'^(Pin|PIN)\s*(Configuration|Description|Function|Name|No\.)', line, re.IGNORECASE):
            pin_section = True
            continue
        if pin_section:
            if re.match(r'^(Absolute|Electrical|Timing|Functional|Description|Application)', line, re.IGNORECASE):
                break
            # Match: number name type/description
            m = re.match(r'(\d+)\s+(\w+)\s+(.*)', line)
            if m:
                pin_num = int(m.group(1))
                pin_name = m.group(2)
                pin_desc = m.group(3).strip()
                if pin_num <= 100 and len(pin_name) <= 20:
                    direction = 'input'
                    if any(w in pin_name.upper() for w in ['VDD', 'VCC', 'GND', 'VSS']):
                        direction = 'power'
                    elif any(w in pin_desc.lower() for w in ['output', 'out']):
                        direction = 'output'
                    elif any(w in pin_desc.lower() for w in ['bidirectional', 'i/o', 'data']):
                        direction = 'bidirectional'

                    pin_type = 'Digital'
                    if any(w in pin_name.upper() for w in ['AIN', 'AOUT', 'VREF', 'ANALOG']):
                        pin_type = 'Analog'
                    elif direction == 'power':
                        pin_type = 'Power'

                    pins.append({
                        'number': pin_num,
                        'name': pin_name,
                        'type': pin_type,
                        'direction': direction,
                        'description': pin_desc[:100]
                    })
            if len(pins) > 60:
                break
    return pins

def extract_timing(text):
    """Extract timing parameters."""
    timings = []
    timing_patterns = [
        (r't(?:HD|hd)[_:]?(?:STA|sta)\s*[^0-9]*?([\d.]+)\s*(ns|µs|us)', 'tHD_STA', 'Start condition hold time'),
        (r't(?:SU|su)[_:]?(?:STO|sto)\s*[^0-9]*?([\d.]+)\s*(ns|µs|us)', 'tSU_STO', 'Stop condition setup time'),
        (r't(?:LOW|low)\s*[^0-9]*?([\d.]+)\s*(ns|µs|us)', 'tLOW', 'SCL low period'),
        (r't(?:HIGH|high)\s*[^0-9]*?([\d.]+)\s*(ns|µs|us)', 'tHIGH', 'SCL high period'),
        (r't(?:SU|su)[_:]?(?:DAT|dat)\s*[^0-9]*?([\d.]+)\s*(ns|µs|us)', 'tSU_DAT', 'Data setup time'),
        (r't(?:HD|hd)[_:]?(?:DAT|dat)\s*[^0-9]*?([\d.]+)\s*(ns|µs|us)', 'tHD_DAT', 'Data hold time'),
        (r't(?:CONV|conv)\s*[^0-9]*?([\d.]+)\s*(ms|µs|us)', 'tCONV', 'Conversion time'),
        (r't(?:POR|por|PORWU)\s*[^0-9]*?([\d.]+)\s*(ms|µs|us)', 'tPOR', 'Power-on reset time'),
    ]
    for pattern, name, desc in timing_patterns:
        m = re.search(pattern, text)
        if m:
            val = float(m.group(1))
            unit = m.group(2).replace('µs', 'us')
            timings.append({'name': name, 'desc': desc, 'min_val': val, 'unit': unit})
    return timings

def main():
    conn = psycopg2.connect(**DB_CONFIG)
    cur = conn.cursor()

    pdfs = sorted(glob.glob(f"{PDF_DIR}/*.pdf"))
    # Filter out non-IC PDFs
    skip = ['AI4EDA', 'AINativeDesign', 'AI_Native', 'Vibe_IC', 'Startup_Analysis']
    pdfs = [p for p in pdfs if not any(s in os.path.basename(p) for s in skip)]

    print(f"Processing {len(pdfs)} PDFs for deep extraction")

    updated = 0
    pins_added = 0
    timing_added = 0

    for pdf in pdfs:
        part = os.path.splitext(os.path.basename(pdf))[0]

        # Find IC in DB
        cur.execute("SELECT id FROM ics WHERE part_number = %s", (part,))
        row = cur.fetchone()
        if not row:
            continue
        ic_id = row[0]

        text = get_text(pdf)
        if not text:
            continue

        print(f"\n{part}:")

        # Extract features
        features = extract_features(text)
        if features:
            cur.execute("UPDATE ics SET features = %s WHERE id = %s", (features, ic_id))
            print(f"  Features: {len(features)}")

        # Extract applications
        apps = extract_applications(text)
        if apps:
            cur.execute("UPDATE ics SET applications = %s WHERE id = %s", (apps, ic_id))
            print(f"  Applications: {len(apps)}")

        # Extract temperature range
        temp_min, temp_max = extract_temp_range(text)
        if temp_min is not None:
            if temp_max is not None and temp_min > temp_max:
                temp_min, temp_max = temp_max, temp_min
            cur.execute("UPDATE ics SET temp_min = %s, temp_max = %s WHERE id = %s", (temp_min, temp_max, ic_id))
            print(f"  Temp: {temp_min} to {temp_max}°C")

        # Extract abs max VDD
        vdd_abs = extract_abs_max_vdd(text)
        if vdd_abs:
            cur.execute("UPDATE ics SET vdd_abs_max = %s WHERE id = %s", (vdd_abs, ic_id))

        # Extract ESD
        esd = extract_esd(text)
        if esd:
            cur.execute("UPDATE ics SET esd_hbm = %s WHERE id = %s", (esd, ic_id))

        # Extract I/O levels
        io = extract_io_levels(text)
        if io:
            sets = []
            vals = []
            for k, v in io.items():
                sets.append(f"{k} = %s")
                vals.append(v)
            if sets:
                vals.append(ic_id)
                cur.execute(f"UPDATE ics SET {', '.join(sets)} WHERE id = %s", vals)
                print(f"  I/O levels: {list(io.keys())}")

        # Extract pins (only if no pins exist yet)
        cur.execute("SELECT COUNT(*) FROM ic_pins WHERE ic_id = %s", (ic_id,))
        existing_pins = cur.fetchone()[0]
        if existing_pins == 0:
            pins = extract_pins_from_table(text, part)
            for pin in pins:
                cur.execute("""
                    INSERT INTO ic_pins (ic_id, pin_number, name, type, direction, description)
                    VALUES (%s, %s, %s, %s, %s, %s)
                    ON CONFLICT (ic_id, pin_number) DO NOTHING
                """, (ic_id, pin['number'], pin['name'], pin['type'], pin['direction'], pin['description']))
                pins_added += 1
            if pins:
                cur.execute("UPDATE ics SET pin_count = %s WHERE id = %s", (len(pins), ic_id))
                print(f"  Pins: {len(pins)}")

        # Extract timing parameters
        cur.execute("SELECT COUNT(*) FROM ic_timing WHERE ic_id = %s", (ic_id,))
        existing_timing = cur.fetchone()[0]
        if existing_timing == 0:
            timings = extract_timing(text)
            for t in timings:
                cur.execute("""
                    INSERT INTO ic_timing (ic_id, param_name, param_desc, min_val, unit)
                    VALUES (%s, %s, %s, %s, %s)
                """, (ic_id, t['name'], t['desc'], t['min_val'], t['unit']))
                timing_added += 1
            if timings:
                print(f"  Timing: {len(timings)} params")

        # Generate keywords from all extracted data
        keywords = set()
        keywords.add(part.lower())
        for f in features[:5]:
            for w in f.lower().split():
                if len(w) > 3:
                    keywords.add(w)
        for a in apps[:3]:
            for w in a.lower().split():
                if len(w) > 3:
                    keywords.add(w)
        if keywords:
            cur.execute("UPDATE ics SET keywords = %s WHERE id = %s", (list(keywords)[:20], ic_id))

        # Write data_sources record (copyright tracking)
        extracted = []
        if features: extracted.append('features')
        if apps: extracted.append('applications')
        if temp_min: extracted.extend(['temp_min', 'temp_max'])
        if vdd_abs: extracted.append('vdd_abs_max')
        if esd: extracted.append('esd_hbm')
        if io: extracted.extend(list(io.keys()))
        if pins: extracted.append('pins')
        if timings: extracted.append('timing')

        if extracted:
            cur.execute("""
                INSERT INTO data_sources (ic_id, source_type, source_url, provider, license, extracted_fields, notes)
                VALUES (%s, 'datasheet_pdf', %s, %s, 'fair-use-factual', %s, 'Auto-extracted by deep_extract.py')
                ON CONFLICT DO NOTHING
            """, (ic_id, f"{PDF_DIR}/{part}.pdf", extract_manufacturer(text) if 'extract_manufacturer' in dir() else 'Unknown', extracted))

        updated += 1

    conn.commit()

    # Final stats
    cur.execute("SELECT datasheet_completeness, COUNT(*) FROM ic_datasheet_ready GROUP BY datasheet_completeness")
    completeness = cur.fetchall()

    cur.execute("SELECT COUNT(*) FROM ics")
    total = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM ic_pins")
    total_pins = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM ic_timing")
    total_timing = cur.fetchone()[0]

    print(f"\n{'='*50}")
    print(f"ICs processed: {updated}")
    print(f"Pins added: {pins_added}")
    print(f"Timing params added: {timing_added}")
    print(f"Total: {total} ICs, {total_pins} pins, {total_timing} timing params")
    print(f"Completeness: {dict(completeness)}")
    print(f"{'='*50}")

    conn.close()

if __name__ == "__main__":
    main()
