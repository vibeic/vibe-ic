"""A gate this commit touches must still be unable to pass while broken.

The 63x8 matrix asks whether a STEP is wired, falsifiable, declares what it
produces.  It does not ask whether the PROGRAM behind that step can be weakened
without anything noticing — and those are different facts.  A survey found five
gates where the second was false while the first was true: 40 matrix cells read
ENFORCED over gates that could be neutered in silence.

Running the full survey costs about ten minutes, which is the wrong price for
every commit and the right price for none.  This guard pays it only where the
risk is: the gate programs THIS working tree changes.  A commit that touches no
gate program costs one canary probe; a commit that weakens one is refused at the
moment it would land.

The canary is not decoration.  Without it, a probe that had stopped working —
an entry shape it no longer recognises, a pytest invocation that no longer runs
anything — would report a clean survey by doing nothing, and this file would
become the thing it exists to prevent.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path


PROGRAMS_DIR = Path(__file__).resolve().parents[1]
#: Bound for a probe subprocess. MEASURED on this tree: the two probe-driving
#: tests take 1.71 s and 1.43 s. The 600 s I first wrote was decoration — it is
#: above the 60 s ceiling `ci_harness_timeout_ceiling_check` enforces, so it
#: could never fire: pytest kills the SESSION at 180 s first, taking every
#: other file in the subset with it. 45 s keeps ~26x headroom over the measured
#: time and stays under the ceiling.
_PROBE_TIMEOUT_S = 45
PLUGIN_ROOT = PROGRAMS_DIR.parent
FLOW_YAML = PLUGIN_ROOT / "flow" / "phase1_phase2_phase3.yaml"

sys.path.insert(0, str(PROGRAMS_DIR))

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

_GATE_CLAUSES = ("program_exit_zero", "advisory_program_exit_zero",
                 "optional_program_exit_zero")

#: Probed on every run regardless of what changed.  Chosen because its gate is
#: blocking and its tests drive the CLI, so a CAUGHT here means the machinery
#: works end to end.
_CANARY = "perc_signoff_check"


def _gate_programs() -> set:
    """Every program the flow names in a gate clause."""
    import yaml
    doc = yaml.safe_load(FLOW_YAML.read_text())
    found = set()

    def walk(node):
        if isinstance(node, dict):
            for key, value in node.items():
                if key in _GATE_CLAUSES:
                    cmd = value.get("command") if isinstance(value, dict) else value
                    if isinstance(cmd, str):
                        m = re.match(r"\s*([A-Za-z0-9_]+)", cmd)
                        if m:
                            found.add(m.group(1))
                else:
                    walk(value)
        elif isinstance(node, list):
            for value in node:
                walk(value)

    for step in doc["steps"]:
        walk(step.get("gate"))
    return found








def test_the_flow_names_gate_programs_this_guard_can_find():
    """If the clause vocabulary moves, this guard would silently watch nothing."""
    gates = _gate_programs()
    assert len(gates) > 100, (
        "only %d gate programs found in the flow — the clause names this guard "
        "walks (%s) no longer match the yaml, so it is watching almost nothing"
        % (len(gates), ", ".join(_GATE_CLAUSES)))
    assert _CANARY in gates, (
        "the canary %r is no longer a gate program; pick another blocking gate "
        "whose tests drive its CLI" % _CANARY)





# --- #547 review: the probe must not mutate the tree other sessions read -----



# --- 2026-08-04: the CLI was safe and the API was not ------------------------



    # NOTE ON WHY THE ASSERTION ABOVE IS SAFE UNDER CONCURRENCY, since it is
    # the one that used to flake: `reap` keeps any scratch whose `.owner.lock`
    # is still HELD, which is correct and is what protects a peer's live run.
    # It only ever failed here because `scratch` could be a peer's directory —
    # selected by "new to this test" rather than by ownership. With the pid
    # check above, `scratch` is this child's, its lock was released by the
    # kernel when the SIGKILL landed, and the reaper takes it.










# ══ THE PROBE'S VERDICT MUST NOT DEPEND ON THE MACHINE ════════════════════
#
# The probe used to run its WHOLE selection as one pytest under one wall-clock
# ceiling (240 s). MEASURED for `analog_adc_enob_corner_check` on an idle-ish
# host (load 5.3): 109.6 s, of which 109 were ONE file —
# `test_shipped_gate_is_wired_register_holds_no_pending_shrink`, which this
# module's own ranking calls rank 1, "merely names it in prose", and which it
# says "can neither catch nor clear it". On a loaded shard that selection
# exceeds the ceiling, the probe returns TIMEOUT, and the guard above reports
# "was NOT PROBED" — a FAILING test about the MEASUREMENT, on a gate the same
# probe calls CAUGHT when run alone.
#
# `probe` now runs the selection ONE FILE AT A TIME in rank order and stops at
# the first refusal. Nothing is removed from the selection, so a SILENT still
# means every file ran and none refused; only the TIMEOUTs move.
