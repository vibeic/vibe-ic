#!/usr/bin/env python3
"""vibe-ic#969 + #970 — the report half of `sync_image_version.py` is not as
safe as it claims, and the count it prints is not the population it declared.

TWO HALVES OF ONE FINDING, which is why they are one file.

#969 — AN INVARIANT THAT WAS A HABIT. `do_report_upstream`'s docstring says
"NEVER RETURNS 1", and #927 landed the CI wiring that depends on it:
`run_tolerating_uncheckable` tolerates rc 2 ONLY, so rc 1 from this path is a
FAIL — the exact outcome #927 was landed to make impossible. Measured on
origin/main:

    python3 tools/vibeic-eda/sync_image_version.py --report-upstream \
            --json /tmp/does-not-exist/x.json
    -> FileNotFoundError, uncaught, rc=1

The unguarded `Path(json_path).write_text(...)` is the instance. The invariant
is the claim, and a claim that holds only for the inputs somebody happened to
try is a habit. So this file pins BOTH: the write cannot kill the process, and
the `--report-upstream` dispatch cannot emit a 1 no matter what escapes from
underneath it.

#969 — AND THE GUARD THAT WAS VACUOUS. The test defending that invariant
asserted `cp.returncode in (0, 2)` and nothing else. argparse's UNKNOWN-FLAG
exit code is ALSO 2, so it passed against a tree where `--report-upstream` does
not exist at all — it could not distinguish "the report correctly degraded to
NOT CHECKED" from "the feature is absent". It also never passed `--json`, the
one flag that broke the invariant.

    A CONTROL THAT PASSES IN BOTH ARMS IS NOT A CONTROL.

`test_the_vacuous_guard_would_have_passed_a_program_without_the_feature` is
this file's own decisiveness proof, and it is a TEST rather than a sentence in
a commit message: it drives a program that has no `--report-upstream` at all
and shows, in one assertion block, that the OLD predicate accepts it and the
NEW one refuses it. If somebody ever loosens the predicate back, that test goes
red.

#970 — A DENOMINATOR THAT DID NOT SAY WHAT IT DROPPED. `INSTALL_DOC_CANDIDATES`
is a DECLARED POPULATION, and its comment says "EVERY vibeic-eda tag in these
is a live pointer". `install_doc_refs` counts only the ones matching
`vibeic-eda:X.Y.Z`, so a registered file whose tags are all FLOATING
contributes zero and leaves no trace: `--check` printed "25 across 10 file(s)"
over 11 registered files and answered `[PASS]`. Measured, two arms, on the same
two lines of the same file:

    as shipped (`:latest`)   25 across 10 / 16 pointers / PASS
    pinned to a stale tag    27 across 11 / 18 pointers / FAIL, both lines named

A stale PIN is caught loudly. A FLOATING pointer in the same registered file,
on the same lines, is silently outside the denominator and the summary still
reads complete. That is the #901 shape — a count that reads as coverage while
one member of the declared population was never measurable — and the house
rule for it is `gate_discloses_denominator_check`: a PASS must say how much it
looked at, and DECLARED vs PROBED must both be printed when they differ.

DISCLOSE, DO NOT BLOCK. Whether those two lines should be pinned to the anchor
is a call for a person; the defect repaired here is that nobody could see there
was a call to make. rc is unchanged in every direction.

PAIRED GUARDS — what must NOT change, so the fix cannot be bought by breaking
something that was already right:

    a doc with a correct PINNED pointer         stays silent (no #970 line)
    a drifted pinned pointer                    still FAILS
    the blocking half                           still makes NO registry call
    a clean tree                                still passes

chip-AGNOSTIC and version-less: every fixture version is synthetic, and nothing
here is coupled to whatever the real anchor happens to be on the day it runs.
"""
from __future__ import annotations

import importlib.util
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

# parents: [0]=tests [1]=programs [2]=vibe-ic [3]=plugins
# [4]=vibe-ic-marketplace [5]=repo root. `test_the_denominator_of_this_file_is_real`
# fails loudly if this is off by one, rather than letting every assertion pass
# vacuously against a path that does not exist.
_REPO = Path(__file__).resolve().parents[5]
_PROG = _REPO / "tools" / "vibeic-eda" / "sync_image_version.py"
_ENV_KEY = "VIBEIC_EDA_PUBLISHED_TAG"

pytestmark = pytest.mark.skipif(
    not _PROG.is_file(),
    reason=f"{_PROG} not present (packaged plugin ships no repo-root tools/)")

