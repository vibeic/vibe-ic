"""Assertions for Program candidates emitted from ordinary prose."""
from pathlib import Path


def assert_program_candidate(result, source_text=None):
    assert result.status == 'PASS', result
    assert result.extras['deterministic_generator']
    assert result.output_files
    assert all(Path(path).is_file() for path in result.output_files)
    assert not result.extras.get('fallback_skill')


def assert_program_chain_candidate(result, source_text=None):
    kind, rtl, rejected = result
    assert kind and rtl, rejected
    assert 'module ' in rtl
    assert not any(name == 'SPEC_SENTENCES_UNACCOUNTED' for name, _ in rejected)
    return rtl


def assert_prose_handoff(result, source_text=None):
    assert result.status == 'PASS_WITH_WAIVERS', result
    assert result.extras['fallback_skill'] == 'spec-to-rtl'
    assert not result.output_files
