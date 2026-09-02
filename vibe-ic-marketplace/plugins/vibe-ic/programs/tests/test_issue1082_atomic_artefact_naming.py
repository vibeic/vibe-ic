"""A declared artefact under its final name means the write completed. #1082.

The load-bearing pair here is the KILL pair, and the RED arm is the point of
the file: it does not merely show the fix working, it demonstrates the defect
the fix removes, using the REAL `required_outputs` predicate as the victim.

    fixed    kill mid-write -> final name absent  -> required_outputs MISSING
    unfixed  kill mid-write -> final name present -> required_outputs PASS
                               (truncated, and nothing downstream can tell)

The unfixed arm is not a model of the old code. `(d / "results.json")
.write_text(...)` is verbatim what `origin/main` runs at every one of the 31
converted sites, so the arm exercises the pre-fix idiom itself.

SIGKILL specifically, and not an exception: an exception would be caught by
the helper's own `except BaseException`, which is a different (and much
easier) claim. SIGKILL is what a `finally` cannot cover and what an OOM killer
or a torn-down process group actually sends — it proves the guarantee comes
from the RENAME, not from cleanup code the dying process would have had to run.
"""
import hashlib
import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

import pytest

PLUGIN = Path(__file__).resolve().parent.parent.parent
PROGRAMS = PLUGIN / "programs"
sys.path.insert(0, str(PROGRAMS))
import _atomic_artefact as AA  # noqa: E402

#: Step 33's declared output. A real entry from the flow YAML, not an invented
#: path, so the predicate under test is resolving something it really resolves.
REL = "reports/phase3/ir_drop.json"

#: Big enough that a write is observably in progress. The kill is not timed —
#: the harness POLLS until a partial file is on disk and only then signals, so
#: the size sets how wide that window is, never whether the test is correct.
PAYLOAD_MB = 64
PAYLOAD = "x" * (PAYLOAD_MB * 1024 * 1024)


def _kill_mid_write(tmp_path, arm):
    """Start a writer, kill it once a partial artefact is observable.

    Returns (final_exists, final_size, final_md5, leftovers, killed_at).
    """
    dest = tmp_path / REL
    dest.parent.mkdir(parents=True, exist_ok=True)
    child = tmp_path / "child.py"
    child.write_text(
        "import sys\n"
        f"sys.path.insert(0, {str(PROGRAMS)!r})\n"
        "from pathlib import Path\n"
        f"payload = 'x' * ({PAYLOAD_MB} * 1024 * 1024)\n"
        f"dest = Path({str(dest)!r})\n"
        + ("import _atomic_artefact as _aa\n_aa.write_text(dest, payload)\n"
           if arm == "fixed" else
           # verbatim the pre-fix idiom — see module docstring
           "dest.write_text(payload)\n"))

    proc = subprocess.Popen([sys.executable, str(child)])
    full = PAYLOAD_MB * 1024 * 1024
    watched = dest if arm == "unfixed" else None
    killed_at = None
    deadline = time.time() + 60
    try:
        while time.time() < deadline:
            if watched is None:
                cands = list(dest.parent.glob(dest.name + AA.TMP_SUFFIX + ".*"))
                if cands:
                    watched = cands[0]
            if watched is not None and watched.exists():
                size = watched.stat().st_size
                if 0 < size < full:
                    proc.send_signal(signal.SIGKILL)
                    killed_at = size
                    break
            time.sleep(0.001)
    finally:
        if proc.poll() is None:
            proc.send_signal(signal.SIGKILL)
        proc.wait()

    assert killed_at is not None, (
        f"never observed a partial write for arm={arm}; the {PAYLOAD_MB}MB "
        "payload completed before the poll could signal, so this run proves "
        "nothing either way")
    exists = dest.exists()
    return (exists,
            dest.stat().st_size if exists else None,
            hashlib.md5(dest.read_bytes()).hexdigest() if exists else None,
            sorted(p.name for p in
                   dest.parent.glob(dest.name + AA.TMP_SUFFIX + ".*")),
            killed_at)


def _required_outputs_verdict(project):
    """The REAL consumer: `flow_compliance_check`'s own presence check."""
    import flow_compliance_check as fcc
    ok, found, missing = fcc._check_files_exist(project, [REL], False)
    return ok, found, missing


