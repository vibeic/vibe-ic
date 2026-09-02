"""100% capture over a denominator that cannot see the directive.

MEASURED, opentitan_aes on the pristine benchmark-data corpus:
`phase1_doc_input_completeness_check` printed

    PASS — all 11 non-reference input doc(s) at 100% capture

while `prim_generic`, `FIPS-197`, `SP 800-38A` and
`input/reference_flow/pre_syn/` appeared in NONE of the 28 generated L
documents. `_harvest_tokens` found 19 design tokens in the whole NL brief and
every one was an ALL-CAPS acronym: it took `FIPS` but not `FIPS-197`, `NIST`
but not `SP 800-38A`. A lowercase/mixed-case identifier or a path is not one of
its regex families, so the shape an input uses to state a DIRECTIVE never
entered the denominator.

The advisory is deliberately NON-BLOCKING: widening a 100%-capture gate is an
enforcement change whose blast radius must be measured across the corpus first.
These tests pin the reporting, and pin that the verdict does NOT move.
"""
from __future__ import annotations

import sys
from pathlib import Path

_PROGRAMS = Path(__file__).resolve().parents[1]
if str(_PROGRAMS) not in sys.path:
    sys.path.insert(0, str(_PROGRAMS))

import phase1_doc_input_completeness_check as C  # noqa: E402

BRIEF = """
4. Implementation route: REUSED-IP / catalog-glue.
   `input/vendor_rtl/{aes,prim}/` is staged; the prim layer is `prim_generic`.
5. Sign-off target on **sky130A**; the flow reference is staged under
   `input/reference_flow/pre_syn/`.
6. Oracle: the register map must match `input/golden/aes.hjson`, and the
   vectors are NIST FIPS-197 / SP 800-38A.
"""


def test_a_directive_the_l_docs_do_not_carry_is_reported(tmp_path):
    """THE FALSIFIER. Red while the harvester cannot see the directive shape."""
    generated = '{"pdk": "sky130A", "modes": ["ECB", "CBC"]}'
    missing = C._unlanded_directive_tokens(BRIEF, generated)
    for tok in ("prim_generic", "FIPS-197", "SP 800-38A",
                "input/reference_flow/pre_syn/"):
        assert tok in missing, (
            f"the input states `{tok}` as a directive and no L document "
            f"carries it, yet it was not reported: {missing}")


def test_the_oracle_path_is_never_reported_as_unlanded(tmp_path):
    """CONTROL, and a correctness requirement, not a nicety.

    Phase 1 is FORBIDDEN to read the oracle (§4.05). An oracle path named by
    the input MUST NOT land in an L doc, so reporting it as a missing directive
    would tell the operator to commit the one violation the flow exists to
    prevent.
    """
    missing = C._unlanded_directive_tokens(BRIEF, "{}")
    assert not any("golden" in t for t in missing), (
        f"an oracle path was reported as an unlanded directive: {missing}")


def test_a_directive_that_did_land_is_not_reported(tmp_path):
    """DIRECTIONAL CONTROL. A reporter that flags everything reports nothing."""
    generated = ('{"pdk": "sky130A", "prim": "prim_generic", '
                 '"flow": "input/reference_flow/pre_syn/", '
                 '"standards": ["FIPS-197", "SP 800-38A"]}')
    missing = C._unlanded_directive_tokens(BRIEF, generated)
    assert missing == [], f"tokens present in the L docs were reported: {missing}"


def test_prose_and_expressions_are_not_directives():
    """Over-reach control: a NAME has a word in it and no spaces."""
    got = C._harvest_directive_tokens(
        "the `I+1` cell at **3.3** V is `a` and the value is `x`")
    assert got == set(), f"non-name tokens entered the directive set: {got}"


def test_the_advisory_does_not_change_the_verdict(tmp_path):
    """The gate's contract is unchanged: this reports, it does not grade.

    `_report_unlanded_directives` returns its rows and prints; it must not
    raise and must not be consulted for any verdict.
    """
    rows = C._report_unlanded_directives([("brief.txt", BRIEF)], "{}")
    assert rows and rows[0][0] == "brief.txt"
    assert C._report_unlanded_directives([], "{}") == []
    assert C._report_unlanded_directives(
        [("brief.txt", "no directives here at all")], "{}") == []


# --------------------------------------------------------------------------
# THE ARM THAT MATTERS. Everything above imports helpers the pre-fix tree does
# not have, so against main it raises AttributeError — which proves a symbol is
# absent, not that anything BEHAVES wrongly. This one drives the program the
# way the flow does, through its CLI, and asserts on what the operator SEES.
# It collects and runs on either tree.
# --------------------------------------------------------------------------
import json  # noqa: E402
import subprocess  # noqa: E402

_GATE = _PROGRAMS / "phase1_doc_input_completeness_check.py"


def _synthetic_project(tmp_path: Path) -> Path:
    proj = tmp_path / "proj"
    docs = proj / "phase1" / "input_doc"
    docs.mkdir(parents=True)
    (docs / "brief.txt").write_text(BRIEF)
    gen = proj / "phase1" / "generated_docs"
    gen.mkdir(parents=True)
    # Every ALL-CAPS acronym the old harvester collects IS present, so the
    # existing 100%-capture verdict is satisfied and the run reaches PASS.
    (gen / "L1_DATASHEET.json").write_text(json.dumps({
        "pdk": "sky130A", "notes": "REUSED IP NIST FIPS vectors",
        "acronyms": ["ECB", "CBC"],
    }))
    return proj


def test_the_operator_is_told_the_directive_did_not_land(tmp_path):
    """THE BEHAVIOURAL FALSIFIER — red on the pre-fix tree, no AttributeError.

    The gate reaches PASS in BOTH arms (the capture denominator is untouched);
    what changes is whether the four directives are named at all.
    """
    proj = _synthetic_project(tmp_path)
    r = subprocess.run([sys.executable, str(_GATE), str(proj)],
                       capture_output=True, text=True)
    out = r.stdout + r.stderr
    assert "prim_generic" in out, (
        "the input states `prim_generic` and no L document carries it; the "
        f"gate said nothing about it:\n{out}")
    assert "UNLANDED_INPUT_DIRECTIVE" in out, (
        f"no advisory was emitted:\n{out}")
    assert "aes.hjson" not in out, (
        f"the oracle path must never be named as unlanded:\n{out}")


def test_the_advisory_is_not_blocking(tmp_path):
    """DIRECTIONAL CONTROL — passes in BOTH arms, and must.

    The gate's exit code is its contract with the flow. Reporting an unlanded
    directive must not start failing runs that pass today.
    """
    proj = _synthetic_project(tmp_path)
    r = subprocess.run([sys.executable, str(_GATE), str(proj)],
                       capture_output=True, text=True)
    assert r.returncode == 0, (
        f"the advisory changed the verdict (rc={r.returncode}):\n"
        f"{r.stdout}\n{r.stderr}")
