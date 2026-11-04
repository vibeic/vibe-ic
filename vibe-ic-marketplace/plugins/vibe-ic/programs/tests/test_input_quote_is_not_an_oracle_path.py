import pytest

import phase1_doc_one_shot_runner as producer


def test_located_input_quote_is_not_an_additional_source_path():
    doc = {'fields': {'implementation_route': [{
        'source': 'input/docs/spec.md', 'line': 1,
        'evidence': 'Use the include directory input/vendor_rtl/vendor/prim/rtl/.',
    }]}}
    assert producer._assert_no_rtl_oracle_leak_in_l_doc(doc, 'L19.json') == []


@pytest.mark.parametrize('record', [
    {'source': 'phase2/stage1/rtl/widget.sv', 'line': 1,
     'evidence': 'Selected implementation.'},
    {'evidence': 'phase2/stage1/rtl/widget.sv'},
])
def test_actual_build_sources_still_refuse(record):
    assert producer._assert_no_rtl_oracle_leak_in_l_doc(record, 'L19.json')
