#!/usr/bin/env python3
"""Project-local LibreLane step handoff. No Phase-3 step opts in implicitly."""
from __future__ import annotations

import argparse
import fnmatch
import hashlib
import json
import math
import os
import re
import shutil
import subprocess
import sys
import tempfile
from decimal import Decimal
from pathlib import Path
from typing import Any, Callable

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _atomic_artefact import write_json  # noqa: E402
import _docker_memory as _dmem  # noqa: E402 — every `docker run` carries the ceiling
import _container_exec as _ce  # noqa: E402 — the existing in-image route


class Refusal(RuntimeError):
    def __init__(self, code: str, detail: str):
        self.code = code
        super().__init__(f"{code}: {detail}")


LOCAL_PROVIDER_ROUTE_ENV = 'VIBEIC_LIBRELANE_ROUTE'


class LocalRuntime(str):
    """The executable and paths required to run LibreLane on this host."""

    def __new__(cls, executable: str, *, librelane_root: str, pdk_root: str,
                pdk: str | None, network_mode: str):
        value = str.__new__(cls, executable)
        value.executable = executable
        value.librelane_root = librelane_root
        value.pdk_root = pdk_root
        value.pdk = pdk
        value.network_mode = network_mode
        return value


def _provider_switch(project: Path | None) -> dict[str, Any]:
    path = Path(project) / 'phase3/librelane_switch.json' if project else None
    return _load(path) if path and path.is_file() else {}


def _provider_route_value(project: Path | None) -> str | None:
    switch = _provider_switch(project)
    for key in ('execution_route', 'provider_route', 'librelane_route',
                'execution_provider', 'librelane_provider', 'provider', 'route'):
        value = switch.get(key)
        if isinstance(value, dict):
            value = value.get('route') or value.get('mode')
        if isinstance(value, str) and value.strip():
            return value.strip().upper()
    value = os.environ.get(LOCAL_PROVIDER_ROUTE_ENV)
    return value.strip().upper() if value and value.strip() else None


def _provider_route(project: Path | None = None) -> bool:
    value = _provider_route_value(project)
    if value in {'LOCAL', 'HOST', 'NATIVE'}:
        return True
    if value in {'REMOTE', 'CONTAINER', 'DOCKER'}:
        return False
    return _ce.no_container_route()


def _explicit_local_route(project: Path | None) -> bool:
    return _provider_route_value(project) in {'LOCAL', 'HOST', 'NATIVE'}


def _provider_roots(project: Path | None, pdk: str | None) -> tuple[str | None, str | None, str | None]:
    switch = _provider_switch(project)
    root = switch.get('pdk_root_host') or os.environ.get('VIBEIC_LIBRELANE_PDK_ROOT')
    source = (switch.get('librelane_root_host') or switch.get('librelane_root') or
              switch.get('development_librelane_source') or
              os.environ.get('VIBEIC_LIBRELANE_ROOT'))
    selected = pdk or switch.get('pdk')
    return ((str(root) if root not in (None, '') else None),
            (str(source) if source not in (None, '') else None),
            (str(selected) if selected not in (None, '') else None))


def local_runtime(project: Path | None = None, pdk: str | None = None) -> LocalRuntime | None:
    if not _explicit_local_route(project):
        return None
    root, source, selected = _provider_roots(project, pdk)
    root = str(Path(root).expanduser()) if root else None
    source = str(Path(source).expanduser()) if source else None
    if selected and not _PDK_NAME.fullmatch(selected):
        raise Refusal('LL_PDK_NAME_INVALID', repr(selected))
    if not root or not Path(root).is_dir():
        raise Refusal('LL_LOCAL_PDK_ROOT_INVALID', str(root))
    if not source or not (Path(source) / 'librelane/__init__.py').is_file():
        raise Refusal('LL_LOCAL_LIBRELANE_ROOT_INVALID', str(source))
    executable = (_provider_switch(project).get('librelane_executable') or
                  os.environ.get('VIBEIC_LIBRELANE_EXECUTABLE') or sys.executable)
    executable = shutil.which(str(executable))
    if executable is None:
        raise Refusal('LL_LOCAL_EXECUTABLE_INVALID', 'LibreLane Python executable is unavailable')
    network = str(_provider_switch(project).get('local_network_mode') or
                  os.environ.get('VIBEIC_LIBRELANE_LOCAL_NETWORK') or 'none').strip().lower()
    if network not in {'none', 'host'}:
        raise Refusal('LL_LOCAL_LAUNCH_UNSUPPORTED', f'network mode {network!r}')
    return LocalRuntime(executable, librelane_root=str(Path(source).resolve()),
                        pdk_root=str(Path(root).resolve()), pdk=selected, network_mode=network)


def _provider_for_image(image: Any) -> LocalRuntime | None:
    return image if isinstance(image, LocalRuntime) else None


def native_tool_command(image: Any, command: list[str]) -> tuple[str, list[str]]:
    """Enter a native tool through the current provider's admitted executable."""
    provider = _provider_for_image(image)
    if provider is None:
        return 'none', command
    return provider.network_mode, [
        provider.executable, '-c',
        'import os,sys;os.execvp(sys.argv[1],sys.argv[1:])', *command]


def _provider_route_mismatch(image: Any, project: Path | None = None, *,
                             native_handoff: bool = False) -> Refusal | None:
    provider = _provider_for_image(image)
    if provider is not None:
        # A provider passed to a child has no project argument; an explicit
        # remote environment remains an authoritative mismatch control.
        if _provider_route_value(project) in {'REMOTE', 'CONTAINER', 'DOCKER'}:
            return Refusal('LL_LOCAL_REMOTE_MISMATCH',
                            f'LOCAL provider {provider} cannot run on a Docker-backed route')
        if project is not None and not _provider_route(project):
            return Refusal('LL_LOCAL_REMOTE_MISMATCH',
                            f'LOCAL provider {provider} cannot run on a Docker-backed route')
    elif image is not None and _explicit_local_route(project):
        return Refusal('LL_LOCAL_REMOTE_MISMATCH',
                        f'Docker-backed image {image} cannot run on an explicit LOCAL route')
    # A native Step-15 handoff must refuse an explicitly remote route before
    # resolving the host's image.  Ordinary direct callers retain their
    # declared route semantics; the native rule is opt-in at that seam.
    if (native_handoff and
            _provider_route_value(project) in {'REMOTE', 'CONTAINER', 'DOCKER'} and
            _ce.no_container_route()):
        return Refusal('LL_LOCAL_REMOTE_MISMATCH',
                       'explicit remote route cannot run without a container route')
    return None


# Docker CLI run-option arity (including short and platform-specific options):
# https://docs.docker.com/reference/cli/docker/container/run/
# Execution backends still enforce which options they can actually implement.
_DOCKER_RUN_VALUE_OPTIONS = frozenset({
    '-a', '-c', '-e', '-h', '-l', '-m', '-p', '-u', '-v', '-w',
    '--add-host', '--annotation', '--attach', '--blkio-weight',
    '--blkio-weight-device', '--cap-add', '--cap-drop', '--cgroup-parent',
    '--cgroupns', '--cidfile', '--cpu-count', '--cpu-percent', '--cpu-period',
    '--cpu-quota', '--cpu-rt-period', '--cpu-rt-runtime', '--cpu-shares', '--cpus',
    '--cpuset-cpus', '--cpuset-mems', '--detach-keys', '--device',
    '--device-cgroup-rule', '--device-read-bps', '--device-read-iops',
    '--device-write-bps', '--device-write-iops', '--dns', '--dns-option',
    '--dns-search', '--domainname', '--entrypoint', '--env', '--env-file',
    '--expose', '--gpus', '--group-add', '--health-cmd', '--health-interval',
    '--health-retries', '--health-start-interval', '--health-start-period',
    '--health-timeout', '--hostname', '--io-maxbandwidth', '--io-maxiops',
    '--ip', '--ip6', '--ipc', '--isolation', '--label', '--label-file', '--link',
    '--link-local-ip', '--log-driver', '--log-opt', '--mac-address', '--memory',
    '--memory-reservation', '--memory-swap', '--memory-swappiness', '--mount',
    '--name', '--net', '--network', '--network-alias', '--oom-score-adj', '--pid',
    '--pids-limit', '--platform', '--publish', '--pull', '--restart', '--runtime',
    '--security-opt', '--shm-size', '--stop-signal', '--stop-timeout',
    '--storage-opt', '--sysctl', '--tmpfs', '--ulimit', '--user', '--userns',
    '--uts', '--volume', '--volume-driver', '--volumes-from', '--workdir',
})


def _container_image_arg(argv: list[Any]) -> Any | None:
    """Return the image token after the Docker-run options, if unambiguous."""
    try:
        at = argv.index('run') + 1
    except ValueError:
        return None
    while at < len(argv):
        token = argv[at]
        if not isinstance(token, str):
            return token
        if not token.startswith('-'):
            return token
        if token == '--rm':
            at += 1
        elif token in _DOCKER_RUN_VALUE_OPTIONS:
            at += 2
        else:
            return None
    return None


def _local_memory_bytes(value: str) -> int:
    """Decode the Docker byte/unit values emitted by this owner."""
    if value == '-1':
        return -1
    match = re.fullmatch(r'([0-9]+(?:\.[0-9]+)?)([kmgtp]?)(?:b)?', value.lower())
    if not match:
        raise Refusal('LL_LOCAL_LAUNCH_UNSUPPORTED', f'invalid memory limit {value!r}')
    power = 'bkmgtp'.index(match[2] or 'b')
    return int(Decimal(match[1]) * (1024 ** power))


def _run_local(argv: list[str], *, probe_deadline_s: float | None,
               supervised: bool, log: Path | None,
               provider: LocalRuntime | None = None,
               **kw: Any) -> subprocess.CompletedProcess:
    """Execute only the Docker-run shapes emitted by this LibreLane owner.

    Reuse the existing mount-path conversion and host process supervision.
    The enclosing fresh image supplies the environment and cgroup memory bound.
    CPU limits select at most ceil(N) inherited CPUs; memory becomes a child
    rlimit. Process counts use a transient user scope, never a per-UID rlimit.
    Unknown launch options refuse rather than silently discarding their meaning.
    """
    mounts, variables, entrypoint, container_workdir = [], {}, None, None
    network, memory, memory_swap = None, None, None
    cpus, pids_limit = None, None
    at = argv.index('run') + 1
    while at < len(argv) and argv[at].startswith('-'):
        option = argv[at]
        if option == '--rm':
            at += 1
            continue
        if option not in ('-v', '-e', '--entrypoint', '--memory', '--memory-swap',
                          '--network', '--workdir', '--cpus', '--pids-limit'):
            raise Refusal('LL_LOCAL_LAUNCH_UNSUPPORTED', option)
        if option == '--workdir' and at + 1 >= len(argv):
            raise Refusal('LL_LOCAL_WORKDIR_INVALID', '--workdir requires a path')
        if option in ('--cpus', '--pids-limit') and at + 1 >= len(argv):
            raise Refusal('LL_LOCAL_LAUNCH_UNSUPPORTED', f'{option} requires a value')
        value = argv[at + 1]
        if option == '-v':
            host, guest, *mode = value.split(':')
            if mode not in ([], ['ro'], ['rw']) or not Path(host).exists():
                raise Refusal('LL_LOCAL_MOUNT_INVALID', value)
            mounts.append((guest, str(Path(host).resolve())))
        elif option == '-e':
            key, value = value.split('=', 1)
            variables[key] = value
        elif option == '--entrypoint':
            entrypoint = value
        elif option == '--network':
            network = value
        elif option == '--workdir':
            container_workdir = value
        elif option == '--memory':
            memory = _local_memory_bytes(value)
        elif option == '--memory-swap':
            memory_swap = _local_memory_bytes(value)
        elif option in ('--cpus', '--pids-limit'):
            try:
                if option == '--cpus':
                    number = Decimal(value)
                    if not number.is_finite() or number < 0:
                        raise ValueError('CPU count must be finite and nonnegative')
                    cpus = math.ceil(number)
                else:
                    pids_limit = int(value)
                    if pids_limit < -1:
                        raise ValueError('process limit must be nonnegative or -1')
            except (ValueError, ArithmeticError) as exc:
                raise Refusal('LL_LOCAL_LAUNCH_UNSUPPORTED',
                              f'invalid {option} value {value!r}: {exc}') from None
        at += 2
    child_cwd = None
    if container_workdir is not None:
        requested_cwd = Path(container_workdir)
        if not requested_cwd.is_absolute():
            raise Refusal('LL_LOCAL_WORKDIR_INVALID',
                          f'--workdir must be an absolute mounted path: {container_workdir!r}')
        mapped_cwd = Path(_ce.localise_mounted_paths(container_workdir, mounts))
        mapped_mounts = []
        for guest, host in mounts:
            guest_path = Path(guest)
            try:
                relative = requested_cwd.relative_to(guest_path)
            except ValueError:
                continue
            mapped_mounts.append((len(guest_path.parts), guest_path, Path(host), relative))
        if not mapped_mounts:
            raise Refusal('LL_LOCAL_WORKDIR_INVALID',
                          f'--workdir is outside every declared mount: {container_workdir!r}')
        _, guest_root, host_root, relative = max(mapped_mounts, key=lambda row: row[0])
        try:
            resolved_root = host_root.resolve(strict=True)
            child_cwd = mapped_cwd.resolve(strict=True)
            expected_cwd = (resolved_root / relative).resolve(strict=True)
            supplied_cwd = Path(kw['cwd']).resolve(strict=True) if kw.get('cwd') is not None else None
        except OSError as exc:
            raise Refusal('LL_LOCAL_WORKDIR_INVALID',
                          f'--workdir does not resolve on the mounted host path: {exc}') from None
        if (child_cwd != expected_cwd or not child_cwd.is_dir()
                or not child_cwd.is_relative_to(resolved_root)):
            raise Refusal('LL_LOCAL_WORKDIR_INVALID',
                          f'--workdir does not resolve to an existing directory in mount {guest_root}')
        if supplied_cwd is not None and supplied_cwd != child_cwd:
            raise Refusal('LL_LOCAL_WORKDIR_INVALID',
                          'caller cwd conflicts with the mounted Docker --workdir')
        kw['cwd'] = child_cwd
    image = argv[at]
    provider = provider or _provider_for_image(image)
    if provider is not None:
        if _provider_route_value(None) in {'REMOTE', 'CONTAINER', 'DOCKER'}:
            raise Refusal('LL_LOCAL_REMOTE_MISMATCH',
                          f'LOCAL provider {provider} cannot run on a Docker-backed route')
        image = str(image)
        argv[at] = image
    if provider is not None and network is None:
        network = provider.network_mode
    if provider is not None and (memory is None or memory <= 0):
        raise Refusal('LL_LOCAL_LAUNCH_UNSUPPORTED', 'a finite --memory limit is required')
    if provider is not None and memory_swap != memory:
        raise Refusal('LL_LOCAL_LAUNCH_UNSUPPORTED', '--memory-swap must equal --memory on the host route')
    command = argv[at + 1:]
    if entrypoint:
        command = [entrypoint, *command]
    elif command[:1] == ['--skip']:
        command = command[1:]
    else:
        raise Refusal('LL_LOCAL_LAUNCH_UNSUPPORTED', 'missing explicit --skip command')
    command = [_ce.localise_mounted_paths(part, mounts) for part in command]
    if provider is not None and command and command[0] in {'python', 'python3'}:
        command[0] = provider.executable
    if provider is not None and network == 'none':
        helper = shutil.which('bwrap')
        if helper is None:
            raise Refusal('LL_LOCAL_LAUNCH_UNSUPPORTED', 'bwrap is needed for --network none')
        command = [helper, '--bind', '/', '/', '--unshare-net', '--', *command]
    environment = dict(kw.pop('env', None) or os.environ)
    environment.update({key: _ce.localise_mounted_paths(value, mounts)
                        for key, value in variables.items()})
    if provider is not None and provider.librelane_root:
        environment['PYTHONPATH'] = os.pathsep.join(
            [provider.librelane_root, environment.get('PYTHONPATH', '')]).rstrip(os.pathsep)
        environment['PATH'] = str(Path(provider.executable).parent) + os.pathsep + environment.get('PATH', '')
    if provider is not None or any(value is not None for value in (memory, cpus, pids_limit)):
        # Apply native limits in a separate launcher.  A
        # preexec_fn in a supervised/threaded parent can deadlock after fork;
        # this launcher sets limits and immediately execs the bound command.
        launcher = (
            'import os,resource,sys\n'
            'memory,cpus=map(int,sys.argv[1:3])\n'
            'def cap(kind,requested):\n'
            '    limits=(requested,*resource.getrlimit(kind))\n'
            '    bound=min(value for value in limits if value!=resource.RLIM_INFINITY)\n'
            '    resource.setrlimit(kind,(bound,bound))\n'
            'if memory>0: cap(resource.RLIMIT_AS,memory)\n'
            'if cpus>0: os.sched_setaffinity(0,sorted(os.sched_getaffinity(0))[:cpus])\n'
            'os.execvpe(sys.argv[3],sys.argv[3:],os.environ)')
        executable = provider.executable if provider is not None else sys.executable
        command = [executable, '-c', launcher, str(memory or 0), str(cpus or 0),
                   *command]
    if provider is not None:
        environment['VIBEIC_LOCAL_MEMORY_LIMIT_BYTES'] = str(memory)
        environment['VIBEIC_LOCAL_NETWORK_MODE'] = provider.network_mode
    _ce.local_exec_mode('librelane_contract')
    with _ce.local_engine_cwd() as scratch:
        if child_cwd is None:
            kw.setdefault('cwd', scratch)
        scope_started = None
        if pids_limit is not None:
            scope_runner = shutil.which('systemd-run', path=environment.get('PATH'))
            if scope_runner is None:
                raise Refusal('LL_LOCAL_PIDS_LIMIT_UNENFORCEABLE',
                              'systemd-run is unavailable for the requested TasksMax')
            # Runtime startup handshake, removed with this invocation's scratch.
            # A failed scope launch must not be mistaken for the tool's own rc.
            scope_started = Path(scratch) / 'pids-scope-started'
            # Keep tool argv literal even on systemd versions which expand $.
            scope_argv = Path(scratch) / 'pids-scope-argv.json'
            scope_argv.write_text(json.dumps(command))
            scoped_launcher = (
                'import json,os,sys\n'
                'from pathlib import Path\n'
                'group=next(line.split(":",2)[2].strip() for line in '
                'Path("/proc/self/cgroup").read_text().splitlines() if line.startswith("0::"))\n'
                'actual=(Path("/sys/fs/cgroup")/group.lstrip("/")/"pids.max").read_text().strip()\n'
                'wanted=int(sys.argv[2])\n'
                'if wanted>=0 and (actual=="max" or int(actual)>wanted):\n'
                '    raise SystemExit("requested cgroup pids.max was not applied")\n'
                'command=json.loads(Path(sys.argv[3]).read_text())\n'
                'Path(sys.argv[1]).touch()\n'
                'os.execvpe(command[0],command,os.environ)')
            tasks_max = 'infinity' if pids_limit == -1 else str(pids_limit)
            command = [scope_runner, '--user', '--scope', '-q', '-p',
                       f'TasksMax={tasks_max}', '--', executable, '-c',
                       scoped_launcher, str(scope_started), str(pids_limit), str(scope_argv)]
        import _watchdog as _wd
        # A LOCAL probe allocation is an observable budget, not permission to
        # kill a progressing native process.  Only measured stillness permits
        # the owned process-group reap, for probes and tool sessions alike.
        budget = TOOL_BUDGET_S if probe_deadline_s is None else probe_deadline_s
        grace = (TOOL_STALL_GRACE_S if TOOL_STALL_GRACE_S is not None
                 else _wd.DEFAULT_STALL_GRACE_S)
        watched = _wd.run_host_supervised(
            command, env=environment, stall_grace_s=grace,
            hard_ceiling_s=budget,
            ceiling_notice=_ce.default_ceiling_notice(
                'LOCAL LibreLane', budget), **kw)
        if scope_started is not None and not scope_started.is_file():
            raise Refusal('LL_LOCAL_PIDS_LIMIT_UNENFORCEABLE',
                          f'could not start a user scope with TasksMax={tasks_max}; '
                          f'{_salvage(watched.out, watched.err, log)}')
        if watched.outcome == 'stalled':
            raise Refusal('LL_TOOL_STALLED',
                          f'LOCAL tool made no progress for {grace:g} s; '
                          f'{_salvage(watched.out, watched.err, log)}')
        result = _wd.completed_process(command, watched)
    return result


def _local_config_source(source: Path, mounts: list[tuple[Path, str]], *,
                         local: bool | None = None) -> Path:
    """Project a declared config's mount paths without changing its bytes."""
    if local is None:
        local = _ce.no_container_route()
    if not local:
        return source
    mapping = [(guest, str(host.resolve())) for host, guest in mounts]
    def paths(value):
        if isinstance(value, str):
            return _ce.localise_mounted_paths(value, mapping)
        if isinstance(value, list):
            return [paths(item) for item in value]
        if isinstance(value, dict):
            return {key: paths(item) for key, item in value.items()}
        return value
    native = source.with_name(source.stem + '.local.json')
    write_json(native, paths(_load(source)))
    return native


#: The refusals that say the TOOL was stopped, not what the design is, and the
#: `verdict.ReasonClass` value a consumer books them NOT_MEASURED with.
#: `run_container` raises both: a supervised tool step that made no progress
#: (container CPU and output flat for the stall grace) and a probe that passed
#: its deadline. The tool never answered, so neither is a FAIL; every other
#: refusal keeps whatever its consumer already decides.
TOOL_STOP_REASONS = {'LL_TOOL_STALLED': 'stalled',
                     'LL_TOOL_DEADLINE': 'budget_exhausted'}


def tool_stop_reason(code: str | None) -> str | None:
    """The NOT_MEASURED reason class for a tool-stop refusal code, else None."""
    return TOOL_STOP_REASONS.get(code) if code else None


def _tool_stop_session_rcs() -> dict[str, int]:
    """Each stop as the exit code a PnR session reports for the same event:
    the watchdog's stall kill and 124 reserved for a child probe deadline.
    The session watchdog itself never kills at its recorded ceiling. A chain that runs inside
    step_pnr's session (steps 19/20, 21) answers with these, so step_pnr books
    its own stall and a LibreLane stall by one rule."""
    import _watchdog as _wd
    return {'LL_TOOL_STALLED': _wd.RC_STALLED, 'LL_TOOL_DEADLINE': 124}


def tool_stop_session_rc(code: str | None) -> int | None:
    """The session exit code for a tool-stop refusal code, else None."""
    return _tool_stop_session_rcs().get(code) if code else None


def session_stop_reason(rc: int | None, evidence: str = "") -> str | None:
    """Classify a stop only when this invocation names its source.

    A tool may exit 124 or 199 naturally. The watchdog's own stall note or
    the route/CTS refusal line is required; the recorded ceiling cannot
    produce 124 since it is advisory.
    """
    import re
    if rc == _tool_stop_session_rcs()['LL_TOOL_STALLED']:
        if 'WATCHDOG_STALLED:' in evidence or re.search(
                r'(?m)^PNR_(?:ROUTE|CTS_HOLD)_REFUSED LL_TOOL_STALLED:', evidence):
            return TOOL_STOP_REASONS['LL_TOOL_STALLED']
    if rc == _tool_stop_session_rcs()['LL_TOOL_DEADLINE']:
        if re.search(r'(?m)^PNR_(?:ROUTE|CTS_HOLD)_REFUSED LL_TOOL_DEADLINE:',
                     evidence):
            return TOOL_STOP_REASONS['LL_TOOL_DEADLINE']
    return None


#: How every container this module (and librelane_signoff) starts is bounded.
#: Two kinds, bounded two different ways:
#:
#: * a PROBE (an image probe, a config resolution, a script or flow read) has
#:   an allocated budget, `PROBE_DEADLINE_S` (llv1 W16a). A remote Docker
#:   transport can remove its named container at that deadline; typed LOCAL
#:   execution records the budget but only measured stillness permits a reap;
#: * a TOOL STEP (a LibreLane step, an OpenROAD session, an STA run) is never
#:   stopped on a clock (owner ruling vibe-ic#2051/R4). It runs under the
#:   repo's progress-stall watchdog (`_watchdog.run_host_supervised`), which
#:   watches the container's own CPU and the tool's output and reaps, by name,
#:   only a container in which neither moved for the stall grace
#:   (`_watchdog.DEFAULT_STALL_GRACE_S` unless `TOOL_STALL_GRACE_S` is set).
#:   `TOOL_BUDGET_S` is the recorded budget (`_watchdog.DEFAULT_HARD_CEILING_S`):
#:   crossing it is announced on stderr and written into the run's stderr as a
#:   `VIBEIC_CEILING_CROSSED` line; it kills nothing.
PROBE_DEADLINE_S = 600
TOOL_BUDGET_S = 86_400
#: The refusals caused by TIME, not by the design or by a tool verdict: a remote
#: probe past its deadline, or a tool the watchdog reaped as stalled. Only a
#: plain FAIL is red, so a consumer books these NOT_MEASURED with the refusal.
TIME_REFUSALS = frozenset(TOOL_STOP_REASONS)
TOOL_STALL_GRACE_S: float | None = None
_REAP_DEADLINE_S = 30
_OUTPUT_TAIL = 2000


