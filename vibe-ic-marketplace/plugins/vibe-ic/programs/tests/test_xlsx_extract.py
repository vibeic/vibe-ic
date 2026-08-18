"""Tests for xlsx_extract.py — builds tiny xlsx via openpyxl or zipfile fallback."""
import json
import subprocess
import sys
import zipfile
from pathlib import Path

SCRIPT = Path(__file__).parent.parent / "xlsx_extract.py"
assert SCRIPT.exists()


def _run(*args):
    return subprocess.run([sys.executable, str(SCRIPT), *args],
                          capture_output=True, text=True, timeout=15)


def _make_minimal_xlsx(path: Path, rows):
    """Build a minimal single-sheet xlsx without openpyxl using zip+xml."""
    # This is the "golden minimal" xlsx structure.
    ns = 'xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"'
    sheet_rows = []
    for r_idx, row in enumerate(rows, 1):
        cells = []
        for c_idx, val in enumerate(row):
            col_letter = chr(ord('A') + c_idx)
            cells.append(f'<c r="{col_letter}{r_idx}" t="inlineStr"><is><t>{val}</t></is></c>')
        sheet_rows.append(f'<row r="{r_idx}">{"".join(cells)}</row>')
    sheet_xml = f'<?xml version="1.0"?><worksheet {ns}><sheetData>{"".join(sheet_rows)}</sheetData></worksheet>'
    workbook_xml = f'<?xml version="1.0"?><workbook {ns}><sheets><sheet name="Sheet1" sheetId="1" r:id="rId1" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"/></sheets></workbook>'
    rels_xml = '<?xml version="1.0"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/></Relationships>'
    wb_rels_xml = '<?xml version="1.0"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/></Relationships>'
    content_types = '<?xml version="1.0"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="xml" ContentType="application/xml"/><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/><Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/></Types>'
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("[Content_Types].xml", content_types)
        z.writestr("_rels/.rels", rels_xml)
        z.writestr("xl/workbook.xml", workbook_xml)
        z.writestr("xl/_rels/workbook.xml.rels", wb_rels_xml)
        z.writestr("xl/worksheets/sheet1.xml", sheet_xml)


def test_extracts_minimal_sheet(tmp_path):
    f = tmp_path / "cmd.xlsx"
    _make_minimal_xlsx(f, [
        ["CMD", "Payload", "CRC"],
        ["70", "00", "3D"],
        ["72", "", "71"],
    ])
    out = tmp_path / "result.json"
    r = _run(str(f), "--json", str(out))
    assert r.returncode == 0
    data = json.loads(out.read_text())
    sheet = list(data["files"][0]["sheets"].values())[0]
    assert sheet["header"] == ["CMD", "Payload", "CRC"]
    assert sheet["row_count"] == 2


def test_empty_xlsx_exits_1(tmp_path):
    f = tmp_path / "empty.xlsx"
    _make_minimal_xlsx(f, [])
    r = _run(str(f))
    assert r.returncode == 1


def test_directory_scan(tmp_path):
    _make_minimal_xlsx(tmp_path / "a.xlsx", [["X"], ["1"]])
    _make_minimal_xlsx(tmp_path / "b.xlsx", [["Y"], ["2"]])
    r = _run(str(tmp_path))
    assert r.returncode == 0


def test_non_xlsx_file_exits_2(tmp_path):
    (tmp_path / "foo.txt").write_text("not xlsx")
    r = _run(str(tmp_path / "foo.txt"))
    assert r.returncode == 2
