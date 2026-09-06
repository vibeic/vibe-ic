#!/usr/bin/env python3
"""Every token `nda_tokens()` NAMES must be matchable by the detector family.

THE DEFECT THIS PINS. `nda_tokens()` named eight roles; `nda_regex_family()` —
and therefore `nda_source_regex()`, `nda_source_regex_str()`, both prose
detectors' `pdk_codename` rule, and `nda_tracked_tree_scan` — joined three of
them. The other five (`foundry_brand1..3`, `ip_vendor`, `ip_part`) were named
by the list the guards call their token store and invisible to the scanner
that enforces "no NDA token in the tracked tree".

MEASURED on the parent commit, fictional fixture set, one token planted per
role into a tracked file of a throwaway repo, `nda_tracked_tree_scan.py`:

    index 0,1,2  ->  rc 1  FAIL
    index 3..7   ->  rc 0  "[PASS] ... no NDA token in any tracked path or
                            content"

That rc 0 is a false clean verdict over a tree that carried a token, so the
constraint was unenforced for five of eight tokens while the gate said clean.
It is the same defect shape as an empty token set matching everything, arriving
from the other end: a list that names more than the pattern can see.

It also caught how the miss stayed invisible: a negative control built with
`sorted(nda_tokens())[0]` plants whichever token sorts first, which lands in
the covered three or the uncovered five by alphabetical accident. A control
that plants an ARBITRARY token measures the alphabet. This file plants EVERY
one and reports by INDEX.

NO TOKEN LITERAL IS WRITTEN, PRINTED OR ASSERTED ON HERE. The planted text is
built from `nda_tokens()` at run time, every failure message names the INDEX
and the ROLE (a role name is not a secret — it says a foundry brand exists,
not which one), and no assertion message interpolates a value.
"""
from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

import pytest

_PROGRAMS = Path(__file__).resolve().parents[1]
if str(_PROGRAMS) not in sys.path:
    sys.path.insert(0, str(_PROGRAMS))

import _commercial_pdk as cpdk  # noqa: E402

_SCAN = _PROGRAMS / "nda_tracked_tree_scan.py"


def _indices():
    """(index, role) for every token `nda_tokens()` NAMES, in `NDA_ROLES` order.

    ANCHORED ON THE LIST, NEVER ON THE FAMILY UNDER TEST. The first draft read
    `nda_regex_family_roles()` here, and a control that narrowed the family
    back to its pre-fix three roles then narrowed this PARAMETRIZATION with it:
    the five uncovered indices were not asserted-and-failed, they were not
    generated. 9 passed, 1 failed, where 5 arms had to fail. A population
    derived from the thing under test moves when it moves, which is the shape
    of "narrow the population to turn a row green" arriving by accident.

    `[]` when this host carries no store — which parametrizes every arm below
    to nothing and leaves the module-level guard to SKIP the file. Not a pass:
    an unconfigured host cannot answer the NDA question, and this is the same
    "refuse, never report clean" rule the builders themselves follow."""
    return [(i, r) for i, r in enumerate(
        [r for r in cpdk.NDA_ROLES if cpdk.nda_token_for(r)])]


pytestmark = pytest.mark.skipif(
    not cpdk.nda_literals_available(),
    reason="no NDA token store on this host (VIBEIC_NDA_TOKENS / the private "
           "config's 'nda_tokens') — NOT_MEASURED, never a pass")


def _token(index: int) -> str:
    """The literal at `index` — used, never printed. By ROLE, from the token
    MAP, for the reason `_indices` gives."""
    return cpdk.nda_token_for(_indices()[index][1])


def _variants(token: str) -> "dict[str, str]":
    """The spellings `nda_content_regex`'s docstring claims to cover."""
    out = {
        "as_is": token,
        "upper": token.upper(),
        "lower": token.lower(),
        "mixed": "".join(c.upper() if i % 2 else c.lower()
                         for i, c in enumerate(token)),
    }
    if " " in token:
        out["underscore"] = token.replace(" ", "_")
        out["hyphen"] = token.replace(" ", "-")
        out["nospace"] = token.replace(" ", "")
        out["multispace"] = token.replace(" ", "   ")
    return out


