"""#1410 — two checkers that could not SEE the distinction they were asserting.

Both findings are the same shape and both are FALSE POSITIVES, so both repairs
are to the SCANNER and neither is an exemption:

  * `loop_watchdog_compliance_check` class (b) called
    `gate_host_independence_check.py::_CheckoutClaim.__enter__` an UNBOUNDED
    poll loop. It is a non-blocking flock acquire with
    `deadline = time.monotonic() + self.wait_s` and a `return` on expiry. The
    gate carried zero occurrences of `monotonic` or `deadline`: `loop_guard` was
    the only bound it could recognise.
  * `declaration_searched_only_inside_a_truncated_window` called
    `flow_output_substance.py::_is_probably_binary` a declaration searched
    inside a window. `b"\\x00" in data[:8192]` is git's text/binary heuristic;
    a miss there means "probably text", never "the author declared nothing".

WHAT THIS MODULE PINS is the direction that matters: teaching a scanner to see
a bound must not teach it to stop looking. Every case below is driven in BOTH
directions, and the decisive one is `test_removing_the_deadline_from_the_real_
function_flags_it_again` — the REAL shipped function, with the deadline taken
out together with any independent iteration cap, must redden. That separates
"it learned to see the bound" from
"it learned to ignore that function".

chip-AGNOSTIC: pure AST shapes, no IC / PDK / vendor content.
"""
from __future__ import annotations

import re
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

PROGRAMS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROGRAMS))
import declaration_searched_only_inside_a_truncated_window as D  # noqa: E402

WINDOW_PROG = PROGRAMS / "declaration_searched_only_inside_a_truncated_window.py"






# ══ the truncated-window rule ══════════════════════════════════════════════

def _window_rc(src: str):
    """Run the rule over a one-file tree and return (rc, stdout)."""
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        (root / ".git").mkdir()
        progs = root / "vibe-ic-marketplace" / "plugins" / "vibe-ic" / "programs"
        progs.mkdir(parents=True)
        (progs / "cand.py").write_text(src, encoding="utf-8")
        inv = root / "inv.json"
        inv.write_text('{"known": []}', encoding="utf-8")
        r = subprocess.run([sys.executable, str(WINDOW_PROG),
                            "--root", str(root), "--inventory", str(inv)],
                           capture_output=True, text=True, timeout=600)
        return r.returncode, r.stdout + r.stderr


_SNIFF = '''\
def _is_probably_binary(data):
    return b"\\x00" in data[:8192]
'''

_SNIFF_TUPLE = '''\
def _is_probably_binary(data):
    return data[:8192].startswith((b"\\x00", b"\\xff\\xfe"))
'''

#: THE SAME SHAPE WITH A WORD FOR A NEEDLE. Byte-identical window, byte-
#: identical search; the needle is something an author writes, so a miss here
#: IS a claim that nothing was declared, and it stays a finding.
_DECLARATION_IN_A_WINDOW = '''\
def declared(data):
    return b"ENFORCEMENT" in data[:8192]
'''

_TEXT_DECLARATION_IN_A_WINDOW = '''\
def declared(text):
    return "ENFORCEMENT" in text[:8192]
'''


def test_a_content_type_sniff_is_not_a_declaration_search():
    for src in (_SNIFF, _SNIFF_TUPLE):
        rc, out = _window_rc(src)
        assert rc == 0, out
        assert "content-type sniffs:       1" in out, out


@pytest.mark.parametrize("src", [_DECLARATION_IN_A_WINDOW,
                                 _TEXT_DECLARATION_IN_A_WINDOW])
def test_a_declaration_searched_in_a_window_is_still_refused(src):
    """THE FALSIFICATION FOR THE SNIFF: change the needle from a byte class to
    a word and the identical window is a finding again. The exemption is the
    needle's, not the file's and not the window's."""
    rc, out = _window_rc(src)
    assert rc == 1, out
    assert "8192" in out, out


def test_the_real_sniff_and_its_mutation():
    """The shipped `_is_probably_binary`, read from the tree, and the same
    function with its needle turned into a word."""
    src = (PROGRAMS / "flow_output_substance.py").read_text(encoding="utf-8")
    fn = re.search(r"def _is_probably_binary.*?\n\n", src, re.S)
    assert fn, "the measured site is gone; re-measure before editing this test"
    real = fn.group(0)
    assert _window_rc(real)[0] == 0, real
    mutated = real.replace('b"\\x00"', 'b"ENFORCEMENT"')
    assert mutated != real
    assert _window_rc(mutated)[0] == 1, mutated


def test_the_shipped_tree_still_passes_the_window_rule():
    root = PROGRAMS.parents[3]
    if not (root / ".git").exists():
        pytest.skip("not a checkout")
    r = subprocess.run([sys.executable, str(WINDOW_PROG), "--root", str(root)],
                       capture_output=True, text=True, timeout=1800)
    assert r.returncode == 0, f"rc={r.returncode}\n{r.stdout}\n{r.stderr}"
