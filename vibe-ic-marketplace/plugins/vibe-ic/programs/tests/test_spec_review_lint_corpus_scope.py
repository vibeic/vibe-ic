"""spec_review_lint.py — the corner-case checklist asks about the SPEC, not a file.

MEASURED DEFECT, quoted from the program's own module header before this fix:
"Of 422 WARNs, 329 (78%) are corner-case-uncovered — and that check is evaluated
PER FILE, so a spec split across 18 chapter files scores up to 72 of them even
when all four corner cases ARE covered by the corpus as a whole."

The other four checks ask a question about ONE document ("is this signal's width
declared?", "does this timing sentence name an edge?") and keep their per-file
attribution. The corner-case checklist asks "does this DESIGN say what happens on
reset during operation?" — a spec split into chapters answers that in whichever
chapter owns the subject, so asking every chapter the same question turns one
design question into N of them.

This fix makes a check fire far LESS often, which is only correct if it still
fires whenever the corpus genuinely fails to address an item. Every direction is
pinned here, and the load-bearing one is direction 3: deleting the single
sentence that covers an item must make the corpus red again.

  1. no document addresses the item      -> reported, exactly ONCE for the corpus
  2. exactly one document addresses it   -> NOT reported
  3. delete that one covering sentence   -> red again (the control)
  4. a single-file spec                  -> unchanged, a corpus of one document
"""
import json
import os
import shutil

import pytest
import subprocess
import sys
from pathlib import Path

SCRIPT = Path(__file__).parent.parent / 'spec_review_lint.py'
assert SCRIPT.exists()


def _lint(argv):
    return subprocess.run([sys.executable, str(SCRIPT), *argv],
                          capture_output=True, text=True)


def _run_corpus(d, extra=()):
    """Lint every .md in `d` in ONE invocation, the way the flow's glob does."""
    jf = d.parent / 'out.json'
    res = _lint(['--strict', '--json', str(jf), *extra,
                 *[str(p) for p in sorted(d.glob('*.md'))]])
    findings = json.loads(jf.read_text())['findings'] if jf.exists() else []
    return res, findings


def uncovered_ids(findings, code='corner-case-uncovered'):
    """The checklist ids reported under `code`, as a LIST so a duplicate report
    of the same item is visible (a set would hide exactly the defect)."""
    return [f['message'].rsplit("item '", 1)[1].split("'", 1)[0]
            for f in findings if f['code'] == code]


# A chapter that addresses nothing on the checklist but is otherwise a clean,
# lintable document: it names a clock, a reset, an edge and an opcode layer, so
# the ONLY findings it can produce are corner-case ones.
CHAPTER = """\
# Chapter {n} — {title}

Interface:
 - input  clk
 - input  rst_n
 - output flag

rst_n is an active-low reset. flag is sampled on the rising edge of clk and is
reset by rst_n. The command word is 0x0 = LOAD, 0x1 = SHIFT, 0x2 = CLEAR, so the
design has an encoded input space.

Chapter {n} describes the {title} of the block in prose.
"""

# The one sentence, in the one chapter, that covers 'reset-during-operation'.
COVERING_SENTENCE = ("A reset asserted during operation clears the accumulator "
                     "and the transfer is abandoned.\n")


def _corpus(tmp_path, n_chapters=8, covering_chapter=None):
    d = tmp_path / 'docs'
    d.mkdir(exist_ok=True, parents=True)
    for i in range(1, n_chapters + 1):
        body = CHAPTER.format(n=i, title=f'part {i}')
        if i == covering_chapter:
            body += COVERING_SENTENCE
        (d / f'c{i:02d}.md').write_text(body)
    return d


# ── direction 1: no document addresses it -> reported exactly once ──────────
def test_an_item_no_document_addresses_is_reported_once_for_the_corpus(tmp_path):
    d = _corpus(tmp_path)
    res, f = _run_corpus(d)
    ids = uncovered_ids(f)
    assert ids.count('reset-during-operation') == 1, (
        f"8 chapters, none addressing it -> exactly one finding, got {ids}")
    assert ids.count('back-to-back') == 1, ids
    assert res.returncode == 1, "an uncovered item must still fail --strict"


def test_every_uncovered_item_is_reported_at_most_once_whatever_the_file_count(tmp_path):
    """The count of corner-case findings must not scale with the file count."""
    small = uncovered_ids(_run_corpus(_corpus(tmp_path / 'a', 2))[1])
    large = uncovered_ids(_run_corpus(_corpus(tmp_path / 'b', 18))[1])
    assert small == large, (small, large)
    assert len(large) == len(set(large)), f"an item reported twice: {large}"