#: Assembled, never spelled as a literal — a fully-qualified pull line at a
#: version that is not the anchor is exactly what the repo-wide drift net is
#: built to find, and it is right to find it. A fixture the net cannot see
#: needs no entry on `.image-version-ignore`, and every entry there costs a
#: reader's attention. (The same reasoning, and the same trick, as the #927
#: test file next to this one.)
_IMG = "vibeic-" + "eda"
_GHCR = "ghcr.io/vibeic/" + _IMG


def _load_prog(name="siv969"):
    spec = importlib.util.spec_from_file_location(name, _PROG)
    m = importlib.util.module_from_spec(spec)
    sys.modules[name] = m
    spec.loader.exec_module(m)
    return m


def _env(**extra):
    e = dict(os.environ)
    e.pop(_ENV_KEY, None)
    e.update(extra)
    return e


def _report(args, env_extra=None, cwd=None, prog=None):
    """Run the REPORTING half. Pinned offline by default so the exit code is a
    property of the program and not of whoever's network this runs on."""
    return subprocess.run(
        [sys.executable, str(prog or _PROG), "--report-upstream", *args],
        cwd=str(cwd or _REPO), capture_output=True, text=True,
        env=_env(**(env_extra or {_ENV_KEY: "99.99.99"})))


# ── #969: the guard's own discriminator ──────────────────────────────────────

def _the_report_actually_ran(cp) -> bool:
    """THE PREDICATE THE OLD GUARD WAS MISSING.

    `rc in (0, 2)` is true of a program that HAS the flag and degraded
    honestly, and equally true of a program that does not have the flag at all
    — argparse exits 2 on an unrecognised argument. Two things a guard must be
    able to tell apart, and the old one could not.

    So the discriminator is not the code: it is whether the report RAN. Its
    header line is emitted before any registry call, so it is present in every
    honest outcome including NOT CHECKED, and absent from every outcome where
    the feature is missing or the program died on the way.
    """
    return ("unrecognized arguments" not in cp.stderr
            and "vibeic_eda_upstream_report" in cp.stdout
            and "Traceback" not in cp.stderr)


def _unwritable_json_targets(tmp_path):
    """Every `--json` destination this host can make un-writable, DISCOVERED
    rather than listed — the set differs by platform and by whether the test
    runs as root, and a typed list would silently shrink to nothing.

    Each is a real OSError subclass from a real syscall, not a mock:
        parent missing        FileNotFoundError  (the reported instance)
        parent is a FILE      NotADirectoryError (mkdir -p cannot repair it)
        target IS a directory IsADirectoryError
        parent is read-only   PermissionError    (absent when running as root)
    """
    out = [("parent directory does not exist",
            tmp_path / "no" / "such" / "dir" / "r.json")]

    blocker = tmp_path / "a-file"
    blocker.write_text("not a directory\n")
    out.append(("a parent that is a FILE", blocker / "r.json"))

    isdir = tmp_path / "a-dir"
    isdir.mkdir()
    out.append(("a target that IS a directory", isdir))

    ro = tmp_path / "ro"
    ro.mkdir()
    os.chmod(ro, 0o500)
    if not os.access(ro, os.W_OK):        # false for root — then simply skip it
        out.append(("a read-only parent directory", ro / "r.json"))
    return out


def test_the_report_half_cannot_return_one_for_any_json_destination(tmp_path):
    """#969's instance, over every un-writable destination this host affords.

    On origin/main the first of these raised an uncaught FileNotFoundError and
    python exited 1 — the code `run_tolerating_uncheckable` does NOT tolerate.
    """
    seen = 0
    for label, target in _unwritable_json_targets(tmp_path):
        cp = _report(["--json", str(target)])
        seen += 1
        assert cp.returncode in (0, 2), (label, cp.returncode,
                                         cp.stdout + cp.stderr)
        assert _the_report_actually_ran(cp), (label, cp.stdout, cp.stderr)
        assert "Traceback" not in cp.stderr, (label, cp.stderr)
    # This file's own denominator: a loop over an empty list asserts nothing.
    assert seen >= 3, f"only {seen} un-writable destination(s) constructed"


