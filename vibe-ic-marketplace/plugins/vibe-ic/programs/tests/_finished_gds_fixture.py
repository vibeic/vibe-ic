"""The finishing publisher's record for a fixture whose State GDS stands for the finished one."""
import hashlib
import json
from pathlib import Path


def publish_finished_gds(project, state_path=None):
    project = Path(project)
    state_path = Path(state_path or project / 'state_out.json')
    state = json.loads(state_path.read_text())
    gds = project / str(state.get('gds') or state.get('klayout_gds'))
    record = project / 'phase3/librelane/37-default-promotion.json'
    record.parent.mkdir(parents=True, exist_ok=True)
    record.write_text(json.dumps({
        'stream_state': str(state_path), 'canonical': str(gds),
        'stream_state_sha256': hashlib.sha256(state_path.read_bytes()).hexdigest(),
        'canonical_sha256': hashlib.sha256(gds.read_bytes()).hexdigest() if gds.is_file() else None}))
    return gds
