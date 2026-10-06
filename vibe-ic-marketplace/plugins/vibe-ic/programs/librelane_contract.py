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
import signal
import socket
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


LOCAL_ATTESTATION_ENV = 'VIBEIC_LIBRELANE_LOCAL_ATTESTATION'
LOCAL_PROVIDER_ROUTE_ENV = 'VIBEIC_LIBRELANE_ROUTE'
LOCAL_PROVIDER_IDENTITY_PREFIX = 'local://librelane@sha256:'


class LocalProviderIdentity(str):
    """String-compatible identity for a host-owned LibreLane provider."""

    def __new__(cls, reference: str, *, librelane_root: str | None,
                pdk_root: str, pdk: str | None, source_sha256: str,
                pdk_root_sha256: str | None, executable: str,
                executable_sha256: str, source_kind: str,
                network_mode: str, network_namespace: str,
                network_helper: str | None, network_helper_sha256: str | None):
        value = str.__new__(cls, reference)
        value.route = 'LOCAL'
        value.provider = 'host-owned-librelane'
        value.librelane_root = librelane_root
        value.pdk_root = pdk_root
        value.pdk = pdk
        value.source_sha256 = source_sha256
        value.pdk_root_sha256 = pdk_root_sha256
        value.executable = executable
        value.executable_sha256 = executable_sha256
        value.source_kind = source_kind
        value.network_mode = network_mode
        value.network_namespace = network_namespace
        value.network_helper = network_helper
        value.network_helper_sha256 = network_helper_sha256
        return value

    def as_record(self) -> dict[str, Any]:
        return {'route': self.route, 'provider': self.provider,
                'reference': str(self), 'librelane_root': self.librelane_root,
                'pdk_root': self.pdk_root, 'pdk': self.pdk,
                'source_sha256': self.source_sha256,
                'pdk_root_sha256': self.pdk_root_sha256,
                'executable': self.executable,
                'executable_sha256': self.executable_sha256,
                'source_kind': self.source_kind,
                'network_mode': self.network_mode,
                'network_namespace': self.network_namespace,
                'network_helper': self.network_helper,
                'network_helper_sha256': self.network_helper_sha256}


_LOCAL_PROVIDER_IDENTITIES: dict[str, LocalProviderIdentity] = {}


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


def _local_tree_sha256(root: Path | None) -> str | None:
    if root is None:
        return None
    try:
        if root.is_symlink() or not root.exists():
            return None
        if root.is_file():
            return hashlib.sha256(root.read_bytes()).hexdigest()
        result = hashlib.sha256()
        for path in sorted(root.rglob('*')):
            if path.is_symlink():
                return None
            if path.is_dir() or '__pycache__' in path.parts or path.suffix in {'.pyc', '.pyo'}:
                continue
            if not path.is_file():
                return None
            relative = path.relative_to(root).as_posix().encode()
            result.update(len(relative).to_bytes(8, 'big'))
            result.update(relative)
            result.update(hashlib.sha256(path.read_bytes()).digest())
        return result.hexdigest()
    except OSError:
        return None


def _local_executable_identity(value: str | None = None) -> tuple[str, str]:
    candidate = value or os.environ.get('VIBEIC_LIBRELANE_EXECUTABLE') or sys.executable
    path = Path(candidate).expanduser()
    if not path.is_absolute():
        resolved = shutil.which(str(path))
        path = Path(resolved) if resolved else path
    try:
        path = path.resolve(strict=True)
        if not path.is_file() or not os.access(path, os.X_OK):
            raise OSError('not an executable file')
        return str(path), hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError as exc:
        raise Refusal('LL_LOCAL_EXECUTABLE_INVALID', f'{path}: {exc}') from None


def _local_network_namespace() -> str:
    try:
        return os.readlink('/proc/self/ns/net')
    except OSError as exc:
        raise Refusal('LL_LOCAL_NETWORK_UNATTESTED',
                      f'cannot identify host network namespace: {exc}') from None


def _local_network_helper_identity() -> tuple[str, str]:
    helper = shutil.which('bwrap')
    if not helper:
        raise Refusal('LL_LOCAL_NETWORK_UNATTESTED',
                      'bwrap is required to provide a LOCAL network namespace')
    try:
        path = Path(helper).resolve(strict=True)
        if not path.is_file() or not os.access(path, os.X_OK):
            raise OSError('not an executable file')
        return str(path), hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError as exc:
        raise Refusal('LL_LOCAL_NETWORK_UNATTESTED',
                      f'cannot bind bwrap identity: {exc}') from None


def local_provider_identity(project: Path | None = None,
                            pdk: str | None = None) -> LocalProviderIdentity | None:
    """Resolve an explicitly selected host-owned LibreLane/PDK provider."""
    # A generic no-container/native fallback is still the legacy attested-image
    # route.  Only an explicit LOCAL/HOST/NATIVE selection may promote the
    # caller into the typed host-provider identity contract.
    if not _explicit_local_route(project):
        return None
    root_value, source_value, selected = _provider_roots(project, pdk)
    if not root_value:
        if _explicit_local_route(project):
            raise Refusal('LL_LOCAL_PROVIDER_UNDECLARED',
                          'LOCAL requires pdk_root_host or VIBEIC_LIBRELANE_PDK_ROOT')
        return None
    if not source_value:
        raise Refusal('LL_LOCAL_SOURCE_UNDECLARED',
                      'LOCAL requires librelane_root_host or VIBEIC_LIBRELANE_ROOT')
    if selected and not _PDK_NAME.fullmatch(selected):
        raise Refusal('LL_PDK_NAME_INVALID', repr(selected))
    root = Path(root_value).expanduser()
    if not root.is_absolute() or root.is_symlink() or not root.is_dir():
        raise Refusal('LL_LOCAL_PDK_ROOT_INVALID', str(root))
    source = Path(source_value).expanduser() if source_value else None
    if source is not None and (not source.is_absolute() or source.is_symlink() or
                               not source.is_dir()):
        raise Refusal('LL_LOCAL_LIBRELANE_ROOT_INVALID', str(source))
    if source is not None:
        package_init = source / 'librelane' / '__init__.py'
        if package_init.is_symlink() or not package_init.is_file():
            raise Refusal('LL_LOCAL_SOURCE_UNATTESTED',
                          f'LibreLane package is not bound under {source}')
    executable, executable_sha = _local_executable_identity(
        _provider_switch(project).get('librelane_executable'))
    source_sha = _local_tree_sha256(source) if source is not None else executable_sha
    if not source_sha:
        raise Refusal('LL_LOCAL_SOURCE_UNATTESTED',
                      f'cannot hash declared LibreLane source {source}')
    source_kind = 'source_tree' if source is not None else 'executable'
    switch = _provider_switch(project)
    network_mode = (switch.get('local_network_mode') or
                    os.environ.get('VIBEIC_LIBRELANE_LOCAL_NETWORK') or 'none')
    network_mode = str(network_mode).strip().lower()
    if network_mode not in {'none', 'host'}:
        raise Refusal('LL_LOCAL_NETWORK_UNATTESTED',
                      f'unsupported local network mode {network_mode!r}')
    network_namespace = _local_network_namespace()
    network_helper, network_helper_sha = (
        _local_network_helper_identity() if network_mode == 'none' else (None, None))
    root_sha = _local_tree_sha256(root)
    if not root_sha:
        raise Refusal('LL_LOCAL_PROVIDER_IDENTITY_UNBOUND',
                      f'cannot hash PDK root {root}')
    material = json.dumps({'route': 'LOCAL', 'provider': 'host-owned-librelane',
                           'librelane_root': str(source.resolve()) if source else None,
                           'pdk_root': str(root.resolve()), 'pdk': selected,
                           'source_sha256': source_sha, 'source_kind': source_kind,
                           'pdk_root_sha256': root_sha, 'executable': executable,
                           'executable_sha256': executable_sha,
                           'network_mode': network_mode,
                           'network_namespace': network_namespace,
                           'network_helper': network_helper,
                           'network_helper_sha256': network_helper_sha},
                          sort_keys=True, separators=(',', ':')).encode()
    reference = LOCAL_PROVIDER_IDENTITY_PREFIX + hashlib.sha256(material).hexdigest()
    identity = LocalProviderIdentity(
        reference, librelane_root=str(source.resolve()) if source else None,
        pdk_root=str(root.resolve()), pdk=selected, source_sha256=source_sha,
        pdk_root_sha256=root_sha, executable=executable,
        executable_sha256=executable_sha, source_kind=source_kind,
        network_mode=network_mode, network_namespace=network_namespace,
        network_helper=network_helper, network_helper_sha256=network_helper_sha)
    _LOCAL_PROVIDER_IDENTITIES[reference] = identity
    return identity


def _provider_for_image(image: Any) -> LocalProviderIdentity | None:
    if isinstance(image, LocalProviderIdentity):
        return image
    return _LOCAL_PROVIDER_IDENTITIES.get(str(image))


def _provider_route_mismatch(image: Any, project: Path | None = None) -> Refusal | None:
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
    return None


def _container_image_arg(argv: list[Any]) -> Any | None:
    """Return the image token after the Docker-run options, if unambiguous."""
    try:
        at = argv.index('run') + 1
    except ValueError:
        return None
    value_options = {'-v', '-e', '--entrypoint', '--memory', '--memory-swap',
                     '--network', '--workdir', '--cpus', '--shm-size'}
    while at < len(argv):
        token = argv[at]
        if not isinstance(token, str):
            return token
        if not token.startswith('-'):
            return token
        if token == '--rm':
            at += 1
        elif token in value_options:
            at += 2
        else:
            return None
    return None


def _local_reference_token(argv: list[Any]) -> str | None:
    """Find an exact typed LOCAL reference without scanning command text."""
    pattern = re.escape(LOCAL_PROVIDER_IDENTITY_PREFIX) + r'[0-9a-f]{64}'
    return next((part for part in argv
                 if isinstance(part, str) and re.fullmatch(pattern, part)), None)


