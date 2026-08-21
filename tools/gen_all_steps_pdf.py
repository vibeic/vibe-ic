#!/usr/bin/env python3
"""Render an ALL_STEPS Markdown doc to a PDF whose wide tables DO NOT overflow.

The ALL_STEPS docs carry a 7-column step table whose "Programs / Skills" column
holds long `code`-token lists. In portrait A4 that column runs off the right
edge and is clipped (the bug this fixes). The fix is layout, not content:

  * A4 **landscape** (more width for the 7-column table),
  * `table-layout: fixed; width: 100%` so columns share the page width instead
    of pushing past it,
  * `word-break / overflow-wrap: anywhere` on cells and `word-break: break-all`
    on inline `code`, so long unbreakable tokens wrap instead of overflowing.

Engine: python-markdown (tables) -> weasyprint (HTML+CSS -> PDF). Deterministic
and reproducible, replacing the previous hand-synced PDFs.

Usage:
  gen_all_steps_pdf.py <input.md> <output.pdf>
"""
import sys
from pathlib import Path

import markdown
from weasyprint import HTML

_CSS = """
@page { size: A4 landscape; margin: 9mm 8mm; }
* { box-sizing: border-box; }
body {
  font-family: 'Noto Sans CJK TC', 'DejaVu Sans', sans-serif;
  font-size: 8pt; line-height: 1.32; color: #111;
}
h1 { font-size: 15pt; margin: 0 0 6pt; }
h2 { font-size: 12pt; margin: 12pt 0 4pt; border-bottom: 1pt solid #ccc; padding-bottom: 2pt; }
h3 { font-size: 10pt; margin: 9pt 0 3pt; }
h4 { font-size: 8.5pt; margin: 7pt 0 3pt; }
p, li { margin: 2pt 0; }
strong { font-weight: 700; }

table {
  table-layout: fixed;            /* <- columns share the page width; no overflow */
  width: 100%;
  border-collapse: collapse;
  margin: 5pt 0 8pt;
  font-size: 6.6pt;
  line-height: 1.25;
}
th, td {
  border: 0.5pt solid #b0b0b0;
  padding: 2pt 3pt;
  vertical-align: top;
  text-align: left;
  word-break: break-word;         /* <- wrap long cell content */
  overflow-wrap: anywhere;
}
th { background: #eef1f4; font-weight: 700; }
tr:nth-child(even) td { background: #fafbfc; }
/* the leading "#" / id column is narrow; the rest share the remainder */
table td:first-child, table th:first-child { width: 4%; }

code, kbd, tt {
  font-family: 'DejaVu Sans Mono', 'Noto Sans Mono', monospace;
  font-size: 0.9em;
  word-break: break-all;          /* <- long skill/token names wrap */
  white-space: normal;
  background: #f3f4f6; padding: 0 1pt; border-radius: 2px;
}
pre { background: #f3f4f6; padding: 4pt; overflow-wrap: anywhere;
      white-space: pre-wrap; font-size: 7pt; border: 0.5pt solid #ddd; }
pre code { background: none; word-break: normal; }
"""


def render(md_path: Path, pdf_path: Path) -> None:
    text = md_path.read_text(encoding="utf-8")
    html_body = markdown.markdown(
        text,
        extensions=["tables", "fenced_code", "sane_lists", "attr_list", "md_in_html"],
    )
    doc = (
        "<!doctype html><html><head><meta charset='utf-8'>"
        f"<style>{_CSS}</style></head><body>{html_body}</body></html>"
    )
    HTML(string=doc, base_url=str(md_path.parent)).write_pdf(str(pdf_path))
    print(f"  wrote {pdf_path}  ({pdf_path.stat().st_size:,} bytes)")


def main(argv):
    if len(argv) != 3:
        print(__doc__)
        return 2
    render(Path(argv[1]), Path(argv[2]))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
