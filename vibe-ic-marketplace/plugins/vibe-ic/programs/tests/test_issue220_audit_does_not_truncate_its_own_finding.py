"""A D2 finding clipped at 300 characters is a report that went quiet.

THE DEFECT, measured on origin/main c9dacb8275 (v1.14.71)
---------------------------------------------------------
`plugin_full_audit.audit_d2` stored each guard's stdout as
`r.stdout.strip()[:300]`. `flow_condition_reachability_check` prints its
KNOWN-OPEN section — baselined holes, explicitly "reported, not blocking" —
FIRST, and its hard section — `FAIL: N NEW self-disabling condition(s)` — SECOND.

So on a main whose guard exited 1 because of a NEW hole at step 23, both the
console line and the `--json` report showed only the DT2 known-open, cut off
mid-sentence at "flow-YAML". An operator reading the audit saw a non-blocking
entry and no sign at all of the blocking one that was failing the build.

That is the D2 defect class one level up: the report that would have told you is
the thing that went silent. `audit_d2` already carries a comment saying a guard
that COULD NOT RUN is not a clean guard (#220); a guard whose finding cannot be
READ is the same fact.

chip-AGNOSTIC: a synthetic guard program and the shipped audit; no design, PDK,
foundry, vendor or process literal appears.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

PROGRAMS = Path(__file__).resolve().parents[1]
AUDIT = PROGRAMS / "plugin_full_audit.py"

#: Long enough that the interesting half sits past the old 300-char cap, and
#: shaped like the real guard: benign section first, blocking section second.
_HEAD = ("KNOWN-OPEN: 1 self-disabling condition(s) listed in the baseline "
         "(reported, not blocking):\n  - " + "x" * 320 + "\n")
_TAIL = "FAIL: 1 NEW self-disabling condition(s) — THE BLOCKING HALF\n"

_FAKE_GUARD = f'''#!/usr/bin/env python3
import sys
sys.stdout.write({_HEAD!r})
sys.stdout.write({_TAIL!r})
sys.exit(1)
'''


def _plugin_with_fake_guard(tmp_path: Path) -> Path:
    """A minimal plugin tree whose `flow_condition_reachability_check` is the
    two-section guard above. Only `programs/` has to exist for `main` to run;
    D1 and the flow scan degrade to their own no-input behaviour, which is not
    what is being measured here."""
    plugin = tmp_path / "plugin"
    progs = plugin / "programs"
    progs.mkdir(parents=True)
    (progs / "flow_condition_reachability_check.py").write_text(_FAKE_GUARD)
    return plugin


def _run(plugin: Path, tmp_path: Path):
    rep = tmp_path / "audit.json"
    r = subprocess.run([sys.executable, str(AUDIT), str(plugin),
                        "--json", str(rep)], capture_output=True, text=True)
    return r, json.loads(rep.read_text())


def test_the_blocking_half_survives_into_the_json_report(tmp_path):
    """RED WITHOUT THE FIX: `detail` is 300 characters of the KNOWN-OPEN
    section and the FAIL section is not in the report at all."""
    plugin = _plugin_with_fake_guard(tmp_path)
    _, doc = _run(plugin, tmp_path)
    finding = [f for f in doc["D2_step_compliance_checker"]["findings"]
               if f["check"] == "flow_condition_reachability_check"]
    assert len(finding) == 1, doc["D2_step_compliance_checker"]["findings"]
    detail = finding[0]["detail"]
    assert _TAIL.strip() in detail, (
        "the audit deleted the guard's blocking section from its own report; "
        f"it kept {len(detail)} char(s) ending {detail[-60:]!r}")


def test_the_blocking_half_survives_onto_stdout(tmp_path):
    """The JSON is not what an operator reads. The console rendering must carry
    it too, and must not fold a multi-line finding onto one line where the tail
    is the part that scrolls away."""
    plugin = _plugin_with_fake_guard(tmp_path)
    r, _ = _run(plugin, tmp_path)
    assert _TAIL.strip() in r.stdout, r.stdout[-600:]


def test_the_guards_exit_code_is_recorded(tmp_path):
    """`returncode == 1` (a verdict) and `returncode == 2` (could not run) are
    different repairs, and the finding should not make a reader guess which
    happened."""
    plugin = _plugin_with_fake_guard(tmp_path)
    _, doc = _run(plugin, tmp_path)
    finding = [f for f in doc["D2_step_compliance_checker"]["findings"]
               if f["check"] == "flow_condition_reachability_check"][0]
    assert finding.get("exit_code") == 1, finding


def test_a_guard_that_could_not_run_is_still_not_a_pass(tmp_path):
    """WHAT MUST NOT REGRESS — the #220 rule this loop already encoded. Exit 2
    is the operational tier and must still produce a finding, now with its whole
    message rather than 200 characters of it."""
    plugin = _plugin_with_fake_guard(tmp_path)
    (plugin / "programs" / "flow_condition_reachability_check.py").write_text(
        "#!/usr/bin/env python3\n"
        "import sys\n"
        f"sys.stderr.write({('operational: ' + 'y' * 400)!r})\n"
        "sys.exit(2)\n")
    r, doc = _run(plugin, tmp_path)
    assert r.returncode == 1, r.stdout
    finding = [f for f in doc["D2_step_compliance_checker"]["findings"]
               if f["check"] == "flow_condition_reachability_check"][0]
    assert finding.get("exit_code") == 2, finding
    assert "guard could not run" in finding["detail"], finding
    assert "y" * 400 in finding["detail"], (
        "the operational message was clipped: " + finding["detail"][-80:])


def test_a_clean_guard_still_produces_no_finding(tmp_path):
    """The control. Keeping more text must not turn silence into a finding."""
    plugin = _plugin_with_fake_guard(tmp_path)
    (plugin / "programs" / "flow_condition_reachability_check.py").write_text(
        "#!/usr/bin/env python3\nprint('PASS')\n")
    _, doc = _run(plugin, tmp_path)
    assert not [f for f in doc["D2_step_compliance_checker"]["findings"]
                if f["check"] == "flow_condition_reachability_check"], doc
