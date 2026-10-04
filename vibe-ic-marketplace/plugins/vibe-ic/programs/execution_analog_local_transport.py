"""Passive analog producer transport through the existing ephemeral supervisor.

No policy bootstrap, capability, Controller, receipt issuer or docker-exec.
"""
# --- sibling-import path (vibe-ic#2104) ------------------------------------
# `programs/` is a flat directory whose modules import each other by BARE
# name. Python puts a file's own directory on `sys.path` only when that file
# is run as `__main__`; under `importlib.util.spec_from_file_location` — how
# the gates, the wiring audit and much of the suite load a program — it does
# not, so every bare sibling import below raises ModuleNotFoundError. Restore
# the condition the file is written for. Idempotent, and the same shape the
# sibling programs that already carry it use.
import os as _os                                                    # noqa: E402
import sys as _sys                                                  # noqa: E402

if _os.path.dirname(_os.path.abspath(__file__)) not in _sys.path:
    _sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
# ---------------------------------------------------------------------------
from contextlib import contextmanager
import json
import os
from pathlib import Path
import threading
import time
import execution_modes as em


@contextmanager
def local_transport(receipts: Path, deadline: float, *, project: Path, parameters: dict):
    import _container_exec as ce
    import _docker_watchdog as watchdog
    import librelane_contract as lc
    original = {name: getattr(ce, name) for name in (
        'docker_exec_argv', 'run_in_container', 'run_in_container_supervised')}
    original_watchdog = watchdog.run_docker_supervised
    original_native = lc.run_container
    receipts.parent.mkdir(parents=True, exist_ok=True)
    lock = threading.RLock()

    def argv(container, *rest, opts=()):
        if container not in ('', 'host') or opts:
            raise em.Refusal('ANALOG_EXISTING_CONTAINER_FORBIDDEN', str(container))
        return [parameters['docker'], 'run', '--rm', '--network', 'none',
                '--cpus', str(parameters['cpus']), '--memory', str(parameters['ram_mb']) + 'm',
                '--memory-swap', str(parameters['ram_mb']) + 'm',
                '--user', f'{os.getuid()}:{os.getgid()}',
                '-v', str(project) + ':' + str(project),
                parameters['image_ref'], '--skip', *rest]

    def observed(command, **kwargs):
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise em.Refusal('ANALOG_NATIVE_FINITE_DEADLINE', str(command))
        # run_chain also uses this same fixed supervisor. Clamp its bound and
        # Docker quotas; never carry the ordinary live FD or issuer locator.
        if command[0] != parameters['docker'] or 'run' not in command:
            raise em.Refusal('ANALOG_NATIVE_COMMAND_UNBOUND', str(command))
        at = command.index('run') + 1
        command = [*command[:at], '--cpus', str(parameters['cpus']),
                   '--memory', str(parameters['ram_mb']) + 'm',
                   '--memory-swap', str(parameters['ram_mb']) + 'm', *command[at:]]
        safe_env = {k: v for k, v in os.environ.items() if not k.startswith('VIBEIC_EXECUTION')}
        started = time.monotonic_ns()
        kwargs.pop('supervised', None); kwargs.pop('probe_deadline_s', None)
        kwargs['env'] = safe_env
        with lock:
            done = original_native(command, probe_deadline_s=remaining, **kwargs)
        with receipts.open('a') as stream:
            stream.write(json.dumps(dict(argv=command, observer_pid=os.getpid(), rc=done.returncode,
                stdout=done.stdout, stderr=done.stderr, started_ns=started,
                ended_ns=time.monotonic_ns())) + '\n')
        return done

    def run(container, command, *args, **kwargs):
        return observed(argv(container, 'bash', '-lc', command))

    def supervised(container, command, marker, **kwargs):
        done = run(container, command)
        return done.returncode, done.stdout, done.stderr

    ce.docker_exec_argv = argv
    ce.run_in_container = ce.run_in_container_supervised = run
    watchdog.run_docker_supervised = supervised
    lc.run_container = observed
    try:
        yield
    finally:
        for name, value in original.items():
            setattr(ce, name, value)
        watchdog.run_docker_supervised = original_watchdog
        lc.run_container = original_native
