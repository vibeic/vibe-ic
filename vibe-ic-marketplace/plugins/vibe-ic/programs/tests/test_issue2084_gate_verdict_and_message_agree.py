#!/usr/bin/env python3
"""vibe-ic#2084 — `project_outputs_in_tree_check` must state its finding at
the severity it exits with, on the line a reader is entitled to read.

MEASURED (lane rbsha2, 2026-09-07, plugin v1.17.62): the completion audit read
246 invoked / 182 passed / 1 failed, and the message it published for the one
failed gate was that gate's own

    "[INFO] … 2 ephemeral process-marker reference(s) — non-blocking (the
     supervised watchdog removes these pidfiles after child exit; they are
     runtime metadata, not project outputs)"

— one sentence saying both that the finding does not matter and that the run
failed on it.

REPRODUCED on the pristine tip (8HD-4, lane cz2084, pinned image), and the
reproduction moved the diagnosis: the marker class was ALREADY non-blocking in
code — `_WATCHDOG_PIDFILE_RE` matches are `continue`d before a finding is
recorded, and a project whose only volatile references are two watchdog
pidfiles exits 0 (`test_process_markers_alone_do_not_fail_the_gate` below,
which passed before the fix too and is kept as the no-leak control). The gate
was not failing ON the markers. It was failing on a separate, genuinely
blocking reference in the same tree and never saying so, for two reasons:

  (1) `flow_compliance_check._p0_first_line` publishes a failed gate's FIRST
      output line as its reason, and the four non-blocking [INFO] disclosures
      were printed BEFORE the verdict line — so line 0 of a FAIL was a note
      whose own words are "non-blocking".

  (2) a dangling-only failure (`live` empty, `dangling` non-empty) exits 1 and
      used to print NO failing line at all: its top severity was `[WARN]`. A
      reader holding the FULL stdout was still told the worst thing present was
      a warning.

Both halves are reporting, not verdicts: every exit code is unchanged. These
tests pin the reporting so it cannot drift back, and the no-leak controls pin
that the detection side did not move.
"""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

_PROGRAMS = Path(__file__).resolve().parents[1]
if str(_PROGRAMS) not in sys.path:
    sys.path.insert(0, str(_PROGRAMS))

import flow_compliance_check as F                # noqa: E402

PROG = _PROGRAMS / "project_outputs_in_tree_check.py"

# The exact pidfile namespace `_docker_watchdog.py` owns; the gate classifies
# these as runtime metadata. Two of them, as the #2084 evidence had.
_MARKERS = ["/tmp/.vibeic-job-alpha2084.pid", "/tmp/.vibeic-job-beta2084.pid"]


def _run(project: Path) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(PROG), str(project)],
                          capture_output=True, text=True)


def _verdict_lines(out: str):
    """(index, tag) for every line that carries a bracketed severity tag."""
    return [(i, ln.split("]")[0] + "]")
            for i, ln in enumerate(out.splitlines())
            if ln.startswith("[")]


@pytest.fixture
def stray():
    """A file that really exists under a volatile prefix, for the LIVE case.

    Built under `/tmp` explicitly rather than via `tmp_path`: `_PATH_RE` admits
    nothing but /tmp, /var/tmp, /dev/shm, /run, so a subject placed wherever
    TMPDIR happens to point measures the harness instead of the gate — the same
    reason `test_project_outputs_in_tree_check.volatile_project` pins its own.
    """
    d = Path(tempfile.mkdtemp(dir="/tmp", prefix="i2084-stray-"))
    f = d / "chip_top.gds"
    f.write_text("# stray project output\n", encoding="utf-8")
    try:
        yield f
    finally:
        import shutil
        shutil.rmtree(d, ignore_errors=True)


def _project(root: Path, extra_refs=()) -> Path:
    """The #2084 tree: a report citing the two markers, plus `extra_refs`."""
    (root / "reports").mkdir(parents=True, exist_ok=True)
    (root / "reports" / "audit.json").write_text(json.dumps({
        "watchdog": list(_MARKERS),
        "notes": list(extra_refs),
    }), encoding="utf-8")
    return root


# ── 1. THE REPORTED SYMPTOM: a blocking run must publish a blocking reason ──

def test_a_blocking_run_does_not_publish_a_non_blocking_first_line(tmp_path):
    """The exact #2084 shape: markers + one dangling reference → rc 1.

    Asserted through `_p0_first_line`, the function the completion audit
    actually uses to fill a failed gate's `message`, so this measures the
    string a reader gets rather than a substring of stdout somewhere.
    """
    proj = _project(tmp_path, ["gds was written to /tmp/i2084-gone/chip.gds"])
    r = _run(proj)
    assert r.returncode == 1, r.stdout + r.stderr

    published = F._p0_first_line(r.stdout)
    assert published.startswith("[FAIL]"), (
        f"the audit would publish {published!r} as the reason this gate "
        f"failed")
    assert "non-blocking" not in published, published
    assert "blocking external-storage reference" in published, published


