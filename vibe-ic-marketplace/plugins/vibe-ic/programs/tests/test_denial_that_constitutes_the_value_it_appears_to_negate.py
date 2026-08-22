"""The constitutive-denial rule, driven in both directions.

The measurement behind this rule is that adding a blanket denial check to a
line classifier broke four passing tests. The table is what makes the repair
possible at all, so the table's own behaviour is asserted here first.
"""
from __future__ import annotations

import re
import json
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

_PROGRAMS = Path(__file__).resolve().parents[1]
PROG = _PROGRAMS / "denial_that_constitutes_the_value_it_appears_to_negate.py"

sys.path.insert(0, str(_PROGRAMS))
import _prose_polarity as P                                    # noqa: E402

#: An extractor whose subject IS the freedom, carrying a blanket denial check.
#: This is the repair that was measured FAILING and reverted.
_DEFECT = '''\
import _prose_polarity as pol


def extract_unconstrained_paths(text, record):
    for line in text.splitlines():
        if "clock period" not in line:
            continue
        if pol.is_denied(line):
            continue
        record["unconstrained_paths"] = line
    return record
'''

#: The remedy: ask WHICH of the two the denial is.
_REPAIRED = '''\
import _prose_polarity as pol


def extract_unconstrained_paths(text, record):
    for line in text.splitlines():
        if "clock period" not in line:
            continue
        kind, word = pol.classify_denial("freedom", line)
        if kind == "negating":
            continue
        record["unconstrained_paths"] = line
    return record
'''

#: An extractor of a real quantity. A blanket denial check there is CORRECT and
#: is what #712 asked for; flagging it would refuse the other repair.
_NEGATING_CONCEPT = '''\
import _prose_polarity as pol


def extract_clock_period_ns(text, record):
    for line in text.splitlines():
        if "clock period" not in line:
            continue
        if pol.is_denied(line):
            continue
        record["clock_period_ns"] = line
    return record
'''

#: The same blanket check written out longhand.
_INLINE = '''\
import re


def extract_optional_ports(text, record):
    for line in text.splitlines():
        if re.search(r"\\b(?:not|no|none|never)\\b", line):
            continue
        record["optional_ports"] = line
    return record
'''


# ───────────────────────── the table itself ─────────────────────────────────
def test_the_table_is_keyed_by_the_extracted_concept():
    """The same words must mean opposite things to two extractors."""
    sentence = "the clock period is not specified"
    assert P.classify_denial("freedom", sentence)[0] == "constitutive"
    assert P.classify_denial("clock_period_ns", sentence)[0] == "negating"


def test_constitutive_is_tested_before_negating():
    """Every constitutive idiom ALSO matches the negation vocabulary.

    That is precisely what makes the blanket check wrong here, so testing
    negation first would classify all of them as negations and the table would
    change nothing.
    """
    for concept, idioms in P.CONSTITUTIVE_IDIOMS.items():
        span = {"freedom": "it is not specified",
                "optionality": "it is not required",
                "absence": "there is no reset",
                "exclusion": "excluding the seal ring"}[concept]
        assert P.is_denied(span) is not None, (
            f"{concept}: the control needs a span the BLANKET check would "
            f"reject, or it proves nothing")
        kind, word = P.classify_denial(concept, span)
        assert kind == "constitutive", (concept, span, kind, word)
        assert word


def test_the_table_is_not_narrower_than_the_denial_vocabulary_it_overrides():
    """A constitutive table must cover every language `is_denied` already does.

    THE ASYMMETRY IS THE BUG. `_DENIAL_CORE` has shipped a CJK tier since
    before this table existed, so `is_denied` fires on those sentences today.
    If the constitutive table were narrower, `classify_denial` would fall
    through to the negation branch and return "negating" for a sentence whose
    denial IS the value — which is precisely the inversion this rule exists to
    prevent, just in another language.

    MEASURED, by rebuilding the table with its non-ASCII entries removed and
    re-classifying the same four spans: two of the four flip to "negating" —
    the two on which the shipped `is_denied` already fires. So the entries are
    load-bearing, and this test is what says so.
    """
    spans = {"freedom": "時脈週期未指定",
             "optionality": "非必要",
             "absence": "此設計無 reset",
             "exclusion": "除外 seal ring"}
    assert set(spans) == set(P.CONSTITUTIVE_IDIOMS), (
        "a concept was added to the table with no cross-language control; add "
        "one here or the parity claim stops covering it")
    for concept, span in spans.items():
        kind, word = P.classify_denial(concept, span)
        assert kind == "constitutive", (
            f"{concept}: {span!r} classified {kind!r} via {word!r}. A denial "
            f"that CONSTITUTES the value must never be read as negating it.")


