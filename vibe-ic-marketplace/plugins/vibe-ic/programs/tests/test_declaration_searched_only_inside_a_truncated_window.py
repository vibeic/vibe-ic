"""The truncated-window rule, driven in both directions.

The control the capture recorded is reproduced here as a test in its own right:
a byte-identical declaration inside and outside a head window must not be
decided by the prose above it.
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

PROG = (Path(__file__).resolve().parents[1]
        / "declaration_searched_only_inside_a_truncated_window.py")

#: A head window, searched by a COMPILED pattern — the shape the known
#: instance ships, and the one a rule reading only `re.search(pat, s)` misses.
_DEFECT_HEAD = '''\
import re

_DECL_RE = re.compile(r"ENFORCEMENT:\\s*(\\w+)")


def declared_intent(path):
    text = path.read_text(errors="replace")
    m = _DECL_RE.search(text[:4000])
    return m.group(1) if m else None
'''

#: A tail window is the same class: a bound written to limit size doing the
#: work of a predicate.
_DEFECT_TAIL = '''\
def crashed(evidence):
    text = evidence.read_text(errors="replace")
    return "FATAL" in text[-2000:]
'''

#: The remedy: the window stays for display, the SEARCH sees the whole text.
_REPAIRED = '''\
import re

_DECL_RE = re.compile(r"ENFORCEMENT:\\s*(\\w+)")


def declared_intent(path):
    text = path.read_text(errors="replace")
    m = _DECL_RE.search(text)
    if m is None:
        return None
    if m.start() >= 4000:
        return f"declared outside the 4000-byte window, at byte {m.start()}"
    return m.group(1)


def excerpt(path):
    return path.read_text(errors="replace")[:4000]
'''

#: A window that only feeds OUTPUT is a display bound and is correct.
_DISPLAY_ONLY = '''\
def report(text):
    print(f"stdout tail: {text[-4000:]}")
    return {"head": text[:2000]}
'''

#: Below the floor the constant is an index or a field width, not a window.
_SMALL_INDEX = '''\
def sha_prefix(sha, blob):
    return sha[:12] in blob[:40]
'''


def _tree(body: str, inventory=None, name="sample_audit.py") -> Path:
    root = Path(tempfile.mkdtemp(prefix="tws_"))
    (root / ".git").mkdir()
    progs = root / "vibe-ic-marketplace" / "plugins" / "vibe-ic" / "programs"
    progs.mkdir(parents=True)
    (progs / name).write_text(body)
    (root / "inventory.json").write_text(
        json.dumps({"known": inventory or []}) + "\n")
    return root


def _run(root: Path, inventory: Path = None):
    return subprocess.run(
        [sys.executable, str(PROG), "--root", str(root), "--inventory",
         str(inventory or (root / "inventory.json"))],
        capture_output=True, text=True, timeout=300)


def test_a_head_window_feeding_a_search_is_refused():
    """NEGATIVE CONTROL — the instance the capture measured, reintroduced."""
    r = _run(_tree(_DEFECT_HEAD))
    assert r.returncode == 1, f"rc={r.returncode}\n{r.stdout}\n{r.stderr}"
    assert "text[4000]" in r.stdout
    assert "compiled pattern" in r.stdout


def test_a_tail_window_feeding_a_search_is_refused():
    """The head-slice and the tail-slice shapes are ONE class."""
    r = _run(_tree(_DEFECT_TAIL))
    assert r.returncode == 1, f"rc={r.returncode}\n{r.stdout}\n{r.stderr}"
    assert "-2000" in r.stdout


def test_searching_the_whole_text_is_not_refused():
    r = _run(_tree(_REPAIRED))
    assert r.returncode == 0, (
        f"the remedy was refused (rc={r.returncode})\n{r.stdout}\n{r.stderr}")


def test_a_display_only_window_is_not_refused():
    r = _run(_tree(_DISPLAY_ONLY))
    assert r.returncode == 0, f"rc={r.returncode}\n{r.stdout}\n{r.stderr}"


def test_a_constant_below_the_floor_is_not_a_window():
    r = _run(_tree(_SMALL_INDEX))
    assert r.returncode == 0, f"rc={r.returncode}\n{r.stdout}\n{r.stderr}"


def test_the_control_the_capture_recorded():
    """Same declaration, two byte offsets, opposite verdicts.

    This is the measurement that made the class visible, kept as a test so the
    claim is re-runnable rather than quoted.
    """
    decl_re = re.compile(r"ENFORCEMENT:\s*(\w+)")

    def windowed(text):
        m = decl_re.search(text[:4000])
        return m.group(1) if m else None

    def whole(text):
        m = decl_re.search(text)
        return m.group(1) if m else None

    near = '"""x\nENFORCEMENT: blocking\n"""\n'
    far = '"""' + ("prose. " * 800) + "\nENFORCEMENT: blocking\n" + '"""\n'
    assert far.index("ENFORCEMENT:") > 4000

    assert windowed(near) == "blocking"
    assert windowed(far) is None, (
        "the window did not truncate the far declaration — the control is not "
        "measuring what it claims to")
    assert whole(near) == whole(far) == "blocking", (
        "searching the whole text must give ONE answer for both")


def test_a_stale_inventory_row_is_a_failure():
    r = _run(_tree(_REPAIRED, inventory=[
        {"key": "programs/gone.py::text::head::4000", "reason": "stale"}]))
    assert r.returncode == 1, f"rc={r.returncode}\n{r.stdout}"


def test_a_missing_tree_is_undetermined_not_a_pass():
    r = subprocess.run([sys.executable, str(PROG), "--root", "/nonexistent/jd"],
                       capture_output=True, text=True, timeout=300)
    assert r.returncode == 2, f"rc={r.returncode}\n{r.stdout}\n{r.stderr}"


def test_a_bad_invocation_is_rc_3():
    r = subprocess.run([sys.executable, str(PROG), "--no-such-flag"],
                       capture_output=True, text=True, timeout=300)
    assert r.returncode == 3, f"rc={r.returncode}\n{r.stdout}\n{r.stderr}"


def test_the_shipped_tree_passes_its_own_rule():
    root = Path(__file__).resolve().parents[5]
    if not (root / ".git").exists():
        pytest.skip("not a checkout")
    r = subprocess.run([sys.executable, str(PROG), "--root", str(root)],
                       capture_output=True, text=True, timeout=1800)
    assert r.returncode == 0, f"rc={r.returncode}\n{r.stdout}\n{r.stderr}"
