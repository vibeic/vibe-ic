#!/usr/bin/env python3
"""
ds-quality-check -- Datasheet Auto-Quality Scorer
===================================================
Scores a Markdown-format datasheet on 10 criteria (0-10 each, total /100).

Criteria:
    1. Features section exists and has >=5 items
    2. Description >=2 paragraphs
    3. Pin Configuration table with >=3 columns
    4. Absolute Maximum Ratings table exists
    5. Recommended Operating Conditions with min/typ/max
    6. Electrical Characteristics with DC+AC sections
    7. Timing Diagrams present (ASCII art or description)
    8. Block Diagram present
    9. Detailed Description with Register Map (if applicable)
   10. Application Information with circuit

Usage:
    python3 ds_quality_check.py <datasheet.md>
    python3 ds_quality_check.py <datasheet.md> --json
"""

import re
import sys
import json
import argparse
from pathlib import Path
from typing import List, Dict, Any, Tuple


# ============================================================================
# Section Finders
# ============================================================================

def _find_section(text: str, patterns: List[str]) -> str:
    """Extract text under a section heading matching any of the patterns.

    Returns the text from the heading to the next same-level (or higher) heading.
    """
    for pat in patterns:
        # Match Markdown headings (##, ###, etc.)
        regex = rf'(^|\n)(#{{1,4}})\s+[^\n]*{pat}[^\n]*\n'
        m = re.search(regex, text, re.IGNORECASE)
        if m:
            level_hashes = m.group(2)
            start = m.end()
            # Find next heading of same or higher level
            next_heading = re.search(
                rf'\n#{{{1},{len(level_hashes)}}}\s+',
                text[start:]
            )
            end = start + next_heading.start() if next_heading else len(text)
            return text[start:end]
    return ""


def _count_table_columns(section_text: str) -> int:
    """Count the maximum number of columns in Markdown tables within the section."""
    max_cols = 0
    for line in section_text.split('\n'):
        if '|' in line and not re.match(r'^\s*\|[\s\-:|]+\|\s*$', line):
            cols = len([c for c in line.split('|') if c.strip()])
            max_cols = max(max_cols, cols)
    return max_cols


def _has_table(section_text: str) -> bool:
    """Check if section contains at least one Markdown table."""
    lines = section_text.split('\n')
    for i, line in enumerate(lines):
        if re.match(r'^\s*\|[\s\-:|]+\|\s*$', line):
            return True
    return False


def _count_list_items(section_text: str) -> int:
    """Count bullet/numbered list items in section."""
    items = re.findall(r'^\s*[-*+]\s+\S|^\s*\d+\.\s+\S', section_text, re.MULTILINE)
    return len(items)


def _count_paragraphs(section_text: str) -> int:
    """Count non-empty paragraph blocks (separated by blank lines)."""
    blocks = re.split(r'\n\s*\n', section_text.strip())
    paragraphs = 0
    for block in blocks:
        block = block.strip()
        if not block:
            continue
        # Skip tables, headings, code blocks, list-only blocks
        if block.startswith('|') or block.startswith('#') or block.startswith('```'):
            continue
        # Must have at least one sentence-like line
        lines = [l for l in block.split('\n') if l.strip() and not l.strip().startswith(('-', '*', '+', '|', '#'))]
        if lines:
            paragraphs += 1
    return paragraphs


def _has_ascii_art(section_text: str) -> bool:
    """Detect ASCII art diagrams (code blocks, box-drawing, or signal waveforms)."""
    # Code block
    if '```' in section_text:
        return True
    # Box-drawing characters
    if re.search(r'[┌┐└┘├┤┬┴┼─│╔╗╚╝║═]', section_text):
        return True
    # Simple ASCII art patterns (lines of dashes, pipes, plus signs forming diagrams)
    art_lines = 0
    for line in section_text.split('\n'):
        stripped = line.strip()
        if len(stripped) > 5 and re.match(r'^[\s\-\+\|_/\\<>\[\](){}=*^~.]+$', stripped):
            art_lines += 1
        # Signal waveform patterns
        if re.search(r'_{2,}|‾{2,}|\-{3,}.*\|', stripped):
            art_lines += 1
    return art_lines >= 2


