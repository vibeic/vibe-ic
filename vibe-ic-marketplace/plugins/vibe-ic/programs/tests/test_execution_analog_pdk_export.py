"""Focused controls for the bounded analog PDK export helper."""
import hashlib
import json
import shutil
from pathlib import Path
import subprocess
import sys

import pytest

import execution_analog_installation as installation
import execution_analog_pdk_export as export


IMAGE_REF = 'ghcr.io/vibeic/vibeic-eda@sha256:' + 'a' * 64
IMAGE_ID = 'sha256:' + 'b' * 64
MANIFEST = 'sha256:' + 'a' * 64


@pytest.fixture
def setup_export(tmp_path, monkeypatch):
    project = tmp_path / 'project'
    project.mkdir()
    (project / 'input').mkdir()
    (project / 'input/immutable.txt').write_text('caller-owned input\n')
    pdk = tmp_path / 'container' / 'foss' / 'pdks' / 'sky130A'
    (pdk / 'libs.tech/ngspice/models').mkdir(parents=True)
    (pdk / 'libs.tech/ngspice/shared').mkdir(parents=True)
    seed = pdk / 'libs.tech/ngspice/models/top.spice'
    child = pdk / 'libs.tech/ngspice/shared/child.lib'
    leaf = pdk / 'libs.tech/ngspice/shared/leaf.inc'
    seed.write_text('.include "../shared/child.lib"\n')
    child.write_text('.inc leaf.inc\n')
    leaf.write_text('model leaf\n')
    facts = {
        'available': True, 'probe_ok': True, 'source': 'container_installed', 'rung': 2,
        'target': 'sky130A', 'family': 'sky130A', 'matched_dir': 'sky130A',
        'pdk_root': '/foss/pdks/sky130A',
        'spice_libs': ['/foss/pdks/sky130A/libs.tech/ngspice/models/top.spice'],
        'drc_deck': None, 'lvs_deck': None,
    }
    calls = []

    def inspect(ref, *, docker):
        return {'image_ref': IMAGE_REF, 'image_id': IMAGE_ID,
                'image_manifest_digest': MANIFEST, 'image_repo_digests': [IMAGE_REF]}

    def run(argv, *, probe_deadline_s, env):
        assert probe_deadline_s == 120
        assert '--network' in argv and 'none' in argv
        assert IMAGE_REF in argv
        calls.append(list(argv))
        scratch = Path(argv[argv.index('-v') + 1].split(':', 1)[0])
        script = argv[argv.index('--skip') + 3]
        pdk_arg = argv[argv.index('--skip') + 4]
        request_arg = argv[argv.index('--skip') + 6]
        done = subprocess.run([sys.executable, '-c', script, str(pdk), str(scratch), request_arg],
                              capture_output=True, text=True)
        return subprocess.CompletedProcess(argv, done.returncode, done.stdout, done.stderr)

    monkeypatch.setattr(installation, 'inspect_image', inspect)
    monkeypatch.setattr(export.lc, 'run_container', run)
    return project, pdk, facts, calls


def call(project, facts, **kwargs):
    return export.export_bounded_pdk(project, target='sky130A', image_ref=IMAGE_REF,
                                     image_id=IMAGE_ID, resolver_facts=facts, **kwargs)