def local_image_attestation(image: str | None = None) -> dict[str, Any]:
    """Read the host's live launch receipt, bound to THIS container and image.

    The host mounts its ordinary launch_identity.json read-only after inspecting
    the fresh CID. An image environment string alone is never execution proof.
    This is deliberately uncached: changed/absent authority refuses even on reuse.
    """
    path = Path(os.environ.get(LOCAL_ATTESTATION_ENV, ''))
    try:
        raw = path.read_bytes()
        def unique(pairs):
            out = {}
            for key, value in pairs:
                if key in out:
                    raise ValueError(f'duplicate key {key}')
                out[key] = value
            return out
        record = json.loads(raw, object_pairs_hook=unique)
        inspected = record['container_inspect']
        cid, reference = record['cid'], record['image']
        import _eda_pin
        wanted = image or os.environ.get('VIBEIC_EDA_IMAGE') or reference
        image_digest = _eda_pin.reference_digest(reference)
        host_images = record['image_inspect']
        host_image = next(item for item in host_images
                          if item['Id'] == inspected['Image'])
        manifest = inspected.get('ImageManifestDescriptor', {}).get('digest')
        host_config = inspected.get('HostConfig', {})
        if not isinstance(host_config, dict):
            raise ValueError('HostConfig is not an inspection object')
        repo_digests = host_image.get('RepoDigests', [])
        if (not isinstance(repo_digests, list)
                or not all(isinstance(ref, str) for ref in repo_digests)):
            raise ValueError('host image RepoDigests is not a string list')
        held = [_eda_pin.reference_digest(ref) for ref in repo_digests]
        if (not re.fullmatch(r'[0-9a-f]{64}', cid)
                or inspected['Id'] != cid
                or inspected['Config']['Hostname'] != socket.gethostname()
                or not socket.gethostname().startswith(cid[:12])
                or inspected['State']['Running'] is not True
                or inspected['State'].get('Paused') or inspected['State'].get('Dead')
                or not image_digest or '@sha256:' not in reference
                or _eda_pin.reference_digest(wanted) != image_digest
                or _eda_pin.reference_digest(inspected['Config']['Image']) != image_digest
                or not (manifest == image_digest or image_digest in held)):
            raise ValueError('host CID/image inspection does not bind this LOCAL process')
    except (OSError, ValueError, TypeError, KeyError, AttributeError, StopIteration) as exc:
        raise Refusal('LL_LOCAL_IMAGE_UNATTESTED', f'{path}: {exc}') from None
    return {'image': reference, 'image_id': inspected['Image'],
            'repo_digests': list(repo_digests), 'cid': cid,
            'network_mode': host_config.get('NetworkMode'),
            'memory': host_config.get('Memory'),
            'memory_swap': host_config.get('MemorySwap'),
            'auto_remove': host_config.get('AutoRemove'),
            'attestation_path': str(path.resolve()),
            'attestation_sha256': hashlib.sha256(raw).hexdigest()}


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
               provider: LocalProviderIdentity | None = None,
               **kw: Any) -> subprocess.CompletedProcess:
    """Execute only the Docker-run shapes emitted by this LibreLane owner.

    Reuse the existing mount-path conversion and host process supervision.
    The enclosing fresh image supplies the environment and cgroup memory bound.
    Unknown launch options refuse rather than silently discarding their meaning.
    """
    mounts, variables, entrypoint, container_workdir = [], {}, None, None
    network, memory, memory_swap, auto_remove = None, None, None, False
    at = argv.index('run') + 1
    while at < len(argv) and argv[at].startswith('-'):
        option = argv[at]
        if option == '--rm':
            auto_remove = True
            at += 1
            continue
        if option not in ('-v', '-e', '--entrypoint', '--memory', '--memory-swap', '--network', '--workdir'):
            raise Refusal('LL_LOCAL_LAUNCH_UNSUPPORTED', option)
        if option == '--workdir' and at + 1 >= len(argv):
            raise Refusal('LL_LOCAL_WORKDIR_INVALID', '--workdir requires a path')
        value = argv[at + 1]
        if option == '-v':
            host, guest, *mode = value.split(':')
            if mode not in ([], ['ro']) or not Path(host).exists():
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
    attestation = None if provider is not None else local_image_attestation(image)
    if provider is not None:
        if _local_network_namespace() != provider.network_namespace:
            raise Refusal('LL_LOCAL_NETWORK_UNATTESTED',
                          'the host network namespace changed since provider admission')
        if (provider.librelane_root and
                _local_tree_sha256(Path(provider.librelane_root)) != provider.source_sha256):
            raise Refusal('LL_LOCAL_SOURCE_CHANGED', provider.librelane_root)
        if _local_tree_sha256(Path(provider.pdk_root)) != provider.pdk_root_sha256:
            raise Refusal('LL_LOCAL_PDK_CHANGED', provider.pdk_root)
        if network is None:
            network = provider.network_mode
        if network != provider.network_mode:
            raise Refusal('LL_LOCAL_NETWORK_UNATTESTED',
                          f'requested {network!r}; provider binds {provider.network_mode!r}')
        if provider.network_mode == 'none':
            if (not provider.network_helper or
                    _local_executable_identity(provider.network_helper)[1] !=
                    provider.network_helper_sha256):
                raise Refusal('LL_LOCAL_NETWORK_UNATTESTED',
                              'the bound LOCAL network helper changed or disappeared')
        if memory is None or memory <= 0:
            raise Refusal('LL_LOCAL_MEMORY_UNATTESTED',
                          'LOCAL execution requires a finite --memory bound')
        if memory_swap is None or memory_swap != memory:
            raise Refusal('LL_LOCAL_SWAP_UNATTESTED',
                          'LOCAL execution requires --memory-swap equal to --memory')
        if not auto_remove:
            raise Refusal('LL_LOCAL_AUTOREMOVE_UNATTESTED',
                          'LOCAL execution requires Docker-equivalent --rm process lifetime')
    if attestation is not None and network is not None and attestation['network_mode'] != network:
        raise Refusal('LL_LOCAL_NETWORK_UNATTESTED',
                      f"requested --network {network}; current CID {attestation['cid']} "
                      f"has NetworkMode={attestation['network_mode']!r}")
    for requested, key, code in ((memory, 'memory', 'LL_LOCAL_MEMORY_UNATTESTED'),
                                (memory_swap, 'memory_swap', 'LL_LOCAL_SWAP_UNATTESTED')):
        if attestation is None:
            continue
        if requested is None:
            continue
        actual = attestation[key] if attestation is not None else None
        # Zero memory is unlimited; zero swap is an unspecified Docker default.
        unbounded_request = requested == 0 if key == 'memory' else requested == -1
        valid = type(actual) is int and (actual >= 0 if key == 'memory' else actual == -1 or actual > 0)
        if (not valid or (key == 'memory' and requested < 0)
                or (not unbounded_request and not (0 < actual <= requested))):
            raise Refusal(code, f"current CID {attestation['cid']} has {key}={actual!r}; "
                          f'requested {requested} bytes; a finite outer limit may be stricter')
    if attestation is not None and auto_remove and attestation['auto_remove'] is not True:
        raise Refusal('LL_LOCAL_AUTOREMOVE_UNATTESTED',
                      f"requested --rm; current CID {attestation['cid']} "
                      f"has AutoRemove={attestation['auto_remove']!r}")
    command = argv[at + 1:]
    if entrypoint:
        command = [entrypoint, *command]
    elif command[:1] == ['--skip']:
        command = command[1:]
    else:
        raise Refusal('LL_LOCAL_LAUNCH_UNSUPPORTED', 'missing explicit --skip command')
    command = [_ce.localise_mounted_paths(part, mounts) for part in command]
    if provider is not None:
        executable = shutil.which(command[0]) if command else None
        if not executable:
            raise Refusal('LL_LOCAL_EXECUTABLE_INVALID', command[0] if command else '<empty>')
        executable = str(Path(executable).resolve())
        if (executable != provider.executable or
                hashlib.sha256(Path(executable).read_bytes()).hexdigest() !=
                provider.executable_sha256):
            raise Refusal('LL_LOCAL_EXECUTABLE_MISMATCH',
                          f'{executable} is not the bound {provider.executable}')
        if provider.network_mode == 'none':
            command = [provider.network_helper, '--bind', '/', '/', '--unshare-net', '--', *command]
    environment = dict(kw.pop('env', None) or os.environ)
    environment.update({key: _ce.localise_mounted_paths(value, mounts)
                        for key, value in variables.items()})
    if provider is not None and provider.librelane_root:
        environment['PYTHONPATH'] = os.pathsep.join(
            [provider.librelane_root, environment.get('PYTHONPATH', '')]).rstrip(os.pathsep)
    if provider is not None:
        # Apply the native address-space ceiling in a separate launcher.  A
        # preexec_fn in a supervised/threaded parent can deadlock after fork;
        # this launcher sets the limit and immediately execs the bound command.
        launcher = (
            'import os,resource,sys; '
            'limit=int(sys.argv[1]); '
            'resource.setrlimit(resource.RLIMIT_AS,(limit,limit)); '
            'os.execvpe(sys.argv[2],sys.argv[2:],os.environ)')
        command = [provider.executable, '-c', launcher, str(memory), *command]
        environment['VIBEIC_LOCAL_MEMORY_LIMIT_BYTES'] = str(memory)
        environment['VIBEIC_LOCAL_NETWORK_MODE'] = provider.network_mode
    _ce.local_exec_mode('librelane_contract')
    with _ce.local_engine_cwd() as scratch:
        if child_cwd is None:
            kw.setdefault('cwd', scratch)
        if probe_deadline_s is not None:
            # A probe timeout kills the native group, including descendants.
            # A tool's natural rc=124 remains an ordinary tool failure.
            with subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                  text=True, start_new_session=True, env=environment, **kw) as child:
                try:
                    out, err = child.communicate(timeout=probe_deadline_s)
                except subprocess.TimeoutExpired:
                    os.killpg(child.pid, signal.SIGKILL)
                    out, err = child.communicate()
                    raise Refusal('LL_TOOL_DEADLINE', f'LOCAL probe passed {probe_deadline_s:g} s; '
                                  f'{_salvage(out, err, log)}') from None
                result = subprocess.CompletedProcess(command, child.returncode, out, err)
        else:
            import _watchdog as _wd
            grace = TOOL_STALL_GRACE_S if TOOL_STALL_GRACE_S is not None else _wd.DEFAULT_STALL_GRACE_S
            result = _wd.run_host_supervised(command, env=environment,
                stall_grace_s=grace, hard_ceiling_s=TOOL_BUDGET_S,
                ceiling_notice=_ce.default_ceiling_notice('LOCAL LibreLane', TOOL_BUDGET_S), **kw)
            if result.outcome == 'stalled':
                raise Refusal('LL_TOOL_STALLED', f'LOCAL tool made no progress for {grace:g} s; '
                              f'{_salvage(result.out, result.err, log)}')
            result = _wd.completed_process(command, result)
    if provider is not None:
        changed = []
        if (provider.librelane_root and
                _local_tree_sha256(Path(provider.librelane_root)) != provider.source_sha256):
            changed.append(f'LL_LOCAL_SOURCE_CHANGED: {provider.librelane_root}')
        if _local_tree_sha256(Path(provider.pdk_root)) != provider.pdk_root_sha256:
            changed.append(f'LL_LOCAL_PDK_CHANGED: {provider.pdk_root}')
        if changed:
            detail = '; '.join(changed)
            if result.returncode:
                result.stderr = (result.stderr or '') + f'\n{detail}\n'
            else:
                raise Refusal('LL_LOCAL_SOURCE_CHANGED', detail)
    if attestation is not None and local_image_attestation(image) != attestation:
        raise Refusal('LL_LOCAL_ATTESTATION_CHANGED', attestation['attestation_path'])
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
    write_json(native.with_suffix('.provenance.json'), {
        'source': str(source), 'source_sha256': digest(source),
        'native_sha256': digest(native), 'mounts': mapping, 'execution_route': 'LOCAL'})
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
#: * a PROBE (an image probe, a config resolution, a script or flow read) is
#:   seconds of work. It keeps a short hard client deadline, `PROBE_DEADLINE_S`
#:   (llv1 W16a), and its container is removed by name when that passes;
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
#: The refusals caused by TIME, not by the design or by a tool verdict: a probe
#: past its deadline, a tool the watchdog reaped as stalled. Only a plain FAIL
#: is red, so a consumer books these NOT_MEASURED with the refusal as reason.
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