def _has_min_typ_max(section_text: str) -> bool:
    """Check if section contains min/typ/max columns or values."""
    lower = section_text.lower()
    text_raw = section_text
    # Table header pattern
    if re.search(r'min\s*\|.*typ\s*\|.*max', lower):
        return True
    if re.search(r'min.*typ.*max', lower):
        return True
    # Chinese equivalents
    if re.search(r'最小\s*\|.*典型\s*\|.*最大', text_raw):
        return True
    if re.search(r'最小.*典型.*最大', text_raw):
        return True
    # Separate mentions
    has_min = 'min' in lower or '最小' in text_raw
    has_typ = 'typ' in lower or '典型' in text_raw
    has_max = 'max' in lower or '最大' in text_raw
    return has_min and has_typ and has_max


# ============================================================================
# Scoring Functions (one per criterion)
# ============================================================================

def check_features(text: str) -> Tuple[int, str]:
    """Criterion 1: Features section exists and has >=5 items."""
    section = _find_section(text, [r'feature', r'key\s+feature', r'highlights',
                                   r'特性', r'特點', r'主要特性', r'功能特性'])
    if not section:
        return 0, "Features section not found"
    items = _count_list_items(section)
    if items >= 5:
        return 10, f"Features section has {items} items (>=5)"
    elif items >= 3:
        score = 5 + items
        return min(score, 9), f"Features section has {items} items (need >=5 for full score)"
    elif items >= 1:
        return 3, f"Features section has only {items} item(s)"
    else:
        return 1, "Features section exists but has no list items"


def check_description(text: str) -> Tuple[int, str]:
    """Criterion 2: Description >=2 paragraphs."""
    section = _find_section(text, [r'description', r'overview', r'introduction',
                                   r'簡介', r'概述', r'產品概述', r'說明'])
    if not section:
        return 0, "Description/Overview section not found"
    paragraphs = _count_paragraphs(section)
    if paragraphs >= 3:
        return 10, f"Description has {paragraphs} paragraphs"
    elif paragraphs == 2:
        return 8, f"Description has {paragraphs} paragraphs"
    elif paragraphs == 1:
        return 4, "Description has only 1 paragraph (need >=2)"
    else:
        return 1, "Description section exists but has no substantial paragraphs"


def check_pin_config(text: str) -> Tuple[int, str]:
    """Criterion 3: Pin Configuration table with >=3 columns."""
    section = _find_section(text, [r'pin\s+config', r'pin\s+description', r'pin\s+assign',
                                   r'pin\s+out', r'pin\s+diagram', r'pinout',
                                   r'terminal\s+function', r'pin\s+function',
                                   r'腳位', r'引腳', r'腳位配置', r'腳位說明'])
    if not section:
        # Also try a broader search in the full text
        pin_table = re.search(r'(?:pin|terminal)\s+(?:name|number|#)', text, re.IGNORECASE)
        if pin_table:
            # Find the table near this match
            start = max(0, pin_table.start() - 200)
            end = min(len(text), pin_table.end() + 2000)
            section = text[start:end]
        else:
            return 0, "Pin Configuration section/table not found"

    cols = _count_table_columns(section)
    if cols >= 4:
        return 10, f"Pin Configuration table has {cols} columns (>=3)"
    elif cols >= 3:
        return 8, f"Pin Configuration table has {cols} columns"
    elif cols >= 2:
        return 5, f"Pin Configuration table has only {cols} columns (need >=3)"
    elif _has_table(section):
        return 3, "Pin Configuration table found but has <2 columns"
    else:
        return 1, "Pin Configuration section exists but no table found"


