"""vibe-ic#712 — a denied value must not be published as a declaration."""
from __future__ import annotations

import json, subprocess, sys, tempfile
from pathlib import Path

PROGRAMS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROGRAMS))
import _prose_polarity as PP            # noqa: E402
import prose_polarity_consulted_check as G  # noqa: E402


# ── the shared vocabulary ───────────────────────────────────────────────────

def test_the_two_real_sentences_are_both_denials():
    """Verbatim from #706 and #711 — with the value itself neutralised, so no
    PDK, vendor or part number appears in this repo's tests."""
    assert PP.is_denied("This block is NOT targeted at <a process>.")
    assert PP.is_denied("has NO meaning here and is REMOVED, not translated")


def test_a_plain_declaration_is_not_a_denial():
    assert PP.is_denied("Targeted at <a process>, 250nm CMOS.") is None
    assert PP.is_denied("die area 1200 x 900 um") is None


def test_a_parenthetical_qualifier_does_not_read_as_a_denial():
    """#711's measurement: real die statements carry harmless negations inside
    brackets, so those are blanked before looking."""
    assert PP.is_denied("die area 1200 x 900 um (not including seal ring)") is None
    assert PP.is_denied("die area 1200 x 900 um, not applicable here") is not None


def test_the_denial_word_is_returned_not_a_bare_bool():
    """A refusal that names its evidence is checkable; a bare False is not."""
    assert PP.is_denied("this is REMOVED").lower() == "removed"


def test_both_landed_extractors_now_share_one_vocabulary():
    """#706 and #711 each grew a private copy within a day of each other, and
    #711's own comment records why the second had to be written: the blindness
    'survived in the neighbouring field of the same document'."""
    for mod in ("phase1_doc_one_shot_runner", "floorplan_contract"):
        src = (PROGRAMS / f"{mod}.py").read_text()
        assert "_prose_polarity" in src, f"{mod} still carries its own copy"


# ── the gate ────────────────────────────────────────────────────────────────

def _tree(tmp: Path, body: str) -> Path:
    (tmp / "programs").mkdir(parents=True, exist_ok=True)
    (tmp / "programs" / "some_extract.py").write_text(body)
    return tmp


_BLIND = '''
import re
RE = re.compile(r"targets (\\w+)")
def extract(text, rec):
    m = RE.search(text)
    if m:
        rec["pdk_target"] = m.group(1)
    return rec
'''

_AWARE = '''
import re
from _prose_polarity import is_denied
RE = re.compile(r"targets (\\w+)")
def extract(text, rec):
    m = RE.search(text)
    if m and not is_denied(text):
        rec["pdk_target"] = m.group(1)
    return rec
'''


def test_the_gate_sees_a_polarity_blind_extractor(tmp_path):
    assert G.scan(_tree(tmp_path, _BLIND)) == ["some_extract::extract"]


def test_the_gate_clears_one_that_consults_polarity(tmp_path):
    assert G.scan(_tree(tmp_path, _AWARE)) == []


def test_a_grep_that_does_not_write_the_matched_value_is_out_of_scope(tmp_path):
    """The narrowing that keeps the baseline meaningful. 'Any subscript
    assignment' caught 592 functions — every one that greps something and fills
    a dict. Both real defects write the value taken OUT of the prose IN as the
    declaration; that is the shape."""
    body = '''
import re
RE = re.compile(r"foo")
def count(text, rec):
    rec["n"] = len(RE.findall(text))
    rec["seen"] = True
    return rec
'''
    assert G.scan(_tree(tmp_path, body)) == []


def test_no_baseline_is_CANNOT_DETERMINE_not_a_pass(tmp_path):
    _tree(tmp_path, _BLIND)
    r = subprocess.run([sys.executable, str(PROGRAMS / "prose_polarity_consulted_check.py"),
                        "--root", str(tmp_path)],
                       capture_output=True, text=True, timeout=55)
    assert r.returncode == 2
    assert "NOT a pass" in (r.stdout + r.stderr)


def test_a_NEW_polarity_blind_extractor_FAILS(tmp_path):
    root = _tree(tmp_path, "")
    prog = str(PROGRAMS / "prose_polarity_consulted_check.py")
    assert subprocess.run([sys.executable, prog, "--root", str(root),
                           "--write-baseline"], capture_output=True,
                          text=True, timeout=55).returncode == 0
    (root / "programs" / "some_extract.py").write_text(_BLIND)
    r = subprocess.run([sys.executable, prog, "--root", str(root)],
                       capture_output=True, text=True, timeout=55)
    assert r.returncode == 1
    assert "some_extract::extract" in r.stdout
