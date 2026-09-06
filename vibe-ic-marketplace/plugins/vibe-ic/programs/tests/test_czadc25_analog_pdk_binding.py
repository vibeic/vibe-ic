"""`--pdk` reaches the analog track, and a contradiction REFUSES.

Measured on `u_hawaii_adc` (lane czadc25, host 8hd-3, image 0.3.46): a run
invoked with `--pdk sky130A` wrote `layout_provenance.json` naming ihp-sg13g2
twelve times and sky130A zero times, and raised no mismatch advisory. The
analog invocation in `vibe_ic_one_shot_runner` forwarded only `--container`,
while the phase1 and phase3 invocations either side of it both forwarded
`--pdk`. The A-track is the one track whose every step is a PDK-bound
simulation or a PDK-bound rule deck, so the flag that named its PDK was the
only part of the run that was about that PDK.

The ruling this pins: BIND OR REFUSE, NEVER SILENTLY IGNORE.
"""
import ast
import json
import subprocess
import sys
from pathlib import Path

import pytest

PROGRAMS = Path(__file__).resolve().parents[1]
ONE_SHOT = PROGRAMS / "vibe_ic_one_shot_runner.py"
ANALOG = PROGRAMS / "analog_one_shot_runner.py"

sys.path.insert(0, str(PROGRAMS))


# ── the forwarding, read out of the AST rather than out of a grep ───────────

def _analog_dispatch_args(src: str):
    """The argv list literal the ANALOG dispatch is built from, as source.

    Located structurally: the assignment whose target is `_analog_args`. A
    grep for `--pdk` would pass on a `--pdk` that belongs to phase1 or phase3,
    which is exactly the confusion this test exists to prevent.
    """
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            for t in node.targets:
                if isinstance(t, ast.Name) and t.id == "_analog_args":
                    return node
    return None


def test_analog_dispatch_is_built_from_a_named_argv_list():
    node = _analog_dispatch_args(ONE_SHOT.read_text())
    assert node is not None, (
        "the analog dispatch no longer builds `_analog_args`; the forwarding "
        "test below can no longer find its subject")


def test_analog_dispatch_forwards_pdk():
    """RED BEFORE THE FIX: the analog invocation passed `[project,
    --container, args.container]` and nothing else."""
    src = ONE_SHOT.read_text()
    tree = ast.parse(src)
    # every `args.pdk` attribute access inside the analog dispatch region
    node = _analog_dispatch_args(src)
    assert node is not None
    region_start = node.lineno
    # the dispatch region ends at the `_run_phase("ANALOG ...")` call
    end = None
    for n in ast.walk(tree):
        if (isinstance(n, ast.Call) and getattr(n.func, "id", "") == "_run_phase"
                and n.args and isinstance(n.args[0], ast.Constant)
                and str(n.args[0].value).startswith("ANALOG A1")):
            end = n.lineno
    assert end is not None and end > region_start
    region = "\n".join(src.splitlines()[region_start - 1:end])
    assert "args.pdk" in region, (
        "the ANALOG dispatch does not consult args.pdk; a run driven with "
        "--pdk would produce analog evidence that has nothing to do with it")
    assert "--pdk" in region
    assert '"auto"' in region, (
        "`auto` is the argparse default and means 'the design decides'; "
        "forwarding it as a selector would make every default run claim a PDK")


def test_analog_runner_accepts_pdk():
    """The flag the orchestrator now forwards must be one the analog runner
    can receive — otherwise the forwarding turns every analog run into an
    argparse error."""
    out = subprocess.run([sys.executable, str(ANALOG), "--help"],
                         capture_output=True, text=True, timeout=120)
    assert out.returncode == 0, out.stderr
    assert "--pdk" in out.stdout


# ── the family comparator ──────────────────────────────────────────────────

@pytest.mark.parametrize("a,b,expect", [
    ("ihp-sg13g2", "sg13g2", True),      # L19 carries the bare family
    ("sky130A", "sky130", True),         # installed dir carries a suffix
    ("gf180mcuD", "gf180", True),
    ("sky130A", "sg13g2", False),        # the contradiction that was invisible
    ("ihp-sg13g2", "ihp-sg13cmos5l", False),  # shared 'ihp' must not agree
    ("", "sg13g2", None),                # NOT False: nothing was compared
    ("sg13g2", "", None),
    ("ab", "sg13g2", None),              # too short to name a family
])
def test_families_agree(a, b, expect):
    import analog_pdk_availability as apa
    assert apa.families_agree(a, b) is expect