def run_container(argv: list[str], *, probe_deadline_s: float | None = None,
                  supervised: bool = False, log: Path | None = None,
                  **kw: Any) -> subprocess.CompletedProcess:
    """Run one `docker run` argv, named so it can be removed by that name.

    Exactly one bound, stated by the caller:
      * ``probe_deadline_s=`` -- a probe: `subprocess.run(..., timeout=)`; past
        the deadline the container is removed by name and `LL_TOOL_DEADLINE` is
        raised;
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
    if image_arg is None and (_explicit_local_route(None) or
                              _local_reference_token(argv) is not None):
        raise Refusal('LL_LOCAL_IMAGE_UNRESOLVABLE',
                      'LOCAL route cannot identify an unambiguous image token')
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
    # Use the image's normal environment, with its explicit skip front door.
    # Overriding ENTRYPOINT bypassed that environment for resolved tool steps.
    argv = list(argv)
    if '--entrypoint' in argv:
        index = argv.index('--entrypoint')
        entrypoint = argv[index + 1]
        image_index = next((i for i in range(index + 2, len(argv))
                            if '@sha256:' in argv[i]), None)
        if image_index is not None:
            image = argv[image_index]
            argv = [*argv[:index], *argv[index + 2:image_index], image,
                    '--skip', entrypoint, *argv[image_index + 1:]]
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
    """Return the run's settled die/core, bound to its Floorplan step.

    The tape-out declaration is the owner input and remains authoritative when
    it answers ``core_area_um``.  This helper is only the derived fallback for
    consumers whose owner answer is ``NOT_DETERMINED``.  It deliberately binds
    the runner record to the resolved LibreLane config and the actual
    ``OpenROAD.Floorplan`` receipt; a rectangle copied from a stale report or
    guessed from DIE_AREA alone is refused.
    """
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
    receipt_path = step / 'vibeic_receipt.json'
    state_path = step / 'state_out.json'
    resolved_config_path = step / 'config.json'
    try:
        receipt = _load(receipt_path)
        state = _load(state_path)
        resolved = _load(resolved_config_path)
    except (OSError, ValueError, Refusal) as exc:
        raise Refusal('LL_FLOORPLAN_CORE_PROVENANCE',
                      f'{step}: incomplete Floorplan receipt: '
                      f'{type(exc).__name__}: {exc}') from exc
    if (receipt.get('input', {}).get('step') != 'OpenROAD.Floorplan' or
            not isinstance(receipt.get('sha256'), dict)):
        raise Refusal('LL_FLOORPLAN_CORE_PROVENANCE',
                      f'{receipt_path}: not an OpenROAD.Floorplan receipt')
    if resolved.get('DIE_AREA') != [int(v) if v.is_integer() else v for v in die] or \
            resolved.get('CORE_AREA') != [int(v) if v.is_integer() else v for v in core]:
        raise Refusal('LL_FLOORPLAN_CORE_PROVENANCE',
                      f'{resolved_config_path}: resolved geometry is stale')
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
    for path in (resolved_config_path, state_path, def_path):
        name = path.name
        want = receipt['sha256'].get(name)
        if not path.is_file() or not isinstance(want, str) or digest(path) != want:
            raise Refusal('LL_FLOORPLAN_CORE_PROVENANCE',
                          f'{receipt_path}: {name} is missing or changed')
    if _def_design_name(def_path) != design_name:
        raise Refusal('LL_FLOORPLAN_CORE_PROVENANCE',
                      f'{def_path}: DESIGN does not match resolved DESIGN_NAME '
                      f'{design_name!r}')
    def_die = DD.def_diearea_um(def_path.read_text(errors='replace'))
    if def_die is None or _rect_differs(def_die, die):
        raise Refusal('LL_FLOORPLAN_CORE_PROVENANCE',
                      f'{def_path}: DIEAREA {def_die} differs from {die}')
    source = (f'{basis}; bound to {config_path.relative_to(project)} '
              f'(sha256:{digest(config_path)}) and '
              f'{receipt_path.relative_to(project)} '
              f'(DESIGN_NAME={design_name}, DEF={def_path.relative_to(project)}; '
              f'state/config/DEF digests verified)')
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
        names.extend(v for v in values if v not in names)
    return names


def emit_config(project: Path, pdk: str, output: Path) -> dict:
    """Emit only declared inputs; unavailable values stay absent, never guessed."""
    root = project / 'phase1/generated_docs'
    l8, l9, l19 = (_ldoc(root, name) for name in EMIT_CONFIG_LDOCS)
    # The pad producer (step 15.5ic) runs after synthesis and pre-layout STA;
    # before it has run the PAD_* keys are undeclared, so they stay absent.
    pad_path = project / 'phase3/stage3/pnr/pad_assignment.json'
    pads = _load(pad_path) if pad_path.is_file() else {}
    result: dict[str, Any] = {}
    sources: dict[str, str] = {}
    clocks = [c for c in l8.get('clock_domains', []) if c.get('role') == 'primary'
              and c.get('pdk_scoped_target') in (None, pdk)]
    if len(clocks) != 1:
        raise Refusal('LL_CLOCK_AMBIGUOUS', f'{len(clocks)} primary clocks for {pdk}')
    c = clocks[0]
    _set(result, sources, 'CLOCK_PERIOD', c.get('period_ns'), 'L8_TIMING_WAVEFORM.clock_domains[primary].period_ns')
    _set(result, sources, 'CLOCK_PORT', c.get('source_pin'), 'L8_TIMING_WAVEFORM.clock_domains[primary].source_pin')
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
    sdc = project / 'phase3/stage3/pnr/constraint.sdc'
    if sdc.is_file():
        for key in ('PNR_SDC_FILE', 'SIGNOFF_SDC_FILE'):
            _set(result, sources, key, 'dir::' + str(sdc.relative_to(project)),
                 'phase3/stage3/pnr/constraint.sdc (L9-derived producer artefact)')
    declared, declared_sources = declaration_config(project)
    for key, value in declared.items():
        _set(result, sources, key, value, declared_sources[key])
    declarations = l19.get('fields', {}).get('constraint_declarations', [])
    supported = {'MAX_FANOUT_CONSTRAINT', 'MAX_TRANSITION_CONSTRAINT',
                 'MAX_CAPACITANCE_CONSTRAINT', 'FP_CORE_UTIL', 'PL_TARGET_DENSITY',
                 'PDN_VOFFSET', 'PDN_HOFFSET', 'PDN_CORE_RING',
                 'PDN_CORE_RING_CONNECT_TO_PADS', 'PDN_SKIPTRIM', 'FP_PDN_SKIPTRIM',
                 'FP_PDN_VOFFSET', 'FP_PDN_HOFFSET'}
    chosen: dict[str, list[tuple[int, Any, str]]] = {}
    for row in declarations:
        key = row.get('token')
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
            parsed: Any = float(value.rstrip('%'))
            if parsed.is_integer():
                parsed = int(parsed)
        except ValueError:
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
        _set(result, sources, 'RSZ_DONT_TOUCH_LIST',
             aux_tie_dont_touch(_load(chip_top_record)) or None,
             'reports/phase3/io_pad_chip_top.json.aux_pin_signal_connections'
             '[].{tie_instance,net}')
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
    # Strap width/pitch: this design's own pre-route EM search (T103), measured
    # with PSM on its placed, clock-treed layout. Absent record -> absent keys.
    from _ppa.pdn_em_presweep import librelane_pdn_config
    pdn, pdn_source = librelane_pdn_config(project)
    for key, value in pdn.items():
        _set(result, sources, key, value, pdn_source)
    write_json(output, result)
    write_json(output.with_suffix('.provenance.json'), sources)
    return result


def emit_synthesis_config(project: Path, pdk: str, output: Path,
                          rtl_files: list[Path], defines: list[str],
                          use_slang: bool,
                          std_cell_library: str | None = None,
                          synth_liberty: str | None = None,
                          top: str | None = None) -> dict:
    """Bind Yosys.Synthesis to the caller's selected design inputs."""
    import sparse_fsm_detect
    import catalog_synth_safe_params_check

    if not rtl_files or any(not path.is_file() or not path.resolve().is_relative_to(project.resolve())
                            for path in rtl_files):
        raise Refusal('LL_SYNTH_INPUT_MISSING', 'selected RTL must exist inside the project')
    result = emit_config(project, pdk, output)
    sources = _load(output.with_suffix('.provenance.json'))
    _set(result, sources, 'PDK', pdk, 'resolved PDK supplied by phase3_one_shot_runner')
    if std_cell_library:
        _set(result, sources, 'STD_CELL_LIBRARY', std_cell_library,
             'resolved synthesis liberty library supplied by phase3_one_shot_runner')
    if synth_liberty:
        _set(result, sources, 'LIB', {'*': [synth_liberty]},
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
    write_json(output, result)
    write_json(output.with_suffix('.provenance.json'), sources)
    return result


def phase2_pdk(project: Path) -> tuple[str, str]:
    """Read the existing Phase-2 PDK declaration, refusing ambiguous evidence.

    The shared declaration accessor selects the source. This stricter tool
    input boundary checks its providers for malformed or conflicting values;
    a prose target is not an executable PDK distribution name.
    """
    import declared_pdk_is_the_pdk_used_check as declared

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
                    values.add(value.strip())
        except (OSError, ValueError) as exc:
            raise Refusal('LL_PHASE2_PDK_INVALID', f'{path.relative_to(project)}: {exc}') from exc
    pdk, source = declared.declared_target(project)
    if not pdk or not source or not values:
        raise Refusal('LL_PHASE2_PDK_UNDECLARED', 'declare PDK in Phase-2 L19 or input/project.json')
    if values != {pdk}:
        raise Refusal('LL_PHASE2_PDK_CONFLICT', 'Phase-2 PDK declarations disagree')
    switch = project / 'phase3/librelane_switch.json'
    if switch.is_file():
        selected = _load(switch).get('pdk')
        if selected is not None and selected != pdk:
            raise Refusal('LL_PHASE2_PDK_CONFLICT', 'switch.pdk disagrees with Phase-2 declaration')
    return pdk, source


def emit_lint_config(project: Path, pdk: str, output: Path, top: str,
                     rtl_files: list[Path], top_source: str,
                     pdk_source: str = 'phase3/librelane_switch.json.pdk') -> dict:
    """Bind Verilator.Lint to the design's own RTL and declared top.

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
    write_json(output, result)
    write_json(output.with_suffix('.provenance.json'), sources)
    return result


def verify_synthesis_stat(stat_path: Path, state: dict, stats_path: Path,
                          top: str, output: Path) -> dict:
    """Bind the area-gate input and copied netlist to Yosys's native stat."""
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
    native_hash = digest(native_netlist)
    if stats.get('netlist_sha256') != 'sha256:' + native_hash:
        raise Refusal('LL_STAT_NETLIST_MISMATCH', str(native_netlist))
    report = {'status': 'PASS', 'top': top, 'cell_count': count,
              'area_um2': area, 'stat_sha256': digest(stat_path),
              'native_netlist_sha256': native_hash,
              'area_gate_input_sha256': digest(stats_path)}
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
    'OpenROAD.CheckSDCFiles': ('nl',), 'OpenROAD.STAPrePNR': ('nl',),
    'OpenROAD.Floorplan': ('nl',), 'Yosys.EQY': ('nl',),
    'Checker.YosysUnmappedCells': ('nl',), 'Checker.YosysSynthChecks': ('nl',),
    'Checker.NetlistAssignStatements': ('nl',),
    'Magic.RCX': ('gds',), 'Magic.DRC': ('gds',),
    'KLayout.DRC': ('gds',),
    # These native PV steps consume stream/logical views, not an ODB.
    # The resolved sidecar additionally enforces each installed step's inputs.
    'Magic.SpiceExtraction': ('gds', 'def'),
    'Netgen.LVS': ('spice', 'pnl'), 'KLayout.LVS': ('cdl', 'gds'),
    # Stream-level checks and finishing read the stream alone (steps 26, 26.5ic).
    'KLayout.Antenna': ('gds',), 'Checker.KLayoutAntenna': (),
    'KLayout.SealRing': ('gds',), 'KLayout.XOR': ('mag_gds', 'klayout_gds'),
    # Step 34's stream finishing (the PDK fill script, its density deck).
    'KLayout.Filler': ('gds',), 'KLayout.Density': ('gds',),
    'Checker.KLayoutDensity': (),
    # Steps 37.3 / 37.5ic (mig105): vibe-ic's own stream checks.
    'Vibeic.FinishingXOR': ('gds',), 'Vibeic.DatabaseUnit': ('gds',)}