# ---------------------------------------------------------------------------
# The list and the family are the SAME population.
# ---------------------------------------------------------------------------
def test_the_family_names_every_token_the_list_names():
    """MEMBERSHIP, not counts. Compare the token SETS: a substitution that keeps
    the size (drop one role, add another) is the one thing a count cannot see."""
    assert set(cpdk.nda_regex_family()) == set(cpdk.nda_tokens()), (
        "nda_regex_family() and nda_tokens() name different token sets; a "
        "token the list names that the family cannot match leaves the "
        "constraint unenforced for that token while the scanner reports clean "
        f"(family {len(cpdk.nda_regex_family())} entr(ies), list "
        f"{len(cpdk.nda_tokens())})")


def test_index_and_role_lists_are_aligned():
    assert cpdk.nda_regex_family_roles() == [r for _i, r in _indices()]
    assert len(cpdk.nda_token_patterns()) == len(_indices())


# ---------------------------------------------------------------------------
# Every index fires, in every builder, in every claimed spelling.
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("builder", ["nda_source_regex", "nda_content_regex"])
def test_every_index_fires_in_every_claimed_spelling(builder):
    rx = getattr(cpdk, builder)()
    missed = []
    for index, role in _indices():
        for name, spelling in _variants(_token(index)).items():
            if not rx.search(f"design note: the {spelling} part\n"):
                missed.append(f"index {index} ({role}) spelling {name}")
    assert not missed, (
        f"{builder}() cannot match token(s) that nda_tokens() names: "
        + "; ".join(missed))


def test_every_per_token_pattern_matches_its_own_token_and_no_other():
    """Per-index patterns are what lets a finding be reported as an INDEX. If
    index i also matched token j the report would misattribute the leak."""
    pats = [re.compile(p, re.IGNORECASE) for p in cpdk.nda_token_patterns()]
    assert len(pats) == len(_indices()), (
        f"{len(pats)} per-token pattern(s) for {len(_indices())} named "
        "token(s) — an index in a finding would name the wrong role")
    for index, role in _indices():
        assert pats[index].search(_token(index)), (
            f"pattern index {index} ({role}) does not match its own token")


# ---------------------------------------------------------------------------
# The load-bearing arm: the gate that enforces "no token in the tracked tree".
# ---------------------------------------------------------------------------
@pytest.fixture
def planted(tmp_path):
    """A throwaway git repo with one tracked file, content supplied per test.

    A real repo and the real gate, not the regex: rc 0 from THIS program over a
    tree carrying a token is the false verdict the whole file is about, and it
    is reachable through the pattern builder, the escaping, or the enumeration.
    """
    def _make(text: str) -> Path:
        d = tmp_path / f"repo{len(list(tmp_path.iterdir()))}"
        d.mkdir()
        subprocess.run(["git", "init", "-q", str(d)], check=True)
        (d / "artefact.md").write_text(text, encoding="utf-8")
        subprocess.run(["git", "-C", str(d), "add", "-A"], check=True)
        return d
    return _make


@pytest.mark.parametrize("index,role", _indices())
def test_the_tracked_tree_gate_fires_on_every_named_token(index, role,
                                                          planted):
    d = planted(f"design note: the {_token(index)} process\n")
    r = subprocess.run([sys.executable, str(_SCAN), "--repo", str(d)],
                       capture_output=True, text=True)
    assert r.returncode == 1, (
        f"nda_tracked_tree_scan returned rc {r.returncode} over a tracked "
        f"tree carrying the token at index {index} ({role}) — rc 0 there is "
        f"not a weaker verdict, it is a false one. Gate output (masked by "
        f"the gate itself): {r.stdout.strip()[-300:]}")
    assert str(index) in r.stdout, (
        f"the gate failed but did not attribute the hit to index {index} "
        f"({role}); a finding nobody can attribute is not actionable")