def test_the_corpus_finding_names_the_documents_it_searched(tmp_path):
    """'not addressed' must never be readable as 'not looked for'."""
    d = _corpus(tmp_path, 3)
    res, f = _run_corpus(d)
    msg = [x for x in f
           if x['code'] == 'corner-case-uncovered'][0]['message']
    assert 'searched all 3 document(s)' in msg, msg
    for i in (1, 2, 3):
        assert f'c{i:02d}.md' in msg, msg
    assert [x for x in f if x['code'] == 'corner-case-uncovered'
            ][0]['spec'] == '(corpus)'


# ── direction 2: exactly one document addresses it -> not reported ─────────
def test_an_item_exactly_one_document_addresses_is_not_reported(tmp_path):
    d = _corpus(tmp_path, 8, covering_chapter=5)
    res, f = _run_corpus(d)
    ids = uncovered_ids(f)
    assert 'reset-during-operation' not in ids, (
        f"chapter 5 addresses it for the whole spec, got {ids}")


def test_the_covering_document_may_be_the_first_or_the_last(tmp_path):
    for chapter in (1, 8):
        d = _corpus(tmp_path / f'c{chapter}', 8, covering_chapter=chapter)
        ids = uncovered_ids(_run_corpus(d)[1])
        assert 'reset-during-operation' not in ids, (chapter, ids)


def test_a_pattern_cannot_match_across_a_document_boundary(tmp_path):
    """ADVERSARIAL: two documents that each hold one HALF of a covering phrase
    do not between them cover the item — the corpus is searched as a set of
    documents, not as one run-on string."""
    d = tmp_path / 'docs'
    d.mkdir()
    (d / 'c1.md').write_text(CHAPTER.format(n=1, title='one').rstrip()
                             + "\nThe block performs a reset")
    (d / 'c2.md').write_text("during operation of the sequencer.\n"
                             + CHAPTER.format(n=2, title='two'))
    ids = uncovered_ids(_run_corpus(d)[1])
    assert 'reset-during-operation' in ids, (
        "half a phrase in each of two files is not a covered item: %s" % ids)


# ── direction 3: the control — remove the covering sentence, it goes red ───
def test_removing_the_single_covering_sentence_makes_the_item_red_again(tmp_path):
    """THE LOAD-BEARING CONTROL. Corpus scoping is only correct if the check
    still says no. One sentence in one of eight files is the difference between
    green and red for this item."""
    d = _corpus(tmp_path, 8, covering_chapter=5)
    before_res, before = _run_corpus(d)
    assert 'reset-during-operation' not in uncovered_ids(before)

    covering = d / 'c05.md'
    text = covering.read_text()
    assert COVERING_SENTENCE in text
    covering.write_text(text.replace(COVERING_SENTENCE, ''))

    after_res, after = _run_corpus(d)
    ids = uncovered_ids(after)
    assert ids.count('reset-during-operation') == 1, (
        f"removing the one covering sentence must re-report it: {ids}")
    assert after_res.returncode == 1
    assert (len(uncovered_ids(after)) == len(uncovered_ids(before)) + 1), (
        uncovered_ids(before), ids)


def test_an_uncovered_item_still_fails_the_strict_gate_over_a_big_corpus(tmp_path):
    """A check that could no longer fail a corpus would not be a check."""
    res, _ = _run_corpus(_corpus(tmp_path, 18))
    assert res.returncode == 1


# ── direction 4: a single-file spec is a corpus of one ─────────────────────
#: R-0915-29: the corner-case items only ask about a subject the spec declares,
#: so an UNCOVERED fixture has to DECLARE all four subjects and then address
#: none of them -- otherwise it is measuring applicability, not coverage.
CHAPTER = CHAPTER + """
The block decodes a command word (0x0 = LOAD, 0x1 = SHIFT) arriving on its slave
port and holds an 8-bit accumulator.
"""

SINGLE_UNCOVERED = CHAPTER.format(n=1, title='the whole spec')
SINGLE_COVERED = SINGLE_UNCOVERED + """
A reset asserted during operation clears the accumulator. Back-to-back
transactions are accepted with no idle cycle between them. On overflow the
result saturates and the full flag asserts. An illegal reserved command word
produces defined behaviour: the block holds its output.
"""


def test_a_single_file_spec_reports_every_item_it_does_not_address(tmp_path):
    d = tmp_path / 'docs'
    d.mkdir()
    (d / 'c01.md').write_text(SINGLE_UNCOVERED)
    res, f = _run_corpus(d)
    assert sorted(uncovered_ids(f)) == sorted([
        'reset-during-operation', 'back-to-back',
        'full-empty-overflow-underflow', 'illegal-inputs']), f
    assert res.returncode == 1