def validate_step_receipt(folder: Path, step: str) -> dict:
    """Validate retained tool bytes before reuse or downstream publication.

    This checks a product boundary, not source landing. Missing execution
    output is refused; computing a new digest cannot replace the producer's
    recorded digest.
    """
    try:
        folder = folder.resolve()
        receipt = _load(folder / 'vibeic_receipt.json')
        fp, hashes = receipt['input'], receipt['sha256']
        if fp.get('step') != step or not isinstance(hashes, dict):
            raise ValueError('wrong producer or missing hashes')
        for name in ('state_out.json', 'input_fingerprint.json', 'pdk_root.json',
                     'invocation.log'):
            if name not in hashes:
                raise ValueError(f'missing producer file: {name}')
        for name, sha in hashes.items():
            path = (folder / name).resolve()
            if not path.is_relative_to(folder) or not re.fullmatch('[0-9a-f]{64}', str(sha)) \
                    or not path.is_file() or digest(path) != sha:
                raise ValueError(f'changed producer file: {name}')
        if _load(folder / 'input_fingerprint.json') != fp:
            raise ValueError('input fingerprint differs')
        if not (folder / 'invocation.log').read_text().strip():
            raise ValueError('tool execution log is empty')
        state = _load(folder / 'state_out.json')
        for path in _walk_paths({k: v for k, v in state.items() if k != 'metrics'}):
            if path.is_relative_to(folder) and \
                    hashes.get(str(path.relative_to(folder))) != digest(path):
                raise ValueError(f'unbound output view: {path}')
        return receipt
    except (OSError, ValueError, TypeError, KeyError, AttributeError) as exc:
        raise Refusal('LL_STEP_OUTPUT_UNBOUND', f'{folder}: {exc}') from exc


def config_file_hashes(config: dict, mounts: list) -> dict[str, str]:
    """Hash config files on the host, including files behind PDK mounts."""
    result = {}
    for path in _walk_paths(config):
        source = path
        for host, guest in sorted(mounts, key=lambda m: len(str(m[1])), reverse=True):
            if path.is_relative_to(guest):
                source = Path(host) / path.relative_to(guest)
                break
        if source.is_file():
            result[str(path)] = digest(source)
            # Density decks load their rule/layer definitions from Ruby
            # siblings. Bind those executable inputs before running/caching.
            if str(path) == config.get('KLAYOUT_DENSITY_RUNSET'):
                for dependency in sorted(source.parent.rglob('*.rb')):
                    guest = path.parent / dependency.relative_to(source.parent)
                    result[str(guest)] = digest(dependency)
    return result


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
    completed = run_container([docker, 'run', *_dmem.docker_memory_flags(), '--rm',
                               '--network', 'none', *volumes,
                               image, '--skip', 'openroad', '-exit', str(tcl)],
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
    receipt: dict[str, Any] = {'step': step_id, 'image': image,
                               'config': str(config_path), 'config_sha256': digest(config_path),
                               'design_name': config.get('DESIGN_NAME'),
                               'required': required, 'views': {}, 'derived': {}}

    def _file(view: str, value: Any) -> Path:
        path = Path(value)
        if not path.is_file():
            raise Refusal('LL_BRIDGE_VIEW_MISSING', f'{view}: {path}')
        receipt['views'][view] = {'source': str(path.resolve()), 'sha256': digest(path)}
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
                f'// vibe-ic bridge: {part.resolve()} sha256:{digest(part)}\n'
                + part.read_text(errors='replace') + '\n' for part in parts))
            receipt['derived']['nl'] = {'from': [str(p.resolve()) for p in parts],
                                        'sha256': digest(joined)}
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
        tcl = _openroad_convert(project, image, config,
                                [f"read_def {{{state['def']}}}", f'write_db {{{odb}}}'],
                                output_dir, 'def_to_odb', mounts, docker)
        if not odb.is_file():
            raise Refusal('LL_BRIDGE_CONVERSION_FAILED', str(output_dir / 'def_to_odb.log'))
        state['odb'] = str(odb.resolve())
        receipt['derived']['odb'] = {'from': state['def'], 'tcl_sha256': digest(tcl),
                                     'sha256': digest(odb)}
    if 'def' in required and 'def' not in state and 'odb' in state:
        out_def = output_dir / 'bridge.def'
        out_def.unlink(missing_ok=True)
        tcl = _openroad_convert(project, image, config,
                                [f"read_db {{{state['odb']}}}", f'write_def {{{out_def}}}'],
                                output_dir, 'odb_to_def', mounts, docker)
        if not out_def.is_file():
            raise Refusal('LL_BRIDGE_CONVERSION_FAILED', str(output_dir / 'odb_to_def.log'))
        state['def'] = str(out_def.resolve())
        receipt['derived']['def'] = {'from': state['odb'], 'tcl_sha256': digest(tcl),
                                     'sha256': digest(out_def)}
    if 'pnl' in required and 'pnl' not in state and ('odb' in state or 'def' in state):
        # The powered netlist every LibreLane OpenROAD step writes with its
        # views (io.tcl SAVE_PNL: `write_verilog -include_pwr_gnd`), from the
        # same database; LVS (Netgen.LVS) consumes it (mig105).
        pnl = output_dir / 'bridge.pnl.v'
        pnl.unlink(missing_ok=True)
        load = (f"read_db {{{state['odb']}}}" if 'odb' in state
                else f"read_def {{{state['def']}}}")
        tcl = _openroad_convert(project, image, config,
                                [load, f'write_verilog -include_pwr_gnd {{{pnl}}}'],
                                output_dir, 'to_pnl', mounts, docker)
        if not pnl.is_file():
            raise Refusal('LL_BRIDGE_CONVERSION_FAILED', str(output_dir / 'to_pnl.log'))
        state['pnl'] = str(pnl.resolve())
        receipt['derived']['pnl'] = {'from': state.get('odb') or state['def'],
                                     'tcl_sha256': digest(tcl), 'sha256': digest(pnl)}
    missing = [view for view in required if view not in state]
    if missing:
        raise Refusal('LL_BRIDGE_VIEW_MISSING', f'{step_id}: {missing}')
    state['metrics'] = dict(metrics or {})
    if metrics:
        if not metrics_source:
            raise Refusal('LL_BRIDGE_METRICS_UNSOURCED', step_id)
        receipt['metrics_source'] = metrics_source
    path = output_dir / 'state_in.json'
    write_json(path, state)
    receipt['state_sha256'] = digest(path)
    write_json(output_dir / 'bridge_receipt.json', receipt)
    return path