def test_the_verdict_line_precedes_every_non_blocking_disclosure(
        tmp_path, stray):
    """Ordering, on all three outcomes the gate can reach with disclosures.

    A disclosure that sorts ahead of the verdict is the mechanism of (1): it
    does not matter WHICH note it is, only that a note can occupy line 0.
    """
    for extra, want in (
            ([], "[PASS]"),
            ([f"gds at {stray}"], "[FAIL]"),
            (["gds at /tmp/i2084-gone/chip.gds"], "[FAIL]"),
    ):
        root = tmp_path / f"p{want}{len(extra)}{len(str(extra))}"
        proj = _project(root, extra)
        r = _run(proj)
        tags = _verdict_lines(r.stdout)
        assert tags, r.stdout
        first_i, first_tag = tags[0]
        assert first_tag == want, f"{extra}: first tagged line is {first_tag}"
        infos = [i for i, t in tags if t == "[INFO]"]
        assert infos, f"{extra}: the marker disclosure vanished"
        assert min(infos) > first_i, (
            f"{extra}: a non-blocking [INFO] at line {min(infos)} precedes "
            f"the verdict at line {first_i}")


# ── 2. ONE CLASSIFICATION: rc 1 is never topped by a non-blocking word ──────

def test_a_dangling_only_failure_is_tagged_at_the_severity_it_exits_with(
        tmp_path):
    """Defect (2): this used to exit 1 with `[WARN]` as its only tag."""
    proj = _project(tmp_path,
                    ["GDS written to /tmp/i2084-swept/chip_top.gds"])
    r = _run(proj)
    assert r.returncode == 1, r.stdout + r.stderr
    tags = {t for _i, t in _verdict_lines(r.stdout)}
    assert "[FAIL]" in tags, r.stdout
    assert "[WARN]" not in tags, (
        "a blocking exit may not be topped by a warning: " + r.stdout)
    assert "dangling external-path" in r.stdout
    assert "/tmp/i2084-swept/chip_top.gds" in r.stdout, (
        "the blocking reference must be NAMED")


def test_every_blocking_reference_is_named_and_counted(tmp_path, stray):
    """live + dangling together: the deciding line carries the population."""
    proj = _project(tmp_path, [f"gds at {stray}",
                               "def at /tmp/i2084-gone/floor.def"])
    r = _run(proj)
    assert r.returncode == 1, r.stdout + r.stderr
    head = r.stdout.splitlines()[0]
    assert head.startswith("[FAIL]"), head
    assert "2 blocking external-storage reference(s)" in head, head
    assert "(1 live, 1 dangling)" in head, head
    assert str(stray) in r.stdout
    assert "/tmp/i2084-gone/floor.def" in r.stdout


# ── 3. NO-LEAK CONTROLS: the detection side did not move ───────────────────
#
# These three are GREEN AGAINST THE PRE-FIX GATE TOO, on purpose. A control
# that only passes after the change proves the change, not the invariant; it
# cannot tell you the fix left detection alone, which is the one thing a
# control is for. So they assert exit codes and NAMES only — never ordering,
# never a severity tag, both of which the fix deliberately moves and which are
# pinned by sections 1 and 2 above instead.
#
# MEASURED both directions (8HD-4, lane cz2084, pinned image, by explicit
# `git show <base>:<path>` file swap, not `git stash`):
#     pre-fix gate  : sections 1+2 -> 5 failed, this section -> 3 passed
#     post-fix gate : all 8 passed

def test_process_markers_alone_do_not_fail_the_gate(tmp_path):
    """The class the issue named IS non-blocking, and was before the fix too.

    Kept as the control that states it: two watchdog pidfiles and nothing else
    exit 0, with the markers disclosed rather than swallowed.
    """
    proj = _project(tmp_path)
    r = _run(proj)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "[PASS]" in r.stdout, r.stdout
    assert "2 ephemeral process-marker reference(s)" in r.stdout
    for m in _MARKERS:
        assert m in r.stdout, f"{m} disclosed but not named"


def test_a_live_stray_output_still_fails_beside_the_markers(tmp_path, stray):
    """A real stray project output blocks, named, even in a tree full of
    non-blocking disclosures. This is the half a mis-classification would
    silence, so it is asserted on the same tree as the markers."""
    proj = _project(tmp_path, [f"final GDS: {stray}"])
    r = _run(proj)
    assert r.returncode == 1, r.stdout + r.stderr
    assert "live external-storage artifact" in r.stdout
    assert str(stray) in r.stdout


def test_a_waived_reference_still_passes_with_the_markers_disclosed(tmp_path):
    """The waiver route is unchanged, and its disclosure follows it too."""
    proj = _project(tmp_path, ["cache at /tmp/i2084-cache/inter.json"])
    (proj / "waivers.json").write_text(json.dumps({
        "project_artifacts_external_storage_intentional":
            "Build cache lives under /tmp by design, is never cited as audit "
            "evidence, and is rotated by the OS sweep; documented in the run "
            "book beside the cache architecture.",
    }), encoding="utf-8")
    r = _run(proj)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "[PASS_WITH_WAIVER]" in r.stdout, r.stdout


# ── 4. THE CONTRACT IS STATED ONCE (a fix assertion, not a control) ────────

def test_the_docstring_no_longer_declares_a_narrower_rule_than_the_code():
    """The module prose used to say FAIL required the file to still exist,
    while `main()` has always exited 1 on dangling references as well. Two
    classifications in one file is the defect #2084 names; the prose is held
    to the code's."""
    doc = PROG.read_text(encoding="utf-8").split('"""')[1]
    assert "FAIL when found\n    AND the referenced file actually exists" \
        not in doc
    assert "dangling" in doc, (
        "the exit-code table must name the dangling half it blocks on")