def test_a_single_file_spec_that_addresses_everything_reports_nothing(tmp_path):
    d = tmp_path / 'docs'
    d.mkdir()
    (d / 'c01.md').write_text(SINGLE_COVERED)
    res, f = _run_corpus(d)
    assert uncovered_ids(f) == [], f
    assert [x for x in f if x['code'] == 'corner-case-not-applicable'] == [], f


def test_a_single_file_spec_is_a_corpus_of_one_document(tmp_path):
    """Same file, alone: identical verdict whether it is reached as the only
    positional argument or through the corpus path."""
    d = tmp_path / 'docs'
    d.mkdir()
    (d / 'c01.md').write_text(SINGLE_UNCOVERED)
    direct = _lint(['--strict', str(d / 'c01.md')])
    res, _ = _run_corpus(d)
    assert direct.returncode == res.returncode == 1
    assert direct.stdout.count('corner-case-uncovered') == 4


# ── the other checks stay PER FILE ─────────────────────────────────────────
def test_every_other_check_keeps_its_per_file_attribution(tmp_path):
    """Only the corner-case checklist is corpus-scoped, because only it asks a
    question about the spec as a whole. A timing statement missing its edge is
    a defect in the document that holds it, and must be attributed there — and
    two documents with the same defect must yield two findings, not one."""
    d = tmp_path / 'docs'
    d.mkdir()
    # No document-level edge declaration anywhere in either file, so the
    # per-sentence check is the one that decides (see `_REF_EDGE_DOC`).
    bad = ("The output is valid within 5 ns of the request being accepted by "
           "the block.\n")
    (d / 'c01.md').write_text("# Chapter one\n\nThe block forwards data.\n" + bad)
    (d / 'c02.md').write_text("# Chapter two\n\nThe block drains data.\n" + bad)
    _, f = _run_corpus(d)
    timing = [x for x in f if x['code'] == 'timing-no-ref-edge']
    assert len(timing) == 2, f
    assert {Path(x['spec']).name for x in timing} == {'c01.md', 'c02.md'}, timing


def test_a_json_contract_alongside_prose_does_not_break_the_corpus(tmp_path):
    """JSON contracts never ran the prose checklist and still do not; the prose
    documents beside them are still linted as a corpus."""
    d = tmp_path / 'docs'
    d.mkdir()
    (d / 'c01.md').write_text(SINGLE_UNCOVERED)
    (d / 'contract.json').write_text(json.dumps(
        {"module": "TopModule", "ports": [{"name": "clk", "direction": "input"}]}))
    jf = tmp_path / 'out.json'
    res = _lint(['--strict', '--json', str(jf),
                 str(d / 'c01.md'), str(d / 'contract.json')])
    f = json.loads(jf.read_text())['findings']
    assert len(uncovered_ids(f)) == 4, f
    assert res.returncode == 1


@pytest.fixture
def reviewed_native_case(tmp_path, monkeypatch):
    supplied = os.environ.get('VIBEIC_NATIVE_SPEC_CASE')
    if not supplied:
        pytest.skip('requires explicitly staged genuine native source review')
    original = Path(supplied)
    project = tmp_path / 'native'
    project.mkdir()
    for name in ('input', 'phase1', 'reports', 'source'):
        shutil.copytree(original / name, project / name)
    monkeypatch.chdir(project)
    sys.path.insert(0, str(SCRIPT.parent))
    from argparse import Namespace
    import flow109
    args = Namespace(flow='109', flow109_manifest=project/'input/flow109/selection.json',
                     flow109_plan_only=False, execution_mode='default',
                     entry_step='D01', exit_step='D01', delivery_target='rtl', route=None)
    monkeypatch.setenv(flow109.CONTEXT_ENV, '')
    monkeypatch.setenv(flow109.ATTEMPT_ENV, '')
    assert flow109.prepare_front_door(args, project) is None
    return project


def _native_lint(project, source=None):
    target = project / 'reports/native-spec-control.json'
    if target.exists():
        target.unlink()
    selected = [str(source)] if source is not None else ['input/docs/*.md', 'input/docs/*.rst', 'input/*.md']
    result = _lint(['--strict', '--json', str(target), *selected])
    return result, json.loads(target.read_text()) if target.exists() else None


