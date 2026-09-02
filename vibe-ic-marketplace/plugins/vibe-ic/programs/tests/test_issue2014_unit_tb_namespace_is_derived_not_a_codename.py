#!/usr/bin/env python3
"""A private chip codename sat in ordinary matching logic, invisible to the guard.

THE LEAK. `rtl_unit_test_coverage_check.has_tb` matched a module to its unit
testbench by stripping a FIXED set of four leading prefixes, and one of the
four was a private chip codename on `programs/tests/chip_deny_list.txt`. It was
not a guard implementing the deny rule -- those must name the token -- it was
ordinary matching logic keyed on a codename.

AND THE TREE-WIDE GUARD WAS BLIND TO IT. `source_chip_agnostic_check` matches
WORD-BOUNDED, which is the rule `chip_deny_list.txt` states for itself
("Matching is case-insensitive, word-bounded (\\b)"), and the literal carried a
trailing underscore, so `(?<![A-Za-z0-9_])token(?![A-Za-z0-9_])` matched
nothing. MEASURED at `d510241488f9` over all 1357 top-level programs:
word-bounded hits 0, substring hits 49 -- and of those 49, this was the ONLY
one in logic. The other 48 are the published corpus identifier, two guards'
own detection patterns, and docstring prose.

THE REPLACEMENT IS DERIVED, NOT RE-LISTED. `design_namespaces` reads the
design's OWN module stems and calls a leading token run a namespace when two or
more modules wear it, or when removing it names another module in the same
directory. Nothing is written down, so nothing can leak.

THREE CONTROLS, and the third is the one that keeps this from happening again:
POSITIVE (what the codename prefix used to catch is still caught), NEGATIVE (an
unattested prefix is not stripped, so an unrelated testbench is not credited),
and CLEANLINESS (this file names no deny-list token -- asserted with a matcher
that can see the trailing-underscore shape the tree-wide one cannot, because
the file now DECLARES `CHIP_AGNOSTIC: strict` and this is the lane that
enforces a declaration).
"""
import pathlib
import re
import sys

import pytest

PROGRAMS = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROGRAMS))

import rtl_unit_test_coverage_check as C  # noqa: E402
import source_chip_agnostic_check as S    # noqa: E402

SUBJECT = PROGRAMS / "rtl_unit_test_coverage_check.py"
DENY = PROGRAMS / "tests" / "chip_deny_list.txt"


def _deny_tokens():
    return [t for t in (ln.split("#", 1)[0].strip().lower()
                        for ln in DENY.read_text(encoding="utf-8").splitlines())
            if t]


def _sim(tmp_path, names):
    d = tmp_path / "sim_unit"
    d.mkdir(parents=True, exist_ok=True)
    for n in names:
        (d / n).write_text("// tb\n", encoding="utf-8")
    return d


# ---------------------------------------------------------------------------
# CONTROL 1 — POSITIVE: what the codename prefix used to catch is still caught
# ---------------------------------------------------------------------------
def test_two_modules_wearing_one_namespace_attest_it(tmp_path):
    """The shape the removed list existed for: a design namespaces its modules
    and names the testbench after the role. Two modules wear `ns`, so the
    design has attested it, and `tb_rx_phy.v` covers `ns_rx_phy`."""
    stems = {"ns_rx_phy", "ns_tx_phy", "cmd_dispatcher"}
    ns = C.design_namespaces(stems)
    assert "ns" in ns, ns
    sim = _sim(tmp_path, ["tb_rx_phy.v"])
    assert C.has_tb("ns_rx_phy", sim, ns) is not None


def test_the_same_module_spelled_both_ways_attests_it(tmp_path):
    """The second attestation, and it needs no second namespaced module: the
    design itself carries `rx_phy` beside `pfx_rx_phy`. This is the fixture
    shape `test_v1_15_67_unit_tb_denominator` already uses."""
    stems = {"pfx_mac", "rx_phy", "pfx_rx_phy"}
    ns = C.design_namespaces(stems)
    assert "pfx" in ns, ns
    sim = _sim(tmp_path, ["tb_rx_phy.v"])
    assert C.has_tb("pfx_rx_phy", sim, ns) is not None


def test_the_documented_exact_and_alias_matches_are_unchanged(tmp_path):
    """Everything that never depended on the prefix list still holds: the exact
    name, the `cmd_` role alias, and the `_dispatcher` role alias. Those are
    role words, not codenames, and dropping them would have changed verdicts
    beyond the leak."""
    sim = _sim(tmp_path, ["tb_ns_rx_phy.v", "tb_dispatcher.v", "tb_disp.sv"])
    assert C.has_tb("ns_rx_phy", sim, set()) is not None
    assert C.has_tb("cmd_dispatcher", sim, set()) is not None
    assert C.has_tb("uart_dispatcher", sim, set()) is not None


def test_end_to_end_a_namespaced_design_is_covered(tmp_path):
    """Driven through `check`, not just the helper — the namespaces must reach
    it from the module set the run actually has."""
    fsm = "module m;\n  always @(*) case (state) default: ; endcase\nendmodule\n"
    rtl = tmp_path / "rtl"
    rtl.mkdir()
    for stem in ("ns_rx_phy", "ns_tx_phy"):
        (rtl / f"{stem}.v").write_text(fsm, encoding="utf-8")
    sim = _sim(tmp_path, ["tb_rx_phy.v", "tb_tx_phy.v"])
    r = C.check(tmp_path, rtl, sim)
    assert r["module_namespaces"] == ["ns"], r["module_namespaces"]
    assert r["pass"] is True, r["findings"]
    assert r["candidates_total"] == 2, r