def tree_digest(root):
    return {p.relative_to(root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(root.rglob('*')) if p.is_file()}


def test_exports_seed_and_literal_closure_deterministically(setup_export):
    project, _, facts, _ = setup_export
    before = tree_digest(project / 'input')
    first = call(project, facts)
    second = call(project, facts)
    assert first['status'] == 'MEASURED'
    assert first['receipt_digest'] == second['receipt_digest']
    assert first['files'] == second['files']
    assert first['reused'] is False and second['reused'] is True
    assert len(first['files']) == 3
    assert first['resolver_fields']['spice_libs'] == [
        f"{first['output_root']}/libs.tech/ngspice/models/top.spice"]
    assert before == tree_digest(project / 'input')


def test_safe_parent_relative_include_stays_inside_root(setup_export):
    project, pdk, facts, _ = setup_export
    result = call(project, facts)
    assert result['status'] == 'MEASURED'
    child = next(row for row in result['files'] if row['guest_path'].endswith('/shared/child.lib'))
    assert child['guest_path'] == '/foss/pdks/sky130A/libs.tech/ngspice/shared/child.lib'
    copied = project / result['output_root'] / child['relative_path']
    assert copied.read_bytes() == b'.inc leaf.inc\n'

    (pdk / 'libs.tech/ngspice/models/top.spice').write_text(
        '.include "missing/../shared/child.lib"\n')
    erased_prefix_child = pdk / 'libs.tech/ngspice/models/shared/child.lib'
    erased_prefix_child.parent.mkdir(parents=True)
    erased_prefix_child.write_bytes(b'lexically normalized bytes\n')
    normalized = call(project, facts)
    assert normalized['status'] == 'MEASURED', normalized.get('not_measured')
    normalized_child = next(
        row for row in normalized['files']
        if row['guest_path'] == '/foss/pdks/sky130A/libs.tech/ngspice/models/shared/child.lib')
    normalized_copy = project / normalized['output_root'] / normalized_child['relative_path']
    assert normalized_copy.read_bytes() == b'lexically normalized bytes\n'
    assert not any('consumer-outside' in row['guest_path'] or '/sub/' in row['guest_path']
                   for row in normalized['files'])
    normalized_again = call(project, facts)
    assert normalized_again['status'] == 'MEASURED'
    assert normalized['receipt_digest'] == normalized_again['receipt_digest']
    assert normalized['files'] == normalized_again['files']
    assert normalized_again['reused'] is True


def test_symlink_parent_before_dotdot_is_not_measured(setup_export):
    """A real resolver follows each component before interpreting '..'."""
    project, pdk, facts, _ = setup_export
    models = pdk / 'libs.tech/ngspice/models'
    top = models / 'top.spice'
    internal = models / 'shared/child.lib'
    outside = pdk.parent.parent / 'consumer-outside'
    link_target = outside / 'branch'
    external = outside / 'shared/child.lib'
    internal.parent.mkdir(parents=True)
    link_target.mkdir(parents=True)
    external.parent.mkdir(parents=True)
    internal.write_bytes(b'in-root bytes\n')
    external.write_bytes(b'outside bytes\n')
    (models / 'sub').symlink_to(link_target, target_is_directory=True)
    top.write_text('.include "sub/../shared/child.lib"\n')

    consumer_path = (models / 'sub/../shared/child.lib').resolve(strict=True)
    lexical_target = internal.resolve(strict=True)
    assert consumer_path == external.resolve(strict=True)
    assert consumer_path.read_bytes() != lexical_target.read_bytes()

    result = call(project, facts)
    assert result['status'] == 'NOT_MEASURED'
    assert result['not_measured'] == ['PDK_SYMLINK_REFUSED']


def test_measured_root_alias_reads_canonical_target_and_seals_binding(setup_export):
    project, pdk, facts, _ = setup_export
    canonical = pdk.parent / 'ciel/sky130/versions/test-version/sky130A'
    canonical.parent.mkdir(parents=True)
    pdk.rename(canonical)
    pdk.symlink_to('ciel/sky130/versions/test-version/sky130A', target_is_directory=True)

    result = call(project, facts)

    assert result['status'] == 'MEASURED'
    assert result['pdk_root'] == '/foss/pdks/sky130A'
    assert result['pdk_root_binding'] == {
        'logical_root': '/foss/pdks/sky130A',
        'link_text': 'ciel/sky130/versions/test-version/sky130A',
        'canonical_root': '/foss/pdks/ciel/sky130/versions/test-version/sky130A',
    }
    seed = next(row for row in result['files'] if row['guest_path'].endswith('/models/top.spice'))
    assert seed['guest_path'].startswith('/foss/pdks/sky130A/')
    copied = project / result['output_root'] / seed['relative_path']
    assert copied.read_bytes() == b'.include "../shared/child.lib"\n'
    receipt = json.loads((project / result['output_root'] / '_receipt.json').read_text())
    assert receipt['pdk_root_binding'] == result['pdk_root_binding']
    assert hashlib.sha256(export._canonical({k: v for k, v in receipt.items()
        if k not in ('receipt_digest', 'output_root')})).hexdigest() == result['receipt_digest']


def test_root_alias_outside_authority_is_not_measured(setup_export):
    project, pdk, facts, _ = setup_export
    outside = pdk.parent.parent / 'outside' / 'sky130A'
    outside.mkdir(parents=True)
    shutil.rmtree(pdk)
    pdk.symlink_to(outside, target_is_directory=True)
    result = call(project, facts)
    assert result['status'] == 'NOT_MEASURED'
    assert result['not_measured'] == ['PDK_ROOT_ALIAS_ESCAPE']
    assert not list((project / export.OUTPUT_BASE).glob('*/_receipt.json'))







def test_same_root_absolute_include_is_accepted_foreign_root_is_not(setup_export):
    project, pdk, facts, _ = setup_export
    top = pdk / 'libs.tech/ngspice/models/top.spice'
    top.write_text('.include "/foss/pdks/sky130A/libs.tech/ngspice/shared/child.lib"\n')
    result = call(project, facts)
    assert result['status'] == 'MEASURED'
    assert any(row['guest_path'] == '/foss/pdks/sky130A/libs.tech/ngspice/shared/child.lib'
               for row in result['files'])
    top.write_text('.include "/foss/pdks/gf180mcuD/libs.tech/ngspice/shared/child.lib"\n')
    result = call(project, facts)
    assert result['status'] == 'NOT_MEASURED'
    assert result['not_measured'] == ['PDK_PATH_ESCAPE']


def test_resolver_config_seed_follows_literal_include(setup_export):
    project, pdk, facts, _ = setup_export
    deck = pdk / 'libs.tech/klayout/drc/main.svrf'
    child = pdk / 'libs.tech/klayout/drc/rules/core.svrf'
    child.parent.mkdir(parents=True)
    deck.write_text('INCLUDE "rules/core.svrf"\n')
    child.write_text('DRC CHECK\n')
    facts['drc_deck'] = '/foss/pdks/sky130A/libs.tech/klayout/drc/main.svrf'
    result = call(project, facts)
    assert result['status'] == 'MEASURED'
    assert any(row['guest_path'].endswith('/drc/rules/core.svrf') for row in result['files'])


def test_config_import_after_tcl_semicolon_is_closed(setup_export):
    project, pdk, facts, _ = setup_export
    deck = pdk / 'libs.tech/klayout/drc/main.tcl'
    child = pdk / 'libs.tech/klayout/drc/shared/rules.tcl'
    child.parent.mkdir(parents=True)
    deck.write_text('set base .; source "shared/rules.tcl"\n')
    child.write_text('set rule 1\n')
    facts['drc_deck'] = '/foss/pdks/sky130A/libs.tech/klayout/drc/main.tcl'
    result = call(project, facts)
    assert result['status'] == 'MEASURED'
    assert any(row['guest_path'].endswith('/drc/shared/rules.tcl') for row in result['files'])


def test_tcl_url_does_not_hide_later_dynamic_source(setup_export):
    project, pdk, facts, _ = setup_export
    deck = pdk / 'libs.tech/klayout/drc/main.tcl'
    deck.parent.mkdir(parents=True)
    deck.write_text('set root http://example.invalid; source $root/rules.tcl\n')
    facts['drc_deck'] = '/foss/pdks/sky130A/libs.tech/klayout/drc/main.tcl'
    result = call(project, facts)
    assert result['status'] == 'NOT_MEASURED'
    assert result['not_measured'] == ['PDK_DYNAMIC_INCLUDE_REFUSED']


def test_dynamic_config_import_is_not_measured(setup_export):
    project, pdk, facts, _ = setup_export
    deck = pdk / 'libs.tech/klayout/drc/main.svrf'
    deck.parent.mkdir(parents=True)
    deck.write_text('source $RULE_ROOT/rules.svrf\n')
    facts['drc_deck'] = '/foss/pdks/sky130A/libs.tech/klayout/drc/main.svrf'
    result = call(project, facts)
    assert result['status'] == 'NOT_MEASURED'
    assert result['not_measured'] == ['PDK_DYNAMIC_INCLUDE_REFUSED']


def test_klayout_layout_source_calls_are_not_pdk_imports(setup_export):
    project, pdk, facts, _ = setup_export
    drc = pdk / 'libs.tech/klayout/drc/sky130A.lydrc'
    lvs = pdk / 'libs.tech/klayout/lvs/sky130.lvs'
    drc.parent.mkdir(parents=True)
    lvs.parent.mkdir(parents=True)
    drc.write_text('# input guard\nif $input\nsource($input)\nend\n\n')
    lvs.write_text('\n#=== GET LAYOUT ===\nsource($input, $top_cell)\n\n# input consumed\n')
    facts['spice_libs'] = []
    facts['spice_lib'] = None
    facts['drc_deck'] = '/foss/pdks/sky130A/libs.tech/klayout/drc/sky130A.lydrc'
    facts['lvs_deck'] = '/foss/pdks/sky130A/libs.tech/klayout/lvs/sky130.lvs'

    result = call(project, facts)

    assert result['status'] == 'MEASURED', result.get('not_measured')
    assert {row['guest_path'] for row in result['files']} == {
        facts['drc_deck'], facts['lvs_deck']}


@pytest.mark.parametrize('module_name', ['etc', 'time', 'logger'])
def test_klayout_bare_runtime_require_is_not_pdk_closure(setup_export, module_name):
    project, pdk, facts, _ = setup_export
    deck = pdk / 'libs.tech/klayout/lvs/runtime-requires.lvs'
    deck.parent.mkdir(parents=True)
    deck.write_text(f'require "{module_name}"\n')
    facts['spice_libs'] = []
    facts['spice_lib'] = None
    facts['lvs_deck'] = '/foss/pdks/sky130A/libs.tech/klayout/lvs/runtime-requires.lvs'

    result = call(project, facts)

    assert result['status'] == 'MEASURED', result.get('not_measured')
    assert {row['guest_path'] for row in result['files']} == {facts['lvs_deck']}


@pytest.mark.parametrize(('directive', 'child_name'), [
    ("require 'shared/required.rb'", 'required.rb'),
    ("require_relative('shared/relative.rb')", 'relative.rb'),
    ("load 'shared/loaded.rb'", 'loaded.rb'),
])
def test_klayout_ruby_literal_imports_remain_in_closure(setup_export, directive, child_name):
    project, pdk, facts, _ = setup_export
    deck = pdk / 'libs.tech/klayout/drc/main.lydrc'
    child = deck.parent / 'shared' / child_name
    child.parent.mkdir(parents=True)
    deck.write_text(directive + '\n')
    child.write_text('# bounded ruby helper\n')
    facts['spice_libs'] = []
    facts['spice_lib'] = None
    facts['drc_deck'] = '/foss/pdks/sky130A/libs.tech/klayout/drc/main.lydrc'
    result = call(project, facts)
    assert result['status'] == 'MEASURED', result.get('not_measured')
    assert any(row['guest_path'].endswith('/shared/' + child_name) for row in result['files'])


@pytest.mark.parametrize('directive', [
    'require($rule_path)', 'require_relative ENV["RULE"]', 'load($rule_path)',
])
def test_klayout_ruby_dynamic_imports_remain_refused(setup_export, directive):
    project, pdk, facts, _ = setup_export
    deck = pdk / 'libs.tech/klayout/drc/main.lydrc'
    deck.parent.mkdir(parents=True)
    deck.write_text(directive + '\n')
    facts['spice_libs'] = []
    facts['spice_lib'] = None
    facts['drc_deck'] = '/foss/pdks/sky130A/libs.tech/klayout/drc/main.lydrc'
    result = call(project, facts)
    assert result['status'] == 'NOT_MEASURED'
    assert result['not_measured'] == ['PDK_DYNAMIC_INCLUDE_REFUSED']


@pytest.mark.parametrize(('contents', 'child', 'reason'), [
    ('.include "../../../../outside.lib"\n', None, 'PDK_PATH_ESCAPE'),
    ('.include "$MODEL_ROOT/x.lib"\n', None, 'PDK_DYNAMIC_INCLUDE_REFUSED'),
    ('.include "missing.lib"\n', None, 'PDK_FILE_MISSING'),
])
def test_unsafe_or_unavailable_closure_is_not_measured(setup_export, contents, child, reason):
    project, pdk, facts, _ = setup_export
    (pdk / 'libs.tech/ngspice/models/top.spice').write_text(contents)
    result = call(project, facts)
    assert result['status'] == 'NOT_MEASURED'
    assert result['not_measured'] == [reason]
    assert not list((project / export.OUTPUT_BASE).glob('*/_receipt.json'))


def test_symlink_in_closure_is_refused(setup_export):
    project, pdk, facts, _ = setup_export
    alias = pdk / 'libs.tech/ngspice/shared/child.lib'
    alias.unlink()
    alias.symlink_to(pdk / 'libs.tech/ngspice/shared/leaf.inc')
    result = call(project, facts)
    assert result['status'] == 'NOT_MEASURED'
    assert result['not_measured'] == ['PDK_SYMLINK_REFUSED']


@pytest.mark.parametrize(('limit', 'value', 'reason'), [
    ('max_files', 2, 'PDK_EXPORT_MAX_FILES'),
    ('max_bytes', 5, 'PDK_EXPORT_MAX_BYTES'),
])
def test_export_limits_are_enforced(setup_export, limit, value, reason):
    project, _, facts, _ = setup_export
    result = call(project, facts, **{limit: value})
    assert result['status'] == 'NOT_MEASURED'
    assert result['not_measured'] == [reason]