def check_abs_max_ratings(text: str) -> Tuple[int, str]:
    """Criterion 4: Absolute Maximum Ratings table exists."""
    section = _find_section(text, [r'absolute\s+maximum', r'abs\.?\s+max',
                                   r'絕對最大', r'最大額定值', r'極限值'])
    if not section:
        return 0, "Absolute Maximum Ratings section not found"
    if _has_table(section):
        rows = len([l for l in section.split('\n') if '|' in l and not re.match(r'^\s*\|[\s\-:|]+\|\s*$', l)])
        if rows >= 5:
            return 10, f"Absolute Maximum Ratings table with {rows} parameters"
        elif rows >= 3:
            return 7, f"Absolute Maximum Ratings table with {rows} parameters"
        else:
            return 4, f"Absolute Maximum Ratings table sparse ({rows} parameters)"
    return 2, "Absolute Maximum Ratings section exists but no table"


def check_rec_operating(text: str) -> Tuple[int, str]:
    """Criterion 5: Recommended Operating Conditions with min/typ/max."""
    section = _find_section(text, [r'recommend.*operat', r'operating\s+condition',
                                   r'recommended\s+condition',
                                   r'建議操作', r'推薦工作', r'推薦操作', r'操作條件'])
    if not section:
        return 0, "Recommended Operating Conditions section not found"
    has_table = _has_table(section)
    has_mtm = _has_min_typ_max(section)
    if has_table and has_mtm:
        return 10, "Recommended Operating Conditions with min/typ/max table"
    elif has_table:
        return 6, "Recommended Operating Conditions table exists but no min/typ/max"
    elif has_mtm:
        return 5, "Min/typ/max values mentioned but no proper table"
    else:
        return 2, "Recommended Operating Conditions section exists but incomplete"


def check_electrical_chars(text: str) -> Tuple[int, str]:
    """Criterion 6: Electrical Characteristics with DC+AC sections."""
    section = _find_section(text, [r'electrical\s+char', r'dc\s+char', r'electrical\s+spec',
                                   r'電氣特性', r'電性參數', r'電氣規格'])
    if not section:
        # Try finding DC and AC separately
        dc = _find_section(text, [r'dc\s+char', r'dc\s+spec', r'static\s+char',
                                  r'直流特性', r'靜態特性'])
        ac = _find_section(text, [r'ac\s+char', r'ac\s+spec', r'dynamic\s+char',
                                  r'switching\s+char', r'交流特性', r'動態特性', r'切換特性'])
        if dc and ac:
            section = dc + '\n' + ac
        elif dc or ac:
            section = dc or ac
        else:
            return 0, "Electrical Characteristics section not found"

    lower = section.lower()
    has_dc = bool(re.search(r'dc|static|quiescent|bias|leakage|input.*voltage|output.*voltage|supply.*current|vcc|vdd|idd|直流|靜態|供電|電壓|電流', lower))
    has_ac = bool(re.search(r'ac|dynamic|switching|frequency|bandwidth|slew|propagation|delay|rise.*time|fall.*time|pwm|頻率|延遲|切換|交流|動態', lower))
    has_table = _has_table(section)

    if has_dc and has_ac and has_table:
        return 10, "Electrical Characteristics with DC + AC data and tables"
    elif has_dc and has_ac:
        return 7, "DC + AC mentioned but tables may be incomplete"
    elif (has_dc or has_ac) and has_table:
        kind = "DC" if has_dc else "AC"
        return 6, f"Only {kind} characteristics with table (missing {'AC' if has_dc else 'DC'})"
    elif has_dc or has_ac:
        return 3, "Partial electrical characteristics, no tables"
    else:
        return 1, "Electrical Characteristics section exists but lacks DC/AC data"


