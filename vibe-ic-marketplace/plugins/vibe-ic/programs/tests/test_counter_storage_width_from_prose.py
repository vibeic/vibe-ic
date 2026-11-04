import json

import pytest

import phase1_doc_one_shot_runner as producer


@pytest.mark.parametrize('width, conflict', [(64, False), (128, False),
                                           (None, False), (64, True)])
def test_counter_storage_width_is_separate_from_csr_access_width(tmp_path, width, conflict):
    text = ('# Register map\n'
            '| Address | Name | R/W | Description | Width |\n'
            '| --- | --- | --- | --- | --- |\n'
            '| 0x40 | TICKS | RW | Free-running counter low half | 32 |\n'
            '| 0x44 | EVENTS | RW | Event counter low half | 32 |\n')
    if width is not None:
        text += f'\nThe counters ``TICKS`` and ``EVENTS`` are always available and {width} bit wide.\n'
    if conflict:
        text += '\nThe counters ``TICKS`` and ``EVENTS`` are 32 bit wide.\n'
    docs = tmp_path / 'input/docs'
    docs.mkdir(parents=True)
    (docs / 'registers.md').write_text(text)
    result = producer.gen_l4_regmap(tmp_path, {'registers.md': text})
    registers = json.loads(result.path.read_text())['registers']
    for name in ['TICKS', 'EVENTS']:
        register = next(r for r in registers if r['name'] == name)
        assert register.get('counter_width_bits') == (None if conflict else width)
        assert register['width_bits'] == 32
