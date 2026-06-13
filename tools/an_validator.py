#!/usr/bin/env python3
"""
an-validator -- Application Note Quality Validator
=====================================================
Scores a Markdown application note on 8 criteria (0-10 each, total /80).

Criteria:
    1. Overview present
    2. Typical Application Circuit (ASCII schematic)
    3. External Component Selection with values
    4. PCB Layout section
    5. Firmware Example with code block
    6. Design Calculations with formulas
    7. FAQ with >=5 items
    8. Competitive Comparison table

Usage:
    python3 an_validator.py <appnote.md>
    python3 an_validator.py <appnote.md> --json
"""

import re
import sys
import json
import argparse
from pathlib import Path
from typing import List, Dict, Any, Tuple


# ============================================================================
# Helpers
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


def _has_table(section_text: str) -> bool:
    """Check for Markdown table separator row."""
    for line in section_text.split('\n'):
        if re.match(r'^\s*\|[\s\-:|]+\|\s*$', line):
            return True
    return False


def _count_table_rows(section_text: str) -> int:
    """Count data rows in Markdown tables (exclude header/separator)."""
    rows = 0
    for line in section_text.split('\n'):
        if '|' in line and not re.match(r'^\s*\|[\s\-:|]+\|\s*$', line):
            rows += 1
    # Subtract header row (first row is typically header)
    return max(0, rows - 1) if rows > 0 else 0


def _has_code_block(section_text: str) -> bool:
    """Check for fenced code blocks (``` ... ```)."""
    return bool(re.search(r'```', section_text))


def _has_ascii_art(section_text: str) -> bool:
    """Detect ASCII art / schematics."""
    if '```' in section_text:
        return True
    if re.search(r'[┌┐└┘├┤┬┴┼─│╔╗╚╝║═]', section_text):
        return True
    art_lines = 0
    for line in section_text.split('\n'):
        stripped = line.strip()
        if len(stripped) > 5 and re.match(r'^[\s\-\+\|_/\\<>\[\](){}=*^~.]+$', stripped):
            art_lines += 1
    return art_lines >= 2


def _count_list_items(section_text: str) -> int:
    """Count bullet/numbered list items."""
    return len(re.findall(r'^\s*[-*+]\s+\S|^\s*\d+\.\s+\S', section_text, re.MULTILINE))


def _count_paragraphs(section_text: str) -> int:
    """Count non-empty paragraph blocks."""
    blocks = re.split(r'\n\s*\n', section_text.strip())
    paragraphs = 0
    for block in blocks:
        block = block.strip()
        if not block:
            continue
        if block.startswith('|') or block.startswith('#') or block.startswith('```'):
            continue
        lines = [l for l in block.split('\n')
                 if l.strip() and not l.strip().startswith(('-', '*', '+', '|', '#'))]
        if lines:
            paragraphs += 1
    return paragraphs


# ============================================================================
# Scoring Functions
# ============================================================================

def check_overview(text: str) -> Tuple[int, str]:
    """Criterion 1: Overview present."""
    section = _find_section(text, [r'overview', r'introduction', r'purpose',
                                   r'about\s+this', r'scope',
                                   r'概述', r'簡介', r'總覽', r'目的'])
    if not section:
        # First section might be the overview without explicit heading
        first_para = re.match(r'^[^#]*?(?=\n#|\Z)', text, re.DOTALL)
        if first_para and len(first_para.group().strip()) > 100:
            return 5, "No explicit Overview heading but substantial introductory text found"
        return 0, "Overview section not found"

    paragraphs = _count_paragraphs(section)
    length = len(section.strip())

    if paragraphs >= 2 and length > 300:
        return 10, f"Overview with {paragraphs} paragraphs, comprehensive"
    elif paragraphs >= 1 and length > 100:
        return 7, f"Overview present ({paragraphs} paragraph(s))"
    elif length > 50:
        return 4, "Overview section is brief"
    else:
        return 2, "Overview section exists but is very sparse"