def test_an_unwritable_json_destination_does_not_DOWNGRADE_the_reading(
        tmp_path):
    """NOT RETURNING 1 IS NOT ENOUGH — the reading must be UNCHANGED.

    FOUND BY THE MUTANT ARM, and it is the reason that arm is not a formality.
    With the write guard neutered (`except OSError: raise`) and only the
    dispatch clamp in `main` left standing, every assertion above still passed:
    the exception escaped, the clamp turned it into rc 2, and rc 2 is inside
    `(0, 2)`. The invariant held and the ANSWER was destroyed — a run that had
    already resolved the registry and printed the comparison in full came out
    saying `[NOT CHECKED] … NOTHING was compared`, which is false.

    So the property is stated as an EQUALITY against the same run with no
    `--json` at all: whether a copy of the record could be persisted is not
    allowed to be an input to what the reading says. `--json` is documented as
    "ALSO write the dated reading", and `also` is the whole claim.

    THE OBSERVATION INSTANT IS NORMALISED OUT, and it has to be: the verdict
    line carries `observed_at`, two subprocesses are two instants, and the
    first version of this test compared them raw and failed on a one-second
    tick between the baseline and the third destination. A flaky control is
    worse than none — it retrains a reader to re-run until green.
    """
    baseline = _report([])
    assert baseline.returncode == 0, baseline.stdout + baseline.stderr

    _INSTANT = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z")

    def _verdict(cp):
        return [_INSTANT.sub("<observed_at>", ln)
                for ln in cp.stdout.splitlines()
                if ln.startswith(("[REPORT]", "[NOT CHECKED]", "[FAIL]"))]

    seen = 0
    for label, target in _unwritable_json_targets(tmp_path):
        cp = _report(["--json", str(target)])
        seen += 1
        assert cp.returncode == baseline.returncode, (
            label, "an unwritable --json path changed the exit code",
            cp.returncode, baseline.returncode, cp.stdout + cp.stderr)
        assert _verdict(cp) == _verdict(baseline), (
            label, "an unwritable --json path changed the READING",
            _verdict(cp), _verdict(baseline))
    assert seen >= 3, f"only {seen} un-writable destination(s) constructed"


def test_a_writable_json_destination_is_still_written(tmp_path):
    """PAIRED GUARD. The cheapest way to stop a write from failing is to stop
    writing. `--json` is the flag #927 advertises for the reporting half, so it
    must still produce the file when the path IS usable — including a parent
    that does not exist yet, which is the ordinary "point it at a reports dir"
    case and is repaired rather than merely tolerated."""
    import json as _json
    target = tmp_path / "fresh" / "sub" / "r.json"
    cp = _report(["--json", str(target)])
    assert cp.returncode == 0, cp.stdout + cp.stderr
    assert target.is_file(), cp.stdout
    rec = _json.loads(target.read_text())
    assert rec["blocking"] is False, rec
    assert re.match(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$",
                    rec["observed_at"]), rec


def test_the_report_half_cannot_return_one_when_something_UNANTICIPATED_raises():
    """THE INVARIANT, not the instance.

    Guarding the one write that was found fixes the one input that was tried.
    This drives an exception from a place nobody guarded — the registry
    accessor itself — and requires the dispatch to answer rc 2 NOT CHECKED
    rather than letting python turn it into 1.

    The exception is injected into the MODULE's own accessor rather than into
    `socket`, because a network-shaped failure is already handled; what is being
    pinned is the behaviour for a failure shape nobody predicted.
    """
    code = (
        "import importlib.util, sys\n"
        f"spec = importlib.util.spec_from_file_location('siv', {str(_PROG)!r})\n"
        "m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)\n"
        "def _boom(*a, **k):\n"
        "    raise RuntimeError('an unanticipated failure inside the report')\n"
        "m.check_anchor_vs_reality = _boom\n"
        "sys.exit(m.main(['--report-upstream', '--require-remote']))\n"
    )
    cp = subprocess.run([sys.executable, "-c", code], cwd=str(_REPO),
                        capture_output=True, text=True, env=_env())
    blob = cp.stdout + cp.stderr
    assert cp.returncode == 2, (cp.returncode, blob)
    assert "NOT CHECKED" in cp.stdout, blob
    assert "[PASS]" not in cp.stdout, blob          # never bought as a pass


