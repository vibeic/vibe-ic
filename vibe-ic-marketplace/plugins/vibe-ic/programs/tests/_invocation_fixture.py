"""Native synthesis top input for output-retention tests."""
import json
from pathlib import Path


def bind_invocation_top(project, top):
    source = Path(project) / 'phase3/librelane/synthesis_resolved.json'
    source.parent.mkdir(parents=True, exist_ok=True)
    source.write_text(json.dumps({'DESIGN_NAME': top}))
