"""A test that plants a probe in the shipped tree races every test that reads it.

THE DEFECT (8HD-8 stacked census, 2026-09-28). `test_issue559`'s growth-hole
test wrote `programs/brand_new_hand_rolled_check.py`, measured, and unlinked it
in a `finally`. Under xdist, `test_upstream_mirror_is_pinned::
test_the_shipped_tree_is_clean` listed programs/*.py while the probe existed and
read it after the unlink: `FileNotFoundError`, a red on a test that is correct.
Lane rfrace fixed twelve writers of this shape on 2026-09-27; this one was
missed because its write sat inside a helper whose parameter is named
`tmp_path`, and the caller passed the SHIPPED programs dir as that argument.

WHY A NEW TEST IS NEEDED AT ALL. `suite_write_guard` compares `git status`
snapshots and states its own bound: "a write made AND reverted inside a single
test is invisible to a snapshot taken after it". A probe writer that cleans up
is exactly that write, so the guard printed `[PASS] ... wrote nothing` over
every one of these on origin/main. The race is the only symptom, and a race
is a symptom nobody reproduces on demand.

WHAT THIS DOES. It re-runs each former writer in a child pytest under
`_tree_write_audit`, which records the WRITE itself (an audit hook in every
Python process of the child), and requires both that the node PASSED -- a node
that did not run proves nothing about what it writes -- and that it wrote
nothing under the checkout. Moving any of them back into the shipped tree is
then a named red here instead of an intermittent one somewhere else.

Each entry names what the node wrote on origin/main 76a277544, measured with
the same hook.
"""
from __future__ import annotations

import sys
import textwrap
from pathlib import Path


_TESTS = Path(__file__).resolve().parent
_PLUGIN = _TESTS.parents[1]
#: The checkout the plugin sits in (the monorepo root), or the plugin itself
#: where there is no enclosing checkout (the installed cache).
_ROOT = next((p for p in _PLUGIN.parents if (p / ".git").exists()), _PLUGIN)
if str(_TESTS) not in sys.path:
    sys.path.insert(0, str(_TESTS))
import _progress_run as _pr  # noqa: E402
import _tree_write_audit as TWA  # noqa: E402

_T = "programs/tests/"
FORMER_WRITERS = {
    _T + "test_progress_run.py"
         "::test_the_outer_window_is_RESOLVED_from_its_owner_not_copied_here":
        "REWROTE the tracked programs/pytest_per_file_junit.py in place "
        "(DEFAULT_STALL_AFTER 300 -> 999) and wrote it back",
}
#: NOT watched here, and why. `test_issue1129_gatekeeper_prepare_landing.py::
#: test_the_real_program_runs_against_this_repo_and_honours_its_boundary` ran
#: the real landing preparation on the SHARED checkout (version bump across
#: plugin.json, both marketplace manifests and the READMEs; INDEX.md; then
#: `git checkout --`). It now runs from a private `--shared` clone and asserts
#: that the program it ran lives there. It costs ~460 s (the census writer) and
#: skips on any dirty tree, so re-running it in this child would double that
#: cost and read as "did not PASS" whenever the suite runs on local edits.


#: The child session's OWN autouse cleanup, by identity (file, function). Each
#: deletes a stray waveform dump (.vcd/.fst/...) from the plugin root or
#: programs/ after every test -- including one a CONCURRENT parent worker
#: leaked while the child ran, which the audit would otherwise charge to the
#: watched node (review of PR fxprobe, 2026-09-28). A write made inside one of
#: these is the harness's, not the node's; the same write made by the node's
#: own code is still the node's (see the exemption calibration below).
CLEANUP_FIXTURES = (
    (_PLUGIN / "conftest.py", "_strip_stray_waveform_artifacts"),
    (_TESTS / "conftest.py", "_clean_stray_waveform_dumps"),
)


def test_the_exempt_cleanup_fixtures_exist_by_the_identity_declared():
    """An exemption naming a function that no longer exists would exempt
    nothing and say nothing; it must be anchored to the real definition."""
    import ast
    for path, name in CLEANUP_FIXTURES:
        tree = ast.parse(Path(path).read_text())
        defs = {n.name for n in ast.walk(tree)
                if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}
        assert name in defs, f"{path} no longer defines {name}"