def test_the_vacuous_guard_would_have_passed_a_program_without_the_feature(
        tmp_path):
    """THE DECISIVENESS PROOF, kept as a test rather than as a claim.

    A stand-in program with NO `--report-upstream` at all is driven with the
    exact invocation the old guard used. The old predicate (`rc in (0, 2)`)
    accepts it; the new one refuses it. That is the whole difference between a
    guard for an invariant and a guard for argparse, and freezing it here means
    the predicate cannot be loosened back without going red.
    """
    stub = tmp_path / "no_such_feature.py"
    stub.write_text(
        "#!/usr/bin/env python3\n"
        "import argparse, sys\n"
        "ap = argparse.ArgumentParser()\n"
        "ap.add_argument('--check', action='store_true')\n"
        "ap.parse_args()\n"
        "sys.exit(0)\n")
    cp = subprocess.run(
        [sys.executable, str(stub), "--report-upstream", "--require-remote"],
        cwd=str(tmp_path), capture_output=True, text=True, env=_env())

    assert cp.returncode == 2, cp.stderr           # argparse, not a degrade
    assert cp.returncode in (0, 2), cp.stderr      # THE OLD GUARD: passes
    assert not _the_report_actually_ran(cp), (     # THE NEW GUARD: refuses
        "the discriminator accepted a program that has no --report-upstream; "
        "it is testing argparse, not the invariant", cp.stdout, cp.stderr)


# ── #970: the denominator must say what it did not count ─────────────────────

def _pinned_line(version: str) -> str:
    return f"    docker pull {_GHCR}:{version}\n"


def _floating_line(tag: str) -> str:
    return f"    docker pull {_GHCR}:{tag}\n"


def _two_registered_docs(m):
    """Two entries DISCOVERED from the program's own registry, never typed.

    A hard-coded pair would keep passing after somebody reorders or renames the
    candidates, testing a path that no longer exists — the same "a typed list
    is a promise nobody will add a case" failure this file is about.
    """
    docs = [c for c in m.INSTALL_DOC_CANDIDATES if c.lower().endswith(".md")]
    assert len(docs) >= 2, m.INSTALL_DOC_CANDIDATES
    return docs[0], docs[1]


def _fixture_repo(tmp_path, anchor="1.0.0", floating_tag=None,
                  second_doc_version=None):
    """A self-contained repo the tool runs in unmodified.

    The tool prefers `script_dir/VERSION`, so the SCRIPT is copied in beside a
    fixture VERSION — its documented "runs from either repo" mode. Two
    REGISTERED install docs are created: the first always carries a correct
    pinned pointer, the second carries either a floating tag (the #970
    condition) or a pin at `second_doc_version`.
    """
    m = _load_prog("siv970_fixture")
    first, second = _two_registered_docs(m)
    root = tmp_path / "fixture"
    (root / "tools" / "vibeic-eda").mkdir(parents=True)
    shutil.copy2(_PROG, root / "tools" / "vibeic-eda" / "sync_image_version.py")
    (root / "tools" / "vibeic-eda" / "VERSION").write_text(anchor + "\n")

    p1 = root / first
    p1.parent.mkdir(parents=True, exist_ok=True)
    p1.write_text("# fixture install doc\n\n" + _pinned_line(anchor))

    p2 = root / second
    p2.parent.mkdir(parents=True, exist_ok=True)
    if floating_tag is not None:
        p2.write_text("# fixture install doc\n\n" + _floating_line(floating_tag)
                      + _floating_line(floating_tag))
    else:
        p2.write_text("# fixture install doc\n\n"
                      + _pinned_line(second_doc_version or anchor))

    for cmd in (["git", "init", "-q"],
                ["git", "config", "user.email", "t@example.invalid"],
                ["git", "config", "user.name", "t"],
                ["git", "add", "-A"],
                ["git", "commit", "-qm", "fixture"]):
        subprocess.run(cmd, cwd=str(root), check=True, capture_output=True,
                       text=True)
    return root, first, second


def _check_severed(root):
    """`--check` with name resolution broken inside the child.

    Severed rather than merely offline: the blocking half's defining property
    is that it makes NO registry call, and a fixture that only happens not to
    need one would not notice a call being re-added.
    """
    prog = root / "tools" / "vibeic-eda" / "sync_image_version.py"
    code = (
        "import sys, socket, runpy\n"
        "def _boom(*a, **k):\n"
        "    raise TimeoutError('simulated severed registry')\n"
        "socket.getaddrinfo = _boom\n"
        "socket.create_connection = _boom\n"
        "sys.argv = ['sync_image_version.py', '--check']\n"
        f"runpy.run_path({str(prog)!r}, run_name='__main__')\n"
    )
    return subprocess.run([sys.executable, "-c", code], cwd=str(root),
                          capture_output=True, text=True, env=_env())