def _copy_state_views(state_path: Path, targets: dict[str, Path],
                      *, path_map: dict[str, str] | None = None) -> dict:
    """Copy mapped state views and describe the bytes transferred.

    This primitive establishes only a copy, never extraction measurement or
    a producer receipt. The native whole-flow importer supplies its own
    flow/step/source preflight and journal; direct RCX consumers must use
    ``handoff_to_direct`` and its producing-receipt validation.
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
        replaced = digest(dest) if dest.is_file() else None
        dest.parent.mkdir(parents=True, exist_ok=True)
        tmp = dest.with_name(dest.name + '.handoff.tmp')
        shutil.copyfile(source, tmp)
        os.replace(tmp, dest)
        rows[view] = {'source': str(source), 'source_sha256': digest(source),
                      'dest': str(dest), 'dest_sha256': digest(dest),
                      'replaced_sha256': replaced}
        if source.suffix.lower() == '.def':
            # The top a later step judges is the one this DEF states, whatever
            # the view is called (`def`, `post_cts_def`, `post_hold_def`).
            rows[view]['design'] = _def_design_name(source)
        if rows[view]['source_sha256'] != rows[view]['dest_sha256']:
            raise Refusal('LL_HANDOFF_COPY_MISMATCH', view)
    return {'state': str(state_path), 'state_sha256': digest(state_path),
            'views': rows}


def handoff_to_direct(state_path: Path, targets: dict[str, Path], receipt: Path,
                      *, path_map: dict[str, str] | None = None) -> dict:
    """LibreLane -> direct: put named state views where the direct step reads them.

    ``targets`` maps a state view (``def``, ``odb``, ``nl``, ``spef:<corner>``)
    to the file path the direct consumer expects. ``path_map`` rewrites a
    container prefix to its host path. Every handed file is bound by sha256
    on both sides; RCX additionally requires its original producer receipt.
    """
    rcx_receipt = (validate_rcx_receipt(state_path.parent)
                   if _state_step_id(state_path.parent) == 'OpenROAD.RCX' else None)
    document = _copy_state_views(state_path, targets, path_map=path_map)
    if rcx_receipt is not None:
        for view, row in document['views'].items():
            if view.partition(':')[0] != 'spef':
                continue
            source = Path(row['source'])
            recorded = rcx_receipt['sha256'].get(
                str(source.resolve().relative_to(state_path.parent.resolve())))
            if not recorded or row['dest_sha256'] != recorded:
                raise Refusal('LL_RCX_OUTPUT_UNBOUND', f'{view}: handoff bytes changed')
    write_json(receipt, document)
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
        identity = local_image_attestation(image)
        root = os.environ.get('PDK_ROOT', '')
        if not root.startswith('/') or not Path(root).is_dir():
            raise Refusal('LL_IMAGE_PDK_ROOT_UNDECLARED', f'{image}: PDK_ROOT={root!r}')
        return {'image_id': identity['image_id'], 'pdk_root': root.rstrip('/') or '/'}
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
        local_image_attestation(image)
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
    created = subprocess.run([docker, 'create', *_dmem.docker_memory_flags(),
                              '--network', 'none', '--entrypoint', 'true',
                              found['image_id']], capture_output=True, text=True)
    try:
        if created.returncode:
            raise Refusal('LL_IMAGE_PDK_NOT_EXTRACTABLE',
                          f'{image}: docker create rc={created.returncode} {created.stderr.strip()[:200]}')
        copied = subprocess.run([docker, 'cp', '-L', f'{created.stdout.strip()}:{guest}',
                                 str(scratch / pdk)], capture_output=True, text=True)
        if copied.returncode or not (scratch / pdk).is_dir():
            raise Refusal('LL_IMAGE_PDK_ABSENT',
                          f'{image}: {guest} not a directory in the image '
                          f'(rc={copied.returncode} {copied.stderr.strip()[:200]})')
        try:
            (scratch / pdk).rename(root / pdk)
        except OSError:
            if not (root / pdk).is_dir():   # another resolver won the rename; keep theirs
                raise
        write_json(marker, {**want, 'image': image, 'host_path': str(root / pdk)})
    finally:
        if not created.returncode:
            subprocess.run([docker, 'rm', '-f', created.stdout.strip()], capture_output=True)
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
                        image: str | None = None, docker: str = 'docker') -> dict[str, Any]:
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
    mismatch = _provider_route_mismatch(image, project)
    if mismatch is not None:
        raise mismatch
    provider = _provider_for_image(image)
    if provider is None and _explicit_local_route(project):
        provider = local_provider_identity(project, pdk)
    if provider is not None:
        if provider.pdk and pdk and provider.pdk != str(pdk):
            raise Refusal('LL_LOCAL_PDK_PROVIDER_MISMATCH',
                          f'provider declares {provider.pdk!r}; caller requested {pdk!r}')
        answer = {'path': provider.pdk_root, 'source': 'local_provider',
                  'identity': str(provider), 'provider': provider.as_record(),
                  'pdk': provider.pdk or pdk,
                  'pdk_from': ('provider identity' if provider.pdk else 'caller')}
        if project is not None and (project / 'phase3').is_dir():
            write_json(project / PDK_ROOT_PROVENANCE_REL, answer)
        return answer
    if switch.get('pdk_root_host'):
        answer = {'path': str(switch['pdk_root_host']), 'source': 'declared',
                  'declared_by': 'phase3/librelane_switch.json pdk_root_host'}
    elif os.environ.get('VIBEIC_LIBRELANE_PDK_ROOT'):
        answer = {'path': os.environ['VIBEIC_LIBRELANE_PDK_ROOT'], 'source': 'declared',
                  'declared_by': 'env VIBEIC_LIBRELANE_PDK_ROOT'}
    else:
        answer = None
    if answer is not None:
        # A declared root is a PDK_ROOT: the tree a consumer reads is
        # <path>/<pdk>. Record WHICH PDK when it is known, so a consumer of
        # the receipt (gds_antenna_deck_check) does not have to guess it.
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
                                 'image_pdk_root_from': ('attested LOCAL environment PDK_ROOT'
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
                     image: str | None = None, docker: str = 'docker') -> str | None:
    """The host PDK root per `pdk_root_resolution`, or None when it refuses."""
    try:
        return pdk_root_resolution(project, pdk, image=image, docker=docker)['path']
    except Refusal:
        return None


def resolve_image(project: Path | None = None) -> str:
    """Switch ``image`` > ``VIBEIC_LIBRELANE_IMAGE`` > the host's resolved image.

    The fallback is the plugin's ONE runtime resolver, `_eda_pin.image_reference`
    (the newest released vibeic-eda image on this host, by its own version
    label, as a digest).  The source never stores a digest or version: the EDA
    image and the plugin release separately (owner 2026-08-21, 2026-09-17).
    When nothing resolves this refuses by name; it never guesses.
    """
    path = project / 'phase3/librelane_switch.json' if project else None
    declared = _load(path).get('image') if path and path.is_file() else None
    provider = local_provider_identity(project)
    if provider is not None:
        if project is not None and (project / 'phase3').is_dir():
            write_json(project / 'phase3/librelane_image.provenance.json',
                       {'image': str(provider), 'source': 'host-owned LOCAL provider',
                        'provider': provider.as_record()})
        return provider
    if _ce.no_container_route():
        identity = local_image_attestation(declared or os.environ.get('VIBEIC_LIBRELANE_IMAGE'))
        if project is not None and (project / 'phase3').is_dir():
            write_json(project / 'phase3/librelane_image.provenance.json',
                       {**identity, 'source': 'host-CID attested LOCAL image'})
        return identity['image']
    if declared or os.environ.get('VIBEIC_LIBRELANE_IMAGE'):
        return str(declared or os.environ['VIBEIC_LIBRELANE_IMAGE'])
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
    if provider is not None:
        key = (str(provider), docker)
        if key not in _CAPABILITY:
            _CAPABILITY[key] = {
                'image': str(provider), 'execution_route': 'LOCAL',
                'provider': provider.as_record(), 'openroad_aliases': {},
                'tcl_probe': 'NOT_MEASURED: host-owned LOCAL provider'}
        return _CAPABILITY[key]
    if _ce.no_container_route():
        local_image_attestation(image)
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
        if exc.code != 'LL_TOOL_DEADLINE':
            raise
        # Best effort, like rc != 0 below: a probe that ran out of time
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
                  extra: list[str] | None = None,
                  drv_probe: list[str] | None = None) -> Path | None:
    """Write the init file that defines the probe's aliases (and a caller's
    `extra` Tcl lines, e.g. a tool debug print the caller reads back), or
    nothing when there is neither.

    `drv_probe`: the DRV stage probe (`drv_stage_receipts.probe_lines`). It is
    written to OpenROAD's init file AND to OpenSTA's (`.sta`), because the
    sign-off STA step runs the `sta` binary, which reads only its own."""
    aliases = (capability or {}).get('openroad_aliases') or {}
    if not aliases and not extra and not drv_probe:
        return None
    folder.mkdir(parents=True, exist_ok=True)
    lines = ['# vibe-ic librelane_contract: abbreviation aliases derived from the image']
    for short, full in sorted(aliases.items()):
        lines.append(f'if {{[llength [info commands ::{short}]] == 0}} '
                     f'{{ proc ::{short} {{args}} {{ return [::{full} {{*}}$args] }} }}')
    if extra:
        lines += ['# vibe-ic librelane_contract: caller-declared init lines', *extra]
    if drv_probe:
        lines += ['# vibe-ic librelane_contract: DRV stage probe', *drv_probe]
    (folder / '.openroad').write_text('\n'.join(lines) + '\n')
    sta_init = folder / '.sta'
    if drv_probe:
        sta_init.write_text('\n'.join(['# vibe-ic librelane_contract: DRV stage probe',
                                        *drv_probe]) + '\n')
    else:
        sta_init.unlink(missing_ok=True)
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


#: The flow-mode layer (llv1 W3): the mode of every switchable step under a
#: project-wide implementation flow (`_impl_flow`, the `--librelane` record).
#: It sits ABOVE the switch file, `PRODUCTION_DEFAULTS` and the class
#: defaults, and exists only when the project carries a non-default record;
#: a project without one never reaches it, so its answers are unchanged.
#:
#: Under `librelane` LibreLane produces the step, EXCEPT where the owner's
#: ruling keeps vibe-ic's check because LibreLane's default is weaker (the
#: eight places of COMMON.md). There the step is `dual` when its `librelane`
#: mode would REPLACE vibe-ic's judgement, and `direct` when vibe-ic alone
#: does the step:
#:   2   direct  P0's blocking lint list (i). LibreLane's own lint is not lost:
#:               Verilator.Lint + its three checkers are the first four steps
#:               of segment 1 (MEASURED, spike 2026-09-28), so the phase-2 arm
#:               is not run a second time.
#:   3/4/5 direct  CDC, simulation and formal are vibe-ic's (no LibreLane step).
#:   8   dual    `librelane` replaces the SDC semantic checks with OpenSTA's
#:               read verdict; both must pass (a: the spec SDC is kept).
#:   13  direct  vibe-ic LEC on the exact netlist segment 2 consumes (b); the
#:               EQY arm is off by default and skips gf180 in LibreLane.
#:   24  dual    LibreLane's IR is static and report-only; vibe-ic's budget
#:               gates judge too (d).
#:   25  direct  LibreLane has no EM step; vibe-ic runs it on the tool's ODB.
#:   26  dual    Classic reports antenna violations without gating on them;
#:               `librelane` would drop vibe-ic's own antenna re-read (h).
#:   31  dual    LibreLane's reduced DRC deck, no ERC, LVS from a DEF
#:               extraction; vibe-ic's step-31 decks stay (g).
#:   23  librelane  vibe-ic's sta_report_check judges the tool's per-corner
#:               reports in this mode (c).
#:   32  librelane  Vibeic.PostRouteRepair inside the chain (e).
#:   29  librelane  vibe-ic's own gate-level simulation (Vibeic.GateLevelSim)
#:               over the tool's per-corner SDFs.
#:   30  direct  LibreLane has no post-layout SPICE step; the tool arm is
#:               only recorded beside vibe-ic's correlation.
#: Steps absent here (the analog A6/A7 arms) keep the ordinary resolution;
#: v1 refuses an analog design under the flag at the front door (decision 13).
IMPL_STEP_MODES: dict[str, dict[str, str]] = {
    'librelane': {
        '2': 'direct', '3': 'direct', '4': 'direct', '5': 'direct',
        '7': 'librelane', '8': 'dual', '9': 'librelane', '10': 'librelane',
        '13': 'direct',
        '15': 'librelane', '15.5ic': 'librelane', '17': 'librelane',
        '18': 'librelane', '19': 'librelane', '20': 'librelane',
        '21': 'librelane', '22': 'librelane', '23': 'librelane',
        '24': 'dual', '25': 'direct', '26': 'dual', '26.5ic': 'librelane',
        '29': 'librelane', '30': 'direct',
        '31': 'dual', '32': 'librelane', '33': 'librelane', '34': 'librelane',
        '37': 'librelane', 'DT2': 'librelane', 'DT3': 'librelane',
    },
}


#: Every step some implementation-flow layer decides. A step outside it (the
#: analog A6/A7 arms; v1 is digital only) never reads the record, so neither
#: a damaged record nor a switch conflict can change its answer.
IMPL_LAYER_STEPS: frozenset[str] = frozenset(
    step for layer in IMPL_STEP_MODES.values() for step in layer)


def impl_step_modes(project: Path) -> dict[str, str] | None:
    """The flow-mode layer in force for `project`, or None (the default flow).

    None whenever the project has no implementation-flow record, without
    reading anything else. A record that cannot be read refuses by its own
    reason class, never falls back to the per-step answers: guessing the
    default for a flagged project is the in-place switch decision 20 refuses.
    A switch file naming a step the layer decides refuses the run with
    `IMPL_SWITCH_CONFLICT` (decision 18), whichever answer either gives.
    """
    import _impl_flow
    if not _impl_flow.record_path(project).exists():
        return None
    try:
        impl = _impl_flow.recorded_impl(project)
    except _impl_flow.ImplRefusal as exc:
        raise Refusal(exc.reason_class, exc.detail) from None
    layer = IMPL_STEP_MODES.get(impl)
    if layer is None:
        raise Refusal(_impl_flow.IMPL_NOT_YET_SUPPORTED,
                      f"no flow-mode layer for '{impl}' in this release")
    path = project / 'phase3/librelane_switch.json'
    named = _load(path).get('steps', {}) if path.is_file() else {}
    clash = sorted(step for step in named if step in layer)
    if clash:
        raise Refusal('IMPL_SWITCH_CONFLICT',
                      f"{path} names step(s) {clash}, which the project's "
                      f"'{impl}' flow ({_impl_flow.FLAG_FOR[impl]}) decides; "
                      'a step is chosen by the flag or by the switch file, '
                      'never both. Remove them from the switch file, or run '
                      'the default flow.')
    return dict(layer)


def selected_mode(project: Path, step: str) -> str:
    """The flow-mode layer's answer when the project has an implementation
    flow that decides the step (a step no layer decides never reads the
    record), else the project's switch when it names the
    step, else the production default for the step, else the design class's
    default (when the steps it continues resolve to LibreLane too), else
    `direct`. An invalid mode is refused, from either source."""
    layer = impl_step_modes(project) if step in IMPL_LAYER_STEPS else None
    if layer is not None and step in layer:
        return layer[step]
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
    outside every class, and for a project under an implementation flow,
    whose layer decides every class-default step."""
    layer = impl_step_modes(project)
    path = project / 'phase3/librelane_switch.json'
    steps = _load(path).get('steps', {}) if path.is_file() else {}
    cls = design_class(project)
    return {step: selected_mode(project, step)
            for step in CLASS_PRODUCTION_DEFAULTS.get(cls or '', {})
            if step not in steps and step not in PRODUCTION_DEFAULTS
            and step not in (layer or {})
            and _class_default(project, step, steps) is not None}