def check_typical_application(text: str) -> Tuple[int, str]:
    """Criterion 2: Typical Application Circuit (ASCII schematic)."""
    section = _find_section(text, [r'typical\s+application', r'application\s+circuit',
                                   r'circuit\s+schematic', r'reference\s+design',
                                   r'schematic', r'application\s+diagram',
                                   r'典型應用', r'應用電路', r'電路圖', r'參考電路'])
    if not section:
        # Search broadly
        if re.search(r'typical\s+application|application\s+circuit|schematic', text, re.IGNORECASE):
            return 3, "Application circuit referenced but no dedicated section"
        return 0, "Typical Application Circuit section not found"

    has_art = _has_ascii_art(section)
    has_components = bool(re.search(r'R\d|C\d|L\d|D\d|U\d|Q\d|resistor|capacitor|inductor',
                                    section, re.IGNORECASE))
    length = len(section.strip())

    if has_art and has_components and length > 200:
        return 10, "Typical Application with ASCII schematic and component references"
    elif has_art and length > 100:
        return 8, "Typical Application with ASCII schematic"
    elif has_components and length > 200:
        return 6, "Application circuit description with component references but no schematic"
    elif length > 100:
        return 4, "Application section present but lacks visual schematic"
    else:
        return 2, "Application section exists but is sparse"


def check_component_selection(text: str) -> Tuple[int, str]:
    """Criterion 3: External Component Selection with values."""
    section = _find_section(text, [r'component\s+select', r'external\s+component',
                                   r'bill\s+of\s+material', r'BOM',
                                   r'component\s+value', r'design\s+guide',
                                   r'component\s+recommendation',
                                   r'元件選擇', r'外部元件', r'物料清單', r'零件'])
    if not section:
        # Search for component values in broader text
        comp_values = re.findall(
            r'\d+\.?\d*\s*[kKmMuUnNpP]?[FfHhOo\u03a9\u2126]',
            text
        )
        if len(comp_values) >= 5:
            return 4, f"No dedicated section but {len(comp_values)} component values found in text"
        return 0, "External Component Selection section not found"

    has_table = _has_table(section)
    comp_values = re.findall(
        r'\d+\.?\d*\s*[kKmMuUnNpP]?[FfHhOo\u03a9\u2126]',
        section
    )
    has_values = len(comp_values) >= 3

    if has_table and has_values:
        return 10, f"Component selection with table and {len(comp_values)} values"
    elif has_table:
        return 7, "Component selection table present"
    elif has_values:
        return 6, f"Component values mentioned ({len(comp_values)}) but no table"
    else:
        return 3, "Component selection section exists but lacks specific values"


def check_pcb_layout(text: str) -> Tuple[int, str]:
    """Criterion 4: PCB Layout section."""
    section = _find_section(text, [r'PCB\s+layout', r'layout\s+guide', r'layout\s+consider',
                                   r'board\s+layout', r'thermal\s+pad',
                                   r'layout\s+recommend',
                                   r'PCB\s*設計', r'佈局', r'布局', r'電路板'])
    if not section:
        # Check for layout mentions
        layout_refs = re.findall(r'PCB|layout|trace|routing|copper|ground\s+plane',
                                 text, re.IGNORECASE)
        if len(layout_refs) >= 3:
            return 3, "PCB layout topics mentioned but no dedicated section"
        return 0, "PCB Layout section not found"

    has_art = _has_ascii_art(section)
    length = len(section.strip())
    has_guidelines = bool(re.search(
        r'trace|routing|decoupl|bypass|ground\s+plane|via|copper|thermal',
        section, re.IGNORECASE
    ))

    if has_art and has_guidelines and length > 300:
        return 10, "PCB Layout section with diagram and guidelines"
    elif has_guidelines and length > 200:
        return 7, "PCB Layout section with guidelines"
    elif has_art:
        return 6, "PCB Layout section with diagram but brief"
    elif length > 100:
        return 4, "PCB Layout section present but brief"
    else:
        return 2, "PCB Layout section exists but is very sparse"


def check_firmware_example(text: str) -> Tuple[int, str]:
    """Criterion 5: Firmware Example with code block."""
    section = _find_section(text, [r'firmware', r'software\s+example', r'code\s+example',
                                   r'programming\s+example', r'driver\s+example',
                                   r'register\s+access', r'software\s+interface',
                                   r'programming\s+guide',
                                   r'韌體', r'軟體範例', r'程式範例', r'驅動範例'])
    if not section:
        # Check for any code blocks in the document
        code_blocks = re.findall(r'```(?:c|cpp|python|verilog|asm|rust|sv)?.*?```',
                                 text, re.DOTALL)
        if code_blocks:
            return 4, f"No firmware section but {len(code_blocks)} code block(s) found"
        return 0, "Firmware Example section not found"

    has_code = _has_code_block(section)
    has_register_ops = bool(re.search(
        r'read|write|register|0x[0-9A-Fa-f]+|SPI|I2C|GPIO',
        section, re.IGNORECASE
    ))
    length = len(section.strip())

    if has_code and has_register_ops and length > 300:
        return 10, "Firmware example with code block and register operations"
    elif has_code and length > 100:
        return 8, "Firmware example with code block"
    elif has_register_ops and length > 200:
        return 5, "Firmware section with register references but no code block"
    elif has_code:
        return 6, "Code block present but brief"
    else:
        return 3, "Firmware section exists but lacks code examples"