def _as_text(stream: Any) -> str:
    if stream is None:
        return ''
    return stream.decode(errors='replace') if isinstance(stream, bytes) else str(stream)


def _salvage(out: Any, err: Any, log: Path | None) -> str:
    """Keep what the tool printed before it was stopped: in `log` when the caller
    names one (the log it would have written), else a tail in the refusal."""
    text = _as_text(out) + '\n' + _as_text(err)
    if log is not None:
        log.parent.mkdir(parents=True, exist_ok=True)
        log.write_text(text)
        return f'partial output in {log}'
    tail = text.strip()[-_OUTPUT_TAIL:]
    return f'partial output: {tail!r}' if tail else 'no output'


def _reap(binary: str, name: str) -> str:
    """Remove container `name` and SAY whether that worked."""
    try:
        done = subprocess.run([binary, 'rm', '-f', name], capture_output=True, text=True,
                              timeout=_REAP_DEADLINE_S)
    except (OSError, subprocess.SubprocessError) as exc:
        return f'NOT removed ({type(exc).__name__}: {exc})'
    if done.returncode == 0:
        return 'removed'
    if 'no such container' in (done.stderr or '').lower():
        return 'already gone'
    return f'NOT removed (rc={done.returncode}: {(done.stderr or "").strip()[:200]})'


class _Client:
    """A `docker run` client, launched through `subprocess.run` on a thread and
    shaped like the Popen `_watchdog.run_supervised` drives.

    `subprocess.run` stays this module's one subprocess edge (the edge its
    tests substitute), and the watchdog supervises it from outside: the
    client's stdout/stderr go straight into the watchdog's files, so output is
    a live progress signal; the container's CPU is read by NAME; and the stop
    is the reap by NAME, after which the client returns on its own. `kill` is
    therefore a no-op here -- the client holds no work of its own."""

    def __init__(self, cmd: list[str], *, stdout: Any = None, stderr: Any = None,
                 env: Any = None, cwd: Any = None) -> None:
        import threading
        self.returncode: int | None = None
        self.error: BaseException | None = None  # re-raised by run_container
        self.pid = None
        kw: dict[str, Any] = {'stdout': stdout, 'stderr': stderr}
        if env is not None:
            kw['env'] = env
        if cwd is not None:
            kw['cwd'] = cwd

        def work() -> None:
            try:
                done = subprocess.run(cmd, **kw)
                rc = done.returncode
                for stream, sink in ((getattr(done, 'stdout', None), stdout),
                                     (getattr(done, 'stderr', None), stderr)):
                    if stream and hasattr(sink, 'write'):  # an edge that returned its streams
                        sink.write(stream.encode() if isinstance(stream, str) else stream)
                        sink.flush()
            except BaseException as exc:  # noqa: BLE001 -- raised again in the caller's thread
                self.error, rc = exc, 127
            self.returncode = rc
        self._thread = threading.Thread(target=work, name=f'vibeic-ll-{cmd[0]}', daemon=True)
        self._thread.start()

    def poll(self) -> int | None:
        return None if self._thread.is_alive() else self.returncode

    def wait(self, timeout: float | None = None) -> int | None:
        self._thread.join(timeout)
        if self._thread.is_alive():
            raise subprocess.TimeoutExpired('docker run', timeout)
        return self.returncode

    def kill(self) -> None:
        pass


def _image_entrypoint(docker: str, image: str) -> Any:
    """Read the local image's declared launch interface before starting tools."""
    try:
        inspected = subprocess.run(
            [docker, 'image', 'inspect', image, '--format',
             '{{json .Config.Entrypoint}}'],
            capture_output=True, text=True, timeout=30)
        if inspected.returncode:
            raise ValueError(inspected.stderr.strip())
        return json.loads(inspected.stdout)
    except (OSError, subprocess.SubprocessError, ValueError) as exc:
        raise Refusal('LL_IMAGE_ENTRYPOINT_UNAVAILABLE', str(exc)) from exc


def _image_tool_argv(argv: list[str], *, image: str | None = None) -> list[str]:
    """Preserve the selected image's environment when entering a native tool.

    Older images enter their tool environment via ui_startup.sh --skip; native
    images have no entrypoint and execute the tool directly. Never infer this
    distinction from a mutable tag, version string, or a failed tool launch.
    A caller with its own validated image binding may supply that exact token
    when its resource options exceed the narrow shared argv parser.
    """
    if image is None:
        image = _container_image_arg(argv)
    elif argv.count(image) != 1:
        raise Refusal('LL_IMAGE_TOKEN_AMBIGUOUS', 'declared image must occur exactly once')
    if image is None:
        return list(argv)
    at = argv.index(image)
    head, command = list(argv[:at]), list(argv[at + 1:])
    if '--entrypoint' in head:
        index = head.index('--entrypoint')
        command = [head[index + 1], *command]
        del head[index:index + 2]
    elif command[:1] == ['--skip']:
        command = command[1:]
    else:
        return list(argv)
    entrypoint = _image_entrypoint(argv[0], str(image))
    if entrypoint is None or entrypoint == []:
        prefix = []
    elif entrypoint == ['/dockerstartup/scripts/ui_startup.sh']:
        prefix = ['--skip']
    else:
        raise Refusal('LL_IMAGE_ENTRYPOINT_UNSUPPORTED', repr(entrypoint))
    return [*head, image, *prefix, *command]


def run_container(argv: list[str], *, probe_deadline_s: float | None = None,
                  supervised: bool = False, log: Path | None = None,
                  **kw: Any) -> subprocess.CompletedProcess:
    """Run one `docker run` argv, named so it can be removed by that name.

    Exactly one bound, stated by the caller:
      * ``probe_deadline_s=`` -- a probe allocation. Remote Docker removes its
        named container at the deadline; typed LOCAL records the same budget
        but never kills progress, and reaps only on measured stillness;
      * ``supervised=True`` -- a tool step: `_watchdog.run_host_supervised`
        with the ephemeral-container CPU probe and reap-by-name; a stall
        raises `LL_TOOL_STALLED`, and nothing else stops the job.
    Either refusal names the container's fate and keeps the tool's partial
    output (in ``log`` when given), and a stall names the signals the watchdog
    actually read. Callers read `.returncode` / `.stdout` / `.stderr` as before.

    The container's CPU is read from the HOST: `docker inspect` gives the
    container's init pid, and `_watchdog.host_tree_progress` sums CPU and I/O
    over that pid's host-side tree -- every process the container runs. No
    `docker exec` is involved, so no attach guard can blind it (an image other
    than the pinned runtime is read like any other).
    """
    if (probe_deadline_s is None) == (not supervised):
        raise ValueError('run_container: pass exactly one of probe_deadline_s= or supervised=True')
    image_arg = _container_image_arg(argv)
    provider = _provider_for_image(image_arg)
    mismatch = _provider_route_mismatch(image_arg)
    if mismatch is not None:
        raise mismatch
    if provider is not None:
        return _run_local(list(argv), probe_deadline_s=probe_deadline_s,
                          supervised=supervised, log=log, provider=provider, **kw)
    if _ce.no_container_route():
        return _run_local(list(argv), probe_deadline_s=probe_deadline_s,
                          supervised=supervised, log=log, **kw)
    argv = _image_tool_argv(argv)
    import _docker_watchdog as _dw  # the one naming rule for ephemeral containers
    at = argv.index('run') + 1
    binary = argv[0]
    name = _dw.ephemeral_container_name('vibeic_ll')
    named = [*argv[:at], '--name', name, *argv[at:]]
    if probe_deadline_s is not None:
        try:
            return subprocess.run(named, capture_output=True, text=True, timeout=probe_deadline_s, **kw)
        except subprocess.TimeoutExpired as exc:
            fate = _reap(binary, name)
            raise Refusal('LL_TOOL_DEADLINE', f'{binary} run passed its {probe_deadline_s:g} s probe '
                          f'deadline; container {name} {fate}; '
                          f'{_salvage(exc.stdout, exc.stderr, log)}') from exc
    import _watchdog as _wd

    def rebound(cmd: list[str], **k: Any) -> subprocess.CompletedProcess:
        # The watchdog helpers spell the client `docker`; use the caller's.
        return subprocess.run([binary, *cmd[1:]] if cmd and cmd[0] == 'docker' else cmd, **k)
    grace = TOOL_STALL_GRACE_S if TOOL_STALL_GRACE_S is not None else _wd.DEFAULT_STALL_GRACE_S
    import time
    started, first_read_s = time.monotonic(), min(_wd.DEFAULT_POLL_S, grace / 4.0)
    init_pid: dict[str, int] = {}

    def cpu_probe(proc: Any) -> float | None:
        # The client is still creating the container in its first poll window,
        # so there is nothing to read yet; a job that ends inside that window
        # is never probed at all.
        if time.monotonic() - started < first_read_s or proc.poll() is not None:
            return None
        if 'pid' not in init_pid:
            try:
                done = subprocess.run([binary, 'inspect', '-f', '{{.State.Pid}}', name],
                                      capture_output=True, text=True, timeout=_REAP_DEADLINE_S)
                pid = int((done.stdout or '').strip() or 0)
            except (OSError, subprocess.SubprocessError, ValueError):
                return None
            if pid <= 0:
                return None  # not started yet, or already gone: no reading, never zero
            init_pid['pid'] = pid
        return _wd.host_tree_progress(init_pid['pid'])
    clients: list[_Client] = []

    def launch(cmd: list[str], **k: Any) -> _Client:
        clients.append(_Client(cmd, **k))
        return clients[-1]
    result = _wd.run_host_supervised(
        named, popen_factory=launch, kill=_dw.ephemeral_container_reap(name, runner=rebound),
        cpu_probe=cpu_probe, stall_grace_s=grace, hard_ceiling_s=TOOL_BUDGET_S,
        ceiling_notice=_ce.default_ceiling_notice(name, TOOL_BUDGET_S), **kw)
    if clients and clients[0].error is not None:
        raise clients[0].error  # what `subprocess.run` raised (no docker client, ...)
    seen = result.supervision or {}
    err = result.err
    if seen.get('hard_ceiling_exceeded'):
        # The budget is a RECORD (#2051): it lands in the log the caller writes.
        err += (f'\n{_ce.CEILING_CROSSED_MARK} container={name} budget_s={TOOL_BUDGET_S:g} '
                f'crossed_at_s={float(seen.get("hard_ceiling_crossed_s") or 0):.0f} '
                f'-- recorded, not a kill: the run went on.\n')
    if result.outcome == 'stalled':
        watched = str(seen.get('watched') or 'unknown')
        flat = ('container CPU and output flat' if 'cpu:unreadable' not in watched
                else 'output flat; container CPU unreadable')
        fate = _reap(binary, name)
        if fate == 'already gone':
            fate = "removed by the watchdog's reap"
        raise Refusal('LL_TOOL_STALLED', f'{binary} run made no progress ({flat}; watched={watched}) '
                      f'for {grace:g} s; container {name} {fate}; '
                      f'{_salvage(result.out, err, log)}')
    return subprocess.CompletedProcess(named, result.rc, result.out, err)

def digest(path: Path) -> str:
    h = hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()


def _load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text())
    if not isinstance(value, dict):
        raise Refusal('LL_INVALID_JSON_OBJECT', str(path))
    return value


def project_path(project: Path, value: str | Path) -> Path:
    """Resolve a State's project view after moving a run; leave PDK assets alone."""
    project, path = Path(project).resolve(), Path(value)
    if not path.is_absolute():
        return project / path
    if path.is_relative_to(project):
        return path
    for index, part in enumerate(path.parts):
        if part in ("phase1", "phase2", "phase3", "reports", "input", "requirements", "adopted"):
            local = project.joinpath(*path.parts[index:])
            if local.exists():
                return local
    return path


def _set(out: dict, provenance: dict, key: str, value: Any, source: str) -> None:
    if value is None or value in ('NOT_DETERMINED', 'NOT_MEASURED', ''):
        return
    out[key] = value
    provenance[key] = source


#: The L-docs `emit_config` consumes, by EXACT name. A prefix match lets one
#: document stand in for another (D1: `L8_TIMING_WAVEFORM` satisfied an `L8_`
#: slot while `L8_RTL_CONSTANTS` was absent, and the clauses reading it SKIPPED).
EMIT_CONFIG_LDOCS = ('L8_TIMING_WAVEFORM.json', 'L9_INTEGRATION_SPEC.json',
                     'L19_CONSTRAINTS_PDK.json')
DECLARATION_REL = 'input/submission_template/tapeout_declaration.json'
SLOTS_REL = 'input/submission_template/slots'


def _ldoc(root: Path, name: str) -> dict[str, Any]:
    path = root / name
    if not path.is_file():
        raise Refusal('LL_LDOC_MISSING', f'{name} (emit_config reads it by exact name)')
    return _load(path)


def _rect(value: Any, key: str) -> list[float | int]:
    if not (isinstance(value, list) and len(value) == 4 and
            all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in value)
            and value[0] < value[2] and value[1] < value[3]):
        raise Refusal('LL_DECLARATION_RECT_INVALID', f'{key}: {value!r}')
    return value


def _def_die_area(path: Path) -> list[float] | None:
    """DIEAREA of a DEF template in microns, or None when it states none."""
    text = path.read_text(errors='replace')
    units = re.search(r'^\s*UNITS\s+DISTANCE\s+MICRONS\s+(\d+)\s*;', text, re.M)
    area = re.search(r'^\s*DIEAREA((?:\s*\(\s*-?\d+\s+-?\d+\s*\))+)\s*;', text, re.M)
    if not (units and area):
        return None
    points = [(int(x), int(y)) for x, y in re.findall(r'\(\s*(-?\d+)\s+(-?\d+)\s*\)', area.group(1))]
    scale = int(units.group(1))
    xs, ys = [x for x, _ in points], [y for _, y in points]
    return [min(xs) / scale, min(ys) / scale, max(xs) / scale, max(ys) / scale]


def _slot_def_template(project: Path) -> tuple[str, str] | None:
    """The operator slot's own ``FP_DEF_TEMPLATE``, as (dir:: path, source)."""
    import yaml
    found: dict[str, str] = {}
    slots = project / SLOTS_REL
    for slot in sorted(list(slots.glob('*.yaml')) + list(slots.glob('*.yml'))):
        try:
            mapping = yaml.safe_load(slot.read_text())
        except (OSError, yaml.YAMLError) as exc:
            raise Refusal('LL_SLOT_UNREADABLE', f'{slot}: {exc}') from exc
        value = mapping.get('FP_DEF_TEMPLATE') if isinstance(mapping, dict) else None
        if value in (None, ''):
            continue
        raw = str(value)
        raw = raw[5:] if raw.startswith('dir::') else raw
        template = (slot.parent / raw).resolve()
        if not template.is_file() or not template.is_relative_to(project.resolve()):
            raise Refusal('LL_DEF_TEMPLATE_MISSING', f'{slot.name}: {value}')
        found[str(template)] = (f'{slot.relative_to(project)}.FP_DEF_TEMPLATE '
                                f'(sha256:{digest(template)})')
    if len(found) > 1:
        raise Refusal('LL_DEF_TEMPLATE_AMBIGUOUS', ', '.join(sorted(found)))
    if not found:
        return None
    path, source = next(iter(found.items()))
    return 'dir::' + str(Path(path).relative_to(project.resolve())), source


#: Declaration pad answers -> the LibreLane variables the pad producer writes.
_PAD_ANSWERS = {'pad_site_name': 'PAD_SITE_NAME',
                'pad_corner_site_name': 'PAD_CORNER_SITE_NAME',
                'pad_edge_spacing_um': 'PAD_EDGE_SPACING',
                'pad_fillers': 'PAD_FILLERS'}


def declaration_config(project: Path) -> tuple[dict[str, Any], dict[str, str]]:
    """Step 0.5ic -> LibreLane: the declared die, core and pads as config.

    Every value is read through ``_tapeout_declaration.answer`` -- the one
    reader, which withholds an owner-only answer nobody attested -- never out
    of ``answers`` directly. A HARDMACRO's own rectangle is ``macro_area_um``;
    its ``die_area_um`` is a question it does not owe (vibe-ic#2118). A die
    whose declared ``fp_sizing`` is ``relative`` was DERIVED from a
    utilisation, so its rectangles are not emitted as the truth.
    """
    import _tapeout_declaration as TD
    source = DECLARATION_REL.removesuffix('.json') + '.answers.'
    doc = _load(project / DECLARATION_REL)
    result: dict[str, Any] = {}
    sources: dict[str, str] = {}
    answered = {key: TD.answer(doc, key) for key in (
        'deliverable', 'top_cell', 'die_area_um', 'core_area_um', 'fp_sizing',
        'die_origin_um', 'macro_area_um', 'pad_order_by_side', 'pad_rotations',
        'pad_corner_master', *_PAD_ANSWERS)}
    given = {k: v for k, v in answered.items() if v != TD.NOT_DETERMINED}
    _set(result, sources, 'DESIGN_NAME', given.get('top_cell'), source + 'top_cell')
    sizing = given.get('fp_sizing')
    if sizing is not None and sizing not in ('absolute', 'relative'):
        raise Refusal('LL_DECLARATION_FP_SIZING_INVALID', repr(sizing))
    if given.get('deliverable') == TD.DELIVERABLE_HARDMACRO:
        if 'macro_area_um' in given:
            _set(result, sources, 'DIE_AREA', _rect(given['macro_area_um'], 'macro_area_um'),
                 source + 'macro_area_um (deliverable HARDMACRO)')
    elif sizing != 'relative':
        if 'die_area_um' in given:
            die = _rect(given['die_area_um'], 'die_area_um')
            origin = given.get('die_origin_um')
            if isinstance(origin, list) and len(origin) == 2 and list(die[:2]) != list(origin):
                raise Refusal('LL_DECLARATION_ORIGIN_MISMATCH',
                              f'die_area_um {die} vs die_origin_um {origin}')
            _set(result, sources, 'DIE_AREA', die, source + 'die_area_um')
        if 'core_area_um' in given:
            core = _rect(given['core_area_um'], 'core_area_um')
            die = result.get('DIE_AREA')
            if die and not (core[0] >= die[0] and core[1] >= die[1] and
                            core[2] <= die[2] and core[3] <= die[3]):
                raise Refusal('LL_DECLARATION_CORE_OUTSIDE_DIE', f'{core} vs {die}')
            _set(result, sources, 'CORE_AREA', core, source + 'core_area_um')
    if sizing is not None:
        _set(result, sources, 'FP_SIZING', sizing, source + 'fp_sizing')
    elif 'DIE_AREA' in result:
        _set(result, sources, 'FP_SIZING', 'absolute', sources['DIE_AREA'])
    order = given.get('pad_order_by_side')
    if isinstance(order, dict):
        for side in ('south', 'east', 'north', 'west'):
            if isinstance(order.get(side), list):
                _set(result, sources, 'PAD_' + side.upper(), order[side],
                     f'{source}pad_order_by_side.{side}')
    rotations = given.get('pad_rotations')
    if isinstance(rotations, dict):
        for axis in ('horizontal', 'vertical', 'corner'):
            _set(result, sources, 'PAD_ROTATION_' + axis.upper(), rotations.get(axis),
                 f'{source}pad_rotations.{axis}')
    if isinstance(given.get('pad_corner_master'), str):
        _set(result, sources, 'PAD_CORNER', [given['pad_corner_master']],
             source + 'pad_corner_master')
    for answer_key, key in _PAD_ANSWERS.items():
        _set(result, sources, key, given.get(answer_key), source + answer_key)
    template = _slot_def_template(project)
    if template:
        path, origin = template
        _set(result, sources, 'FP_DEF_TEMPLATE', path, origin)
        die = _def_die_area(project / path[5:])
        if die is not None and 'DIE_AREA' in result and \
                any(abs(a - b) > 1e-6 for a, b in zip(die, result['DIE_AREA'])):
            raise Refusal('LL_DEF_TEMPLATE_DIE_MISMATCH',
                          f'{path} DIEAREA {die} vs declared {result["DIE_AREA"]}')
    return result, sources


