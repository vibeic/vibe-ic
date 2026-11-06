"""Source CLI controls: native backend entries remain bounded and mode-specific.

No phase/tool is dispatched: every positive entry deliberately omits its exit.
"""
from pathlib import Path
import subprocess
import sys

import pytest

from _route_fixture import stage_owner_route


RUNNER = Path(__file__).resolve().parents[1] / "vibe_ic_one_shot_runner.py"












































_D20_GOOD_SDC = (
    'create_clock -name clk -period 10 [get_ports clk]\n'
    'set_input_delay 1 -clock clk [get_ports a]\n'
    'set_output_delay 1 -clock clk [get_ports q]\n'
)


























def test_d20_explicit_consumers_refuse_external_and_symlink_sdc_authority(
        tmp_path):
    """Every actual consumer confines its explicit override before reading."""
    import hashlib
    import sdc_syntax_check as syntax

    project = tmp_path / 'project'
    constraints = project / 'input/constraints'
    constraints.mkdir(parents=True)
    external = tmp_path / 'external.sdc'
    external.write_text(_D20_GOOD_SDC)
    digest = hashlib.sha256(external.read_bytes()).hexdigest()
    linked = constraints / 'linked.sdc'
    linked.symlink_to(external)

    for candidate, detail in (
            (external,
             'explicit SDC parent is not literal input/constraints authority'),
            (linked, 'explicit SDC is a symlink')):
        syntax_result = syntax._regex_audit(
            str(project), sdc_path=candidate, sdc_sha256=digest)

        assert syntax_result.passed is False
        assert [(row.rule, row.message) for row in syntax_result.findings] == [
            ('SDC_AUTHORITY_REFUSED', detail)]
        assert syntax_result.summary['sdc_files_checked'] == []


def test_d20_explicit_consumers_refuse_parent_symlink_alias(tmp_path):
    """A regular leaf cannot enter through a foreign symlinked parent."""
    import hashlib
    import sdc_syntax_check as syntax

    project = tmp_path / 'project'
    source = project / 'input/constraints/clock.sdc'
    source.parent.mkdir(parents=True)
    source.write_text(_D20_GOOD_SDC)
    alias = tmp_path / 'foreign-alias'
    alias.symlink_to(source.parent, target_is_directory=True)
    candidate = alias / source.name
    assert candidate.is_symlink() is False
    digest = hashlib.sha256(source.read_bytes()).hexdigest()
    detail = 'explicit SDC parent is not literal input/constraints authority'

    syntax_result = syntax._regex_audit(
        str(project), sdc_path=candidate, sdc_sha256=digest)

    assert syntax_result.passed is False
    assert [(row.rule, row.message) for row in syntax_result.findings] == [
        ('SDC_AUTHORITY_REFUSED', detail)]
    assert syntax_result.summary['sdc_files_checked'] == []


def test_sdc_syntax_default_discovery_keeps_any_valid_deck_contract(tmp_path):
    """Return2's explicit one-deck strictness must not alter default discovery."""
    import sdc_syntax_check as syntax

    project = tmp_path / 'project'
    source = project / 'input/constraints/clock.sdc'
    source.parent.mkdir(parents=True)
    source.write_text(_D20_GOOD_SDC)
    invalid = project / 'phase2/stage2/constraints/invalid.sdc'
    invalid.parent.mkdir(parents=True)
    invalid.write_text(
        'create_clock -name bad -period 10 [get_ports bad]\n')

    result = syntax._regex_audit(str(project))
    assert result.passed is True
    assert result.summary['valid_files'] == 1
    assert result.summary['errors'] == 1
    assert {row.file for row in result.findings if row.severity == 'ERROR'} == {
        'phase2/stage2/constraints/invalid.sdc'}
