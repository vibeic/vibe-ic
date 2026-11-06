"""Flow declaration and hardmacro route cases after pad-drive removal."""

from __future__ import annotations
import json
import sys
from pathlib import Path

PROGRAMS = Path(__file__).resolve().parents[1]

if str(PROGRAMS) not in sys.path:
    sys.path.insert(0, str(PROGRAMS))

from _hostpaths import require_repo  # noqa: E402
import _tapeout_declaration as TD  # noqa: E402

FLOW = require_repo("vibe-ic-marketplace", "plugins", "vibe-ic", "flow",
                    "phase1_phase2_phase3.yaml")

CLAUSE = "pad_input_drive_check . --json reports/phase3/sta/pad_input_drive_check.json"


def test_step23_declares_the_clause():
    text = FLOW.read_text()
    step23 = text[text.index("\n  - id: 23\n"):text.index("\n  - id: 24")]
    assert f'- program_exit_zero: "{CLAUSE}"' in step23


def _step23_only():
    import yaml
    step = next(s for s in yaml.safe_load(FLOW.read_text())["steps"]
                if str(s.get("id")) == "23")
    clause = [c for c in step["gate"]["all_of"]
              if isinstance(c, dict) and c.get("program_exit_zero") == CLAUSE]
    assert len(clause) == 1
    return dict(step, required_outputs=[], gate={"all_of": clause})


def test_control_an_attested_hardmacro_is_decided_not_applicable(tmp_path):
    """The IP route: a slot catalogue is staged, but the owner-attested
    declaration says HARDMACRO, so no pad ring exists."""
    import _owner_declared as OD
    project = tmp_path / "ip"
    slots = project / TD.SLOTS_REL
    slots.mkdir(parents=True)
    (slots / "s.yaml").write_text("slot: catalogue entry\n")
    (project / TD.DECLARATION_REL).write_text(json.dumps(OD.attest(
        {"schema": "vibe-ic/tapeout_declaration/1",
         "answers": {"deliverable": "HARDMACRO", "top_cell": "t",
                     "pad_order_by_side": "NOT_DETERMINED"}})) + "\n")
    assert TD.requests_pad_ring(project) is False