def settled_floorplan_geometry(project: Path) -> tuple[list[float | int],
                                                         list[float | int], str]:
    """Read settled die/core geometry from the native config, State and DEF."""
    project = Path(project).resolve()
    import _declared_die as DD

    record_path = Path(project) / DD.FLOORPLAN_RECTANGLES_REL
    try:
        record = _load(record_path)
    except (OSError, ValueError, Refusal) as exc:
        raise Refusal('LL_FLOORPLAN_CORE_PROVENANCE',
                      f'{record_path}: {type(exc).__name__}: {exc}') from exc

    def rect(value: Any, name: str, *, numeric_strings: bool = False) -> list[float]:
        def number(v: Any) -> float | None:
            if isinstance(v, bool) or not isinstance(v, (int, float, str)):
                return None
            if isinstance(v, str) and not numeric_strings:
                return None
            try:
                result = float(v)
            except (TypeError, ValueError):
                return None
            return result if math.isfinite(result) else None
        values = [number(v) for v in value] if isinstance(value, (list, tuple)) else []
        if not (len(values) == 4 and all(v is not None for v in values) and
                values[0] < values[2] and values[1] < values[3]):
            raise Refusal('LL_FLOORPLAN_CORE_PROVENANCE',
                          f'{record_path}: invalid {name} {value!r}')
        return [float(v) for v in values]

    die = rect(record.get('die_rect_um'), 'die_rect_um')
    floorplan = record.get('floorplan_rect_um')
    if floorplan is not None:
        core = rect(floorplan, 'floorplan_rect_um')
        basis = f'{DD.FLOORPLAN_RECTANGLES_REL}.floorplan_rect_um'
    else:
        pad = record.get('core_pad_um')
        if (not isinstance(pad, (int, float)) or isinstance(pad, bool) or
                not math.isfinite(float(pad)) or float(pad) < 0):
            raise Refusal('LL_FLOORPLAN_CORE_PROVENANCE',
                          f'{record_path}: no usable floorplan_rect_um or core_pad_um')
        p = float(pad)
        core = [die[0] + p, die[1] + p, die[2] - p, die[3] - p]
        basis = (f'{DD.FLOORPLAN_RECTANGLES_REL}.die_rect_um inset by '
                 f'{DD.FLOORPLAN_RECTANGLES_REL}.core_pad_um')
    if not (core[0] >= die[0] and core[1] >= die[1] and
            core[2] <= die[2] and core[3] <= die[3]):
        raise Refusal('LL_FLOORPLAN_CORE_PROVENANCE',
                      f'{record_path}: core {core} outside die {die}')

    config_path = Path(project) / 'phase3/librelane/15-config/OpenROAD.Floorplan.json'
    try:
        config = _load(config_path)
    except (OSError, ValueError, Refusal) as exc:
        raise Refusal('LL_FLOORPLAN_CORE_PROVENANCE',
                      f'{config_path}: {type(exc).__name__}: {exc}') from exc
    config_die = rect(config.get('DIE_AREA'), 'OpenROAD.Floorplan DIE_AREA',
                      numeric_strings=True)
    config_core = rect(config.get('CORE_AREA'), 'OpenROAD.Floorplan CORE_AREA',
                       numeric_strings=True)
    if _rect_differs(config_die, die) or _rect_differs(config_core, core):
        raise Refusal('LL_FLOORPLAN_CORE_PROVENANCE',
                      f'{config_path}: resolved geometry {config_die}/{config_core} '
                      f'differs from {record_path} {die}/{core}')
    design_name = config.get('DESIGN_NAME')
    if (not isinstance(design_name, str) or not design_name or
            Path(design_name).name != design_name):
        raise Refusal('LL_FLOORPLAN_CORE_PROVENANCE',
                      f'{config_path}: invalid DESIGN_NAME {design_name!r}')

    step = Path(project) / 'phase3/librelane/15-floorplan/02-openroad-floorplan'
    state_path = step / 'state_out.json'
    resolved_config_path = step / 'config.json'
    try:
        state = _load(state_path)
        resolved = _load(resolved_config_path)
    except (OSError, ValueError, Refusal) as exc:
        raise Refusal('LL_FLOORPLAN_CORE_PROVENANCE',
                      f'{step}: incomplete native Floorplan output: '
                      f'{type(exc).__name__}: {exc}') from exc
    if resolved.get('DIE_AREA') != [int(v) if v.is_integer() else v for v in die] or \
            resolved.get('CORE_AREA') != [int(v) if v.is_integer() else v for v in core]:
        raise Refusal('LL_FLOORPLAN_CORE_PROVENANCE',
                      f'{resolved_config_path}: resolved geometry differs')
    if resolved.get('DESIGN_NAME') != design_name:
        raise Refusal('LL_FLOORPLAN_CORE_PROVENANCE',
                      f'{resolved_config_path}: DESIGN_NAME {resolved.get("DESIGN_NAME")!r} '
                      f'differs from {config_path} {design_name!r}')
    state_def = state.get('def')
    if not isinstance(state_def, str) or not state_def:
        raise Refusal('LL_FLOORPLAN_CORE_PROVENANCE',
                      f'{state_path}: missing resolved DEF for DESIGN_NAME {design_name!r}')
    recorded_def = Path(state_def)
    expected_def_name = f'{design_name}.def'
    if recorded_def.name != expected_def_name:
        raise Refusal('LL_FLOORPLAN_CORE_PROVENANCE',
                      f'{state_path}: DEF {state_def!r} is not the resolved '
                      f'{design_name}.def in {step}')
    # A readback may bind the same producer under a different container path.
    # When the recorded path is under this project, retain the stronger exact
    # relative-path check; otherwise require the complete producer-step suffix
    # (never a directory glob or an unrelated same-named DEF).
    project_root = Path(project).resolve()
    try:
        recorded_rel = (recorded_def.resolve() if recorded_def.is_absolute()
                        else (step / recorded_def).resolve()).relative_to(project_root)
    except (OSError, ValueError):
        recorded_rel = None
    expected_rel = step.resolve().relative_to(project_root) / expected_def_name
    if recorded_rel is not None and recorded_rel != expected_rel:
        raise Refusal('LL_FLOORPLAN_CORE_PROVENANCE',
                      f'{state_path}: DEF {state_def!r} is outside the '
                      f'resolved producer path {expected_rel}')
    if recorded_rel is None:
        suffix = tuple(expected_rel.parts)
        if (recorded_def.is_absolute() and
                tuple(recorded_def.parts[-len(suffix):]) != suffix) or \
                (not recorded_def.is_absolute() and recorded_def != Path(expected_def_name)):
            raise Refusal('LL_FLOORPLAN_CORE_PROVENANCE',
                          f'{state_path}: DEF {state_def!r} is not bound to '
                          f'the resolved producer path {expected_rel}')
    def_path = (step / expected_def_name).resolve()
    metrics = state.get('metrics') or {}
    if not metrics.get('design__die__bbox') or not metrics.get('design__core__bbox'):
        raise Refusal('LL_FLOORPLAN_CORE_PROVENANCE',
                      f'{state_path}: missing settled die/core metrics')
    def metric_rect(value: Any, name: str) -> list[float]:
        raw = ([str(v) for v in value] if isinstance(value, (list, tuple))
               else re.findall(r'-?(?:\d+(?:\.\d*)?|\.\d+)', str(value)))
        try:
            values = [float(v) for v in raw]
        except (TypeError, ValueError):
            values = []
        if (len(values) != 4 or not all(math.isfinite(v) for v in values) or
                values[0] >= values[2] or values[1] >= values[3]):
            raise Refusal('LL_FLOORPLAN_CORE_PROVENANCE',
                          f'{state_path}: invalid {name} {value!r}')
        return values
    state_die = metric_rect(metrics['design__die__bbox'], 'die metric')
    state_core = metric_rect(metrics['design__core__bbox'], 'core metric')
    if _rect_differs(state_die, die) or not (
            state_core[0] >= die[0] and state_core[1] >= die[1] and
            state_core[2] <= die[2] and state_core[3] <= die[3] and
            state_core[0] >= core[0] and state_core[1] >= core[1] and
            state_core[2] <= core[2] and state_core[3] <= core[3]):
        raise Refusal('LL_FLOORPLAN_CORE_PROVENANCE',
                      f'{state_path}: settled metrics {state_die}/{state_core} '
                      f'do not fit {die}/{core}')
    if _def_design_name(def_path) != design_name:
        raise Refusal('LL_FLOORPLAN_CORE_PROVENANCE',
                      f'{def_path}: DESIGN does not match resolved DESIGN_NAME '
                      f'{design_name!r}')
    def_die = DD.def_diearea_um(def_path.read_text(errors='replace'))
    if def_die is None or _rect_differs(def_die, die):
        raise Refusal('LL_FLOORPLAN_CORE_PROVENANCE',
                      f'{def_path}: DIEAREA {def_die} differs from {die}')
    source = (f'{basis}; native {resolved_config_path.relative_to(project)} '
              f'(DESIGN_NAME={design_name}, DEF={def_path.relative_to(project)})')
    return _whole(die), _whole(core), source


def settled_floorplan_core(project: Path) -> tuple[list[float | int], str]:
    """Compatibility view of :func:`settled_floorplan_geometry`."""
    _die, core, source = settled_floorplan_geometry(project)
    return core, source


def aux_tie_dont_touch(chip_top_record: dict[str, Any]) -> list[str]:
    """The pad-control tie identities the chip-top producer declared (F23).

    Each `aux_pin_signal_connections` row names a tie instance and the net
    that joins it to one pad control pin; post-layout LEC proves exactly that
    instance/pin on exactly that net. LibreLane's RepairDesignPostGPL runs
    `repair_tie_fanout` (DESIGN_REPAIR_TIE_FANOUT), which deletes each tie and
    re-drives its load from a clone on a fresh net. MEASURED on spm x gf180mcuD
    (0.3.79): all 76 declared ties were replaced (`u_pad_clk/PD` on `net`), and
    with these names `set_dont_touch` the same call inserted 0 ties and every
    declared net survived. So they reach RSZ_DONT_TOUCH_LIST, which LibreLane's
    resizer steps apply before repairing.
    """
    rows = chip_top_record.get('aux_pin_signal_connections') or []
    if not isinstance(rows, list):
        raise Refusal('LL_AUX_TIE_RECORD_INVALID',
                      'io_pad_chip_top.json.aux_pin_signal_connections is not a list')
    names: list[str] = []
    for index, row in enumerate(rows):
        values = [row.get(k) for k in ('tie_instance', 'net')] if isinstance(row, dict) else []
        if len(values) != 2 or not all(isinstance(v, str) and v for v in values):
            raise Refusal('LL_AUX_TIE_RECORD_INVALID',
                          f'aux_pin_signal_connections[{index}] names no tie_instance/net')
        # A constant output built into the pad is already that pad instance.
        # Protect its control net, not the whole GPIO: freezing the GPIO also
        # prevents repair_design from inserting a buffer on its core data
        # input (RSZ-3006). Separate core tie cells retain both protections.
        protected = values[1:] if values[0] == row.get('instance') else values
        names.extend(v for v in protected if v not in names)
    return names


def _declared_flow_settings(l19: dict, pdk: str) -> tuple[dict, dict]:
    """The existing L19 flow-setting parser, shared by emission and reuse.

    Unsupported, inapplicable and unset declarations produce no setting.
    """
    result: dict[str, Any] = {}
    sources: dict[str, str] = {}
    declarations = l19.get('fields', {}).get('constraint_declarations', [])
    supported = {'MAX_FANOUT_CONSTRAINT', 'MAX_TRANSITION_CONSTRAINT',
                 'MAX_CAPACITANCE_CONSTRAINT', 'FP_CORE_UTIL', 'PL_TARGET_DENSITY',
                 'PDN_VOFFSET', 'PDN_HOFFSET', 'PDN_CORE_RING',
                 'PDN_CORE_RING_CONNECT_TO_PADS', 'PDN_SKIPTRIM', 'FP_PDN_SKIPTRIM',
                 'FP_PDN_VOFFSET', 'FP_PDN_HOFFSET', 'PDN_VWIDTH'}
    chosen: dict[str, list[tuple[int, Any, str]]] = {}
    for row in declarations:
        key = row.get('token')
        key = {'SYNTH_MAX_FANOUT': 'MAX_FANOUT_CONSTRAINT'}.get(key, key)
        if key not in supported:
            continue
        scope = row.get('scope')
        if scope and not (fnmatch.fnmatch(pdk.lower(), str(scope).lower()) or
                          pdk.lower().startswith(str(scope).lower().rstrip('*_'))):
            continue
        value = str(row.get('value', '')).strip()
        if value.lower() in ('', '工具預設', 'not_determined'):
            continue
        key = {'FP_PDN_SKIPTRIM': 'PDN_SKIPTRIM', 'FP_PDN_VOFFSET': 'PDN_VOFFSET',
               'FP_PDN_HOFFSET': 'PDN_HOFFSET'}.get(key, key)
        try:
            # Native GeneratePDN consumes this width in micrometres, not a
            # percentage or boolean. Keep omitted/default declarations absent.
            parsed: Any = float(value if key == 'PDN_VWIDTH' else value.rstrip('%'))
            if key == 'PDN_VWIDTH' and (not math.isfinite(parsed) or parsed <= 0):
                raise ValueError('width must be positive and finite')
            if parsed.is_integer():
                parsed = int(parsed)
        except ValueError:
            if key == 'PDN_VWIDTH':
                raise Refusal('LL_PDN_VERTICAL_WIDTH_INVALID',
                              'PDN_VWIDTH must be a positive finite number in um') from None
            if value.lower().startswith('true'):
                parsed = True
            elif value.lower().startswith('false'):
                parsed = False
            else:
                continue
        priority = (2 if scope else 0) + (1 if 'L9_' in str(row.get('source')) else 0)
        chosen.setdefault(key, []).append((priority, parsed, f"L19_CONSTRAINTS_PDK.constraint_declarations:{row.get('source')}:{row.get('line')}"))
    for key, rows in chosen.items():
        priority = max(row[0] for row in rows)
        applicable = [row for row in rows if row[0] == priority]
        if len({str(row[1]) for row in applicable}) != 1:
            raise Refusal('LL_CONSTRAINT_CONFLICT', key)
        _, value, source = applicable[0]
        _set(result, sources, key, value, source)
    return result, sources


def _typed_clock_sdc(clocks: list[dict], groups: Any) -> str:
    """The SDC stated by typed L8 periods and asynchronous clock groups."""
    lines = [f"create_clock -name {c.get('source_pin')} -period {c.get('period_ns')} "
             f"[get_ports {c.get('source_pin')}]" for c in clocks]
    for group in groups if isinstance(groups, list) else []:
        if isinstance(group, dict) and group.get('relationship') == 'asynchronous':
            lines.append('set_clock_groups -asynchronous ' + ' '.join(
                f"-group [get_clocks {clock}]" for clock in group.get('clocks') or []))
    return '\n'.join(lines) + '\n'


def _bound_primary_clocks(project: Path, l9: dict, clocks: list[dict],
                          sdc: Path, clock_groups: Any = None) -> tuple[list[str], str, str]:
    """Bind multiple roots to declared inputs and an explicit asynchronous SDC.

    A binding alone does not license timing cuts. Retain the complete declared
    deck, including waveforms and I/O constraints; refuse unresolved Tcl clock
    declarations rather than guessing their targets or relationships.
    """
    from l_doc_consumer_contract import l9_top_ports, l9_port_direction
    import sdc_constraints

    def refuse(detail: str) -> None:
        raise Refusal('LL_CLOCK_AMBIGUOUS', detail)

    inputs = {p['name'] for p in l9_top_ports(l9)
              if p.get('name') and l9_port_direction(p) == 'in'
              and any(p.get(k) for k in ('dir', 'mode', 'direction'))}
    aliases = {pin: {pin} for pin in inputs}
    l1 = project / 'phase1/generated_docs/L1_DATASHEET.json'
    if l1.is_file():
        for pin in _load(l1).get('pin_table', []):
            target = pin.get('rtl_name')
            if target in inputs:
                for alias in (pin.get('name'), pin.get('board_name'),
                              *(pin.get('aliases') or [])):
                    if isinstance(alias, str) and alias:
                        aliases.setdefault(alias, set()).add(target)

    def resolve(pin: Any) -> str:
        targets = aliases.get(pin, set()) if isinstance(pin, str) else set()
        if len(targets) != 1:
            refuse(f'undeclared or ambiguous top input {pin!r}')
        return next(iter(targets))

    roots = [resolve(c.get('source_pin')) for c in clocks]
    bindings = l9.get('clock_binding')
    if not isinstance(bindings, dict) or not bindings:
        bindings = {f"{row.get('name')}.{port.get('name')}": port.get('net')
                    for row in l9.get('instances') or [] if isinstance(row, dict)
                    for port in row.get('ports') or []
                    if isinstance(port, dict) and port.get('type') == 'clock'}
    if not bindings:
        refuse('multiple primary clocks require L9.clock_binding or typed instance clock ports')
    bound = {resolve(pin) for pin in bindings.values()}
    if len(set(roots)) != len(roots) or not set(roots) <= bound:
        refuse('duplicate or unbound primary clock pins')
    paths = [sdc] if sdc.is_file() else sdc_constraints.collect_sdc_files(project)
    texts = [path.read_text() for path in paths]
    if not texts and clock_groups:
        texts = [_typed_clock_sdc(clocks, clock_groups)]
    # This boundary supports literal clock objects. Complex Tcl remains an
    # explicit refusal; no user script is executed during config emission.
    active = '\n'.join(line.split('#', 1)[0]
                       for text in texts for line in text.replace('\\\n', ' ').splitlines())
    commands = [line.strip() for line in re.split(r'[;\n]', active) if line.strip()]
    clock_commands = [line for line in commands if re.match(r'^create_clock\s', line)]
    for command in clock_commands:
        targets = re.findall(
            r'\[get_ports\s+(?:\{([A-Za-z_]\w*)\}|([A-Za-z_]\w*))\]', command)
        if len(targets) != 1 or len(re.findall(r'\bget_ports\b', command)) != 1:
            refuse('SDC primary clocks require one literal top input per create_clock')
    declarations = sdc_constraints.create_clocks_in_text('\n'.join(clock_commands))
    by_pin: dict[str, dict] = {}
    for clock in declarations:
        pin = resolve(clock.get('port_name'))
        if pin not in roots or pin in by_pin:
            refuse(f'extra or repeated SDC primary clock {clock.get("port_name")!r}')
        by_pin[pin] = clock
    if set(by_pin) != set(roots):
        refuse('SDC must declare every bound primary clock')
    for pin, clock in zip(roots, clocks):
        period = clock.get('period_ns')
        if (isinstance(period, bool) or not isinstance(period, (int, float))
                or not math.isfinite(period) or period <= 0
                or by_pin[pin]['period_ns'] is None
                or not math.isclose(period, by_pin[pin]['period_ns'], rel_tol=1e-9)):
            refuse(f'L8/SDC period unresolved or conflicting for {pin}')
    names = {c['name'] or c['port_name'] for c in declarations}
    if len(names) != len(roots):
        refuse('SDC clock names must be distinct')
    separated: set[frozenset[str]] = set()
    group_pattern = r'\s*-group\s+\[get_clocks\s+(?:\{([\w\s]+)\}|(\w+))\]'
    for command in commands:
        if not re.match(r'^set_clock_groups\s+-asynchronous\b', command):
            continue
        body = re.sub(r'^set_clock_groups\s+-asynchronous\b', '', command)
        if not re.fullmatch(f'(?:{group_pattern})+\\s*', body):
            refuse('unresolved asynchronous SDC clock groups')
        groups = [set((a or b).split()) for a, b in re.findall(group_pattern, body)]
        flat = [name for group in groups for name in group]
        if len(groups) < 2 or len(flat) != len(set(flat)) or not set(flat) <= names:
            refuse('unknown or overlapping asynchronous SDC clock groups')
        for i, group in enumerate(groups):
            for other in groups[i + 1:]:
                separated.update(frozenset((a, b)) for a in group for b in other)
    if any(frozenset((a, b)) not in separated for a in names for b in names if a != b):
        refuse('primary clock relationships lack explicit asynchronous SDC groups')
    source = ', '.join(str(path.relative_to(project)) for path in paths)
    if l1.is_file():
        source += ' + L1_DATASHEET.pin_table.{rtl_name,board_name,aliases}'
    return [by_pin[pin]['port_name'] for pin in roots], '\n'.join(texts), source


def emit_config(project: Path, pdk: str, output: Path, *, synthesis_only: bool = False) -> dict:
    """Emit only declared inputs; unavailable values stay absent, never guessed."""
    from declared_pdk_is_the_pdk_used_check import declared_distribution, PDKDeclarationError
    try:
        declared_pdk, pdk_sources = declared_distribution(project)
    except PDKDeclarationError as exc:
        raise Refusal('LL_' + exc.code, exc.detail) from exc
    if pdk not in (None, 'auto', declared_pdk):
        raise Refusal('LL_PDK_DECLARATION_CONFLICT', 'requested PDK differs from case declaration')
    pdk = declared_pdk
    root = project / 'phase1/generated_docs'
    l8, l9, l19 = (_ldoc(root, name) for name in EMIT_CONFIG_LDOCS)
    # The pad producer (step 15.5ic) runs after synthesis and pre-layout STA;
    # before it has run the PAD_* keys are undeclared, so they stay absent.
    pad_path = project / 'phase3/stage3/pnr/pad_assignment.json'
    pads = _load(pad_path) if pad_path.is_file() else {}
    result: dict[str, Any] = {}
    sources: dict[str, str] = {}
    _set(result, sources, 'PDK', pdk,
         '; '.join(f'{path.relative_to(project)}:{key}' for path, key in pdk_sources))
    # Phase-1's typed clock contract spells a primary source as
    # domain_kind=primary / role=master.  Retain role=primary for older
    # documents, using the same two-field primary semantics as the L8 timing
    # consumers instead of demanding a vocabulary Phase-1 does not emit.
    clocks = [c for c in l8.get('clock_domains', [])
              if (c.get('domain_kind') == 'primary'
                  or c.get('role') in ('primary', 'master'))
              and c.get('pdk_scoped_target') in (None, pdk)]
    if not clocks:
        raise Refusal('LL_CLOCK_AMBIGUOUS', f'{len(clocks)} primary clocks for {pdk}')
    sdc = project / 'phase3/stage3/pnr/constraint.sdc'
    multi_sdc = None
    clock_port = clocks[0].get('source_pin')
    clock_source = 'L8_TIMING_WAVEFORM.clock_domains[primary].source_pin'
    if len(clocks) > 1:
        clock_port, text, sdc_source = _bound_primary_clocks(
            project, l9, clocks, sdc, l8.get('clock_groups'))
        clock_source += ' + L9_INTEGRATION_SPEC.clock_binding + ' + sdc_source
        if not sdc.is_file():
            sdc = output.with_name('multi_clock.sdc')
            multi_sdc = text
    c = clocks[0]
    _set(result, sources, 'CLOCK_PERIOD', c.get('period_ns'), 'L8_TIMING_WAVEFORM.clock_domains[primary].period_ns')
    _set(result, sources, 'CLOCK_PORT', clock_port, clock_source)
    # The design's whole build closure (cmp3 D8): the read phase-3 synthesis
    # and the Step-5 proof take (`_chip_synth_read.chip_rtl_files`), not the
    # one file named after the top -- a multi-file core (subservient) lost
    # every submodule, and Yosys.JsonHeader stopped on the first of them.
    import _chip_synth_read as CSR
    rtl = CSR.chip_rtl_files(project / 'phase2/stage1/rtl')
    chip_top = project / 'phase3/stage3/pnr/chip_top_io.v'
    if rtl and chip_top.is_file():
        _set(result, sources, 'VERILOG_FILES',
             ['dir::' + str(path.relative_to(project)) for path in (*rtl, chip_top)],
             '_chip_synth_read.chip_rtl_files(phase2/stage1/rtl) (the read phase-3 '
             'synthesis and the Step-5 proof take) + phase3/stage3/pnr/chip_top_io.v')
    if sdc.is_file() or multi_sdc is not None:
        for key in ('PNR_SDC_FILE', 'SIGNOFF_SDC_FILE'):
            _set(result, sources, key, 'dir::' + str(sdc.relative_to(project)),
                 (sdc_source if len(clocks) > 1 else
                  'phase3/stage3/pnr/constraint.sdc (L9-derived producer artefact)'))
    # Mapped synthesis does not require a die/core/pad placement declaration.
    # A present declaration is still validated; physical callers remain strict.
    declared, declared_sources = (({}, {}) if synthesis_only
                                 and not (project / DECLARATION_REL).exists()
                                 else declaration_config(project))
    for key, value in declared.items():
        _set(result, sources, key, value, declared_sources[key])
    settings, setting_sources = _declared_flow_settings(l19, pdk)
    for key, value in settings.items():
        _set(result, sources, key, value, setting_sources[key])
    # Step 19 (T98): CTS leaf clusters stay within the declared fanout cap.
    # `set_max_fanout` in the SDC does not constrain clock_tree_synthesis
    # (MEASURED on spm x ihp-sg13g2: a 16-sink leaf against a declared 8), so
    # the cap reaches `-sink_clustering_size` directly, from the same
    # declaration; LibreLane's own default leaves the size unset.
    if 'MAX_FANOUT_CONSTRAINT' in result:
        _set(result, sources, 'CTS_SINK_CLUSTERING_SIZE', result['MAX_FANOUT_CONSTRAINT'],
             sources['MAX_FANOUT_CONSTRAINT'] + ' (CTS_SINK_CLUSTERING_SIZE = MAX_FANOUT_CONSTRAINT)')
    # The pad producer (15.5ic) translates the declaration; where both state
    # a value they must agree. The declaration is the input, so it wins the
    # provenance; a disagreement is refused, never resolved by either side.
    produced: dict[str, Any] = {}
    for key in ('PAD_SOUTH', 'PAD_EAST', 'PAD_NORTH', 'PAD_WEST', 'PAD_SITE_NAME',
                'PAD_CORNER_SITE_NAME', 'PAD_FILLERS', 'PAD_ROTATION_HORIZONTAL',
                'PAD_ROTATION_VERTICAL', 'PAD_ROTATION_CORNER', 'PAD_CORNER',
                'PAD_EDGE_SPACING'):
        value = pads.get(key)
        if key == 'PAD_CORNER' and value and not isinstance(value, list):
            value = [value]
        produced[key] = value
    for key in ('PAD_EDGE_SPACING',):
        for owner, value in (('pad_assignment.json', produced.get(key)),
                             ('declaration', result.get(key))):
            if value is None:
                continue
            try:
                spacing = float(value)
            except (TypeError, ValueError) as exc:
                raise Refusal('LL_PAD_SPACING_INVALID', f'{owner}: {value}') from exc
            if not 0 <= spacing < float('inf'):
                raise Refusal('LL_PAD_SPACING_INVALID', f'{owner}: {spacing}')
            if owner == 'pad_assignment.json':
                produced[key] = spacing
            else:
                result[key] = spacing
    for key, value in produced.items():
        if value in (None, '', []):
            continue
        if key in result:
            if result[key] != value:
                raise Refusal('LL_PAD_DECLARATION_CONFLICT',
                              f'{key}: declaration {result[key]!r} vs '
                              f'phase3/stage3/pnr/pad_assignment.json {value!r}')
            continue
        _set(result, sources, key, value, 'phase3/stage3/pnr/pad_assignment.json.' + key)
    # Supply nets: the chip-top producer's power-pad plan names them.  A PDN
    # grid with no net names and no ring cannot reach the supply pads: on the
    # spm chip path the PDK-default GeneratePDN measured 3,391,999
    # power-grid violations (every shape floating) until these were declared.
    plan = {}
    chip_top_record = project / CHIP_TOP_RECORD_REL
    if chip_top_record.is_file():
        plan = _load(chip_top_record).get('power_pad_plan') or {}
        if isinstance(plan, str):
            plan = {}
    for key, field in (('VDD_NETS', 'power_net'), ('GND_NETS', 'ground_net')):
        if isinstance(plan.get(field), str) and plan[field]:
            _set(result, sources, key, [plan[field]],
                 f'reports/phase3/io_pad_chip_top.json.power_pad_plan.{field}')
    if chip_top_record.is_file():
        record = _load(chip_top_record)
        _set(result, sources, 'RSZ_DONT_TOUCH_LIST',
             aux_tie_dont_touch(record) or None,
             'reports/phase3/io_pad_chip_top.json.aux_pin_signal_connections'
             '[].{tie_instance,net}')
        # Place every selected external bond, including supplemental supplies
        # absent from the PDK's default terminal list. The native pad placer
        # derives their geometry from the actual master pin; no DEF is edited.
        if record.get('verdict') == 'WROTE':
            placed = set(plan.get('instances') or [])
            for side in ('SOUTH', 'EAST', 'NORTH', 'WEST'):
                placed.update(result.get('PAD_' + side) or [])
            terminals = {f"{pad['master']}/{pad['terminal']}"
                         for instance, pad in (record.get('pad_instances') or {}).items()
                         if instance in placed and pad.get('port')
                         and pad.get('master') and pad.get('terminal')}
            if terminals:
                _set(result, sources, 'PAD_PLACE_IO_TERMINALS',
                     sorted(terminals | set(result.get('PAD_PLACE_IO_TERMINALS') or [])),
                     f'{CHIP_TOP_RECORD_REL}.pad_instances[].{{master,terminal,port}}')
    # Core ring + pad connection: the PDK registry's pad-connected ring, the
    # same declaration the direct deck's `add_pdn_ring` is built from.
    registry = Path(__file__).resolve().parent / 'pdk_registry.json'
    entries = _load(registry).get('pdks', []) if registry.is_file() else []
    if isinstance(entries, dict):
        entries = [dict(v, name=k) for k, v in entries.items() if isinstance(v, dict)]
    ring = next((e.get('pdn_ring') for e in entries
                 if isinstance(e, dict) and e.get('name') == pdk), None)
    has_pads = any(k in result for k in ('PAD_SOUTH', 'PAD_EAST', 'PAD_NORTH', 'PAD_WEST'))
    if isinstance(ring, dict) and ring.get('layers') and has_pads:
        _set(result, sources, 'PDN_CORE_RING', True,
             f'programs/pdk_registry.json.pdks[name={pdk}].pdn_ring')
        if ring.get('connect_to_pad_layers'):
            _set(result, sources, 'PDN_CORE_RING_CONNECT_TO_PADS', True,
                 f'programs/pdk_registry.json.pdks[name={pdk}].pdn_ring.connect_to_pad_layers')
    elif has_pads and plan.get('instances'):
        # A produced core supply pair also needs a core-to-pad connection when
        # the registry has no custom ring geometry. Use the existing native
        # PDN ring; its selected PDK owns layers, widths, spacing and offsets.
        supplied = {pad.get('kind') for pad in plan.get('core_supply_pads', [])
                    if isinstance(pad, dict) and pad.get('master') and pad.get('terminal')
                    and pad.get('grid_net', pad.get('port')) == plan.get(
                        'power_net' if pad.get('kind') == 'power' else 'ground_net')}
        if {'power', 'ground'} <= supplied:
            source = f'{CHIP_TOP_RECORD_REL}.power_pad_plan.core_supply_pads'
            _set(result, sources, 'PDN_CORE_RING', True, source)
            _set(result, sources, 'PDN_CORE_RING_CONNECT_TO_PADS', True, source)
    # Resistive supply pads expose the bond as an external port while the
    # core grid is an internal net. Native PDN must not add a second external
    # core supply terminal: the pad's PDK resistor is the electrical boundary.
    if any(pad.get('grid_net') and pad.get('grid_net') != pad.get('port')
           for pad in plan.get('core_supply_pads', []) if isinstance(pad, dict)):
        _set(result, sources, 'PDN_ENABLE_PINS', False,
             f'{CHIP_TOP_RECORD_REL}.power_pad_plan.core_supply_pads[].grid_net')
    # Strap width/pitch: this design's own pre-route EM search (T103), measured
    # with PSM on its placed, clock-treed layout. Absent record -> absent keys.
    from _ppa.pdn_em_presweep import librelane_pdn_config
    pdn, pdn_source = librelane_pdn_config(project)
    for key, value in pdn.items():
        _set(result, sources, key, value, pdn_source)
    if multi_sdc is not None:
        sdc.parent.mkdir(parents=True, exist_ok=True)
        sdc.write_text(multi_sdc)
    write_json(output, result)
    write_json(output.with_suffix('.provenance.json'), sources)
    return result


