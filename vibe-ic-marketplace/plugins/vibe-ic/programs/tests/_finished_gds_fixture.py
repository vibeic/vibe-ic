"""Set the fixture's finished GDS in the actual selected native State."""
import json
from pathlib import Path


def publish_finished_gds(project, state_path=None):
    project = Path(project)
    state_path = Path(state_path or project / 'state_out.json')
    state = json.loads(state_path.read_text())
    gds = project / str(state.get('gds') or state.get('klayout_gds'))
    state['gds'] = str(gds)
    state_path.write_text(json.dumps(state))
    return gds