_UNCOUNTED_RE = re.compile(
    r"registered but UNCOUNTED\s*:\s*(\d+) present-with-no-pinned-ref")


def _uncounted_count(stdout):
    m = _UNCOUNTED_RE.search(stdout)
    assert m, ("the check printed no UNCOUNTED reconciliation line at all — "
               "the denominator does not state what it dropped", stdout)
    return int(m.group(1))


def test_a_registered_doc_whose_pointers_are_all_floating_is_DISCLOSED(
        tmp_path):
    """#970. The file is registered, exists, and carries only floating tags, so
    it contributes NOTHING to the count. The count must say so — by name, and
    in the verdict sentence, not only in a block above it."""
    root, first, second = _fixture_repo(tmp_path, anchor="1.0.0",
                                        floating_tag="latest")
    cp = _check_severed(root)
    out = cp.stdout

    assert cp.returncode == 0, out + cp.stderr          # DISCLOSE, not block
    assert _uncounted_count(out) == 1, out
    assert second in out, out                           # named, not just counted
    assert ":latest" in out, out                        # and WHAT it carries
    pass_line = [ln for ln in out.splitlines() if ln.startswith("[PASS]")]
    assert pass_line, out
    assert "NOT counted" in pass_line[0], (
        "the verdict sentence still reads as complete coverage", pass_line[0])
    # The numerator's file set and the declared population are BOTH printed.
    assert re.search(r"across 1 of \d+ registered file\(s\)", out), out


def test_the_uncounted_file_is_found_by_the_SHAPE_of_its_tag(tmp_path):
    """DISCOVER, DO NOT ENUMERATE, applied to the disclosure itself.

    `latest` is not special — it is merely the floating tag published today.
    A rule spelled against that one name is silently incomplete the first time
    somebody writes `:edge`, which is the failure mode `is_mutable_tag` was
    written as a predicate to avoid. The disclosure must reuse it.
    """
    for tag in ("edge", "nightly", "main"):
        root, _first, second = _fixture_repo(tmp_path / tag, anchor="1.0.0",
                                             floating_tag=tag)
        cp = _check_severed(root)
        assert cp.returncode == 0, cp.stdout + cp.stderr
        assert _uncounted_count(cp.stdout) == 1, (tag, cp.stdout)
        assert second in cp.stdout, (tag, cp.stdout)
        assert f":{tag}" in cp.stdout, (tag, cp.stdout)


def test_the_disclosure_counts_POINTERS_not_distinct_tag_names(tmp_path):
    """Two `:latest` pull lines are two pointers a reader can follow. A reader
    deciding whether to pin them needs to know there are two."""
    root, _first, _second = _fixture_repo(tmp_path, anchor="1.0.0",
                                          floating_tag="latest")
    cp = _check_severed(root)
    assert "2 floating pointer(s)" in cp.stdout, cp.stdout


def test_the_reconciliation_ARITHMETIC_closes(tmp_path):
    """counted + uncounted + absent == the declared population, printed.

    The paired guard above is written against absence so it holds in both arms;
    this is the positive statement it cannot make. `gate_discloses_denominator_
    check` prints `probed of declared` and names what it could not drive, for
    exactly this reason: a reader must be able to add the published numbers up
    and get the population back, or the summary is a claim rather than a count.
    """
    m = _load_prog("siv970_arith")
    declared = len(m.INSTALL_DOC_CANDIDATES)
    root, _first, _second = _fixture_repo(tmp_path, anchor="1.0.0",
                                          floating_tag="latest")
    out = _check_severed(root).stdout

    hit = re.search(r"across (\d+) of (\d+) registered file\(s\)", out)
    assert hit, ("the count does not publish the declared population", out)
    counted, published_declared = int(hit.group(1)), int(hit.group(2))
    assert published_declared == declared, (published_declared, declared, out)

    absent = re.search(r"(\d+) not-present-in-this-repo", out)
    assert absent, out
    assert counted + _uncounted_count(out) + int(absent.group(1)) == declared, (
        counted, _uncounted_count(out), absent.group(1), declared, out)


def test_the_reconciliation_reads_ZERO_when_every_registered_doc_is_pinned(
        tmp_path):
    """The other direction of the same line. Without this the disclosure could
    be a constant that always names something, which is an alarm, not a count.
    """
    root, _first, _second = _fixture_repo(tmp_path, anchor="1.0.0")
    out = _check_severed(root).stdout
    assert _uncounted_count(out) == 0, out
    assert re.search(r"across 2 of \d+ registered file\(s\)", out), out