# ── the refusal, run end to end ────────────────────────────────────────────

def _project(tmp: Path, declared: str) -> Path:
    import _path_layout as _pl
    proj = tmp / "proj"
    (proj / "phase1" / "generated_docs").mkdir(parents=True)
    (proj / "phase1" / "generated_docs" / "L19_CONSTRAINTS_PDK.json").write_text(
        json.dumps({"doc_id": "L19", "fields": {"pdk_target": declared}}))
    # THE BLOCK LIST GOES WHERE THE RUNNER LOOKS, asked of the runner's own
    # path library. Typing `analog/` here put it two directories from where
    # `analog_dir()` resolves, and the runner's honest "block list missing"
    # refusal then read like a failure of the fix under test.
    bl = _pl.analog_dir(proj) / "analog_block_list.json"
    bl.parent.mkdir(parents=True, exist_ok=True)
    bl.write_text(json.dumps({"blocks": [{"name": "b0", "type": "ldo"}]}))
    return proj


def _report(proj: Path) -> Path:
    """WHERE THE RUNNER PUTS IT, asked of the runner's own path library rather
    than typed here. A test that hardcodes `reports/analog_one_shot.json`
    fails on a tree that writes `reports/phase3/analog_one_shot.json`, and the
    failure looks like the fix rather than like the test."""
    import _path_layout as _pl
    return _pl.report_path(proj, "analog_one_shot.json")


def _run(proj: Path, *extra):
    """No pipe between the runner and `returncode`. The finding this file
    pins was first reported as "the misroute exits rc=0"; the 0 was `tail`'s
    exit code, read through a pipe. The real code was 2."""
    return subprocess.run([sys.executable, str(ANALOG), str(proj), *extra],
                          capture_output=True, text=True, timeout=900)


def test_contradicting_pdk_refuses_and_names_both(tmp_path):
    """A `--pdk` that contradicts the design's declaration stops the run and
    names BOTH — it does not substitute either one in silence."""
    proj = _project(tmp_path, "sg13g2")
    cp = _run(proj, "--pdk", "sky130A")
    assert cp.returncode != 0, (cp.returncode, cp.stdout, cp.stderr)
    blob = cp.stdout + cp.stderr
    assert "sky130A" in blob, "the refusal does not name the FLAG"
    assert "sg13g2" in blob, "the refusal does not name the DECLARATION"
    rep = json.loads(_report(proj).read_text())
    assert rep["verdict"] == "BLOCKED"
    assert rep["pdk_flag"] == "sky130A"
    assert rep["pdk_declared"] == "sg13g2"
    # NOTHING was simulated on the way to the refusal.
    assert not list(proj.rglob("corner_results.json"))


def test_agreeing_pdk_does_not_refuse(tmp_path):
    """THE CONTROL, and the direction written down first: a flag that AGREES
    with the declaration must not produce a refusal. Without this the test
    above passes for a runner that refuses everything.

    `--blocks` selects nothing so the control measures the REFUSAL DECISION —
    which runs before the block list is loaded — and not a full A1-A9 sweep."""
    proj = _project(tmp_path, "sg13g2")
    cp = _run(proj, "--pdk", "ihp-sg13g2", "--blocks", "__none__")
    assert cp.returncode == 0, (cp.stdout, cp.stderr)
    rep = json.loads(_report(proj).read_text())
    assert rep["verdict"] != "BLOCKED"
    assert "CONTRADICTS" not in (cp.stdout + cp.stderr)


def test_no_declaration_is_not_a_contradiction(tmp_path):
    """A project that declares nothing keeps running on the operator's flag.
    `families_agree` returns None there, and None is not False: a comparison
    that could not be MADE must never be reported as one that failed."""
    proj = _project(tmp_path, "")
    cp = _run(proj, "--pdk", "sky130A", "--blocks", "__none__")
    assert cp.returncode == 0, (cp.stdout, cp.stderr)
    rep = json.loads(_report(proj).read_text())
    assert rep["verdict"] != "BLOCKED"


def test_no_flag_is_not_a_contradiction(tmp_path):
    """And the pre-fix invocation shape — no `--pdk` at all — is unchanged."""
    proj = _project(tmp_path, "sg13g2")
    cp = _run(proj, "--blocks", "__none__")
    assert cp.returncode == 0, (cp.stdout, cp.stderr)
    rep = json.loads(_report(proj).read_text())
    assert rep["verdict"] != "BLOCKED"