def check_timing_diagrams(text: str) -> Tuple[int, str]:
    """Criterion 7: Timing Diagrams present (ASCII art or description)."""
    section = _find_section(text, [r'timing\s+diagram', r'timing\s+waveform',
                                   r'signal\s+timing', r'waveform',
                                   r'時序', r'時序圖', r'時序參數'])
    if not section:
        # Check for timing content in broader text
        timing_refs = re.findall(r'timing\s+diagram|waveform|signal\s+timing|時序', text, re.IGNORECASE)
        if timing_refs:
            return 3, f"Timing diagrams referenced ({len(timing_refs)}x) but no dedicated section"
        return 0, "No timing diagram section or references found"

    has_art = _has_ascii_art(section)
    has_desc = len(section.strip()) > 100

    if has_art and has_desc:
        return 10, "Timing diagram section with ASCII art and description"
    elif has_art:
        return 8, "Timing diagram section with ASCII art"
    elif has_desc:
        return 5, "Timing diagram section with description but no visual"
    else:
        return 2, "Timing diagram section exists but is sparse"


def check_block_diagram(text: str) -> Tuple[int, str]:
    """Criterion 8: Block Diagram present."""
    section = _find_section(text, [r'block\s+diagram', r'functional\s+block',
                                   r'system\s+block', r'architecture\s+diagram',
                                   r'方塊圖', r'功能方塊', r'架構圖', r'功能說明'])
    if not section:
        # Check for inline block diagram
        block_refs = re.findall(r'block\s+diagram|functional\s+diagram|方塊圖|功能說明', text, re.IGNORECASE)
        if block_refs:
            # Try to find ASCII art near references
            for ref_match in re.finditer(r'block\s+diagram', text, re.IGNORECASE):
                nearby = text[ref_match.start():min(len(text), ref_match.end() + 2000)]
                if _has_ascii_art(nearby):
                    return 7, "Block diagram found near reference (not in dedicated section)"
            return 3, "Block diagram referenced but no visual found"
        return 0, "No block diagram section or references found"

    has_art = _has_ascii_art(section)
    has_desc = len(section.strip()) > 80

    if has_art and has_desc:
        return 10, "Block diagram section with visual and description"
    elif has_art:
        return 8, "Block diagram section with visual"
    elif has_desc:
        return 4, "Block diagram section with text description only"
    else:
        return 2, "Block diagram section exists but is sparse"


def check_detailed_description(text: str) -> Tuple[int, str]:
    """Criterion 9: Detailed Description with Register Map (if applicable)."""
    section = _find_section(text, [r'detail.*description', r'functional\s+description',
                                   r'device\s+description', r'theory\s+of\s+operation',
                                   r'詳細說明', r'功能描述', r'暫存器', r'寄存器'])
    if not section:
        section = _find_section(text, [r'register\s+map', r'register\s+description',
                                       r'register\s+table',
                                       r'暫存器映射', r'暫存器表', r'寄存器映射'])
        if section:
            if _has_table(section):
                return 7, "Register Map found (but no detailed description section)"
            return 4, "Register section found but no table"

    if not section:
        return 0, "Detailed Description section not found"

    has_regmap = bool(re.search(r'register\s+map|register\s+addr|register\s+table|0x[0-9A-Fa-f]+',
                                section, re.IGNORECASE))
    has_table = _has_table(section)
    long_enough = len(section.strip()) > 300

    if long_enough and has_regmap and has_table:
        return 10, "Detailed description with register map table"
    elif long_enough and has_regmap:
        return 8, "Detailed description with register references"
    elif long_enough:
        return 6, "Detailed description present but no register map"
    elif has_regmap:
        return 5, "Brief description with register references"
    else:
        return 3, "Detailed description section exists but is brief"


def check_application_info(text: str) -> Tuple[int, str]:
    """Criterion 10: Application Information with circuit."""
    section = _find_section(text, [r'application\s+info', r'typical\s+application',
                                   r'application\s+circuit', r'application\s+and\s+implement',
                                   r'application\s+note', r'application\s+example',
                                   r'應用電路', r'應用資訊', r'典型應用', r'應用範例'])
    if not section:
        return 0, "Application Information section not found"

    has_art = _has_ascii_art(section)
    has_table = _has_table(section)
    has_component_values = bool(re.search(
        r'\d+\s*[kKmMuUnNpP]?[FfHhOoVvAa\u03a9\u2126]', section))
    long_enough = len(section.strip()) > 200

    if has_art and has_component_values and long_enough:
        return 10, "Application Information with circuit diagram and component values"
    elif has_art and long_enough:
        return 8, "Application Information with circuit diagram"
    elif has_component_values and long_enough:
        return 7, "Application Information with component values but no diagram"
    elif long_enough:
        return 5, "Application Information section present but lacks circuit/values"
    elif has_art or has_table:
        return 4, "Application Information with visual but brief"
    else:
        return 2, "Application Information section exists but is sparse"