# ---------------------------------------------------------------------------
# CONTROL 2 — NEGATIVE: an unattested prefix is not stripped
# ---------------------------------------------------------------------------
def test_a_prefix_only_one_module_wears_is_not_a_namespace(tmp_path):
    """A namespace one module wears is a NAME. Stripping it would credit
    `tb_top.v` — a whole-chip testbench — to a module, which is the
    over-crediting a written list buys silently."""
    stems = {"lone_top", "other_fsm"}
    ns = C.design_namespaces(stems)
    assert "lone" not in ns, ns
    sim = _sim(tmp_path, ["tb_top.v"])
    assert C.has_tb("lone_top", sim, ns) is None


def test_an_unrelated_testbench_is_never_credited(tmp_path):
    """A tb for a DIFFERENT granularity must not cover a module. `phy` is a
    token-boundary suffix of `ns_rx_phy`, and a bare suffix rule would credit
    it; the namespace bound is what stops that."""
    stems = {"ns_rx_phy", "ns_tx_phy"}
    ns = C.design_namespaces(stems)
    sim = _sim(tmp_path, ["tb_phy.v", "tb_ns.v"])
    assert C.has_tb("ns_rx_phy", sim, ns) is None


def test_no_namespace_is_derived_from_an_empty_or_flat_module_set():
    """FAIL-CLOSED. Nothing to read means nothing is stripped — stricter, so
    this can report a missing testbench that was credited before and can never
    credit one that was missing."""
    assert C.design_namespaces(set()) == set()
    assert C.design_namespaces({"alpha", "beta", "gamma"}) == set()


# ---------------------------------------------------------------------------
# CONTROL 3 — the file names no codename, and this test can go RED
# ---------------------------------------------------------------------------
def _codename_hits(text, tokens):
    """Deny tokens in `text`, seeing the shape the tree-wide guard cannot.

    `source_chip_agnostic_check._build_token_re` is word-bounded, which is the
    contract `chip_deny_list.txt` states, and is right for the whole tree —
    `u_hawaii_adc`-style long names are legitimate identifiers. It is NOT
    enough for a file that declares `CHIP_AGNOSTIC: strict`, because the leak
    this test exists for was `<token>_` : a deny token followed by an
    underscore, which word-bounding reads as part of a longer word.

    So this lane adds exactly that shape and nothing else: the token as a whole
    identifier (the canonical matcher, driven, never copied) OR the token
    immediately followed by `_`.
    """
    hits = {m.group(1).lower() for m in S._build_token_re(tokens).finditer(text)}
    low = text.lower()
    for t in tokens:
        if re.search(r"(?<![A-Za-z0-9_])" + re.escape(t) + r"_", low):
            hits.add(f"{t}_")
    return sorted(hits)


def test_the_subject_declares_the_stricter_rule_it_is_held_to():
    """The repo's own mechanism, reused rather than reinvented: a program
    DECLARES its strictness in its header, `source_chip_agnostic_check` READS
    and DISCLOSES it and does not enforce it, and the program's own test is the
    lane that can refuse. This is that lane."""
    strictness, offset = S.declared_strictness_site(
        SUBJECT.read_text(encoding="utf-8"))
    assert strictness == "strict", (strictness, offset)
    assert 0 <= offset < S._STRICTNESS_WINDOW, (
        f"the declaration sits at byte {offset}, past the "
        f"{S._STRICTNESS_WINDOW}-byte window the audit reads")


def test_the_subject_names_no_deny_list_codename():
    tokens = _deny_tokens()
    assert tokens, "the deny list is empty; this control would pass on nothing"
    hits = _codename_hits(SUBJECT.read_text(encoding="utf-8"), tokens)
    assert hits == [], (
        f"{SUBJECT.name} names deny-list token(s) {hits}. A codename in "
        f"matching logic is the leak this file's `design_namespaces` "
        f"replaced; derive the namespace from the design instead.")


def test_this_control_fires_when_a_codename_is_put_back():
    """PROVE IT CAN GO RED. The test above is a zero, and a zero from a matcher
    that cannot see the defect is exactly what let the original leak stand for
    months. Fed the pre-fix line verbatim in shape, it must fire — including
    the trailing-underscore form the tree-wide word-bounded matcher misses.
    """
    tokens = _deny_tokens()
    codename = next((t for t in tokens if "_" not in t and len(t) > 4), None)
    assert codename, tokens
    pre_fix = f'    for prefix in ("aid_", "{codename}_", "u_", "i_"):\n'
    assert _codename_hits(pre_fix, tokens) == [f"{codename}_"], (
        "the control cannot see the shape it exists for")
    # and the tree-wide matcher genuinely cannot — that is why this lane exists
    assert not S._build_token_re(tokens).search(pre_fix), (
        "the word-bounded matcher now sees it; re-derive why this lane is "
        "stricter before keeping it")
