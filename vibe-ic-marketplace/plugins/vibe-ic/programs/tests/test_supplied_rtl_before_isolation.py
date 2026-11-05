"""A complete supplied top needs a handoff, not a whole-project author copy."""
import json
from pathlib import Path
import pytest
import design_one_shot_runner as runner


def project(root, source):
    docs = root / 'phase1/generated_docs'
    docs.mkdir(parents=True)
    (docs / 'L9_INTEGRATION_SPEC.json').write_text(json.dumps({'top_module': 'neutral_top'}))
    rtl = root / 'input/vendor_rtl'
    rtl.mkdir(parents=True)
    (rtl / 'supplied.v').write_text(source)
    return root


def test_complete_supplied_top_hands_off_without_snapshot(tmp_path, monkeypatch):
    root = project(tmp_path, 'module neutral_top(input clk, output q);assign q=clk;endmodule\n')
    monkeypatch.setattr(runner, '_phase1_snapshot_to_stage', lambda *args:
        pytest.fail('handoff has no author writes that need a project snapshot'))
    result = runner.step_rtl_gen(root, 'processor_cpu', force_regen=True)
    assert result.status == 'PASS_WITH_WAIVERS', result.detail
    assert result.extras['fallback_skill'] == 'catalog-glue-author'
    assert result.extras['supplied_build_rtl'] == ['input/vendor_rtl/supplied.v']
    assert any(x.get('force_rtl_regen_overridden') for x in result.extras['deferred_generators'])
    assert not (root / 'phase2/stage1/rtl/supplied.v').exists()


@pytest.mark.parametrize('source', ['module child(input clk);endmodule\n', '`define WIDTH 8\n'])
def test_partial_or_header_only_source_keeps_the_normal_author_path(tmp_path, monkeypatch, source):
    root = project(tmp_path, source)
    seen = []
    def snapshot(*args):
        seen.append(True)
        raise runner._Phase1RtlOutputRefused('TEST_AUTHOR_PATH', root, 'ordinary dispatch reached')
    monkeypatch.setattr(runner, '_phase1_snapshot_to_stage', snapshot)
    result = runner.step_rtl_gen(root, 'processor_cpu')
    assert seen == [True]
    assert result.status != 'PASS_WITH_WAIVERS'