# ---------------------------------------------------------------------------
# THE PAIR
# ---------------------------------------------------------------------------
@pytest.mark.timeout(120)
def test_fixed_a_killed_write_leaves_nothing_under_the_final_name(tmp_path):
    exists, size, md5, leftovers, killed_at = _kill_mid_write(tmp_path, "fixed")
    assert exists is False, (
        f"killed at {killed_at} bytes and the final name still exists "
        f"(size={size}, md5={md5})")
    ok, found, missing = _required_outputs_verdict(tmp_path)
    assert ok is False and missing == [REL], (
        f"required_outputs must report the declared output MISSING when the "
        f"step died: ok={ok} found={found} missing={missing}")
    # The partial is not merely invisible — it is NAMED, and attributable.
    assert len(leftovers) == 1 and AA.is_temp_artefact(leftovers[0]), leftovers


@pytest.mark.timeout(120)
def test_unfixed_a_killed_write_leaves_a_truncated_file_that_PASSES(tmp_path):
    """The red arm. Without the fix the artefact exists, is truncated, and the
    real predicate credits the step with having produced it."""
    exists, size, md5, leftovers, killed_at = _kill_mid_write(tmp_path,
                                                              "unfixed")
    full = PAYLOAD_MB * 1024 * 1024
    assert exists is True, "expected the pre-fix idiom to leave a partial file"
    assert size < full, f"not actually truncated: {size} == {full}"
    assert md5 != hashlib.md5(PAYLOAD.encode()).hexdigest(), (
        "the partial must not hash equal to the complete payload")
    assert leftovers == [], "the pre-fix idiom writes no temp at all"

    import flow_compliance_check as fcc
    assert fcc._resolves_to_real_artefact(tmp_path / REL) is True, (
        "the presence predicate returns True for a non-symlink unconditionally "
        "— this is the property the fix works around, not one it changes")
    ok, found, missing = _required_outputs_verdict(tmp_path)
    assert ok is True and found == [REL] and missing == [], (
        "THE DEFECT: required_outputs reports PASS over a file truncated at "
        f"{size} of {full} bytes (killed at {killed_at}). ok={ok}")


# ---------------------------------------------------------------------------
# The helper's own contract
# ---------------------------------------------------------------------------
def test_a_raising_writer_leaves_no_final_name_and_no_temp(tmp_path):
    dest = tmp_path / "r" / "out.json"
    boom = RuntimeError("step died")
    with pytest.raises(RuntimeError) as ei:
        with AA.writing(dest) as fh:
            fh.write('{"half":')
            raise boom
    assert ei.value is boom, "the original exception must propagate unchanged"
    assert not dest.exists()
    assert list(dest.parent.glob("*")) == []


def test_a_completing_writer_does_leave_the_final_name(tmp_path):
    """The control for the pair above: a helper that removed the artefact in
    every case would satisfy it and be useless."""
    dest = tmp_path / "r" / "out.json"
    with AA.writing(dest) as fh:
        fh.write("done")
    assert dest.read_text() == "done"
    assert list(dest.parent.glob("*" + AA.TMP_SUFFIX + ".*")) == []


def test_the_temp_is_a_sibling_so_the_rename_cannot_cross_a_filesystem(tmp_path):
    dest = tmp_path / "deep" / "out.json"
    assert AA.temp_name_for(dest).parent == dest.parent


def test_write_json_writes_nothing_when_the_object_is_not_serialisable(tmp_path):
    dest = tmp_path / "out.json"
    with pytest.raises(TypeError):
        AA.write_json(dest, {"bad": object()})
    assert not dest.exists()
    assert list(tmp_path.glob("*")) == []


def test_write_json_round_trips_and_ends_with_a_newline(tmp_path):
    dest = tmp_path / "out.json"
    AA.write_json(dest, {"a": [1, 2]})
    raw = dest.read_text()
    assert raw.endswith("\n") and json.loads(raw) == {"a": [1, 2]}


def test_write_bytes_is_atomic_too(tmp_path):
    dest = tmp_path / "out.bin"
    AA.write_bytes(dest, b"\x00\x01")
    assert dest.read_bytes() == b"\x00\x01"


def test_is_temp_artefact_accepts_ours_and_rejects_a_real_name():
    assert AA.is_temp_artefact("ir_drop.json.tmp.1234")
    assert not AA.is_temp_artefact("ir_drop.json")
    assert not AA.is_temp_artefact("ir_drop.tmp.json")


