#!/usr/bin/env python3
"""targeted_arm_cache.py — content-addressed reuse for the LANDING gate's
targeted pytest arm, keyed on EVERYTHING that can change its verdict.

WHY THIS EXISTS, AND WHY IT IS DELIBERATELY NARROW
==================================================
`tools/gatekeeper-land.sh` re-runs the targeted arm from scratch on every
invocation: `.git/gatekeeper-stamp` is written and never read for reuse,
`-p no:cacheprovider` disables pytest's own incremental substrate, and the
merged JUnit goes to a `mktemp` that is `rm -f`'d. So a round that is asked the
same question twice pays twice.

The obvious ambition — a PER-FILE cache that skips the files a diff cannot have
touched — was designed, then MEASURED and REFUSED. Two numbers killed it, both
taken on this tree (origin/main 116bcb5a8) against the real 279-file selection
for the real landing `HEAD~1..HEAD`:

  * 265 of the 279 selected files (95.0%) have a transitive Python import
    closure that contains at least one construct whose read set cannot be
    enumerated statically — `subprocess` (234 files), `importlib` (184),
    `rglob` (165), `os.walk` (134), `iterdir` (121), `__import__` (113),
    `socket` (111), `requests` (107), `scandir` (99), `Popen` (77),
    `check_output`/`check_call` (7 each), `glob.glob` (6), `listdir` (2),
    `os.system` (1). A per-file key built from the import closure would
    therefore be MISSING inputs for 95% of the arm, and a key that misses an
    input serves a FALSE GREEN.
  * The only sound way to enumerate those read sets is to observe them, and the
    observation has to be paid on every MISS — i.e. on every landing that
    changes anything. Measured with `strace -f`, two files, same host:
        test_agent_checkin_scope_guard.py    1.16 s -> 8.67 s (openat+getdents64)
                                                   -> 11.92 s (%file+getdents64)
        test_pnr_tool_fatal_signal_...py     5.24-5.51 s -> 9.83 s (openat+getdents64)
    1.8x on the syscall-sparse file, 7.5x-10.3x on the syscall-dense one. Even
    at the low end that is a doubling of the arm to buy back, at most, the
    population measured in the next paragraph.

There is a third reason, and it is the decisive one. The arm's selection is
ALREADY change-driven: `ci_targeted_test_select.py` maps the diff to the tests
that can see it, so within one landing "the selected set" IS "the set that can
have changed". What is left over is the curated SMOKE floor, which is included
unconditionally — and the smoke floor's own documented purpose is to cover the
selector's blind spots ("the PR that breaks a global invariant is exactly the PR
whose changed-file set cannot reach the test that guards it"). A cache that
served the smoke floor from a previous tree, keyed on the selector, would go
blind exactly where the selector goes blind. That is not a cache, it is a hole.

MEASURED over the last 20 first-parent landings on origin/main: the selection is
18-279 files (mean 92.7, 1854 in total); the floor is 17 files in every one of
the 20; and the ONLY files selected in all 20 are exactly those 17. So the floor
is the entire cross-landing reuse opportunity — 18.3% of selected FILES, but
only 30.0 s of the 1927.5 s of case time the 279-file arm spends, i.e. 1.56%.
Buying 1.56% by going blind where the selector is blind is not a trade worth
making, and buying it at 1.8x-10x tracing overhead is not a speedup at all.

So this program caches ONE thing, the only thing that is safe without a read-set
model: an EXACT REPEAT. If the whole subject tree, the whole environment, the
instrument and the selection are byte-identical to a recorded GREEN measurement
taken on THIS host since THIS boot, the recorded measurement is replayed.
Anything else is a MISS, and a MISS re-runs.

WHAT IS IN THE KEY
==================
Everything below is hashed. A missing or unreadable input is a REFUSAL (no key
is emitted at all), never a silently-absent field:

  SUBJECT
    every TRACKED path: mode, symlink target, and sha256 of the WORKTREE bytes
      (not the index blob — the index can be stale, and `assume-unchanged` can
      make it lie)
    every UNTRACKED, non-ignored path: same
    every IGNORED path that is not in the declared regenerable set
      (`__pycache__/`, `*.pyc`, `.pytest_cache/`): same. Ignored-but-read files
      are a real input; only the regenerable set is exempt, and that exemption
      is a named list, not a wildcard.
  INSTRUMENT
    the exact pytest argv and the exact driver argv, verbatim
    sha256 of: the harness `tools/gatekeeper-land.sh`, the driver
      `pytest_per_file_junit.py`, the selector `ci_targeted_test_select.py`,
      `_watchdog.py`, `_pytest_progress_plugin.py`, `suite_write_guard.py`,
      `scratch_root_guard.py`, EVERY `conftest.py` in the plugin tree,
      `pytest.ini`, `.claude-plugin/plugin.json`, and this program itself
    the selection file: sha256 and the sorted path list
  RUNTIME
    `sys.version`, realpath of the interpreter and sha256 of that binary,
    `platform.machine`/`system`/`release`
    every installed distribution: (name, version) and sha256 of its `RECORD`
      (which carries a per-file hash of everything the installer wrote)
    full content hash of the packages this arm actually loads: `pytest`,
      `_pytest`, `pluggy`, `pytest_timeout`, `iniconfig`, `packaging`
    the WHOLE environment (`os.environ`, sorted), umask, uid, gid
  HOST
    `uname -n`, `/etc/machine-id`, `/proc/sys/kernel/random/boot_id`
      — because gate verdicts on this tree are measurably host-dependent
      (`gate_host_independence_check` is itself one of the gates), so a record
      from another host, or from this host before a reboot, is not evidence
      about this one.
  SCHEMA
    this program's schema version and its own sha256

WHAT IS NOT IN THE KEY, STATED SO NOBODY HAS TO GUESS
=====================================================
  * post-install hand edits to files under site-packages that the RECORD hash
    and the six pinned package trees do not cover;
  * anything outside the repo and outside the environment: the wall clock, the
    network, files under /tmp, the state of any daemon;
  * the host's non-Python toolchain (git, bash, klayout, container images) —
    `boot_id` and `machine-id` bound reuse to one host since one boot, which
    makes a toolchain swap require a reboot to go unnoticed, but does not
    exclude it.
  Each of those is a reason a hit could be wrong. That is why a hit is only ever
  granted for a GREEN record: a stale green can only ever be replaced by a
  re-run, and the cache can never turn a red into a pass, nor hand a candidate
  a failure exemption.

MEASURED WORTH — READ THIS BEFORE TURNING IT ON
===============================================
On the LANDING path across the last 20 first-parent landings the hit rate is
ZERO, and not by accident: all 21 commit trees in that window are distinct, so
an exact repeat never occurs between landings. What it does buy:

  * an exact repeat of the same round on the same host — measured on the real
    17-file smoke selection, 35.33 s cold -> 0.99 s / 1.01 s warm, with a
    BYTE-IDENTICAL normalised verdict (sorted {classname::name -> outcome},
    driver process records excluded): 5433999c… both times;
  * the same shape at the 279-file arm's scale: the whole warm path costs
    0.476-0.497 s (key 0.46-0.48 s over 4685 tracked files, JUnit validation
    0.016 s over 6108 records, copy 0.002 s) against a 1751 s cold arm.

THE ARM IS NOT IDEMPOTENT ON ITS OWN SUBJECT, and that is a HARD blocker for any
exact-repeat scheme at scale. MEASURED, three consecutive identical rounds over
the same 100-file selection on the same tree: every round's PRE-run key equalled
the previous round's POST-run key, and every round produced a NEW post-run key
(b4796abf -> eb2405a0 -> 3399d4a1), so not one of them could hit its own
predecessor. The cause is named: `programs/tests/test_gds_geometry_signoff_wiring.py`
writes seven `vibe-ic-marketplace/scratch_geom_signoff_tests/*/phase3/stage4/gds/
top.gds` files INTO the repo, and their bytes differ on every run. They are
git-IGNORED, so `git status --porcelain` does not list them, so the in-session
write guard reports "this pytest session wrote nothing" and the closing
`worktree unchanged since the gates started` gate passes. Isolated: running that
one file alone changes exactly those seven files and nothing else. Until it
writes under the scratch root instead of the repo, this cache converges only for
selections that exclude it — which the 17-file smoke floor does, and which is
why the floor measurements above hit on the second round.

And on THIS tree it cannot populate at all at full width: the 279-file arm ends
AGGREGATE_NORECORD rc=199 with 1 file NORECORD and 9 red cases, so the
green-only rule stores nothing. Repairing the aggregate progress protocol is a
prerequisite for this cache mattering on the landing path at all. Where it
already pays without that repair is a repeated verification of the SAME tree —
which is what `tools/gatekeeper-verify-merge.sh --base-gate-cache` (schema
`4-exact-tree`) does for the differential's base arms, and which nothing in the
repo currently passes.

FAIL CLOSED
===========
`lookup` returns MISS (rc 1) on: no entry, unreadable entry, schema mismatch,
key mismatch, a JUnit that does not parse, a JUnit that does not carry a record
for every selected file, a non-zero red count, an rc outside {0}, a log without
`AGGREGATE_COMPLETE`, or ANY exception. `publish` refuses to store anything that
is not a complete green record. There is no flag that relaxes either.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import shutil
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Dict, List, Optional, Tuple

SCHEMA = "targeted-arm-cache-schema=1-exact-repeat-green-only"

# The ONLY paths whose content is exempt from the subject hash. Regenerable
# bytecode/cache the suite itself is allowed to write (see the write guard's own
# "+N regenerable cache artefact(s)" line). Everything else that git ignores is
# still an input and is still hashed.
#
# DIRECTORY components only, deliberately. An earlier draft also exempted any
# path ending `.pyc`, which would have exempted a SOURCELESS module dropped
# beside its package — that one really is importable, so it is an input.
REGENERABLE = ("__pycache__/", ".pytest_cache/")

# Packages this arm actually loads. Hashed in full, on top of the RECORD hash of
# every installed distribution, because these are the ones whose bytes decide
# what "pass" means.
PINNED_PACKAGES = ("pytest", "_pytest", "pluggy", "pytest_timeout",
                   "iniconfig", "packaging")


class Refuse(Exception):
    """An input could not be read. No key is emitted; the caller must re-run."""


def _sha_file(path: Path) -> str:
    h = hashlib.sha256()
    try:
        with path.open("rb") as fh:
            for chunk in iter(lambda: fh.read(1 << 20), b""):
                h.update(chunk)
    except OSError as exc:
        raise Refuse(f"cannot read {path}: {exc}") from exc
    return h.hexdigest()


def _git(repo: Path, *args: str) -> str:
    try:
        out = subprocess.run(["git", "-C", str(repo), *args],
                             capture_output=True, check=True)
    except (OSError, subprocess.CalledProcessError) as exc:
        raise Refuse(f"git {' '.join(args)} failed: {exc}") from exc
    return out.stdout.decode("utf-8", "surrogateescape")


def _is_regenerable(rel: str) -> bool:
    return any(part in rel for part in REGENERABLE)


def _entry(repo: Path, rel: str) -> str:
    """mode + symlink target + content hash of the WORKTREE bytes."""
    p = repo / rel
    try:
        st = p.lstat()
    except OSError as exc:
        raise Refuse(f"cannot stat {rel}: {exc}") from exc
    if os.path.islink(p):
        try:
            return f"link:{os.readlink(p)}"
        except OSError as exc:
            raise Refuse(f"cannot read link {rel}: {exc}") from exc
    if not os.path.isfile(p):
        raise Refuse(f"{rel} is neither a regular file nor a symlink")
    return f"{st.st_mode & 0o7777:o}:{_sha_file(p)}"


def subject_digest(repo: Path) -> Tuple[str, Dict[str, int]]:
    """Hash every byte of the subject tree that is not declared regenerable."""
    tracked = [p for p in _git(repo, "ls-files", "-z").split("\0") if p]
    untracked = [p for p in _git(repo, "ls-files", "-z", "--others",
                                 "--exclude-standard").split("\0") if p]
    ignored = [p for p in _git(repo, "ls-files", "-z", "--others",
                               "--ignored", "--exclude-standard").split("\0")
               if p]
    # The regenerable exemption applies wherever the path turns up. A tree whose
    # .gitignore does not happen to list `__pycache__` would otherwise report the
    # suite's own bytecode as an UNTRACKED input and miss on every run.
    untracked = [p for p in untracked if not _is_regenerable(p)]
    ignored_kept = [p for p in ignored if not _is_regenerable(p)]
    rows: List[str] = []
    for kind, paths in (("T", tracked), ("U", untracked), ("I", ignored_kept)):
        for rel in sorted(paths):
            rows.append(f"{kind} {rel} {_entry(repo, rel)}")
    h = hashlib.sha256("\n".join(rows).encode("utf-8", "surrogateescape"))
    counts = {"tracked": len(tracked), "untracked": len(untracked),
              "ignored_hashed": len(ignored_kept),
              "ignored_regenerable_skipped": len(ignored) - len(ignored_kept)}
    return h.hexdigest(), counts


def _tree_digest(root: Path) -> str:
    if not root.is_dir():
        raise Refuse(f"expected a directory: {root}")
    rows: List[str] = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames.sort()
        for name in sorted(filenames):
            p = Path(dirpath) / name
            rel = p.relative_to(root).as_posix()
            if _is_regenerable(rel):
                continue
            rows.append(f"{rel} {_sha_file(p)}")
    return hashlib.sha256("\n".join(rows).encode()).hexdigest()


def runtime_digest() -> Dict[str, str]:
    import importlib.metadata as md
    import importlib.util as iu

    dists: List[str] = []
    for dist in md.distributions():
        name = dist.metadata["Name"] if dist.metadata else None
        version = getattr(dist, "version", None)
        record = ""
        try:
            base = getattr(dist, "_path", None)
            if base is not None:
                rec = Path(base) / "RECORD"
                if rec.is_file():
                    record = _sha_file(rec)
        except Refuse:
            raise
        except Exception:  # noqa: BLE001 - unknown metadata layout is a refusal
            raise Refuse(f"cannot fingerprint distribution {name!r}")
        dists.append(f"{name}=={version}#{record}")
    dists.sort()

    pinned: List[str] = []
    for mod in PINNED_PACKAGES:
        spec = iu.find_spec(mod)
        if spec is None:
            raise Refuse(f"the arm's own dependency {mod!r} is not importable")
        if spec.submodule_search_locations:
            locs = sorted(str(x) for x in spec.submodule_search_locations)
            pinned.append(f"{mod}:" + ",".join(
                _tree_digest(Path(loc)) for loc in locs))
        elif spec.origin and spec.origin != "built-in":
            pinned.append(f"{mod}:{_sha_file(Path(spec.origin))}")
        else:
            raise Refuse(f"{mod!r} has no locatable origin")

    exe = Path(sys.executable).resolve()
    env_rows = sorted(f"{k}={v}" for k, v in os.environ.items())
    umask = os.umask(0o022)
    os.umask(umask)
    return {
        "python_version": sys.version,
        "python_exe": str(exe),
        "python_exe_sha256": _sha_file(exe),
        "platform": f"{platform.system()}/{platform.release()}/"
                    f"{platform.machine()}",
        "distributions_sha256": hashlib.sha256(
            "\n".join(dists).encode()).hexdigest(),
        "distribution_count": str(len(dists)),
        "pinned_packages_sha256": hashlib.sha256(
            "\n".join(pinned).encode()).hexdigest(),
        "environ_sha256": hashlib.sha256(
            "\n".join(env_rows).encode("utf-8", "surrogateescape")).hexdigest(),
        "umask": f"{umask:o}",
        "uid_gid": f"{os.getuid()}:{os.getgid()}",
    }


def host_digest() -> Dict[str, str]:
    def _read(path: str) -> str:
        try:
            return Path(path).read_text().strip()
        except OSError as exc:
            raise Refuse(f"cannot read host identity {path}: {exc}") from exc
    return {
        "node": platform.node(),
        "machine_id": _read("/etc/machine-id"),
        "boot_id": _read("/proc/sys/kernel/random/boot_id"),
    }


def instrument_digest(repo: Path, plugin: Path) -> Dict[str, str]:
    named = {
        "harness": repo / "tools" / "gatekeeper-land.sh",
        "driver": plugin / "programs" / "pytest_per_file_junit.py",
        "selector": plugin / "programs" / "ci_targeted_test_select.py",
        "watchdog": plugin / "programs" / "_watchdog.py",
        "progress_plugin": plugin / "programs" / "_pytest_progress_plugin.py",
        "write_guard": plugin / "programs" / "suite_write_guard.py",
        "scratch_guard": plugin / "programs" / "scratch_root_guard.py",
        "pytest_ini": plugin / "pytest.ini",
        "plugin_json": plugin / ".claude-plugin" / "plugin.json",
        "self": Path(__file__).resolve(),
    }
    out: Dict[str, str] = {}
    for label, path in named.items():
        if not path.is_file():
            raise Refuse(f"instrument input {label} is missing at {path}")
        out[label] = _sha_file(path)
    conftests = sorted(str(p.relative_to(plugin)) for p in plugin.rglob("conftest.py")
                       if not _is_regenerable(str(p.relative_to(plugin))))
    if not conftests:
        raise Refuse("no conftest.py found under the plugin root — pytest "
                     "injects it, so its absence cannot be assumed benign")
    out["conftests"] = hashlib.sha256("\n".join(
        f"{rel} {_sha_file(plugin / rel)}" for rel in conftests).encode()
    ).hexdigest()
    out["conftest_count"] = str(len(conftests))
    return out


# Flags whose VALUE is an ephemeral path chosen by `mktemp` on every
# invocation, and which name an OUTPUT or a file whose CONTENT is already in the
# key by other means. Keeping the literal path would make the key differ between
# two identical runs — measured: two consecutive identical runs produced keys
# 7453e72d… and 8e4ea411… solely because `--junit` pointed at a fresh mktemp.
# The VALUES are replaced by a placeholder; the FLAGS themselves stay in the
# key, so dropping or adding one still changes it.
_EPHEMERAL_PATH_FLAGS = ("--selection", "--junit", "--progress-relay")


def _normalise_argv(argv: List[str]) -> List[str]:
    out: List[str] = []
    skip = False
    for tok in argv:
        if skip:
            out.append("<path>")
            skip = False
            continue
        out.append(tok)
        if tok in _EPHEMERAL_PATH_FLAGS:
            skip = True
        elif tok.startswith(_EPHEMERAL_PATH_FLAGS) and "=" in tok:
            out[-1] = tok.split("=", 1)[0] + "=<path>"
    if skip:
        raise Refuse("argv ends with a path flag that has no value")
    return out


def build_key(repo: Path, plugin: Path, selection: Path,
              pytest_argv: List[str], driver_argv: List[str]
              ) -> Tuple[str, Dict[str, object]]:
    if not selection.is_file():
        raise Refuse(f"selection {selection} is missing")
    sel_lines = [l.strip() for l in selection.read_text().splitlines()
                 if l.strip()]
    if not sel_lines:
        raise Refuse("the selection is empty — an empty corpus is not a pass")
    subject, counts = subject_digest(repo)
    manifest: Dict[str, object] = {
        "schema": SCHEMA,
        "subject_sha256": subject,
        "subject_counts": counts,
        "selection_sha256": hashlib.sha256(
            "\n".join(sorted(sel_lines)).encode()).hexdigest(),
        "selection_files": len(sel_lines),
        "pytest_argv": _normalise_argv(pytest_argv),
        "driver_argv": _normalise_argv(driver_argv),
        "instrument": instrument_digest(repo, plugin),
        "runtime": runtime_digest(),
        "host": host_digest(),
    }
    # `subject_counts` is AUDIT, not input. It is derived from the same
    # enumeration that produced `subject_sha256`, and one of its members —
    # how many regenerable paths were SKIPPED — grows as the suite writes
    # `__pycache__`. MEASURED: two gatekeeper-land rounds on an identical tree
    # produced keys 887c33e2… and e50d4a3d… whose only differing field was that
    # counter (105 -> 265), so the second round missed its own predecessor. A
    # counter of what the key deliberately ignores must not be in the key.
    hashed = {k: v for k, v in manifest.items() if k != "subject_counts"}
    blob = json.dumps(hashed, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(blob.encode()).hexdigest(), manifest


# ---------------------------------------------------------------- completeness

def _junit_is_complete_green(xml: Path, selection: List[str]
                             ) -> Tuple[bool, str]:
    try:
        root = ET.parse(str(xml)).getroot()
    except Exception as exc:  # noqa: BLE001
        return False, f"junit does not parse: {exc!r}"
    suites = [root] if root.tag == "testsuite" else list(root)
    seen_files: set = set()
    red = 0
    cases = 0
    for suite in suites:
        for case in suite.iter("testcase"):
            classname = case.get("classname") or ""
            name = case.get("name") or ""
            if (classname.startswith("pytest_per_file_process")
                    or name == "process_exit"):
                # The driver's own per-file process records are a recording
                # shape, not a verdict. Excluded from the verdict comparison for
                # exactly the reason the acceptance bar says to exclude them.
                continue
            cases += 1
            f = case.get("file")
            if f:
                seen_files.add(f)
            for child in case:
                if child.tag in ("failure", "error"):
                    red += 1
                    break
    if cases == 0:
        return False, "junit carries no test cases"
    if red:
        return False, f"record is not green ({red} red case(s))"
    missing = [s for s in selection if s not in seen_files]
    if missing:
        return False, (f"{len(missing)} selected file(s) have no record, "
                       f"first={missing[0]}")
    return True, "complete green record for every selected file"


# ------------------------------------------------------------------- commands

def cmd_key(a) -> int:
    key, manifest = build_key(Path(a.repo), Path(a.plugin), Path(a.selection),
                              a.pytest_argv, a.driver_argv)
    if a.manifest:
        Path(a.manifest).write_text(json.dumps(manifest, indent=2,
                                               sort_keys=True))
    print(key)
    return 0


def cmd_lookup(a) -> int:
    try:
        key, _ = build_key(Path(a.repo), Path(a.plugin), Path(a.selection),
                           a.pytest_argv, a.driver_argv)
    except Refuse as exc:
        print(f"CACHE_MISS  key could not be built: {exc}", file=sys.stderr)
        return 1
    prefix = Path(a.cache) / key
    xml, log, man = (Path(f"{prefix}.xml"), Path(f"{prefix}.log"),
                     Path(f"{prefix}.manifest.json"))
    if not (xml.is_file() and log.is_file() and man.is_file()):
        print(f"CACHE_MISS  no entry for {key[:16]}", file=sys.stderr)
        return 1
    try:
        stored = json.loads(man.read_text())
    except Exception as exc:  # noqa: BLE001
        print(f"CACHE_MISS  manifest unreadable: {exc!r}", file=sys.stderr)
        return 1
    if stored.get("schema") != SCHEMA or stored.get("key") != key:
        print("CACHE_MISS  schema/key mismatch", file=sys.stderr)
        return 1
    if stored.get("rc") != 0:
        print("CACHE_MISS  stored rc is not 0", file=sys.stderr)
        return 1
    sel = [l.strip() for l in Path(a.selection).read_text().splitlines()
           if l.strip()]
    ok, why = _junit_is_complete_green(xml, sel)
    if not ok:
        print(f"CACHE_MISS  {why}", file=sys.stderr)
        return 1
    try:
        log_text = log.read_text(errors="replace")
    except OSError as exc:
        print(f"CACHE_MISS  log unreadable: {exc}", file=sys.stderr)
        return 1
    if "AGGREGATE_COMPLETE" not in log_text and "NORECORD" in log_text:
        print("CACHE_MISS  stored log records a lost session", file=sys.stderr)
        return 1
    if a.out_junit:
        shutil.copyfile(xml, a.out_junit)
    if a.out_log:
        shutil.copyfile(log, a.out_log)
    print(f"CACHE_HIT  {key}  ({why})", file=sys.stderr)
    return 0


def cmd_prepare(a) -> int:
    """Emit the PRE-RUN key so `publish` can store under the tree that was
    actually measured.

    MEASURED, and the reason this subcommand exists: the 279-file arm leaves 31
    files in the tree that `git status --porcelain` cannot see, because they are
    git-IGNORED but not regenerable bytecode (`scratch_geom_signoff_tests/**`,
    `reports/phase3/antenna.json`). They are still inputs — a gate may read them
    — so the subject digest covers them, which means the tree at the END of a
    run is not the tree the run was ASKED about. Publishing under a key
    recomputed afterwards would file the answer under the wrong question.
    """
    try:
        key, manifest = build_key(Path(a.repo), Path(a.plugin),
                                  Path(a.selection), a.pytest_argv,
                                  a.driver_argv)
    except Refuse as exc:
        print(f"CACHE_NOKEY  {exc}", file=sys.stderr)
        return 1
    out = Path(a.key_out)
    out.write_text(key + "\n")
    manifest["key"] = key
    # The manifest travels with the key, so the entry a later reader audits
    # describes the tree that was MEASURED, not the tree left behind afterwards.
    Path(str(out) + ".manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True))
    print(key)
    return 0


def cmd_publish(a) -> int:
    try:
        key, manifest = build_key(Path(a.repo), Path(a.plugin),
                                  Path(a.selection), a.pytest_argv,
                                  a.driver_argv)
    except Refuse as exc:
        print(f"CACHE_NOPUBLISH  key could not be built: {exc}",
              file=sys.stderr)
        return 0
    if a.key_in:
        # The PRE-RUN key wins: it names the tree the measurement answers for.
        # A mismatch is not an error — it is the arm having written into its own
        # subject — but it is DISCLOSED, because a reader who sees a cache that
        # never converges deserves to know which files moved.
        try:
            pre = Path(a.key_in).read_text().strip()
        except OSError as exc:
            print(f"CACHE_NOPUBLISH  pre-run key unreadable: {exc}",
                  file=sys.stderr)
            return 0
        if pre != key:
            print(f"CACHE_SUBJECT_MOVED  pre={pre[:16]} post={key[:16]} — the "
                  "arm wrote into its own subject; publishing under the PRE-run "
                  "key", file=sys.stderr)
        post_key = key
        key = pre
        pre_manifest = Path(str(a.key_in) + ".manifest.json")
        if pre_manifest.is_file():
            try:
                manifest = json.loads(pre_manifest.read_text())
            except Exception as exc:  # noqa: BLE001
                print(f"CACHE_NOPUBLISH  pre-run manifest unreadable: {exc!r}",
                      file=sys.stderr)
                return 0
        manifest["post_run_key"] = post_key
    if a.rc != 0:
        print("CACHE_NOPUBLISH  only a green measurement is reusable",
              file=sys.stderr)
        return 0
    sel = [l.strip() for l in Path(a.selection).read_text().splitlines()
           if l.strip()]
    ok, why = _junit_is_complete_green(Path(a.junit), sel)
    if not ok:
        print(f"CACHE_NOPUBLISH  {why}", file=sys.stderr)
        return 0
    cache = Path(a.cache)
    cache.mkdir(parents=True, exist_ok=True)
    manifest["key"] = key
    manifest["rc"] = a.rc
    prefix = cache / key
    tmpdir = Path(tempfile.mkdtemp(dir=str(cache), prefix=".pub-"))
    try:
        shutil.copyfile(a.junit, tmpdir / "x.xml")
        shutil.copyfile(a.log, tmpdir / "x.log")
        (tmpdir / "x.manifest.json").write_text(
            json.dumps(manifest, indent=2, sort_keys=True))
        # The manifest is published LAST: a lookup that finds a manifest has, by
        # construction, already got both payloads on disk.
        os.replace(tmpdir / "x.xml", f"{prefix}.xml")
        os.replace(tmpdir / "x.log", f"{prefix}.log")
        os.replace(tmpdir / "x.manifest.json", f"{prefix}.manifest.json")
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)
    print(f"CACHE_PUBLISHED  {key}", file=sys.stderr)
    return 0


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    ap.add_argument("--repo", required=True)
    ap.add_argument("--plugin", required=True)
    ap.add_argument("--selection", required=True)
    ap.add_argument("--cache", default=None)
    ap.add_argument("--pytest-argv", dest="pytest_argv", default="")
    ap.add_argument("--driver-argv", dest="driver_argv", default="")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("key"); p.add_argument("--manifest", default=None)
    p = sub.add_parser("lookup")
    p.add_argument("--out-junit", default=None)
    p.add_argument("--out-log", default=None)
    p = sub.add_parser("prepare")
    p.add_argument("--key-out", required=True)
    p = sub.add_parser("publish")
    p.add_argument("--junit", required=True)
    p.add_argument("--log", required=True)
    p.add_argument("--rc", type=int, required=True)
    p.add_argument("--key-in", default=None,
                   help="the PRE-RUN key from `prepare`; publish under it "
                        "rather than under a key recomputed after the arm has "
                        "written into its own subject")
    a = ap.parse_args(argv)
    a.pytest_argv = a.pytest_argv.split("\x1f") if a.pytest_argv else []
    a.driver_argv = a.driver_argv.split("\x1f") if a.driver_argv else []
    try:
        if a.cmd == "key":
            return cmd_key(a)
        if a.cmd == "prepare":
            return cmd_prepare(a)
        if not a.cache:
            ap.error("--cache is required for lookup/publish")
        if a.cmd == "lookup":
            return cmd_lookup(a)
        return cmd_publish(a)
    except Refuse as exc:
        # A refusal is a MISS for lookup and a no-op for publish. Never a hit.
        print(f"CACHE_REFUSE  {exc}", file=sys.stderr)
        return 0 if a.cmd == "publish" else 1
    except Exception as exc:  # noqa: BLE001
        print(f"CACHE_REFUSE  unexpected: {exc!r}", file=sys.stderr)
        return 0 if a.cmd == "publish" else 1


if __name__ == "__main__":
    raise SystemExit(main())