#: vibe-ic's own LibreLane steps (`Vibeic.*`), shipped with this plugin in
#: `programs/librelane_plugins/librelane_plugin_vibeic`. LibreLane discovers a
#: `librelane_plugin_*` module on `sys.path`; the contract mounts `programs/`
#: read-only at its own path and adds the plugin root to `PYTHONPATH` only
#: for a run that names such a step, so every other step's invocation and
#: fingerprint are unchanged.
PLUGIN_ROOT = Path(__file__).resolve().parent / 'librelane_plugins'
PLUGIN_STEP_PREFIX = 'Vibeic.'
#: The `programs/` modules the plugin's steps import (inputs of those steps).
PLUGIN_HOST_MODULES = ('_spare_plan.py', 'dynamic_ir_vectored_emit.py')


def _plugin_args(step_ids: list[str]) -> list[str]:
    if not any(str(s).startswith(PLUGIN_STEP_PREFIX) for s in step_ids):
        return []
    programs = PLUGIN_ROOT.parent.resolve()
    return ['-v', f'{programs}:{programs}:ro', '-e', f'PYTHONPATH={PLUGIN_ROOT.resolve()}']


def _plugin_digests(step_id: str) -> dict[str, str]:
    """The custom step's code is an input of that step: its files, and the
    plan builder it imports, by sha256."""
    if not step_id.startswith(PLUGIN_STEP_PREFIX):
        return {}
    files = sorted(PLUGIN_ROOT.rglob('*.py')) + sorted(PLUGIN_ROOT.rglob('*.tcl')) + sorted(
        PLUGIN_ROOT.rglob('*.drc')) + [
        PLUGIN_ROOT.parent / name for name in PLUGIN_HOST_MODULES]
    return {str(path.relative_to(PLUGIN_ROOT.parent)): digest(path)
            for path in files if path.is_file()}


#: The steps whose config must carry the die the run itself settled on:
#: step 15's floorplan sizes the die, and 15.5ic's PadRing (`pad_cfg.tcl`)
#: reads `$::env(DIE_AREA)`, which LibreLane never exports for a null value.
_DIE_STEPS = frozenset({'OpenROAD.Floorplan', 'OpenROAD.PadRing'})


def _rect_differs(a: Any, b: Any) -> bool:
    return len(a) != len(b) or any(abs(x - y) > 1e-6 for x, y in zip(a, b))


def _whole(rect: list[float]) -> list[float | int]:
    return [int(v) if float(v).is_integer() else v for v in rect]


def _runner_floorplan(project: Path) -> tuple[list | None, list | None, dict[str, str], str]:
    """(die, core, sources, why) from the run's one floorplan authority.

    `phase3_one_shot_runner.step_pnr` writes `floorplan_rectangles.json`
    before it hands steps 15/15.5ic to LibreLane; it is read through
    `_declared_die`, the one reader of that record. The core is the slot's
    `floorplan_rect_um` when the record names one, else the die inset by
    `core_pad_um` -- the direct deck's own `-core_area`.
    """
    import _declared_die as DD
    die, why, record = DD.declared(project)
    if die is None:
        return None, None, {}, why
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
    return die, core, sources, why


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
    die, core, derived, why = _runner_floorplan(project)
    if die is not None:
        if 'DIE_AREA' in config:
            if _rect_differs(config['DIE_AREA'], die):
                raise Refusal('LL_DERIVED_DIE_CONFLICT',
                              f"declared {config['DIE_AREA']} ({sources['DIE_AREA']}) vs "
                              f"the run's {die} ({derived['DIE_AREA']})")
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