# ============================================================================
# Main Scorer
# ============================================================================

CRITERIA = [
    ("Features (>=5 items)", check_features),
    ("Description (>=2 paragraphs)", check_description),
    ("Pin Configuration (>=3 col table)", check_pin_config),
    ("Absolute Maximum Ratings table", check_abs_max_ratings),
    ("Recommended Operating Conditions (min/typ/max)", check_rec_operating),
    ("Electrical Characteristics (DC+AC)", check_electrical_chars),
    ("Timing Diagrams (visual)", check_timing_diagrams),
    ("Block Diagram (visual)", check_block_diagram),
    ("Detailed Description + Register Map", check_detailed_description),
    ("Application Information + circuit", check_application_info),
]


def score_datasheet(md_path: str) -> Dict[str, Any]:
    """Score a Markdown datasheet and return JSON-serializable report."""
    path = Path(md_path)
    if not path.exists():
        return {
            "file": str(path),
            "error": f"File not found: {md_path}",
            "total_score": 0,
            "max_score": 100,
            "per_item": [],
        }

    text = path.read_text(encoding='utf-8', errors='replace')

    per_item: List[Dict[str, Any]] = []
    total = 0

    for name, check_fn in CRITERIA:
        score, reason = check_fn(text)
        per_item.append({
            "name": name,
            "score": score,
            "max": 10,
            "reason": reason,
        })
        total += score

    return {
        "file": str(path),
        "total_score": total,
        "max_score": 100,
        "per_item": per_item,
    }


def print_report(result: Dict[str, Any]):
    """Pretty-print the scoring report."""
    print(f"\n{'='*64}")
    print(f"  ds-quality-check -- Datasheet Quality Score")
    print(f"{'='*64}")
    print(f"  File:  {result['file']}")

    if "error" in result:
        print(f"  ERROR: {result['error']}")
        print(f"{'='*64}\n")
        return

    total = result['total_score']
    grade = "EXCELLENT" if total >= 90 else "GOOD" if total >= 70 else "FAIR" if total >= 50 else "POOR"
    print(f"  Score: {total}/100 ({grade})")
    print(f"\n  {'No.':<5}{'Criterion':<45}{'Score':<8}")
    print(f"  {'---':<5}{'---':<45}{'---':<8}")

    for i, item in enumerate(result['per_item'], 1):
        score_str = f"{item['score']}/{item['max']}"
        icon = "PASS" if item['score'] >= 7 else "WARN" if item['score'] >= 4 else "FAIL"
        print(f"  {i:<5}{item['name']:<45}{score_str:<8} [{icon}]")
        print(f"        {item['reason']}")

    print(f"\n  TOTAL: {total}/100")
    if total < 70:
        print(f"  BELOW THRESHOLD: Score must be >=70 for Checkpoint 1 pass")
    print(f"{'='*64}\n")


def main():
    parser = argparse.ArgumentParser(
        description='ds-quality-check: Auto-score a Markdown datasheet (0-100)')
    parser.add_argument('datasheet', help='Path to datasheet Markdown file (e.g., 04_datasheet.md)')
    parser.add_argument('--json', action='store_true', help='Output JSON instead of text report')
    args = parser.parse_args()

    result = score_datasheet(args.datasheet)

    if args.json:
        print(json.dumps(result, indent=2, ensure_ascii=False))
    else:
        print_report(result)

    # Exit with non-zero if below threshold
    sys.exit(0 if result['total_score'] >= 70 else 1)


if __name__ == '__main__':
    main()