def test_the_disclosure_itself_makes_no_registry_call():
    """The structural half of #927's property, over the code this change adds.

    The behavioural guard above could in principle be satisfied by a program
    that calls the registry and ignores the answer. These functions are the new
    ones, and none of them may reach out.
    """
    src = _PROG.read_text(encoding="utf-8")
    for fn in ("def do_check", "def install_doc_coverage",
               "def print_install_doc_coverage"):
        assert fn in src, (fn, "not present in the program under test")
        body = src.split(fn, 1)[1].split("\ndef ", 1)[0]
        assert "_query_ghcr" not in body, (fn, "reaches the registry")
        assert "published_tags" not in body, (fn, "reaches the registry")


# ── PAIRED GUARDS: what must NOT change ──────────────────────────────────────

#
# THE FOUR BELOW ARE ARM-INVARIANT BY CONSTRUCTION, and that is the point of
# them. Each was measured to PASS against origin/main's program as well as
# against the fixed one, so none of them can be the reason the fix looks good.
# They exist to make the fix unbuyable: it must not be paid for by making a
# correctly-pinned doc noisy, by softening real drift, or by re-introducing the
# registry call #927 removed. A test that changes with the fix cannot say any
# of that — which is why the assertions that DO need the new output live in
# their own tests further down.
#

def test_a_doc_with_a_correct_PINNED_pointer_stays_silent(tmp_path):
    """PAIRED GUARD. A gate that only ever says no is a ban, not a check.

    Both registered docs carry correct pins here, so nothing may be reported
    about either of them and the verdict sentence must not acquire a caveat.
    Written against ABSENCE — the file is not named, the verdict is unqualified
    — so it holds identically before and after, and fires only if the
    disclosure over-fires.
    """
    root, _first, second = _fixture_repo(tmp_path, anchor="1.0.0")
    cp = _check_severed(root)
    out = cp.stdout
    assert cp.returncode == 0, out + cp.stderr
    assert second not in out, (
        "a correctly pinned registered doc was reported as uncounted", out)
    pass_line = [ln for ln in out.splitlines() if ln.startswith("[PASS]")]
    assert pass_line, out
    assert "NOT counted" not in pass_line[0], pass_line[0]
    assert "970" not in pass_line[0], pass_line[0]


def test_a_drifted_pinned_pointer_still_FAILS(tmp_path):
    """PAIRED GUARD. The gate's primary job, unchanged by the disclosure.
    Adding a line that explains what was NOT counted must not soften what IS."""
    root, _first, second = _fixture_repo(tmp_path, anchor="1.0.0",
                                         second_doc_version="0.9.0")
    cp = _check_severed(root)
    assert cp.returncode == 1, cp.stdout + cp.stderr
    assert "live pointer(s) != 1.0.0" in cp.stdout, cp.stdout
    assert second in cp.stdout, cp.stdout


def test_the_blocking_half_still_makes_NO_registry_call(tmp_path):
    """PAIRED GUARD — #927's defining property, over a tree that contains the
    #970 condition.

    The disclosure reads FILES and reuses `is_mutable_tag`; neither may
    introduce a round-trip. With name resolution severed, a program that
    reached out would surface the TimeoutError somewhere in its output.
    """
    root, _first, _second = _fixture_repo(tmp_path, anchor="1.0.0",
                                          floating_tag="latest")
    cp = _check_severed(root)
    blob = cp.stdout + cp.stderr
    assert "TimeoutError" not in blob, blob
    assert "unreachable" not in blob.lower(), blob
    assert cp.returncode == 0, blob


def test_the_real_repo_still_passes_its_own_check():
    """A check that cannot return clean is an alarm. The tree this lands on
    must still be green, disclosure and all."""
    cp = subprocess.run([sys.executable, str(_PROG), "--check"],
                        cwd=str(_REPO), capture_output=True, text=True,
                        env=_env())
    assert cp.returncode == 0, cp.stdout + cp.stderr
    assert "[PASS]" in cp.stdout, cp.stdout


def test_the_denominator_of_this_file_is_real():
    """If _REPO is off by one every assertion above passes vacuously."""
    assert _PROG.is_file(), _PROG
    assert (_REPO / "tools" / "vibeic-eda" / "VERSION").is_file()
    m = _load_prog("siv969_denominator")
    assert len(m.INSTALL_DOC_CANDIDATES) >= 2, m.INSTALL_DOC_CANDIDATES
