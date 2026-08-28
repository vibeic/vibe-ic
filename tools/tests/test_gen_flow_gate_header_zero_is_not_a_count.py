"""A dimension count of zero is this program failing to READ the page.

MEASURED 2026-08-28. `dimension_rows` counted `<td class="dnum">n</td>`. The
page was rewritten on 2026-08-26 with `class="num"`, and from that moment the
count was 0 on every run -- silently. `--check` printed "0 cells" as a derived
figure, and a plain run rewrote a real `cells 612` down to `cells 0` on the
page whose entire subject is that it has 612 cells.

Two spellings, one table; a zero over both is refused, never written.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

for _anc in Path(__file__).resolve().parents:
    if (_anc / "tools" / "gen_flow_gate_header.py").is_file():
        _ROOT = _anc
        break
else:                                                    # pragma: no cover
    raise RuntimeError("gen_flow_gate_header.py not found above this test")

_GEN = _ROOT / "tools" / "gen_flow_gate_header.py"

_HEADER = ('<div class="fg-snapshot"><span>plugin <b>v0.0.1</b></span>'
           '<span>flow steps <b>63</b></span><span>cells <b>612</b></span></div>')

#: The CURRENT shape: a label cell naming the dimension.
_LABELLED = "".join(f'<tr><td>D{i}</td><td class="num">{i}</td></tr>'
                    for i in range(1, 10))
#: The LEGACY shape: one `dnum` cell per row, no label.
_LEGACY = "".join(f'<tr><td class="dnum">{i}</td></tr>' for i in range(1, 10))
#: Neither: a table this program cannot read as dimensions.
_UNREADABLE = '<tr><td class="num">68</td></tr>'


def _page(rows: str) -> str:
    return f"<html><body>{_HEADER}<table>{rows}</table></body></html>"


def _run(tmp_path: Path, rows: str, *args: str):
    p = tmp_path / "page.html"
    p.write_text(_page(rows), encoding="utf-8")
    r = subprocess.run([sys.executable, str(_GEN), "--page", str(p), *args],
                       capture_output=True, text=True)
    return r, p


# ---------------------------------------------------------------- can FAIL --
def test_an_unreadable_table_is_refused_not_written(tmp_path):
    """The measured defect: `cells 612 -> 0`."""
    r, p = _run(tmp_path, _UNREADABLE)
    assert r.returncode == 2, r.stdout + r.stderr
    assert "cells <b>612</b>" in p.read_text(encoding="utf-8"), \
        "the figure was rewritten despite the refusal"
    assert "NOT a pass" in r.stderr


def test_the_refusal_also_holds_under_check(tmp_path):
    r, _ = _run(tmp_path, _UNREADABLE, "--check")
    assert r.returncode == 2, r.stdout + r.stderr


# ---------------------------------------------------------------- can PASS --
def test_the_current_label_shape_is_counted(tmp_path):
    r, _ = _run(tmp_path, _LABELLED, "--check")
    assert "x 9 dimensions" in r.stdout, r.stdout


def test_the_legacy_dnum_shape_is_still_counted(tmp_path):
    """The shape this repo's own liveness fixture uses; losing it is the same bug."""
    r, _ = _run(tmp_path, _LEGACY, "--check")
    assert "x 9 dimensions" in r.stdout, r.stdout


def test_a_bilingual_page_does_not_multiply_its_dimensions(tmp_path):
    """`data-en` carries a second copy of every label; distinct, not counted."""
    doubled = "".join(
        f'<tr><td data-en="D{i}" data-zh="D{i}">D{i}</td></tr>'
        for i in range(1, 10))
    r, _ = _run(tmp_path, doubled, "--check")
    assert "x 9 dimensions" in r.stdout, r.stdout
