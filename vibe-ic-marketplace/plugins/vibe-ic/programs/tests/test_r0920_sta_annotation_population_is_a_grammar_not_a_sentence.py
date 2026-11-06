"""`sta_annotation_population.classify` reads GRAMMAR, not prose — measured.

It is a `_NOT_PROSE` entry in `prose_polarity_consulted_check`, and that claim
has to be MEASURED rather than asserted: an exemption nobody drove is a waiver.
Its two inputs are both machine-written and both closed:

  * OpenSTA's own `report_annotated_delay` banner — `Found <n> unannotated
    drivers.` / `Found <n> partially unannotated drivers.`, anchored at line
    start and line end, with the driver inventory between them COUNTED against
    the banner's own number; plus this flow's `STA_LINK_INSTANCE` /
    `STA_UNCONNECTED_OUTPUT` records, one producer each.
  * a DEF `NETS` / `SPECIALNETS` section, whose statement count is likewise
    checked against the section header's own number.

Neither has a negation form: there is no way to write "this driver is NOT
unannotated" in either. A driver that is annotated is simply ABSENT from the
inventory, and absence is already how this function answers.

So this file drives every token of `_prose_polarity`'s vocabulary — both tiers,
the CJK spellings included — into every position a sentence can physically
occupy around each grammar, and measures that no published answer moves. The
negative controls at the end move the answer deliberately, so a zero here is a
fact about the grammar and not about a fixture that could not move anything.
"""
import sys
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import _prose_polarity as pol  # noqa: E402

_BODY = ("Found 1 unannotated drivers.\n"
         "u_pg/Y\n"
         "Found 0 partially unannotated drivers.\n"
         "STA_LINK_INSTANCE u_pg cellA\n")

_DEF = ("VERSION 5.8 ;\n"
        "DESIGN top ;\n"
        "NETS 1 ;\n"
        "- VSS ( u_pg Y ) + USE GROUND ;\n"
        "END NETS\n"
        "END DESIGN\n")

#: The whole vocabulary, taken from the module rather than restated — a private
#: copy is the divergence `_prose_polarity` exists to end.
_TOKENS = ("not", "no", "none", "without", "excluding", "never", "non",
           "removed", "obsolete", "superseded", "n/a", "inapplicable",
           "deprecated", "no longer", "does not apply",
           "非", "无", "無", "不", "否")

#: A denial that also carries a RIVAL declaration, so a reader that absorbed it
#: would publish something different rather than merely nothing.
def _denial(token: str) -> str:
    return (f"This inventory is {token} applicable: "
            f"Found 0 unannotated drivers.")






def test_every_token_is_a_denial_in_the_shared_vocabulary():
    """The fixture is driving real denials, not arbitrary words."""
    for token in _TOKENS:
        assert pol.is_denied(_denial(token)), token








# ── NEGATIVE CONTROLS: the fixture CAN move the answer ──────────────────────