def test_replacing_an_existing_artefact_never_exposes_a_partial(tmp_path):
    """The honest limit, pinned: a re-run that dies leaves the PREVIOUS
    complete artefact — never nothing, and never a mixture."""
    dest = tmp_path / "out.json"
    AA.write_json(dest, {"v": 1})
    before = dest.read_text()
    with pytest.raises(RuntimeError):
        with AA.writing(dest) as fh:
            fh.write("{partial")
            raise RuntimeError("died")
    assert dest.read_text() == before


# ---------------------------------------------------------------------------
# Drift: one helper, not N copies
# ---------------------------------------------------------------------------
def _declared_basenames():
    import yaml
    doc = yaml.safe_load((PLUGIN / "flow" /
                          "phase1_phase2_phase3.yaml").read_text())
    outs = []

    def walk(o):
        if isinstance(o, dict):
            for k, v in o.items():
                if k == "required_outputs" and isinstance(v, list):
                    outs.extend(x for x in v if isinstance(x, str))
                else:
                    walk(v)
        elif isinstance(o, list):
            for x in o:
                walk(x)
    walk(doc)
    return {os.path.basename(a.strip())
            for spec in outs for a in spec.split(" OR ")
            if "*" not in os.path.basename(a.strip())}


def test_no_declared_output_is_written_with_a_raw_write_text():
    """States its own DENOMINATOR, and its own blind spot.

    Covers write sites whose TARGET EXPRESSION contains a literal naming one of
    the flow's declared outputs. A site that builds its destination from a
    variable names no literal and is invisible here — this is a lower bound on
    conversion, and saying so is the difference between a guard and a claim of
    completeness it cannot support.
    """
    import ast
    bases = _declared_basenames()
    assert len(bases) > 100, f"declared-output set collapsed to {len(bases)}"
    residual = []
    for f in sorted(PROGRAMS.glob("*.py")):
        if f.name.startswith("_"):
            continue
        try:
            tree = ast.parse(f.read_text(encoding="utf-8", errors="replace"))
        except SyntaxError:
            continue
        for n in ast.walk(tree):
            if (isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
                    and n.func.attr in ("write_text", "write_bytes")):
                lits = {c.value for c in ast.walk(n.func.value)
                        if isinstance(c, ast.Constant)
                        and isinstance(c.value, str)}
                if lits & bases:
                    residual.append(f"{f.name}:{n.lineno}")
    assert residual == [], (
        "declared outputs written without the atomic helper — a partial one "
        "would read as complete to required_outputs:\n  "
        + "\n  ".join(residual))


def test_the_guard_above_would_fire_on_a_reverted_site(tmp_path):
    """The control. Without this, the guard passes trivially if the AST walk is
    broken, and a silent 'no residual' is exactly the vacuous green this repo
    keeps removing."""
    import ast
    bases = _declared_basenames()
    probe = tmp_path / "probe.py"
    probe.write_text('from pathlib import Path\n'
                     'def f(d):\n'
                     '    (d / "ir_drop.json").write_text("{}")\n')
    tree = ast.parse(probe.read_text())
    found = []
    for n in ast.walk(tree):
        if (isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
                and n.func.attr in ("write_text", "write_bytes")):
            lits = {c.value for c in ast.walk(n.func.value)
                    if isinstance(c, ast.Constant) and isinstance(c.value, str)}
            if lits & bases:
                found.append(n.lineno)
    assert found == [3], (
        "the walk used by the guard above cannot see a reverted site, so its "
        f"green means nothing: {found}")


# ---------------------------------------------------------------------------
# THE PAIR, ON A REAL CONVERTED PRODUCER (vibe-ic#2014 tail)
#
# `test_no_declared_output_is_written_with_a_raw_write_text` above is a STATIC
# residual count. It went red on three sites that landed with the formal flow
# and never adopted the helper:
#
#     design_one_shot_runner.py:16935   formal_not_applicable.json
#     design_one_shot_runner.py:16960   formal_authoring_request.json
#     formal_property_run.py:1349       formal_authoring_request.json
#
# Both names are DECLARED `required_outputs` of step 5 in
# `flow/phase1_phase2_phase3.yaml`. A static residual of `[]` is necessary and
# not sufficient: the guarantee #1082 buys is that a rename survives SIGKILL,
# and only a kill can show that. So the conversion is graded the way the
# module's own pair grades the helper — by killing a real producer mid-write
# and asking `flow_compliance_check` what it sees.
#
# The two arms differ in ONE thing: whether the converted call reaches
# `_atomic_artefact.write_json` or the raw idiom it replaced. That makes this
# the control for the fix itself — restore the raw write and the FIXED arm
# reproduces the red.
# ---------------------------------------------------------------------------
FORMAL_REL = "phase2/stage1/formal/formal_authoring_request.json"


