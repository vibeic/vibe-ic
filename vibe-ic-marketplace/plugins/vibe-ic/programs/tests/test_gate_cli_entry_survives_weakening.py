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

import json
import re
import subprocess
import sys
from pathlib import Path

import pytest

PROGRAMS_DIR = Path(__file__).resolve().parents[1]
PLUGIN_ROOT = PROGRAMS_DIR.parent
FLOW_YAML = PLUGIN_ROOT / "flow" / "phase1_phase2_phase3.yaml"

sys.path.insert(0, str(PROGRAMS_DIR))
import gate_cli_mutation_probe as PROBE  # noqa: E402

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


def _changed_gate_programs() -> list:
    """Gate programs this working tree changes, against the upstream baseline.

    Returns [] when the baseline cannot be resolved — a shallow CI checkout, a
    detached build.  That is a real limit and it is why the canary exists: this
    guard degrades to "the probe still works", never to "nothing was checked".
    """
    gates = _gate_programs()
    for base in ("origin/main", "main"):
        try:
            r = subprocess.run(
                ["git", "diff", "--name-only", f"{base}...HEAD"],
                cwd=PLUGIN_ROOT, capture_output=True, text=True, timeout=60)
        except (OSError, subprocess.SubprocessError):
            return []
        if r.returncode != 0:
            continue
        break
    else:
        return []
    changed = set()
    for line in list(r.stdout.split("\n")) + _dirty():
        p = Path(line.strip())
        if p.suffix == ".py" and p.parent.name == "programs" and p.stem in gates:
            changed.add(p.stem)
    return sorted(changed)


def _dirty() -> list:
    """Uncommitted changes count too — the guard should fire before the commit."""
    try:
        r = subprocess.run(["git", "status", "--porcelain"], cwd=PLUGIN_ROOT,
                           capture_output=True, text=True, timeout=60)
    except (OSError, subprocess.SubprocessError):
        return []
    return [line[3:].strip() for line in r.stdout.split("\n") if line.strip()]


_TARGETS = sorted({_CANARY, *_changed_gate_programs()})


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


@pytest.mark.parametrize("program", _TARGETS)
def test_neutering_the_gate_reddens_something(program):
    """Make it unable to fail, and require a test to notice.

    SILENT is the finding.  NO_TEST / NO_ENTRY are failures of the MEASUREMENT
    and are reported as such — a probe that could not run has not cleared the
    gate, and saying so is the difference between this guard and the static
    proxy that was rejected for producing two false comforts.
    """
    result = PROBE.probe(program)
    state = result["state"]
    if state == "CAUGHT":
        return
    if state == "SILENT":
        pytest.fail(
            "%s can be made unable to fail and nothing reddens.\n"
            "  entry neutered: %s\n"
            "  test files run: %s\n"
            "The flow reads this program's EXIT CODE. A test that calls audit() "
            "measures the finding and leaves the verdict-to-exit-code mapping "
            "unmeasured. Add a test that runs it as a subprocess on an input it "
            "should refuse, and assert the exit code the flow would act on."
            % (program, result.get("entry"), ", ".join(result.get("tests", []))))
    pytest.fail(
        "%s was NOT PROBED (%s) — the measurement failed, which is not the same "
        "as the gate being protected. Fix the probe rather than reading this as "
        "a pass." % (program, state))


def test_no_gate_is_left_neutered_in_the_tree():
    """A killed probe cannot reach its `finally`.

    Measured: one did, and the next run then read the NEUTERED file as its
    original and restored to it — the weakening compounding one line per killed
    run, invisibly, in a gate the flow depends on. The probe now refuses a file
    that already carries the marker and leaves a sidecar while it works; this
    asserts neither is sitting in the tree.
    """
    stale = PROBE.stale_backups()
    assert not stale, (
        "a probe was interrupted and left %d backup(s): %s\n"
        "Restore each program from its sidecar (or from git) and delete the "
        "sidecar before trusting any result in this file."
        % (len(stale), ", ".join(p.name for p in stale)))
    marked = [p.name for p in PROGRAMS_DIR.glob("*.py")
              if p.name != "gate_cli_mutation_probe.py"
              and "# NEUTERED" in p.read_text(errors="replace")]
    assert not marked, (
        "these programs carry the probe's NEUTERED marker and cannot fail: %s"
        % ", ".join(marked))

# --- #547 review: the probe must not mutate the tree other sessions read -----

def test_the_default_run_never_touches_the_shipped_programs_tree(tmp_path):
    """A neutered gate returns 0, so a concurrent reader sees a PASS it did not
    earn. That is worse than the same-shaped hazard measured at v1.7.97, where
    an injected file made other sessions FAIL — wrong, but loud. This one is
    quiet and green, for exactly the class of check whose job is to be able to
    fail.

    Asserted on `git status` of the shipped tree across a real probe run, not on
    the presence of a `--programs-root` flag: the flag existing proves nothing
    about which path the default takes.
    """
    import subprocess as sp
    def dirt():
        r = sp.run(["git", "status", "--porcelain", "programs"],
                   cwd=PLUGIN_ROOT, capture_output=True, text=True, timeout=60)
        return r.stdout
    before = dirt()
    r = sp.run([sys.executable, str(PROGRAMS_DIR / "gate_cli_mutation_probe.py"),
                "spec_declaration_emit"],
               cwd=PLUGIN_ROOT, capture_output=True, text=True, timeout=600)
    assert dirt() == before, (
        "the probe modified the shipped programs tree; while a gate is neutered "
        "any concurrent reader of it gets an unearned PASS\n" + dirt())
    assert "CAUGHT" in r.stdout or "SILENT" in r.stdout, (
        "the probe did not reach a verdict, so the no-dirt assertion above "
        "proves only that it did nothing:\n" + r.stdout + r.stderr)


def test_the_probe_can_still_report_SILENT(tmp_path):
    """CONTROL. Without this, CAUGHT on every real gate is indistinguishable
    from a probe that always says CAUGHT. Same gate, a copy whose test file
    keeps the NAME (so it is still selected) but has been blunted."""
    import shutil, subprocess as sp
    root = tmp_path / "programs"
    shutil.copytree(PROGRAMS_DIR, root,
                    ignore=shutil.ignore_patterns("__pycache__", ".pytest_cache"))
    hit = 0
    for f in (root / "tests").glob("test_*.py"):
        if "spec_declaration_emit" in f.read_text():
            f.write_text("import spec_declaration_emit  # noqa: F401\n\n"
                         "def test_placeholder():\n    assert True\n")
            hit += 1
    assert hit, "no test file names the program — the control is vacuous"
    r = sp.run([sys.executable, str(PROGRAMS_DIR / "gate_cli_mutation_probe.py"),
                "spec_declaration_emit", "--programs-root", str(root)],
               cwd=PLUGIN_ROOT, capture_output=True, text=True, timeout=600)
    assert "SILENT" in r.stdout, (
        "a gate whose tests cannot see it was neutered still reported CAUGHT — "
        "the probe is asserting, not measuring:\n" + r.stdout + r.stderr)