def synthesis_levers(project: Path) -> dict[str, str] | None:
    """Declared native synthesis strategy; None preserves the absent authority.

    The native config owns the effective default. Keep None, an explicit empty
    object and an explicit AREA 0 distinct for handoff currentness, even when
    all three result in the same native strategy. No arbitrary config overlay.
    """
    path = project / 'phase3/librelane_switch.json'
    doc = _load(path) if path.is_file() else {}
    if not isinstance(doc, dict):
        raise Refusal('LL_SYNTH_LEVER_INVALID', 'switch must be an object')
    if 'synthesis_levers' not in doc:
        return None
    raw = doc['synthesis_levers']
    if not isinstance(raw, dict):
        raise Refusal('LL_SYNTH_LEVER_INVALID', 'synthesis_levers must be an object')
    from _ppa.synthesis import STRATEGIES
    for key, value in raw.items():
        if key != 'SYNTH_STRATEGY':
            raise Refusal('LL_SYNTH_LEVER_UNKNOWN', str(key))
        if not isinstance(value, str) or value not in STRATEGIES:
            raise Refusal('LL_SYNTH_LEVER_INVALID', f'{key}: {value!r}')
    return dict(raw)


def emit_synthesis_config(project: Path, pdk: str, output: Path,
                          rtl_files: list[Path], defines: list[str],
                          use_slang: bool,
                          std_cell_library: str | None = None,
                          synth_liberty: str | list[str] | None = None,
                          top: str | None = None) -> dict:
    """Bind Yosys.Synthesis to the caller's selected design inputs."""
    import sparse_fsm_detect
    import catalog_synth_safe_params_check

    if not rtl_files or any(not path.is_file() or not path.resolve().is_relative_to(project.resolve())
                            for path in rtl_files):
        raise Refusal('LL_SYNTH_INPUT_MISSING', 'selected RTL must exist inside the project')
    result = emit_config(project, pdk, output, synthesis_only=True)
    sources = _load(output.with_suffix('.provenance.json'))
    _set(result, sources, 'PDK', pdk, 'resolved PDK supplied by phase3_one_shot_runner')
    if std_cell_library:
        _set(result, sources, 'STD_CELL_LIBRARY', std_cell_library,
             'resolved synthesis liberty library supplied by phase3_one_shot_runner')
    if synth_liberty:
        _set(result, sources, 'LIB', {'*': (synth_liberty if isinstance(synth_liberty, list)
                                          else [synth_liberty])},
             'resolved synthesis liberty supplied by phase3_one_shot_runner')
    _set(result, sources, 'VERILOG_FILES',
         [str(path.resolve()) for path in rtl_files],
         'phase3_one_shot_runner.step_synth selected RTL (package-first, include-hub filtered)')
    for key in ('PNR_SDC_FILE', 'SIGNOFF_SDC_FILE'):
        if key in result and str(result[key]).startswith('dir::'):
            result[key] = str((project / str(result[key])[5:]).resolve())
    _set(result, sources, 'VERILOG_DEFINES', defines,
         'phase3_one_shot_runner.step_synth macro-aware frontend decision')
    _set(result, sources, 'USE_SLANG', use_slang,
         'phase3_one_shot_runner.step_synth frontend decision')
    # LibreLane couples optional bus splitting to opt_clean -purge AFTER
    # hilomap. Keep the final tie-cell mapping intact; OpenROAD reads bus nets
    # directly. An explicit design setting remains visible to the recipe gate.
    if 'SYNTH_SPLITNETS' not in result:
        _set(result, sources, 'SYNTH_SPLITNETS', False,
             'preserve final hilomap tie cells; native splitnets runs opt_clean -purge')
    sparse = sparse_fsm_detect.detect_paths(rtl_files)
    _set(result, sources, 'SYNTH_PRESERVE_FSM_REGISTERS', sparse['register_names'],
         'sparse_fsm_detect over selected design RTL')
    _set(result, sources, 'SYNTH_PRESERVE_FSM_INSTANCES', sparse['flop_instances'],
         'sparse_fsm_detect over selected design RTL')
    _set(result, sources, 'SYNTH_FSM_ENCFILE', True,
         'step 13 LEC requires the synthesis FSM recoding table')
    # A catalogued IP that is itself the top: SYNTH_PARAMETERS reaches it
    # (`chparam ... <top>`). Below the top, the glue pins it (step-1 gate).
    pinned = catalog_synth_safe_params_check.top_synth_parameters(project, top) if top else None
    if pinned:
        _set(result, sources, 'SYNTH_PARAMETERS', pinned[0], pinned[1])
    for key, value in (synthesis_levers(project) or {}).items():
        _set(result, sources, key, value,
             f'phase3/librelane_switch.json synthesis_levers.{key}')
    write_json(output, result)
    write_json(output.with_suffix('.provenance.json'), sources)
    return result


def phase2_pdk(project: Path, *, selected: str | None = None) -> tuple[str, str]:
    """Read the existing Phase-2 PDK declaration, refusing ambiguous evidence.

    The shared declaration accessor selects the source. This stricter tool
    input boundary checks its providers for malformed or conflicting values;
    a prose target is not an executable PDK distribution name.
    An explicit selection may name a declared alternate or family revision;
    omission retains the existing primary-target result.
    """
    import declared_pdk_is_the_pdk_used_check as declared
    import pdk_family_identity as identity

    def distribution_name(value):
        if not isinstance(value, str):
            return value
        name, _ = identity.canonical_entry(value, exact_distribution=True)
        if name is not None:
            return name
        if any(identity.normalise(value) == identity.normalise(candidate)
               for candidate in identity.registry_names()):
            raise Refusal('LL_PHASE2_PDK_INVALID', 'ambiguous registered PDK spelling')
        # Preserve opaque declarations for the existing native resolvability
        # gate; an unregistered token gains no spelling aliases here.
        return value

    paths = [project / 'phase1/pdk_staging_read.json',
             project / 'phase1/merged_docs/L19_CONSTRAINTS_PDK.json',
             project / 'phase1/L19_CONSTRAINTS_PDK.json',
             project / 'input/project.json']
    paths += sorted((project / 'phase1/generated_docs').glob('L19_*.json'))
    values: set[str] = set()
    for path in paths:
        if not path.exists():
            continue
        try:
            doc = json.loads(path.read_text())
            if not isinstance(doc, dict):
                raise ValueError('declaration must be an object')
            scopes = [doc]
            if 'fields' in doc:
                if not isinstance(doc['fields'], dict):
                    raise ValueError('fields must be an object')
                scopes.append(doc['fields'])
            keys = ('adopted_pdk_target', 'staged_identifier') if path.name == 'pdk_staging_read.json' else (
                ('pdk', 'target_pdk', 'pdk_target') if path.name == 'project.json' else declared._L19_KEYS)
            for scope in scopes:
                for key in keys:
                    value = scope.get(key)
                    if value is None or value == '':
                        continue
                    if not isinstance(value, str) or not _PDK_NAME.fullmatch(value.strip()):
                        raise ValueError(f'{key} must name an exact PDK distribution')
                    # The staging record deliberately keeps both the raw
                    # family token found in the staged enablement and the
                    # executable target adopted from stronger evidence.  They
                    # are provenance + decision, not two peer declarations.
                    # Once an adopted target exists, validate but do not add
                    # the raw staged identifier to the equality set.
                    if (path.name == 'pdk_staging_read.json'
                            and key == 'staged_identifier'
                            and scope.get('adopted_pdk_target')):
                        continue
                    values.add(distribution_name(value.strip()))
        except (OSError, ValueError) as exc:
            raise Refusal('LL_PHASE2_PDK_INVALID', f'{path.relative_to(project)}: {exc}') from exc
    pdk, source = declared.declared_target(project)
    if not pdk or not source or not values:
        raise Refusal('LL_PHASE2_PDK_UNDECLARED', 'declare PDK in Phase-2 L19 or input/project.json')
    pdk = distribution_name(pdk)
    if values != {pdk}:
        raise Refusal('LL_PHASE2_PDK_CONFLICT', 'Phase-2 PDK declarations disagree')
    if selected is not None and selected != 'auto':
        if not isinstance(selected, str) or not _PDK_NAME.fullmatch(selected):
            raise Refusal('LL_PHASE2_PDK_INVALID', 'selected PDK must name an exact distribution')
        selected = distribution_name(selected)
        # The scalar primary is not the complete declaration of a multi-PDK
        # design. Reuse the backend's existing, one-directional family/revision
        # rule; a caller may select only a process the design already names.
        import phase3_one_shot_runner as p3
        tokens = {pdk.lower()}
        for alternate in p3._read_declared_pdk_alternates(project):
            if not _PDK_NAME.fullmatch(alternate):
                raise Refusal('LL_PHASE2_PDK_INVALID', 'alternate PDK must name an exact distribution')
            tokens.add(alternate.lower())
        if selected != pdk and not p3._declares_resolved_pdk(selected, tokens):
            raise Refusal('LL_PHASE2_PDK_CONFLICT',
                          'selected PDK is not a declared target or revision')
        pdk, source = selected, f'run selection {selected}; declared by {source}'
    switch = project / 'phase3/librelane_switch.json'
    if switch.is_file():
        selected = distribution_name(_load(switch).get('pdk'))
        if selected is not None and selected != pdk:
            raise Refusal('LL_PHASE2_PDK_CONFLICT', 'switch.pdk disagrees with Phase-2 declaration')
    return pdk, source


def emit_lint_config(project: Path, pdk: str, output: Path, top: str,
                     rtl_files: list[Path], top_source: str,
                     pdk_source: str = 'phase3/librelane_switch.json.pdk') -> dict:
    """Bind lint and its copied JSON header to the selected RTL and reader.

    Step 2 runs before any Phase-3 artefact exists, so this reads nothing
    from phase3/stage3; unlike `emit_config` it needs no pad or die input."""
    if not rtl_files or any(not path.is_file() or not path.resolve().is_relative_to(project.resolve())
                            for path in rtl_files):
        raise Refusal('LL_LINT_INPUT_MISSING', 'selected RTL must exist inside the project')
    if not top:
        raise Refusal('LL_TOP_UNDECLARED', 'no declared RTL top module')
    result: dict[str, Any] = {'meta': {'step': 'Verilator.Lint'}}
    sources: dict[str, str] = {}
    _set(result, sources, 'DESIGN_NAME', top, top_source)
    _set(result, sources, 'PDK', pdk, pdk_source)
    _set(result, sources, 'VERILOG_FILES', [str(path.resolve()) for path in rtl_files],
         '_rtl_include_hub.silicon_rtl_selection (the step-9 synthesis input)')
    # Step 2 copies this raw config for Yosys.JsonHeader. Retain the same
    # source-extension reader choice as step_synth instead of resolving its
    # default Verilog reader against a declared SystemVerilog closure.
    _set(result, sources, 'USE_SLANG', any(path.suffix == '.sv' for path in rtl_files),
         'selected SystemVerilog source; step_synth frontend parity')
    write_json(output, result)
    write_json(output.with_suffix('.provenance.json'), sources)
    return result


def verify_synthesis_stat(stat_path: Path, state: dict, stats_path: Path,
                          top: str, output: Path | None) -> dict:
    """Bind the area-gate input and copied netlist to Yosys's native stat."""
    if output is not None:
        output.unlink(missing_ok=True)
    stat = _load(stat_path)
    stats = _load(stats_path)
    module = stat.get('modules', {}).get('\\' + top)
    if module is None:
        module = stat.get('modules', {}).get(top)
    if not isinstance(module, dict):
        raise Refusal('LL_STAT_TOP_MISSING',
                      f'{top}: no modules entry for it in {stat_path}')
    metrics = state.get('metrics', {})
    native_netlist = Path(state.get('nl') or '')
    if not native_netlist.is_file():
        raise Refusal('LL_SYNTH_OUTPUT_MISSING', str(native_netlist))
    count = module.get('num_cells')
    area = module.get('area')
    if not isinstance(count, int) or isinstance(count, bool) or \
            not isinstance(area, (int, float)) or isinstance(area, bool):
        raise Refusal('LL_STAT_UNMEASURED', str(stat_path))
    other_counts = (stats.get('cell_count'), metrics.get('design__instance__count'))
    other_areas = (stats.get('chip_area'), metrics.get('design__instance__area'))
    if any(value != count for value in other_counts) or any(
            not isinstance(value, (int, float)) or isinstance(value, bool) or
            abs(value - area) > max(1e-6, abs(area) * 1e-9)
            for value in other_areas):
        raise Refusal('LL_STAT_MISMATCH', f'{stat_path} vs {stats_path}/state metrics')
    report = {'status': 'PASS', 'top': top, 'cell_count': count,
              'area_um2': area}
    if output is not None:
        write_json(output, report)
    return report


def _walk_paths(value: Any):
    if isinstance(value, dict):
        for item in value.values():
            yield from _walk_paths(item)
    elif isinstance(value, list):
        for item in value:
            yield from _walk_paths(item)
    elif isinstance(value, str) and value.startswith('/'):
        yield Path(value)


# Early steps consume only the views produced so far. Floorplan creates
# the first ODB/DEF/SDC from the mapped netlist.
# A lone analog block has only a GDS: these steps declare GDS as their
# sole required input (magic.py RCX/DRC, klayout.py DRC).
# One table for the run_chain floor and the bridge's chain requirements.
_EARLY_STEP_INPUTS: dict[str, tuple[str, ...]] = {
    'Verilator.Lint': (), 'Yosys.JsonHeader': (), 'Yosys.Synthesis': ('json_h',),
    'Checker.LintErrors': (), 'Checker.LintTimingConstructs': (),
    'Checker.LintWarnings': (),
    'OpenROAD.CheckSDCFiles': ('nl',), 'OpenROAD.STAPrePNR': ('nl',),
    'OpenROAD.Floorplan': ('nl',), 'Yosys.EQY': ('nl',),
    'Vibeic.PostMapRepair': ('nl',),
    'Checker.YosysUnmappedCells': ('nl',), 'Checker.YosysSynthChecks': ('nl',),
    'Checker.NetlistAssignStatements': ('nl',),
    'Magic.RCX': ('gds',), 'Magic.DRC': ('gds',),
    'KLayout.DRC': ('gds',),
    # These native PV steps consume stream/logical views, not an ODB.
    # The resolved sidecar additionally enforces each installed step's inputs.
    'Magic.SpiceExtraction': ('gds', 'def'),
    'Netgen.LVS': ('spice', 'pnl'), 'KLayout.LVS': ('cdl', 'gds'),
    # Stream-level checks and finishing read the stream alone (steps 26, 26.5ic).
    'Vibeic.FillAwareStreamOut': ('def',),
    'KLayout.Antenna': ('gds',), 'Checker.KLayoutAntenna': (),
    'KLayout.SealRing': ('gds',), 'KLayout.XOR': ('mag_gds', 'klayout_gds'),
    # Step 34's stream finishing (the PDK fill script, its density deck).
    'KLayout.Filler': ('gds',), 'KLayout.Density': ('gds',),
    'Checker.KLayoutDensity': (),
    # Steps 37.3 / 37.5ic (mig105): vibe-ic's own stream checks.
    'Vibeic.FinishingXOR': ('gds',), 'Vibeic.DatabaseUnit': ('gds',)}


def resolve_state_pdk_asset(value: str | Path, *, pdk: str | None,
                            mounts: list = ()) -> Path | None:
    """Resolve an existing native view through PDK paths and mounts.

    No runtime discovery, cache writes, or changes to the recorded inputs.
    An unresolved asset must remain unmeasured by its consumer.
    """
    path = Path(value)
    if '..' in path.parts:
        return None
    # Select the mounted source before testing existence: a visible guest file
    # may contain different bytes from the file the tool actually mounts.
    source = path
    for host, guest in sorted(mounts, key=lambda m: len(str(m[1])), reverse=True):
        if path.is_relative_to(guest):
            source = Path(host) / path.relative_to(guest)
            break
    if source.is_file():
        return source
    try:
        registry = json.loads(Path(__file__).with_name('pdk_registry.json').read_text())
        if not pdk or pdk not in {entry['name'] for entry in registry['pdks']}:
            return None
        parts = path.parts
        if not path.is_absolute() or parts.count(pdk) != 1:
            return None
        suffix = parts[parts.index(pdk) + 1:]
        if len(suffix) < 2 or suffix[0] not in ('libs.ref', 'libs.tech'):
            return None
        declared = os.environ.get('PDK_ROOT', '')
        root = Path(declared)
        if not declared or not root.is_absolute() or '..' in root.parts:
            return None
        roots = [root / pdk]
        if root.name == pdk:
            roots.append(root)
        candidates = []
        for selected in roots:
            candidate = selected.joinpath(*suffix)
            # Nix directory/file links may target a different store package.
            # Resolve the currently installed PDK tree, including Nix links.
            if candidate.is_relative_to(selected) and candidate.is_file():
                candidates.append(candidate)
        if len(candidates) != 1:
            return None
        return candidates[0]
    except (OSError, ValueError, KeyError, TypeError):
        return None


def _check_state(state: dict, *, outputs: bool = False,
                 step_id: str = '') -> None:
    required = _EARLY_STEP_INPUTS.get(step_id, ('odb', 'def', 'nl', 'sdc'))
    if not outputs:
        for key in required:
            if not state.get(key):
                raise Refusal('LL_STATE_MISSING', f'state[{key!r}] is empty')
    for path in _walk_paths({k: v for k, v in state.items() if k != 'metrics'}):
        if not path.is_file():
            raise Refusal('LL_STATE_FILE_MISSING', str(path))


def views_path(config_path: Path) -> Path:
    """Sidecar holding the step's LibreLane-declared ``inputs``/``outputs``."""
    return config_path.with_name(config_path.stem + '.views.json')


def _declared_views(config_path: Path) -> tuple[str, list[str], list[str]]:
    step_id = _load(config_path).get('meta', {}).get('step', '')
    sidecar = views_path(config_path)
    declared = _load(sidecar) if sidecar.is_file() else {}
    if declared.get('step') != step_id or not isinstance(declared.get('inputs'), list):
        raise Refusal('LL_STEP_INPUTS_UNDECLARED',
                      f'{step_id}: resolve the config with resolve_step_configs')
    return step_id, list(declared['inputs']), list(declared.get('outputs') or [])


def _required_views(config_paths: list[Path]) -> list[str]:
    """What a chain's first State must carry, from LibreLane's own declarations.

    Walking the chain in order, a view some step consumes (its declared inputs
    plus the run_chain floor) that no EARLIER step declares as an output must
    come from the bridge.  A view needed late in the chain is refused up front
    rather than when that step starts.
    """
    needed: list[str] = []
    produced: set[str] = set()
    for path in config_paths:
        step_id, inputs, outputs = _declared_views(path)
        for view in [*inputs, *_EARLY_STEP_INPUTS.get(step_id, ('odb', 'def', 'nl', 'sdc'))]:
            if view not in produced and view not in needed:
                needed.append(view)
        produced.update(outputs)
    return needed


def _def_design_name(path: Path) -> str | None:
    with path.open(errors='replace') as stream:
        for line in stream:
            words = line.split()
            if len(words) >= 2 and words[0] == 'DESIGN':
                return words[1]
            if words[:1] == ['COMPONENTS']:
                break
    return None


def _openroad_convert(project: Path, image: str, config: dict, tcl_body: list[str],
                      folder: Path, name: str, mounts: list[tuple[Path, str]],
                      docker: str) -> Path:
    """One OpenROAD session in the image, with the step config's own LEFs."""
    tech = config.get('TECH_LEFS') or {}
    tech_lef = tech.get('nom_*') or next(iter(tech.values()), None)
    if not tech_lef:
        raise Refusal('LL_TECH_LEF_MISSING', str(config.get('meta')))
    lefs = list(dict.fromkeys([tech_lef] + [x for key in ('CELL_LEFS', 'PAD_LEFS', 'MACRO_LEFS', 'EXTRA_LEFS')
                                             for x in (config.get(key) or [])]))
    tcl = folder / f'{name}.tcl'
    tcl.write_text('\n'.join([f'read_lef {{{path}}}' for path in lefs] + tcl_body) + '\n')
    volumes = ['-v', f'{project.resolve()}:{project.resolve()}']
    for host, guest in mounts:
        volumes += ['-v', f'{host.resolve()}:{guest}:ro']
    network, command = native_tool_command(image, ['openroad', '-exit', str(tcl)])
    completed = run_container([docker, 'run', *_dmem.docker_memory_flags(), '--rm',
                               '--network', network, *volumes,
                               image, '--skip', *command],
                              supervised=True, log=folder / f'{name}.log')
    (folder / f'{name}.log').write_text(completed.stdout + '\n' + completed.stderr)
    if completed.returncode:
        raise Refusal('LL_BRIDGE_CONVERSION_FAILED', str(folder / f'{name}.log'))
    return tcl


