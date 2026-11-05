"""A moved project consumes native State without rewriting the tool output."""
import json

import librelane_postroute as postroute


def test_stapostpnr_reads_moved_views_without_a_receipt(tmp_path):
    project = tmp_path / 'copy'
    folder = project / 'phase3/librelane/sta'
    folder.mkdir(parents=True)
    files = {'nl': 'design.v', 'sdc': 'design.sdc', 'def': 'filled.def'}
    for name in [*files.values(), 'scene/design.sdf']:
        path = folder / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text('native output')
    old = '/old/run/phase3/librelane/sta/'
    state = {key: old + name for key, name in files.items()}
    state['sdf'] = {'scene': old + 'scene/design.sdf'}
    state['metrics'] = {'timing__setup_vio__count': 0}
    (folder / 'state_out.json').write_text(json.dumps(state))
    (folder / 'config.json').write_text(json.dumps({'meta': {'step': 'OpenROAD.STAPostPNR'}}))
    record = project / postroute.STEP23_RECORD
    record.parent.mkdir(parents=True)
    record.write_text(json.dumps({'sta_state': old + 'state_out.json'}))
    native_bytes = (folder / 'state_out.json').read_bytes()

    actual_folder, actual = postroute.stapostpnr_state(project)

    assert actual_folder == folder
    assert actual['def'] == str(folder / 'filled.def')
    assert postroute.corner_sdfs(actual) == {'scene': folder / 'scene/design.sdf'}
    assert actual['metrics'] == state['metrics']
    assert (folder / 'state_out.json').read_bytes() == native_bytes
