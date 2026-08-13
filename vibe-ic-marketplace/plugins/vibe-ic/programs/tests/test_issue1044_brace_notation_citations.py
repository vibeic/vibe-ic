"""A citation gate that cannot SEE a notation reports PASS over it (vibe-ic#1044).

THE DEFECT
==========
`evidence_citation_resolves_check` extracted citations with

    _CITE_RE = re.compile(r"`([A-Za-z0-9_./+-]+)`")

whose character class excludes `{` and `}`. A brace-notation citation was
therefore never extracted at all — and `_TEMPLATE_RE`, which matches
`\\{[^}]*\\}`, would have discarded it a second time if it had been. So

    `phase3/stage3/multicorner_sta/hold_{ss,tt,ff}.rpt`

named three specific corner reports, none of which exists, and the gate
reported PASS. Nothing distinguished "I checked this and it resolves" from
"this was never in my population".

Brace expansion is NOT a template. `*` and `<...>` decline to name a file;
`{ss,tt,ff}` names three, enumerably, and asks the reader to believe all three
are there.

MEASURED on v1.10.35, default scope: 55 brace tokens expanded into 177
alternatives; 10 of those qualify as evidence citations and ALL TEN dangle.
Citations checked 221 -> 231, unresolved 98 -> 108.

WHAT MUST STAY REJECTED, and is asserted below: `'{...}` (a SystemVerilog
assignment pattern), `${VAR}/...` (shell), and `{a.def, b.def}` (spaces). The
charset still excludes the quote, the dollar and the space, so those tokens
remain unmatchable rather than being resolved as if they named files.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

_PROGRAMS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_PROGRAMS))
import evidence_citation_resolves_check as G  # noqa: E402


# --------------------------------------------------------------------------
# expansion itself
# --------------------------------------------------------------------------

def test_a_single_group_expands_to_each_alternative():
    assert G.expand_braces("a/hold_{ss,tt,ff}.rpt") == [
        "a/hold_ss.rpt", "a/hold_tt.rpt", "a/hold_ff.rpt"]


def test_two_groups_expand_as_a_cartesian_product():
    assert G.expand_braces("x_{a,b}.{log,rpt}") == [
        "x_a.log", "x_a.rpt", "x_b.log", "x_b.rpt"]


def test_a_token_with_no_group_is_returned_unchanged():
    assert G.expand_braces("phase3/openroad.log") == ["phase3/openroad.log"]


def test_a_group_inside_a_directory_component_expands():
    assert G.expand_braces("a/{p12,p3}/x.rpt") == ["a/p12/x.rpt", "a/p3/x.rpt"]


def test_an_empty_alternative_is_kept_rather_than_silently_dropped():
    """Shell keeps it, and dropping it would narrow the claim the document
    made without saying so. It simply fails to resolve."""
    assert G.expand_braces("a/{x,}.log") == ["a/x.log", "a/.log"]


def test_a_pathological_token_is_left_unexpanded_and_stays_a_template():
    """The combinatorial bound is disclosed, not silent: past it the token is
    returned whole and `_TEMPLATE_RE` discards it — the pre-fix behaviour."""
    tok = "a/{1,2}{3,4}{5,6}{7,8}{9,0}.log"          # 5 groups > bound of 4
    assert G.expand_braces(tok) == [tok]
    assert not G._is_citation(tok), "the unexpanded token must stay a template"


# --------------------------------------------------------------------------
# the extractor
# --------------------------------------------------------------------------

def test_the_extractor_now_matches_a_brace_token():
    hits = G._CITE_RE.findall("see `a/hold_{ss,tt}.rpt` for the corners")
    assert hits == ["a/hold_{ss,tt}.rpt"]


@pytest.mark.parametrize("text,why", [
    ("`'{default:0}`", "SystemVerilog assignment pattern (quote)"),
    ("`${REPO_TOP}/hw/x.sh`", "shell variable (dollar)"),
    ("`{a.def, b.def}`", "spaces — prose enumeration, not a path"),
])
def test_non_path_brace_tokens_are_still_not_extracted(text, why):
    """The charset must not have been widened into a licence to resolve
    anything with a brace in it."""
    assert G._CITE_RE.findall(text) == [], why


def test_a_glob_surviving_expansion_is_still_a_template():
    """`{a,spare_*}` expands, and the `spare_*` alternative must still be
    discarded — expansion feeds the unchanged rule, it does not bypass it."""
    alts = G.expand_braces("reports/{coverage,spare_*}.log")
    assert alts == ["reports/coverage.log", "reports/spare_*.log"]
    assert G._is_citation(alts[0])
    assert not G._is_citation(alts[1])


# --------------------------------------------------------------------------
# THE PAIRED GUARD — the issue asks for this by name
# --------------------------------------------------------------------------

def _corpus(tmp_path: Path, doc_text: str, *, ship: tuple = ()) -> Path:
    root = tmp_path / "ic"
    (root / "cell").mkdir(parents=True)
    (root / "cell" / "RESULT.md").write_text(doc_text)
    for rel in ship:
        f = root / "cell" / rel
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text("evidence\n")
    return root


def test_a_dangling_brace_citation_REDDENS(tmp_path):
    """Plant one, prove the gate sees it. Before this fix the same corpus was
    green because the token was never extracted."""
    root = _corpus(tmp_path, "proof: `sta/hold_{ss,tt}.rpt`\n")
    dangling, cited, docs, discarded, bt, ba = G.scan(root, None)

    assert cited == 2, (cited, dangling)
    assert bt == 1 and ba == 2
    got = sorted(d["citation"] for d in dangling)
    assert got == ["sta/hold_ss.rpt", "sta/hold_tt.rpt"], got


def test_the_same_citation_is_GREEN_when_every_alternative_ships(tmp_path):
    """PAIRED with the test above — otherwise 'it reddens' could just mean
    'it reddens on everything'."""
    root = _corpus(tmp_path, "proof: `sta/hold_{ss,tt}.rpt`\n",
                   ship=("sta/hold_ss.rpt", "sta/hold_tt.rpt"))
    dangling, cited, docs, discarded, bt, ba = G.scan(root, None)
    assert cited == 2, cited
    assert dangling == [], dangling


def test_ONE_missing_alternative_is_enough_to_redden(tmp_path):
    """The claim is about every named file, so partial shipping is a partial
    lie and must be caught."""
    root = _corpus(tmp_path, "proof: `sta/hold_{ss,tt}.rpt`\n",
                   ship=("sta/hold_ss.rpt",))
    dangling, cited, docs, discarded, bt, ba = G.scan(root, None)
    assert [d["citation"] for d in dangling] == ["sta/hold_tt.rpt"], dangling


# --------------------------------------------------------------------------
# the denominator the issue asks the gate to report
# --------------------------------------------------------------------------

def test_the_scan_reports_what_it_DISCARDED_not_only_what_it_kept(tmp_path):
    """"N citations checked" without the discard count cannot be told from
    "N were legible and the rest were dropped" — the shape that hid this bug.

    NOTE ON WHAT `discarded` COUNTS, because it is narrower than it sounds and
    a reader should not over-read it: it counts tokens the extractor MATCHED
    and `_is_citation` then rejected. A token the regex never matched at all
    (`a/*.log` — the `*` is not in the charset) is not counted here, because
    the extractor never saw it. That residue is real and is exactly where this
    bug lived, so it is stated rather than implied.
    """
    root = _corpus(tmp_path,
                   "kept `a/x.log`, prose `a/b.md`, data `a/c.json`\n")
    dangling, cited, docs, discarded, bt, ba = G.scan(root, None)
    assert cited == 1, cited
    assert discarded == 2, (discarded, "a/b.md and a/c.json")


def test_a_token_the_regex_never_matches_is_not_counted_as_discarded(tmp_path):
    """The honest bound on the disclosure above, asserted so it cannot drift
    into a claim of completeness."""
    root = _corpus(tmp_path, "glob `a/*.log` only\n")
    dangling, cited, docs, discarded, bt, ba = G.scan(root, None)
    assert cited == 0 and discarded == 0, (cited, discarded)


def test_the_cli_prints_the_extractor_denominator(tmp_path):
    root = _corpus(tmp_path, "proof: `sta/hold_{ss,tt}.rpt`\n")
    r = subprocess.run(
        [sys.executable, str(_PROGRAMS / "evidence_citation_resolves_check.py"),
         str(root)], capture_output=True, text=True, timeout=120)
    assert "extractor" in r.stdout, r.stdout
    assert "discarded" in r.stdout, r.stdout
    assert "brace token" in r.stdout, r.stdout