def state_from_direct(project: Path, image: str, config_path: Path,
                      views: dict[str, Any], output_dir: Path, *,
                      mounts: list[tuple[Path, str]] | None = None,
                      metrics: dict[str, Any] | None = None,
                      metrics_source: str | None = None,
                      chain: list[Path] | None = None,
                      docker: str = 'docker') -> Path:
    """direct -> LibreLane: a State the resolved step can consume, or a refusal.

    ``views`` names the direct step's real files: ``def``, ``odb``, ``nl`` (one
    path, or the ordered files the direct deck reads before ``link_design``),
    ``sdc``, ``pnl``, ``spef`` (``{corner_pattern: path}``), ``gds`` ...  The
    required set is what LibreLane declares for the step (``meta.inputs`` in a
    config from ``resolve_step_configs``) plus the run_chain floor.  An ODB
    missing beside a DEF is produced by OpenROAD from the step config's own
    LEFs; a DEF missing beside an ODB is written from it; a powered netlist
    (``pnl``) missing beside either is written from it with
    ``write_verilog -include_pwr_gnd``, as LibreLane's own views are.  Any other missing
    view refuses ``LL_BRIDGE_VIEW_MISSING``; nothing is synthesized.  With
    ``chain`` (the later steps' configs, in order) the check covers every view
    a later step consumes that no earlier step produces.  Metrics
    enter only as a measured mapping with a named source.
    """
    config = _load(config_path)
    step_id = config.get('meta', {}).get('step', '')
    required = _required_views([config_path, *(chain or [])])
    if 'pnl' in required and not views.get('pnl') and ('def' in views or 'odb' in views):
        # Preserve digital run_half's powered-netlist derivation from the
        # routed database. The explicit mixed-top pair needs no such conversion.
        required = list(dict.fromkeys([*required, 'odb']))
    output_dir.mkdir(parents=True, exist_ok=True)
    mounts = list(mounts or [])
    state: dict[str, Any] = {}

    def _file(view: str, value: Any) -> Path:
        path = Path(value)
        if not path.is_file():
            raise Refusal('LL_BRIDGE_VIEW_MISSING', f'{view}: {path}')
        return path.resolve()

    for view, value in views.items():
        if value is None:
            continue
        if view == 'nl' and isinstance(value, (list, tuple)):
            parts = [Path(x) for x in value]
            for index, part in enumerate(parts):
                _file(f'nl[{index}]', part)
            joined = output_dir / 'bridge.nl.v'
            joined.write_text(''.join(
                f'// Native bridge source: {part.resolve()}\n'
                + part.read_text(errors='replace') + '\n' for part in parts))
            state['nl'] = str(joined.resolve())
        elif view == 'spef':
            if not isinstance(value, dict) or not value:
                raise Refusal('LL_BRIDGE_SPEF_CORNERS_UNDECLARED', str(value))
            state['spef'] = {corner: str(_file(f'spef[{corner}]', path))
                             for corner, path in value.items()}
        else:
            state[view] = str(_file(view, value))
    name = config.get('DESIGN_NAME')
    if 'def' in state and name and _def_design_name(Path(state['def'])) != name:
        raise Refusal('LL_BRIDGE_DESIGN_MISMATCH',
                      f"{state['def']}: DESIGN != config DESIGN_NAME {name}")
    if 'odb' in required and 'odb' not in state and 'def' in state:
        odb = output_dir / 'bridge.odb'
        odb.unlink(missing_ok=True)
        _openroad_convert(project, image, config,
                                [f"read_def {{{state['def']}}}", f'write_db {{{odb}}}'],
                                output_dir, 'def_to_odb', mounts, docker)
        if not odb.is_file():
            raise Refusal('LL_BRIDGE_CONVERSION_FAILED', str(output_dir / 'def_to_odb.log'))
        state['odb'] = str(odb.resolve())
    if 'def' in required and 'def' not in state and 'odb' in state:
        out_def = output_dir / 'bridge.def'
        out_def.unlink(missing_ok=True)
        _openroad_convert(project, image, config,
                                [f"read_db {{{state['odb']}}}", f'write_def {{{out_def}}}'],
                                output_dir, 'odb_to_def', mounts, docker)
        if not out_def.is_file():
            raise Refusal('LL_BRIDGE_CONVERSION_FAILED', str(output_dir / 'odb_to_def.log'))
        state['def'] = str(out_def.resolve())
    if 'pnl' in required and 'pnl' not in state and ('odb' in state or 'def' in state):
        # The powered netlist every LibreLane OpenROAD step writes with its
        # views (io.tcl SAVE_PNL: `write_verilog -include_pwr_gnd`), from the
        # same database; LVS (Netgen.LVS) consumes it (mig105).
        pnl = output_dir / 'bridge.pnl.v'
        pnl.unlink(missing_ok=True)
        load = (f"read_db {{{state['odb']}}}" if 'odb' in state
                else f"read_def {{{state['def']}}}")
        _openroad_convert(project, image, config,
                                [load, f'write_verilog -include_pwr_gnd {{{pnl}}}'],
                                output_dir, 'to_pnl', mounts, docker)
        if not pnl.is_file():
            raise Refusal('LL_BRIDGE_CONVERSION_FAILED', str(output_dir / 'to_pnl.log'))
        state['pnl'] = str(pnl.resolve())
    missing = [view for view in required if view not in state]
    if missing:
        raise Refusal('LL_BRIDGE_VIEW_MISSING', f'{step_id}: {missing}')
    state['metrics'] = dict(metrics or {})
    if metrics:
        if not metrics_source:
            raise Refusal('LL_BRIDGE_METRICS_UNSOURCED', step_id)
    path = output_dir / 'state_in.json'
    write_json(path, state)
    return path


def _copy_state_views(state_path: Path, targets: dict[str, Path],
                      *, path_map: dict[str, str] | None = None) -> dict:
    """Copy the native State views to their requested destination paths.

    """
    state = _load(state_path)
    rows: dict[str, Any] = {}
    for view, dest in targets.items():
        key, _, corner = view.partition(':')
        value = state.get(key)
        if corner:
            value = value.get(corner) if isinstance(value, dict) else None
        if not isinstance(value, str) or not value:
            raise Refusal('LL_HANDOFF_VIEW_MISSING', view)
        for guest, host in (path_map or {}).items():
            if value.startswith(guest.rstrip('/') + '/'):
                value = host.rstrip('/') + value[len(guest.rstrip('/')):]
                break
        source = Path(value)
        if not source.is_file():
            raise Refusal('LL_HANDOFF_VIEW_MISSING', f'{view}: {source}')
        dest = Path(dest)
        dest.parent.mkdir(parents=True, exist_ok=True)
        tmp = dest.with_name(dest.name + '.handoff.tmp')
        shutil.copyfile(source, tmp)
        os.replace(tmp, dest)
        rows[view] = {'source': str(source), 'dest': str(dest)}
        if source.suffix.lower() == '.def':
            # The top a later step judges is the one this DEF states, whatever
            # the view is called (`def`, `post_cts_def`, `post_hold_def`).
            rows[view]['design'] = _def_design_name(source)
    return {'state': str(state_path), 'views': rows}


def handoff_to_direct(state_path: Path, targets: dict[str, Path], output: Path,
                      *, path_map: dict[str, str] | None = None) -> dict:
    """Copy the native State's selected views to their downstream paths."""
    document = _copy_state_views(state_path, targets, path_map=path_map)
    write_json(output, document)
    return document


# --- the direct routing deck's side of a LibreLane floorplan handoff ---

def def_supply_tcl(def_text: str, marker: str) -> str:
    """Create the supply nets and supply BTerms a tool DEF declares.

    `read_def -floorplan_initialize` lays a DEF onto the LINKED design and
    skips every net and pin the design does not own (ODB-0247/0249).  A
    synthesized netlist owns no supply net, so a LibreLane state read that way
    loses its whole PDN.  MEASURED on the clean spm GeneratePDN DEF (0.3.77):
    30,462 special-wire shapes and 38 BTerms from `read_db`; 0 and 36 from a
    bare floorplan read; 30,462 and 38 once the two supply nets and pins are
    created from the DEF's own SPECIALNETS/PINS first, with COMPONENTS,
    SPECIALNETS and VIAS byte-identical to the ODB's and identical net
    connectivity.  Only nets the DEF itself marks ``USE POWER``/``USE GROUND``
    are created.
    """
    def _section(name: str) -> str:
        m = re.search(rf"(?ms)^{name}\s+\d+\s*;(.*?)^END\s+{name}\b", def_text)
        return m.group(1) if m else ""

    supplies: dict[str, str] = {}
    wildcard: dict[str, list[str]] = {}
    for stmt in _section("SPECIALNETS").split(";"):
        m = re.match(r"\s*-\s+(\S+)", stmt)
        use = re.search(r"\+\s*USE\s+(POWER|GROUND)\b", stmt)
        if m and use:
            supplies[m.group(1)] = use.group(1)
            head = stmt.split("+", 1)[0]
            wildcard[m.group(1)] = re.findall(r"\(\s*\*\s+(\S+)\s*\)", head)
    pins: list[tuple[str, str, str]] = []
    for stmt in _section("PINS").split(";"):
        m = re.match(r"\s*-\s+(\S+)\s+\+\s*NET\s+(\S+)", stmt)
        if m and m.group(2) in supplies:
            d = re.search(r"\+\s*DIRECTION\s+(\S+)", stmt)
            pins.append((m.group(1), m.group(2), d.group(1) if d else "INOUT"))
    lines = [f'puts "{marker} librelane_supply_nets"',
             "set _ll_blk [[[ord::get_db] getChip] getBlock]"]
    for net, use in sorted(supplies.items()):
        lines.append(f'if {{[$_ll_blk findNet "{net}"] eq "NULL"}} {{ set _ll_n '
                     f'[odb::dbNet_create $_ll_blk "{net}"]; $_ll_n setSpecial; '
                     f'$_ll_n setSigType {use} }}')
    for pin, net, direction in pins:
        lines.append(f'if {{[$_ll_blk findBTerm "{pin}"] eq "NULL"}} {{ set _ll_b '
                     f'[odb::dbBTerm_create [$_ll_blk findNet "{net}"] "{pin}"]; '
                     f'$_ll_b setIoType {direction} }}')
    # The DEF's own `( * <pin> )` terms are the tool's global-connect rules
    # (LibreLane SetPowerConnections / GeneratePDN).  Registering them makes
    # the deck's later `global_connect` re-apply reach every instance created
    # after the ingest (spares, buffers, fill, diodes).  MEASURED on the spm
    # mixed chain without them: PG_RECONNECT_DELTA on_no_net 21888 -> 21888.
    rules = 0
    for net, use in sorted(supplies.items()):
        for pin in wildcard.get(net, []):
            lines.append(f'add_global_connection -net {{{net}}} -pin_pattern '
                         f'{{^{re.escape(pin)}$}} -{use.lower()}')
            rules += 1
    if rules:
        lines.append("global_connect")
    lines.append(f'puts "LIBRELANE_SUPPLY_NETS: {len(supplies)} nets, '
                 f'{len(pins)} pins, {rules} global-connect rules"')
    return "\n".join(lines)


def elide_tap_pdn_region(full_pnr_tcl: str, marker: str) -> str:
    """Remove the direct deck's own tap/PDN construction (15 → LibreLane).

    Everything after the floorplan checkpoint and before placement is step-15
    work (macro placement, tapcells, supply global-connect, PDN).  When that
    step's producer is LibreLane, its state already carries all of it.
    """
    m = re.search(
        rf'(?ms)^write_def\s+\S+/floorplan\.def\s*$\n(.*?)'
        rf'^(?=puts "{re.escape(marker)} placement"\s*$)',
        full_pnr_tcl)
    if m is None or len(re.findall(
            rf'(?m)^puts "{re.escape(marker)} placement"\s*$',
            full_pnr_tcl)) != 1:
        raise ValueError("LL_FLOORPLAN_SEAM_AMBIGUOUS: expected one floorplan "
                         "checkpoint followed by one placement stage")
    return (full_pnr_tcl[:m.start(1)]
            + "# step 15 (taps, supply connect, PDN): LibreLane state, "
              "librelane_contract.handoff_to_direct\n"
            + full_pnr_tcl[m.end(1):])


def placement_consumer_tcl(full_pnr_tcl: str, placed_def_c: str, marker: str,
                           after_load_tcl: str = '') -> str:
    """The direct deck from CTS onward, on LibreLane's placed design (step 17).

    With steps 15..18 produced by LibreLane (Floorplan..DetailedPlacement and
    `Vibeic.InsertSpareCells`), the direct deck consumes the tool's final
    placed DEF instead of rebuilding the design:

    1. the netlist load (the `read_verilog`..`link_design` block) becomes one
       full `read_def` of the handed-over DEF, which creates the block with
       every instance, net, pin, row, track and special net. The deck's
       `read_lef` lines stay, so CTS and routing use the SAME tech LEF as the
       direct flow (including its via-landing remediation), and so a resume
       or SDR child deck derived from this one still restores a checkpoint
       DEF on top of them. (MEASURED: `read_db` after `read_lef` replaces the
       whole database, tech included.)
    2. everything the deck does between the resume-elide sentinel and
       `puts "<marker> cts"` (floorplan/pad-ring ingest, taps, PDN, global
       placement, the legalization ladder, the #684 tap prune, spare
       insertion, pre-CTS repair) is removed: it is already in that DEF.
       ``after_load_tcl`` goes in its place: the session state a DEF does not
       carry (global-connect rules, dont_touch).

    The sentinel itself stays, so resume and SDR child decks still find the
    region they elide. Anything else refuses `LL_PLACEMENT_SEAM_AMBIGUOUS`.
    """
    lines = full_pnr_tcl.splitlines()
    starts = [i for i, ln in enumerate(lines) if ln.startswith('read_verilog ')]
    if not starts:
        raise ValueError('LL_PLACEMENT_SEAM_AMBIGUOUS: no read_verilog design load')
    i_rv = starts[0]
    i_ld = i_rv + 1
    while i_ld < len(lines) and (lines[i_ld].startswith('read_verilog ')
                                 or not lines[i_ld].strip()
                                 or lines[i_ld].lstrip().startswith('#')):
        i_ld += 1
    if i_ld >= len(lines) or not lines[i_ld].startswith('link_design '):
        raise ValueError('LL_PLACEMENT_SEAM_AMBIGUOUS: read_verilog is not '
                         'followed by link_design')
    lines[i_rv:i_ld + 1] = [
        '# steps 15..18: the design is LibreLane\'s placed DEF '
        '(librelane_contract.placement_consumer_tcl)',
        f'read_def {placed_def_c}']
    text = '\n'.join(lines) + '\n'
    begin = re.findall(r'(?m)^# <<<PNR_RESUME_ELIDE_BEGIN>>>\s*$', text)
    cts = re.findall(rf'(?m)^puts "{re.escape(marker)} cts"\s*$', text)
    if len(begin) != 1 or len(cts) != 1:
        raise ValueError('LL_PLACEMENT_SEAM_AMBIGUOUS: expected one resume '
                         f'sentinel and one CTS stage, found {len(begin)}/{len(cts)}')
    m = re.search(r'(?ms)^# <<<PNR_RESUME_ELIDE_BEGIN>>>\s*$\n(?:#[^\n]*\n)*'
                  rf'(.*?)^(?=puts "{re.escape(marker)} cts"\s*$)', text)
    if m is None:
        raise ValueError('LL_PLACEMENT_SEAM_AMBIGUOUS: CTS precedes the sentinel')
    ingest = (f'puts "{marker} librelane_placement_ingest"\n'
              f'puts "LIBRELANE_PLACEMENT_CONSUMED: {placed_def_c}"\n'
              + (after_load_tcl.rstrip('\n') + '\n' if after_load_tcl.strip() else ''))
    return text[:m.start(1)] + ingest + text[m.end(1):]


#: Step 17's PPA levers on the LibreLane arm: LibreLane config variables the
#: GlobalPlacement / RepairDesignPostGPL / DetailedPlacement steps read. A
#: value enters the config only as a declared project input --
#: `phase3/librelane_switch.json` `placement_levers` {KEY: value}, the file a
#: PPA candidate writes -- with that source in the provenance file.
PLACEMENT_LEVERS: dict[str, tuple[str, float | None, float | None]] = {
    'PL_TARGET_DENSITY_PCT': ('number', 0.0, 100.0),
    'PL_TIMING_DRIVEN': ('bool', None, None),
    'PL_ROUTABILITY_DRIVEN': ('bool', None, None),
    'GPL_CELL_PADDING': ('int', 0, None),
    'DPL_CELL_PADDING': ('int', 0, None),
    'PL_WIRE_LENGTH_COEF': ('number', 0.0, None),
    'PL_MAX_DISPLACEMENT_X': ('int', 0, None),
    'PL_MAX_DISPLACEMENT_Y': ('int', 0, None),
}
PLACEMENT_LEVERS_KEY = 'placement_levers'

#: A lever that replaces a deprecated design key LibreLane would otherwise
#: translate (`PL_TARGET_DENSITY` fraction -> `_PCT`); both set is a conflict.
_LEVER_SUPERSEDES = {'PL_TARGET_DENSITY_PCT': ('PL_TARGET_DENSITY',)}


def _lever_value(key: str, raw: Any) -> Any:
    kind, low, high = PLACEMENT_LEVERS[key]
    if kind == 'bool':
        if isinstance(raw, bool):
            return raw
        if str(raw).strip().lower() in ('true', 'false'):
            return str(raw).strip().lower() == 'true'
        raise ValueError(f'{raw!r} is not a boolean')
    if isinstance(raw, bool):
        raise ValueError(f'{raw!r} is not a number')
    value: Any = int(str(raw).strip()) if kind == 'int' else float(str(raw).strip())
    if value != value or value in (float('inf'), float('-inf')):
        raise ValueError(f'{raw!r} is not finite')
    if (low is not None and (value < low or (kind == 'number' and value == low))) \
            or (high is not None and value > high):
        raise ValueError(f'{raw!r} is outside the lever range')
    return value


def placement_levers(project: Path) -> dict[str, tuple[Any, str]]:
    """The project's declared placement levers -> a `resolve_step_configs`
    overlay. An unknown key refuses `LL_PLACEMENT_LEVER_UNKNOWN`; a value of
    the wrong type or outside the lever's range `LL_PLACEMENT_LEVER_INVALID`.
    Nothing is defaulted: an absent lever leaves the design declaration or
    LibreLane's own default in force."""
    path = project / 'phase3/librelane_switch.json'
    declared = _load(path).get(PLACEMENT_LEVERS_KEY) if path.is_file() else None
    if declared is None:
        return {}
    if not isinstance(declared, dict):
        raise Refusal('LL_PLACEMENT_LEVER_INVALID', f'{PLACEMENT_LEVERS_KEY} is not an object')
    overlay: dict[str, tuple[Any, str]] = {}
    for key, raw in declared.items():
        if key not in PLACEMENT_LEVERS:
            raise Refusal('LL_PLACEMENT_LEVER_UNKNOWN',
                          f'{key}: not one of {sorted(PLACEMENT_LEVERS)}')
        try:
            value = _lever_value(key, raw)
        except ValueError as exc:
            raise Refusal('LL_PLACEMENT_LEVER_INVALID', f'{key}: {exc}') from exc
        overlay[key] = (value, f'phase3/librelane_switch.json {PLACEMENT_LEVERS_KEY}.{key}')
    return overlay


#: The host cache a resolved PDK root is materialised into, one directory per
#: IMAGE ID. `VIBEIC_PDK_ROOT_CACHE` names it; else the XDG cache convention.
#: This is where the COPY lives, never where a PDK is guessed to be: the content
#: always comes out of the resolved image.
PDK_ROOT_CACHE_ENV = 'VIBEIC_PDK_ROOT_CACHE'
PDK_ROOT_MARKER = '.vibeic_pdk_root.json'
PDK_ROOT_PROVENANCE_REL = 'phase3/librelane_pdk_root.provenance.json'
#: A local metadata read; the bound is for a stalled docker daemon, not a slow host.
IMAGE_INSPECT_DEADLINE_S = 60
#: Where a step container sees the run's resolved PDK root: the host root
#: `pdk_root_resolution` answers is bound here (each chain mounts
#: `<root>/<pdk>` at `/pdk/<pdk>`), and step configs are resolved against it
#: (`resolve_step_configs`: `Chip(..., pdk_root="/pdk")`). `run_chain`
#: passes it to LibreLane's CLI as `--pdk-root`, never leaving the CLI to
#: default to the image's own `PDK_ROOT` (W22).
PDK_GUEST_ROOT = '/pdk'
_PDK_NAME = re.compile(r'^[A-Za-z0-9][A-Za-z0-9._+-]*$')


def image_pdk_root(image: str, docker: str = 'docker') -> dict[str, str]:
    """The image's OWN PDK location: its `PDK_ROOT` env, and its image ID.

    Read with `docker image inspect` (never a pull, never a run). The digest is
    the identity and the repository is configuration (#2170): a `repo@digest`
    this host holds under another repository name is inspected by that name.
    An image not on this host, or one declaring no absolute `PDK_ROOT`, refuses.
    """
    if _ce.no_container_route():
        root = os.environ.get('PDK_ROOT', '')
        if not root.startswith('/') or not Path(root).is_dir():
            raise Refusal('LL_IMAGE_PDK_ROOT_UNDECLARED', f'{image}: PDK_ROOT={root!r}')
        return {'image_id': str(image), 'pdk_root': root.rstrip('/') or '/'}
    def _inspect(ref: str) -> subprocess.CompletedProcess:
        try:
            return subprocess.run([docker, 'image', 'inspect', '--format',
                                   '{{json .Id}} {{json .Config.Env}}', ref],
                                  capture_output=True, text=True,
                                  timeout=IMAGE_INSPECT_DEADLINE_S)
        except OSError as exc:
            raise Refusal('LL_IMAGE_NOT_INSPECTABLE', f'{image}: {exc}') from None
        except subprocess.TimeoutExpired:
            raise Refusal('LL_IMAGE_NOT_INSPECTABLE', f'{image}: docker image inspect gave no '
                          f'answer within the {IMAGE_INSPECT_DEADLINE_S} s deadline') from None
    result = _inspect(image)
    if result.returncode:
        import _eda_pin
        digest = _eda_pin.reference_digest(image)
        held = _eda_pin.local_references_for_digest(digest)[0] if digest else ()
        if held:
            result = _inspect(held[0])
    if result.returncode:
        raise Refusal('LL_IMAGE_NOT_INSPECTABLE',
                      f'{image}: rc={result.returncode} {result.stderr.strip()[:200]}')
    try:
        image_id, env = (json.loads(part) for part in result.stdout.strip().split(' ', 1))
    except ValueError:
        raise Refusal('LL_IMAGE_NOT_INSPECTABLE', f'{image}: {result.stdout[:200]!r}') from None
    values = [e.split('=', 1)[1] for e in (env or []) if e.startswith('PDK_ROOT=')]
    root = values[-1] if values else ''
    if not (isinstance(image_id, str) and re.fullmatch(r'sha256:[0-9a-f]{64}', image_id)):
        raise Refusal('LL_IMAGE_NOT_INSPECTABLE', f'{image}: image id {image_id!r}')
    if not root.startswith('/'):
        raise Refusal('LL_IMAGE_PDK_ROOT_UNDECLARED', f'{image}: PDK_ROOT={root!r}')
    return {'image_id': image_id, 'pdk_root': root.rstrip('/') or '/'}


def _pdk_root_cache() -> Path:
    declared = os.environ.get(PDK_ROOT_CACHE_ENV)
    if declared:
        return Path(declared)
    xdg = os.environ.get('XDG_CACHE_HOME')
    return (Path(xdg) if xdg else Path.home() / '.cache') / 'vibeic' / 'pdk_root'