def check_design_calculations(text: str) -> Tuple[int, str]:
    """Criterion 6: Design Calculations with formulas."""
    section = _find_section(text, [r'design\s+calc', r'calculation', r'design\s+equation',
                                   r'design\s+formula', r'design\s+procedure',
                                   r'design\s+example',
                                   r'設計計算', r'計算', r'設計公式', r'設計範例'])
    if not section:
        # Search for formula patterns in entire text
        formulas = re.findall(r'[A-Za-z_]+\s*=\s*[A-Za-z0-9_\s\*/\+\-\(\)]+[/\*]',
                              text)
        if len(formulas) >= 2:
            return 4, f"No dedicated section but {len(formulas)} formula-like expressions found"
        return 0, "Design Calculations section not found"

    # Look for formulas
    formula_patterns = [
        r'[A-Za-z_]+\s*=\s*[A-Za-z0-9_\s\*/\+\-\(\)\.]+',  # basic formula
        r'\$.*?\$',  # LaTeX inline
        r'\\frac',   # LaTeX fraction
        r'[VIRCLf]\s*=',  # V=IR style
    ]
    formula_count = 0
    for pat in formula_patterns:
        formula_count += len(re.findall(pat, section))

    has_numbers = bool(re.search(r'\d+\.?\d*\s*[kKmMuUnNpP]?[FfHhOoVvAa\u03a9\u2126]', section))
    length = len(section.strip())

    if formula_count >= 3 and has_numbers and length > 300:
        return 10, f"Design calculations with {formula_count} formulas and numerical values"
    elif formula_count >= 2 and length > 100:
        return 7, f"Design calculations with {formula_count} formulas"
    elif formula_count >= 1:
        return 5, "Design calculations section with at least one formula"
    elif length > 100:
        return 3, "Design calculations section present but lacks formulas"
    else:
        return 2, "Design calculations section exists but is sparse"


def check_faq(text: str) -> Tuple[int, str]:
    """Criterion 7: FAQ with >=5 items."""
    section = _find_section(text, [r'FAQ', r'frequently\s+asked',
                                   r'common\s+question', r'troubleshoot',
                                   r'Q\s*&\s*A',
                                   r'常見問題', r'疑難排解', r'問答'])
    if not section:
        return 0, "FAQ section not found"

    # Count Q&A items
    # Patterns: "Q:" or "Q1:" or "**Q:**" or numbered questions or bold questions
    qa_patterns = [
        r'^\s*Q\d*[\s:.:]',            # Q: or Q1:
        r'^\s*\*\*Q',                   # **Q...**
        r'^\s*\d+\.\s+\*\*',           # 1. **question**
        r'^\s*###\s+Q',                 # ### Q:
        r'^\s*[-*]\s+\*\*',            # - **question**
    ]
    items = 0
    for pat in qa_patterns:
        items += len(re.findall(pat, section, re.MULTILINE))

    # Also count by looking for question marks in list items or sub-headings
    if items == 0:
        items = len(re.findall(r'^\s*[-*+]\s+.*\?', section, re.MULTILINE))
    if items == 0:
        items = len(re.findall(r'^\s*\d+\.\s+.*\?', section, re.MULTILINE))
    if items == 0:
        items = len(re.findall(r'^#{2,4}\s+.*\?', section, re.MULTILINE))
    # Fallback: count list items as potential Q&A pairs
    if items == 0:
        items = _count_list_items(section) // 2  # assume Q+A pairs

    if items >= 5:
        return 10, f"FAQ section with {items} items (>=5)"
    elif items >= 3:
        return 6, f"FAQ section with {items} items (need >=5 for full score)"
    elif items >= 1:
        return 3, f"FAQ section with only {items} item(s)"
    else:
        return 1, "FAQ section exists but no Q&A items detected"


