#!/usr/bin/env python3
"""gatekeeper_targeted_cache.py — cross-round reuse for the TARGETED test tier.

WHY
===
Measured on this host: one `tools/gatekeeper-land.sh` round is 1864 s, and the
targeted test tier alone is 1525 s of it — 81.8%. Nothing carries that answer
from one round to the next. `.git/gatekeeper-stamp` is WRITTEN at the end of a
round and never read for reuse, `-p no:cacheprovider` disables pytest's own
incremental substrate on this tier by design, and the merged JUnit goes to a
`mktemp` that is `rm -f`'d before the round exits. So a round that re-asks the
identical question of the identical tree pays the full 1525 s to receive the
identical answer.

THE ONE FAILURE MODE THIS FILE CAN HAVE IS A FALSE GREEN
========================================================
Reuse is a claim about inputs: "nothing that could change this verdict has
changed". Every design decision below is subordinate to that claim, so the key
is EXACT rather than clever:

  * The tier is reused only for a checkout whose bytes ARE the named commit —
    no tracked modification, no untracked file, no `assume-unchanged` /
    `skip-worktree` entry hiding either. A dirty tree is a MISS, always. This
    is the property that makes `head=<sha>` a complete statement about every
    file the suite can read, and it is checked with a FRESH index rather than
    with `git status`, because the index is the one thing a subject can tamper
    with (the same argument `gatekeeper-verify-merge.sh::attest_test_worktree`
    already makes for the arms it grades).
  * Everything else that is not a repository file — interpreter, installed
    distributions, environment, host, boot, the exact driver contract, the
    selection itself — is hashed into the key. A difference in any of them is
    a MISS.
  * A MISS is the safe default in EVERY unknown: cache directory unusable,
    lock held by another round, manifest unreadable, XML unparsable, git
    unavailable. There is no path on which "I could not tell" becomes reuse.

WHY NOT A RELEVANCE-BASED (DELTA) CACHE — the design that was rejected
=====================================================================
The obvious bigger prize is "re-run only the tests the change since the last
round could have affected, and reuse the rest", keyed with
`ci_targeted_test_select.py` on the delta between the cached tree and this one.
It is not shipped, and the reason is measured rather than cautious:

  * That selector's own module docstring names the holes: a `conftest.py` edit
    finds ZERO consumers by the derived rule while really affecting every test
    file, and the 33 non-`.py` fixtures under `programs/tests/fixtures/` and
    `phase1_fixtures/` are consumed by PATH literal, so a fixture edit selects
    the smoke floor. Under delta reuse both would be served a stale verdict for
    every test outside the floor.
  * More fundamentally, this suite's SUBJECT is this repository. Tests here
    read the shipped tree, the flow definition, the docs, the shell gates, and
    the commit history through subprocesses — none of which any import graph
    can enumerate. The brief this file answers is explicit: what cannot be
    enumerated confidently is a reason NOT to cache. So the enumeration used
    here is the only complete one available — the whole commit, plus the
    non-file inputs listed above.

The cost of that choice is stated rather than hidden: this cache pays on a
RE-GATE of an unchanged tree, and pays nothing on the first gate of a new one.

WHAT IS STORED, AND ONLY WHEN
=============================
A bundle is published only when the tier answered COMPLETELY and GREEN:
driver rc 0, an `AGGREGATE_COMPLETE rc=0 ... red=0` line, the
`suite_write_guard:` report present (the paired guard `gatekeeper-land.sh`
already requires, so a session that ran without the write guard can never be
banked), no `NORECORD` / `NOTRUN` / `AGGREGATE_NORECORD` / `EMPTY` line, and a
merged JUnit that satisfies `landing_merge_verdict`'s own aggregate predicates
for exactly this selection.

RED IS DELIBERATELY NEVER CACHED. Reusing a red is fail-closed and would save
the same wall clock, but this suite has MEASURED load-sensitive failures (two
cases whose in-test subprocess budgets, 55 s and 60 s, sit within 5-9% of the
observed wall clock on a loaded host). Banking one of those would freeze a
flake into a refusal that no amount of re-running could clear, because the key
of an unchanged tree does not change. So the only thing this cache can ever do
to a round is turn a repeat GREEN into a repeat GREEN faster; it can never
manufacture a green (the key forbids it) and it can never manufacture a red
(nothing red is ever stored).

THE VALIDATION IS RE-RUN AT READ TIME, not trusted from write time. A bundle
whose XML was truncated by a full disk after it was published is refused when
it is read, because the read path re-asks every question the write path asked.

WHERE IT LIVES
==============
`<common git dir>/gatekeeper-targeted-cache/`. The COMMON dir, not the
per-worktree one, so the bundle outlives the worktree churn this repo does at
landing time — but the worktree's own absolute path is part of the key, so a
different checkout of the same commit is a MISS rather than a hit. That is a
deliberate conservatism, and it is the one place this file is stricter than
`gatekeeper-verify-merge.sh`'s `schema=4-exact-tree` base-test lane, which does
reuse across fresh checkouts of one commit: a long-lived landing worktree
carries IGNORED files (run roots, caches) that a fresh checkout does not, and
`git ls-files --others --exclude-standard` cannot see them.

USAGE
=====
    gatekeeper_targeted_cache.py key     --repo R --plugin P --selection S \
                                         --harness H --contract C [--explain]
    gatekeeper_targeted_cache.py lookup  ... --junit-out X --log-out L \
                                         [--max-age-s S]
    gatekeeper_targeted_cache.py publish ... --junit X --log L --rc N \
                                         [--wall-s S]

Exit codes: 0 = HIT / published, 1 = MISS / refused (reason on stdout),
2 = the question could not be asked (also a MISS for every caller).
"""
from __future__ import annotations

