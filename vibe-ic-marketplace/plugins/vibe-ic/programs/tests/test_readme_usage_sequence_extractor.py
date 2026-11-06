#!/usr/bin/env python3
"""Tests for readme_usage_sequence_extractor.py — README numbered-step
host-usage-sequence picker (feeds L12.behavioral_sequences).

Pins the real heuristics and their false-positive defenses:
  * >=3 consecutive monotone-increasing numbered items,
  * >=half begin with a generic imperative verb (Load/Set/Write/...),
  * >=6 chars of action text after the "N." prefix,
  * a counter reset (or intervening prose line) starts a NEW sequence.
"""
from __future__ import annotations

# programs/ is on sys.path via programs/tests/conftest.py.
import readme_usage_sequence_extractor as mod  # noqa: E402

_extract = mod.extract_usage_sequence_from_readme


# ----------------------------------------------------------------------
# PASS — canonical crypto-IP usage sequence.
# ----------------------------------------------------------------------
def test_canonical_sequence():
    readme = (
        "## Usage\n"
        "1. Load key into key registers\n"
        "2. Set length bit in ctrl\n"
        "3. Write init bit\n"
        "4. Wait for ready\n"
        "5. Read digest\n"
    )
    seqs = _extract(readme)
    assert len(seqs) == 1
    seq = seqs[0]
    assert seq["name"] == "usage_sequence_1"
    assert seq["trigger"] == "host_initiates"
    assert seq["source"] == "readme_usage_sequence"
    assert len(seq["steps"]) == 5
    assert seq["steps"][0]["action"] == "Load key into key registers"
    assert seq["steps"][0]["step"] == 1
    assert all("evidence_line" in s for s in seq["steps"])


def test_automatic_markers_and_indented_prose_reach_l12_consumer(tmp_path):
    import json
    import phase1_doc_one_shot_runner as producer
    text = ('1. Write CONTROL = 1\n'
            '   The update is accepted only while idle.\n'
            '1. Wait for READY\n'
            '1. Read RESULT = 0\n')
    source = tmp_path / 'input/docs/usage.md'
    source.parent.mkdir(parents=True)
    source.write_text(text)
    result = producer.gen_l12_behavioral(tmp_path, {'usage.md': text}, {})
    doc = json.loads(result.path.read_text())
    assert len(doc['behavioral_sequences']) == 1
    steps = doc['behavioral_sequences'][0]['steps']
    assert [s['step'] for s in steps] == [1, 2, 3]
    assert [s['evidence_line'] for s in steps] == [1, 3, 4]
    assert 'accepted only while idle' in steps[0]['action']


def test_automatic_markers_preserve_source_item_minimum():
    assert _extract('1. Write CONTROL = 1\n1. Read RESULT = 0\n') == []
    assert _extract('1. Write CONTROL = 1\n   Wait for READY\n   Read RESULT = 0\n') == []


def test_l12_keeps_procedures_from_each_source_with_unique_names(tmp_path):
    import json
    import phase1_doc_one_shot_runner as producer
    texts = {'startup.md': '1. Write ARM = 1\n2. Wait for READY\n3. Read STATUS = 0\n',
             'shutdown.md': '1. Write ARM = 0\n2. Wait for IDLE\n3. Read STATE = 0\n'}
    docs = tmp_path / 'input/docs'
    docs.mkdir(parents=True)
    for name, text in texts.items():
        (docs/name).write_text(text)
    result = producer.gen_l12_behavioral(tmp_path, texts, {})
    sequences = json.loads(result.path.read_text())['behavioral_sequences']
    assert len(sequences) == 2
    assert len({s['name'] for s in sequences}) == 2
    assert {s['evidence'].split(':line')[0] for s in sequences} == {
        'input/docs/startup.md', 'input/docs/shutdown.md'}


def test_l12_keeps_the_existing_procedure_cap_and_rejects_short_lists(tmp_path):
    import json
    import phase1_doc_one_shot_runner as producer
    procedure = '1. Write ENABLE = 1\n2. Wait for READY\n3. Read RESULT = 0\n'
    texts = {'short.md': '1. Write ENABLE = 0\n2. Read RESULT = 0\n',
             'usage.md': ('\n# Next\n'+procedure)*8, 'overflow.md': procedure}
    docs = tmp_path/'input/docs'
    docs.mkdir(parents=True)
    for name, text in texts.items():
        (docs/name).write_text(text)
    result = producer.gen_l12_behavioral(tmp_path, texts, {})
    sequences = json.loads(result.path.read_text())['behavioral_sequences']
    assert len(sequences) == 8
    assert all(s['evidence'].startswith('input/docs/usage.md:line') for s in sequences)


def test_counter_reset_splits_into_two_sequences():
    readme = (
        "1. Load aaaaaa\n"
        "2. Set bbbbbb\n"
        "3. Write cccccc\n"
        "1. Read dddddd\n"
        "2. Send eeeeee\n"
        "3. Poll ffffff\n"
    )
    seqs = _extract(readme)
    assert len(seqs) == 2
    assert seqs[0]["name"] == "usage_sequence_1"
    assert seqs[1]["name"] == "usage_sequence_2"


# ----------------------------------------------------------------------
# FAIL / floors — the defenses that suppress false positives.
# ----------------------------------------------------------------------
def test_too_few_steps_rejected():
    # Only 2 items -> below the >=3 floor.
    readme = "1. Load the key now\n2. Set the ctrl bit\n"
    assert _extract(readme) == []


def test_non_imperative_prose_list_rejected():
    # Descriptive prose (mostly "The ...") fails the imperative fraction.
    readme = (
        "1. The IP is reset internally on power up\n"
        "2. The block then waits idle until selected\n"
        "3. The output appears on the data bus eventually\n"
    )
    assert _extract(readme) == []


def test_short_action_text_breaks_sequence():
    # An item with <6 chars of action text flushes the run, dropping it
    # below the 3-step floor.
    readme = (
        "1. Load the key value\n"
        "2. Go\n"            # too short -> flush
        "3. Write the data\n"
        "4. Read the result\n"
    )
    # Remaining contiguous run after the flush is only 2 imperative
    # items (Write/Read) -> below floor -> no sequence.
    assert _extract(readme) == []


# ----------------------------------------------------------------------
# Edge — empty / None / no list.
# ----------------------------------------------------------------------
def test_empty_string():
    assert _extract("") == []


def test_none_input():
    assert _extract(None) == []


def test_no_numbered_list():
    assert _extract("Just prose describing the chip, no numbered steps.") == []


# ----------------------------------------------------------------------
# helper-level behavior.
# ----------------------------------------------------------------------
def test_first_word_lower_helper():
    assert mod._first_word_lower("Load the thing") == "load"
    assert mod._first_word_lower("  Set bit") == "set"
    assert mod._first_word_lower("123 not a word") == ""