def test_an_exempt_function_is_exempt_and_a_node_write_is_still_caught(
        tmp_path):
    """Exemption is by IDENTITY, not by path or suffix: the same removal of
    the same kind of file is exempt inside the declared function and is the
    node's own write outside it."""
    root = tmp_path / "tree"
    root.mkdir()
    child = tmp_path / "child.py"
    child.write_text(textwrap.dedent("""
        import os, sys
        from pathlib import Path
        root = Path(sys.argv[1])
        def cleanup_fixture(p):
            p.unlink()
        def node_body(p):
            os.remove(p)
        for name in ("leaked_by_a_peer.vcd", "planted_by_the_node.vcd"):
            (root / name).write_text("x")
        cleanup_fixture(root / "leaked_by_a_peer.vcd")
        node_body(root / "planted_by_the_node.vcd")
    """))
    work = tmp_path / "work"
    work.mkdir()
    env = TWA.audit_env(root, work, exempt=((child, "cleanup_fixture"),))
    env["PYTEST_CURRENT_TEST"] = "pkg/test_x.py::test_node (teardown)"
    r = _pr.run([sys.executable, str(child), str(root)], cwd=str(root),
                env=env, capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    events = TWA.read_events(work)
    removed = {e["path"]: e.get("exempt") for e in events
               if e["event"] == "os.remove"}
    assert removed == {"leaked_by_a_peer.vcd": "cleanup_fixture",
                       "planted_by_the_node.vcd": None}, events
    audit = TWA.Audit(rc=0, output="", events=events)
    charged = {(e["event"], e["path"]) for e in
               audit.writes_by("pkg/test_x.py::test_node")}
    assert ("os.remove", "planted_by_the_node.vcd") in charged, charged
    assert ("os.remove", "leaked_by_a_peer.vcd") not in charged, charged


def test_the_audit_sees_a_write_and_only_a_write(tmp_path):
    """Calibration. The instrument must record a planted-and-removed file,
    and must NOT record the three things that fooled its first version: a tmp
    symlink farm pointing INTO the tree being deleted (that deletes links, not
    the tree), `shutil.rmtree` of a tmp dir run from a cwd inside the tree (it
    removes entries by bare name relative to a directory fd), an anonymous
    `O_TMPFILE` opened on the tree's directory (it creates no entry), and a
    bare-name `os.open` relative to a directory fd outside the tree (the
    event does not carry the fd), and `mkdir(exist_ok=True)` on a directory
    that is already there. A bare-name builtin `open()` IS a write to the cwd,
    and a NEW directory is a write, and both must still be seen."""
    root = tmp_path / "tree"
    (root / "programs").mkdir(parents=True)
    (root / "programs" / "real.py").write_text("x\n")
    farm = tmp_path / "farm"
    farm.mkdir()
    (farm / "real.py").symlink_to(root / "programs" / "real.py")
    child = tmp_path / "child.py"
    child.write_text(textwrap.dedent("""
        import shutil, sys
        from pathlib import Path
        root, farm, scratch = map(Path, sys.argv[1:4])
        probe = root / "programs" / "probe.py"
        probe.write_text("planted\\n")
        probe.unlink()
        shutil.rmtree(farm)
        (scratch / "d" / "e").mkdir(parents=True)
        (scratch / "d" / "e" / "f").write_text("x")
        shutil.rmtree(scratch / "d")
        import os
        if hasattr(os, "O_TMPFILE"):
            os.close(os.open(str(root / "programs"),
                             os.O_TMPFILE | os.O_RDWR, 0o600))
        fd = os.open(str(scratch), os.O_RDONLY)
        os.close(os.open("fd_relative.tmp", os.O_CREAT | os.O_WRONLY, 0o600,
                         dir_fd=fd))
        os.close(fd)
        with open("cwd_relative.txt", "w") as fh:
            fh.write("x")
        os.remove("cwd_relative.txt")
        (root / "programs").mkdir(exist_ok=True)
        (root / "programs" / "new_dir").mkdir()
        (root / "programs" / "new_dir").rmdir()
        # CWD-RELATIVE os-level writes, one per operation. With no dir_fd
        # CPython reports dir_fd=-1 in the audit event, which means "the cwd".
        os.mkdir("programs/rel_dir")
        with open("programs/rel_dir/f.txt", "w") as fh:
            fh.write("x")
        os.chmod("programs/rel_dir/f.txt", 0o644)
        os.utime("programs/rel_dir/f.txt")
        os.chown("programs/rel_dir/f.txt", os.getuid(), os.getgid())
        os.symlink("f.txt", "programs/rel_dir/s")
        os.link("programs/rel_dir/f.txt", "programs/rel_dir/h")
        os.rename("programs/rel_dir/f.txt", "programs/rel_dir/g.txt")
        os.replace("programs/rel_dir/g.txt", "programs/rel_dir/f.txt")
        os.remove("programs/rel_dir/s")
        Path("programs/rel_dir/h").unlink()
        os.remove("programs/rel_dir/f.txt")
        Path("programs/rel_dir/t").touch()
        os.remove("programs/rel_dir/t")
        os.rmdir("programs/rel_dir")
    """))
    work = tmp_path / "work"
    work.mkdir()
    r = _pr.run(
        [sys.executable, str(child), str(root), str(farm),
         str(tmp_path / "scratch")],
        cwd=str(root), env=TWA.audit_env(root, work),
        capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    events = TWA.read_events(work)
    seen = {(e["event"], e["path"]) for e in events}
    assert ("open", "programs/probe.py") in seen, events
    assert ("os.remove", "programs/probe.py") in seen, events
    assert ("open", "cwd_relative.txt") in seen, events
    assert ("os.mkdir", "programs/new_dir") in seen, events
    # One per operation; the builtin `open` of the same path must not be what
    # satisfies the remove (it once was: `os.remove("cwd_relative.txt")` went
    # unrecorded while the set equality below still held).
    rel = "programs/rel_dir"
    for want in (("os.remove", "cwd_relative.txt"),
                 ("os.mkdir", rel),
                 ("os.chmod", f"{rel}/f.txt"),
                 ("os.utime", f"{rel}/f.txt"),
                 ("os.chown", f"{rel}/f.txt"),
                 ("os.symlink", f"{rel}/s"),
                 ("os.link", f"{rel}/h"),
                 ("os.rename", f"{rel}/f.txt"),       # rename source
                 ("os.rename", f"{rel}/g.txt"),       # rename target / replace
                 ("os.remove", f"{rel}/s"),
                 ("os.remove", f"{rel}/h"),
                 ("os.remove", f"{rel}/f.txt"),
                 ("open", f"{rel}/t"),                # Path.touch: os.open, relative
                 ("os.rmdir", rel)):
        assert want in seen, (
            f"a cwd-relative {want[0]} of {want[1]} was not recorded: "
            f"{sorted(seen)}")
    assert {e["path"] for e in events} - {
        f"{rel}", f"{rel}/f.txt", f"{rel}/g.txt", f"{rel}/s", f"{rel}/h",
        f"{rel}/t"} == {"programs/probe.py",
                                          "cwd_relative.txt",
                                          "programs/new_dir"}, (
        "the audit reported a write the child never made under the tree: "
        f"{sorted(seen)}")
    assert (root / "programs" / "real.py").read_text() == "x\n"


def test_no_former_writer_plants_anything_in_the_shipped_tree():
    """ONE child session for every former writer, and ONE test, on purpose: a
    module-scoped fixture is instantiated once per xdist WORKER, so spreading
    per-node cases across workers re-ran the whole child session for each.

    Two failure classes, both named per node. A node that did not PASS proves
    nothing about what it writes (renamed, deleted, or red for another
    reason). A node that wrote under the checkout is the defect. An import-time
    write carries no test id, so collection-time events are reported on their
    own: both corpus modules wrote while they were being COLLECTED."""
    audit = TWA.run_nodes(sorted(FORMER_WRITERS), plugin_root=_PLUGIN,
                          root=_ROOT, exempt=CLEANUP_FIXTURES)
    assert audit.outcomes, (
        f"the audited child reported no test at all (rc={audit.rc}); an "
        f"empty session proves nothing:\n{audit.output[-3000:]}")
    problems = []
    for nodeid in sorted(FORMER_WRITERS):
        got = audit.outcomes.get(nodeid)
        if got != "passed":
            problems.append(
                f"{nodeid} did not PASS under the audit ({got or 'not run'})")
        wrote = sorted({f"{e['event']} {e['path']}"
                        for e in audit.writes_by(nodeid)})
        if wrote:
            problems.append(
                f"{nodeid} wrote into the checkout it tests: "
                f"{'; '.join(wrote)} (on origin/main 76a277544 it "
                f"{FORMER_WRITERS[nodeid]})")
    collected = sorted({f"{e['event']} {e['path']}"
                        for e in audit.writes_by("")})
    if collected:
        problems.append("collecting the former writers wrote into the "
                        "checkout: " + "; ".join(collected))
    assert not problems, (
        "every concurrent worker listing these paths races the writer:\n  "
        + "\n  ".join(problems)
        + (f"\nchild rc={audit.rc}\n{audit.output[-3000:]}"
           if any("did not PASS" in p for p in problems) else ""))