def test_the_gate_still_passes_a_tree_that_carries_no_token(planted):
    """THE CONTROL. Without it, a family that matched EVERYTHING would satisfy
    every test above — which is the exact failure `NoNdaLiterals` exists for."""
    d = planted("design note: a generic open-PDK flow on gf180mcuD\n")
    r = subprocess.run([sys.executable, str(_SCAN), "--repo", str(d)],
                       capture_output=True, text=True)
    assert r.returncode == 0, (
        "the gate fails a tree carrying no NDA token: "
        + r.stdout.strip()[-300:])


def test_the_gate_prints_no_literal_when_it_fires(planted):
    """The gate's stated contract. Checked here because widening the family
    widened what it can print: five more roles now reach the report."""
    d = planted("".join(f"line {i}: {_token(i)}\n" for i, _ in _indices()))
    r = subprocess.run([sys.executable, str(_SCAN), "--repo", str(d)],
                       capture_output=True, text=True)
    assert r.returncode == 1
    for index, role in _indices():
        assert _token(index).lower() not in r.stdout.lower(), (
            f"the gate echoed the literal at index {index} ({role}) into its "
            "own output — a gate that prints what it protects publishes it "
            "into every CI log it runs in")


# ---------------------------------------------------------------------------
# The encoding blind spot.
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("index,role", _indices())
@pytest.mark.parametrize("offset", [0, 1, 2])
def test_the_tracked_tree_gate_sees_a_base64_encoded_token(index, role,
                                                           offset, planted):
    """A plaintext-only tree scan measures the ENCODING, not the exposure.

    This module's own history says so: the store used to be base64 in tracked
    source, defended because `git grep` found nothing. MEASURED 2026-09-07, the
    sibling dataset repo still ships that shape and the PLAINTEXT scan of that
    tree returns rc 0 — a clean verdict over a tree from which every role
    decodes in one call.

    Asserted per BYTE OFFSET, because base64 coverage is offset-dependent and
    the builder says which offsets it covers. Where it says it covers one, the
    gate must fire; where it says it does not (a token too short for an
    8-character invariant fragment), the gate must NOT fire — a fragment that
    short is not a signature, and asserting a hit there would be asserting a
    false positive."""
    import base64
    token = _token(index)
    coverable = bool(cpdk._b64_fragment(token, offset))
    blob = base64.b64encode(("y" * offset + token + "zz").encode()).decode()
    d = planted(f"legacy store: {{'role': '{blob}'}}\n")
    r = subprocess.run([sys.executable, str(_SCAN), "--repo", str(d)],
                       capture_output=True, text=True)
    assert r.returncode == (1 if coverable else 0), (
        f"rc {r.returncode} over a tracked tree carrying the token at index "
        f"{index} ({role}) base64-encoded at offset {offset}; the builder "
        f"declares this offset {'coverable' if coverable else 'NOT coverable'}"
        f" — output: {r.stdout.strip()[-300:]}")


def test_the_encoded_coverage_bound_is_declared_not_discovered():
    """The residual, pinned so it cannot widen silently. Every token gets at
    least one covered offset unless it is shorter than 7 characters, and the
    long ones get all three. If a future token set makes this false, the bound
    moved and someone must say so."""
    for index, role in _indices():
        token = _token(index)
        covered = [o for o in (0, 1, 2) if cpdk._b64_fragment(token, o)]
        if len(token) >= 9:
            assert covered == [0, 1, 2], (
                f"index {index} ({role}) is long enough for a base64 "
                f"signature at every offset but covers {covered}")
        elif len(token) >= 7:
            assert 0 in covered, (
                f"index {index} ({role}) has no covered offset at all")


def test_base64_coverage_is_not_in_the_prose_pattern(planted):
    """THE CONTROL ON THE WIDENING. `nda_source_regex_str()` feeds the backlog
    and practical-notes rules and the commit-message guard; a base64 alternative
    there would start matching ordinary encoded payloads in prose. It must be
    the PLAINTEXT family only."""
    import base64
    rx = cpdk.nda_source_regex()
    for index, _role in _indices():
        blob = base64.b64encode(("x" + _token(index)).encode()).decode()
        assert not rx.search(blob), (
            f"the prose/source pattern matches the base64 form of index "
            f"{index}; that widening belongs to nda_token_patterns() alone")