def _materialise_image_pdk(image: str, found: dict[str, str], pdk: str,
                           docker: str) -> tuple[Path, str]:
    """Copy `<image PDK_ROOT>/<pdk>` out of the image, once per image ID.

    The copy lands in a scratch name and is renamed into place, and its marker
    is written last, so a reader sees a finished tree or none. Returns the host
    root (which holds `<pdk>/`) and whether it was `copied` or `reused`.
    """
    if _ce.no_container_route():
        root = Path(found['pdk_root'])
        if not (root / pdk).is_dir():
            raise Refusal('LL_IMAGE_PDK_ABSENT', str(root / pdk))
        return root, 'native'
    root = _pdk_root_cache() / found['image_id'].split(':', 1)[1]
    marker = root / f'{pdk}{PDK_ROOT_MARKER}'
    guest = f"{found['pdk_root']}/{pdk}"
    want = {'image_id': found['image_id'], 'pdk': pdk, 'guest_path': guest}
    try:
        recorded = json.loads(marker.read_text())
    except (OSError, ValueError):
        recorded = None
    if isinstance(recorded, dict) and all(recorded.get(k) == v for k, v in want.items()) \
            and (root / pdk).is_dir():
        return root, 'reused'
    try:
        root.mkdir(parents=True, exist_ok=True)
        scratch = Path(tempfile.mkdtemp(prefix=f'.{pdk}.partial-', dir=root))
    except OSError as exc:
        raise Refusal('LL_PDK_ROOT_CACHE_UNWRITABLE', f'{root}: {exc}') from None
    try:
        # Nix PDK trees contain read-only directories and interior store
        # symlinks. docker cp -L can install their mode before their children
        # and cannot materialise that tree. Copy within the image, resolving
        # its own links, and apply directory modes after their contents.
        copied = subprocess.run([
            docker, 'run', *_dmem.docker_memory_flags(), '--rm', '--network', 'none',
            '--user', f'{os.getuid()}:{os.getgid()}',
            '-v', f'{scratch}:{scratch}', '--entrypoint', 'python3', found['image_id'],
            '-c', 'import shutil,sys;shutil.copytree(sys.argv[1],sys.argv[2],symlinks=False)',
            guest, str(scratch / pdk)], capture_output=True, text=True)
        if copied.returncode or not (scratch / pdk).is_dir():
            raise Refusal('LL_IMAGE_PDK_ABSENT',
                          f'{image}: {guest} not a directory in the image '
                          f'(rc={copied.returncode} {copied.stderr.strip()[:200]})')
        try:
            source_mode = (scratch / pdk).stat().st_mode
            (scratch / pdk).chmod(source_mode | 0o200)
            (scratch / pdk).rename(root / pdk)
            (root / pdk).chmod(source_mode)
        except OSError:
            if not (root / pdk).is_dir():   # another resolver won the rename; keep theirs
                raise
        write_json(marker, {**want, 'image': image, 'host_path': str(root / pdk)})
    finally:
        shutil.rmtree(scratch, ignore_errors=True)
    return root, 'copied'


#: Pruning keeps the current image's copy and this many previous ones; a copy
#: is removed only when its image is gone from this host and nothing uses it.
PDK_ROOT_KEEP_PREVIOUS = 1
PDK_ROOT_PRUNE_LOG = 'pdk_root_prune.log.jsonl'


def _docker_lines(docker: str, *argv: str) -> list[str] | None:
    """stdout lines of a docker query, or None when docker could not answer."""
    try:
        done = subprocess.run([docker, *argv], capture_output=True, text=True)
    except OSError:
        return None
    return None if done.returncode else [l.strip() for l in done.stdout.splitlines() if l.strip()]


def prune_pdk_root_cache(current_image_id: str, docker: str = 'docker') -> dict[str, Any]:
    """Remove cached PDK-root copies whose image is no longer on this host.

    Kept: the current image's copy, the `PDK_ROOT_KEEP_PREVIOUS` most recently
    made other copies, any copy whose image this host still holds, any copy a
    running container binds, and any copy still being made. When docker cannot
    list the host's images or containers nothing is removed (a copy that could
    not be looked at is never presumed unused). Every decision is appended to
    `<cache>/pdk_root_prune.log.jsonl` and returned.
    """
    cache = _pdk_root_cache()
    current = current_image_id.split(':', 1)[-1]
    record: dict[str, Any] = {'cache': str(cache), 'current': current_image_id,
                              'kept': [], 'removed': [], 'refused': None}
    try:
        others = [d for d in cache.iterdir() if d.is_dir() and d.name != current
                  and re.fullmatch(r'[0-9a-f]{64}', d.name)]
    except OSError:
        return record
    if not others:
        return record

    def made(d: Path) -> float:
        return max((m.stat().st_mtime for m in d.glob(f'*{PDK_ROOT_MARKER}')),
                   default=d.stat().st_mtime)
    others.sort(key=made, reverse=True)
    record['kept'] = [{'image_id': f'sha256:{d.name}', 'why': 'previous'}
                      for d in others[:PDK_ROOT_KEEP_PREVIOUS]]
    candidates = others[PDK_ROOT_KEEP_PREVIOUS:]
    held = sources = None
    if candidates:
        held = _docker_lines(docker, 'image', 'ls', '--no-trunc', '--format', '{{.ID}}')
        running = _docker_lines(docker, 'ps', '-q', '--no-trunc')
        sources = [] if running == [] else (_docker_lines(
            docker, 'inspect', '--format', '{{range .Mounts}}{{.Source}}\n{{end}}', *running)
            if running is not None else None)
    if candidates and (held is None or sources is None):
        record['refused'] = ('docker could not list the host images or the running '
                             "containers' mounts; nothing removed")
    elif candidates:
        used = {Path(src).relative_to(base).parts[0] for src in sources
                for base in {cache, cache.resolve()}
                if Path(src).is_relative_to(base) and Path(src) != base}
        for d in candidates:
            why = ('image still on this host' if f'sha256:{d.name}' in held else
                   'bound by a running container' if d.name in used else
                   'copy in progress' if any(d.glob('.*.partial-*')) else None)
            if why:
                record['kept'].append({'image_id': f'sha256:{d.name}', 'why': why})
                continue
            try:
                shutil.rmtree(d)
                record['removed'].append({'image_id': f'sha256:{d.name}', 'path': str(d)})
            except OSError as exc:
                record['kept'].append({'image_id': f'sha256:{d.name}', 'why': f'remove failed: {exc}'})
    try:
        with (cache / PDK_ROOT_PRUNE_LOG).open('a') as log:
            log.write(json.dumps(record, sort_keys=True) + '\n')
    except OSError:
        pass
    return record


def pdk_root_resolution(project: Path | None = None, pdk: str | None = None, *,
                        image: str | None = None, docker: str = 'docker',
                        native_handoff: bool = False) -> dict[str, Any]:
    """Declared > resolved at run time > refused by name, like `resolve_image`.

    1. declared: switch ``pdk_root_host``, else ``VIBEIC_LIBRELANE_PDK_ROOT``.
    2. resolved: the RESOLVED image's own ``PDK_ROOT`` env, joined with the
       design's PDK (the caller's resolved PDK, else the switch's ``pdk``) and
       copied once per image ID to a host directory every consumer can bind.
    3. neither: `LL_PDK_ROOT_NOT_RESOLVABLE`, naming why resolution failed.
    The answer says where the root came from; with a project it is also
    recorded in `phase3/librelane_pdk_root.provenance.json`.
    """
    path = project / 'phase3/librelane_switch.json' if project else None
    switch = _load(path) if path and path.is_file() else {}
    mismatch = _provider_route_mismatch(image, project,
                                        native_handoff=native_handoff)
    if mismatch is not None:
        raise mismatch
    provider = _provider_for_image(image)
    if provider is None and _explicit_local_route(project):
        provider = local_runtime(project, pdk)
    if provider is not None:
        if provider.pdk and pdk and provider.pdk != str(pdk):
            raise Refusal('LL_LOCAL_PDK_PROVIDER_MISMATCH',
                          f'provider declares {provider.pdk!r}; caller requested {pdk!r}')
        answer = {'path': provider.pdk_root, 'source': 'local_runtime',
                  'pdk': provider.pdk or pdk,
                  'pdk_from': ('runtime configuration' if provider.pdk else 'caller')}
        if project is not None and (project / 'phase3').is_dir():
            write_json(project / PDK_ROOT_PROVENANCE_REL, answer)
        return answer
    # Only the production/native Step-15 handoff is already inside the EDA
    # image.  Other direct callers may run on a host where this probe is true,
    # but a declared root remains the contract they supplied explicitly.
    local_image_route = native_handoff and _ce.no_container_route()
    if switch.get('pdk_root_host') and not local_image_route:
        answer = {'path': str(switch['pdk_root_host']), 'source': 'declared',
                  'declared_by': 'phase3/librelane_switch.json pdk_root_host'}
    elif os.environ.get('VIBEIC_LIBRELANE_PDK_ROOT') and not local_image_route:
        answer = {'path': os.environ['VIBEIC_LIBRELANE_PDK_ROOT'], 'source': 'declared',
                  'declared_by': 'env VIBEIC_LIBRELANE_PDK_ROOT'}
    else:
        answer = None
    if answer is not None:
        # A declared root is a PDK_ROOT: the tree a consumer reads is
        # <path>/<pdk>. Record WHICH PDK when it is known, so a consumer of
        # native consumers can resolve the selected PDK paths.
        declared_pdk = pdk or switch.get('pdk')
        if declared_pdk and _PDK_NAME.match(str(declared_pdk)):
            answer['pdk'] = str(declared_pdk)
            answer['pdk_from'] = ('caller (the design\'s resolved PDK)' if pdk
                                  else 'phase3/librelane_switch.json pdk')
    else:
        pdk_source = 'caller (the design\'s resolved PDK)' if pdk else \
            'phase3/librelane_switch.json pdk'
        pdk = pdk or switch.get('pdk')
        try:
            if not pdk:
                raise Refusal('LL_PDK_UNDECLARED', 'no design PDK (caller or switch pdk)')
            if not _PDK_NAME.match(str(pdk)):
                raise Refusal('LL_PDK_NAME_INVALID', repr(pdk))
            image = image or resolve_image(project)
            found = image_pdk_root(image, docker)
            root, how = _materialise_image_pdk(image, found, str(pdk), docker)
            # A new copy is when an older image's copy may have become stale.
            pruned = prune_pdk_root_cache(found['image_id'], docker) if how == 'copied' else None
        except Refusal as exc:
            raise Refusal('LL_PDK_ROOT_NOT_RESOLVABLE',
                          'not declared (switch pdk_root_host / VIBEIC_LIBRELANE_PDK_ROOT) '
                          f'and not resolved from the image: {exc}') from None
        answer = {'path': str(root), 'source': 'resolved',
                  'derivation': {'image': image, 'image_id': found['image_id'],
                                 'image_pdk_root': found['pdk_root'],
                                 'image_pdk_root_from': ('native environment PDK_ROOT'
                                                        if how == 'native' else
                                                        'docker image inspect Config.Env PDK_ROOT'),
                                 'pdk': str(pdk), 'pdk_from': pdk_source,
                                 'guest_path': f"{found['pdk_root']}/{pdk}",
                                 'host_path': str(root / str(pdk)),
                                 'cache': how, 'cache_prune': pruned}}
    if project is not None and (project / 'phase3').is_dir():
        write_json(project / PDK_ROOT_PROVENANCE_REL, answer)
    return answer


def resolve_pdk_root(project: Path | None = None, pdk: str | None = None, *,
                     image: str | None = None, docker: str = 'docker',
                     native_handoff: bool = False) -> str | None:
    """The host PDK root per `pdk_root_resolution`, or None when it refuses."""
    try:
        return pdk_root_resolution(project, pdk, image=image, docker=docker,
                                   native_handoff=native_handoff)['path']
    except Refusal:
        return None


def resolve_image(project: Path | None = None, *, record: bool = True) -> str:
    """Resolve the native executable or selected container image."""
    runtime = local_runtime(project)
    if runtime is not None:
        return runtime
    switch = _provider_switch(project)
    if switch.get('image') or os.environ.get('VIBEIC_LIBRELANE_IMAGE'):
        return str(switch.get('image') or os.environ['VIBEIC_LIBRELANE_IMAGE'])
    import _eda_pin
    try:
        return _eda_pin.image_reference()
    except _eda_pin.ImageNotResolvable as exc:
        raise Refusal('LL_IMAGE_NOT_RESOLVABLE', str(exc)) from None


# LibreLane's OpenROAD scripts name some commands by an ABBREVIATION of the
# real command (`est::check_corner_wire_cap` for `..._caps`, `utl::metric_int`
# for `utl::metric_integer`).  Older OpenROAD builds expanded a unique prefix;
# in 26Q3-2943 the unknown-command handler is OpenSTA's, which looks the
# prefix up relative to `::sta`, so a qualified abbreviation in another
# namespace no longer resolves and OpenROAD.STAMidPNR dies (MEASURED on
# 0.3.77: `invalid command name "est::check_corner_wire_cap"`).  The probe
# below derives, from the image's OWN script tree and OWN OpenROAD binaries,
# every referenced command that is absent but has exactly one expansion; the
# contract defines exactly those aliases in an OpenROAD init file.  A prefix
# with several expansions is a real API skew and refuses.
_TCL_PROBE = r'''set -e
root=$(python3 -c 'import librelane,os;print(os.path.join(os.path.dirname(librelane.__file__),"scripts","openroad"))')
own=$(grep -rhoE 'namespace +eval +(::)?[A-Za-z_][A-Za-z0-9_]*' "$root" --include='*.tcl' | awk '{print $3}' | sed 's/^:://' | sort -u)
grep -rhoE '\b[a-z]+::[A-Za-z_][A-Za-z0-9_]*' "$root" --include='*.tcl' | sort -u \
  | grep -vE "^($(echo $own | tr ' ' '|')|__none__)::" > /tmp/vibeic_cmds.txt
cat > /tmp/vibeic_probe.tcl <<'EOF'
set f [open /tmp/vibeic_cmds.txt]
foreach c [split [read $f] "\n"] {
  if {$c eq "" || [llength [info commands ::$c]] || [llength [info procs ::$c]]} { continue }
  puts "VIBEIC_TCL_MISSING $c [lsort [info commands ::${c}*]]"
}
EOF
for bin in /foss/tools/openroad/bin/openroad /foss/tools/openroad/bin/openroad-python; do
  [ -x "$bin" ] && LD_LIBRARY_PATH="/opt/or-tools/lib${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}" \
    "$bin" -no_init -no_splash -exit /tmp/vibeic_probe.tcl 2>&1 | grep '^VIBEIC_TCL_MISSING' || true
done'''

_CAPABILITY: dict[tuple[str, str], dict] = {}


def _parse_tcl_probe(text: str) -> tuple[dict[str, str], list[str], dict[str, list[str]]]:
    """Unique expansions become aliases; none is recorded; several refuse."""
    aliases: dict[str, str] = {}
    unresolved: set[str] = set()
    ambiguous: dict[str, list[str]] = {}
    for line in text.splitlines():
        parts = line.split()
        if len(parts) < 2 or parts[0] != 'VIBEIC_TCL_MISSING':
            continue
        name, expansions = parts[1], [x.lstrip(':') for x in parts[2:]]
        if len(expansions) == 1:
            aliases[name] = expansions[0]
        elif expansions:
            ambiguous[name] = expansions
        else:
            unresolved.add(name)
    return aliases, sorted(unresolved), ambiguous


def image_capability(image: str, docker: str = 'docker') -> dict:
    provider = _provider_for_image(image)
    mismatch = _provider_route_mismatch(provider)
    if mismatch is not None:
        raise mismatch
    key = (str(image), docker)
    if key in _CAPABILITY:
        return _CAPABILITY[key]
    probe = [docker, 'run', *_dmem.docker_memory_flags(), '--rm', '--entrypoint', 'sh', image, '-c',
             'python3 -m librelane.steps run --help >/dev/null && '
             'yosys -Q -T -y /dev/null -p help >/dev/null']
    result = run_container(probe, probe_deadline_s=PROBE_DEADLINE_S)
    if result.returncode:
        raise Refusal('LL_IMAGE_INCAPABLE', f'{image}: LibreLane CLI or yosys CLI -y unavailable (rc={result.returncode})')
    try:
        tcl = run_container([docker, 'run', *_dmem.docker_memory_flags(), '--rm', '--network', 'none',
                             '--entrypoint', 'bash', image, '-c', _TCL_PROBE],
                            probe_deadline_s=PROBE_DEADLINE_S)
    except Refusal as exc:
        if exc.code not in ('LL_TOOL_DEADLINE', 'LL_TOOL_STALLED'):
            raise
        # Best effort, like rc != 0 below: a secondary probe that stopped
        # measured nothing, and the capability verdict above still stands.
        _CAPABILITY[key] = {'image': image, 'openroad_aliases': {},
                            'tcl_probe': f'NOT_MEASURED: {str(exc)[:300]}'}
        return _CAPABILITY[key]
    if tcl.returncode:
        # The CLI probe above is the capability verdict; this one only derives
        # aliases.  Unmeasured means none are added: a step that needs one
        # then fails by name (LL_STEP_FAILED), never silently passes.
        _CAPABILITY[key] = {'image': image, 'openroad_aliases': {},
                            'tcl_probe': f'NOT_MEASURED: rc={tcl.returncode}'}
        return _CAPABILITY[key]
    aliases, unresolved, ambiguous = _parse_tcl_probe(tcl.stdout)
    if ambiguous:
        raise Refusal('LL_IMAGE_TCL_API_SKEW', json.dumps(ambiguous, sort_keys=True))
    _CAPABILITY[key] = {'image': image, 'openroad_aliases': aliases,
                        'unresolved_guarded': unresolved, 'tcl_probe': 'MEASURED'}
    return _CAPABILITY[key]


def openroad_home(folder: Path, capability: dict | None,
                  extra: list[str] | None = None) -> Path | None:
    """Write native Tcl aliases and the caller's additional init lines."""
    aliases = (capability or {}).get('openroad_aliases') or {}
    if not aliases and not extra:
        return None
    folder.mkdir(parents=True, exist_ok=True)
    lines = ['# Native OpenROAD aliases derived from the installed tool']
    for short, full in sorted(aliases.items()):
        lines.append(f'if {{[llength [info commands ::{short}]] == 0}} '
                     f'{{ proc ::{short} {{args}} {{ return [::{full} {{*}}$args] }} }}')
    if extra:
        lines.extend(extra)
    (folder / '.openroad').write_text('\n'.join(lines) + '\n')
    (folder / '.sta').unlink(missing_ok=True)
    (folder / '.bashrc').write_text('')
    return folder


def derive_step_config(config: Path, output: Path, updates: dict[str, tuple[Any, str]]) -> Path:
    """A copy of a resolved step config with named keys set, each with its source.

    Used for values LibreLane's design-config loader drops before a step sees
    them (a plugin step's own variables) and for one step run per corner.  The
    step's view sidecar is copied beside it; every change is recorded in
    ``<output>.provenance.json``.  An unknown key is refused: the step's own
    ``Step.load`` validates the result against its declared variables.
    """
    doc = _load(config)
    provenance = {}
    for key, (value, source) in updates.items():
        doc[key] = value
        provenance[key] = source
    write_json(output, doc)
    write_json(output.with_suffix('.provenance.json'),
               {'derived_from': str(config), 'derived_from_sha256': digest(config),
                'keys': provenance})
    if views_path(config).is_file():
        write_json(views_path(output), _load(views_path(config)))
    # CR-1 rollout: report declared/applied drift at the actual derived step
    # boundary. Existing published runs may drift, so this remains advisory.
    import declared_knob_applied_parity as _parity
    aliases = {'MAX_FANOUT_CONSTRAINT': 'SYNTH_MAX_FANOUT',
               'PDN_VOFFSET': 'FP_PDN_VOFFSET'}
    knobs = {'SYNTH_MAX_FANOUT', 'FP_CORE_UTIL', 'PL_TARGET_DENSITY',
             'FP_PDN_VOFFSET'}
    observed = {}
    for key, value in doc.items():
        knob = aliases.get(key, key)
        if knob in knobs:
            observed[knob] = (value, provenance.get(key, str(output)))
    project = next((parent for parent in output.parents
                    if (parent / 'input/docs').is_dir() or
                    (parent / 'phase1/generated_docs').is_dir()), None)
    report = (_parity.compare(project, observed) if project else
              {'mode': 'ADVISORY', 'rows': {key: {
                  'status': 'NOT_MEASURED', 'reason': f'{key}: design input root unread',
                  'applied': value[0], 'consumer': value[1]}
                  for key, value in observed.items()}})
    write_json(output.with_suffix('.parity.json'), report)
    return output


#: A step's production default once its lane has CUT OVER (MIGRATION_COMMON
#: criteria (a) and (b), or b-analog for an analog observer step). A step not
#: named here defaults to `direct`. A project opts out of a cut-over default by
#: naming the step `direct` in `phase3/librelane_switch.json`.
PRODUCTION_DEFAULTS: dict[str, str] = {
    # Landed Step2/Step3 defaults remain authoritative.
    '2': 'librelane', '3': 'librelane',
    # Analog A6/A7/A8 direct cutover. The project switch remains the
    # explicit opt-out (for example, {"A6": "direct"}).
    'A6': 'librelane', 'A7': 'librelane', 'A8': 'librelane',
    # Reviewed backend fill/stream default from the sealed delta.
    '34': 'librelane',
}

#: The chip path: a die that carries its own pad ring
#: (`_tapeout_declaration.requests_pad_ring`, the condition of step 15.5ic).
DESIGN_CLASS_CHIP_PAD_RING = 'chip_pad_ring'

#: Production defaults of a DESIGN CLASS, for steps whose tool path is proven
#: only there. T96 (2026-09-27) cut steps 15..20 over on the chip path: the
#: LibreLane Chip segment Floorplan..PadRing..GeneratePDN (15, 15.5ic),
#: GlobalPlacement..DetailedPlacement + Vibeic.InsertSpareCells (17, 18) and
#: CTS..ResizerTimingPostCTS (19, 20), measured on spm x gf180mcuD against the
#: direct chain (docs/librelane_contract.md, "Cut-over of 15..20"). A core-only
#: or HARDMACRO design has no Chip-flow segment (LL_FLOORPLAN_CORE_ONLY_UNSUPPORTED),
#: so it keeps `direct`. A step-wide `PRODUCTION_DEFAULTS` entry outranks these.
CLASS_PRODUCTION_DEFAULTS: dict[str, dict[str, str]] = {
    DESIGN_CLASS_CHIP_PAD_RING: {# Step 7 reuses the fixed 8/10 prelayout call:
                                 # its PVT matrix is the tool's resolved
                                 # STA_CORNERS, not a staged Liberty glob.
                                 # Source: cut-7 82e200e3632b (default hunk).
                                 '7': 'librelane',
                                 # Existing synthesis producer, now bound to
                                 # the Phase2/3 and Step14 product consumers.
                                 '9': 'librelane',
                                 '15': 'librelane', '15.5ic': 'librelane',
                                 '17': 'librelane', '18': 'librelane',
                                 '19': 'librelane', '20': 'librelane',
                                 # T99 + T102 r4 (owner ruling, CUT-OVER rule):
                                 # routing and the post-route repair, as one
                                 # chain (LL21 -> Vibeic.PostRouteRepair -> tail)
                                 '21': 'librelane', '32': 'librelane',
                                 # CUT_W2 (1), R-0929-TOOL-DEFAULT: sign-off
                                 # STA is OpenROAD.STAPostPNR (every declared
                                 # scene, setup AND hold); the direct 2-corner
                                 # deck timed hold only at FF.
                                 '23': 'librelane',
                                 # R-0929-TOOL-DEFAULT (owner 2026-09-29) Wave 1
                                 # (TOOL_DUPLICATION_AUDIT §6), each measured:
                                 # 8  dual: OpenSTA read_sdc/check_setup on
                                 #    STAPrePNR AND the regex arm (T92); the
                                 #    regex retires once dual shows no
                                 #    regex-only finding.
                                 # 10 librelane: STAPrePNR (T92 parity SS/TT/FF
                                 #    15.59/17.76/18.29 ns = direct); its gate
                                 #    judge_slack refuses black boxes and
                                 #    non-finite slack.
                                 # 26 librelane: CheckAntennas on the shipped
                                 #    route + KLayout.Antenna on the shipped GDS
                                 #    (T101 (a)(b); F14 PDK root).
                                 # 26.5ic librelane: KLayout.SealRing with the
                                 #    fork's verify_ring + seal-ring metric;
                                 #    die_finishing_gen verifies the tool's GDS.
                                 '8': 'dual', '10': 'librelane',
                                 '26': 'librelane', '26.5ic': 'librelane',
                                 # CUT_W2 item 2: shared native RCX authority
                                 # with the repair's own pre-tail route basis.
                                 '22': 'librelane'},
}