import argparse
import fcntl
import hashlib
import importlib.util
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

SCHEMA = "1-exact-tree-targeted"

RC_HIT, RC_MISS, RC_CANNOT_ASK = 0, 1, 2

#: Environment variables that cannot change a pytest verdict because they
#: describe the SHELL that spawned the gate rather than the run. Everything
#: else in the environment is hashed. The list is deliberately three entries
#: long: each addition is a place a false green could hide, so it must be
#: argued rather than convenient.
ENV_IGNORE = ("_", "SHLVL", "OLDPWD")

#: Files hashed by name in addition to being covered by `head`. Redundant on a
#: clean checkout — and that redundancy is the point: it is what catches a
#: gate script or driver invoked from a DIFFERENT checkout than the one being
#: measured, which `head` alone cannot see.
INSTRUMENT_RELS = (
    "programs/pytest_per_file_junit.py",
    "programs/_watchdog.py",
    "programs/_pytest_progress_plugin.py",
    "programs/suite_write_guard.py",
    "programs/scratch_root_guard.py",
    "programs/ci_targeted_test_select.py",
    "programs/landing_merge_verdict.py",
    "conftest.py",
    "programs/tests/conftest.py",
    "pytest.ini",
    "setup.cfg",
    "pyproject.toml",
    "tox.ini",
)

#: How many bundles to keep. A landing host gates many trees; the bundles are
#: small (one merged JUnit plus one log) but unbounded growth inside `.git` is
#: a defect of its own.
KEEP_BUNDLES = 40

#: HOW OLD A BUNDLE MAY BE. Not a cleanup policy — a correctness bound on the
#: inputs the key CANNOT see, of which there are exactly three and they are
#: named rather than waved at:
#:
#:   * WALL-CLOCK TIME. A test that reads today's date is green until it is not,
#:     on a tree that never moved. Nothing in the key changes when the day does.
#:   * IGNORED FILES. `git ls-files --others --exclude-standard` is blind to
#:     everything `.gitignore` covers — run roots, caches, generated artefacts —
#:     and a test that reads one of those can change its answer between rounds.
#:   * A SAME-VERSION REINSTALL. The distributions digest carries name and
#:     version; a package reinstalled at the same version with different bytes
#:     is invisible to it.
#:
#: None of the three is enumerable, so the honest thing is to bound how long a
#: green may be believed rather than to claim it is eternal. Six hours covers
#: the case this cache exists for — re-gating a tree during one landing session
#: — and expires long before "the day changed".
MAX_AGE_S = 6 * 3600


