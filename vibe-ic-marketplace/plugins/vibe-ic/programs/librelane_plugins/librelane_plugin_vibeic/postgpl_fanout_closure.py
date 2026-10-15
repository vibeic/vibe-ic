"""Second placement repair pass for buffers created by the first pass.

The installed RepairDesignPostGPL processes the original high fanout net and
may leave its newly inserted first level buffers over the declared limit.
This step runs before DetailedPlacement, which legalizes any new cells.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from librelane.common import get_script_dir
from librelane.steps.openroad import RepairDesignPostGPL
from librelane.steps.step import Step


@Step.factory.register()
class PostGPLFanoutClosure(RepairDesignPostGPL):
    """Repair residual placement fanout using the active SDC and Liberty."""

    id = "Vibeic.PostGPLFanoutClosure"
    name = "Post-Placement Fanout Closure"
    def get_script_path(self) -> str:
        template = Path(__file__).with_suffix(".tcl").read_bytes()
        rc = Path(get_script_dir()) / "openroad/common/set_rc.tcl"
        marker = b"source $::env(SCRIPTS_DIR)/openroad/common/set_rc.tcl"
        if template.count(marker) != 2:
            raise ValueError("post-GPL RC source sites changed")
        # This is the script passed to OpenROAD, not an audit-only expansion.
        # Keep the image's RC/corner logic, including its actual set_wire_rc
        # commands, in the same executed subject as the repair operations.
        subject = Path(self.step_dir) / "pnr_postgpl_timing.tcl"
        subject.write_bytes(template.replace(marker, rc.read_bytes()))
        return str(subject)

    def run(self, state_in, **kwargs):
        subject = Path(self.get_script_path())
        record = subject.with_suffix(".json")
        record.unlink(missing_ok=True)
        before = hashlib.sha256(subject.read_bytes()).hexdigest()
        result = super().run(state_in, **kwargs)
        if hashlib.sha256(subject.read_bytes()).hexdigest() != before:
            raise ValueError("post-GPL executed script changed during execution")
        # run_chain binds ordinary JSON outputs in its existing native receipt.
        # Bind the actual command journal and subject there, without changing
        # the static Tcl checker or authoring an alternative gate verdict.
        commands = Path(self.step_dir) / "COMMANDS"
        record.write_text(json.dumps({
            "script": subject.name, "sha256": before,
            "commands_sha256": hashlib.sha256(commands.read_bytes()).hexdigest(),
            "template_sha256": hashlib.sha256(Path(__file__).with_suffix(".tcl").read_bytes()).hexdigest(),
            "set_rc_sha256": hashlib.sha256((Path(get_script_dir()) / "openroad/common/set_rc.tcl").read_bytes()).hexdigest(),
        }, indent=2) + "\n")
        return result
