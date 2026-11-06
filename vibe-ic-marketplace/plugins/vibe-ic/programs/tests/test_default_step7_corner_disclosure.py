"""The native Step-7 routes record their current corner set without changing signoff."""


import _flow_yaml

REPORT = 'reports/phase3/single_corner_stance.json'


def test_step7_declares_its_corner_disclosure():
    row = next(row for row in _flow_yaml.load()['steps'] if row['id'] == 7)
    assert REPORT in row['required_outputs'], row
