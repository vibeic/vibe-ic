"""A page whose receipt disagrees with its own headline must not read as fine.

Measured 2026-08-28 on the published PPA review: the headline metric cards said
REMEASURED 1 / ROLLBACK_PROVEN 2, the VERIFICATION RECEIPT below them said 3
and 0, and nothing read both. The receipt is the half a reader trusts most — it
is headed "what this review actually ran" and names a pinned commit — so the
stale half was the authoritative-looking half.

The can-fail arm is that page, byte-for-byte as it was published.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import page_states_one_figure_twice_check as G

_PROGRAMS = Path(G.__file__).resolve().parent

#: The measured defect, reduced to the two shapes it occupied: a metric card
#: and a receipt sentence. Nothing else about the page mattered to it.
_CARD = ('<div class="metric"><span class="metric-val">{v}</span>'
         '<span class="metric-label">{n}</span></div>')
_RECEIPT = '<p>Direct census: DECLARED_ONLY=18, REMEASURED={v}, ROLLBACK_PROVEN={r}.</p>'


def _page(card_rem: int, card_rb: int, prose_rem: int, prose_rb: int) -> str:
    return ("<html><body>"
            + _CARD.format(v=card_rem, n="REMEASURED")
            + _CARD.format(v=card_rb, n="ROLLBACK_PROVEN")
            + _RECEIPT.format(v=prose_rem, r=prose_rb)
            + "</body></html>")


# ---------------------------------------------------------------- can FAIL --
def test_a_receipt_that_disagrees_with_the_headline_is_reported():
    report = G.audit(_page(1, 2, 3, 0))
    names = {c["quantity"] for c in report["conflicts"]}
    assert names == {"REMEASURED", "ROLLBACK_PROVEN"}, report


def test_the_report_names_both_sites_so_neither_is_assumed_current():
    conflict = G.audit(_page(1, 2, 3, 0))["conflicts"][0]
    hows = {s["how"] for s in conflict["sites"]}
    assert hows == {"metric card", "stated in prose"}
    assert sorted(conflict["values"]) == ["1", "3"]


# ---------------------------------------------------------------- can PASS --
def test_a_page_whose_halves_agree_is_clean():
    assert G.audit(_page(1, 2, 1, 2))["conflicts"] == []


def test_two_settings_of_one_knob_are_not_a_contradiction():
    """`MAXEDGES=2` vs `=15` — a NEG/POS experiment, measured on a real page."""
    page = ("<html><body><p>NEG: MAXEDGES=2 fires; POS: MAXEDGES=15 does not.</p>"
            + _CARD.format(v=1, n="REMEASURED") + "</body></html>")
    assert G.audit(page)["conflicts"] == []


def test_a_file_line_citation_is_not_a_figure():
    """`README:30-43` and `README:48-51`, measured on a real page."""
    page = ("<html><body><p>See README:30-43 and README:48-51.</p>"
            + _CARD.format(v=1, n="REMEASURED") + "</body></html>")
    assert G.audit(page)["conflicts"] == []


def test_a_layer_datatype_pair_is_not_a_figure():
    """`met1.PIN=1/2` -> `met1.PIN=68/16`, measured on a real page."""
    page = ("<html><body><p>stock met1.PIN=1/2, real met1.PIN=68/16.</p>"
            + _CARD.format(v=1, n="REMEASURED") + "</body></html>")
    assert G.audit(page)["conflicts"] == []


def test_a_status_cell_beside_an_edge_list_is_not_a_card():
    """A `<td>` next to a `<td>` is a row, and a status in a row is a status."""
    page = ("<html><body>"
            + _CARD.format(v=18, n="DECLARED_ONLY")
            + "<table><tr><td>8&rarr;7 &middot; 14&rarr;9</td>"
              "<td>DECLARED_ONLY</td></tr></table></body></html>")
    assert G.audit(page)["conflicts"] == []


def test_a_sentence_ending_period_is_not_a_decimal_point():
    """The guard that rejects `1/2` must not also reject `...PROVEN=0.`"""
    report = G.audit(_page(2, 2, 2, 0))
    assert {c["quantity"] for c in report["conflicts"]} == {"ROLLBACK_PROVEN"}


# ------------------------------------------------------------- fail-safe ----
def test_a_page_declaring_no_figure_is_cannot_check_not_pass():
    out = subprocess.run(
        [sys.executable, str(_PROGRAMS / "page_states_one_figure_twice_check.py"),
         "/dev/null"], capture_output=True, text=True)
    assert out.returncode == 2, out.stdout


def test_a_missing_page_is_cannot_check_not_pass():
    assert G.main(["/nonexistent-page-for-this-test.html"]) == 2
