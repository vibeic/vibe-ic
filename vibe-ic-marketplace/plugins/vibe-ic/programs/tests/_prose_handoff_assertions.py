"""Assertions for the named prose-author contract accepted by ruling 100c."""
import re


def _assert_span(lo, hi, sentence, source_text):
    assert type(lo) is int and type(hi) is int
    assert 0 <= lo < hi
    assert isinstance(sentence, str) and sentence.strip()
    assert hi - lo == len(sentence)
    if source_text is not None:
        assert source_text[lo:hi] == sentence


def assert_prose_handoff(result, source_text=None):
    assert result.status == 'PASS_WITH_WAIVERS', result
    assert result.extras['fallback_skill'] == 'spec-to-rtl'
    assert 'SPEC_SENTENCES_UNACCOUNTED' in result.extras['rejected_emitters']
    assert 'SPEC_SENTENCES_UNACCOUNTED' in result.detail
    spans = result.extras['unaccounted_source_spans']
    assert spans
    for span in spans:
        assert span['kind'] == 'unaccounted'
        lo, hi = span['source_span']
        sentence = span['source_sentence']
        _assert_span(lo, hi, sentence, source_text)
        assert f'[{lo}:{hi}] {sentence}' in result.detail


def assert_prose_chain_handoff(result, source_text):
    kind, rtl, rejected = result
    assert kind is None
    assert rtl is None
    spans = [message for name, messages in rejected
             if name == 'SPEC_SENTENCES_UNACCOUNTED' for message in messages]
    assert spans
    for message in spans:
        parsed = re.fullmatch(r'\[(\d+):(\d+)\] ([\s\S]+)', message)
        assert parsed is not None, message
        lo, hi = int(parsed[1]), int(parsed[2])
        _assert_span(lo, hi, parsed[3], source_text)