def _check_synthesised_read(project: Path, config: dict, sources: dict) -> None:
    """A layout chain reads the RTL the netlist was synthesised from, or refuses.

    Phase-3 synthesis records the read it built (`chip_read_built.json`,
    every file with its sha256 and the define decision) and binds it to the
    netlist it produced. While that netlist stands, the chain's
    VERILOG_FILES, minus the chip-top wrapper step 15.5ic wrote after
    synthesis, must be that read exactly, and the chain carries synthesis's
    define decision. A record that describes no netlist on disk is not
    compared: the provenance says so, with the reason.
    """
    import _chip_synth_read as CSR
    files = config.get('VERILOG_FILES')
    if not files:
        return
    built, why = CSR.built_record_for_current_netlist(project)
    if built is None:
        sources['VERILOG_FILES'] += (
            f'; synthesised-read comparison NOT_MEASURED: {why}; '
            f'VERILOG_DEFINES not carried for the same reason')
        return
    wrapper = 'phase3/stage3/pnr/chip_top_io.v'
    paths = [project / str(f).removeprefix('dir::') for f in files]
    read = [p for p in paths if p.resolve() != (project / wrapper).resolve()]
    # The top is synthesis's own; the file read is this chain's to match.
    differences = CSR.chip_read_differences(
        {'files': built.get('files') or []},
        {'files': [{'name': p.name, 'sha256': digest(p)} for p in read]})
    rel = CSR.built_record_path(project).relative_to(project)
    if differences:
        raise Refusal('LL_LAYOUT_RTL_NOT_THE_SYNTHESISED_READ',
                      f"VERILOG_FILES vs {rel}: {'; '.join(differences)}")
    sources['VERILOG_FILES'] += (f"; equals {rel} (file names and sha256, "
                                 f"bound to {built['netlist']['path']})")
    define = built.get('define')
    if not isinstance(define, dict) or not isinstance(define.get('simulation'), bool):
        raise Refusal('LL_SYNTHESIS_DEFINE_UNRECORDED',
                      f'{rel}.define.simulation is {define!r}')
    # The defines of the read that PRODUCED the netlist: the record is
    # rewritten at binding when a retry frontend read other defines than the
    # decision (`_chip_synth_read.bind_built_record_netlist`).
    defines = (['SIMULATION'] if define['simulation'] else []) + \
        (['SYNTHESIS'] if define.get('synthesis') is True else [])
    _set(config, sources, 'VERILOG_DEFINES', defines,
         f"{rel}.define.simulation/.synthesis (the defines of the read that built "
         f"{built['netlist']['path']}: {define.get('verdict')}, frontend "
         f"{built.get('frontend', 'unrecorded')})")


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
    _check_synthesised_read(project, emitted, sources)
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
    script = '''import json,sys,hashlib
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
    if step_id == "KLayout.Density":
        def walk(value):
            if isinstance(value, dict):
                for nested in value.values(): yield from walk(nested)
            elif isinstance(value, (tuple, list)):
                for nested in value: yield from walk(nested)
            elif str(value).startswith("/"): yield Path(str(value))
        # Image-owned common templates are real inputs too. Read them in the
        # same pinned resolver container, never by guessing a host path.
        owned = {str(path): hashlib.sha256(path.read_bytes()).hexdigest()
                 for path in walk(selected) if path.is_file()
                 and not path.is_relative_to("/pdk")
                 and not path.is_relative_to(project)}
        Path(output, step_id + ".image_files.json").write_text(
            json.dumps({"image": image, "sha256": owned}, indent=2) + "\\n")
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


def emit_pdn_cfg(image: str, pdk: str, output: Path, *, docker: str = 'docker') -> Path | None:
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
    if not (ring.get('connect_to_pad_layers') and connects):
        return None
    script = ('import json,os,librelane;print(json.dumps({' + repr(_PDN_PAYLOAD_KEY) +
              ':open(os.path.join(os.path.dirname(librelane.__file__),'
              '"scripts","openroad","common","pdn_cfg.tcl")).read()}))')
    result = run_container([docker, 'run', *_dmem.docker_memory_flags(), '--rm', '--network',
                            'none', '--entrypoint', 'python3', image, '-c', script],
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
    suffix = [f'# vibe-ic: pdk_registry.json pdks[name={pdk}].pdn_ring.connects',
              *[f'add_pdn_connect -grid stdcell_grid -layers {{{a} {b}}}' for a, b in connects]]
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(native + separator + '\n'.join(suffix) + '\n')
    return output


def flow_segment(image: str, first: str, last: str, *, flow: str = 'Chip',
                 docker: str = 'docker') -> list[str]:
    """The step ids ``first..last`` exactly as the image's own flow orders them."""
    script = ('import json,sys;from librelane.flows import Flow;'
              'f=Flow.factory.get(sys.argv[1]);'
              'print(json.dumps([s.id for s in f.Steps]))')
    result = run_container([docker, 'run', *_dmem.docker_memory_flags(), '--rm', '--network',
                            'none', '--entrypoint', 'python3', image, '-c', script, flow],
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
        'os.write(fd,cfg.dumps().encode());os.close(fd);os.replace(tmp,out)'
    )
    volumes = ['-v', f'{project.resolve()}:{project.resolve()}']
    for host, guest in mounts or []:
        volumes += ['-v', f'{host.resolve()}:{guest}:ro']
    result = run_container([docker, 'run', *_dmem.docker_memory_flags(), '--rm', *volumes,
                            '--entrypoint', 'python3', image, '-c', script],
                           probe_deadline_s=PROBE_DEADLINE_S)
    if result.returncode or not output.is_file():
        raise Refusal('LL_CONFIG_RESOLVE_FAILED',
                      (result.stderr or result.stdout)[-1000:])
    return output

def _sta_liberty_input_hashes(config: dict, project: Path,
                              mounts: list[tuple[Path, str]]) -> dict[str, str | None]:
    """Hash the host bytes mounted at each STAPostPNR Liberty guest path.

    The scene log later establishes which of these declared inputs was read.
    Unknown paths stay unbound; a consumer cannot sign off from a filename.
    """
    libraries: set[str] = set()
    for field in ('CELL_LIBS', 'PAD_LIBS', 'EXTRA_LIBS'):
        value = config.get(field) or {}
        groups = value.values() if isinstance(value, dict) else [value]
        for group in groups:
            if isinstance(group, str):
                libraries.add(group)
            elif isinstance(group, (list, tuple)):
                libraries.update(v for v in group if isinstance(v, str))
    roots = [(project.resolve(), project.resolve()),
             *((Path(host).resolve(), Path(guest)) for host, guest in mounts)]
    roots.sort(key=lambda item: len(str(item[1])), reverse=True)
    result: dict[str, str | None] = {}
    for library in sorted(libraries):
        guest_path = Path(library)
        host_path = None
        for host_root, guest_root in roots:
            try:
                host_path = host_root / guest_path.relative_to(guest_root)
                break
            except ValueError:
                continue
        result[library] = digest(host_path) if host_path and host_path.is_file() else None
    return result


def _rcx_pdk_input_hashes(config: dict, project: Path,
                          mounts: list[tuple[Path, str]]) -> dict[str, str | None]:
    """RCX's declared rules and physical LEFs, at their mounted host bytes."""
    paths = []
    for field in ('RCX_RULESETS', 'TECH_LEFS', 'CELL_LEFS', 'EXTRA_LEFS'):
        value = config.get(field) or []
        groups = value.values() if isinstance(value, dict) else [value]
        for group in groups:
            paths.extend([group] if isinstance(group, str) else group)
    return _sta_liberty_input_hashes({'CELL_LIBS': {'*': paths}}, project, mounts)


def validate_rcx_receipt(folder: Path) -> dict:
    """Require the producing receipt's bytes before sharing or reusing RCX.

    Current path equality and a newly computed output hash cannot establish
    which route was extracted or which SPEF the producer actually wrote.
    """
    try:
        folder = Path(folder).resolve()
        receipt = _load(folder / 'vibeic_receipt.json')
        fingerprint, hashes = receipt['input'], receipt['sha256']
        if fingerprint.get('step') != 'OpenROAD.RCX' or not isinstance(hashes, dict):
            raise ValueError('not an RCX producer receipt')
        for name in ('state_out.json', 'state_in.json', 'config.json',
                     'input_fingerprint.json'):
            if not hashes.get(name) or hashes[name] != digest(folder / name):
                raise ValueError(f'{name}: producer bytes absent or changed')
        if _load(folder / 'input_fingerprint.json') != fingerprint:
            raise ValueError('producer input fingerprint differs')
        before = _load(folder / 'state_in.json')
        state = _load(folder / 'state_out.json')
        for view in ('def', 'odb', 'nl', 'sdc'):
            if before.get(view):
                recorded = fingerprint['state_files'].get(before[view])
                if not recorded or any(not doc.get(view) or
                        digest(Path(doc[view])) != recorded for doc in (before, state)):
                    raise ValueError(f'{view}: extraction input bytes changed')
        spefs = state.get('spef')
        if not isinstance(spefs, dict) or not spefs:
            raise ValueError('producer SPEF population absent')
        for pattern, source in spefs.items():
            path = Path(source).resolve()
            if not path.is_relative_to(folder):
                raise ValueError(f'{pattern}: SPEF belongs to another producer')
            recorded = hashes.get(str(path.relative_to(folder)))
            if not recorded or recorded != digest(path):
                raise ValueError(f'{pattern}: producer SPEF bytes absent or changed')
        return receipt
    except (OSError, ValueError, TypeError, KeyError, AttributeError) as exc:
        raise Refusal('LL_RCX_OUTPUT_UNBOUND', f'{folder}: {exc}') from exc


def _current_config_material(config: dict, mounts: list) -> dict:
    """Hash the real files read through the caller's declared mounts."""
    result = {}
    for path in _walk_paths(config):
        material = path
        for host, guest in mounts:
            if path.is_relative_to(guest):
                material = Path(host) / path.relative_to(guest)
                break
        if material.is_dir():
            continue
        if not material.is_file():
            raise Refusal('LL_CONFIG_MATERIAL_MISSING', str(path))
        result[str(material)] = digest(material)
    return result


def xor_report_record(folder: Path) -> dict:
    """Read the actual Step37.3 KLayout report and its compared subjects."""
    import xml.etree.ElementTree as ET
    report = folder / 'xor.xml'
    if not report.is_file():
        raise Refusal('LL_XOR_REPORT_MISSING', str(report))
    try:
        with report.open('rb') as stream:
            root = ET.parse(stream).getroot()
    except (OSError, ET.ParseError) as exc:
        raise Refusal('LL_XOR_REPORT_UNREADABLE', str(report)) from exc
    state = _load(folder / 'state_out.json')
    design = _load(folder / 'config.json').get('DESIGN_NAME')
    magic, klayout = state.get('mag_gds'), state.get('klayout_gds')
    if (root.tag != 'report-database' or not design
            or root.findtext('top-cell') != design
            or root.findtext('description') != f'XOR {magic} vs. {klayout}'):
        raise Refusal('LL_XOR_REPORT_SUBJECT_MISMATCH', str(report))
    items = root.find('items')
    value = (state.get('metrics') or {}).get('design__xor_difference__count')
    if (items is None or type(value) is not int or value < 0
            or len(items.findall('item')) != value
            or any(item.tag != 'item' for item in items)):
        raise Refusal('LL_XOR_REPORT_COUNT_MISMATCH', str(report))
    return {'path': 'xor.xml', 'sha256': digest(report), 'design': design,
            'magic_gds': {'path': magic, 'sha256': digest(Path(magic))},
            'klayout_gds': {'path': klayout, 'sha256': digest(Path(klayout))},
            'count': len(items.findall('item'))}


def bind_xor_report(folder: Path, receipt: dict) -> dict:
    """Complete producer metadata from retained real report bytes, without tools."""
    record = xor_report_record(folder)
    return {**receipt, 'sha256': {**receipt['sha256'], 'xor.xml': record['sha256']},
            'xor_report': record}


def check_xor_report(folder: Path, receipt: dict) -> dict:
    """A missing binding or any changed bytes/subject/result blocks reuse."""
    record = receipt.get('xor_report')
    if (not isinstance(record, dict) or record.get('path') != 'xor.xml'
            or receipt.get('sha256', {}).get('xor.xml') != record.get('sha256')):
        raise Refusal('LL_XOR_REPORT_BINDING_MISSING', str(folder))
    if not (folder / 'xor.xml').is_file():
        raise Refusal('LL_XOR_REPORT_MISSING', str(folder / 'xor.xml'))
    if digest(folder / 'xor.xml') != record['sha256']:
        raise Refusal('LL_XOR_REPORT_CHANGED', str(folder / 'xor.xml'))
    current = xor_report_record(folder)
    if current != record:
        raise Refusal('LL_XOR_REPORT_BINDING_MISMATCH', str(folder / 'xor.xml'))
    return current


def run_chain(project: Path, image: str, steps: list[tuple[str, Path, Path]],
              *, docker: str = 'docker', mounts: list[tuple[Path, str]] | None = None,
              lane: str | None = None, pdk_root: str | None = None,
              namespace: str | None = None,
              openroad_init: list[str] | None = None) -> list[Path]:
    """Run pinned per-step snapshots. Step directories retain both inputs and outputs.

    ``openroad_init``: extra Tcl lines for the OpenROAD init file every
    OpenROAD step reads (joins each step's fingerprint).

    ``pdk_root``: the PDK root as the step container sees it (normally
    `PDK_GUEST_ROOT`, bound from the run's resolved root). It is REQUIRED:
    without it LibreLane's CLI takes `--pdk-root` from the image's own
    `PDK_ROOT` at import, a value nothing in the run stated. Each step folder
    records it, with the host mounts beneath it, in `pdk_root.json`.
    """
    if not pdk_root or not str(pdk_root).startswith('/'):
        raise Refusal('LL_PDK_ROOT_UNSTATED',
                      f'{[s[0] for s in steps]}: pdk_root={pdk_root!r}; the run '
                      f'must state the PDK root its step containers read, or '
                      f'LibreLane defaults to the image\'s PDK_ROOT')
    mismatch = _provider_route_mismatch(image, project)
    if mismatch is not None:
        raise mismatch
    provider = _provider_for_image(image)
    local = provider is not None or _provider_route(project)
    root = str(pdk_root).rstrip('/') or '/'
    pdk_record = {'cli_pdk_root': str(pdk_root),
                  'mounts_under_it': [[str(host.resolve()), guest]
                                      for host, guest in mounts or []
                                      if guest == root or guest.startswith(root + '/')],
                  'stated_by': 'run_chain(pdk_root=...)'}
    if provider is not None:
        pdk_record['provider'] = provider.as_record()
    if local:
        pdk_root = _ce.localise_mounted_paths(str(pdk_root),
            [(guest, str(host.resolve())) for host, guest in mounts or []])
        logical_mounts = pdk_record['mounts_under_it']
        pdk_record.update(cli_pdk_root=pdk_root, requested_pdk_root=root,
            execution_route='LOCAL', requested_mounts=logical_mounts,
            mounts_under_it=[[host, _ce.localise_mounted_paths(guest,
                [(g, str(h.resolve())) for h, g in mounts or []])]
                for host, guest in logical_mounts])
    capability = image_capability(image, docker)
    outputs = []
    previous: Path | None = None
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
    import drv_stage_receipts as _drv_stages
    drv_probe = (_drv_stages.probe_lines()
                 if _drv_stages.chain_needs_probe(s for s, _, _ in steps) else None)
    home = openroad_home(base / '.openroad_home', capability, openroad_init,
                         drv_probe=drv_probe)
    for index, (step_id, config, initial_state) in enumerate(steps, 1):
        name = f'{index:02d}-{step_id.lower().replace(".", "-")}'
        folder = base / name
        state_path = previous or initial_state
        state = _load(state_path)
        _check_state(state, step_id=step_id)
        if _load(config).get('meta', {}).get('step') != step_id:
            raise Refusal('LL_STEP_CONFIG_MISMATCH', step_id)
        # A step's DECLARED outputs are not a promise (KLayout.StreamOut
        # declares `gds` and writes only `klayout_gds`), so the views the next
        # step declares it consumes are checked on the state it actually gets.
        if views_path(config).is_file():
            declared = _load(views_path(config)).get('inputs') or []
            missing = [view for view in declared if not state.get(view)]
            if missing:
                raise Refusal('LL_STATE_MISSING', f'{step_id}: {missing}')
        fingerprint = {'image': str(image), 'config': digest(config), 'state': digest(state_path),
                       'state_files': {str(path): digest(path) for path in _walk_paths(
                           {k: v for k, v in state.items() if k != 'metrics'})},
                       # Files the step config names (SDC, EQY script, PDN Tcl…)
                       # are inputs too: an edited deck must re-run the step.
                       'config_files': config_file_hashes(_load(config), mounts or []),
                       'step': step_id}
        if provider is not None:
            fingerprint['local_provider'] = provider.as_record()
        elif _ce.no_container_route():
            fingerprint['local_image'] = local_image_attestation(image)
        if lane in ('37.3-magic', '37.3-compare'):
            fingerprint['config_files'] = _current_config_material(
                _load(config), mounts or [])
        if step_id == 'KLayout.Density':
            image_files = config.with_name('KLayout.Density.image_files.json')
            if image_files.is_file():
                owned = _load(image_files)
                if owned.get('image') != image or not isinstance(owned.get('sha256'), dict) \
                        or any(not re.fullmatch('[0-9a-f]{64}', str(sha))
                               for sha in owned['sha256'].values()):
                    raise Refusal('LL_DENSITY_IMAGE_INPUT_UNBOUND', str(image_files))
                fingerprint['image_files'] = owned
                fingerprint['image_files_sha256'] = digest(image_files)
        if step_id == 'OpenROAD.STAPostPNR':
            fingerprint['liberty_files'] = _sta_liberty_input_hashes(
                _load(config), project, mounts or [])
        if step_id == 'OpenROAD.RCX':
            fingerprint['rcx_pdk_files'] = _rcx_pdk_input_hashes(
                _load(config), project, mounts or [])
            if not fingerprint['rcx_pdk_files'] or any(
                    value is None for value in fingerprint['rcx_pdk_files'].values()):
                raise Refusal('LL_RCX_PDK_INPUT_UNREADABLE', str(config))
        if home:
            fingerprint['openroad_aliases'] = (capability or {}).get('openroad_aliases') or {}
        if step_id.startswith(PLUGIN_STEP_PREFIX):
            fingerprint['plugin'] = _plugin_digests(step_id)
        if openroad_init:
            fingerprint['openroad_init'] = list(openroad_init)
        if drv_probe:
            fingerprint['drv_stage_probe'] = _drv_stages.probe_digest()
        receipt = folder / 'vibeic_receipt.json'
        # A folder is reused only if it was run under THIS stated root: one
        # from before the root was recorded (the CLI then took the image's
        # PDK_ROOT) or under another root/mount is archived and re-run. The
        # fingerprint itself is unchanged, so no other step re-runs for it.
        try:
            retained = validate_step_receipt(folder, step_id) if receipt.exists() else None
        except Refusal:
            retained = None
        if (retained is not None and retained.get('input') == fingerprint
                and (folder / 'state_out.json').exists()
                and (folder / 'pdk_root.json').is_file()
                and _load(folder / 'pdk_root.json') == pdk_record):
            if lane == '37.3-compare' and step_id == 'KLayout.XOR':
                check_xor_report(folder, _load(receipt))
            if step_id == 'OpenROAD.RCX':
                validate_rcx_receipt(folder)
            _check_state(_load(folder / 'state_out.json'), outputs=True)
            previous = folder / 'state_out.json'
            outputs.append(folder)
            _drv_stages.record_step(project, step_id, folder, reused=True)
            continue
        if folder.exists():
            archive = base / 'attempts'
            archive.mkdir(parents=True, exist_ok=True)
            number = 1
            while (archive / f'{name}-{number:04d}').exists():
                number += 1
            shutil.move(str(folder), str(archive / f'{name}-{number:04d}'))
        folder.mkdir(parents=True, exist_ok=True)
        write_json(folder / 'input_fingerprint.json', fingerprint)
        write_json(folder / 'pdk_root.json', pdk_record)
        volume_args = ['-v', f'{project.resolve()}:{project.resolve()}']
        # LibreLane's Yosys ABC path already emits the exact temporary script
        # with ``-showtmp``.  Keep that tool-owned temp directory on the
        # existing same-path project mount so the receipt owner can copy the
        # script named by invocation.log after the container returns.  This is
        # capture/persistence only; it does not enable ABC buffering.
        abc_tmp = None
        if step_id == 'Yosys.Synthesis':
            abc_tmp = folder / 'vibeic_abc_tmp'
            abc_tmp.mkdir(parents=True, exist_ok=True)
            volume_args += ['--workdir', str(folder.resolve())]
        for host, guest in mounts or []:
            volume_args += ['-v', f'{host.resolve()}:{guest}:ro']
        if home:
            volume_args += ['-e', f'HOME={home.resolve()}']
        if abc_tmp is not None:
            volume_args += ['-e', f'TMPDIR={abc_tmp.resolve()}']
        volume_args += _plugin_args([step_id])
        cmd = [docker, 'run', *_dmem.docker_memory_flags(), '--rm', *volume_args,
               '--entrypoint', 'python3', image,
               '-m', 'librelane.steps', 'run', '--id', step_id, '-c', str(config),
               '-i', str(state_path), '-o', str(folder), '--pdk-root', str(pdk_root)]
        try:
            completed = run_container(cmd, supervised=True,
                                      log=folder / 'invocation.log')
        except Refusal as exc:
            if exc.code != 'LL_TOOL_STALLED':
                raise
            partial = folder / 'state_out.json'
            moved = folder / 'state_out.stalled.json'
            if partial.is_file():
                partial.replace(moved)
            write_json(folder / 'vibeic_stalled.json', {
                'verdict': 'NOT_MEASURED', 'reason_class': 'stalled',
                'step': step_id, 'detail': str(exc),
                'partial_state': str(moved) if moved.is_file() else None,
                'invocation_log': str(folder / 'invocation.log')})
            raise Refusal(exc.code, f'{step_id}: {exc}; '
                          f'evidence={folder / "vibeic_stalled.json"}') from exc
        (folder / 'invocation.log').write_text(completed.stdout + '\n' + completed.stderr)
        if completed.returncode or not (folder / 'state_out.json').exists():
            raise Refusal('LL_STEP_FAILED', f'{step_id}: rc={completed.returncode}; {folder / "invocation.log"}')
        if step_id == 'Yosys.Synthesis':
            # Use the existing receipt owner and the actual tool log.  A
            # missing or guest-only path remains absent and therefore keeps
            # the downstream synth receipt NOT_VERIFIED/FAIL.
            _drv_stages.keep_abc_script(
                project, folder, (folder / 'invocation.log').read_text(errors='replace'))
        out_state = _load(folder / 'state_out.json')
        _check_state(out_state, outputs=True)
        if step_id == 'OpenROAD.STAPostPNR' and fingerprint['liberty_files'] != \
                _sta_liberty_input_hashes(_load(config), project, mounts or []):
            raise Refusal('LL_STA_LIBERTY_CHANGED_DURING_RUN', str(folder))
        if step_id == 'OpenROAD.RCX' and fingerprint['rcx_pdk_files'] != \
                _rcx_pdk_input_hashes(_load(config), project, mounts or []):
            raise Refusal('LL_RCX_PDK_CHANGED_DURING_RUN', str(folder))
        if step_id == 'OpenROAD.RCX':
            try:
                inputs_unchanged = (fingerprint['state'] == digest(state_path) and
                    fingerprint['config'] == digest(config) and
                    all(digest(Path(path)) == recorded
                        for path, recorded in fingerprint['state_files'].items()))
            except OSError:
                inputs_unchanged = False
            if not inputs_unchanged:
                raise Refusal('LL_RCX_OUTPUT_UNBOUND',
                              f'{folder}: extraction input bytes changed during execution')
        hashes = {'state_out.json': digest(folder / 'state_out.json'),
                  'invocation.log': digest(folder / 'invocation.log')}
        for path in _walk_paths({k: v for k, v in out_state.items() if k != 'metrics'}):
            if path.is_relative_to(folder):
                hashes[str(path.relative_to(folder))] = digest(path)
        for path in folder.rglob('*'):
            if path.is_file() and path.name.endswith(('.json', '.rpt')) and path.name not in ('vibeic_receipt.json',):
                hashes[str(path.relative_to(folder))] = digest(path)
            if step_id == 'OpenROAD.STAPostPNR' and path.is_file() and path.name == 'sta.log':
                hashes[str(path.relative_to(folder))] = digest(path)
        record = {'input': fingerprint, 'sha256': hashes}
        if lane == '37.3-compare' and step_id == 'KLayout.XOR':
            record = bind_xor_report(folder, record)
        write_json(receipt, record)
        previous = folder / 'state_out.json'
        outputs.append(folder)
        # DRV standard section 1: the stage's receipt, bound to this run.
        _drv_stages.record_step(project, step_id, folder)
    return outputs


#: STAPostPNR writes one `sta.log` per analysed corner. This line names each
#: cell library it read for that corner (LibreLane 3.1 `scripts/openroad/sta`).
_STA_CELL_LIBRARY_RE = re.compile(
    r"^Reading cell library for the '([^']+)' corner at '([^']+)'", re.M)


def _state_step_id(folder: Path) -> str | None:
    """The LibreLane step that wrote `folder`, from its own records."""
    receipt = folder / 'vibeic_receipt.json'
    if receipt.is_file():
        return _load(receipt).get('input', {}).get('step')
    config = folder / 'config.json'
    if config.is_file():
        return _load(config).get('meta', {}).get('step')
    return None


def post_pnr_timing_inputs(project: Path, state_path: Path, corner: str) -> dict:
    """The routed netlist, SDC, SPEF and cell libraries `OpenROAD.STAPostPNR`
    timed `corner` with, as project-relative paths.

    Netlist, SDC and SPEF come from the step's `state_out.json`; the SPEF is
    the one whose corner pattern matches `corner` (the same `fnmatch` rule
    LibreLane applies). The cell libraries are the ones the step's own
    `<corner>/sta.log` says it read. A corner the step did not analyse, an
    ambiguous or absent SPEF, or a view outside the project is refused.
    """
    folder = state_path.parent
    step = _state_step_id(folder)
    if step != 'OpenROAD.STAPostPNR':
        raise Refusal('LL_NOT_STAPOSTPNR', f'{folder}: written by {step}')
    state = _load(state_path)
    log = folder / corner / 'sta.log'
    if not log.is_file():
        analysed = sorted(d.name for d in folder.iterdir()
                          if (d / 'sta.log').is_file())
        raise Refusal('LL_CORNER_NOT_ANALYSED', f'{corner}: {analysed}')
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
    result: dict[str, Any] = {'step': step, 'corner': corner,
                              'liberties': libraries}
    for key, value in (('sta_netlist', state.get('nl')),
                       ('sdc', state.get('sdc')), ('spef', matched[0]),
                       ('state', str(state_path))):
        path = Path(value or '')
        if not value or not path.is_file():
            raise Refusal('LL_STATE_FILE_MISSING',
                          f'{key}: no file at path {value!r}')
        if not path.resolve().is_relative_to(root):
            raise Refusal('LL_STATE_OUTSIDE_PROJECT', f'{key}: {value}')
        result[key] = str(path.resolve().relative_to(root))
    result['sha256'] = {key: digest(root / result[key])
                        for key in ('sta_netlist', 'sdc', 'spef', 'state')}
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
              'source': str(folder / 'state_out.json'),
              'sha256': {'state_out.json': digest(folder / 'state_out.json')}}
    for name in ('metrics.json',):
        if (folder / name).exists():
            result['sha256'][name] = digest(folder / name)
    reports = {}
    for name in required_reports or []:
        path = folder / name
        if path.is_file():
            reports[name] = {'status': 'PRESENT', 'sha256': digest(path)}
            result['sha256'][name] = reports[name]['sha256']
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
