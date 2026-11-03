"""Step 90 ERC: recorded LEFs from another PDK root reach the tool under this run's root."""
import json
from types import SimpleNamespace

import phase3_one_shot_runner as runner

TECH, CELL = 'sc/techlef/sc__nom.tlef', 'sc/lef/sc.lef'
PADS = ['io/lef/io__in.lef', 'io/lef/io__bi.lef']
HISTORIC = '/foss/pdks/ciel/kit/versions/abc/kitD/libs.ref/'


def historic(*names):
    return [HISTORIC + name for name in names]


def restore(tmp_path, monkeypatch, recorded, *, present=(TECH, CELL, *PADS), macro_lefs=()):
    root = tmp_path / 'store/kitD/libs.ref'
    for name in present:
        (root / name).parent.mkdir(parents=True, exist_ok=True)
        (root / name).write_text('VERSION 5.8 ;\n')
    inventory = tmp_path / 'run' / runner.PHYSICAL_VIEW_INVENTORY_REL
    inventory.parent.mkdir(parents=True)
    inventory.write_text(json.dumps({'read_lef_paths': list(recorded)}))
    monkeypatch.setattr(runner, '_padring_chip_top_record', lambda project: None)
    pdk = SimpleNamespace(name='kitD', tech_lef=str(root / TECH), tech_lef_source=str(root / TECH),
                          cell_lef=str(root / CELL), macro_lefs=[str(root / m) for m in macro_lefs],
                          macro_gds=[])
    done = runner._restore_recorded_physical_views(tmp_path / 'run', pdk, 'eda')
    return pdk, done, root


def test_recorded_lefs_rebind_in_order_and_the_cell_lef_is_read_once(tmp_path, monkeypatch):
    pdk, done, root = restore(tmp_path, monkeypatch, historic(TECH, CELL, *PADS))
    assert pdk.macro_lefs == [str(root / name) for name in PADS]
    assert done['macro_lefs'] == pdk.macro_lefs


def test_a_view_already_loaded_is_not_read_twice(tmp_path, monkeypatch):
    pdk, _, root = restore(tmp_path, monkeypatch, historic(*PADS), macro_lefs=[PADS[0]])
    assert pdk.macro_lefs == [str(root / PADS[0]), str(root / PADS[1])]


def test_a_view_this_root_lacks_stays_as_recorded_for_the_tool_to_report(tmp_path, monkeypatch):
    pdk, done, root = restore(tmp_path, monkeypatch, historic(*PADS), present=(TECH, CELL, PADS[0]))
    assert pdk.macro_lefs == [str(root / PADS[0]), HISTORIC + PADS[1]]
    assert 'refused' not in done


def test_a_readable_project_macro_lef_is_kept_as_recorded(tmp_path, monkeypatch):
    macro = tmp_path / 'macro.lef'
    macro.write_text('VERSION 5.8 ;\n')
    pdk, _, _ = restore(tmp_path, monkeypatch, [str(macro), *historic(CELL)])
    assert pdk.macro_lefs == [str(macro)]