@pytest.mark.parametrize('selection', ['missing_globs', 'single_reviewed_view'])
def test_reviewed_native_spec_consumes_complete_current_population(reviewed_native_case, selection):
    project = reviewed_native_case
    receipt = project / 'reports/audit/ai_judgements/D1.json'
    before = receipt.read_bytes()
    selected = next(iter(sorted((project/'input/docs').rglob('*.md')))) if selection == 'single_reviewed_view' else None
    result, report = _native_lint(project, selected)
    assert result.returncode == 0, (result.stdout, result.stderr)
    native = report['native_input']
    assert native['review']['evidence_sha256'] == json.loads(before)['evidence_sha256']
    from phase1_all_l_docs_present_check import fact_graph_layer_contract
    expected = fact_graph_layer_contract(project)
    assert native['required_outputs'] == expected['required_outputs']
    assert native['facts'] == expected['facts']
    answer = json.loads((project/'reports/audit/phase1/expert_parse_track_pack/l_doc_expectations.json').read_text())
    assert native['source_demands'] == len(answer['source_demands'])
    assert len(native['source_inputs']) > 0
    assert receipt.read_bytes() == before


@pytest.mark.parametrize('damage', ['absent_review', 'wrong_subject_review', 'changed_layer',
                                   'missing_layer', 'changed_original', 'missing_demands',
                                   'absent_scope', 'physical_graph_selection'])
def test_native_spec_refuses_unbound_or_incomplete_reviewed_input(reviewed_native_case, damage):
    project = reviewed_native_case
    before, _ = _native_lint(project)
    assert before.returncode == 0, (before.stdout, before.stderr)
    if damage == 'absent_review':
        (project/'reports/audit/ai_judgements/D1.json').unlink()
    elif damage == 'wrong_subject_review':
        shutil.copy2(os.environ['VIBEIC_NATIVE_SPEC_WRONG_REVIEW'],
                     project/'reports/audit/ai_judgements/D1.json')
    elif damage == 'changed_layer':
        p = project/'phase1/generated_docs/L2_FRS.json'
        value = json.loads(p.read_text())
        value['requirements'][0]['text'] = 'changed source requirement'
        p.write_text(json.dumps(value))
    elif damage == 'missing_layer':
        (project/'phase1/generated_docs/L22_VERIFICATION_PLAN.json').unlink()
    elif damage == 'changed_original':
        p = project/'input/docs/unit.sv'
        p.write_text(p.read_text() + '// changed original bytes\n')
    elif damage == 'missing_demands':
        p = project/'reports/audit/phase1/expert_parse_track_pack/l_doc_expectations.json'
        value = json.loads(p.read_text())
        value['source_demands'].pop()
        p.write_text(json.dumps(value))
    elif damage == 'absent_scope':
        os.environ.pop('VIBEIC_FLOW109_CONTEXT')
    else:
        from phase1_engine.schema import FactGraph
        graph = FactGraph.load(project/'input/phase1_structured.yaml')
        import flow109
        features = next(r['features'] for r in flow109.load_registry()['reference_profiles']
                        if r['features']['physical'])
        graph.metadata['flow109_manifest']['features'] = features
        graph.save(project/'input/phase1_structured.yaml')
    result, _ = _native_lint(project)
    assert result.returncode == 2, (result.stdout, result.stderr)


@pytest.mark.parametrize('input_state', ['unreviewed_file', 'missing_file'])
def test_native_review_does_not_authorize_a_different_explicit_input(reviewed_native_case, input_state):
    project = reviewed_native_case
    before, _ = _native_lint(project)
    assert before.returncode == 0, (before.stdout, before.stderr)
    foreign = project / 'reports/unreviewed-spec.md'
    if input_state == 'unreviewed_file':
        foreign.write_text('A different source document that was never reviewed.\n')
    result, _ = _native_lint(project, foreign)
    assert result.returncode == 2, (result.stdout, result.stderr)


@pytest.mark.parametrize('population', ['reviewed_plus_missing', 'reviewed_plus_unreviewed',
                                       'all_reviewed'])
def test_mixed_explicit_native_inputs_require_every_selected_file(reviewed_native_case, population):
    project = reviewed_native_case
    reviewed = sorted((project/'input/docs').rglob('*.md'))
    assert len(reviewed) >= 2
    if population == 'all_reviewed':
        second = reviewed[1]
    else:
        second = project/'reports/missing-unreviewed-spec.md'
        if population == 'reviewed_plus_unreviewed':
            second.write_text('An explicit document outside the genuine reviewed subject.\n')
    receipt = project/'reports/audit/ai_judgements/D1.json'
    signature = receipt.read_bytes()
    target = project/'reports/mixed-native-spec.json'
    result = _lint(['--strict', '--json', str(target), str(reviewed[0]), str(second)])
    expected = 0 if population == 'all_reviewed' else 2
    assert result.returncode == expected, (result.stdout, result.stderr)
    if population == 'all_reviewed':
        report = json.loads(target.read_text())
        from phase1_all_l_docs_present_check import fact_graph_layer_contract
        full = fact_graph_layer_contract(project)
        assert report['native_input']['required_outputs'] == full['required_outputs']
        assert report['native_input']['facts'] == full['facts']
    assert receipt.read_bytes() == signature
