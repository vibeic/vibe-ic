#!/usr/bin/env python3
"""test_issue2204_expert_second_pass_is_reachable.py

`phase1_expert_parse_track` ends its first pass by telling the operator to
invoke the `vibe-ic:ic-expert-agent` subagent and "re-run to consume its
answer". THE ONE CANONICAL FRONT DOOR COULD NOT PERFORM THAT RE-RUN.
`vibe_ic_one_shot_runner._phase1_decision` returned `(False, "")` as soon as
`L_count >= 13`, and Phase 1 emits 28 L documents — so from the first
successful run onward every orchestrator invocation SKIPPED Phase 1 and a
delivered expert answer sat unread on disk forever.

MEASURED before the fix, on a synthesised project carrying 28 L documents, the
subagent's `l_doc_expectations.json` on disk and an `expert_parse_track.json`
whose `ai_subtrack.status` is still `HANDOFF_EMITTED`:

    _phase1_decision(project, force_skip=False) -> (False, '')

— identical to the answer it gives for the same project with no answer file at
all. The decision could not see the difference between "phase 1 has run" and
"phase 1 has run AND its expert answer has been read".

WHAT IS PINNED HERE, AND WHY BOTH DIRECTIONS ARE PINNED
------------------------------------------------------
A change that always re-runs Phase 1 would make the first half of this file
green and would be a wall-clock tax on every run, not a fix. So the SKIP
direction is pinned as hard as the RE-ENTER direction:

  * an UNREAD delivered answer re-enters Phase 1, in a mode that runs the
    second track ALONE and re-extracts nothing;
  * a root whose answer was read — under EVERY status the track can record
    once it has opened an answer — is still SKIPPED;
  * a root with no answer at all is still SKIPPED;
  * an operator's `--skip-phase1` is still a skip.

The last three are CONTROLS: they are green before this fix and must stay
green after it. A fix that reddens them has replaced one defect with a worse
one.

TERMINATION is keyed to the bytes the producer actually read. An unchanged
refused answer is skipped; a corrected answer or an answer without a read
receipt is retried. The subprocess lifecycle fixtures below reproduce both
independent review variants. Their L-docs and initial PASS summary are synthetic
seam scaffolding, not certified extraction or golden benchmark evidence.

Every fixture is synthesised here from neutral parts. No design, PDK, vendor
or IP-model identifier appears anywhere in this file.

Run: python3 -m pytest programs/tests/test_issue2204_expert_second_pass_is_reachable.py -q
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


_PROGRAMS = Path(__file__).resolve().parents[1]
if str(_PROGRAMS) not in sys.path:
    sys.path.insert(0, str(_PROGRAMS))

import _path_layout as _pl                    # noqa: E402
from _route_fixture import stage_owner_route  # noqa: E402

#: WHERE PASS 1's RECORD LIVES, asked of the router. R-0915-151 moved
#: `phase1_one_shot.json` onto `_path_layout`'s router, because the flat
#: `reports/phase1_one_shot.json` is a location this repo's own
#: `reports_subfolder_taxonomy_check` calls a stray file. These arms are about the SECOND PASS
#: being reachable and consuming the delivered answer, not about layout: they staged pass 1 flat
#: and then read the flat path back, so once the second pass began publishing at the routed path
#: they were reading a file nobody had updated. The legacy-location behaviour has its own home,
#: `test_a_pass_one_written_before_the_move_is_still_carried.py`; these ask the router so they
#: are not accidentally testing two things.
def _pass1_record(project: Path) -> Path:
    # The parent is created because several of these call sites WRITE pass 1's record to stage a
    # project. The flat location they used to write needed no mkdir -- `reports/` already existed
    # -- and the routed one does; my first rewrite of these arms missed that and turned them into
    # FileNotFoundError at `reports/orchestrator/`. Harmless on a read.
    path = _pl.report_path(project, "phase1_one_shot.json")
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def _report(project: Path) -> Path:
    return _pl.report_path(project, "phase1/expert_parse_track.json")


def _invoke_lifecycle(project, label, *, first_pass=False):
    """Retain the real producer's argv, rc, output and report snapshots."""
    argv = [sys.executable, "-B", str(_PROGRAMS / "phase1_one_shot_runner.py"),
            str(project), "--ic-name", "review_counter"]
    cp = subprocess.run(argv, capture_output=True, text=True)
    (project / f"{label}.stdout").write_text(cp.stdout)
    (project / f"{label}.stderr").write_text(cp.stderr)
    row = {"argv": argv, "rc": cp.returncode}
    for key, path in (("track", _report(project)),
                      ("summary", _pass1_record(project))):
        if path.is_file():
            row[key] = json.loads(path.read_text())
    (project / f"{label}.json").write_text(json.dumps(row, indent=2))
    return row


def test_actual_first_pass_failure_survives_consumption(tmp_path):
    p = tmp_path / "no_input"
    p.mkdir()
    # owner route rule 2026-09-28 (ICROUTE)
    stage_owner_route(p, "ic")
    first = _invoke_lifecycle(p, "01_no_input", first_pass=True)
    # R-0915-85 — rc 1 is unchanged and is what this case is about: a first
    # pass over a project with NO INPUT is not green. The WORD is NOT_MEASURED,
    # because nothing failed -- D1 was refused for want of anything to read --
    # and publishing FAIL would claim a finding about a design nobody examined.
    assert first["rc"] == 1, first
    assert first["summary"]["verdict"] == "NOT_MEASURED", first["summary"]