def check_competitive_comparison(text: str) -> Tuple[int, str]:
    """Criterion 8: Competitive Comparison table."""
    section = _find_section(text, [r'competitiv', r'comparison', r'alternative',
                                   r'benchmark', r'vs\.?\s', r'competitor',
                                   r'競爭', r'比較', r'替代方案', r'競品'])
    if not section:
        # Check if there are comparison mentions anywhere
        comp_refs = re.findall(r'competitor|alternative|compared?\s+to|versus|vs\.?\s',
                               text, re.IGNORECASE)
        if comp_refs:
            return 2, "Competitive comparison mentioned but no dedicated section"
        return 0, "Competitive Comparison section not found"

    has_table = _has_table(section)
    table_rows = _count_table_rows(section)
    length = len(section.strip())

    if has_table and table_rows >= 3 and length > 200:
        return 10, f"Competitive comparison table with {table_rows} products"
    elif has_table and table_rows >= 1:
        return 7, f"Competitive comparison table with {table_rows} product(s)"
    elif has_table:
        return 5, "Comparison table present but sparse"
    elif length > 200:
        return 4, "Competitive comparison text present but no table"
    else:
        return 2, "Competitive comparison section exists but is sparse"


# ============================================================================
# Main Scorer
# ============================================================================

CRITERIA = [
    ("Overview", check_overview),
    ("Typical Application Circuit (ASCII schematic)", check_typical_application),
    ("External Component Selection (values)", check_component_selection),
    ("PCB Layout", check_pcb_layout),
    ("Firmware Example (code block)", check_firmware_example),
    ("Design Calculations (formulas)", check_design_calculations),
    ("FAQ (>=5 items)", check_faq),
    ("Competitive Comparison table", check_competitive_comparison),
]


def score_appnote(md_path: str) -> Dict[str, Any]:
    """Score a Markdown application note and return JSON-serializable report."""
    path = Path(md_path)
    if not path.exists():
        return {
            "file": str(path),
            "error": f"File not found: {md_path}",
            "total_score": 0,
            "max_score": 80,
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
        "max_score": 80,
        "per_item": per_item,
    }


def print_report(result: Dict[str, Any]):
    """Pretty-print the scoring report."""
    print(f"\n{'='*64}")
    print(f"  an-validator -- Application Note Quality Score")
    print(f"{'='*64}")
    print(f"  File:  {result['file']}")

    if "error" in result:
        print(f"  ERROR: {result['error']}")
        print(f"{'='*64}\n")
        return

    total = result['total_score']
    max_score = result['max_score']
    pct = (total / max_score * 100) if max_score > 0 else 0
    grade = "EXCELLENT" if pct >= 90 else "GOOD" if pct >= 70 else "FAIR" if pct >= 50 else "POOR"
    print(f"  Score: {total}/{max_score} ({pct:.0f}%, {grade})")
    print(f"\n  {'No.':<5}{'Criterion':<45}{'Score':<8}")
    print(f"  {'---':<5}{'---':<45}{'---':<8}")

    for i, item in enumerate(result['per_item'], 1):
        score_str = f"{item['score']}/{item['max']}"
        icon = "PASS" if item['score'] >= 7 else "WARN" if item['score'] >= 4 else "FAIL"
        print(f"  {i:<5}{item['name']:<45}{score_str:<8} [{icon}]")
        print(f"        {item['reason']}")

    print(f"\n  TOTAL: {total}/{max_score}")
    if total < 56:
        print(f"  BELOW THRESHOLD: Score must be >=56/80 for Checkpoint 1 pass")
    print(f"{'='*64}\n")


def main():
    parser = argparse.ArgumentParser(
        description='an-validator: Auto-score a Markdown application note (0-80)')
    parser.add_argument('appnote', help='Path to application note Markdown file (e.g., 05_appnote.md)')
    parser.add_argument('--json', action='store_true', help='Output JSON instead of text report')
    args = parser.parse_args()

    result = score_appnote(args.appnote)

    if args.json:
        print(json.dumps(result, indent=2, ensure_ascii=False))
    else:
        print_report(result)

    # Exit with non-zero if below threshold
    sys.exit(0 if result['total_score'] >= 56 else 1)


if __name__ == '__main__':
    main()