#: A class default runs only inside the chain it continues. The producers are
#: one LibreLane chain (15.5ic -> 15 -> 17/18) or one deck region (19 with 20),
#: so a project that names one of these steps anything but `librelane` takes
#: the steps that depend on it back to `direct` with it, instead of meeting
#: the runner's split refusals (LL_FLOORPLAN_PADRING_SPLIT_UNSUPPORTED,
#: LL_PLACEMENT_NEEDS_LIBRELANE_FLOORPLAN, LL_SPARE_PLACEMENT_SPLIT_UNSUPPORTED,
#: LL_CTS_HOLD_SPLIT_UNSUPPORTED) on a combination it never asked for.
CLASS_DEFAULT_REQUIRES: dict[str, tuple[str, ...]] = {
    '15': ('15.5ic',), '17': ('15', '15.5ic', '18'), '18': ('15', '15.5ic', '17'),
    '19': ('20',), '20': ('19',),
    # Step 32's class default is the repair INSIDE step 21's LibreLane chain
    # (the proven chain, T102 r3/r4); a project that takes 21 back to direct
    # takes 32 with it, onto the deck's own post-route repair. Step 21 on
    # LibreLane stands on its own (T99 routed after direct 19/20 too).
    '32': ('21',)}


def design_class(project: Path) -> str | None:
    """The design class whose production defaults apply, or None."""
    import _tapeout_declaration as TD
    return DESIGN_CLASS_CHIP_PAD_RING if TD.requests_pad_ring(project) else None


def _class_default(project: Path, step: str, named: dict[str, Any],
                   _seen: frozenset[str] = frozenset()) -> str | None:
    """`step`'s class default, when every step it continues also resolves to
    `librelane`; None otherwise (the caller then uses `direct`)."""
    defaults = CLASS_PRODUCTION_DEFAULTS.get(design_class(project) or '', {})
    mode = defaults.get(step)
    if mode is None:
        return None
    seen = _seen | {step}
    for need in CLASS_DEFAULT_REQUIRES.get(step, ()):
        if need in named:
            if named[need] != 'librelane':
                return None
        elif need not in seen and _class_default(project, need, named, seen) != 'librelane':
            return None
    return mode


def selected_mode(project: Path, step: str) -> str:
    """The step switch, production default, class default, or direct tool."""
    path = project / 'phase3/librelane_switch.json'
    steps = _load(path).get('steps', {}) if path.is_file() else {}
    if step in steps:
        mode = steps[step]
    elif step in PRODUCTION_DEFAULTS:
        mode = PRODUCTION_DEFAULTS[step]
    else:
        mode = _class_default(project, step, steps) or 'direct'
    if mode not in ('direct', 'librelane', 'dual'):
        raise Refusal('LL_INVALID_SWITCH', f'{step}: {mode}')
    return mode


def class_defaults_in_force(project: Path) -> dict[str, str]:
    """The steps this project runs on a class default rather than its switch:
    `{step: mode}` for every class-default step the switch does not name and
    whose default survives `CLASS_DEFAULT_REQUIRES`. Empty for a project
    outside every class."""
    path = project / 'phase3/librelane_switch.json'
    steps = _load(path).get('steps', {}) if path.is_file() else {}
    cls = design_class(project)
    return {step: selected_mode(project, step)
            for step in CLASS_PRODUCTION_DEFAULTS.get(cls or '', {})
            if step not in steps and step not in PRODUCTION_DEFAULTS
            and _class_default(project, step, steps) is not None}


#: vibe-ic's own LibreLane steps (`Vibeic.*`), shipped with this plugin in
#: `programs/librelane_plugins/librelane_plugin_vibeic`. LibreLane discovers a
#: `librelane_plugin_*` module on `sys.path`; the contract mounts `programs/`
#: read-only at its own path and adds the plugin root to `PYTHONPATH` only
#: for a run that names such a step, so every other step's invocation and
#: are unchanged.
PLUGIN_ROOT = Path(__file__).resolve().parent / 'librelane_plugins'
PLUGIN_STEP_PREFIX = 'Vibeic.'
#: The `programs/` modules the plugin's steps import (inputs of those steps).


def _plugin_args(step_ids: list[str]) -> list[str]:
    if not any(str(s).startswith(PLUGIN_STEP_PREFIX) for s in step_ids):
        return []
    programs = PLUGIN_ROOT.parent.resolve()
    return ['-v', f'{programs}:{programs}:ro', '-e', f'PYTHONPATH={PLUGIN_ROOT.resolve()}']


#: The steps whose config must carry the die the run itself settled on:
#: step 15's floorplan sizes the die, and 15.5ic's PadRing (`pad_cfg.tcl`)
#: reads `$::env(DIE_AREA)`, which LibreLane never exports for a null value.
_DIE_STEPS = frozenset({'OpenROAD.Floorplan', 'OpenROAD.PadRing'})


def _rect_differs(a: Any, b: Any) -> bool:
    return len(a) != len(b) or any(abs(x - y) > 1e-6 for x, y in zip(a, b))


def _whole(rect: list[float]) -> list[float | int]:
    return [int(v) if float(v).is_integer() else v for v in rect]


def _runner_floorplan(project: Path) -> tuple[list | None, list | None, dict[str, str], str, dict]:
    """(die, core, sources, why, record) from the run's floorplan authority.

    `phase3_one_shot_runner.step_pnr` writes `floorplan_rectangles.json`
    before it hands steps 15/15.5ic to LibreLane; it is read through
    `_declared_die`, the one reader of that record. The core is the slot's
    `floorplan_rect_um` when the record names one, else the die inset by
    `core_pad_um` -- the direct deck's own `-core_area`.
    """
    import _declared_die as DD
    die, why, record = DD.declared(project)
    if die is None:
        return None, None, {}, why, record
    die = _whole(die)
    base = DD.FLOORPLAN_RECTANGLES_REL
    sources = {'DIE_AREA': (f"{base}.die_rect_um - {why} "
                            f"({record.get('program') or 'the run'})")}
    rect, pad = record.get('floorplan_rect_um'), record.get('core_pad_um')
    core = None
    if rect is not None:
        core = _whole([float(v) for v in _rect(rect, f'{base}.floorplan_rect_um')])
        sources['CORE_AREA'] = f'{base}.floorplan_rect_um (the slot core)'
    elif isinstance(pad, (int, float)) and not isinstance(pad, bool) and pad >= 0:
        core = _whole([die[0] + pad, die[1] + pad, die[2] - pad, die[3] - pad])
        sources['CORE_AREA'] = (f'{base}.die_rect_um inset by {base}.core_pad_um '
                                f'({pad}) - the direct deck\'s -core_area')
    return die, core, sources, why, record


def _derived_provisional_die_source(project: Path, record: dict,
                                    declared: list, settled: list
                                    ) -> str | None:
    """Read a provisional slot replacement whose declared rectangles agree."""
    intent = record.get('die_intent')
    if not isinstance(intent, dict) or intent.get('intent') != 'DERIVED_PROVISIONAL_SLOT':
        return None

    def _wxh(value: Any) -> list[int] | None:
        match = re.fullmatch(r'\s*(\d+)\s*[xX]\s*(\d+)\s*', str(value or ''))
        return [0, 0, int(match.group(1)), int(match.group(2))] if match else None

    old_rect = _wxh(intent.get('declared_die_um'))
    new_rect = _wxh(intent.get('resolved_die_um'))
    if old_rect is None or new_rect is None:
        return None
    if _rect_differs(declared, old_rect) or _rect_differs(settled, new_rect):
        return None
    slot = intent.get('resolved_slot')
    rel = intent.get('source_relpath')
    if (not isinstance(slot, str) or not isinstance(rel, str)
            or Path(rel).name != rel):
        return None
    slot_file = project / 'input' / 'submission_template' / 'slots' / f'{slot}.yaml'
    try:
        contract = json.loads(slot_file.read_text(errors='replace'))
        die_area = (contract.get('die_area') or {}).get('rect')
        if isinstance(die_area, str):
            die_area = die_area.split()
        die_area = [float(v) for v in die_area]
        if len(die_area) != 4:
            return None
    except (OSError, ValueError, TypeError):
        return None
    if (contract.get('slot') != slot
            or _rect_differs(_whole(die_area), new_rect)):
        return None
    return (f"reports/phase3/floorplan_rectangles.json.die_intent: "
            f"provisional slot {intent.get('declared_slot')} -> {slot} ({rel})")


def _apply_runner_floorplan(project: Path, config: dict, sources: dict,
                            step_ids: list[str]) -> None:
    """Give a 15/15.5ic chain the die the run settled on, when none is declared.

    A declared die wins and must agree with the run's record; a declared
    `relative` sizing cannot carry a pad ring; a PadRing that neither source
    gives a die is refused before the tool, never left to die at pad_cfg.tcl.
    """
    if not _DIE_STEPS & set(step_ids):
        return
    padring = 'OpenROAD.PadRing' in step_ids
    if config.get('FP_SIZING') == 'relative':
        if padring:
            raise Refusal('LL_PADRING_DIE_RELATIVE_DECLARED',
                          f"{sources.get('FP_SIZING')} = relative: a utilisation-sized "
                          'floorplan cannot carry a pad ring')
        return
    die, core, derived, why, floorplan_record = _runner_floorplan(project)
    if die is not None:
        if 'DIE_AREA' in config:
            if _rect_differs(config['DIE_AREA'], die):
                replacement = _derived_provisional_die_source(
                    project, floorplan_record, config['DIE_AREA'], die)
                if replacement is None:
                    raise Refusal('LL_DERIVED_DIE_CONFLICT',
                                  f"declared {config['DIE_AREA']} ({sources['DIE_AREA']}) vs "
                                  f"the run's {die} ({derived['DIE_AREA']})")
                _set(config, sources, 'DIE_AREA', die, replacement)
        else:
            _set(config, sources, 'DIE_AREA', die, derived['DIE_AREA'])
        _set(config, sources, 'FP_SIZING', config.get('FP_SIZING') or 'absolute',
             sources.get('FP_SIZING') or derived['DIE_AREA'])
        if 'CORE_AREA' not in config and core is not None:
            _set(config, sources, 'CORE_AREA', core, derived['CORE_AREA'])
    if 'DIE_AREA' in config and 'CORE_AREA' in config:
        d, c = config['DIE_AREA'], config['CORE_AREA']
        if not (c[0] >= d[0] and c[1] >= d[1] and c[2] <= d[2] and c[3] <= d[3]):
            raise Refusal('LL_DERIVED_CORE_OUTSIDE_DIE',
                          f"{c} ({sources['CORE_AREA']}) vs {d} ({sources['DIE_AREA']})")
    template = config.get('FP_DEF_TEMPLATE')
    if template and 'DIE_AREA' in config:
        stated = _def_die_area(project / str(template).removeprefix('dir::'))
        if stated is not None and _rect_differs(stated, config['DIE_AREA']):
            raise Refusal('LL_DEF_TEMPLATE_DIE_MISMATCH',
                          f"{template} DIEAREA {stated} vs {config['DIE_AREA']} "
                          f"({sources['DIE_AREA']})")
    if padring and 'DIE_AREA' not in config:
        raise Refusal('LL_PADRING_DIE_UNDERIVABLE',
                      f'no declared answers.die_area_um and {why}')


#: The chip-top producer's record (step 15.5ic, `io_pad_chip_top_gen`): the
#: pad-carrying top it wrapped around the core, and which module is which.
CHIP_TOP_RECORD_REL = 'reports/phase3/io_pad_chip_top.json'


def layout_top(project: Path) -> tuple[str, str, str] | None:
    """(chip_top, core, source) when this chip-path run built a pad-carrying top.

    On the chip path step 15.5ic wraps the core in a top that instantiates the
    IO cells, and every layout database from 15.5ic on is that top: the direct
    deck links it (`_inject_padring_chip_top`) and LibreLane's PadRing places
    the instances PAD_* name inside it. Read from the producer's record, never
    from a name; None for a core-only or HARDMACRO design, or before the
    producer wrote a top.
    """
    if design_class(project) != DESIGN_CLASS_CHIP_PAD_RING:
        return None
    path = project / CHIP_TOP_RECORD_REL
    if not path.is_file():
        return None
    record = _load(path)
    if record.get('verdict') != 'WROTE':
        return None
    # WROTE claims a wrapper: a record that cannot name it, or names one
    # module twice, contradicts itself and is refused, never read as "no top".
    chip_top, core = record.get('chip_top_module'), record.get('core_module')
    problems = []
    if not record.get('chip_top_verilog'):
        problems.append('no chip_top_verilog')
    if not isinstance(chip_top, str) or not chip_top:
        problems.append(f'chip_top_module {chip_top!r}')
    if not isinstance(core, str) or not core:
        problems.append(f'core_module {core!r}')
    if not problems and chip_top == core:
        problems.append(f'chip_top_module and core_module are both {core!r}')
    if problems:
        raise Refusal('LL_CHIP_TOP_RECORD_CONTRADICTORY',
                      f"{CHIP_TOP_RECORD_REL} verdict WROTE but "
                      f"{'; '.join(problems)}")
    return chip_top, core, f'{CHIP_TOP_RECORD_REL}.chip_top_module'


def _apply_layout_top(project: Path, config: dict, sources: dict) -> None:
    """A layout chain on the chip path links the chip top, not the core.

    The declared `top_cell` may name the core (spm, subservient: the product
    name); this run's own record says the layout's top is the wrapper around
    it, which is the rule `general_precheck._recorded_physical_top` applies to
    the streamed layout. A declared name that is neither refuses.
    """
    found = layout_top(project)
    if found is None:
        return
    chip_top, core, source = found
    declared = config.get('DESIGN_NAME')
    if declared == chip_top:
        return
    if declared not in (None, core):
        raise Refusal('LL_TOP_CELL_CONFLICT',
                      f"{sources.get('DESIGN_NAME')} = {declared!r} names neither the "
                      f"core {core!r} nor the chip top {chip_top!r} of {CHIP_TOP_RECORD_REL}")
    _set(config, sources, 'DESIGN_NAME', chip_top,
         f"{source} (the pad-carrying top around the core {core!r}; declared "
         f"top_cell {declared!r} is that core)" if declared else
         f"{source} (the pad-carrying top around the core {core!r})")


def _apply_synthesis_defines(project: Path, config: dict, sources: dict) -> None:
    """Carry the native synthesis configuration's preprocessing choices."""
    configs = [path for path in (project / 'phase3/librelane').glob('**/config.json')
               if (_load(path).get('meta') or {}).get('step') == 'Yosys.Synthesis'
               and 'attempts' not in path.relative_to(project).parts
               and (path.parent / 'state_out.json').is_file()]
    if len(configs) != 1:
        return
    native = _load(configs[0])
    if 'VERILOG_DEFINES' in native:
        _set(config, sources, 'VERILOG_DEFINES', native['VERILOG_DEFINES'],
             f'{configs[0].relative_to(project)}.VERILOG_DEFINES')


def native_supply_pdn_geometry(config: dict, record: dict) -> tuple[dict, list[list[str]], dict]:
    """Reserve the resolved native ring and connect actual core-facing pad metal."""
    from math import ceil
    result = dict(config)
    reach = (record.get('power_pad_plan') or {}).get('pad_strap_reach') or {}
    required = record.get('die_required_um') or {}
    if not (config.get('PDN_CORE_RING') and config.get('PDN_CORE_RING_CONNECT_TO_PADS')
            and record.get('verdict') == 'WROTE' and reach.get('verdict') == 'MEASURED'):
        return result, [], {}
    die, core = config.get('DIE_AREA'), config.get('CORE_AREA')
    if not die or not core:
        return result, [], {}
    widths = [float(config['PDN_CORE_RING_' + axis + 'WIDTH']) for axis in ('V', 'H')]
    spacing = max(float(config['PDN_CORE_RING_' + axis + 'SPACING']) for axis in ('V', 'H'))
    offset = max(float(config['PDN_CORE_RING_' + axis + 'OFFSET']) for axis in ('V', 'H'))
    gap = max(spacing, float(required['pad_strap_reach_um']) - min(widths) + spacing)
    inset = ceil(float(required['ring_depth_um']) + offset + 2 * max(widths) + spacing + gap)
    d, c = list(map(float, die)), list(map(float, core))
    result['CORE_AREA'] = [max(c[0], d[0] + inset), max(c[1], d[1] + inset),
                           min(c[2], d[2] - inset), min(c[3], d[3] - inset)]
    if result['CORE_AREA'][0] >= result['CORE_AREA'][2] or result['CORE_AREA'][1] >= result['CORE_AREA'][3]:
        raise Refusal('LL_PAD_PDN_CORE_DOES_NOT_FIT', f'{inset} um inset in {die}')
    pad_layers = {strap['layer'] for cell in reach.get('cells', {}).values()
                  for side in cell.get('sides', {}).values() for strap in side.get('straps', [])}
    ring_layers = {config.get('PDN_CORE_' + axis + '_LAYER') or config['PDN_' + axis + '_LAYER']
                   for axis in ('VERTICAL', 'HORIZONTAL')}
    connects = [list(pair) for pair in sorted({(pad, ring) for pad in pad_layers - ring_layers
                                             for ring in ring_layers if pad != ring})]
    return result, connects, {'core_inset_um': inset,
                             'core_area_changed': _rect_differs(c, result['CORE_AREA']),
                             'pad_layers': sorted(pad_layers),
                             'ring_layers': sorted(ring_layers),
                             'source': 'resolved native PDN ring + IO producer LEF pin geometry'}


def resolve_step_configs(project: Path, image: str, pdk: str,
                         step_ids: list[str], *, pdk_root: Path,
                         docker: str = 'docker',
                         folder: str = '37-config',
                         overlay: dict[str, tuple[Any, str]] | None = None) -> dict[str, Path]:
    """Resolve step configs from declared design inputs and the image's PDK.

    The installed LibreLane resolver supplies PDK values.  A prior run's
    resolved.json (including its design-specific numbers) is never an input.
    """
    image_capability(image, docker)
    if not (pdk_root / pdk).is_dir():
        raise Refusal('LL_PDK_MISSING', str(pdk_root / pdk))
    root = project / 'phase3/librelane' / folder
    root.mkdir(parents=True, exist_ok=True)
    design = root / 'design.json'
    emitted = emit_config(project, pdk, design)
    sources = _load(design.with_suffix('.provenance.json'))
    _apply_synthesis_defines(project, emitted, sources)
    _apply_runner_floorplan(project, emitted, sources, step_ids)
    _apply_layout_top(project, emitted, sources)
    for key, (value, source) in (overlay or {}).items():
        if key == 'EXTRA_EXCLUDED_CELLS':
            # This knob is a set of forbidden masters, not a replacement
            # value: the run-wide policy must retain PDK/design exclusions.
            inherited = emitted.get(key) or []
            if (not isinstance(inherited, list) or not isinstance(value, list)
                    or any(not isinstance(x, str) for x in inherited + value)):
                raise Refusal('LL_EXCLUSION_POLICY_INVALID', key)
            value = sorted(set(inherited) | set(value))
            source = (source + '; union with declared/PDK ' +
                      str(sources.get(key, 'none')))
        for older in _LEVER_SUPERSEDES.get(key, ()):
            if older in emitted:
                emitted.pop(older)
                sources[older] = f'superseded by {key} ({source})'
        _set(emitted, sources, key, value, source)
    # The explicit overlay outranks every declared or derived rectangle, and
    # the rules that judged those judged them BEFORE it; what the tool is
    # handed is judged here, whoever supplied each half.
    die, core = emitted.get('DIE_AREA'), emitted.get('CORE_AREA')
    if die and core and not (core[0] >= die[0] and core[1] >= die[1] and
                             core[2] <= die[2] and core[3] <= die[3]):
        raise Refusal('LL_CONFIG_CORE_OUTSIDE_DIE',
                      f"CORE_AREA {core} ({sources.get('CORE_AREA')}) vs "
                      f"DIE_AREA {die} ({sources.get('DIE_AREA')})")
    write_json(design, emitted)
    write_json(design.with_suffix('.provenance.json'), sources)
    requested = root / 'steps.json'
    write_json(requested, step_ids)
    script = '''import json,sys
from pathlib import Path
from librelane.flows.chip import Chip
from librelane.steps import Step
design, requested, output, pdk, project, image = sys.argv[1:]
flow = Chip(config=design, pdk=pdk, pdk_root="/pdk", design_dir=project)
raw = flow.config.to_raw_dict()
for step_id in json.loads(Path(requested).read_text()):
    target = Step.factory.get(step_id)
    if target is None:
        raise ValueError("unknown LibreLane step: " + step_id)
    names = {var.name for var in target.get_all_config_variables()}
    selected = {key: value for key, value in raw.items() if key in names}
    # A step outside the Chip flow (vibe-ic's own `Vibeic.*`) declares
    # variables the flow's resolver does not know, so the resolved dict drops
    # them; take exactly those, and only those, from the declared design file.
    if step_id.startswith("Vibeic."):
        declared = json.loads(Path(design).read_text())
        selected.update({key: value for key, value in declared.items()
                         if key in names and key not in selected})
    selected["meta"] = {"librelane_version": __import__("librelane.__version__", fromlist=["__version__"]).__version__, "step": step_id}
    Path(output, step_id + ".json").write_text(json.dumps(selected, indent=2, default=str) + "\\n")
    # LibreLane's Meta refuses unknown keys, so the step's declared views live beside it.
    Path(output, step_id + ".views.json").write_text(json.dumps({
        "step": step_id,
        "inputs": [getattr(f, "id", None) or f.value.id for f in target.inputs],
        "outputs": [getattr(f, "id", None) or f.value.id for f in target.outputs]}) + "\\n")
# The flow's own gates (`Flow.gating_config_vars`): a flow skips a step whose
# gating variable is false; a caller running steps one by one must too.
gates = getattr(Chip, "gating_config_vars", {}) or {}
Path(output, "flow_gates.json").write_text(json.dumps({
    step_id: {var: raw.get(var) for var in gates.get(step_id, [])}
    for step_id in json.loads(Path(requested).read_text()) if step_id in gates},
    indent=2, default=str) + "\\n")
'''
    runtime_design = _local_config_source(
        design, [(pdk_root, '/pdk')],
        local=_provider_for_image(image) is not None or _provider_route(project))
    cmd = [docker, 'run', *_dmem.docker_memory_flags(), '--rm',
           '-v', f'{project.resolve()}:{project.resolve()}',
           '-v', f'{pdk_root.resolve()}:/pdk:ro', *_plugin_args(step_ids),
           '--entrypoint', 'python3', image, '-c', script, str(runtime_design),
           str(requested), str(root), pdk, str(project.resolve()), image]
    result = run_container(cmd, probe_deadline_s=PROBE_DEADLINE_S, log=root / 'resolution.log')
    (root / 'resolution.log').write_text(result.stdout + '\n' + result.stderr)
    if result.returncode:
        raise Refusal('LL_CONFIG_RESOLUTION_FAILED', str(root / 'resolution.log'))
    configs = {step: root / f'{step}.json' for step in step_ids}
    for step, path in configs.items():
        if not path.is_file() or _load(path).get('meta', {}).get('step') != step:
            raise Refusal('LL_STEP_CONFIG_MISSING',
                          f'{step}: no config at {path} naming meta.step {step!r}')
    # Complete the native ring using the same invocation's resolved geometry.
    # Custom registry recipes retain their existing declared handling.
    if 'OpenROAD.GeneratePDN' in configs and 'OpenROAD.Floorplan' in configs:
        pdn = _load(configs['OpenROAD.GeneratePDN'])
        record_path = project / CHIP_TOP_RECORD_REL
        if not pdn.get('PDN_CFG') and record_path.is_file():
            floor = _load(configs['OpenROAD.Floorplan'])
            adjusted, connects, geometry = native_supply_pdn_geometry(
                {**pdn, 'CORE_AREA': floor.get('CORE_AREA')}, _load(record_path))
            if geometry:
                changed = geometry['core_area_changed']
                if changed and not str(sources.get('CORE_AREA', '')).startswith(
                        'reports/phase3/floorplan_rectangles.json'):
                    raise Refusal('LL_DECLARED_CORE_PAD_PDN_CLEARANCE',
                                  f"{floor['CORE_AREA']} needs {geometry['core_inset_um']} um inset")
                internal = internal_supply_grid_sources(_load(record_path))
                recipe = emit_pdn_cfg(image, pdk, root / 'pdn_cfg.tcl',
                                      docker=docker, native_connects=connects,
                                      **({'internal_supply_sources': internal} if internal else {}))
                for path in configs.values():
                    snapshot = _load(path)
                    if 'CORE_AREA' in snapshot:
                        snapshot['CORE_AREA'] = adjusted['CORE_AREA']
                    if recipe and 'PDN_CFG' in snapshot:
                        snapshot['PDN_CFG'] = str(recipe.resolve())
                    write_json(path, snapshot)
                emitted['CORE_AREA'] = adjusted['CORE_AREA']
                sources['CORE_AREA'] = str(sources.get('CORE_AREA')) + '; ' + geometry['source']
                if recipe:
                    emitted['PDN_CFG'] = str(recipe.resolve())
                    sources['PDN_CFG'] = geometry['source']
                write_json(design, emitted)
                write_json(design.with_suffix('.provenance.json'), sources)
                rectangles = project / 'reports/phase3/floorplan_rectangles.json'
                if rectangles.is_file() and changed:
                    fact = _load(rectangles)
                    fact['core_pad_um'] = max(float(fact.get('core_pad_um') or 0),
                                              geometry['core_inset_um'])
                    fact['native_pdn_supply_geometry'] = geometry
                    write_json(rectangles, fact)
                write_json(root / 'native_pdn_supply_geometry.json', {**geometry, 'connects': connects})
    return configs


