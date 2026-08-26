"""spec_review_lint.py — a markdown BLOCKQUOTE line is structure, not prose.

MEASURED DEFECT. Run the way the flow runs it over the nine published corpus
cells, `spm` was down to 2 findings / 1 WARN, and that single WARN was the only
thing keeping the cell red. It was `timing-no-ref-edge` raised on

    > (a status annotation naming the baseline configuration and a clock period)

in `L7_verification_plan.md` — a status note ABOUT the run, not a sentence of
the spec stating a timing requirement. `_prose_lines_only` already drops the
markdown structures whose marker declares "this line is not a sentence" (fenced
code, table rows and rules, ATX headings); a blockquote marker is the same kind
of declaration and was the only one missing.

THIS FIX MAKES A CHECK SAY NO LESS OFTEN, so both directions are pinned here,
and the load-bearing direction is the FIRST one:

  1. a genuine PROSE timing sentence with no reference edge is STILL reported —
     the control that proves the check was narrowed, not disabled
  2. the same sentence inside a blockquote is NOT reported
  3. the rest of a document that CONTAINS a blockquote is still linted, so the
     rule drops a line and not a section
  4. THE COST, chosen deliberately and pinned rather than hidden: a genuine
     requirement that merely HAPPENS to be quoted is dropped too. The rule is
     structural and cannot tell a quoted requirement from a quoted status note;
     it is accepted because, measured over every blockquote line in every linted
     document of the published corpus, a blockquote is where these specs put
     annotation ABOUT normative text (baseline status, rationale, clarification,
     a quoted source) and never where a requirement is first stated. Test 4 is
     what would have to change first if that ever stopped being true.
"""
import json
import subprocess
import sys
from pathlib import Path

SCRIPT = Path(__file__).parent.parent / 'spec_review_lint.py'
assert SCRIPT.exists()


def run(tmp_path, spec_text, name='spec.md'):
    spec = tmp_path / name
    spec.write_text(spec_text, encoding='utf-8')
    jf = tmp_path / f'{name}.out.json'
    res = subprocess.run(
        [sys.executable, str(SCRIPT), '--strict', '--json', str(jf), str(spec)],
        capture_output=True, text=True)
    findings = json.loads(jf.read_text())['findings'] if jf.exists() else []
    return res, findings


def timing(findings):
    return [f for f in findings if f['code'] == 'timing-no-ref-edge']


# A document that is clean on every OTHER check — every declared signal has
# direction/polarity/clock/reset, every mode is absent, and all four corner-case
# checklist items are addressed — so the ONLY finding it can produce is the
# timing one under test. {timing} is the line the test varies.
DOC = """\
Implement TopModule.
 - input  clk
 - input  rst_n
 - output q
rst_n is an active-low asynchronous reset; q is registered synchronous to clk
and reset by rst_n. A reset during operation clears q. Back-to-back requests are
accepted. On overflow it saturates; on empty underflow it holds. Illegal opcodes
are ignored.
{timing}
"""

# A timing statement with NO reference edge anywhere in it.
SENTENCE = "The output must meet a 3 ns setup."

# The shape that was raised on spm: a status annotation carrying the baseline
# configuration and a clock period. Not a sentence of the spec.
STATUS = ("> **Baseline status**: `size = 32` / `sky130A` / TT corner / 10 ns "
          "signed off clean.")


# ---- 1. THE CONTROL: prose timing with no ref edge is STILL reported -------
def test_prose_timing_without_ref_edge_is_still_reported(tmp_path):
    res, f = run(tmp_path, DOC.format(timing=SENTENCE))
    assert len(timing(f)) == 1, f
    assert res.returncode == 1, res.stdout


# ---- 2. the blockquote status annotation is NOT a prose sentence ----------
def test_blockquote_status_annotation_is_not_reported(tmp_path):
    res, f = run(tmp_path, DOC.format(timing=STATUS))
    assert timing(f) == [], f
    assert res.returncode == 0, res.stdout


def test_the_same_status_line_unquoted_is_reported(tmp_path):
    """Pairs with the test above: removing ONLY the blockquote marker brings the
    finding back, so it is the marker doing the work and not the wording."""
    res, f = run(tmp_path, DOC.format(timing=STATUS.lstrip('> ')))
    assert len(timing(f)) == 1, f
    assert res.returncode == 1, res.stdout


# ---- 3. a blockquote drops its LINE, not the document around it -----------
def test_prose_beside_a_blockquote_is_still_linted(tmp_path):
    res, f = run(tmp_path, DOC.format(timing=f"{STATUS}\n\n{SENTENCE}"))
    assert len(timing(f)) == 1, f
    assert '3 ns setup' in timing(f)[0]['message'], f


def test_lazy_and_indented_blockquote_markers_are_recognised(tmp_path):
    """Markdown allows `>` with no following space and up to three leading
    spaces; both are blockquotes and neither may leak back in as prose."""
    for i, marker in enumerate(('>', '   > ', '>  ')):
        res, f = run(tmp_path, DOC.format(timing=marker + SENTENCE),
                     name=f'lazy{i}.md')
        assert timing(f) == [], (marker, f)


# ---- 4. THE COST, pinned rather than hidden -------------------------------
def test_a_genuine_requirement_that_is_quoted_is_dropped_too(tmp_path):
    """ACCEPTED COST. `> Requirement R7: <a real timing requirement>` is a real
    requirement that merely happens to be quoted, and this rule silences it.
    The rule is structural and cannot tell it from a quoted status note. This
    test exists so the cost is visible and so a change of policy has to come
    here first — it is NOT a claim that the quoted requirement is fine."""
    quoted = f"> Requirement R7: {SENTENCE}"
    res, f = run(tmp_path, DOC.format(timing=quoted))
    assert timing(f) == [], f
    # ... and the identical requirement, unquoted, IS still caught. The cost is
    # exactly the blockquote marker and nothing wider.
    res2, f2 = run(tmp_path, DOC.format(timing=f"Requirement R7: {SENTENCE}"),
                   name='unquoted.md')
    assert len(timing(f2)) == 1, f2