def _kill_a_real_producer(tmp_path, arm):
    """Drive `formal_property_run._write_authoring_incomplete` and SIGKILL it.

    The payload is made observable by handing the producer a `reason` large
    enough that the write is in progress when the poll fires — the producer,
    the destination and the serialisation are its own, unchanged.
    """
    dest = tmp_path / FORMAL_REL
    dest.parent.mkdir(parents=True, exist_ok=True)
    child = tmp_path / "producer.py"
    revert = (
        "" if arm == "fixed" else
        # VERBATIM the pre-fix idiom, injected at the one seam the fix moved.
        "import json as _j\n"
        "def _raw(path, obj, **kw):\n"
        "    path.write_text(_j.dumps(obj, indent=2, ensure_ascii=False)+'\\n')\n"
        # `hasattr`, so the PRE-FIX tree answers this test instead of raising.
        # There the producer is already raw and there is no seam to patch; an
        # AttributeError here would make the control observe nothing on the
        # exact tree it exists to characterise.
        "if hasattr(F, '_aa'):\n"
        "    F._aa.write_json = _raw\n")
    child.write_text(
        "import sys\n"
        f"sys.path.insert(0, {str(PROGRAMS)!r})\n"
        "from pathlib import Path\n"
        "import formal_property_run as F\n"
        + revert +
        f"reason = 'x' * ({PAYLOAD_MB} * 1024 * 1024)\n"
        f"F._write_authoring_incomplete(Path({str(dest.parent)!r}), reason)\n",
        encoding="utf-8")

    proc = subprocess.Popen([sys.executable, str(child)])
    watched = dest if arm == "unfixed" else None
    killed_at = None
    deadline = time.time() + 120
    try:
        while time.time() < deadline:
            if watched is None:
                cands = list(dest.parent.glob(dest.name + AA.TMP_SUFFIX + ".*"))
                if cands:
                    watched = cands[0]
            if watched is not None and watched.exists():
                size = watched.stat().st_size
                if 0 < size < PAYLOAD_MB * 1024 * 1024:
                    proc.send_signal(signal.SIGKILL)
                    killed_at = size
                    break
            time.sleep(0.001)
    finally:
        if proc.poll() is None:
            proc.send_signal(signal.SIGKILL)
        proc.wait()

    assert killed_at is not None, (
        f"never observed a partial write for arm={arm}; this run proves "
        "nothing either way")
    return dest.exists(), killed_at


def _formal_required_outputs_verdict(project):
    import flow_compliance_check as fcc
    return fcc._check_files_exist(project, [FORMAL_REL], False)


@pytest.mark.timeout(240)
def test_a_killed_real_producer_leaves_no_declared_output_behind(tmp_path):
    """THE CONVERTED SITE, KILLED. `formal_authoring_request.json` must be
    absent, so `required_outputs` reports MISSING and the run says the work is
    unfinished — which it is."""
    exists, killed_at = _kill_a_real_producer(tmp_path, "fixed")
    assert not exists, (
        f"killed at {killed_at} bytes and {FORMAL_REL} still exists — a "
        "partial receipt reads to required_outputs as a complete one")
    ok, _found, missing = _formal_required_outputs_verdict(tmp_path)
    assert not ok and missing, (ok, missing)


@pytest.mark.timeout(240)
def test_reverting_that_one_site_brings_the_truncated_pass_back(tmp_path):
    """THE OTHER DIRECTION, and the control for the fix. With the raw idiom
    restored at the same seam, the kill leaves a truncated file and
    `flow_compliance_check` reports the declared output PRESENT."""
    exists, killed_at = _kill_a_real_producer(tmp_path, "unfixed")
    assert exists, f"expected a truncated leftover (killed at {killed_at})"
    ok, found, _missing = _formal_required_outputs_verdict(tmp_path)
    assert ok and found, (
        "the pre-fix idiom must reproduce the defect this conversion closes")
    size = (tmp_path / FORMAL_REL).stat().st_size
    assert size < PAYLOAD_MB * 1024 * 1024, size
    with pytest.raises(json.JSONDecodeError):
        json.loads((tmp_path / FORMAL_REL).read_text(errors="replace"))
