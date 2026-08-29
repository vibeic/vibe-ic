"""A pattern built from NO tokens matches EVERYTHING. It must refuse instead.

`_commercial_pdk`'s detector builders join the NDA tokens into a regex
alternation. Given an EMPTY token set that becomes an alternation of nothing —
`(?<![0-9a-zA-Z])()(?![0-9a-zA-Z])` — which matches the empty string at every
position in any text.

MEASURED before the guard, by driving the two REAL gates from an isolated
authority directory where the token source was unreachable:

    commit_msg_nda_check   FAIL: 4 NDA token occurrence(s) in 3 message(s)
    nda_diff_scan_check    FAIL: 1621 NDA token occurrence(s) in the diff

Both verdicts are false, confident and specific, and a reader has no way to tell
them from a real leak. It is the same defect as returning `("",)` from a prefix
accessor — `name.startswith("")` is true of every name — which is why
`nda_cell_prefixes` is pinned here too.

This is LATENT on a tree whose token store always resolves, and latent is exactly
how it survives to the first change that makes the set resolvable-or-not. It cost
one such change a full diagnosis.

chip-AGNOSTIC: about the shape of a detector, not about any design.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_PROGRAMS = Path(__file__).resolve().parents[1]
if str(_PROGRAMS) not in sys.path:
    sys.path.insert(0, str(_PROGRAMS))

import _commercial_pdk as cpdk  # noqa: E402

_BUILDERS = ("nda_regex_family", "nda_source_regex",
             "nda_source_regex_str", "nda_content_regex")


@pytest.fixture
def no_literals(monkeypatch):
    """Resolve NO tokens — the state of every unconfigured host.

    Was `monkeypatch.setattr(cpdk, "_dec", lambda key: "")`, which simulated an
    unreachable store while the store was eight base64 entries compiled into
    the module. The store is the PRIVATE CONFIG now, so this state is no longer
    a simulation: it is what a public checkout, and any CI job that has not been
    handed the tokens, actually is."""
    monkeypatch.setattr(cpdk, "_nda_token_map", dict)
    return cpdk


@pytest.mark.parametrize("builder", _BUILDERS)
def test_a_builder_refuses_rather_than_returning_an_everything_pattern(
        builder, no_literals):
    with pytest.raises(cpdk.NoNdaLiterals):
        getattr(cpdk, builder)()


def test_the_refusal_says_what_the_caller_must_do(no_literals):
    with pytest.raises(cpdk.NoNdaLiterals) as exc:
        cpdk.nda_content_regex()
    msg = str(exc.value)
    assert "matches EVERYTHING" in msg, msg
    assert "NOT_MEASURED" in msg, msg


def test_the_prefix_accessor_returns_nothing_not_an_empty_prefix(no_literals):
    pfx = cpdk.nda_cell_prefixes()
    assert pfx == (), pfx
    assert "" not in pfx, (
        'an empty prefix makes `name.startswith(p)` true of every name — a '
        'detector that says yes to every subject')


def test_the_guard_is_not_in_the_way_when_the_tokens_ARE_there():
    """The control. Without this, the four tests above are satisfied by builders
    that refuse unconditionally, which would disable the detectors entirely."""
    assert cpdk.nda_tokens(), (
        "this suite resolves a token store (the fixture set, via conftest); "
        "fixture-free arm")
    pat = cpdk.nda_content_regex()
    assert pat.pattern != "", pat.pattern
    assert pat.search("") is None, (
        "the compiled pattern still matches the empty string, so the alternation "
        "is empty despite the tokens resolving")
    assert cpdk.nda_cell_prefixes() and cpdk.nda_cell_prefixes()[0]