# ------------------------------------------------------------------ utilities


def _git(repo: Path, *args: str, env: dict | None = None
         ) -> subprocess.CompletedProcess:
    e = dict(os.environ)
    if env:
        e.update(env)
    return subprocess.run(["git", "-C", str(repo), *args],
                          capture_output=True, text=True, timeout=300, env=e)


def _sha256_bytes(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def _sha256_file(p: Path) -> str:
    try:
        return _sha256_bytes(p.read_bytes())
    except OSError:
        return "ABSENT"


def _load_verdict_module(plugin: Path):
    """`landing_merge_verdict` loaded by path, exactly as the verifier loads it.

    The aggregate predicates below are that module's, not a second copy of
    them. A cache that decided "this record covers this selection" with its own
    reimplementation would be free to drift from the program whose answer the
    landing actually uses, and the drift would be invisible until it mattered.
    """
    path = plugin / "programs" / "landing_merge_verdict.py"
    spec = importlib.util.spec_from_file_location("_gk_tcache_verdict", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


# ------------------------------------------------- the worktree exactness gate


def worktree_is_exact(repo: Path) -> tuple[bool, str]:
    """Whether this checkout's BYTES are exactly `HEAD`, with nothing beside it.

    Three questions, because three different things break the claim that
    `head=<sha>` names every file the suite can read:

      index flags   `assume-unchanged` / `skip-worktree` let a tracked file be
                    edited while `git status` stays clean. Read first, because
                    it is the one that makes the other two lie.
      tracked bytes compared through a FRESH index populated from `HEAD^{tree}`,
                    so none of the subject's index state participates.
      untracked     any file pytest could collect or a repo-scanning test could
                    read. `--exclude-standard`, so `.gitignore` still governs —
                    which is exactly why an IGNORED file is the one input this
                    gate cannot see, and why the worktree path is in the key.
    """
    head = _git(repo, "rev-parse", "HEAD")
    if head.returncode != 0:
        return False, "cannot read HEAD"
    flags = _git(repo, "ls-files", "-v")
    if flags.returncode != 0:
        return False, "cannot read the index flags"
    for line in (flags.stdout or "").splitlines():
        if re.match(r"^(S|[a-z]) ", line):
            return False, "index carries assume-unchanged/skip-worktree entries"
    tmpdir = tempfile.mkdtemp(prefix="gk_tcache_index_")
    try:
        index = os.path.join(tmpdir, "index")
        env = {"GIT_INDEX_FILE": index, "GIT_NO_REPLACE_OBJECTS": "1"}
        rt = _git(repo, "read-tree", "HEAD^{tree}", env=env)
        if rt.returncode != 0:
            return False, "cannot materialize the expected tree index"
        # A `read-tree` index has no stat cache, so unchanged files would all
        # look modified. Refreshing legitimately returns 1 when something IS
        # modified; `diff-files` below is what decides.
        _git(repo, "update-index", "--really-refresh", env=env)
        df = _git(repo, "diff-files", "--name-only", "--no-ext-diff",
                  "--no-textconv", "--ignore-submodules=none", env=env)
        if df.returncode > 1:
            return False, "cannot compare the tracked worktree bytes"
        if (df.stdout or "").strip():
            n = len((df.stdout or "").strip().splitlines())
            return False, f"{n} tracked file(s) differ from HEAD"
        others = _git(repo, "ls-files", "--others", "--exclude-standard",
                      env=env)
        if others.returncode != 0:
            return False, "cannot enumerate untracked files"
        if (others.stdout or "").strip():
            n = len((others.stdout or "").strip().splitlines())
            return False, f"{n} untracked file(s) present"
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)
    return True, "exact"


# ------------------------------------------------------------------- the key


def _distributions_digest() -> str:
    """Every installed distribution's name and version.

    `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1` means only `pytest` and the explicitly
    named `pytest_timeout` can join the session — but the SUITE imports third
    party modules of its own, and this file is not in a position to enumerate
    which. The whole set is cheaper to hash than to argue about.
    """
    try:
        from importlib import metadata
        names = sorted(
            f"{d.metadata['Name']}=={d.version}"
            for d in metadata.distributions()
            if d.metadata and d.metadata.get("Name"))
        return _sha256_bytes("\n".join(names).encode())
    except Exception as exc:                                    # noqa: BLE001
        # UNKNOWN, and unknown must not collapse into a shared constant: a
        # constant would make two hosts with different, unreadable package
        # sets share a key. The exception text keys them apart, and the caller
        # additionally treats an unreadable environment as a reason to miss.
        return "UNREADABLE:" + _sha256_bytes(repr(exc).encode())


def _env_digest() -> str:
    items = sorted((k, v) for k, v in os.environ.items() if k not in ENV_IGNORE)
    return _sha256_bytes(
        "\0".join(f"{k}={v}" for k, v in items).encode("utf-8", "replace"))


def _boot_id() -> str:
    try:
        return Path("/proc/sys/kernel/random/boot_id").read_text().strip()
    except OSError:
        return "unknown"


def key_material(repo: Path, plugin: Path, selection: Path, harness: Path,
                 contract: str) -> list[tuple[str, str]]:
    """The ordered (name, value) pairs the key digest is taken over.

    Ordered and printable on purpose: `key --explain` is how a reader answers
    "why did this round miss", and how a reviewer audits what the cache
    believes a verdict depends on. A component that is not on this list is a
    component this cache is claiming cannot change the tier's answer.
    """
    head = _git(repo, "rev-parse", "HEAD").stdout.strip()
    pjson = plugin / ".claude-plugin" / "plugin.json"
    try:
        version = json.loads(pjson.read_text()).get("version", "UNREADABLE")
    except Exception:                                           # noqa: BLE001
        version = "UNREADABLE"
    instruments = ";".join(
        f"{rel}:{_sha256_file(plugin / rel)}" for rel in INSTRUMENT_RELS)
    return [
        ("schema", SCHEMA),
        ("head", head),
        ("repo", str(repo.resolve())),
        ("plugin", str(plugin.resolve())),
        ("selection_sha256", _sha256_file(selection)),
        ("harness_sha256", _sha256_file(harness)),
        ("instruments", _sha256_bytes(instruments.encode())),
        ("plugin_version", str(version)),
        ("contract", contract),
        ("python", f"{sys.executable}|{sys.version}|{platform.machine()}"),
        ("distributions", _distributions_digest()),
        ("env", _env_digest()),
        ("host", platform.node()),
        ("boot", _boot_id()),
    ]


def key_digest(material: list[tuple[str, str]]) -> str:
    return _sha256_bytes(
        "\n".join(f"{k}={v}" for k, v in material).encode("utf-8", "replace"))


# --------------------------------------------------------- bundle validation


def _selection_list(selection: Path) -> list[str]:
    return [ln.strip() for ln in selection.read_text().splitlines() if ln.strip()]


_BAD_MARKERS = ("NORECORD", "NOTRUN", "AGGREGATE_NORECORD", "EMPTY",
                "FALLBACK_BATCH_NORECORD", "FALLBACK_WORKER_NORECORD")


def log_is_complete_green(text: str) -> tuple[bool, str]:
    """Whether a driver log is the COMPLETE, GUARDED, GREEN shape.

    Every condition here is one `gatekeeper-land.sh:run_pytest` already imposes
    on a live run. They are re-imposed on the stored copy because a bundle is
    read by a LATER round, and that round's verdict is built out of this text.
    """
    lines = text.splitlines()
    for line in lines:
        for marker in _BAD_MARKERS:
            if line.startswith(marker):
                return False, f"log carries {marker}"
    agg = [ln for ln in lines if ln.startswith("AGGREGATE_COMPLETE")]
    if len(agg) != 1:
        return False, f"{len(agg)} AGGREGATE_COMPLETE line(s), want exactly 1"
    m = re.match(r"^AGGREGATE_COMPLETE\s+rc=(-?\d+)\s+cases=(\d+)\s+red=(\d+)",
                 agg[0])
    if not m:
        return False, "AGGREGATE_COMPLETE line is not the expected shape"
    if m.group(1) != "0" or m.group(3) != "0":
        return False, f"aggregate rc={m.group(1)} red={m.group(3)} is not green"
    if int(m.group(2)) <= 0:
        return False, "aggregate recorded zero cases"
    if not any(ln.startswith("=== pytest junit summary") for ln in lines):
        return False, "no junit summary — the instrument did not report"
    # The PAIRED GUARD, carried across rounds. `gatekeeper-land.sh` refuses a
    # green whose session did not report `suite_write_guard:`, because a green
    # bought by dropping the write guard looks exactly like an honest one. A
    # bundle is a green, so it inherits the same bar.
    if "suite_write_guard:" not in text:
        return False, "suite_write_guard did not report in the stored session"
    return True, "complete green"


def junit_is_complete_green(plugin: Path, junit: Path,
                            selection: list[str]) -> tuple[bool, str]:
    try:
        verdict = _load_verdict_module(plugin)
    except Exception as exc:                                    # noqa: BLE001
        return False, f"landing_merge_verdict unavailable ({exc})"
    try:
        if not selection:
            return False, "empty selection"
        if not verdict.junit_has_aggregate_process(junit):
            return False, "no valid aggregate process attestation"
        seen = verdict.junit_aggregate_files(junit, selection)
        if seen != set(selection):
            return False, (f"aggregate covers {len(seen)} of "
                           f"{len(selection)} selected file(s)")
        red = verdict.junit_aggregate_red_count(junit)
        if red:
            return False, f"aggregate carries {red} red outcome(s)"
    except Exception as exc:                                    # noqa: BLE001
        return False, f"junit unreadable ({exc})"
    return True, "complete green"


# ------------------------------------------------------------------- storage


def _cache_dir(repo: Path, explicit: str | None) -> Path | None:
    if explicit:
        return Path(explicit)
    r = _git(repo, "rev-parse", "--path-format=absolute", "--git-common-dir")
    if r.returncode != 0 or not r.stdout.strip():
        return None
    return Path(r.stdout.strip()) / "gatekeeper-targeted-cache"


class _Lock:
    """Non-blocking flock. A BUSY lock is a MISS, never a wait.

    Cache coordination must not serialize two rounds: a landing that waited on
    another landing's cache would be slower than the tier it is replacing.
    """

    def __init__(self, path: Path):
        self.path = path
        self.fd = None

    def __enter__(self) -> bool:
        try:
            self.fd = os.open(str(self.path), os.O_CREAT | os.O_RDWR, 0o644)
            fcntl.flock(self.fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            return True
        except OSError:
            if self.fd is not None:
                os.close(self.fd)
                self.fd = None
            return False

    def __exit__(self, *exc):
        if self.fd is not None:
            try:
                fcntl.flock(self.fd, fcntl.LOCK_UN)
            finally:
                os.close(self.fd)
                self.fd = None


def _prefix(cache: Path, head: str, digest: str) -> Path:
    return cache / f"{head}.{digest}.targeted"


def _prune(cache: Path, keep: int = KEEP_BUNDLES) -> None:
    try:
        manifests = sorted(cache.glob("*.targeted.manifest"),
                           key=lambda p: p.stat().st_mtime, reverse=True)
    except OSError:
        return
    for stale in manifests[keep:]:
        base = str(stale)[: -len(".manifest")]
        for ext in (".manifest", ".xml", ".log", ".selection", ".lock"):
            try:
                os.unlink(base + ext)
            except OSError:
                pass


# --------------------------------------------------------------- the commands


def _common_args(ap: argparse.ArgumentParser) -> None:
    ap.add_argument("--repo", required=True)
    ap.add_argument("--plugin", required=True)
    ap.add_argument("--selection", required=True)
    ap.add_argument("--harness", required=True)
    ap.add_argument("--contract", required=True,
                    help="the exact driver/pytest contract this tier ran under")
    ap.add_argument("--cache-dir", default=None)


def _resolve(a) -> tuple[Path, Path, Path, Path]:
    return (Path(a.repo), Path(a.plugin), Path(a.selection), Path(a.harness))


def cmd_key(a) -> int:
    repo, plugin, selection, harness = _resolve(a)
    material = key_material(repo, plugin, selection, harness, a.contract)
    ok, why = worktree_is_exact(repo)
    if a.explain:
        for k, v in material:
            print(f"{k}={v}")
        print(f"worktree_exact={'yes' if ok else 'no'} ({why})")
    print(key_digest(material))
    return RC_HIT if ok else RC_MISS


def cmd_lookup(a) -> int:
    repo, plugin, selection, harness = _resolve(a)
    ok, why = worktree_is_exact(repo)
    if not ok:
        print(f"MISS  worktree is not exactly HEAD: {why}")
        return RC_MISS
    cache = _cache_dir(repo, a.cache_dir)
    if cache is None or not cache.is_dir():
        print("MISS  no cache directory")
        return RC_MISS
    material = key_material(repo, plugin, selection, harness, a.contract)
    head = dict(material)["head"]
    if not head:
        print("MISS  HEAD is unreadable")
        return RC_CANNOT_ASK
    digest = key_digest(material)
    prefix = _prefix(cache, head, digest)
    manifest_p = Path(str(prefix) + ".manifest")
    xml_p = Path(str(prefix) + ".xml")
    log_p = Path(str(prefix) + ".log")
    sel_p = Path(str(prefix) + ".selection")
    with _Lock(Path(str(prefix) + ".lock")) as held:
        if not held:
            print("MISS  another round holds this bundle's lock")
            return RC_MISS
        for p in (manifest_p, xml_p, log_p, sel_p):
            if not p.is_file() or p.stat().st_size == 0:
                print(f"MISS  no bundle ({p.name} absent or empty)")
                return RC_MISS
        manifest = manifest_p.read_text().splitlines()
        want = {f"schema={SCHEMA}", f"head={head}", f"fingerprint={digest}",
                f"host={platform.node()}", "rc=0"}
        missing = sorted(w for w in want if w not in manifest)
        if missing:
            print(f"MISS  manifest does not assert {missing}")
            return RC_MISS
        # BYTE-FOR-BYTE, beside the hash already in the key. The hash makes a
        # different selection a different bundle; this makes a hash collision
        # or a truncated write refuse instead of being reused.
        try:
            if sel_p.read_bytes() != selection.read_bytes():
                print("MISS  stored selection differs from this round's")
                return RC_MISS
        except OSError as exc:
            print(f"MISS  selection unreadable ({exc})")
            return RC_CANNOT_ASK
        text = log_p.read_text(errors="replace")
        good, why = log_is_complete_green(text)
        if not good:
            print(f"MISS  stored log is not a complete green: {why}")
            return RC_MISS
        good, why = junit_is_complete_green(plugin, xml_p,
                                            _selection_list(selection))
        if not good:
            print(f"MISS  stored junit is not a complete green: {why}")
            return RC_MISS
        try:
            shutil.copyfile(xml_p, a.junit_out)
            shutil.copyfile(log_p, a.log_out)
        except OSError as exc:
            print(f"MISS  cannot deliver the bundle ({exc})")
            return RC_CANNOT_ASK
        # THE AGE BOUND. Read from the manifest rather than from the file's
        # mtime, which a copy or a restore rewrites.
        epoch = next((ln.split("=", 1)[1] for ln in manifest
                      if ln.startswith("measured_epoch=")), None)
        try:
            age = time.time() - float(epoch)                     # type: ignore
        except (TypeError, ValueError):
            print("MISS  bundle does not say when it was measured")
            return RC_MISS
        if age < 0 or age > a.max_age_s:
            print(f"MISS  bundle is {int(age)} s old, past the "
                  f"{int(a.max_age_s)} s bound")
            return RC_MISS
        measured = next((ln.split("=", 1)[1] for ln in manifest
                         if ln.startswith("measured_at=")), "unknown")
        wall = next((ln.split("=", 1)[1] for ln in manifest
                     if ln.startswith("measured_wall_s=")), "unknown")
        print(f"HIT  measured_at={measured} measured_wall_s={wall} "
              f"head={head[:12]} key={digest[:12]}")
        return RC_HIT


def cmd_publish(a) -> int:
    repo, plugin, selection, harness = _resolve(a)
    if str(a.rc) != "0":
        print(f"REFUSED  rc={a.rc} — only a complete green tier is banked")
        return RC_MISS
    ok, why = worktree_is_exact(repo)
    if not ok:
        print(f"REFUSED  worktree is not exactly HEAD: {why}")
        return RC_MISS
    cache = _cache_dir(repo, a.cache_dir)
    if cache is None:
        print("REFUSED  no cache directory")
        return RC_CANNOT_ASK
    try:
        cache.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        print(f"REFUSED  cannot create the cache directory ({exc})")
        return RC_CANNOT_ASK
    text = Path(a.log).read_text(errors="replace")
    good, why = log_is_complete_green(text)
    if not good:
        print(f"REFUSED  this round's log is not a complete green: {why}")
        return RC_MISS
    good, why = junit_is_complete_green(plugin, Path(a.junit),
                                        _selection_list(selection))
    if not good:
        print(f"REFUSED  this round's junit is not a complete green: {why}")
        return RC_MISS
    material = key_material(repo, plugin, selection, harness, a.contract)
    head = dict(material)["head"]
    digest = key_digest(material)
    prefix = _prefix(cache, head, digest)
    with _Lock(Path(str(prefix) + ".lock")) as held:
        if not held:
            print("REFUSED  another round holds this bundle's lock")
            return RC_MISS
        try:
            for src, ext in ((a.junit, ".xml"), (a.log, ".log"),
                             (str(selection), ".selection")):
                tmp = str(prefix) + ext + ".tmp"
                shutil.copyfile(src, tmp)
                os.replace(tmp, str(prefix) + ext)
            manifest = "\n".join([
                f"schema={SCHEMA}",
                f"head={head}",
                f"fingerprint={digest}",
                f"host={platform.node()}",
                f"repo={repo.resolve()}",
                "rc=0",
                f"files={len(_selection_list(selection))}",
                f"measured_at={time.strftime('%Y-%m-%dT%H:%M:%S%z')}",
                f"measured_epoch={int(time.time())}",
                f"measured_wall_s={a.wall_s}",
            ]) + "\n"
            tmp = str(prefix) + ".manifest.tmp"
            Path(tmp).write_text(manifest)
            os.replace(tmp, str(prefix) + ".manifest")
        except OSError as exc:
            print(f"REFUSED  cannot write the bundle ({exc})")
            return RC_CANNOT_ASK
    _prune(cache)
    print(f"STORED  head={head[:12]} key={digest[:12]} "
          f"files={len(_selection_list(selection))} wall_s={a.wall_s}")
    return RC_HIT


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("key", help="print the cache key for this round")
    _common_args(p)
    p.add_argument("--explain", action="store_true")
    p.set_defaults(fn=cmd_key)

    p = sub.add_parser("lookup", help="reuse a stored tier result, or MISS")
    _common_args(p)
    p.add_argument("--junit-out", required=True)
    p.add_argument("--log-out", required=True)
    p.add_argument("--max-age-s", type=float, default=MAX_AGE_S,
                   help="refuse a bundle older than this (see MAX_AGE_S)")
    p.set_defaults(fn=cmd_lookup)

    p = sub.add_parser("publish", help="bank this round's tier result")
    _common_args(p)
    p.add_argument("--junit", required=True)
    p.add_argument("--log", required=True)
    p.add_argument("--rc", required=True)
    p.add_argument("--wall-s", default="unknown")
    p.set_defaults(fn=cmd_publish)

    a = ap.parse_args(argv)
    try:
        return a.fn(a)
    except Exception as exc:                                    # noqa: BLE001
        # ANY unexpected failure is a MISS. This program sits on the landing
        # critical path and its worst possible behaviour is to be believed
        # when it is confused.
        print(f"MISS  cache decision failed ({exc!r})")
        return RC_CANNOT_ASK


if __name__ == "__main__":
    raise SystemExit(main())