def flow_gated_off(config_root: Path) -> dict[str, list[str]]:
    """The requested steps the flow itself would skip, each with the gating
    variables that are false, from ``flow_gates.json`` written by
    ``resolve_step_configs`` (the image's ``Flow.gating_config_vars`` over the
    resolved design config). A missing file refuses: an ungated chain would
    run steps the flow never runs (a heuristic diode on every pin, MEASURED
    on spm: 206 diodes and 92 max-fanout DRVs)."""
    path = config_root / 'flow_gates.json'
    if not path.is_file():
        raise Refusal('LL_FLOW_GATES_UNRESOLVED', str(path))
    return {step: sorted(var for var, value in gates.items() if not value)
            for step, gates in _load(path).items()
            if any(not value for value in gates.values())}


_PDN_PAYLOAD_KEY = 'vibeic_pdn_payload_v1'


def _extract_pdn_payload(stdout: str) -> str:
    """Extract the image's Tcl from its structured stdout envelope.

    The pinned image's normal entrypoint may print startup diagnostics before
    executing the requested command.  Those bytes are not Tcl and must never
    be copied into a generated config.  The probe therefore emits one JSON
    record whose value is the *entire* native script; this reader accepts only
    exactly one such record and preserves the value byte-for-byte.
    """
    records: list[str] = []
    for line in str(stdout or '').splitlines():
        try:
            value = json.loads(line)
        except (TypeError, ValueError):
            continue
        if isinstance(value, dict) and _PDN_PAYLOAD_KEY in value:
            payload = value[_PDN_PAYLOAD_KEY]
            if not isinstance(payload, str):
                raise Refusal('LL_PDN_CFG_UNREADABLE',
                              'structured payload value is not a string')
            records.append(payload)
    if len(records) != 1 or not records[0]:
        raise Refusal('LL_PDN_CFG_UNREADABLE',
                      'missing or ambiguous structured PDN Tcl payload')
    return records[0]


def internal_supply_grid_sources(record: dict) -> list[list[str]]:
    """Actual scheduled resistor-fed core grids, with their external bond."""
    if record.get('verdict') != 'WROTE':
        return []
    plan = record.get('power_pad_plan') or {}
    rows = []
    for instance, pad in (record.get('pad_instances') or {}).items():
        kind = pad.get('kind')
        grid = plan.get('power_net' if kind == 'power' else 'ground_net')
        bond, fed = pad.get('terminal'), (pad.get('derivation') or {}).get('fed_rail')
        connections = pad.get('supply_connections') or {}
        if (kind in ('power', 'ground') and pad.get('is_supply_pad')
                and instance in (plan.get('instances') or [])
                and pad.get('grid_net') == grid and grid and bond and fed and bond != fed
                and connections.get(fed) == grid
                and connections.get(bond) == pad.get('port') != grid
                and any(p.get('kind') == kind and p.get('master') == pad.get('master')
                        and p.get('terminal') == bond for p in plan.get('core_supply_pads', []))):
            rows.append([str(instance), str(pad['master']), str(fed), str(bond),
                         str(pad['port']), str(grid)])
    return sorted(rows)


def internal_supply_grid_check_tcl(rows: list[list[str]]) -> str:
    """Use native internal-net connectivity checking after proving its source.

    A resistor separates a chip bond from the core grid: a BTerm on that grid
    would bypass the resistor. Check the actual ODB source connection first,
    then keep native checking of every grid shape and instance connection.
    """
    def word(value: str) -> str:
        return '"' + ''.join('\\' + c if c in '\\"$[]' else c for c in value) + '"'
    sources = ' '.join('[list ' + ' '.join(map(word, row)) + ']' for row in rows)
    nets = ' '.join(word(net) for net in sorted({row[-1] for row in rows}))
    return f'''
# Internal supply grids proved by the chip-top producer's PDK resistor model.
set block [ord::get_db_block]
foreach source [list {sources}] {{
    lassign $source instance master fed bond port grid
    set inst [$block findInst $instance]
    set external [$block findBTerm $port]
    if {{$inst eq "NULL" || $external eq "NULL"}} {{
        error "Internal supply source is absent: $instance / $port"
    }}
    set inner [$inst findITerm $fed]
    set outer [$inst findITerm $bond]
    if {{$inner eq "NULL" || $outer eq "NULL"}} {{
        error "Internal supply source pins are absent: $instance"
    }}
    set core_net [$inner getNet]
    set bond_net [$outer getNet]
    if {{$core_net eq "NULL" || $bond_net eq "NULL" ||
        $core_net eq $bond_net || [$external getNet] ne $bond_net ||
        [[$inst getMaster] getName] ne $master || [$core_net getName] ne $grid ||
        [llength [$core_net getBTerms]] != 0}} {{
        error "Internal supply source does not match the producer: $instance"
    }}
}}
set ::vibeic_internal_supply_grids [list {nets}]
rename check_power_grid ::vibeic_native_check_power_grid
proc check_power_grid {{args}} {{
    set index [lsearch -exact $args -net]
    set net [lindex $args [expr {{$index + 1}}]]
    if {{[lsearch -exact $::vibeic_internal_supply_grids $net] >= 0}} {{
        lappend args -dont_require_terminals
    }}
    return [::vibeic_native_check_power_grid {{*}}$args]
}}
'''


def emit_pdn_cfg(image: str, pdk: str, output: Path, *, docker: str = 'docker',
                 native_connects: list[list[str]] | None = None,
                 internal_supply_sources: list[list[str]] | None = None) -> Path | None:
    """The image's own PDN script plus the PDK registry's pad-facing connects.

    LibreLane has no variable for an extra ``add_pdn_connect``; its default
    ``pdn_cfg.tcl`` builds the core ring but never joins it to the pads'
    core-facing supply pins.  On the spm chip path that left all 3,391,999
    grid shapes floating (``design__power_grid_violation__count``).  The
    registry's ``pdn_ring.connects`` is the declaration the direct deck's own
    ring uses; nothing else is added.  None when nothing is declared.
    """
    registry = Path(__file__).resolve().parent / 'pdk_registry.json'
    entries = _load(registry).get('pdks', []) if registry.is_file() else []
    if isinstance(entries, dict):
        entries = [dict(v, name=k) for k, v in entries.items() if isinstance(v, dict)]
    ring = next((e.get('pdn_ring') for e in entries
                 if isinstance(e, dict) and e.get('name') == pdk), None) or {}
    connects = [pair for pair in ring.get('connects') or []
                if isinstance(pair, list) and len(pair) == 2]
    if native_connects:
        connects = sorted({tuple(pair) for pair in connects + native_connects})
    if not ((ring.get('connect_to_pad_layers') and connects) or native_connects
            or internal_supply_sources):
        return None
    script = ('import json,os,librelane;print(json.dumps({' + repr(_PDN_PAYLOAD_KEY) +
              ':open(os.path.join(os.path.dirname(librelane.__file__),'
              '"scripts","openroad","common","pdn_cfg.tcl")).read()}))')
    provider = _provider_for_image(image)
    network = provider.network_mode if provider is not None else 'none'
    result = run_container([docker, 'run', *_dmem.docker_memory_flags(), '--rm', '--network',
                            network, '--entrypoint', 'python3', image, '-c', script],
                           probe_deadline_s=PROBE_DEADLINE_S)
    if result.returncode:
        raise Refusal('LL_PDN_CFG_UNREADABLE', (result.stderr or '')[-500:])
    native = _extract_pdn_payload(result.stdout)
    if 'add_pdn_connect' not in native:
        raise Refusal('LL_PDN_CFG_UNREADABLE',
                      'structured PDN Tcl payload lacks add_pdn_connect')
    # Keep the native payload byte-for-byte.  Add only the one separator needed
    # before the source-owned registry additions; never strip Tcl text that may
    # legitimately contain an ``[INFO]`` fragment or trailing newlines.
    separator = '' if native.endswith('\n\n') else ('\n' if native.endswith('\n') else '\n\n')
    basis = ('IO producer core-facing LEF pins + resolved native PDN ring'
             if native_connects else f'pdk_registry.json pdks[name={pdk}].pdn_ring.connects')
    suffix = [f'# vibe-ic: {basis}',
              *[f'add_pdn_connect -grid stdcell_grid -layers {{{a} {b}}}' for a, b in connects]]
    output.parent.mkdir(parents=True, exist_ok=True)
    checking = internal_supply_grid_check_tcl(internal_supply_sources) if internal_supply_sources else ''
    output.write_text(native + separator + '\n'.join(suffix) + '\n' + checking)
    return output


def flow_segment(image: str, first: str, last: str, *, flow: str = 'Chip',
                 docker: str = 'docker') -> list[str]:
    """The step ids ``first..last`` exactly as the image's own flow orders them."""
    script = ('import json,sys;from librelane.flows import Flow;'
              'f=Flow.factory.get(sys.argv[1]);'
              'print(json.dumps([s.id for s in f.Steps]))')
    provider = _provider_for_image(image)
    network = provider.network_mode if provider is not None else 'none'
    result = run_container([docker, 'run', *_dmem.docker_memory_flags(), '--rm', '--network',
                            network, '--entrypoint', 'python3', image, '-c', script, flow],
                           probe_deadline_s=PROBE_DEADLINE_S)
    try:
        order = json.loads(result.stdout.strip().splitlines()[-1])
    except (IndexError, ValueError):
        order = None
    if result.returncode or not isinstance(order, list):
        raise Refusal('LL_FLOW_UNRESOLVED', f'{flow}: {(result.stderr or "")[-500:]}')
    if first not in order or last not in order or order.index(first) > order.index(last):
        raise Refusal('LL_FLOW_SEGMENT_INVALID', f'{flow}: {first}..{last}')
    return order[order.index(first):order.index(last) + 1]


def resolve_step_config(project: Path, image: str, source: Path, output: Path,
                        *, mounts: list[tuple[Path, str]] | None = None,
                        pdk_root: str | None = None, docker: str = 'docker') -> Path:
    """Ask LibreLane to apply its PDK config before the step-only CLI runs."""
    mismatch = _provider_route_mismatch(image, project)
    if mismatch is not None:
        raise mismatch
    source = _local_config_source(
        source, mounts or [],
        local=_provider_for_image(image) is not None or _provider_route(project))
    script = (
        'import json,os,tempfile;'
        'from librelane.config import Config;'
        'from librelane.steps import Step;'
        f'p={str(source)!r}; out={str(output)!r}; root={pdk_root!r};'
        '_,cls=Step.factory.from_step_config(p);'
        f'cfg,_=Config.load(p,cls.get_all_config_variables(),design_dir={str(project)!r},pdk_root=root);'
        'fd,tmp=tempfile.mkstemp(dir=os.path.dirname(out));'
        'os.fchmod(fd,0o644);'
        'os.write(fd,cfg.dumps().encode());os.close(fd);os.replace(tmp,out)'
    )
    volumes = ['-v', f'{project.resolve()}:{project.resolve()}']
    for host, guest in mounts or []:
        volumes += ['-v', f'{host.resolve()}:{guest}:ro']
    # The native resolver reports a missing source itself. Some callers also
    # probe the exact argv with a stand-in runner before creating that file;
    # in either case there is no step-specific plugin to mount yet.
    step_id = _load(source).get('meta', {}).get('step', '') if source.is_file() else ''
    result = run_container([docker, 'run', *_dmem.docker_memory_flags(), '--rm', *volumes,
                            *_plugin_args([step_id]),
                            '--entrypoint', 'python3', image, '-c', script],
                           probe_deadline_s=PROBE_DEADLINE_S)
    if result.returncode or not output.is_file():
        raise Refusal('LL_CONFIG_RESOLVE_FAILED',
                      (result.stderr or result.stdout)[-1000:])
    return output


def run_chain(project: Path, image: str, steps: list[tuple[str, Path, Path]],
              *, docker: str = 'docker', mounts: list[tuple[Path, str]] | None = None,
              lane: str | None = None, pdk_root: str | None = None,
              namespace: str | None = None,
              openroad_init: list[str] | None = None) -> list[Path]:
    """Run configured native LibreLane steps, carrying each output State forward."""
    if lane is not None and (not lane or '/' in lane or lane in ('.', '..')):
        raise Refusal('LL_INVALID_LANE', str(lane))
    if namespace and (Path(namespace).is_absolute() or
                      any(part in ('..', '.') for part in Path(namespace).parts)):
        raise Refusal('LL_INVALID_NAMESPACE', namespace)
    if lane and namespace:
        raise Refusal('LL_LANE_NAMESPACE_CONFLICT', f'{lane}: {namespace}')
    base = project / 'phase3/librelane'
    if lane:
        base /= lane
    if namespace:
        base /= namespace
    capability = image_capability(image, docker)
    home = openroad_home(base / '.openroad_home', capability, openroad_init)
    if pdk_root and (_provider_for_image(image) is not None or _provider_route(project)):
        pdk_root = _ce.localise_mounted_paths(str(pdk_root),
            [(guest, str(host.resolve())) for host, guest in mounts or []])
    outputs = []
    previous: Path | None = None
    for index, (step_id, config, initial_state) in enumerate(steps, 1):
        folder = base / f'{index:02d}-{step_id.lower().replace(".", "-")}'
        state_path = previous or initial_state
        if folder.exists():
            archive = base / 'attempts'
            archive.mkdir(parents=True, exist_ok=True)
            number = 1
            while (archive / f'{folder.name}-{number:04d}').exists():
                number += 1
            shutil.move(str(folder), str(archive / f'{folder.name}-{number:04d}'))
        folder.mkdir(parents=True, exist_ok=True)
        volume_args = ['-v', f'{project.resolve()}:{project.resolve()}']
        for host, guest in mounts or []:
            volume_args += ['-v', f'{host.resolve()}:{guest}:ro']
        if home:
            volume_args += ['-e', f'HOME={home.resolve()}']
        volume_args += _plugin_args([step_id])
        cmd = [docker, 'run', *_dmem.docker_memory_flags(), '--rm', *volume_args,
               '--entrypoint', 'python3', image,
               '-m', 'librelane.steps', 'run', '--id', step_id, '-c', str(config),
               '-i', str(state_path), '-o', str(folder)]
        if pdk_root:
            cmd += ['--pdk-root', str(pdk_root)]
        completed = run_container(cmd, supervised=True, log=folder / 'invocation.log')
        (folder / 'invocation.log').write_text(completed.stdout + '\n' + completed.stderr)
        if completed.returncode or not (folder / 'state_out.json').exists():
            raise Refusal('LL_STEP_FAILED', f'{step_id}: rc={completed.returncode}; {folder / "invocation.log"}')
        previous = folder / 'state_out.json'
        outputs.append(folder)
    return outputs


#: STAPostPNR writes one `sta.log` per analysed corner. This line names each
#: cell library it read for that corner (LibreLane 3.1 `scripts/openroad/sta`).
_STA_CELL_LIBRARY_RE = re.compile(
    r"^Reading cell library for the '([^']+)' corner at '([^']+)'", re.M)


def _state_step_id(folder: Path) -> str | None:
    """The LibreLane step that wrote `folder`, from its own records."""
    config = folder / 'config.json'
    if config.is_file():
        return _load(config).get('meta', {}).get('step')
    return None


def post_pnr_timing_inputs(project: Path, state_path: Path, corner: str, *,
                           allowed_external: set[Path] | None = None) -> dict:
    """The routed netlist, SDC, SPEF and cell libraries `OpenROAD.STAPostPNR`
    timed `corner` with, as project-relative paths.

    Netlist, SDC and SPEF come from the step's `state_out.json`; the SPEF is
    the one whose corner pattern matches `corner` (the same `fnmatch` rule
    LibreLane applies). The cell libraries are the ones the step's own
    `<corner>/sta.log` says it read. A corner the step did not analyse, an
    ambiguous or absent SPEF, or a view outside the project is refused. A
    caller that independently reopened an immutable original owner may name
    its exact resolved files in ``allowed_external``; no directory-wide
    exception is inferred here.
    """
    folder = state_path.parent
    config_path = folder / 'config.json'
    for path in (config_path, state_path):
        if not path.resolve().is_relative_to(folder.resolve()):
            raise Refusal('LL_STATE_OUTSIDE_PROJECT', str(path))
    step = (_load(config_path).get('meta') or {}).get('step')
    if step != 'OpenROAD.STAPostPNR':
        raise Refusal('LL_NOT_STAPOSTPNR', f'{folder}: written by {step}')
    state = _load(state_path)
    log = folder / corner / 'sta.log'
    if not log.is_file():
        analysed = sorted(d.name for d in folder.iterdir()
                          if (d / 'sta.log').is_file())
        raise Refusal('LL_CORNER_NOT_ANALYSED', f'{corner}: {analysed}')
    if not log.resolve().is_relative_to(folder.resolve()):
        raise Refusal('LL_STATE_OUTSIDE_PROJECT', str(log))
    spefs = state.get('spef') or {}
    if isinstance(spefs, str):
        spefs = {'*': spefs}
    matched = [path for pattern, path in spefs.items()
               if fnmatch.fnmatch(corner, pattern)]
    if len(matched) != 1:
        raise Refusal('LL_SPEF_UNRESOLVED', f'{corner}: {len(matched)} matching SPEF')
    libraries = [path for name, path in
                 _STA_CELL_LIBRARY_RE.findall(log.read_text(errors='replace'))
                 if name == corner]
    if not libraries:
        raise Refusal('LL_CORNER_LIBRARY_UNREAD', str(log))
    root = project.resolve()
    allowed = {Path(path).resolve() for path in (allowed_external or set())}
    result: dict[str, Any] = {'step': step, 'corner': corner,
                              'liberties': libraries}
    for key, value in (('sta_netlist', state.get('nl')),
                       ('sdc', state.get('sdc')), ('spef', matched[0]),
                       ('state', str(state_path))):
        path = Path(value or '')
        if not value or not path.is_file():
            raise Refusal('LL_STATE_FILE_MISSING',
                          f'{key}: no file at path {value!r}')
        resolved = path.resolve()
        if not resolved.is_relative_to(root) and resolved not in allowed:
            raise Refusal('LL_STATE_OUTSIDE_PROJECT', f'{key}: {value}')
        result[key] = (str(resolved.relative_to(root))
                       if resolved.is_relative_to(root) else str(resolved))
    return result


def judge_step(folder: Path, required_metrics: list[str], output: Path,
               limits: dict[str, dict[str, float]] | None = None,
               required_reports: list[str] | None = None,
               scope: dict[str, str] | None = None) -> dict:
    state = _load(folder / 'state_out.json')
    metrics = dict(state.get('metrics', {}))
    if (folder / 'metrics.json').is_file():
        metrics.update(_load(folder / 'metrics.json'))
    rows = {key: {'status': 'MEASURED', 'value': metrics[key]} if key in metrics and metrics[key] is not None
            else {'status': 'NOT_MEASURED'} for key in required_metrics}
    verdict = 'PASS' if rows and all(x['status'] == 'MEASURED' for x in rows.values()) else 'NOT_MEASURED'
    for key, bounds in (limits or {}).items():
        if key not in rows or rows[key]['status'] != 'MEASURED':
            verdict = 'NOT_MEASURED'
            continue
        value = rows[key]['value']
        if not isinstance(value, (int, float)) or isinstance(value, bool):
            rows[key]['status'] = 'INVALID'
            verdict = 'FAIL'
            continue
        if any((bound == 'min' and value < threshold) or
               (bound == 'max' and value > threshold) or
               (bound == 'eq' and value != threshold)
               for bound, threshold in bounds.items()):
            rows[key]['status'] = 'FAIL'
            verdict = 'FAIL'
    result = {'verdict': verdict, 'metrics': rows, 'scope': scope or {},
              'source': str(folder / 'state_out.json')}
    reports = {}
    for name in required_reports or []:
        path = folder / name
        if path.is_file():
            reports[name] = {'status': 'PRESENT', 'path': str(path)}
        else:
            reports[name] = {'status': 'NOT_MEASURED'}
            if result['verdict'] != 'FAIL':
                result['verdict'] = 'NOT_MEASURED'
    result['reports'] = reports
    write_json(output, result)
    return result


def select_arms(arms: dict[str, Path], objectives: dict[str, str], output: Path) -> dict:
    """Measured, same-key Pareto selection; ties retain both arms for review."""
    from _ppa.pareto import dominates, Objective
    data = {name: _load(path) for name, path in arms.items()}
    eligible = {name: doc for name, doc in data.items()
                if doc.get('verdict') == 'PASS' and
                all(doc.get('metrics', {}).get(k, {}).get('status') == 'MEASURED' for k in objectives)}
    if len(eligible) != len(data):
        verdict = {'selection': 'UNDETERMINED', 'reason': 'LL_ARM_NOT_MEASURED', 'arms': list(arms)}
    elif len({json.dumps(doc.get('scope'), sort_keys=True) for doc in eligible.values()}) != 1 or \
            any(not isinstance(doc.get('scope'), dict) or not doc['scope'] for doc in eligible.values()):
        verdict = {'selection': 'UNDETERMINED', 'reason': 'LL_ARM_SCOPE_MISMATCH', 'arms': list(arms)}
    else:
        # Reuse the Pareto domination relation, with explicit senses and equal scope.
        names = list(eligible)
        axes = [Objective(k, k, sense, {'step': 'same'}) for k, sense in objectives.items()]
        values = {n: {'values': {k: {'value': eligible[n]['metrics'][k]['value']} for k in objectives}}
                  for n in names}
        frontier = [n for n in names if not any(dominates(values[m], values[n], axes)
                    for m in names if m != n)]
        verdict = {'selection': frontier[0] if len(frontier) == 1 else 'UNDETERMINED',
                   'frontier': frontier, 'arms': list(arms), 'reason': None if len(frontier) == 1 else 'LL_PARETO_TIE'}
    write_json(output, verdict)
    return verdict


def execute_dual(project: Path, step_id: str,
                 librelane_arm: Callable[[Path], Path],
                 openroad_arm: Callable[[Path], Path],
                 objectives: dict[str, str]) -> dict:
    """Invoke both producers in isolated directories and retain their evidence."""
    root = project / 'phase3/tool_arms' / step_id
    reports = {}
    for name, producer in (('librelane', librelane_arm), ('openroad', openroad_arm)):
        folder = root / name
        folder.mkdir(parents=True, exist_ok=True)
        report = producer(folder)
        if not report.resolve().is_relative_to(folder.resolve()) or not report.is_file():
            raise Refusal('LL_ARM_REPORT_MISSING', f'{name}: {report}')
        reports[name] = report
    return select_arms(reports, objectives, root / 'selection.json')


def main() -> int:
    parser = argparse.ArgumentParser()
    commands = parser.add_subparsers(dest='command', required=True)
    emit = commands.add_parser('emit-config')
    emit.add_argument('project', type=Path); emit.add_argument('pdk'); emit.add_argument('output', type=Path)
    args = parser.parse_args()
    try:
        if args.command == 'emit-config':
            emit_config(args.project, args.pdk, args.output)
        return 0
    except Refusal as error:
        print(error, file=sys.stderr)
        return 2


if __name__ == '__main__':
    sys.exit(main())
