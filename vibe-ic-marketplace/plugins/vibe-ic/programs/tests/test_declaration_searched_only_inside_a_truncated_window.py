"""The truncated-window rule, driven in both directions.

The control the capture recorded is reproduced here as a test in its own right:
a byte-identical declaration inside and outside a head window must not be
decided by the prose above it.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


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

#: THE SAME DEFECT WITH THE NUMBER EXTRACTED INTO A NAME. Byte-for-byte the
#: same behaviour as `_DEFECT_HEAD`; the bound is an `ast.Name`, not an
#: `ast.Constant`. A rule that reads literals only goes silent on it, which is
#: how tidying a module can un-detect the defect the module still has.
_DEFECT_NAMED_BOUND = '''\
import re

_DECL_RE = re.compile(r"ENFORCEMENT:\\s*(\\w+)")
DECL_WINDOW_BYTES = 4000


def declared_intent(path):
    text = path.read_text(errors="replace")
    m = _DECL_RE.search(text[:DECL_WINDOW_BYTES])
    return m.group(1) if m else None
'''

#: A NAME THIS RULE MUST REFUSE TO RESOLVE: bound twice, so which number the
#: slice carries is not answerable from the module level. Reporting a size
#: inferred from the wrong binding is worse than the blindness it replaces.
_REBOUND_NAME = '''\
import re

_DECL_RE = re.compile(r"ENFORCEMENT:\\s*(\\w+)")
WINDOW = 4000


def widen():
    global WINDOW
    WINDOW = 10


def declared_intent(text):
    m = _DECL_RE.search(text[:WINDOW])
    return m.group(1) if m else None
'''

#: A flag is not a window. `True` is an `int` in Python and `text[:True]` is a
#: one-byte slice, so resolving it as a size would invent a bound nobody wrote.
_BOOL_NAME = '''\
import re

_DECL_RE = re.compile(r"ENFORCEMENT:\\s*(\\w+)")
STRICT = True


def declared_intent(text):
    m = _DECL_RE.search(text[:STRICT])
    return m.group(1) if m else None
'''






















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