def test_dropping_the_non_ascii_entries_would_invert_two_of_the_four():
    """The negative control for the test above, run in-process.

    It rebuilds the table English-only and asserts the damage is real, so the
    parity test cannot quietly become vacuous if the vocabulary changes.
    """
    eng = {c: tuple(i for i in ids if i.isascii())
           for c, ids in P.CONSTITUTIVE_IDIOMS.items()}
    pats = {c: re.compile("(?:" + "|".join(i) + ")", re.IGNORECASE)
            for c, i in eng.items() if i}
    spans = {"freedom": "時脈週期未指定", "optionality": "非必要",
             "absence": "此設計無 reset", "exclusion": "除外 seal ring"}

    inverted = []
    for concept, span in spans.items():
        pat = pats.get(concept)
        if pat is not None and pat.search(span):
            continue                       # still constitutive, no damage
        if P.is_denied(span) is not None:
            inverted.append(concept)       # falls through to "negating"

    assert sorted(inverted) == ["absence", "optionality"], (
        f"the control measured {sorted(inverted)}; if this set has changed, the "
        f"vocabulary moved and the parity test above needs re-deriving, not "
        f"re-asserting")


def test_a_sentence_with_no_denial_is_neither():
    assert P.classify_denial("freedom", "the clock period is 10 ns") == \
        ("none", None)


# ───────────────────────── the rule ─────────────────────────────────────────
def _tree(body: str, inventory=None) -> Path:
    root = Path(tempfile.mkdtemp(prefix="cdn_"))
    (root / ".git").mkdir()
    progs = root / "vibe-ic-marketplace" / "plugins" / "vibe-ic" / "programs"
    progs.mkdir(parents=True)
    (progs / "sample_extract.py").write_text(body)
    (root / "inventory.json").write_text(
        json.dumps({"known": inventory or []}) + "\n")
    return root


def _run(root: Path, inventory: Path = None):
    return subprocess.run(
        [sys.executable, str(PROG), "--root", str(root), "--inventory",
         str(inventory or (root / "inventory.json"))],
        capture_output=True, text=True, timeout=300)


def test_a_blanket_check_on_a_constitutive_extractor_is_refused():
    """NEGATIVE CONTROL — the repair that was measured failing, reintroduced."""
    r = _run(_tree(_DEFECT))
    assert r.returncode == 1, f"rc={r.returncode}\n{r.stdout}\n{r.stderr}"
    assert "extract_unconstrained_paths" in r.stdout
    assert "freedom" in r.stdout


def test_the_inline_form_is_the_same_check(  ):
    r = _run(_tree(_INLINE))
    assert r.returncode == 1, f"rc={r.returncode}\n{r.stdout}\n{r.stderr}"
    assert "inline denial regex" in r.stdout


def test_consulting_the_table_is_not_refused():
    r = _run(_tree(_REPAIRED))
    assert r.returncode == 0, (
        f"the remedy was refused (rc={r.returncode})\n{r.stdout}\n{r.stderr}")


def test_a_blanket_check_on_a_negating_concept_is_correct():
    """It is what #712 asked for. Flagging it would refuse the other repair."""
    r = _run(_tree(_NEGATING_CONCEPT))
    assert r.returncode == 0, f"rc={r.returncode}\n{r.stdout}\n{r.stderr}"


def test_a_stale_inventory_row_is_a_failure():
    r = _run(_tree(_REPAIRED), )
    assert r.returncode == 0
    r2 = _run(_tree(_REPAIRED, inventory=[
        {"key": "programs/gone.py::f::freedom", "reason": "stale"}]))
    assert r2.returncode == 1, f"rc={r2.returncode}\n{r2.stdout}"


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
    assert "constitutive extractors:" in r.stdout
