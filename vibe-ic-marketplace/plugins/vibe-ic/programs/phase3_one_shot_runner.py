#!/usr/bin/env python3
"""Tool owners and public entry for phase3_one_shot_runner."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import json
import os
import re
import shlex
import subprocess
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple, Union
import _path_layout as _pl
import verdict as _V
import _runner_measurement as _rmeas
import _source_record_merge as _srm
import _container_exec as _cex
import _watchdog as _wd
import _docker_watchdog as _dwd

TOOLS_IN_CONTAINER = "/foss/tools"


_CONTAINER_MOUNTS_CACHE: Dict[str, List[Tuple[str, str]]] = {}


def _container_mounts(container: str) -> List[Tuple[str, str]]:
    if container in _CONTAINER_MOUNTS_CACHE:
        return _CONTAINER_MOUNTS_CACHE[container]
    out: List[Tuple[str, str]] = []
    try:
        cp = subprocess.run(
            ["docker", "inspect", container,
             "--format", "{{range .Mounts}}{{.Source}}|{{.Destination}}\n{{end}}"],
            capture_output=True, text=True, timeout=10,
        )
        if cp.returncode == 0:
            for line in cp.stdout.splitlines():
                line = line.strip()
                if not line or "|" not in line:
                    continue
                src, dst = line.split("|", 1)
                if src and dst:
                    out.append((src.rstrip("/"), dst.rstrip("/")))
    except Exception:
        pass
    # THE TIE-BREAK IS A SEMANTIC CHOICE, NOT A SORT KEY — issue #2061 / R-02.
    #
    # Longest-source-first is right and is unchanged: a nested mount must win
    # over the parent that contains it. But when two mounts have sources of
    # EQUAL LENGTH the old `sort(key=len, reverse=True)` was stable, so the tie
    # fell through to whatever order `docker inspect` happened to emit — and
    # that order is NOT STABLE. Lane rbspm2 measured it over 50 calls per
    # container: the host-unreadable `/foss/designs` won the tie 18 % of the
    # time on one container and 10 % on another.
    #
    # WHAT IT COST. `_to_container_path` returns the FIRST covering mount, and
    # consumers that must read the mapped file ON THE HOST — `dfm_screen_check`
    # resolves via cuts from the LEFs the run's pnr tcl names — then read a path
    # that exists only inside the container. MEASURED: two runs of ONE tree
    # published OPPOSITE `dfm_screen.json` verdicts (3550 vias UNRESOLVED /
    # redundancy UNMEASURED, versus resolved with `single_cut_fraction 1.0` and
    # VIA_REDUNDANCY_LOW). A verdict that flips on a coin toss is worse than
    # either answer, because nothing in the record says a toss happened.
    #
    # SO THE TIE IS DECIDED BY WHAT THE ANSWER IS FOR: prefer a destination that
    # EXISTS ON THIS HOST, because that is the one a host-side reader can open.
    # The third key makes the order TOTAL, so two equal-length sources whose
    # destinations are both present (or both absent) still resolve identically
    # on every call — no residual dependence on the daemon's ordering.
    #
    # Unchanged whenever sources differ in length, which is the ordinary case.
    def _mount_rank(t: Tuple[str, str]) -> Tuple[int, int, str]:
        src, dst = t
        return (-len(src), 0 if os.path.exists(dst) else 1, dst)

    out.sort(key=_mount_rank)
    _CONTAINER_MOUNTS_CACHE[container] = out
    return out


def _to_container_path(host_path: str, container: str) -> str:
    """Translate a host path to the path that resolves inside `container`.

    If no mount covers the path, returns the original (caller must accept
    that the operation may fail inside the container)."""
    if isinstance(host_path, (list, tuple)):
        return [_to_container_path(path, container) for path in host_path]
    if not host_path:
        return host_path
    p = str(host_path)
    for src, dst in _container_mounts(container):
        if p == src:
            return dst
        if p.startswith(src + "/"):
            return dst + p[len(src):]
    return p


_VERDICT_TIERS = tuple(v.value for v in _V.Verdict)


_PROV_SINK: Optional[Path] = None


_SHELL_PROLOGUE = frozenset((
    "export", "cd", "set", "unset", "source", ".", "umask", "ulimit",
    "eval", "exec", "true", ":", "shift", "readonly", "local", "alias",
))


def _split_shell_chain(text: str) -> List[str]:
    """Split a shell command on its `&&` / `||` / `;` separators, IGNORING
    any that fall inside quotes.

    A plain `re.split` on those tokens does not know about quoting, and this
    runner itself builds commands where it matters: it joins multi-valued
    arguments with `;` and then wraps them in double quotes —
    `VAR="/a/one.ext;/a/two.ext"`. The naive split cuts THROUGH that value,
    leaving one dangling quote in each half, which then makes `shlex.split`
    raise and fall back to whitespace splitting. The second half of the
    assignment — a bare path — is then read as the command word.

    MEASURED consequence on a real run: the ledger recorded a data file as
    the tool that ran (`tool: "<something>.ext\\""`, quote and all), and the
    version probe then executed that string in the container, so `version`
    became the shell's `command not found` diagnostic — while
    `version_capture` still said `probed`. The provenance chain is the
    anti-fabrication backbone; a row naming the wrong program with a fake
    version is exactly the failure mode it exists to prevent.

    Pure shell grammar, chip-AGNOSTIC.
    """
    parts: List[str] = []
    buf: List[str] = []
    quote: Optional[str] = None
    i = 0
    n = len(text)
    while i < n:
        ch = text[i]
        if quote:
            buf.append(ch)
            # Inside double quotes a backslash escapes; inside single quotes
            # it does not. Mirror the shell rather than approximating it.
            if ch == "\\" and quote == '"' and i + 1 < n:
                i += 1
                buf.append(text[i])
            elif ch == quote:
                quote = None
            i += 1
            continue
        if ch in ("'", '"'):
            quote = ch
            buf.append(ch)
            i += 1
            continue
        if ch == "\\" and i + 1 < n:
            buf.append(ch)
            i += 1
            buf.append(text[i])
            i += 1
            continue
        if text.startswith("&&", i) or text.startswith("||", i):
            parts.append("".join(buf))
            buf = []
            i += 2
            continue
        if ch == ";":
            parts.append("".join(buf))
            buf = []
            i += 1
            continue
        buf.append(ch)
        i += 1
    parts.append("".join(buf))
    return [p.strip() for p in parts if p.strip()]


def _tool_from_command(cmd: str) -> str:
    """The FIRST REAL PROGRAM in a shell command chain.

    Measured on a real run before this existed: every entry recorded
    `tool: "export"`, because the runner prefixes its container commands with
    `export PATH=... && openroad ...` and the old code took `argv[0]`. A
    ledger whose `tool` column names a shell builtin for every EDA run is the
    same defect vibe-ic#365 was filed about — a field that LOOKS populated
    while carrying the wrong thing — reintroduced by the fix for it.

    Walks the `&&` / `;` chain and returns the first segment whose command
    word is neither a shell builtin nor a `VAR=value` assignment. Falls back
    to the first segment when the whole chain is prologue, so the result is
    never empty.
    """
    text = (cmd or "").strip()
    if not text:
        return "sh"
    parts = _split_shell_chain(text)
    first = ""
    for seg in parts:
        seg = seg.strip()
        if not seg:
            continue
        try:
            words = shlex.split(seg)
        except ValueError:
            words = seg.split()
        # Skip leading `VAR=value` assignments (`FOO=1 bar` runs `bar`).
        while words and re.match(r"^[A-Za-z_][A-Za-z0-9_]*=", words[0]):
            words.pop(0)
        if not words:
            continue
        head = words[0].rsplit("/", 1)[-1]
        first = first or head
        if head not in _SHELL_PROLOGUE:
            return head
    return first or "sh"


_VERSION_CACHE: Dict[Tuple[str, str], Optional[str]] = {}


_VERSION_FLAGS = ("--version", "-version", "-v")


def _tool_version(container: Optional[str], tool: str) -> Optional[str]:
    """First line of `<tool> <version-flag>`, memoised per (container, tool)."""
    if not container or not tool or tool in ("sh", "export"):
        return None
    key = (container, tool)
    if key in _VERSION_CACHE:
        return _VERSION_CACHE[key]
    out: Optional[str] = None
    for flag in _VERSION_FLAGS:
        try:
            # NO PIPELINE. `<tool> --version 2>&1 | head -3` returns `head`'s
            # exit status, which is 0 whenever head runs at all — so the
            # `rc != 0` guard below could never fire, and a shell
            # `command not found` was accepted as this tool's version string
            # (MEASURED: a real ledger row carried
            # `version: "bash: line 1: ...: command not found"` alongside
            # `version_capture: "probed"`). Ask the tool directly and take
            # the first lines here, so the rc under test is the TOOL's.
            rc, so, se = _docker_exec_raw(
                container, f"{shlex.quote(tool)} {flag} 2>&1", timeout=25)
        except Exception:  # noqa: BLE001 — a probe must never break the run
            break
        if rc != 0:
            continue
        # `[:3]` keeps the window the removed `head -3` had, so this change is
        # ONLY about which process's exit status is tested. A probe that
        # captured a version before still captures the same string.
        for line in (so or se or "").splitlines()[:3]:
            s = line.strip()
            # The image prints a login banner on every shell; a banner line is
            # not a version. This is the same `[LEVEL]` filter provenance_logger
            # already needed.
            if s and not s.startswith("[") and "PATH variable" not in s:
                out = s[:200]
                break
        if out:
            break
    _VERSION_CACHE[key] = out
    return out


def _hash_declared_outputs(sink: str, declared) -> dict:
    """SHA256 the artefacts a CALL SITE declared it was asking the tool for.

    `declared` comes from the caller, never from the filesystem. That
    distinction is the whole point and it is doctrine rule #2's: the tempting
    shortcut is to scan for files modified during the command's window and
    attach whatever moved, but that associates a hash with a command that may
    not have produced it — a fabricated attestation, which is exactly what the
    provenance gate exists to catch. A fabricated audit chain is worse than an
    incomplete one, because it is believed.

    So this hashes ONLY paths the caller named, records them project-relative
    (`PROVENANCE_PATH_OUTSIDE_PROJECT`), and SILENTLY OMITS any that do not
    exist — a tool that failed produced nothing, and claiming otherwise would
    be the same fabrication one layer down. An entry with no surviving outputs
    keeps no `outputs` key at all: empty is honest.
    """
    out: dict = {}
    root = Path(sink).resolve()
    for item in (declared or []):
        try:
            p = Path(item)
            p = p if p.is_absolute() else (root / p)
            p = p.resolve()
            if not p.is_file():
                continue                      # not produced — say nothing
            try:
                rel = p.relative_to(root).as_posix()
            except ValueError:
                continue                      # outside the project; not ours
            h = __import__("hashlib").sha256()
            with p.open("rb") as f:
                for chunk in iter(lambda: f.read(1 << 20), b""):
                    h.update(chunk)
            out[rel] = f"sha256:{h.hexdigest()}"
        except Exception:  # noqa: BLE001 — the ledger must never break the run
            continue
    return out


def _log_invocation(cmd: str, rc: int, duration_ms: int,
                    marker: Optional[str] = None,
                    container: Optional[str] = None,
                    outputs=None, input_hashes=None) -> None:
    """Append ONE measured invocation record. Never raises: a ledger that can
    break the run it documents would be traded away the first time it did.

    `duration_s` is emitted ALONGSIDE `duration_ms` on purpose. The other
    writer of this same file (`provenance_logger.py`) has always used
    `duration_s`, so emitting only `duration_ms` would leave every existing
    consumer of `duration_s` reading nothing for these rows — a new
    reader-without-producer split (the vibe-ic#312 family) created by the fix
    for #365. `record` lets a consumer tell the two writers apart rather than
    inferring it from which keys happen to be present.
    """
    sink = _PROV_SINK
    if sink is None:
        return
    _tool = _tool_from_command(cmd)
    _ver = _tool_version(container, _tool)
    entry = {
        "record": "invocation",
        "tool": _tool,
        # NEVER a silent absence: an unknown build and an unrecorded one must
        # not look alike (the #312 lesson, applied to this writer).
        "version": _ver,
        "version_capture": ("probed" if _ver else
                            "NOT CAPTURED — no version flag answered, or no "
                            "container was supplied to the logger"),
        "command": cmd[:400],
        # WHERE IT RAN. A ledger that names a container the run never entered
        # is a false provenance record, and this file learned that the hard
        # way when Phase 3 began running its tools locally (see
        # `_local_exec_mode`). One field, two values, never absent.
        "exec_route": "local" if _local_exec_mode() else "container",
        "exit_code": int(rc),
        "duration_ms": int(duration_ms),   # MEASURED, not a placeholder
        "duration_s": round(int(duration_ms) / 1000.0, 3),
        "measured": True,
        # module-scope import: `_dt` in this file is a FUNCTION-local alias
        # elsewhere, so referencing it here would NameError at runtime — and
        # the except-guard below would have swallowed it into silence.
        "timestamp": __import__("datetime").datetime.now(
            __import__("datetime").timezone.utc)
            .strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
    if marker:
        entry["marker"] = marker
    if input_hashes:
        entry["inputs"] = input_hashes
    # Declared by the CALL SITE, hashed here. Absent when the caller declared
    # nothing or nothing it declared was produced — empty is honest.
    _outs = _hash_declared_outputs(sink, outputs)
    if _outs:
        entry["outputs"] = _outs
        # THE TOOL'S THIRD VALUE, read from the artefact the tool wrote.
        #
        # `_mcp_measurement`'s writer half is the MCP server's
        # `measurementRecord()`, which this runner never goes through — it
        # drives its tools by `docker exec` — so the record was structurally
        # absent for every physical artefact on every design, and
        # `provenance_check --require-measured` reported UNDECLARED ->
        # INCOMPLETE forever. MEASURED on spm x gf180mcuD v1.14.5: 25 of 34
        # gating step-ordering violations were that one gate with nothing to
        # read.
        #
        # NOT the flat `"measured": True` above it — that one is a literal
        # about `duration_ms`, and promoting it here would assert that a tool
        # did its work because a subprocess was timed, which is the exact
        # fabrication `_mcp_measurement` exists to refuse. This reads the
        # artefact instead, and says nothing when it has no rule for it.
        try:
            _m = _rmeas.derive_for_outputs(Path(sink), _outs, _tool)
            if _m is not None:
                entry["measurement"] = _m
        except Exception:      # nosec — provenance must never break a run
            pass
    try:
        with (Path(sink) / "provenance.jsonl").open("a") as f:
            f.write(json.dumps(entry) + "\n")
    except Exception:  # noqa: BLE001 — logging must never break the run
        pass


_LOG_SINK_PIPE = "| tee "


_PIPEFAIL_PREFIX = "set -o pipefail; "


def _tool_status_not_the_log_sinks(cmd: str) -> str:
    """Make the TOOL's exit status survive a `| tee` log sink.

    Idempotent, and a no-op for every command that does not pipe into `tee`.
    """
    if _LOG_SINK_PIPE not in cmd:
        return cmd
    if cmd.lstrip().startswith(_PIPEFAIL_PREFIX.strip()):
        return cmd
    return _PIPEFAIL_PREFIX + cmd


_LOCAL_EXEC_MODE = None  # type: Optional[bool]


def _local_exec_mode() -> bool:
    """True when this process must run its EDA tools ON ITS OWN FILESYSTEM
    because there is NO route from here to a container.

    WHY THIS EXISTS. Every Phase-3 step reaches its tool through
    `docker exec <$EDA_CONTAINER> bash -lc ...` — a container this runner
    never starts and only ever enters. That is correct when the runner sits
    on the host BESIDE the image, and it is unreachable when the runner is
    ALREADY RUNNING INSIDE that image: there is no `docker` binary in there,
    so the very first tool call returns
    `127 COMMAND_NOT_FOUND: ... 'docker'` and every later step is BLOCKED on
    an artefact the first one never wrote. MEASURED 2026-09-06, subservient
    through the canonical front door (`vibe_ic_one_shot_runner.py`,
    --pdk gf180mcuD) inside ghcr.io/vibeic/vibeic-eda 0.3.46: phase1 PASS,
    phase2 PASS_WITH_WAIVERS, Phase 3 opened 15 steps and died at its first
    act with `FAIL synth rc=127 COMMAND_NOT_FOUND: 'docker'`; `yosys`,
    `openroad` and `klayout` were all on PATH in that same process
    (/foss/tools/bin/yosys, /foss/tools/bin/openroad,
    /foss/tools/klayout/klayout). The tools were under the process's own root
    the whole time; only the ACCESS ROUTE was missing.

    This is the third resolver in this file to learn the same lesson, and it
    is deliberately the same shape as the two that came before it —
    `_read_pdk_text` ("Host read first ... then the container"), which taught
    the PDK TEXT to be read in-image; this one teaches the TOOLS to run there,
    and it does so at the ONE exec seam, so no individual resolver needs a
    filesystem opinion of its own. (`_registry_glob_one` briefly had one, in
    v1.17.79; it made three declared-asset refusals stop refusing and was
    removed once this seam existed.)

    THE PREDICATE IS "NO ROUTE EXISTS", AND IT IS EXACTLY ONE QUESTION:
    is there a `docker` client on PATH? With no client there is no route to
    ANY container, whoever named it, so there is no second toolchain this
    could be choosing between — the local one is the only one that exists.

    IT IS DELIBERATELY NOT "AND NOBODY NAMED A CONTAINER". That was this
    function's first predicate and it was WRONG, measured before it shipped:
    `phase3_one_shot_runner`'s own `--container` argument DEFAULTS to
    "vibeic-eda" and `main()` publishes it unconditionally
    (`os.environ["EDA_CONTAINER"] = args.container`), so `$EDA_CONTAINER` is
    ALWAYS set by the time any step runs and the env test could never fire
    through the real front door. A default is not an operator's choice. What
    the operator's naming buys is a NAME IN THE DIAGNOSTIC, not a route —
    see `_annotate_local_exec`.

    HOST-SIDE IS UNCHANGED BY CONSTRUCTION. Every host that runs this flow
    beside a container has a docker client; there, this returns False and the
    argv below is byte-identical to what it has always been.

    DEGRADES LOUDLY, NEVER SILENTLY. The route is announced ONCE on stderr the
    first time it is decided, so every transcript records which one this run
    took; and a tool that is genuinely absent is not silently substituted —
    `bash` reports `<tool>: command not found` and `_annotate_local_exec`
    names the route. Tool/PDK/chip-AGNOSTIC: nothing here names either."""
    global _LOCAL_EXEC_MODE
    if _LOCAL_EXEC_MODE is None:
        # ONE definition of the question, shared with the OTHER way this repo
        # enters a container (`fault_atpg_run._run_docker`, a `docker run` of a
        # sibling container). A second copy here is how the two would come to
        # disagree about which route a run took.
        _LOCAL_EXEC_MODE = _cex.no_container_route()
        if _LOCAL_EXEC_MODE:
            _named = os.environ.get("EDA_CONTAINER") or "<none named>"
            print("[phase3] EXEC ROUTE = LOCAL: no docker client on PATH, so "
                  "every tool command runs on THIS filesystem. The container "
                  "named for this run (%s) was not entered and nothing was "
                  "executed in it." % _named, file=sys.stderr)
    return bool(_LOCAL_EXEC_MODE)


def _exec_argv(container: str, wrapped: str) -> List[str]:
    """The argv that runs `wrapped` in a LOGIN shell where the tools live.

    ONE seam, used by both `_docker_exec_raw` and the supervised branch of
    `_docker_exec`, so the two can never drift into disagreeing about where a
    tool runs. Container route (the default) is unchanged, `-e
    IIC_OSIC_TOOLS_QUIET=1` included.

    In local mode the `-e` cannot be passed as a docker flag, and the knob has
    to be in the ENVIRONMENT before the login shell sources
    /etc/profile.d/iic-osic-tools-setup.sh (that is where the image's startup
    banner is printed). `setdefault` reproduces exactly what `docker exec -e`
    does for the child, and leaves an operator's own value alone."""
    if _local_exec_mode():
        os.environ.setdefault("IIC_OSIC_TOOLS_QUIET", "1")
        return ["bash", "-lc", wrapped]
    # TWO DECISIONS, ONE EACH, COMPOSED HERE.
    #
    # The branch above decides WHERE a tool runs — in this image, or in a
    # container — and that is this seam's question. WHICH BYTES the container
    # holds is a different one, and it is `_container_exec.docker_exec_argv`'s:
    # a name is a label whichever process got there first is holding, and a run
    # that attaches to another run's container records provenance about the
    # wrong image. So the route is chosen here and the argv is built there, by
    # the one constructor that carries the attach check.
    #
    # The argv is UNCHANGED by that: `docker_exec_argv` puts `opts` between
    # `exec` and the container exactly where these two flags already were.
    # Local mode reaches none of this — nothing is being attached to, so there
    # is nothing to check.
    return _cex.docker_exec_argv(
        container, "bash", "-lc", wrapped,
        # The vibeic-eda image's profile prints a startup banner
        # ("[INFO] Final PATH variable: ...") to STDOUT on every LOGIN
        # shell, ahead of the command output. `IIC_OSIC_TOOLS_QUIET` is
        # the image's OWN documented knob for it
        # (/etc/profile.d/iic-osic-tools-setup.sh guards both echoes on
        # it), so suppressing at SOURCE keeps every probe's stdout
        # clean instead of filtering the noise at each consumer.
        opts=("-e", "IIC_OSIC_TOOLS_QUIET=1"))


def _annotate_local_exec(rc: int, err: str) -> str:
    """Name the route when a LOCAL run reports 127.

    Without this, `yosys: command not found` inside the image and
    `No such file or directory: 'docker'` on a host without one are two
    completely different diagnoses that a reader cannot tell apart from the
    rc alone. Bounded: one line, appended, never replacing what the shell
    said. A no-op outside local mode and for every rc but 127."""
    if rc != 127 or not _local_exec_mode():
        return err
    note = ("LOCAL_EXEC: no docker client on PATH, so this ran on THIS "
            "filesystem (container named for the run: %s, not entered); 127 "
            "means the tool is not on PATH here either — it does NOT mean a "
            "container was unreachable."
            % (os.environ.get("EDA_CONTAINER") or "<none named>"))
    return (err + ("\n" if err and not err.endswith("\n") else "") + note)


def _docker_exec_raw(container: str, cmd: str, timeout: int = 1800
                     ) -> Tuple[int, str, str]:
    """Run shell cmd inside a Docker container with a SIMPLE container-side
    wall-clock `timeout` (the pre-v1.3.47 behaviour). Used for SHORT, bounded
    probes (`command -v`, `ls`, `ps`, the identity reap) where a fixed budget
    is correct
    and for the internal watchdog kill/CPU probes (must not recurse through the
    supervisor). Long, open-ended tool runs use `_docker_exec(..., marker=...)`
    which routes through the progress-stall watchdog instead.

    ORGANIC #570 — the container-side kill fires (timeout-5)s before the host
    subprocess.TimeoutExpired so orphan processes stop writing partial files
    before the caller returns rc=124. Falls back gracefully if the container
    has no `timeout` binary. Chip-AGNOSTIC."""
    cmd = _tool_status_not_the_log_sinks(cmd)
    # ONE PRODUCER FOR THE IN-CONTAINER WRAP (vibe-ic#2099). The seven lines
    # this replaces spelled, BYTE FOR BYTE, what
    # `_docker_watchdog.wrap_with_container_timeout(cmd, timeout)` returns —
    # measured across the `max(1, …)` edges (timeout 0/1/5) and quoted commands,
    # identical on every one. Two copies of a string is one defect in two files:
    # the `--kill-after=5` escalation, the `margin_s` lead and the
    # no-`timeout`-binary fallback would each have to be edited twice, and the
    # copy that was missed would fail exactly where nobody was looking. The reap
    # and the CPU probe were already delegated to that module; this was the last
    # piece that was not.
    #
    # THIS PATH KEEPS ITS DEADLINE, AND THAT IS NOT THE THING #2051 REMOVED.
    # `_docker_exec_raw` is the SHORT, BOUNDED probe (`command -v`, `ls`, `ps`,
    # the identity reap): a fixed budget is its documented contract, and the
    # container-side deadline is what makes the host's real — without it a host
    # `subprocess.run` timeout kills only the `docker exec` CLIENT and orphans
    # the tool. What #2051 removed is the OUTER CLOCK on the SUPERVISED path,
    # where a still-converging job was SIGKILLed at a budget; that path now
    # RECORDS its ceiling and is stopped only by the progress-stall reap
    # (`supervised_container_command`, no clock). Do not "fix" this line by
    # deleting its deadline — the two paths are different contracts, and
    # `watchdog_ceiling_semantics_check` judges only the supervised one.
    _wrapped = _dwd.wrap_with_container_timeout(cmd, timeout)
    full = _exec_argv(container, _wrapped)

    # v0.2.36 — on TimeoutExpired, subprocess may hand back partial
    # `stdout`/`stderr` as BYTES even though `text=True` was requested
    # (the streams are killed mid-decode). Normalize any bytes → str so all
    # callers always receive `str`. Chip-AGNOSTIC: pure I/O-type hygiene.
    def _as_text(v) -> str:
        if v is None:
            return ""
        if isinstance(v, (bytes, bytearray)):
            return bytes(v).decode("utf-8", errors="replace")
        return v

    try:
        cp = subprocess.run(full, capture_output=True, text=True,
                            timeout=timeout)
        return (cp.returncode, _as_text(cp.stdout),
                _annotate_local_exec(cp.returncode, _as_text(cp.stderr)))
    except subprocess.TimeoutExpired as e:
        return (124, _as_text(e.stdout),
                f"TIMEOUT after {timeout}s: {e}")
    except FileNotFoundError as e:
        return 127, "", f"COMMAND_NOT_FOUND: {e}"


def _progress_paths_fn(log_path, progress_globs):
    """A per-look resolver for the child transcripts of a transaction.

    R-0915-131. Returns None when nothing was asked for, so every existing
    call site keeps byte-identical behaviour. Otherwise it returns a CALLABLE,
    because the whole point is that the set is resolved when the watchdog
    looks, not when the job launches: `sdr_child_def_leg_*.log` did not exist
    at launch, appeared four hours in, and was the only file with anything to
    say when the kill decision was taken."""
    if not progress_globs or log_path is None:
        return None
    base = Path(log_path).parent

    def _resolve():
        out = []
        for pat in progress_globs:
            try:
                out.extend(sorted(base.glob(pat)))
            except OSError:
                continue
        return out

    return _resolve


def _docker_exec(container: str, cmd: str, timeout: int = 1800, *,
                 marker: Optional[str] = None,
                 log_path: Optional[Path] = None,
                 stall_grace_s: Optional[float] = None,
                 hard_ceiling_s: Optional[float] = None,
                 poll_s: Optional[float] = None,
                 abort_probe: Optional[Callable[[], Optional[str]]] = None,
                 outputs: Optional[List[str]] = None,
                 #: R-0915-123. The TRANSIENT path(s) this call writes to and a
                 #: later statement renames or removes. Two facts used to share
                 #: `outputs=`: what the tool ATTESTS it produced, and what
                 #: ORGANIC-#570 must rename away on a stall/ceiling kill so a
                 #: half-written artefact is never read as a result. They are
                 #: not the same list -- a transient must be isolated on a kill
                 #: and must NOT be attested, because it will not exist at audit
                 #: time (ORGANIC-443). `outputs=` now means attestation only;
                 #: `isolate=` carries the transient.
                 isolate: Optional[List[Path]] = None,
                 inputs: Optional[List[Path]] = None,
                 #: R-0915-131. Glob(s), relative to `log_path`'s directory,
                 #: naming the CHILD transcripts of whatever transaction this
                 #: tool may start. The stall watchdog's progress signal is the
                 #: newest write across the parent log AND these, resolved at
                 #: every look -- a child transcript does not exist when the
                 #: parent launches. A parent that has handed the work to a
                 #: child and gone quiet is not a stall.
                 progress_globs: Optional[List[str]] = None,
                 transcript_path: Optional[Path] = None) -> Tuple[int, str, str]:
    """Run shell cmd inside a Docker container.

    DISPATCH (v1.3.47):
      • marker=None  → `_docker_exec_raw`: the simple bounded wall-clock
        `timeout` — correct for short probes (unchanged behaviour, so the ~40
        short call sites and their tests are untouched).
      • marker set   → the PROGRESS-STALL WATCHDOG (`_watchdog.run_supervised`):
        a long, open-ended tool run (PnR/route/CTS, klayout DRC, magic
        ext2spice, netgen LVS). Killed ONLY when it makes NO forward progress
        (captured output grew OR `log_path` grew OR in-container CPU advanced)
        for `stall_grace_s` (default 30 min) — a still-progressing tool runs to
        completion. `marker` is a token already present in the tool's argv (its
        script/deck path) used to sum the tool's in-container CPU until its
        identity stamp lands; the KILL selects by that stamped
        (pid, /proc starttime), never by argv.
        rc=_wd.RC_STALLED on a stall kill, 124 on the
        24h+ pathological ceiling. chip/tool-AGNOSTIC.

    `abort_probe` (optional) is the CALLER'S OWN DOMAIN read of "this job is
    progressing but going NOWHERE" -- the third kill `_watchdog` already
    implements and that nothing in this file used. It exists for the one shape
    the stall watchdog cannot see: a tool that burns a full core and emits
    NOTHING, which every generic signal reads as healthy forever. The honest
    answer for that shape is a predicate over the tool's OWN output, not a
    clock: returning a reason stops the job with rc=_wd.RC_ABORTED and the
    reason on `.err`, which is a THIRD state a reader can tell apart from both
    a hang and a natural exit. Passing nothing is byte-identical to before.
    """
    if marker is None:
        return _docker_exec_raw(container, cmd, timeout)

    grace = _WATCHDOG_STALL_GRACE_S if stall_grace_s is None else stall_grace_s
    ceiling = (_WATCHDOG_HARD_CEILING_S if hard_ceiling_s is None
               else hard_ceiling_s)
    poll = _WATCHDOG_POLL_S if poll_s is None else poll_s

    # Capture inputs BEFORE execution: hashing them afterwards could bind a
    # report to a replacement layout the tool never read.
    input_hashes = (_hash_declared_outputs(_PROV_SINK, inputs)
                    if _PROV_SINK is not None and inputs else {})
    _t0 = time.monotonic()
    # THE SHARED SUPERVISED DISPATCH, AND NO CLOCK (vibe-ic#2051, v1.18.28).
    #
    # This file used to run its own copy: it wrapped the in-container command
    # in a GNU `timeout` at the ceiling and then drove `_wd.run_supervised`
    # with hand-rolled cpu/kill closures. Two defects in one:
    #
    #   * the wrap is an OUTER WALL CLOCK. It SIGKILLs the tool at the budget
    #     however well the job is going — the thing #2051 removed, after a
    #     still-converging proof was killed at 86395 s and the flow recorded a
    #     design it had never finished comparing. `supervised_container_command`
    #     (used by the shared path) carries the identity stamp and NO clock.
    #   * a private copy of a supervised dispatch is how two files come to
    #     disagree about what stops a job. The reap and the wrap STRING were
    #     already delegated here; the DISPATCH was the last piece.
    #
    # The wrap's other purpose survives without it, measured rather than
    # assumed: `docker exec` already starts each exec in its own session, so
    # the stamping shell is ALREADY the process-group leader and the identity
    # reap signals that whole group.
    #
    # `container=""` is the NATIVE mode the shared path documents, which is
    # exactly this lane's in-image route: no container to exec into, job and
    # probes in this process's own table.
    res_rc, res_out, res_err = _dwd.run_docker_supervised(
        "" if _local_exec_mode() else container,
        _tool_status_not_the_log_sinks(cmd), marker,
        docker_exec_raw=_docker_exec_raw,
        # THE SEAM TRAVELS WITH THE DISPATCH (vibe-ic#2099). Moving this branch
        # onto the shared path at v1.18.43 left `_exec_argv` behind, so the
        # supervised entry point went back to building its own argv — losing
        # `-e IIC_OSIC_TOOLS_QUIET=1` on the container route and the
        # `IIC_OSIC_TOOLS_QUIET` default on the local one, which is precisely
        # the disagreement between the two entry points the seam was written to
        # make impossible. Injected the same way `docker_exec_raw` already is:
        # the shared dispatch stays route-agnostic, and this file keeps exactly
        # one answer to "where does a tool run".
        exec_argv=_exec_argv,
        log_path=log_path,
        progress_paths=_progress_paths_fn(log_path, progress_globs),
        stall_grace_s=grace, poll_s=poll, hard_ceiling_s=ceiling,
        term_grace_s=_WATCHDOG_TERM_GRACE_S,
        # the caller's OWN domain read, carried through rather than dropped
        abort_probe=abort_probe)
    # ORGANIC-#570, now wired into the dispatch instead of being repeated by
    # hand at each call site. A stall kill (`_RC_STALLED`) or the pathological
    # ceiling (124) leaves whatever the tool had written so far at the canonical
    # path; renaming it away is what stops a downstream step reading a
    # half-written artefact as a finished one.
    if isolate and res_rc in (_RC_STALLED, 124):
        _docker_timeout_isolate([Path(x) for x in isolate])
    if input_hashes and _hash_declared_outputs(_PROV_SINK, inputs) != input_hashes:
        res_err += (f"\nInput artifacts changed during execution (native rc={res_rc}); "
                    "the output cannot be bound to the published input.\n")
        res_rc = 1
    if transcript_path is not None:
        transcript_path.parent.mkdir(parents=True, exist_ok=True)
        transcript_path.write_text(res_out + res_err)
    _log_invocation(cmd, res_rc if res_rc is not None else -1,
                    int((time.monotonic() - _t0) * 1000), marker=marker,
                    container=container, outputs=outputs,
                    input_hashes=input_hashes)
    return res_rc, res_out, _annotate_local_exec(res_rc, res_err)


def _docker_timeout_isolate(outputs: List[Path]) -> None:
    """ORGANIC #570 — on a stall/ceiling kill (rc=_RC_STALLED / 124), rename
    partial output files away from canonical paths so downstream steps do not
    read half-written artifacts (DEF, GDS, netlist). Silently skips files that
    don't exist. Chip-AGNOSTIC: pure filesystem rename, no tool or class
    specifics. Wired into the stall-watchdog kill path (v1.3.47)."""
    for p in outputs:
        if p.is_file():
            partial = p.with_suffix(p.suffix + ".timeout.partial")
            try:
                p.rename(partial)
            except OSError:
                pass


_WATCHDOG_POLL_S = _wd.DEFAULT_POLL_S              # 30s cheap probe cadence


_WATCHDOG_STALL_GRACE_S = _wd.DEFAULT_STALL_GRACE_S  # 30 min no-progress ⇒ hung


_WATCHDOG_HARD_CEILING_S = _wd.DEFAULT_HARD_CEILING_S  # 24h pathological backstop


_WATCHDOG_TERM_GRACE_S = 10        # SIGTERM → SIGKILL escalation window


_RC_STALLED = _wd.RC_STALLED


_ASIC_TOP_MODULE_HEADER_RE = re.compile(
    r"\bmodule\s+([A-Za-z_]\w*)\s*"
    r"(?:import\s+[^;]+;\s*)*"
    r"(?:#\s*\(.*?\))?\s*\(.*?\)\s*;", re.S)


_ASIC_TOP_MODULE_BODY_RE = re.compile(
    r"\bmodule\s+([A-Za-z_]\w*)\b(.*?)\bendmodule\b", re.S)


def _strip_v_comments(text: str) -> str:
    """Remove // and /* */ comments so a module name mentioned only in a
    comment is never mistaken for a declaration or an instantiation.

    Shared: the ASIC-top resolver and `_sta_blackboxed_masters` both read
    a name out of text that may carry comments, so neither carries its own
    copy. Renamed from `_asic_top_strip_v_comments` when the second caller
    arrived — the old name asserted a scope this helper no longer has.
    Line-bounded for `//`, so stripping one line can never reach the next.
    """
    text = re.sub(r"/\*.*?\*/", " ", text, flags=re.S)
    text = re.sub(r"//[^\n]*", " ", text)
    return text


def _resolve_asic_top_structural(project: Path, top_name: str,
                                 l9_top_module: Optional[str] = None
                                 ) -> Optional[str]:
    """Resolve the synthesizable ASIC top against rtl/, mirroring phase-2's
    _v661_resolve_dut_module precedence:
      (a) --top-name when it names a real module DEFINED in rtl/;
      (b) L9.top_module when it names a real module DEFINED in rtl/;
      (c) the single instantiation-graph root among rtl/ modules (the module
          no other module instantiates — the actual synthesizable top).
    Returns None when unresolvable (no rtl/, 0 or >1 graph roots) so the caller
    keeps its legacy fallback. Never returns a name absent from rtl/. Reads only
    the (already-staged) rtl/ tree — no golden leak (§4.05)."""
    rtl_dir = _pl.rtl_dir(project)
    if not rtl_dir.is_dir():
        return None
    bodies: Dict[str, str] = {}
    defined: List[str] = []
    seen: set = set()
    for ext in (".v", ".sv"):
        for f in sorted(rtl_dir.rglob(f"*{ext}")):
            try:
                raw = _strip_v_comments(f.read_text(errors="replace"))
            except OSError:
                continue
            for m in _ASIC_TOP_MODULE_HEADER_RE.finditer(raw):
                nm = m.group(1)
                if nm and nm not in seen:
                    seen.add(nm)
                    defined.append(nm)
            for m in _ASIC_TOP_MODULE_BODY_RE.finditer(raw):
                bodies.setdefault(m.group(1), m.group(2))
    if not defined:
        return None
    defined_set = set(defined)
    # (a) orchestrator --top-name when it is a real module.
    if top_name and top_name in defined_set:
        return top_name
    # (b) L9.top_module only when it is a real module (NOT the ic_name fallback).
    if l9_top_module and l9_top_module in defined_set:
        return l9_top_module

    # (c) instantiation-graph root: the module no OTHER module instantiates.
    def _instantiated(child: str) -> bool:
        pat = re.compile(
            rf"\b{re.escape(child)}\s+(?:#\s*\([^;]*?\)\s*)?"
            rf"[A-Za-z_]\w*\s*\(")
        return any(pat.search(b) for mod, b in bodies.items() if mod != child)

    roots = [m for m in defined if not _instantiated(m)]
    if len(roots) == 1:
        return roots[0]
    return None


def _l9_top_module_hint(project: Path) -> Optional[str]:
    """Best-effort read of L9.top_module from the generated integration spec.
    Returns None on any absence / parse error (the resolver treats a phantom
    name that is not a real rtl/ module as unresolved anyway)."""
    try:
        l9 = _pl.generated_docs_dir(project) / "L9_INTEGRATION_SPEC.json"
        if l9.is_file():
            d = json.loads(l9.read_text(errors="replace"))
            if isinstance(d, dict):
                v = d.get("top_module")
                if isinstance(v, str) and v.strip():
                    return v.strip()
    except Exception:
        pass
    return None


def _runner_module():
    return sys.modules[__name__]


def _discover_pg_from_lef(
        cell_lef: Optional[str],
        metal_prefix: str = "met") -> Optional[Tuple[str, str, str, float]]:
    """Discover (power_pin, ground_pin, followpin_layer, rail_width_um) from a
    cell LEF's std-cell power/ground PINs (USE POWER / USE GROUND).

    Returns None when the LEF ships no such pins. chip-AGNOSTIC: reads the
    ACTUAL pin names + the follow-pin rail RECT height, so a commercial PDK
    whose rails are named VDD/VSS (a commercial 180nm PDK) gets a real met1
    follow-pins PDN instead of the sky130-only VPWR/VGND hardcode. Without a
    PDN the power rails are bare, unconnected metal that TritonRoute ignores
    for spacing — signal routes then land <min-space from the rails (the
    commercial-PDK M1.S.1 family). The follow-pin stripe makes the rails real routed
    PG geometry the signal router keeps 0.23 clear of.

    Picks the widest-spanning RECT under each PG pin (that IS the row rail; a
    narrow tap stub is not). Layer name returned VERBATIM (OpenROAD matches the
    tech-LEF layer name case-exactly: a commercial PDK = "MET1", sky130 = "met1").

    ROUTING-LAYER PREFERENCE (`metal_prefix`)
    -----------------------------------------
    Selecting the rail by TALLEST RECT alone is wrong for any PDK that also
    declares WELL-BIAS pins as USE POWER / USE GROUND. gf180mcu does exactly
    that: every std cell carries FOUR PG pins — VDD/VSS on `Metal1` and the
    body ties VNW/VPW on `Nwell`/`Pwell`. Measured on the shipped
    `gf180mcu_fd_sc_mcu7t5v0.lef` (cell `inv_1`):

        PIN VDD  USE POWER   LAYER Metal1  RECT height 0.60 um
        PIN VNW  USE POWER   LAYER Nwell   RECT height 2.59 um   <- taller
        PIN VSS  USE GROUND  LAYER Metal1  RECT height 0.60 um
        PIN VPW  USE GROUND  LAYER Pwell   RECT height 2.19 um   <- taller

    The well RECTs are BOTH taller than the real rails AND span the full cell
    width, so they pass the tap-stub guard and win on height. The function
    then returned ("VNW", "VPW", "Nwell", 2.59) and the PDN emitted its
    follow-pin stripes on `Nwell` — a NON-ROUTING layer. OpenROAD's detailed
    router then took SIGNAL 11 (SIGSEGV) in
    `drt::io::Parser::updateNetRouting` while reading the design, because the
    net geometry sits on a layer with no routing/via setup.

    So a PG candidate on a ROUTING-METAL layer is preferred over a taller one
    that is not, ordering by `(is_metal, height)`. `metal_prefix` is the PDK's
    own routing-layer stem, already carried on PdkConfig and in the registry
    (gf180mcu = "Metal", sky130 = "met", a commercial 180nm PDK = "MET").

    Backward-compatible: when NO candidate sits on a routing-metal layer the
    ordering degenerates to tallest-RECT, i.e. exactly the previous behaviour.
    The sky130 PDN uses a separate hard-coded branch and never reaches here."""
    if not cell_lef:
        return None
    _mp = (metal_prefix or "met").lower()

    def _is_metal(layer: Optional[str]) -> bool:
        return bool(layer) and layer.lower().startswith(_mp)
    text = _read_pdk_text(cell_lef)
    if text is None:
        return None
    power = ground = None
    pwr_layer = pwr_w = gnd_w = None
    # Selection keys: (is_metal, height). A routing-metal candidate always
    # outranks a non-routing one however tall the latter is.
    pwr_key: Optional[Tuple[bool, float]] = None
    gnd_key: Optional[Tuple[bool, float]] = None
    cur_pin = cur_use = cur_layer = None
    macro_w = None
    for raw in text.splitlines():
        s = raw.strip()
        if s.startswith("MACRO "):
            macro_w = None
            cur_pin = cur_use = cur_layer = None
            continue
        m = re.match(r"SIZE\s+([0-9.]+)\s+BY", s)
        if m:
            macro_w = float(m.group(1))
            continue
        m = re.match(r"PIN\s+(\S+)", s)
        if m:
            cur_pin = m.group(1)
            cur_use = cur_layer = None
            continue
        if s.startswith("END ") and cur_pin and s.split()[1:2] == [cur_pin]:
            cur_pin = cur_use = cur_layer = None
            continue
        if cur_pin is None:
            continue
        m = re.match(r"USE\s+(\S+)", s)
        if m:
            cur_use = m.group(1).rstrip(";").upper()
            continue
        m = re.match(r"LAYER\s+(\S+)", s)
        if m:
            cur_layer = m.group(1).rstrip(";")
            continue
        m = re.match(r"RECT\s+(-?[0-9.]+)\s+(-?[0-9.]+)\s+"
                     r"(-?[0-9.]+)\s+(-?[0-9.]+)", s)
        if m and cur_use in ("POWER", "GROUND") and cur_layer:
            x1, y1, x2, y2 = (float(g) for g in m.groups())
            xspan, h = abs(x2 - x1), abs(y2 - y1)
            # a rail spans (nearly) the whole cell width; a tap stub does not
            if macro_w and xspan < 0.8 * macro_w:
                continue
            key = (_is_metal(cur_layer), h)
            if cur_use == "POWER" and (pwr_key is None or key > pwr_key):
                power, pwr_layer, pwr_w, pwr_key = cur_pin, cur_layer, h, key
            elif cur_use == "GROUND" and (gnd_key is None or key > gnd_key):
                ground, gnd_w, gnd_key = cur_pin, h, key
    if power and ground and pwr_layer and pwr_w:
        return (power, ground, pwr_layer, round(pwr_w, 4))
    return None


_PDN_STRAP_WIDTH_X_MINWIDTH = 4.0


_PDN_STRAP_PITCH_X_LAYERPITCH = 40.0


_PDN_STRAP_MIN_PITCH_X_WIDTH = 8.0


_PDN_STRAP_OFFSET_DIV = 4.0


def _techlef_routing_layers(
        tech_lef_text: str) -> List[Tuple[str, str, float, float]]:
    """``(name, DIRECTION, PITCH_um, min WIDTH_um)`` for every ``TYPE ROUTING``
    layer in the tech LEF, in DECLARATION order — which is bottom-to-top metal
    order in every LEF this flow has seen.

    Pure LEF grammar, chip-AGNOSTIC: no layer-name convention is assumed, so a
    stack named ``met1..met5``, ``Metal1..TopMetal2`` or ``M1..M9`` all parse
    identically. ``DIRECTION`` is upper-cased, or ``""`` when the layer
    declares none. Returns ``[]`` on parse failure or empty input, which the
    callers treat as "cannot derive" rather than "nothing to do"."""
    if not isinstance(tech_lef_text, str) or not tech_lef_text:
        return []
    out: List[Tuple[str, str, float, float]] = []
    name: Optional[str] = None
    is_routing = False
    direction = ""
    pitch: Optional[float] = None
    width: Optional[float] = None

    def _flush() -> None:
        if name and is_routing and pitch and pitch > 0 and width and width > 0:
            out.append((name, direction, pitch, width))

    for raw in tech_lef_text.splitlines():
        s = raw.strip()
        m = re.match(r"^LAYER\s+(\w+)", s)
        if m:
            _flush()
            name = m.group(1)
            is_routing = False
            direction = ""
            pitch = None
            width = None
            continue
        if name is None:
            continue
        if re.match(r"^TYPE\s+ROUTING\b", s):
            is_routing = True
            continue
        m = re.match(r"^DIRECTION\s+(\w+)", s)
        if m and not direction:
            direction = m.group(1).upper()
            continue
        m = re.match(r"^PITCH\s+([\d.]+)", s)
        if m and pitch is None:
            try:
                pitch = float(m.group(1))
            except ValueError:
                pitch = None
            continue
        # A LAYER's OWN width is `WIDTH <n> ;` — one value, terminated.
        #
        # `SPACINGTABLE PARALLELRUNLENGTH` rows ALSO begin with the token
        # `WIDTH`, and they come BEFORE the layer's own declaration:
        #
        #     LAYER metal2
        #       TYPE ROUTING ;
        #       SPACINGTABLE
        #         PARALLELRUNLENGTH  0.0000  0.3000  0.9000 ...
        #           WIDTH 0.0000     0.0700  0.0700  0.0700 ...   <-- not a width
        #           WIDTH 0.0900     0.0700  0.0900  0.0900 ...   <-- not a width
        #           ...
        #       WIDTH 0.07 ;                                      <-- the width
        #       PITCH 0.19 ;
        #
        # The old `^WIDTH\s+([\d.]+)` matched the FIRST spacing-table row, and
        # `width is None` then locked that value in, so the layer's real width
        # was never read. On a table whose first row is the 0-width entry the
        # parsed width is 0.0, `_flush()`'s `width > 0` guard drops the layer
        # ENTIRELY, and the drop is silent.
        #
        # MEASURED on one shipped open PDK: 9 of its 10 routing layers were
        # discarded this way — only the one layer that declares no spacing
        # table survived. `_auto_pdn_straps_from_techlef` then saw a single
        # routing layer, correctly concluded there was nothing above the
        # follow-pin layer to strap to, and returned None; phase 3 BLOCKED the
        # PnR step with PDN_NO_STRAPS, so that PDK could not reach a GDS at
        # all and DRC/LVS never ran.
        #
        # Requiring the `;` IMMEDIATELY AFTER THE SINGLE VALUE distinguishes
        # the two unambiguously: a spacing-table row always carries another
        # number next, so it can never match. The `;` is NOT anchored to end
        # of line — two other shipped PDKs write `WIDTH 0.14 ;   # Met1 1`
        # with a trailing comment, and anchoring dropped every one of their
        # layers (measured: 6 -> 0 and 5 -> 0). Pure LEF grammar,
        # chip-AGNOSTIC.
        m = re.match(r"^WIDTH\s+([\d.]+)\s*;", s)
        if m and width is None:
            try:
                width = float(m.group(1))
            except ValueError:
                width = None
            continue
    _flush()
    return out


def _auto_pdn_straps_from_techlef(
        tech_lef_text: str,
        followpin_layer: str) -> Optional[Dict[str, Any]]:
    """Derive an upper-metal strap plan (same schema as registry
    ``pdn_straps``) from the tech LEF, so a PDK with no hand-written strap
    config still gets a CONNECTED power grid instead of isolated row rails.

    STRAPS MUST CROSS THE RAILS THEY TIE TOGETHER
    ---------------------------------------------
    The single rule that makes this work: two stripes only bond where they
    CROSS, so every ``add_pdn_connect`` pair must name layers of OPPOSITE
    ``DIRECTION``. Follow-pin rails run along the rows (the follow-pin layer's
    own direction), so the strap layer that connects DOWN to them must be
    PERPENDICULAR to that direction — a parallel strap layer never crosses a
    rail and bonds nothing.

    Measured: deriving the top two layers as ``(horizontal, vertical)`` and
    connecting ``rails(H) -> lower(H)`` put two PARALLEL layers in the same
    connect pair. ``pdngen`` reported ``PDN-0178 Remaining channel ... on
    <rail layer> for nets: VDD, VSS`` across the whole core, then ``[ERROR
    PDN-0179] Unable to repair all channels`` — it could not bond the rails
    because nothing crossed them.

    So the plan is an ALTERNATING chain from the rails upward, taking the
    HIGHEST pair that alternates:

    * upper strap ``U``, scanning from the top down;
    * lower strap ``L`` below ``U``, with ``dir(L) != dir(followpin)`` (so it
      crosses the rails) and ``dir(U) != dir(L)`` (so the two straps cross
      each other) — giving ``rails -> L -> U``, the same shape as both the
      hard-coded branch in this file and the one hand-written registry config;
    * failing that, a SINGLE strap layer perpendicular to the rails, which is
      enough to bond them even without a second layer;
    * failing that (no direction declared anywhere), the top two layers, which
      is the previous best-effort behaviour.

    ``pdngen`` builds the intervening via stack itself, so naming non-adjacent
    layers is correct.

    Returns ``None`` when NO routing layer sits above the follow-pin layer (a
    single-metal stack cannot be strapped) or when the LEF cannot be parsed.
    ``None`` means "no grid is possible here" and MUST NOT be rendered as a
    successful PDN — see `_build_pdn_tcl`, which emits the ``PDN_NO_STRAPS``
    marker in that case rather than a success marker.

    chip-AGNOSTIC: no PDK name, no layer-name convention, no absolute
    dimension — every number comes from the LEF or from the documented ratios
    above."""
    layers = _techlef_routing_layers(tech_lef_text)
    if not layers or not followpin_layer:
        return None
    names_lc = [n.lower() for n, _d, _p, _w in layers]
    try:
        fp_idx = names_lc.index(followpin_layer.lower())
    except ValueError:
        return None
    above = layers[fp_idx + 1:]
    if not above:
        return None
    fp_dir = layers[fp_idx][1]
    chosen: List[Tuple[str, str, float, float]] = []
    # Highest alternating pair: rails -> L (crosses the rails) -> U (crosses L).
    if fp_dir:
        for ui in range(len(above) - 1, 0, -1):
            u = above[ui]
            if not u[1]:
                continue
            for li in range(ui - 1, -1, -1):
                lo = above[li]
                if lo[1] and lo[1] != fp_dir and u[1] != lo[1]:
                    chosen = [lo, u]
                    break
            if chosen:
                break
        if not chosen:
            # One layer perpendicular to the rails still bonds every rail.
            for cand in reversed(above):
                if cand[1] and cand[1] != fp_dir:
                    chosen = [cand]
                    break
    if not chosen:
        # No usable DIRECTION anywhere — previous best-effort behaviour.
        chosen = above[-2:]

    stripes: List[Dict[str, Any]] = []
    for lname, _dirn, lpitch, lwidth in chosen:
        w = round(_PDN_STRAP_WIDTH_X_MINWIDTH * lwidth, 3)
        p = round(max(_PDN_STRAP_PITCH_X_LAYERPITCH * lpitch,
                      _PDN_STRAP_MIN_PITCH_X_WIDTH * w), 3)
        stripes.append({"layer": lname, "width": w, "pitch": p,
                        "offset": round(p / _PDN_STRAP_OFFSET_DIV, 3)})
    # Connect the rails to the LOWEST chosen strap that actually CROSSES them.
    # Naming a parallel layer here is what produced PDN-0178/0179.
    _down = next((c[0] for c in chosen if c[1] and c[1] != fp_dir),
                 chosen[0][0])
    connects: List[List[str]] = [[followpin_layer, _down]]
    for lower, upper in zip(stripes, stripes[1:]):
        connects.append([lower["layer"], upper["layer"]])
    return {"stripes": stripes, "connects": connects, "source": "auto:tech_lef"}


def _macro_obs_layers_from_lef(lef_text: str) -> Dict[str, Dict[str, Any]]:
    """``{master: {"blocked": {layer: total_area_um2}, "size": (w, h)}}`` — what
    each MACRO's ``OBS`` section declares unroutable, per layer. ORGANIC #685/#686.

    The planner and the follow-pin path both read a macro's ``PIN`` entries and
    NEITHER reads ``OBS``: measured, `"OBS" in inspect.getsource(...)` is False
    for both. So the flow will happily strap a layer the macro declares blocked
    across its ENTIRE footprint, and run standard-cell follow-pins straight
    through the same obstruction — 28 of 292 segments on one real routed DEF.

    `LAYER OVERLAP` is a LEF keyword, not a metal layer: it declares the macro's
    own placement extent. Recorded separately so a caller cannot mistake it for
    a routing blockage and refuse every layer.

    Pure LEF grammar, chip-AGNOSTIC. No design, PDK or vendor literal."""
    out: Dict[str, Dict[str, Any]] = {}
    if not isinstance(lef_text, str) or not lef_text:
        return out
    for mm in re.finditer(r"^\s*MACRO\s+(\S+)(.*?)^\s*END\s+\1\s*$",
                          lef_text, re.S | re.M):
        master, body = mm.group(1), mm.group(2)
        sm = re.search(r"^\s*SIZE\s+([\d.-]+)\s+BY\s+([\d.-]+)\s*;", body, re.M)
        size = (float(sm.group(1)), float(sm.group(2))) if sm else None
        blocked: Dict[str, float] = {}
        overlap = 0.0
        # OBS runs to the next section keyword, not to `END <master>`: a macro
        # may declare PINs after its OBS, and consuming to END would swallow them.
        om = re.search(r"^\s*OBS\s*$(.*?)(?=^\s*(?:PIN|END)\b)", body, re.S | re.M)
        if om:
            layer = None
            for line in om.group(1).splitlines():
                lm = re.match(r"\s*LAYER\s+(\S+)\s*;", line)
                if lm:
                    layer = lm.group(1)
                    continue
                rm = re.match(r"\s*RECT\s+([\d.-]+)\s+([\d.-]+)\s+"
                              r"([\d.-]+)\s+([\d.-]+)\s*;", line)
                if rm and layer:
                    x1, y1, x2, y2 = (float(v) for v in rm.groups())
                    a = abs(x2 - x1) * abs(y2 - y1)
                    if layer.upper() == "OVERLAP":
                        overlap += a
                    else:
                        blocked[layer] = blocked.get(layer, 0.0) + a
        out[master] = {"blocked": blocked, "size": size, "overlap_area": overlap}
    return out


def _layer_is_fully_blocked(entry: Dict[str, Any], layer: str,
                            tol: float = 0.98) -> Optional[bool]:
    """Is `layer` blocked across (essentially) the macro's whole footprint?

    None when it cannot be decided — no SIZE, or a zero-area macro. NOT False:
    a macro whose extent is unknown is one this cannot speak about, and
    answering False there is the absence-reads-as-clean shape.

    `tol` at 0.98 rather than 1.0 because an OBS is often drawn as several
    abutting rects whose union is the footprint minus rounding; requiring
    exactly 100% would report a fully-blocked layer as partially blocked."""
    size = entry.get("size")
    if not size or size[0] <= 0 or size[1] <= 0:
        return None
    area = size[0] * size[1]
    return (entry.get("blocked", {}).get(layer, 0.0) / area) >= tol


def _macro_pg_ports_from_lef(
        lef_text: str) -> List[Dict[str, Any]]:
    """``[{master, pin, use, layer, w, h}]`` — every POWER/GROUND PORT RECT of
    every MACRO in one LEF, with the rect's own width and height in um.

    The SIZE of each port is the load-bearing part: a strap PATTERN can only be
    guaranteed to cross a port whose extent across the strap exceeds the strap
    pitch, and this macro's supply ports are 0.6um in one axis. Pure LEF
    grammar, chip-AGNOSTIC."""
    out: List[Dict[str, Any]] = []
    if not isinstance(lef_text, str) or not lef_text:
        return out
    for mm in re.finditer(r"^\s*MACRO\s+(\S+)(.*?)^\s*END\s+\1\s*$",
                          lef_text, re.S | re.M):
        master, body = mm.group(1), mm.group(2)
        for pm in re.finditer(r"^\s*PIN\s+(\S+)\s*$(.*?)^\s*END\s+\1\s*$",
                              body, re.S | re.M):
            pin, pbody = pm.group(1), pm.group(2)
            use = re.search(r"^\s*USE\s+(POWER|GROUND)\s*;", pbody, re.M)
            if not use:
                continue
            layer = None
            for line in pbody.splitlines():
                lm = re.match(r"\s*LAYER\s+(\S+)\s*;", line)
                if lm:
                    layer = lm.group(1)
                    continue
                rm = re.match(r"\s*RECT\s+([\d.-]+)\s+([\d.-]+)\s+"
                              r"([\d.-]+)\s+([\d.-]+)\s*;", line)
                if rm and layer:
                    x1, y1, x2, y2 = (float(v) for v in rm.groups())
                    out.append({"master": master, "pin": pin,
                                "use": use.group(1), "layer": layer,
                                "w": abs(x2 - x1), "h": abs(y2 - y1)})
    return out


def _macro_pdn_grid_outcome(
        macro_lef_texts: Sequence[str],
        tech_lef_text: Optional[str],
        stripes: Sequence[Dict[str, Any]],
        followpin_layer: str) -> Dict[str, Any]:
    """Plan the MACRO grid — the construct that puts a conductor on a placed
    hard macro's supply pins.

    WHY THIS EXISTS
    ===============
    `pdngen` builds ONE grid per `define_pdn_grid`. The core grid straps the
    standard-cell rows; it does nothing whatever to a hard macro's own supply
    pins, because those pins are not on the rows. A macro grid is the only
    construct in OpenROAD's PDN that connects them, and this flow emitted none:
    `define_pdn_grid -macro` appeared NOWHERE in the programs tree.

    What that produced on a real run, with the macro placed FIXED and its pins
    bound BY NAME to the rails (so every claim-shaped check passed):

        [phase3] HARD-MACRO SUPPLY AUTO GLOBAL-CONNECT: 2 pin(s) bound ...
        [INFO  PDN-0001] Inserting grid: grid       <- one grid, the core's
        [WARNING PSM-0038] Unconnected shape on net <rail> at (...), layer: <pin layer>.
        [WARNING PSM-0039] Unconnected instance <inst>/<pin> at (...).
        [ERROR   PSM-0069] Check connectivity failed on <rail>.

    and, measured on the routed DEF, ZERO wire segments and ZERO vias of the
    net on the pin's own layer anywhere inside the pin rectangle. The core's
    straps ran directly OVER the macro — the metal was there, one layer up,
    with nothing bringing it down.

    THE TWO RULES THAT MAKE THE GRID LAND
    =====================================
    1. THE MACRO GRID'S STRAP MUST CROSS THE CORE'S TOP STRAP, NOT PARALLEL IT.
       Giving the macro grid straps on BOTH strap layers makes it self-
       sufficient: `pdngen` bonds macro-strap to macro-strap and never to the
       core, and the result is a fully-built ISLAND. Measured: the pins carried
       metal and the net went from 1 electrical island to 2, with the pins in
       the smaller one. Straps on ONE layer only, perpendicular to the core's
       other strap layer, leave the macro grid with nothing to bond to except
       the core — which is the point.

    2. A STRAP PATTERN ONLY REACHES A PORT WIDER THAN ITS OWN PITCH.
       Supply ports on a hard macro are often slivers at the boundary. A pitch
       is guaranteed to cross a port only when the port's extent ACROSS the
       strap is at least the pitch, and `pdngen` refuses a pitch below
       2*width+spacing, so a port narrower than that CANNOT be reached by any
       legal pattern. Those ports are reported, not silently missed.

    WHY THIS RETURNS AN OUTCOME AND NOT JUST A PLAN (#701)
    ======================================================
    Through v1.9.78 this function returned `Optional[dict]`, and `None` carried
    TWO different facts about the world:

        "this design has no hard macros"                 -> nothing to do
        "this design has a hard macro whose supply the
         grid cannot reach on any legal layer"           -> something to do,
                                                            and it was not done

    `_build_macro_pdn_grid_tcl(None)` emits the empty string for both, so the
    run's PDN note for the second case was BYTE-IDENTICAL to a macro-free
    design. Reproduced on PUBLIC sky130A material (a 1kbyte SRAM macro + the
    sky130_fd_sc_hd tech LEF): with the vendor also declaring the layers above
    the pin layer unroutable across the whole footprint — an ordinary stance
    for NVM and high-voltage macros — the planner returned None, 0 bytes of
    Tcl and an empty note, exactly like a design containing no macro at all.
    The dropped macro first surfaced several steps later as PSM-0038/0039/0069,
    where nothing tied it back to the plan that refused it.

    The `refused_for_blockage` field already existed to report precisely this,
    and could only ever be populated on the SUCCESS path: when the rule that
    removes unusable strap layers removed ALL of them, the plan was None and
    the reason was discarded before anyone could report it.

    So the return is now TOTAL — a dict, never None — and the two facts land on
    two different values:

        {"plan": <dict>, "refusals": []}       a macro grid was planned
        {"plan": None,   "refusals": []}       NOTHING TO DO: no hard-macro
                                               POWER/GROUND port exists at all
        {"plan": None,   "refusals": [rec…]}   something to do, and it could
                                               not be done — each record names
                                               the master(s), a stable machine
                                               `reason` token, and a sentence

    "Something to do" is defined as: at least one POWER/GROUND port was read
    off a macro LEF. That is the flow's own evidence that a hard macro needs
    supply, and it is the only definition available at this point.

    NOT a repair. The refusal is a REPORT — this deliberately does NOT route
    over a macro whose OBS forbids it. See `_build_macro_pdn_refusal_tcl` for
    why the refusal is loud but not fatal.

    chip-AGNOSTIC: masters, pin layers and every dimension come from the
    design's own LEFs; no PDK name, no layer-name convention, no literal."""
    ports: List[Dict[str, Any]] = []
    # #685 — the same LEF texts, read a second time for what they BLOCK.
    # Derived here rather than taken as a parameter so every existing caller
    # gets the rule without being changed; a rule only new callers get is one
    # the existing runs do not have.
    #
    # The OBS merge is NOT `dict.update`. `_macro_obs_layers_from_lef` emits a
    # record for every MACRO it finds, and a LEF that declares the macro but
    # carries no `OBS` section emits `{"blocked": {}, "size": (...), ...}` --
    # a TRUTHY record that says nothing about obstructions. Last-wins would let
    # that record erase another LEF's real blockage list, and which LEF wins is
    # decided by the order `macro_lefs` was harvested in (dedup upstream is by
    # FILE STEM, so two files declaring the same MACRO both survive it).
    #
    # `content=` is required here for exactly that reason: the emptiness is one
    # level down, in `blocked`, and the record's own truthiness cannot see it.
    #
    # `on_conflict="richer"` -- the OPPOSITE of the sibling rule in
    # `macro_obs_geometry_intersect_check.merge_macro_obs`, and deliberately.
    # That one is a BLOCKING gate, where an over-read FABRICATES a violation
    # and stops a clean design, so it takes the floor. This is a PLANNER whose
    # over-read costs a refusal record that is loud, named and explicitly
    # non-fatal (see the block comment below), while its under-read straps
    # supply straight across metal the macro declares blocked. The asymmetry
    # runs the other way, so the choice does.
    obs: Dict[str, Dict[str, Any]] = {}
    _obs_per_lef: List[Dict[str, Dict[str, Any]]] = []
    for t in (macro_lef_texts or []):
        ports.extend(_macro_pg_ports_from_lef(t))
        _obs_per_lef.append(_macro_obs_layers_from_lef(t))
    obs = _srm.merge_source_records(
        _obs_per_lef, content=lambda e: (e or {}).get("blocked"),
        on_conflict="richer")[0]
    # NOTHING TO DO — and this is the ONLY branch that may say so. Every other
    # exit below has already seen a hard-macro supply port, i.e. work the grid
    # was supposed to do.
    if not ports:
        return {"plan": None, "refusals": []}
    _masters = sorted({p["master"] for p in ports})

    def _refuse(reason: str, detail: str, *, pin_layer: str = "",
                candidates: Sequence[str] = (),
                blocked: Sequence[str] = (),
                ring_alternative: Optional[Dict[str, Any]] = None
                ) -> Dict[str, Any]:
        """One refusal record. `reason` is a STABLE machine token (grep-able,
        never reworded); `detail` is the sentence a human reads. The masters
        are named because "a macro was dropped" without a name is the same
        silence this exists to end, one step quieter."""
        return {"plan": None, "refusals": [{
            "masters": list(_masters),
            "reason": reason,
            "detail": detail,
            "pin_layer": pin_layer,
            "candidate_layers": sorted(candidates),
            "blocked_layers": sorted(blocked),
                    "ring_alternative": ring_alternative,
        }]}

    layers = _techlef_routing_layers(tech_lef_text or "")
    if not layers:
        return _refuse(
            "NO_ROUTING_LAYERS_IN_TECH_LEF",
            "the tech LEF declares no parseable TYPE ROUTING layer, so no "
            "strap layer can be chosen for the macro grid")
    order = {n.lower(): i for i, (n, _d, _p, _w) in enumerate(layers)}
    dirs = {n.lower(): d for n, d, _p, _w in layers}
    pin_layers = sorted({p["layer"] for p in ports},
                        key=lambda l: order.get(l.lower(), 10 ** 6))
    pin_layer = pin_layers[0]
    if pin_layer.lower() not in order:
        return _refuse(
            "PIN_LAYER_NOT_A_ROUTING_LAYER",
            f"the macro declares its supply pins on {pin_layer}, which the "
            "tech LEF does not declare as a TYPE ROUTING layer, so no strap "
            "can be connected down to them",
            pin_layer=pin_layer)
    pin_i = order[pin_layer.lower()]
    strap_by_layer = {s.get("layer", "").lower(): s for s in (stripes or [])
                      if s.get("layer")}
    above = [s for s in (stripes or [])
             if order.get(str(s.get("layer", "")).lower(), -1) > pin_i]
    if not above:
        return _refuse(
            "NO_CORE_STRAP_ABOVE_PIN_LAYER",
            f"no core strap layer sits above the macro supply-pin layer "
            f"{pin_layer} (core straps: "
            f"{', '.join(str(s.get('layer')) for s in (stripes or [])) or 'none'}"
            "), so the grid has nothing to drop onto the pins from",
            pin_layer=pin_layer,
            candidates=[str(s.get("layer")) for s in (stripes or [])
                        if s.get("layer")])
    above.sort(key=lambda s: order[str(s["layer"]).lower()])
    # Rule 0 (ORGANIC #685): never strap a layer the macro declares BLOCKED
    # across its whole footprint. The planner read the macro's PIN entries and
    # never its OBS — measured, `"OBS" in inspect.getsource(...)` was False —
    # so it would place a strap on a layer the macro's own LEF says is
    # unroutable there, and no gate could see it.
    #
    # Only a FULL-footprint block disqualifies a layer. A partial obstruction is
    # ordinary and a strap can route around it; refusing those would reject
    # nearly every real macro and the rule would be turned off. An UNDECIDABLE
    # macro (no SIZE) does not disqualify either — it is not evidence of a
    # block, and inventing one would fail designs this cannot speak about.
    # Two forms on purpose: the comparison is case-insensitive because LEF is,
    # but the REPORTED name keeps the LEF's own casing — a row that renames the
    # layer makes a reader hunt for something the LEF does not contain.
    _blocked_layers = set()          # as written in the LEF, for reporting
    _blocked_lc = set()              # folded, for matching
    for _e in (obs or {}).values():
        for _lay in (_e.get("blocked") or {}):
            if _layer_is_fully_blocked(_e, _lay) is True:
                _blocked_layers.add(_lay)
                _blocked_lc.add(_lay.lower())
    _refused = [s for s in above
                if str(s.get("layer", "")).lower() in _blocked_lc]
    _candidates_before_obs = [str(s.get("layer")) for s in above]
    above = [s for s in above
             if str(s.get("layer", "")).lower() not in _blocked_lc]
    if not above:
        # THE DEFECT (#701). Rule 0 just removed every remaining candidate, so
        # this macro's supply cannot be reached on ANY layer the macro itself
        # permits. Returning a bare None here made that fact indistinguishable
        # from "there are no hard macros" for every observer downstream.
        #
        # The answer is still NO GRID — routing over an OBS the vendor drew
        # across the whole footprint is not a repair, it is a violation — but
        # the REASON now travels with it.
        # The construct that DOES reach these pins, measured rather than
        # suggested (#844). A macro whose OBS blocks every layer above its pin
        # layer still exposes pin-access WINDOWS: on a real post-route project
        # the pin-layer obstruction covered 99.79% of the footprint and the
        # remaining 0.21% decomposed into 30 disjoint free regions, every one
        # touching the boundary, with every supply pin inside one at zero OBS
        # overlap. A conductor approaching from OUTSIDE the footprint lands on
        # the pin without crossing anything the vendor declared, and the detail
        # router already does exactly that for signal -- 16 of 28 signal pins
        # were reached through those same windows while 0 of 3 supply pins were.
        #
        # Measured with a boundary ring on the pin layer, same DEF, same LEFs:
        #
        #     the PDN this flow emits today      VDD 0/2   VSS 0/2
        #     + a pin-layer macro ring           VDD 0/2   VSS 2/2
        #
        # AND ITS LIMIT, which is why this is a recommendation and not an
        # automatic emission: a ring is CONCENTRIC, so two nets get two radii,
        # while every supply pin sits at the SAME depth from the edge -- that is
        # what a pin-access window IS. The inner ring lands; the outer is one
        # ring-pitch too far, and widening pushes it further out (widths 1.0,
        # 2.0, 3.0 and 4.0 give an identical answer). One ring serves ONE net.
        # The construct that serves both is a per-pin stub, which OpenROAD's PDN
        # has no primitive for -- so the honest output here is the measurement
        # and the limit, not a grid that silently powers half the macro.
        _ring = {
            "construct": "add_pdn_ring",
            "layer": pin_layer,
            "why": "the vendor's pin-access windows abut the boundary and carry "
                   "no OBS, so a conductor approaching from outside lands on the "
                   "pin without crossing anything the macro declared",
            "measured_reach": "one supply net per ring",
            "limit": "a ring is concentric and every supply pin sits at the same "
                     "depth from the edge, so the second net is one ring-pitch "
                     "short and no width or offset closes it; both nets need a "
                     "per-pin stub, which OpenROAD PDN has no primitive for",
            "not_measured": "IR drop and DRC were not run on the ring arms -- "
                            "pin coverage is a geometric statement, not a "
                            "current-carrying one",
        }
        return _refuse(
            "ALL_CANDIDATE_LAYERS_BLOCKED_BY_MACRO_OBS",
            f"every core strap layer above the supply-pin layer {pin_layer} "
            f"({', '.join(_candidates_before_obs)}) is declared blocked across "
            f"the macro's whole footprint by its own OBS, so no legal strap "
            f"can reach its supply pins. MEASURED alternative: a boundary ring "
            f"on {pin_layer} reaches the pins through the vendor's own "
            f"pin-access windows -- but a concentric ring serves ONE supply net, "
            f"because every supply pin sits at the same depth from the edge. "
            f"Both nets need a per-pin stub, which OpenROAD PDN cannot express; "
            f"see `ring_alternative` for what was measured and what was not",
            pin_layer=pin_layer,
            candidates=_candidates_before_obs,
            blocked=_blocked_layers,
            ring_alternative=_ring)
    # Rule 1: the macro's strap must have a PARTNER strap layer of the opposite
    # direction in the core plan, and the macro grid must use only one of them.
    strap = None
    partner = None
    for cand in above:
        cd = dirs.get(str(cand["layer"]).lower(), "")
        for other in (stripes or []):
            od = dirs.get(str(other.get("layer", "")).lower(), "")
            if other is cand or not od or not cd or od == cd:
                continue
            strap, partner = cand, other
            break
        if strap:
            break
    if not strap:
        return _refuse(
            "NO_PERPENDICULAR_PARTNER_STRAP",
            f"no core strap layer runs perpendicular to a usable strap above "
            f"{pin_layer} ({', '.join(str(s.get('layer')) for s in above)}), "
            "so a macro grid built here would bond only to itself and leave "
            "the macro supply on an electrical island",
            pin_layer=pin_layer,
            candidates=[str(s.get("layer")) for s in above],
            blocked=_blocked_layers)
    sw = float(strap.get("width") or 0.0)
    if sw <= 0:
        return _refuse(
            "STRAP_WIDTH_UNUSABLE",
            f"the core strap plan gives layer {strap['layer']} a width of "
            f"{strap.get('width')!r}, which cannot be rendered as a macro "
            "strap",
            pin_layer=pin_layer,
            candidates=[str(s.get("layer")) for s in above],
            blocked=_blocked_layers)
    s_dir = dirs.get(str(strap["layer"]).lower(), "")
    # min spacing of the strap layer, from the tech LEF's own WIDTH for it
    s_minw = next((w for n, _d, _p, w in layers
                   if n.lower() == str(strap["layer"]).lower()), sw)
    # R-0915-111 — THE PITCH MUST HOLD TWO STRAPS, NOT ONE. pdngen lays the
    # power and the ground strap INSIDE one pitch, so the gap it computes is
    # `pitch/2 - width`, not `pitch - 2*width`. The old floor (2*width +
    # spacing) agrees with that only while the strap is narrow, which is why
    # this held until an EM floor widened one. MEASURED on spm x gf180mcuD
    # (run10, 2026-09-21): the EM floor took Metal5 from 1.6 to 1.96 um, this
    # plan kept the 4.655 um pitch it had derived for 1.6 (old floor 3.66 <=
    # 4.655, so it looked legal), and pdngen refused the deck outright —
    #   [ERROR PDN-0108] Spacing (0.3650 um) specified for layer Metal5 is
    #   less than minimum spacing (0.4600 um)
    # = 4.655/2 - 1.96. The run swallowed that as PDN_NONFATAL and shipped a
    # design with NO special-net geometry on either supply net, which the flow
    # only noticed two steps later as PG_UNROUTED_SUPPLY, after a 143 s re-run.
    floor = round(2.0 * (sw + s_minw), 3)
    # Rule 2: the extent that matters is ACROSS the strap — the port's width
    # for a vertical strap, its height for a horizontal one.
    def _across(p: Dict[str, Any]) -> float:
        return float(p["h"] if s_dir == "HORIZONTAL" else p["w"])
    reachable = [p for p in ports if _across(p) >= floor]
    unreachable = [p for p in ports if _across(p) < floor]
    if not reachable:
        # Same silence, different cause: EVERY supply port is narrower across
        # the strap than the smallest legal pitch. The partial version of this
        # is already reported as MACRO_PDN_PORT_UNREACHABLE — but that marker
        # lives on the plan, so the total version emitted nothing at all.
        return _refuse(
            "NO_PORT_WIDE_ENOUGH_FOR_ANY_LEGAL_PITCH",
            f"every macro supply port measures less than {floor}um across the "
            f"{strap['layer']} strap direction, which is the smallest pitch "
            f"pdngen will accept for that strap — 2*(width+spacing) = "
            f"2*({sw}+{s_minw}), because the power and ground straps share one "
            f"pitch and pdngen measures their gap as pitch/2-width — so no "
            f"strap pattern can be guaranteed to cross any of them",
            pin_layer=pin_layer,
            candidates=[str(strap["layer"])],
            blocked=_blocked_layers)
    pitch = round(max(floor, min(_across(p) for p in reachable)), 3)
    return {"plan": {
        "masters": sorted({p["master"] for p in ports}),
        "pin_layer": pin_layer,
        "strap_layer": strap["layer"],
        "strap_width": sw,
        "pitch": pitch,
        "partner_layer": partner["layer"],
        "pitch_floor": floor,
        # #685 — what the macro's OBS took off the table, so a reader can tell a
        # layer that was never a candidate from one this rule removed.
        "blocked_layers": sorted(_blocked_layers),
        "refused_for_blockage": sorted({str(s.get("layer")) for s in _refused}),
        "unreachable": sorted({(p["master"], p["pin"],
                                round(_across(p), 3)) for p in unreachable}),
    }, "refusals": []}


def _load_sparse_die_skip(project: Path) -> Optional[Dict[str, Any]]:
    """Read reports/phase3/sparse_die_skip.json (the #684 attestation) if the
    runner wrote one. Returns None when absent / unparseable so consumers
    fall through to their normal (FAIL-on-zero) path. chip-AGNOSTIC."""
    try:
        p = (_pl.reports_phase3_dir(project) if hasattr(
            _pl, "reports_phase3_dir") else (project / "reports" / "phase3")
        ) / "sparse_die_skip.json"
        if p.is_file():
            data = json.loads(p.read_text(errors="replace"))
            return data if isinstance(data, dict) else None
    except Exception:
        pass
    return None


def _parse_macro_supply_pins(
        lef_text: str) -> Dict[str, List[Tuple[str, str]]]:
    """Parse a (macro) LEF and return ``{MACRO_NAME: [(pin_name, USE), ...]}``
    for every pin the LEF types ``USE POWER`` or ``USE GROUND``. USE is
    upper-cased and normalised to ``POWER``/``GROUND``. Pure-LEF grammar (same
    MACRO/PIN/USE walk as `_discover_pg_from_lef`); no PDK literal, so any
    vendor's hard macro parses. Masters with no PG pin are omitted.

    #316 salvage — THE WHOLE PIN ON ONE LINE. LEF 5.8 statements are
    ``;``-terminated, not newline-terminated, so a macro LEF may write an
    entire pin as::

        PIN IOVDD  DIRECTION INOUT ; USE POWER ; PORT ... ; END END IOVDD

    The line-oriented walk below consumed such a line at the ``PIN`` match and
    `continue`d, so the same-line ``USE`` was never read and the same-line
    ``END END IOVDD`` never closed the pin — the pin was dropped silently.
    Measured on published data: ``benchmark-data/ic/u_hawaii_adc`` stages two
    hard macros in exactly this form (``ldo`` IOVDD/VSS, ``delta_sigma``
    VDD/VSS) and this function returned ``{}`` for both, so
    `_macro_supply_gc_plan` saw ZERO supply terminals to bind or to report as
    HARDMACRO_SUPPLY_UNCONNECTED. The shared
    `hardmacro_supply_intent.lef_pg_pins` block parser reads the same file
    correctly; that discrepancy IS the defect. Delegate to it and keep the
    line walk only as the fallback, so one parser answers this question.
    """
    try:
        import hardmacro_supply_intent as _hmsi_pg  # local: shared parser
        shared: Dict[str, List[Tuple[str, str]]] = {}
        for rec in _hmsi_pg.lef_pg_pins(lef_text or ""):
            master = rec.get("master") or ""
            pin = rec.get("pin") or ""
            use = (rec.get("use") or "").upper()
            if not master or not pin or use not in ("POWER", "GROUND"):
                continue
            entry = (pin, use)
            bucket = shared.setdefault(master, [])
            if entry not in bucket:
                bucket.append(entry)
        return {k: v for k, v in shared.items() if v}
    except Exception:
        # Fall through to the inline walk so the runner never dies on an
        # import problem; the walk is a subset, never a superset.
        pass
    result: Dict[str, List[Tuple[str, str]]] = {}
    cur_macro: Optional[str] = None
    cur_pin: Optional[str] = None
    cur_use: Optional[str] = None
    for raw in (lef_text or "").splitlines():
        s = raw.strip()
        m = re.match(r"MACRO\s+(\S+)", s)
        if m:
            cur_macro = m.group(1)
            result.setdefault(cur_macro, [])
            cur_pin = cur_use = None
            continue
        if (cur_macro and s.startswith("END ")
                and s.split()[1:2] == [cur_macro]):
            cur_macro = cur_pin = cur_use = None
            continue
        if cur_macro is None:
            continue
        m = re.match(r"PIN\s+(\S+)", s)
        if m:
            cur_pin = m.group(1)
            cur_use = None
            continue
        if (cur_pin and s.startswith("END ")
                and s.split()[1:2] == [cur_pin]):
            if cur_use in ("POWER", "GROUND"):
                result[cur_macro].append((cur_pin, cur_use))
            cur_pin = cur_use = None
            continue
        if cur_pin is None:
            continue
        # LEF statements are `;`-separated and may share a line
        # (`DIRECTION INOUT ; USE POWER ;` is the common vendor form). The
        # line-anchored match missed those — found via #329's fixtures; the
        # shared hardmacro_supply_intent.lef_pg_pins already handles them.
        for stmt in s.split(";"):
            m = re.match(r"\s*USE\s+(\S+)", stmt)
            if m:
                cur_use = m.group(1).upper()
    return {k: v for k, v in result.items() if v}


@dataclass
class PdkConfig:
    name: str
    liberty: Union[str, List[str]]  # one logical library, possibly split across files
    tech_lef: str
    cell_lef: str
    cell_gds: Optional[str]
    site: str
    drc_deck: Optional[str]
    metal_prefix: str = "met"
    #: v1.15.45 (sha256 capture) — the DISTRIBUTION tech LEF a derived copy
    #: (`active_via_legalized.tlef`) was staged from. `tech_lef` may legitimately
    #: point at that copy under the project; anything that derives the PDK
    #: tree from the tech-LEF path must read this first (see _pdk_dir_of).
    tech_lef_source: Optional[str] = None
    # v0.1.46 — tap-cell master for latch-up well-tie insertion. None means
    # the PDK has no tapcell master and the tapcell step is SKIPPED. For
    # sky130_fd_sc_hd this is `sky130_fd_sc_hd__tapvpwrvgnd_1`; for other
    # PDKs the runner emits a NONFATAL skip.
    tapcell_master: Optional[str] = None
    #: vibe-ic#2360 — WHY `tapcell_master` holds its value, as stated by
    #: `_derive_tapcell_master`: a declaration (naming where), a LEF
    #: `CLASS CORE WELLTAP` finding (naming the file), or `NONE` naming the
    #: LEFs that were read and carried no such macro. None only on the
    #: hand-written named branches, whose literal is itself the declaration.
    tapcell_master_source: Optional[str] = None
    tapcell_distance_um: float = 14.0  # SKY130 latch-up rule typical
    # Antenna-repair diode cell (v0.2.14). OpenROAD `repair_antenna` inserts these
    # after detailed_route to fix process-antenna violations; None → step SKIPPED.
    antenna_diode_cell: Optional[str] = None
    # CTS clock-buffer masters carried on the PdkConfig so a NAMED open PDK
    # (nangate45 / sky130A) drives clock_tree_synthesis with its OWN buffers
    # (mirrors pdk_registry.json clk_buf_cell / clk_buf_root_cell). None →
    # step_pnr's legacy heuristic (sky130 default / custom-PDK Liberty scan).
    # Without this the nangate45 branch fed CTS a sky130 buffer name that does
    # not exist in the Nangate library → CTS_NONFATAL → CTS silently skipped.
    clk_buf: Optional[str] = None
    clk_buf_root: Optional[str] = None
    # v0.2.14 — PnR cell-exclusion file (the PDK's OWN drc_exclude.cells, i.e. the
    # PNR_EXCLUDED_CELL_FILE that OpenLane/librelane feed to OpenROAD `set_dont_use`).
    # Applied after link_design, before any resizer/CTS/repair step, so the optimizer
    # never substitutes a probe/lpflow/DRC-failed cell that TritonRoute then cannot
    # route (the root cause of [ERROR DRT-0085] when repair_design inserted
    # sky130_fd_sc_hd__probe_p_8 as a slew buffer). Reading the PDK's own file keeps
    # this general (any PDK shipping such a file works) and authoritative (identical
    # to the canonical open-source flow); None → step SKIPPED.
    pnr_exclude_cell_file: Optional[str] = None
    # Local IP macros (pdk_local/<vendor>/) — added to all backend steps
    # so hard macros (OTP, RAM, ADC, etc.) are properly integrated.
    macro_libs: List[str] = field(default_factory=list)
    macro_lefs: List[str] = field(default_factory=list)
    macro_gds:  List[str] = field(default_factory=list)
    macro_v:    List[str] = field(default_factory=list)
    # Foundry sign-off decks (Calibre / Assura / KLayout)
    calibre_drc: Optional[str] = None
    calibre_lvs: Optional[str] = None
    calibre_lvs_device: Optional[str] = None
    # v0.3.12 — ORGANIC #509 round-2: KLayout LEF/DEF reader layer-map. The
    # bare KLayout DEF reader assigns a COMPACT layer numbering (met1..met5 =
    # 10..14) instead of the foundry GDS numbers; the streamed GDS is then
    # unreadable by Magic (whose tech expects met3=70/20, met3.pin=70/16,
    # met3.label=70/5) → signoff-LVS extraction loses ALL top routing + pin
    # labels → every top port extracts disconnected. Pointing the DEF reader
    # at the PDK's own foundry layer-map (`<pdk>/libs.tech/klayout/tech/
    # <pdk>.map`) makes the GDS land on the foundry numbers Magic reads;
    # empirically validated: with this map Magic recognises all 36 top ports
    # (port indices 1..36) on the real spm GDS vs 0 before. None → keep the
    # legacy (compact) numbering (no foundry map shipped for that PDK).
    lefdef_layermap: Optional[str] = None
    # v1.3.83 — commercial-PDK sign-off bridge config (input/pdk/bridge/):
    # stdcell_marker_layer: "L/D" GDS layer painted over every std-cell
    #   instance footprint at streamout — the sign-off deck's std-cell
    #   exclusion marker (e.g. an Artisan layer) that foundry-delivered
    #   library GDS may not ship; None → nothing painted.
    # bridge_magicrc / bridge_netgen_setup: PDK-bridge Magic tech + netgen
    #   setup enabling the open-source LVS route on a commercial PDK.
    # dummy_fill: config driving the KLayout dummy-METAL fill before
    #   sign-off DRC ({"layers":[{gds,min_density,tile_um,pitch_um,
    #   margin_um},...]}); None → no fill inserted.
    stdcell_marker_layer: Optional[str] = None
    # Path to the bridge sign-off config itself. The streamout layer
    # conformance check reads it to learn which layers the flow is entitled to
    # draw on beyond the library's own (fill, tap geometry, rail markers,
    # port-label text), so those are not mistaken for un-mapped orphans.
    signoff_config_path: Optional[str] = None
    bridge_magicrc: Optional[str] = None
    bridge_netgen_setup: Optional[str] = None
    dummy_fill: Optional[Dict[str, Any]] = None
    # metal_fill_density: config driving the per-layer DENSITY-TARGETED metal
    #   fill ({"boundary_layer":[l,d],"window_um":W,"max_passes":N,"layers":
    #   [{name,layer,target,max,space,width},...]}). Distinct from dummy_fill:
    #   that lays down a fixed PATTERN, this MEASURES each layer's worst density
    #   window and iterates fill until the layer reaches its target — the number
    #   the foundry's CMP floor is actually stated in. None → no density fill.
    metal_fill_density: Optional[Dict[str, Any]] = None
    # same_net_heal: config driving the post-merge same-net routing-metal
    #   near-miss heal ({"layers":[{gds,name,max_bridge_um},...]}); each
    #   max_bridge_um MUST stay below that layer's min-space so the close can
    #   only bridge same-net gaps (see _klayout_same_net_heal). None → no heal.
    same_net_heal: Optional[Dict[str, Any]] = None
    # v1.3.91 — KLayout streamout drops top-level PORT text labels and a
    # FOLLOWPIN-only power grid is physically-disjoint rails: both make the
    # streamed GDS un-LVS-able (anonymous top nets + one net per rail). When the
    # bridge signoff config carries `port_label_restore` (truthy, optionally a
    # dict overriding text_layer / vdd_marker / vss_marker), step_gds runs a
    # post-streamout pass (def_gds_port_power_restore.py) that injects the DEF
    # PINS as text labels and paints a VDD/VSS rail MARKER per SPECIALNET
    # FOLLOWPIN segment — so the KLayout LVS extractor can name ports and unite
    # the rails by geometry. None → no-op (OSS PDKs keep native streamout).
    port_label_restore: Optional[Dict[str, Any]] = None
    # v1.3.91 — LVS engine selector. "magic" (default) = the #443 Magic
    # ext2spice + netgen route. "klayout" = geometric transistor extraction
    # (klayout_pdk_lvs.py) + netgen — the route that stays net-correct where a
    # commercial-PDK LEF-abstract collapses Magic's top extraction.
    # Config-gated so the general flow is unchanged; requires port_label_restore.
    lvs_engine: str = "magic"
    native_lvs_deck: Optional[str] = None
    native_lvs_library_translator: Optional[str] = None
    native_lvs_cell_libraries: List[str] = field(default_factory=list)
    native_lvs_parameters: Dict[str, str] = field(default_factory=dict)
    # v1.3.91 — optional PDK layer-map JSON (container/host path) for the KLayout
    # LVS engine's geometric device recognition (klayout_pdk_lvs --layermap). None
    # → the program's built-in commercial-PDK map. Chip-AGNOSTIC: any PDK supplies its own.
    lvs_layermap: Optional[str] = None
    # ROUND-3 (subservient x gf180mcuD, 2026-09-02): the via-patch legalizer
    # re-points `tech_lef` at a derived copy INSIDE THE PROJECT so every LEF
    # consumer reads one identical input. Four PDK-ROOT derivations keyed off
    # `tech_lef.find("/libs.ref/")` and silently returned "" once that path
    # moved: no min/max OpenRCX captables (the SS sign-off STA then read the
    # NOMINAL SPEF while its stance said "max-RC"), no post-route real-SPEF
    # repair ("precondition_unmet"), no seal ring, and hardmacro_gen seeing
    # PDK_ROOT ''. The ORIGINAL path is kept here so `_pdk_root_c` can still
    # find the PDK the derived copy came from.
    tech_lef_source: Optional[str] = None
    # v1.3.92 — post-route decap-under-signal-route SHORT guard. A decoupling-cap
    # filler (DECAP/DCAP/FILLCAP) whose LEF abstract omits a MET1 OBS over its
    # capacitor plate lets the router lay a signal MET1 wire across where the decap
    # later lands (filler_placement runs AFTER detailed_route); the streamed GDS
    # then SHORTS that signal to a power rail — and rail-to-rail. When truthy
    # (optionally a dict: {"rail_margin_um": 0.8, "lefs": [<override paths>]}),
    # step_pnr runs decap_route_short_guard.py on the final {top}.def, swapping each
    # conflicting decap for the same-width plain FILL cell (verified purely
    # subtractive: FILL.M1 ⊆ DECAP.M1 — drops only the plate, adds no metal). None →
    # no-op (a well-formed OSS decap LEF declares its MET1 OBS, so the router never
    # routes over it → zero conflicts anyway; gated only to keep the general flow
    # byte-for-byte unchanged). Chip-AGNOSTIC: LEF-size + DEF-routing driven.
    decap_route_short_guard: Optional[Dict[str, Any]] = None
    # v1.3.93 — TAPLESS-CELL PDK latch-up verification. Some commercial PDKs
    # (e.g. a commercial 180nm PDK) ship NO separate tapcell master: the well /
    # substrate ties are BUILT INTO every std/filler cell. For such a PDK
    # `tapcell_master` is None (the tapcell step is CORRECTLY skipped) and the
    # routed DEF carries 0 tap COMPONENTS by design — yet the design IS tapped
    # (ties are cell-internal). The DEF-component well-tap PRESENCE check would
    # then FALSE-FAIL ZERO_TAPS. When set, this config lets the latch-up check
    # VERIFY the ties by MEASURING tap DIFFUSION geometry in the sign-off GDS
    # instead: N-well tap = N+ implant inside NW (no poly over it), P-sub tap =
    # P+ implant outside NW (no poly) — exactly the __ntap__/__ptap__ a foundry
    # latch-up deck derives. Keys are "N/D" GDS specs (datatype optional):
    #   {"nwell":"2/0","nplus":"4/0","pplus":"5/0","poly":"3/0"}
    # ABSENT on a tapless PDK -> the check stays INCOMPLETE (never a fabricated
    # PASS). On a tapcell-methodology PDK (tapcell_master set) it is ignored:
    # there a 0-tap DEF is the real v0.1.45 silent break and still FAILs.
    tap_geom_layers: Optional[Dict[str, Any]] = None
    # v1.3.93 — commercial-PDK PDN vertical straps + inter-layer connects. The
    # adaptive (non-sky130) PDN path emits ONLY met1 follow-pins — per-row
    # horizontal rails with NOTHING tying the rows together, so OpenROAD PSM
    # `analyze_power_grid` reports a disconnected grid (PSM-0069) and static IR
    # cannot be computed. When set, this config adds real orthogonal straps on
    # upper metals + `add_pdn_connect` via-stacks so the rails form an
    # interconnected mesh. Shape (layer names are tech-LEF-EXACT, case-sensitive):
    #   {"stripes":[{"layer":"MET4","width":1.6,"pitch":22.4,"offset":2.24},...],
    #    "connects":[["MET1","MET4"],["MET4","MET5"]]}
    # ABSENT -> the met1-follow-pins-only PDN is emitted unchanged (a PDK with a
    # naturally-connected followpin grid, or one not yet characterised).
    pdn_straps: Optional[Dict[str, Any]] = None
    # Optional pad-connected core ring. Geometry is PDK-owned while the final
    # offset is fitted at runtime to the placed PAD-class side-cell/core gap.
    # Absence is byte-identical to the ordinary core-grid path.
    pdn_ring: Optional[Dict[str, Any]] = None
    # v1.3.93 — static-IR sign-off budget as a PERCENT of VDD. None -> the
    # plugin's documented default (10%, matching ir_drop_budget_check); set a
    # smaller value for a stricter house rule. PSM's padless-core single-bump
    # model (PSM-0073) makes the measured drop a CONSERVATIVE upper bound.
    ir_budget_pct: Optional[float] = None
    # v1.4.59 — OPT-IN cell-aware FEOL over-fire exemption for the native svrfdrc
    # sign-off engine (vibeic-eda >= 0.2.19). On a dense digital design the flat
    # std-cell qualified-cell marker cannot exempt FEOL implant space/notch
    # over-fires (routing carves it — a #511 over-waive), so the streamout's
    # anti-masking guard correctly leaves them as disclosed (gate-FAILing)
    # artifacts. The engine fork exempts them per-master (conservative: an over-
    # fire is dropped only if its bridge is strictly interior to ONE standalone-
    # qualified master's exact placed footprint AND no top-level FEOL forms it).
    # This config supplies the FEOL device layers (the safety guard) + the deck
    # rule-name prefixes to filter; the runner computes the standalone-qualified
    # master set and builds the cfg. Shape:
    #   {"feol_gds":["2/0","3/0","4/0","5/0"],
    #    "feol_rules":["NW.S","OD.S","PO.S","NP.S","PP.S"], "strict_dbu":1}
    # ABSENT (or the image lacks --cell-aware-feol) -> byte-identical stock DRC.
    cell_aware_feol: Optional[Dict[str, Any]] = None


def _macro_abstract_obs_layers(lef_path: Path) -> List[str]:
    """Layer names declared inside a macro abstract's ``OBS`` section.

    Pure LEF grammar, chip- and PDK-AGNOSTIC: no layer-naming convention is
    assumed. Returns ``[]`` when the file will not read, which callers treat as
    "cannot derive", never as "this abstract obstructs nothing"."""
    try:
        txt = lef_path.read_text(errors="ignore")
    except OSError:
        return []
    out: List[str] = []
    in_obs = False
    for raw in txt.splitlines():
        s = raw.strip()
        if re.match(r"^OBS\b", s):
            in_obs = True
            continue
        if not in_obs:
            continue
        if re.match(r"^END\b", s):
            in_obs = False
            continue
        m = re.match(r"^LAYER\s+([A-Za-z_]\w*)", s)
        if m and m.group(1) not in out:
            out.append(m.group(1))
    return out


def _pick_macro_abstract(base: str, by_n: "Dict[int, Path]",
                         routing_layers: int, notes: List[str]) -> Path:
    """Pick ONE routing-layer-keyed hard-macro abstract for the stack in force.

    A vendor that ships ``<macro>_M3.lef`` … ``<macro>_M7.lef`` is not offering
    a preference. Each variant obstructs exactly the layers a stack of that
    height must not route over the macro on, so the variant NUMBER is the
    metal-stack design choice — the same choice the tech LEF already fixes.

    This flow refuses to pick a tech LEF for the operator, on the stated ground
    that the metal stack is a design choice ("an arbitrary pick yields a fully
    green sign-off against a stack nobody chose"). Hard-preferring a fixed
    macro variant answers that same question a SECOND time, silently, and
    differently. Deriving it from the tech LEF keeps one answer in the run.

    MEASURED consequence of the fixed preference, on a real commercial-PDK
    Phase-3 run with a 5-routing-layer stack and a macro shipping ``_M3``…
    ``_M7`` (the ``_M3`` variant was loaded because the preference is fixed):

        the ``_M5`` abstract the stack calls for declares
            LAYER <m4> ; RECT <the WHOLE macro footprint> ;
            LAYER <m5> ; RECT <the WHOLE macro footprint> ;
        the loaded ``_M3`` abstract declares neither, and the router put
            42 power-stripe segments of <m4>, covering 9.3% of it
             4 power-stripe segments of <m5>, covering 4.9% of it
        over that footprint. On the one layer the loaded abstract DOES declare
        the same PDN placed 0 segments — so the router honours what it is told
        and the only reason it routed there is that it was told wrong.

    ``routing_layers == 0`` means the count could not be read; the historical
    lowest-variant pick then stands, and the guess is DISCLOSED rather than
    made to look like a derivation."""
    avail = sorted(by_n)
    shipped = ", ".join("M%d" % n for n in avail)
    if routing_layers and routing_layers in by_n:
        pick = by_n[routing_layers]
        notes.append(
            f"[macro-lef] {base}: the tech LEF in force declares "
            f"{routing_layers} routing layer(s) -> {pick.name} "
            f"(variants shipped: {shipped})")
        return pick
    if routing_layers:
        lower = [n for n in avail if n < routing_layers]
        pick = by_n[max(lower)] if lower else by_n[min(avail)]
        why = (f"this macro ships no _M{routing_layers} variant for the "
               f"{routing_layers}-routing-layer stack in force")
    else:
        pick = by_n[min(avail)]
        why = ("the routing-layer count of the tech LEF in force could not be "
               "read, so the stack this abstract has to match is UNKNOWN")
    tallest = by_n[max(avail)]
    pick_obs = _macro_abstract_obs_layers(pick)
    missing = [l for l in _macro_abstract_obs_layers(tallest)
               if l not in pick_obs]
    tail = (f" {tallest.name} obstructs {', '.join(missing)} over this "
            f"macro's footprint and {pick.name} does not, so the router is "
            f"free to route there." if missing else
            " Every variant declares the same obstruction layers, so the pick "
            "does not change what the router may route over the macro.")
    notes.append(f"[macro-lef] DISCLOSED PICK {base}: {why} — loaded "
                 f"{pick.name} of {{{shipped}}}.{tail}")
    return pick


def _discover_local_macros(
        project: Path,
        tech_lef: Optional[object] = None,
        container: Optional[str] = None) -> Tuple[
        List[str], List[str], List[str], List[str]]:
    """Discover local IP macros (input/pdk_local/<vendor>/) — hard macros
    (OTP, RAM, ADC, …) MUST be integrated into all backend steps so the
    resulting netlist + DEF + GDS hold the macro outline. chip-AGNOSTIC:
    scans common subdir names (lib, LEF, PA_GDS / GDS, Verilog).

    Hoisted out of the custom-PDK auto-detect branch so the NAMED open-PDK
    overrides (--pdk nangate45 / --pdk sky130A) integrate hard macros
    identically: the named branches previously returned early with empty
    macro lists, silently DROPPING the design's SRAM/OTP/ADC macros from
    synth blackboxing, PnR read_lef, GDS streamout and the LVS reference.

    ``tech_lef`` (a host path, a container path, or None) is read for ONE
    purpose: to count the stack's ``TYPE ROUTING`` layers, which is what
    selects a routing-layer-keyed macro abstract (``_pick_macro_abstract``).
    Omitted, that selection falls back to the historical order and SAYS SO.
    """
    macro_libs: List[str] = []
    macro_lefs: List[str] = []
    macro_gds:  List[str] = []
    macro_v:    List[str] = []
    notes: List[str] = []
    routing_layers = (len(_techlef_routing_layers(
        _read_pdk_text(str(tech_lef), container) or "")) if tech_lef else 0)
    pdk_local = project / "input" / "pdk_local"
    if pdk_local.is_dir():
        for vendor_dir in sorted(pdk_local.iterdir()):
            if not vendor_dir.is_dir():
                continue
            # Group by macro base name so we can pick exactly one
            # LEF/lib variant per macro (vendors ship multiple
            # routing-layer / corner / antenna variants and
            # loading them all causes parser collisions).
            lef_by_macro: Dict[str, List[Path]] = {}
            for sub in vendor_dir.rglob("*"):
                if not sub.is_file():
                    continue
                ext = sub.suffix.lower()
                if ext == ".lib":
                    macro_libs.append(str(sub))
                elif ext == ".lef":
                    # Strip _ant / _M<N> / _M<N>L<L> tail to get base
                    base = re.sub(
                        r"(_ant|_M\d+(L\d+)?|_top)?$",
                        "", sub.stem)
                    lef_by_macro.setdefault(base, []).append(sub)
                elif ext == ".gds":
                    macro_gds.append(str(sub))
                elif ext == ".v" and "_t" not in sub.stem:
                    # exclude *_t.v (truth-model variant)
                    macro_v.append(str(sub))
            # Per-macro LEF: the routing-layer-keyed variant the stack in
            # force calls for; otherwise the historical order, for a macro
            # that ships no such variants.
            for base, lefs in sorted(lef_by_macro.items()):
                ant = [f for f in lefs if "_ant" in f.stem]
                nonant = [f for f in lefs if "_ant" not in f.stem]
                by_n: Dict[int, Path] = {}
                for f in nonant:
                    mv = re.search(r"_M(\d+)(?:L\d+)?$", f.stem)
                    if mv:
                        by_n.setdefault(int(mv.group(1)), f)
                pick = (_pick_macro_abstract(base, by_n, routing_layers, notes)
                        if by_n else
                        ((nonant or ant)[0] if (nonant or ant) else None))
                if pick is not None:
                    macro_lefs.append(str(pick))
        # Dedup macro libs to typ-corner only when multiple corners
        # are present.
        if len(macro_libs) > 1:
            typ_only = [f for f in macro_libs
                        if "_tt" in f.lower() or "_typ" in f.lower()
                        or "_t." in f.lower()]
            if typ_only:
                macro_libs = typ_only
        for _n in notes:
            print(_n, flush=True)

    # --- C4/2026-07-31 — the flow's OWN A8-generated hard macros. ---
    # Everything above harvests `input/pdk_local/` ONLY, i.e. VENDOR IP staged
    # into the project BEFORE the run. A design whose macros are its own
    # analog blocks — which is every design the analog A1-A9 track exists for
    # — writes its LEF/lib/GDS/Verilog to `phase3/analog/hardmacro/<block>/`
    # at step A8, and nothing here ever looked there.
    #
    # MEASURED consequence on a real mixed-signal cell (2026-07-31): the tree
    # holds `phase3/analog/hardmacro/{delta_sigma,ldo}/*.{lef,lib,gds,v}`, the
    # harvester returned four empty lists, the generated `pnr.tcl` carried no
    # `read_lef` for either macro, and OpenROAD aborted with
    #     [ERROR ORD-2013] instance u_ds1 LEF master delta_sigma not found.
    # -> no routed DEF -> no GDS -> Steps 31/32/36/37 and M1 all FAIL. The
    # prior round reached PnR only because the macro `read_lef` lines had been
    # inserted by hand; neither that tree nor this one has `input/pdk_local/`
    # at all, so on a blind run this path could never have worked.
    #
    # This is the same structural shape recorded for the L21 rail synth: the
    # VENDOR-IP ordering is covered and the GENERATE-YOUR-OWN-MACRO ordering
    # is not. Strictly ADDITIVE — appends only files that exist, and only
    # for a macro not already supplied by `input/pdk_local/`, so a project
    # that stages vendor IP keeps exactly today's behaviour.
    hm_root = project / "phase3" / "analog" / "hardmacro"
    if hm_root.is_dir():
        _have = {Path(p).stem for p in macro_lefs}
        for blk in sorted(hm_root.iterdir()):
            if not blk.is_dir() or blk.name in _have:
                continue
            _lef = blk / f"{blk.name}.lef"
            if not _lef.is_file():
                _cands = sorted(blk.glob("*.lef"))
                _lef = _cands[0] if _cands else None
            if _lef is None or not _lef.is_file():
                # No abstract -> the macro cannot be placed. Say so rather
                # than silently emitting a PnR script that will abort.
                print(f"[phase3] A8 hardmacro '{blk.name}' has no .lef — "
                      f"it cannot be read into PnR; skipping (this WILL fail "
                      f"link if the netlist instantiates it)")
                continue
            macro_lefs.append(str(_lef))
            for _ext, _sink in ((".lib", macro_libs), (".gds", macro_gds),
                                (".v", macro_v)):
                _f = blk / f"{blk.name}{_ext}"
                if _f.is_file():
                    _sink.append(str(_f))
        if macro_lefs:
            print(f"[phase3] hard macros for PnR: "
                  f"{[Path(p).stem for p in macro_lefs]} "
                  f"({len(macro_libs)} lib, {len(macro_gds)} gds, "
                  f"{len(macro_v)} v)")
    return macro_libs, macro_lefs, macro_gds, macro_v


_DECLARED_PDK_ALT_SOURCE = ("phase1/generated_docs/L19_CONSTRAINTS_PDK.json",
                            ("fields", "pdk_target_alternates"))


def _read_declared_pdk_alternates(project: Path) -> List[str]:
    """Every process the DESIGN co-declares alongside its primary target.

    Phase 1 records these only when the design's own target row names more
    than one (see `_declared_pdk_alternates` there). `[]` for every design
    that names exactly one, so the guard's behaviour on those is unchanged.
    """
    rel, keys = _DECLARED_PDK_ALT_SOURCE
    try:
        doc: Any = json.loads((project / rel).read_text())
    except Exception:
        return []
    for k in keys:
        if not isinstance(doc, dict):
            return []
        doc = doc.get(k)
    if not isinstance(doc, list):
        return []
    return [d.strip() for d in doc if isinstance(d, str) and d.strip()]


def _declares_resolved_pdk(resolved: str, declared_tokens: set) -> bool:
    """Match complete registered spellings and the registry's family tokens.

    Revision tolerance applies only to an actually registered distribution;
    an explicit different revision or an arbitrary extended token is refused.
    """
    from pdk_family_identity import load_registry, normalise, family_tokens
    r = normalise(resolved)
    if not r:
        return False
    if r in declared_tokens:
        return True
    for row in load_registry().get("pdks", []):
        name = str(row.get("name") or "")
        if normalise(name) != r:
            continue
        # Family tokens come from the existing identity authority, not a
        # substring search over the input declaration.
        aliases = {normalise(t) for t in family_tokens(name)
                   if any(c.isdigit() for c in t)}
        if any(t in aliases for t in declared_tokens):
            return True
        # Preserve the established unqualified-family -> registered revision
        # direction, never infer an unregistered revision or swap revisions.
        return name[-1:].isupper() and any(
            len(r) == len(t) + 1 and r.startswith(t)
            for t in declared_tokens)
    return False


def _pdk_tokens(text: str) -> set:
    """Complete name tokens, preserving hyphens/underscores before normalising.

    A name embedded in prose remains readable; a longer connected name must
    never be split into a legitimate registered prefix plus an ignored suffix.
    """
    from pdk_family_identity import normalise
    return {normalise(t) for t in re.findall(
        r"[A-Za-z0-9]+(?:[-_.][A-Za-z0-9]+)*", text)}


def _container_file_text(container: str, path: str) -> Optional[str]:
    """PR-A1 — read a text file from the EDA container (docker exec cat)."""
    try:
        cp = subprocess.run(_cex.docker_exec_argv(container, "cat", path),
                            capture_output=True, text=True, timeout=120)
        return cp.stdout if cp.returncode == 0 else None
    except Exception:
        return None


def _read_pdk_text(path: Optional[str],
                   container: Optional[str] = None) -> Optional[str]:
    """Read a PDK asset (LEF / tech LEF / any text) that may live only
    INSIDE the EDA container.

    Every PDK-introspection helper here is handed a path like
    `/foss/pdks/<pdk>/libs.ref/.../x.lef`. That path exists in the
    container, NOT on the host, so a plain host read raises OSError. The
    helpers all caught that and returned their "nothing found" value, which
    silently disabled the feature instead of reporting a problem:

      • _discover_pg_from_lef      -> no PG pins  -> "PDN_SKIPPED: ...
                                      silicon DOA without external PDN"
      • _discover_filler_masters   -> no fillers  -> "FILLER_SKIPPED"
      • _discover_antenna_diode    -> no diode    -> antenna repair skipped

    sky130A never exposed this because each of those helpers has a
    sky130-literal shortcut that returns before the read. Measured on
    spm x ihp-sg13g2 (2026-07-21): PnR emitted ZERO PDN and zero fillers.

    Host read first (so a staged/host-local copy still wins), then the
    container. Chip- and PDK-AGNOSTIC."""
    if not path:
        return None
    if isinstance(path, (list, tuple)):
        texts = [_read_pdk_text(item, container) for item in _liberty_paths(path)]
        if not all(texts):
            return None
        return _merge_liberty_texts(texts[0], texts[1:], 'registry_library')
    try:
        return Path(path).read_text(errors="ignore")
    except OSError:
        pass
    _c = container or os.environ.get("EDA_CONTAINER")
    return _container_file_text(_c, path) if _c else None


def _merge_liberty_texts(base_text: str, group_texts: List[str],
                         lib_name: str = "merged") -> str:
    """PR-A1 — merge split Liberty group files into one ``library{}``.

    Header from ``base_text`` (library renamed), then the union of every
    top-level ``cell (...)`` block across all groups (balanced-brace
    extraction, dedup by cell name). Pure text transform — ASAP7 ships
    its RVT-TT Liberty split in 5 functional groups while the flow
    consumes ONE liberty path. Chip-AGNOSTIC."""
    import re as _re_m

    def _split_top(t: str):
        m = _re_m.search(r"^\s*cell\s*\(", t, _re_m.MULTILINE)
        if not m:
            return t, []
        header, rest = t[:m.start()], t[m.start():]
        blocks, cur, depth, started = [], [], 0, False
        for ch in rest:
            cur.append(ch)
            if ch == "{":
                depth += 1
                started = True
            elif ch == "}":
                depth -= 1
                if started and depth == 0:
                    blocks.append("".join(cur))
                    cur = []
                    started = False
        return header, blocks

    header, base_blocks = _split_top(base_text)
    header = _re_m.sub(r"library\s*\([^\)]+\)",
                       f"library ({lib_name})", header, count=1)
    seen, out = set(), []
    for b in base_blocks + [blk for t in group_texts
                            for blk in _split_top(t)[1]]:
        nm = _re_m.match(r"\s*cell\s*\(\s*([^\s\)]+)", b)
        key = nm.group(1) if nm else b[:64]
        if key not in seen:
            seen.add(key)
            out.append(b)
    return header + "\n" + "\n".join(out) + "\n}\n"


def _liberty_paths(value) -> List[str]:
    """The complete logical library; scalar callers retain their literal path."""
    if not value:
        return []
    return sorted(set(map(str, value))) if isinstance(value, (list, tuple)) else [str(value)]


def _read_liberty_tcl(value) -> str:
    return '\n'.join(f'read_liberty {path}' for path in _liberty_paths(value))


def _liberty_model_path(value, container: str = '', project: Optional[Path] = None,
                        *, corner: str = '') -> str:
    """Adapt a complete split library for an API that accepts one model file.

    Native list APIs consume the original paths. Legacy single-file tools
    receive every cell in a content-addressed union, never a selected group.
    Single-file inputs are returned verbatim, without staging or rewriting.
    """
    paths = _liberty_paths(value)
    if len(paths) < 2:
        return paths[0] if paths else ''
    import hashlib
    import tempfile

    text = _read_pdk_text(paths, container)
    if text is None:
        raise ValueError(f'PDK_LIBERTY_UNRESOLVED: {paths}')
    identity = hashlib.sha256(('\0'.join(paths) + '\0' + text).encode()).hexdigest()
    directory = (Path(project) / 'phase3/pdk_stage' if project is not None else
                 Path(tempfile.gettempdir()) / 'vibeic-liberty-bundles')
    directory.mkdir(parents=True, exist_ok=True)
    prefix = f'corner_{corner}-' if corner else ''
    target = directory / f'{prefix}library-{identity}.lib'
    if not target.is_file():
        with tempfile.NamedTemporaryFile(mode='w', dir=directory, delete=False) as staged:
            staged.write(text)
        os.replace(staged.name, target)
    return str(target)


_V1_6_596_TIE_HI_PAT = re.compile(
    r"(?:^|_)(?:conb|conp|tiehi|tie_hi|tieh|tiep|logic1)(?:[_x]?\d|_|$)",
    re.IGNORECASE,
)


_V1_6_596_TIE_LO_PAT = re.compile(
    r"(?:^|_)(?:conb|conp|tielo|tie_lo|tiel|tien|logic0)(?:[_x]?\d|_|$)",
    re.IGNORECASE,
)


_V1_6_596_RE_CELL_DECL = re.compile(
    r'^\s*cell\s*\(\s*"?([A-Za-z_][A-Za-z0-9_]*)"?\s*\)',
    re.MULTILINE,
)


READ_REFUSED = "READ_REFUSED"


def read_text_or_container_cat(path: str, container: str = ""
                               ) -> Tuple[Optional[str], str]:
    """Read host text first, then try the container and report native read errors."""
    host_why = ""
    try:
        return Path(path).read_text(errors="ignore"), ""
    except Exception as exc:                       # noqa: BLE001 — classified
        host_why = f"host read of {path} failed: {type(exc).__name__}"
    if not container:
        return None, f"{host_why}, and no container was named to read it from"
    argv = _cex.docker_exec_argv(container, "cat", path)
    try:
        r = subprocess.run(
            argv, capture_output=True, text=True, timeout=30,
            errors="ignore",
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return None, (f"{READ_REFUSED}: {host_why}, and `docker exec "
                      f"{container} cat` could not be run: "
                      f"{type(exc).__name__}: {exc}")
    except Exception as exc:                       # noqa: BLE001 — never unhandled
        return None, (f"{READ_REFUSED}: {host_why}, and reading it from "
                      f"container {container} raised "
                      f"{type(exc).__name__}: {exc}")
    if r.returncode == 0:
        return r.stdout, ""
    return None, (f"{host_why}, and `docker exec {container} cat {path}` "
                  f"exited {r.returncode}")


def _v1_6_604_read_text_or_container_cat(
        path: str, container: str = "") -> Optional[str]:
    """v1.6.604 — Try host read first; fall back to
    `docker exec <container> cat <path>` when the path lives only
    inside the container. Returns None when both fail. Chip-AGNOSTIC.

    The fourteen callers of this name want the text, so the shape is unchanged.
    What changed (vibe-ic#2156) is that a read which was REFUSED rather than
    merely empty now SAYS SO, once, on stderr — a refusal that reaches nobody is
    the same defect as a refusal that was swallowed. An ordinary "it is not
    there" stays quiet; ask `read_text_or_container_cat` when the reason
    matters to the caller.
    """
    text, why = read_text_or_container_cat(path, container)
    if text is None and why.startswith(READ_REFUSED):
        print(f"[NOT_MEASURED] {why}", file=sys.stderr)
    return text


def _v1_6_596_discover_tie_cells(liberty_path: Union[str, List[str]],
                                 container: str = "") -> dict:
    """v1.6.596 — for #404 P3 ORGANIC. Scan `liberty_path` for tie-hi
    and tie-lo cells. Returns a dict with keys:

      `hi_cell`  — name of the tie-high cell (or None)
      `lo_cell`  — name of the tie-low cell (or None)
      `hi_pin`   — output-pin name of the tie-high cell (default 'HI')
      `lo_pin`   — output-pin name of the tie-low cell (default 'LO')

    Conservative on parse error / missing file → returns
    `{hi_cell: None, lo_cell: None, ...}` so the caller can fall
    back to non-hilomap synth flow. Chip-AGNOSTIC: scans liberty
    cell-name vocabulary only.

    v1.6.604 — accepts an optional `container` argument; when the
    host has no copy of the liberty (e.g. /foss/pdks/sky130A inside
    the iic-osic-tools docker) it falls back to `docker exec cat`
    via `_v1_6_604_read_text_or_container_cat`.
    """
    out = {"hi_cell": None, "lo_cell": None,
           "hi_pin": "HI", "lo_pin": "LO"}
    text = (_read_pdk_text(liberty_path, container)
            if isinstance(liberty_path, (list, tuple)) else
            _v1_6_604_read_text_or_container_cat(liberty_path, container))
    if text is None:
        return out
    cellnames = _V1_6_596_RE_CELL_DECL.findall(text)
    if not cellnames:
        return out
    # Sky130-style: conb_1 is the dual tie cell (HI + LO outputs);
    # conp_1 also exists in some variants. For other PDKs split into
    # separate tie_h / tie_l cells. Use the first match for each.
    for nm in cellnames:
        n_lc = nm.lower()
        # conb_X is the canonical sky130 dual-output tie cell — use
        # for both HI and LO. Prefer it when seen.
        if "conb" in n_lc:
            if out["hi_cell"] is None:
                out["hi_cell"] = nm
            if out["lo_cell"] is None:
                out["lo_cell"] = nm
            continue
        if _V1_6_596_TIE_HI_PAT.search(n_lc) and out["hi_cell"] is None:
            # Avoid matching tie-low patterns (the `lo` token would
            # also match _V1_6_596_TIE_HI_PAT if loosely written).
            if not _V1_6_596_TIE_LO_PAT.search(n_lc) or "hi" in n_lc:
                out["hi_cell"] = nm
        if _V1_6_596_TIE_LO_PAT.search(n_lc) and out["lo_cell"] is None:
            if not _V1_6_596_TIE_HI_PAT.search(n_lc) or "lo" in n_lc:
                out["lo_cell"] = nm
    # Sniff output-pin names from the chosen cell block. When the
    # same cell is used for both HI and LO (sky130 conb_1 dual-output),
    # we need both pin names; gather all pins in the block and select
    # the HI-like and LO-like ones by name vocabulary.
    #
    # When the cells are different (separate tie_h / tie_l), the first
    # `pin (X)` declaration is the (only) output for each cell.
    same_cell = (out["hi_cell"] is not None
                 and out["hi_cell"] == out["lo_cell"])
    cells_handled = set()
    for key, default_pin in (("hi_cell", "HI"), ("lo_cell", "LO")):
        if out[key] is None:
            continue
        cell_name = out[key]
        if cell_name in cells_handled:
            # Already processed (same_cell path picks both pins below)
            continue
        cells_handled.add(cell_name)
        block_re = re.compile(
            r"cell\s*\(\s*" + re.escape(cell_name) + r"\s*\)\s*\{",
            re.IGNORECASE,
        )
        m = block_re.search(text)
        if not m:
            out[key.replace("cell", "pin")] = default_pin
            continue
        # Walk forward to find pin declarations. Cap window at 4KB
        # so we don't scan the entire liberty.
        window = text[m.end(): m.end() + 4096]
        # v1.6.598 — for #404 R2. The prior regex matched the
        # literal `pin` substring inside `pg_pin(VDD)` because no
        # word-boundary anchor preceded it. Real PDK Liberty
        # files always declare power/ground rails via
        # `pg_pin(VDD)` / `pg_pin(VSS)` BEFORE the signal pins,
        # so the discoverer locked on `VDD` (a power input rail)
        # instead of the true output pin (`Z` / `ZN` / `Y`).
        # Negative lookbehind on identifier characters fixes it.
        # Chip-AGNOSTIC: pure Liberty grammar fix; no chip-class
        # literal.
        pin_names = re.findall(
            r"(?<![A-Za-z_])pin\s*\(\s*([A-Za-z_][A-Za-z0-9_]*)\s*\)",
            window)
        if not pin_names:
            continue
        if same_cell:
            # Dual-output tie cell — pick the HI-named pin and the
            # LO-named pin by vocabulary. Fall back to first/second
            # pin if names are non-standard.
            hi_named = [p for p in pin_names
                        if re.search(r"\b(hi|h|p|pwr|vdd|one)\b",
                                     p, re.IGNORECASE)]
            lo_named = [p for p in pin_names
                        if re.search(r"\b(lo|l|n|gnd|vss|zero)\b",
                                     p, re.IGNORECASE)]
            if hi_named:
                out["hi_pin"] = hi_named[0]
            elif pin_names:
                out["hi_pin"] = pin_names[0]
            if lo_named:
                out["lo_pin"] = lo_named[0]
            elif len(pin_names) > 1:
                out["lo_pin"] = pin_names[1]
            elif pin_names:
                out["lo_pin"] = pin_names[0]
        else:
            # Single-output cell — first pin is the output.
            out[key.replace("cell", "pin")] = pin_names[0]
    return out


_ORFS_PNR_KNOB_PARAMS: Dict[str, Tuple[str, ...]] = {
    # floorplan geometry — the die the auto-sizer targets and how tightly
    # global placement packs the core.
    "CORE_UTILIZATION":       ("die_target_util", "place_density"),
    "FP_CORE_UTIL":           ("die_target_util", "place_density"),
    "PLACE_DENSITY":          ("place_density",),
    "PLACE_DENSITY_LB_ADDON": ("place_density",),
    # optimization inside whatever floorplan the flow chose.
    "TNS_END_PERCENT":        ("repair_tns_percent",),
    # ── the AREA CEILING on what fixing timing may cost (step 32) ────────────
    # Ported from LibreLane, whose `PL_RESIZER_*_MAX_UTIL_PCT` family is the
    # timing-versus-area trade made ADJUSTABLE instead of hard-coded. Step 32
    # repaired timing with NO area ceiling whatsoever before this: OpenROAD's
    # `repair_timing` accepts `-max_utilization util` and we passed it never.
    #
    # MEASURED in the pinned image (`docker run --skip`, OpenROAD
    # 26Q3-1535-g543c33894f), because the port has to match the TOOL and not a
    # remembered flag list:
    #   repair_timing [-setup] [-hold] [-recover_power percent_of_paths_with_slack]
    #      ... [-max_utilization util] ...
    #   repair_design [-max_wire_length ...] [-max_utilization util] ...
    # There is ONE `-max_utilization` in OpenROAD, not two. LibreLane's two
    # names are its own FLOW-level split — it passes the same tool flag with a
    # different value to the `-setup` call and to the `-hold` call — so these
    # two knobs map to two flow parameters that reach two invocations, which is
    # exactly the shape asked for, arrived at from the tool.
    #
    # These are OPTIMIZATION-class knobs, not routing-resource-supply ones: they
    # BOUND how much area the repair may consume inside whatever floorplan
    # phase 3 chose for itself. They do not replace a self-calibrated quantity,
    # so `_RF_ROUTING_SUPPLY_PARAMS` does not withhold them.
    #
    # NO DEFAULT IS INVENTED. Undeclared means the repair stays unbounded, i.e.
    # today's behaviour exactly — and the audit trail then SAYS SO, which it
    # could not before. A ceiling nobody declared would be a ruler fitted to the
    # answer, and this repository already carries the worked example of why
    # (`matrix_mutation_ledger.ART-POWER-FIGURES-X1000`).
    "PL_RESIZER_SETUP_MAX_UTIL_PCT": ("resizer_setup_max_util_pct",),
    "PL_RESIZER_HOLD_MAX_UTIL_PCT":  ("resizer_hold_max_util_pct",),
    # SURPLUS slack spent on power, in the tool. `-recover_power` takes a
    # PERCENT OF THE PATHS THAT HAVE SLACK, so it acts only where slack already
    # exists; it is the one PPA move here that is not a trade. It has no
    # LibreLane spelling, so the knob name is ours and it is declared the same
    # way — and it stays OFF unless declared, for the reason in the paragraph
    # above and one more: no full place-and-route run was made to measure its
    # effect on this flow's own designs, so defaulting it ON would be shipping
    # an unmeasured behaviour change to every design at once.
    "RESIZER_RECOVER_POWER_PCT":     ("recover_power_pct",),
    "CTS_CLUSTER_SIZE":       ("cts_cluster_size",),
    "CTS_CLUSTER_DIAMETER":   ("cts_cluster_diameter",),
    "CTS_DISTANCE_BETWEEN_BUFFERS": ("cts_distance_between_buffers",),
}


_RF_ROUTING_SUPPLY_PARAMS = frozenset({"die_target_util", "place_density"})


_ORFS_WITHHELD_PNR_KNOBS = frozenset(
    k for k, params in _ORFS_PNR_KNOB_PARAMS.items()
    if _RF_ROUTING_SUPPLY_PARAMS.intersection(params))


_ORFS_KNOB_SUBSYSTEM: Dict[str, str] = {}


_ORFS_HONOURED_ELSEWHERE_KNOBS = frozenset(
    k for k, sub in _ORFS_KNOB_SUBSYSTEM.items() if sub != "pnr")


def _area_receipt_flags(area_receipt: Optional[str],
                        area_run_manifest: Optional[str]) -> List[str]:
    """Return only the explicitly declared producer-evidence argv pair."""
    if bool(area_receipt) != bool(area_run_manifest):
        raise ValueError("--area-receipt and --area-run-manifest must be supplied together")
    if not area_receipt:
        return []
    return ["--area-receipt", str(area_receipt),
            "--area-run-manifest", str(area_run_manifest)]


_L9_DIE_AREA_RECT_RE = re.compile(
    r"DIE_AREA\b[)\s:=|({}'\"`\[]{0,8}"
    r"(-?\d+(?:\.\d+)?)[\s,]+(-?\d+(?:\.\d+)?)[\s,]+"
    r"(-?\d+(?:\.\d+)?)[\s,]+(-?\d+(?:\.\d+)?)",
    re.IGNORECASE)


_L9_DIE_WIDTH_RE = re.compile(
    r"DIE_WIDTH`?\s*[:=|]\s*\*{0,2}\s*(\d+(?:\.\d+)?)\s*(?:um|µm)?",
    re.IGNORECASE)


_L9_DIE_HEIGHT_RE = re.compile(
    r"DIE_HEIGHT`?\s*[:=|]\s*\*{0,2}\s*(\d+(?:\.\d+)?)\s*(?:um|µm)?",
    re.IGNORECASE)


def _l9_declared_die_area(project: Optional[Path]) -> Optional[str]:
    """Return an L9-MANDATED fixed die as a 'WxH' string (integer µm), or None
    when L9 declares no explicit fixed DIE_AREA. Reads ONLY the L9 constraints/
    floorplan doc (input docs or the generated L9) — a blind-legal design input.

    Prefers the canonical `DIE_AREA` rect (llx lly urx ury → W=urx-llx,
    H=ury-lly); else an unambiguous `DIE_WIDTH` + `DIE_HEIGHT` pair. Only a real,
    positive numeric declaration counts (§4.05 / no-fabricate). chip-AGNOSTIC."""
    if project is None:
        return None
    roots = [project / "input" / "docs", _pl.generated_docs_dir(project)]
    for root in roots:
        if not root.is_dir():
            continue
        for p in (sorted(root.glob("L9*")) + sorted(root.glob("*constraint*"))
                  + sorted(root.glob("*floorplan*"))):
            try:
                txt = p.read_text(errors="ignore")
            except OSError:
                continue
            # Prefer the canonical DIE_AREA rect (llx lly urx ury).
            for m in _L9_DIE_AREA_RECT_RE.finditer(txt):
                try:
                    llx, lly, urx, ury = (float(m.group(i)) for i in (1, 2, 3, 4))
                except ValueError:
                    continue
                w, h = urx - llx, ury - lly
                if w > 0 and h > 0:
                    return f"{int(round(w))}x{int(round(h))}"
            # Else an explicit DIE_WIDTH + DIE_HEIGHT pair (both required).
            mw = _L9_DIE_WIDTH_RE.search(txt)
            mh = _L9_DIE_HEIGHT_RE.search(txt)
            if mw and mh:
                try:
                    w, h = float(mw.group(1)), float(mh.group(1))
                except ValueError:
                    w = h = 0.0
                if w > 0 and h > 0:
                    return f"{int(round(w))}x{int(round(h))}"
    return None


_L19_DIE_WXH_RE = re.compile(r"^\s*(\d+)\s*[xX]\s*(\d+)\s*$")


def _l19_declared_die_area(project: Optional[Path]) -> Optional[str]:
    """G-FIXED-DIE-1 — return the phase1-extracted mandated die as a 'WxH'
    string from L19.fields.die_area_budget_um, or None.

    phase1's floorplan-contract ingest (`_post_emit_floorplan_contract`) lands
    the design-MANDATED die here from an OpenLane ``config.json`` DIE_AREA
    AND/OR L9 prose. Consuming L19 closes the case where a design ships the
    fixed die ONLY through its OpenLane config (no prose rect) —
    `_l9_declared_die_area` (prose-only) would miss it, so phase3 would auto-
    size a die the design had already fixed. Only a real, positive 'WxH'
    counts (§4.05 / no-fabricate). chip-AGNOSTIC."""
    if project is None:
        return None
    try:
        p = _pl.generated_docs_dir(project) / "L19_CONSTRAINTS_PDK.json"
        if not p.is_file():
            return None
        doc = json.loads(p.read_text(errors="ignore"))
    except Exception:
        return None
    if not isinstance(doc, dict):
        return None
    fields = doc.get("fields")
    if not isinstance(fields, dict):
        return None
    val = fields.get("die_area_budget_um")
    if not isinstance(val, str):
        return None
    m = _L19_DIE_WXH_RE.match(val)
    if not m:
        return None
    w, h = int(m.group(1)), int(m.group(2))
    if w > 0 and h > 0:
        return f"{w}x{h}"
    return None


def _spare_insertion_provenance(spare_plan: Dict[str, Any],
                                 wrapper: Path) -> Optional[Dict[str, Any]]:
    """Bind optional insertion intent to the actual wrapper the runner read.

    The cell insertion producer owns every `instances` obligation. A wrapper
    can establish optional names, but cannot cancel those cell obligations.
    Missing source is unknown, never evidence that a planned name was omitted.
    """
    import hashlib
    required = [str(i["name"]) for i in spare_plan.get("instances", []) or []
                if isinstance(i, dict) and i.get("name")]
    optional = [str(i["name"]) for i in spare_plan.get("spare_pads", []) or []
                if isinstance(i, dict) and i.get("name")]
    if not spare_plan.get("spare_pads"):
        return None  # No optional insertion claim needs a wrapper witness.
    result = {"version": 1, "status": "UNVERIFIED",
              "required_insertions": required, "planned_not_inserted": [],
              "wrapper": {"path": str(wrapper), "read_status": "UNREADABLE"}}
    try:
        with wrapper.open("rb") as stream:
            raw = stream.read(8 * 1024 * 1024 + 1)
        text = raw.decode("utf-8")
        if not text.strip() or len(raw) > 8 * 1024 * 1024:
            raise ValueError("empty or truncated wrapper")
        text = re.sub(r'"(?:\\.|[^"\\])*"|//[^\n]*|/\*.*?\*/', ' ', text,
                      flags=re.S)
        if not re.search(r"\bmodule\b.*\bendmodule\b", text, re.S):
            raise ValueError("wrapper has no complete module")
    except (OSError, ValueError) as exc:
        result["reason"] = str(exc)
        return result
    tokens = set(re.findall(r"[A-Za-z_][A-Za-z0-9_$]*", text))
    result.update(status="OBSERVED",
                  required_insertions=required + [n for n in optional if n in tokens],
                  planned_not_inserted=[n for n in optional if n not in tokens])
    result["wrapper"].update(read_status="READ",
                             sha256=hashlib.sha256(raw).hexdigest())
    return result


def _spare_safe_clear_net_proc_tcl() -> str:
    """The ONE decision every routing-clear site in this runner makes, as a Tcl
    proc — and the only place `odb::dbWire_destroy` is written.

    WHY A PROC AND NOT A SECOND COPY OF THE FILTER. Until this landed there
    were two: `_spare_safe_routing_clear_tcl` (clear every signal net) and the
    NAMED_VIOL_REROUTE loop in `_named_violation_reroute_tcl` (clear only the
    nets the router's own DRC report cites), which re-typed the SAME two
    protections in place — skip POWER/GROUND, skip any net touching a
    `isDoNotTouch` instance. Two copies of one rule drift, and the v1.5.65
    post-mortem is what drift costs here: a clear that let the spare-tie nets
    (`spare_tielo`/`spare_tiehi`, the Design-for-ECO spare-input bindings) go
    unrouted, after which the rerouter merged them into `la_data_out` /
    `user_irq` — a real LVS mismatch.

    The two loops differ ONLY in which nets they walk, so the loop stays with
    the caller and the DECISION comes from here. It returns a word rather than
    a boolean because the callers count three different outcomes and their log
    lines must not change:

        PG         POWER/GROUND — never counted by either caller
        PROTECTED  a dont_touch instance is on the net; its route is pinned
        UNROUTED   nothing to destroy
        CLEARED    the wire was destroyed

    The `*spare*` NAME filter is NOT here: v1.8.43 removed it because
    preserving one net's stale detailed routing across a global re-route broke
    `detailed_route` (DRT-0206) while protecting nothing —
    `odb::dbWire_destroy` destroys a WIRE, never the net or its iterms, so the
    DEF NETS terminal list that IS the ECO binding is untouched. Its
    replacement is the post-reroute `_routing_integrity_check_tcl`, which is
    why that check is now emitted after EVERY reroute and not only after the
    shipped-signoff one.

    Redefining a proc is idempotent in Tcl, so every emitter may prepend this
    without knowing whether another already did.

    chip-AGNOSTIC: odb API only; no PDK, layer, vendor or design literal.
    """
    return (
        "proc _vibeic_spare_safe_clear_net {_n {_drop_protected 0}} {\n"
        "  set _st [$_n getSigType]\n"
        "  if {$_st eq \"POWER\" || $_st eq \"GROUND\"} { return PG }\n"
        # `_drop_protected` is the ONE exception to the dont_touch skip, and it
        # is passed IN rather than re-implemented: a restored session whose
        # next act is a full clear + global_route + detailed_route must be able
        # to drop a DEF-round-tripped wire the router refuses (DRT-1010,
        # MEASURED on the spare tie-off nets), and a second copy of this filter
        # is exactly what this proc exists to prevent. The PG skip is NOT
        # optional and stays above, so no caller can reach supply wiring.
        "  if {!$_drop_protected} {\n"
        "    foreach _it [$_n getITerms] {\n"
        "      if {[[$_it getInst] isDoNotTouch]} { return PROTECTED }\n"
        "    }\n"
        "  }\n"
        "  set _w [$_n getWire]\n"
        "  if {$_w eq \"NULL\"} { return UNROUTED }\n"
        "  odb::dbWire_destroy $_w\n"
        "  return CLEARED\n"
        "}\n"
    )


def _terminal_contact_helpers_tcl() -> str:
    """Placed terminal shapes and same-layer contact for existing audits."""
    return (
        # Shapes of ONE terminal as {layer x0 y0 x1 y1} records. Empty list ==
        # "could not look", which the caller must not read as "no overlap".
        "proc _vibeic_term_shapes {_t _kind} {\n"
        "  set _out {}\n"
        "  if {$_kind eq \"I\"} {\n"
        "    if {[catch {set _gs [$_t getGeometries]}]} { return {} }\n"
        "    foreach _g $_gs {\n"
        "      if {[catch {\n"
        "        lassign $_g _ly _rc\n"
        "        lappend _out [list [$_ly getName] [$_rc xMin] [$_rc yMin] "
        "[$_rc xMax] [$_rc yMax]]\n"
        "      }]} { continue }\n"
        "    }\n"
        "  } else {\n"
        "    if {[catch {set _bps [$_t getBPins]}]} { return {} }\n"
        "    foreach _bp $_bps {\n"
        "      if {[catch {set _bxs [$_bp getBoxes]}]} { continue }\n"
        "      foreach _b $_bxs {\n"
        "        if {[catch {\n"
        "          lappend _out [list [[$_b getTechLayer] getName] [$_b xMin] "
        "[$_b yMin] [$_b xMax] [$_b yMax]]\n"
        "        }]} { continue }\n"
        "      }\n"
        "    }\n"
        "  }\n"
        "  return $_out\n"
        "}\n"
        # Two terminals touch when ANY pair of their shapes overlaps ON THE SAME
        # layer. Same-layer is the load-bearing half: two rectangles that share
        # an (x,y) footprint on different layers are not connected.
        "proc _vibeic_shapes_touch {_a _b} {\n"
        "  foreach _p $_a {\n"
        "    lassign $_p _pl _px0 _py0 _px1 _py1\n"
        "    foreach _q $_b {\n"
        "      lassign $_q _ql _qx0 _qy0 _qx1 _qy1\n"
        "      if {$_pl ne $_ql} { continue }\n"
        "      if {$_px1 < $_qx0 || $_qx1 < $_px0} { continue }\n"
        "      if {$_py1 < $_qy0 || $_qy1 < $_py0} { continue }\n"
        "      return 1\n"
        "    }\n"
        "  }\n"
        "  return 0\n"
        "}\n"
    )


def _routing_integrity_check_tcl(marker_prefix: str = "SHIP",
                                 membership_path: Optional[str] = None,
                                 stage: Optional[str] = None,
                                 supply_only: bool = False,
                                 ) -> str:
    """v1.8.43 — POST-REROUTE routing-integrity CHECK. Emits
    ``<PFX>_UNROUTED_NETS: <n> <up to 12 names>``.

    This is the replacement protection for the *spare* name filter removed from
    :func:`_spare_safe_routing_clear_tcl`, and it is the DIRECT check for the
    v1.5.65 hazard (a spare-tie net that comes back with no wire, whose pins
    extraction then merges into neighbours -> LVS mismatch). A net that has two
    or more terminals and no wire after `detailed_route` is unrouted, whatever
    its name. Counting it makes the failure mode observable and lets the
    promotion gate REFUSE such a route instead of shipping it.

    chip-AGNOSTIC: odb API only, no name/vendor/SKU literal, no design literal.
    NONFATAL-guarded — a probe that cannot run must never kill the step, and it
    reports that it could not run rather than reporting zero (UNMEASURED is not
    ZERO).

    A WIRE IS NOT THE ONLY WAY TWO TERMINALS ARE CONNECTED. The rule above --
    "two or more terminals and no wire" -- reads a net that needs no wire as a
    net that failed to get one. The standard case is the chip path: a top-level
    DEF PIN is FIXED directly on the pad cell's own PAD terminal, on the same
    layer, and the two shapes ARE the connection. MEASURED, spm x gf180mcuD,
    36-pad ring, phase3/stage3/pnr/routed.def -- the old body counts 36 and the
    design has no unrouted net at all; OpenROAD reports the BTerm bbox and the
    ITerm bbox as the SAME rectangle on the same layer, e.g.

        NET clk iterms=1 bterms=1 wire=NULL
        ITERM u_pad_clk PAD  bbox 6148000 3102000 6268000 3222000  (Metal5)
        BTERM clk            bbox 6148000 3102000 6268000 3222000  (Metal5)

    Every I/O net of every padded design lands in that count, so the number the
    promotion gate is supposed to refuse on is, on the chip path, entirely
    manufactured -- and a REAL unrouted net hiding among them is indistinguishable
    from the noise.

    So a wireless multi-terminal net is UNROUTED only when its terminals are not
    ALREADY physically connected: the shapes are taken per terminal WITH their
    layers (`dbITerm getGeometries` is instance-transformed; `dbBPin getBoxes` is
    already absolute), and the terminals are unioned under "two shapes overlap on
    a shared layer". A net whose terminals all fall in ONE component needs no
    wire and is reported under its own marker, `<PFX>_ABUTTED_NETS`, never folded
    into the unrouted count and never left silent.

    FAIL-SAFE IN THE DIRECTION THAT KEEPS THE CHECK: a terminal whose shapes
    cannot be read cannot be PROVEN abutted, so its net stays counted as
    unrouted and the count of such nets is disclosed as
    `<PFX>_UNROUTED_SHAPE_BLIND`. Being unable to look is never an acquittal.

    The discrimination is measured, not asserted -- on the same database, with 5
    genuinely-routed nets' wires destroyed:

        pre   CONTROL 36 | CANDIDATE unrouted 0,  abutted 36
        post  CONTROL 41 | CANDIDATE unrouted 5,  abutted 36
              (clk__core, net5, p__core, rst__core, spare_tielo_spare_aoi_0)

    -- the planted nets come back by name, including a spare-tie net, which is
    the v1.5.65 hazard this check exists for. On the no-pad arm of the same
    design the two bodies agree exactly, 0/0 before and 5/5 after.

    THE STAGE IS A FIELD, NOT PART OF THE MARKER NAME, and that is a contract
    this lane already wrote. The two post-route antenna passes are the same
    stage emitted twice and must differ in NOTHING but the one stage token
    each pass's probes carry -- `test_splitting_the_reconverge_block_did_not_
    drop_the_second_antenna_pass` normalises that ONE token and then demands
    byte-equality. Baking the stage into the marker name (`UNROUTED_PROBE_
    AFTER_POSTROUTE_ANTENNA_REPAIR_...`) put a SECOND, differently-spelled
    per-pass token outside that normalisation and broke the equality; the
    arms caught it on 5b5bd02af. So `stage` is emitted as a field, spelled
    EXACTLY as `_pin_access_probe_tcl` spells it, and one normalisation now
    covers both probes. A caller that names no stage gets its previous lines
    byte-for-byte -- SHIP, SDR, NAMED_VIOL_REROUTE and PAD_CHECK are
    unchanged, including the `SHIP_UNROUTED_NETS:` line the promotion gate
    parses."""
    _st = f"stage={stage} " if stage else ""
    _net_filter = (
        "    if {$_st ne \"POWER\" && $_st ne \"GROUND\"} { continue }\n"
        "    if {[llength [$_net getSWires]]} { continue }\n"
        if supply_only else
        "    if {$_st eq \"POWER\" || $_st eq \"GROUND\"} { continue }\n")
    return _terminal_contact_helpers_tcl() + (
        "proc _vibeic_uf_find {_arr _x} {\n"
        "  upvar 1 $_arr _a\n"
        "  while {$_a($_x) != $_x} { set _x $_a($_x) }\n"
        "  return $_x\n"
        "}\n"
        "set ::_vic_routing_integrity_complete 0\n"
        "if {[catch {\n"
        "  set _unr 0; set _abut 0; set _blind 0; set _unrn {}; set _abn {}\n"
        "  set _unra {}; set _abna {}\n"
        "  foreach _net [[ord::get_db_block] getNets] {\n"
        "    set _st [$_net getSigType]\n"
        + _net_filter +
        "    set _terms {}\n"
        "    foreach _t [$_net getITerms] { lappend _terms [list I $_t] }\n"
        "    foreach _t [$_net getBTerms] { lappend _terms [list B $_t] }\n"
        "    if {[llength $_terms] < 2} { continue }\n"
        "    if {[$_net getWire] ne \"NULL\"} { continue }\n"
        "    set _sh {}; set _readable 1\n"
        "    foreach _tp $_terms {\n"
        "      lassign $_tp _k _t\n"
        "      set _s [_vibeic_term_shapes $_t $_k]\n"
        "      if {![llength $_s]} { set _readable 0 }\n"
        "      lappend _sh $_s\n"
        "    }\n"
        "    set _n [llength $_sh]; set _one 0\n"
        "    if {$_readable} {\n"
        "      for {set _i 0} {$_i < $_n} {incr _i} { set _uf($_i) $_i }\n"
        "      for {set _i 0} {$_i < $_n} {incr _i} {\n"
        "        for {set _j [expr {$_i + 1}]} {$_j < $_n} {incr _j} {\n"
        "          if {[_vibeic_shapes_touch [lindex $_sh $_i] "
        "[lindex $_sh $_j]]} {\n"
        "            set _ri [_vibeic_uf_find _uf $_i]\n"
        "            set _rj [_vibeic_uf_find _uf $_j]\n"
        "            if {$_ri != $_rj} { set _uf($_ri) $_rj }\n"
        "          }\n"
        "        }\n"
        "      }\n"
        "      set _root [_vibeic_uf_find _uf 0]; set _one 1\n"
        "      for {set _i 1} {$_i < $_n} {incr _i} {\n"
        "        if {[_vibeic_uf_find _uf $_i] != $_root} { set _one 0; break }\n"
        "      }\n"
        "      array unset _uf\n"
        "    } else { incr _blind }\n"
        "    if {$_one} {\n"
        "      incr _abut\n"
        "      lappend _abna [$_net getName]\n"
        "      if {[llength $_abn] < 12} { lappend _abn [$_net getName] }\n"
        "    } else {\n"
        "      incr _unr\n"
        # R-0915-121(b): the UNCAPPED membership, for the file. The capped
        # list above stays exactly as it was -- stdout is a summary and must
        # not become a net dump -- but "which nets" stopped being answerable
        # the moment the cap hid them, and two ICs lost a run to that.
        "      lappend _unra [$_net getName]\n"
        "      if {[llength $_unrn] < 12} { lappend _unrn [$_net getName] }\n"
        "    }\n"
        "  }\n"
        f"  puts \"{marker_prefix}_UNROUTED_NETS: {_st}$_unr "
        "[join $_unrn ,]\"\n"
        f"  puts \"{marker_prefix}_ABUTTED_NETS: {_st}$_abut "
        "[join $_abn ,]\"\n"
        f"  puts \"{marker_prefix}_UNROUTED_SHAPE_BLIND: {_st}$_blind\"\n"
        + (
            # R-0915-121(b) -- the membership goes to a FILE, uncapped. The
            # stdout line keeps its 12-name cap: MEASURED, and it is why this
            # exists. On spm run13 the raise named 86 distinct nets and the
            # checker later found 84 unwired, and the 12 names the Tcl printed
            # were NOT among the 86 -- so "are these the same nets?" could not
            # be answered from the run's own output at all. A file that nobody
            # reads costs nothing; a cap that hides the answer cost two ICs a
            # run each.
            # ONLY WHEN THERE IS SOMETHING TO SAY. Caught by the repo's own
            # suite_write_guard: the path is relative -- correct for the flow,
            # whose cwd IS the pnr directory, the same convention
            # `antenna_iter_*.rpt` already uses -- but several tests execute
            # the emitted deck with the cwd inside the checkout, and an
            # unconditional write dropped seven files into the source tree.
            # A file per boundary per run on a healthy design is clutter
            # anyway; the stdout counts are the summary and the file is only
            # needed when it has names in it.
            "  if {$_unr > 0 && [catch {\n"
            f"    set _unfh [open {membership_path} w]\n"
            f"    puts $_unfh \"# {marker_prefix} unrouted-net membership, "
            "uncapped ([llength $_unra] net(s))\"\n"
            "    foreach _unnm $_unra { puts $_unfh $_unnm }\n"
            f"    puts $_unfh \"# {marker_prefix} abutted "
            "([llength $_abna] net(s))\"\n"
            "    foreach _unnm $_abna { puts $_unfh \"ABUTTED $_unnm\" }\n"
            "    close $_unfh\n"
            "  } _unfe]} {\n"
            f"    puts \"{marker_prefix}_MEMBERSHIP_UNWRITTEN: $_unfe\"\n"
            "  } elseif {$_unr > 0} {\n"
            f"    puts \"{marker_prefix}_MEMBERSHIP: {_st}{membership_path} "
            "([llength $_unra] unrouted, [llength $_abna] abutted)\"\n"
            "  }\n"
            if membership_path else ""
        )
        + "  set ::_vic_routing_integrity_complete 1\n"
        + f"}} e]}} {{ puts \"{marker_prefix}_UNROUTED_CHECK_NONFATAL: $e\" }}\n"
    )


def pnr_input_netlist(project: Path, top: str) -> Tuple[Path, str, bool]:
    synth = _pl.synth_dir(project)
    post_dft = synth / "post_dft_netlist.v"
    if post_dft.is_file():
        return post_dft, "Post-DFT netlist.", True
    return synth / f"{top}_synth.v", "Synthesis netlist.", False


def _def_net_members(def_text: str) -> Dict[str, List[Tuple[str, str]]]:
    """`{net: [(instance, pin), ...]}` over a DEF's NETS and SPECIALNETS.

    A top-level port appears as `("PIN", port)`. SPECIALNETS is read too
    because OpenROAD writes a net joining a port to a pad pin there (MEASURED:
    LibreLane PadRing on spm x gf180mcuD, `- clk ( PIN clk ) ( u_pad_clk PAD )
    + USE SIGNAL`). Wildcard `( * pin )` members are global-connect rules, not
    connections, and are skipped. A net named in both sections is one net.
    """
    out: Dict[str, List[Tuple[str, str]]] = {}
    for section_name in ("SPECIALNETS", "NETS"):
        start = re.search(rf"^\s*{section_name}\s+\d+\s*;", def_text, re.MULTILINE)
        if not start:
            if section_name == "NETS":
                raise ValueError("DEF has no NETS section")
            continue
        end = re.search(rf"^\s*END\s+{section_name}\b", def_text[start.end():],
                        re.MULTILINE)
        if not end:
            raise ValueError(f"DEF {section_name} section is unterminated")
        section = def_text[start.end():start.end() + end.start()]
        for entry in re.finditer(r"^\s*-\s+(?P<net>\S+)\s+(?P<body>.*?);",
                                 section, re.MULTILINE | re.DOTALL):
            members = out.setdefault(entry.group("net"), [])
            for inst, pin in re.findall(r"\(\s+(\S+)\s+(\S+)\s*\)",
                                        entry.group("body").split("+", 1)[0]):
                member = ("PIN" if inst.upper() == "PIN" else inst, pin)
                if inst != "*" and member not in members:
                    members.append(member)
    return out


def _strip_nonlayer_blockages(def_text: str) -> Tuple[str, List[str]]:
    """Return (def_text_without_layerless_BLOCKAGES, dropped_entry_summaries).

    A DEF `BLOCKAGES` section may hold two unrelated kinds of entry:

      - LAYER MET1 RECT ( x1 y1 ) ( x2 y2 ) ;              <- has geometry
      - PLACEMENT + SOFT + COMPONENT <inst> RECT ( ... ) ; <- placer directive

    The second kind names NO layer: it is an instruction to the PLACER not to
    put cells in a region, and it carries no conductor. Magic's DEF reader has
    no layer to bind that RECT to and emits

        LEF read, Line NNNN (Error): No layer defined for RECT.

    and -- measured, not assumed -- then terminates the DEF read part of the
    time: the SAME command on the SAME byte-identical DEF succeeded 2 of 5
    runs and died inside the BLOCKAGES section the other 3. Magic exits 0
    either way, so the step reported only the vague downstream symptom
    "produced no extracted netlist (rc=0)" and LVS was unrunnable at random.

    So: drop only the entries magic cannot bind (no LAYER), keep every entry
    that does name a layer, and leave the DEF used by every OTHER consumer
    untouched -- this staged copy is for extraction alone. The removal is
    LOSS-FREE for extraction by construction (a placement blockage has no
    conductor to extract) and was verified as such: on a run where the intact
    DEF happened to survive, the extracted netlists from the intact and the
    stripped DEF were byte-identical (same md5).

    Strict fall-through: a DEF with no BLOCKAGES section, or one whose
    blockages ALL name a layer, comes back unchanged with an empty list, so
    the caller keeps using the original file. chip-AGNOSTIC: pure DEF syntax,
    no PDK/design knowledge."""
    m = re.search(r"(?m)^[ \t]*BLOCKAGES[ \t]+(\d+)[ \t]*;[ \t]*$", def_text)
    if not m:
        return def_text, []
    end = re.search(r"(?m)^[ \t]*END[ \t]+BLOCKAGES[ \t]*$", def_text[m.end():])
    if not end:
        return def_text, []
    body = def_text[m.end():m.end() + end.start()]
    entries = re.findall(r"-[ \t\r\n].*?;", body, re.S)
    if not entries:
        return def_text, []
    kept = [e for e in entries if re.match(r"-\s+LAYER\b", e)]
    dropped = [" ".join(e.split())[:120] for e in entries if e not in kept]
    if not dropped:
        return def_text, []
    if kept:
        new_section = (f"BLOCKAGES {len(kept)} ;\n"
                       + "".join(f"    {' '.join(e.split())}\n" for e in kept)
                       + "END BLOCKAGES")
    else:
        # An empty `BLOCKAGES 0 ;` block is legal DEF, but emitting nothing is
        # simpler and equally legal; the section is optional.
        new_section = ""
    tail = def_text[m.end() + end.start():]
    tail = re.sub(r"(?m)\A[ \t]*END[ \t]+BLOCKAGES[ \t]*\n?", "", tail)
    return def_text[:m.start()] + new_section + ("\n" if new_section else "") \
        + tail, dropped










_RCX_LEGACY_VARS = (("RCX_RULES", "nom_*"), ("RCX_RULES_MIN", "min_*"),
                    ("RCX_RULES_MAX", "max_*"))


_RCX_DECL_TCL = r"""
lassign $argv pdkdir scl
set root [file dirname $pdkdir]
set pdk [file tail $pdkdir]
set ::env(PDK_ROOT) $root
set ::env(PDK) $pdk
if {$scl ne ""} { set ::env(STD_CELL_LIBRARY) $scl }
set flow ""
foreach f {librelane openlane} {
  if {[file isfile $root/$pdk/libs.tech/$f/config.tcl]} { set flow $f; break }
}
if {$flow eq ""} { puts "RCX_DECL_NO_CONFIG $root/$pdk/libs.tech/{librelane,openlane}/config.tcl"; exit }
set cfg $root/$pdk/libs.tech/$flow/config.tcl
puts "RCX_DECL_CONFIG $cfg"
if {[catch {source $cfg} e]} { puts "RCX_DECL_ERROR [string map {"\n" " "} $e]"; exit }
set from [dict create]
foreach var {RCX_RULESETS %LEGACYVARS%} {
  if {[info exists ::env($var)]} { dict set from $var $cfg }
}
if {[info exists ::env(STD_CELL_LIBRARY)]} {
  set scfg $root/$pdk/libs.tech/$flow/$::env(STD_CELL_LIBRARY)/config.tcl
  if {[file isfile $scfg]} {
    set before [array get ::env RCX_*]
    if {[catch {source $scfg} e]} { puts "RCX_DECL_ERROR [string map {"\n" " "} $e]"; exit }
    puts "RCX_DECL_CONFIG $scfg"
    foreach var {RCX_RULESETS %LEGACYVARS%} {
      if {[info exists ::env($var)] && (![dict exists $before $var] || [dict get $before $var] ne $::env($var))} {
        dict set from $var $scfg
      }
    }
  }
}
if {[info exists ::env(RCX_RULESETS)]} {
  dict for {k v} $::env(RCX_RULESETS) { puts "RCX_DECL_RULESET RCX_RULESETS $k [file isfile $v] [dict get $from RCX_RULESETS] $v" }
} else {
  foreach {var pat} {%LEGACY%} {
    if {[info exists ::env($var)]} { puts "RCX_DECL_RULESET $var $pat [file isfile $::env($var)] [dict get $from $var] $::env($var)" }
  }
}
puts "RCX_DECL_END"
""".replace("%LEGACY%", " ".join(f"{v} {p}" for v, p in _RCX_LEGACY_VARS)).replace(
    "%LEGACYVARS%", " ".join(v for v, _p in _RCX_LEGACY_VARS))


_ESD_CELL_HINTS = (
    "gpiov2", "_hvc", "_lvc", "hvclamp", "lvclamp", "clamp", "clamped",
    "analog_esd", "_esd_pad", "_esd", "hvc_wpad", "lvc_wpad",
    "xres", "_sio", "gnd2gnd", "clmp",            # more sky130_fd_io ESD-bearing pads
    "diode", "ggnmos", "ggnmof", "antenna",        # discrete ESD cells (other PDKs)
)


_ESD_NEGATION_HINTS = (
    "noesd", "no_esd", "unclamp", "noclamp", "declamp", "esd_disabled",
    "bare_pad", "analog_noesd",
)


_STRUCTURAL_PAD_HINTS = (
    "corner_pad", "com_bus_slice", "_slice_", "connect_", "disconnect_",
    "constant_block",
)


_IO_FAMILY_HINTS = (
    "_pad", "_io", "gpio", "bondpad", "padframe", "_pdio", "wpad",
    "hvclamp", "lvclamp", "_hvc", "_lvc", "gpiov2", "xres", "_sio", "gnd2gnd",
)


_DEF_COMPONENT_RE = re.compile(
    r"^\s*-\s+(\S+)\s+(\S+)", re.MULTILINE)


_DEF_COMPONENTS_SECTION_RE = re.compile(
    r"^COMPONENTS\b.*?^END COMPONENTS", re.MULTILINE | re.DOTALL)


@dataclass(frozen=True)
class _DefReopenResolution:
    """The DEF-owned physical facts every consumer of one DEF must agree on.

    `design` is the cell name the DEF declares for itself (`None` when the DEF
    is missing, unreadable or headerless — never a guess). `components` is the
    instantiated `(instance, master)` population, in file order.

    FROZEN, and a tuple rather than a list, because the point of the record is
    that two consumers handed it cannot end up describing different files: a
    consumer that could edit it could re-introduce by mutation exactly the
    divergence this removes."""

    design: Optional[str]
    components: Tuple[Tuple[str, str], ...]


def _def_components_from_text(def_text: str) -> Tuple[Tuple[str, str], ...]:
    """The ONE COMPONENTS parse. `()` when the DEF declares no such block.

    chip-AGNOSTIC structural parse: no literal names. Each component entry
    opens `- <inst> <master>`; only those two tokens are read, so the
    placement syntax that follows is irrelevant here."""
    m = _DEF_COMPONENTS_SECTION_RE.search(def_text or "")
    if not m:
        return ()
    out: List[Tuple[str, str]] = []
    for cm in _DEF_COMPONENT_RE.finditer(m.group(0)):
        inst, master = cm.group(1), cm.group(2)
        # Skip the COMPONENTS header artefact and section keywords.
        if master in (";", "+"):
            continue
        out.append((inst, master))
    return tuple(out)


def _def_resolution_from_text(def_text: str,
                              design: Optional[str] = None
                              ) -> _DefReopenResolution:
    """The resolution for a DEF whose text a caller has ALREADY read.

    `design` is passed in rather than re-derived: the design authority is
    `_def_design_name`, which takes a path, and a consumer holding only text
    (the pad-ring deck, the orphan precondition) is asking about the component
    population and has no design question to answer. It is `None` there, and
    `None` here means NOT ASKED — never "the DEF declares no design"."""
    return _DefReopenResolution(design=design,
                                components=_def_components_from_text(def_text))


def _def_reopen_resolution(def_file: Path) -> _DefReopenResolution:
    """Resolve one DEF's physical facts once, for every consumer of that file.

    Unreadable or absent: `design=None, components=()` — the same answer every
    reader below gave before, and never an exception."""
    try:
        text = def_file.read_text(errors="ignore")
    except OSError:
        text = ""
    return _def_resolution_from_text(text, design=_def_design_name(def_file))


def _parse_def_components(def_file: Path) -> List[Tuple[str, str]]:
    """Parse the DEF COMPONENTS block into [(instance, master), ...].

    chip-AGNOSTIC structural parse: no literal names. Returns [] if the DEF
    has no COMPONENTS block. Each component line is `- <inst> <master> + ...`.

    Now a wrapper over `_def_reopen_resolution` (#2044) so this reader and the
    two others cannot answer differently; the value returned is unchanged."""
    return list(_def_reopen_resolution(def_file).components)


_DEF_DESIGN_RE = re.compile(r"(?m)^\s*DESIGN\s+(\S+)\s*;")


_DEF_BODY_SECTION_RE = re.compile(
    r"^\s*(?:COMPONENTS|PINS|SPECIALNETS|NETS|BLOCKAGES|GROUPS"
    r"|SCANCHAINS|FILLS|SLOTS|REGIONS)\b")


def _def_design_name(def_path: Path) -> Optional[str]:
    """The CELL NAME the DEF declares for itself, or None if it does not.

    WHY A CELL NAME IS NOT A FILE NAME. Every physical step in this runner is
    handed one `top` string and uses it for BOTH -- to build
    `<top>.def` / `<top>.gds` / `<top>_pnr.v`, and as the cell name it hands a
    tool. On the chip path those two stop being the same word. Step 15.5ic's
    `io_pad_chip_top_gen` writes a pad-carrying chip top and
    `_inject_padring_chip_top` retargets `link_design` to it, so the DEF that
    leaves PnR carries `DESIGN chip_top ;` while the FILE is still
    `<core>.def` -- deliberately, because every downstream lookup is keyed on
    the file name. The runner's `top` is resolved once from `rtl/` before the
    flow starts and is never told about the substitution.

    MEASURED, spm x gf180mcuD, a 36-pad chip top, plugin 1.17.4, the run as
    shipped -- `spm.def` says `DESIGN chip_top ;`, and the Magic streamout was
    invoked with `TOP=spm`. Magic's own transcript, which the caller assigned
    to a local and never read:

        Cell spm couldn't be read
        No such file or directory
        Cannot rename; cell "spm" already exists!

    `load spm` on a database that has no `spm` CREATES an empty cell of that
    name, `select top cell` selects that empty cell, and `gds write` writes
    it: `spm.gds`, 106 bytes, one empty structure. `step_drc` then reported
    `violations=0` on it and `pad_ring_route_evidence` reported
    PADRING_GDS_REFERENCES_LOST for 35 references of `gf180mcu_fd_io__in_c`.

    A/B ON THE SHIPPED DEF, same deck, same libraries, ONLY the cell name
    changed: `TOP=spm` -> 106 bytes; `TOP=chip_top` -> 16,941,056 bytes.

    NOT A LIBRARY SHORTAGE, and the same probe says so: adding the PDK IO
    library's LEF and GDS views to the Magic invocation with `TOP=spm` still
    writes 106 bytes, because Magic had already resolved those masters itself
    (`Cell gf180mcu_fd_io__in_c read from path
    /foss/pdks/gf180mcuD/libs.ref/gf180mcu_fd_io/mag`).

    THE DEF IS THE AUTHORITY, and it is the only one that cannot be stale: it
    is the file being streamed, and it names the design it describes. A design
    off the chip path has `DESIGN == top` and every caller below reproduces
    its current behaviour exactly. Chip/PDK-AGNOSTIC: no design, vendor or PDK
    literal -- the DEF names itself.

    BOUNDED BY THE GRAMMAR, NOT BY A BYTE COUNT (#2044 F7). This read used to
    take the first 65536 bytes and search those. DEF puts `DESIGN` in the
    header, but it does not put a CEILING on the header: `#` comments are
    legal anywhere, and a tool that stamps a provenance banner ahead of
    `DESIGN` pushes it past any fixed offset. A DEF whose header crosses that
    offset returned None here, and None is not inert -- `_streamout_top` reads
    it as "the DEF agrees with `top`" and streams the runner's file-naming top,
    which is the 106-byte-GDS failure this very function was written to stop.
    The bound was silently reintroducing the bug it fixes.

    So the scan now walks the header a line at a time and stops on whichever
    comes first: the `DESIGN` line, or the first line opening a section that
    DEF places AFTER `DESIGN` (`_DEF_BODY_SECTION_RE`). The file body is never
    read -- a 182 MB DEF still stops at its COMPONENTS line -- but a header of
    any size is read in full, because the header is where the answer is.
    Unreadable, absent, or headerless: None, never an exception.
    """
    try:
        with open(def_path, "r", errors="replace") as fh:
            for line in fh:
                m = _DEF_DESIGN_RE.match(line)
                if m:
                    return m.group(1)
                if _DEF_BODY_SECTION_RE.match(line):
                    return None            # past the header; DESIGN not stated
    except OSError:
        return None
    return None


def _classify_io_cell(master: str) -> str:
    """Classify ONE DEF master into an IO-pad-ring role (pure, chip-AGNOSTIC).

    Returns one of: 'esd_pad' (IO pad/clamp with integral ESD), 'nonesd_pad'
    (IO pad with NO clamp — bare/noesd/plain-analog), 'structural' (corner /
    common-bus slice / connect-disconnect filler — not a signal pad), or 'other'
    (core std cell / internal macro — not part of any pad ring).

    Strict token ORDER (vetted by design panel + adversarial critics): IO-family
    gate → negation/disable → ESD → structural → default IO pad. The order is
    load-bearing: negation BEFORE esd stops `analog_noesd_pad` being read as ESD;
    esd BEFORE structural stops `gpiov2_corner_pad` / `esd_clamp_slice` being
    swallowed by the broad 'corner'/'_slice_' structural tokens."""
    n = master.lower()
    if not (any(t in n for t in _IO_FAMILY_HINTS)
            or any(t in n for t in _STRUCTURAL_PAD_HINTS)):
        return "other"                                    # core std cell / macro
    if any(t in n for t in _ESD_NEGATION_HINTS):
        return "nonesd_pad"                               # explicit non-ESD / disabled
    if any(t in n for t in _ESD_CELL_HINTS):
        return "esd_pad"                                  # integral clamp / discrete ESD
    if any(t in n for t in _STRUCTURAL_PAD_HINTS):
        return "structural"                               # corner / bus-slice filler
    return "nonesd_pad"                                   # IO pad, no clamp token


_WELLTAP_TOKEN_RE = re.compile(r"(?:^|_)tap(?:\d|_|$)", re.IGNORECASE)


_WELLTAP_RATED = (
    "sky130_fd_sc_hd__tap", "sky130_fd_sc_hdll__tap", "sky130_fd_sc_hs__tap",
    "sky130_fd_sc_ls__tap", "sky130_fd_sc_ms__tap", "sky130_fd_sc_lp__tap",
    "sky130_fd_sc_hvl__tap", "sky130_ef_sc_hd__tap",
)


def _net_pg_class(net: str) -> str:
    """Classify a net name as 'power' | 'ground' | 'signal' by substring."""
    n = net.lower()
    if any(t in n for t in ("vss", "gnd", "vgnd", "vnb")):
        return "ground"
    # 'vswitch' (sky130 IO power-switch rail) has no vdd/vcc substring → add it
    # explicitly (v0.2.11); 'vcchib' is already caught by 'vcc'.
    if any(t in n for t in ("vdd", "vcc", "vpwr", "vpb", "vswitch")):
        return "power"
    return "signal"


def step_scan_physical(project: Path, context: dict) -> dict:
    return {"status": "NOT_MEASURED", "detail": "The native physical scan adapter is not wired."}


def main(argv=None) -> int:
    from flow_engine_frontend import phase_main
    return phase_main(argv, scope="phase3")


_VERDICT_RANK = {v.value: i for i, v in
                 enumerate(reversed(_V.RUN_PRECEDENCE))}


if __name__ == "__main__":
    sys.exit(main())
