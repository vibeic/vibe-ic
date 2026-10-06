"""Explicit enrollment seam for generated controller unit-test producers.

This does NOT qualify fixture files as runtime repository authority. Production
Registry.register tests must call that API directly. Only the Git enrollment of
files deliberately created beneath fixture_root is replaced here; invocation,
closure discovery, byte identity, execution and consumers remain production code.
"""
from dataclasses import replace
from pathlib import Path
from types import MappingProxyType
import json
import sys

import execution_modes as em


def register_source_fixture(registry, adapter, *, fixture_root):
    root = Path(fixture_root).resolve()
    paths = {Path(name).resolve() for name in adapter.source_files}
    interpreter = Path(sys.executable).resolve()
    generated = paths - {interpreter} - {
        p for p in paths if p.is_relative_to(em._REPO_ROOT)}
    if not generated:
        registry.register(adapter)
        return
    assert all(p.is_relative_to(root) for p in generated), generated
    assert adapter.arm_id not in registry._adapters
    em._verified_current_source_commit(adapter.source_sha)
    committed = paths - generated - {interpreter}
    blobs = em._git_source_blobs(adapter.source_sha, committed)
    for name, expected in adapter.source_files.items():
        path = Path(name)
        if path.is_symlink() or not path.is_file() or em.digest(path) != expected:
            raise em.Refusal('ADAPTER_SOURCE_MISMATCH', name)
    for path in committed:
        if blobs[str(path)] != em._blob_bytes(path):
            raise em.Refusal('SOURCE_AUTHORITY_DIRTY', str(path))
    missing = em._source_closure(adapter.source_files) - paths
    if missing:
        raise em.Refusal('ADAPTER_SOURCE_CLOSURE_INCOMPLETE', str(sorted(missing)[0]))
    invocations = {c.name: em._invocation_sources(c) for c in adapter.components}
    for invocation in invocations.values():
        for name, expected in invocation['argument_sources'].items():
            if adapter.source_files.get(name) != expected:
                raise em.Refusal('ENTRY_SOURCE_UNBOUND', name)
    # Keep immutable initial bytes for drift detection; these are explicitly
    # fixture snapshots, not claimed Git blobs for an untracked producer.
    blobs.update({str(p): em._blob_bytes(p) for p in generated})
    registry._adapters[adapter.arm_id] = replace(
        adapter, verified_source_blobs=MappingProxyType(blobs),
        executable_receipts=MappingProxyType({}),
        invocation_sources=MappingProxyType(invocations),
        source_files=MappingProxyType(dict(adapter.source_files)),
        engine_families=tuple(adapter.engine_families),
        components=tuple(adapter.components),
        required_outputs=tuple(adapter.required_outputs),
        objective=MappingProxyType(dict(adapter.objective)),
        output_contract=MappingProxyType({k: tuple(v) for k, v in adapter.output_contract.items()}),
        qualification_evidence='SOFTWARE_FIXTURE_ENROLLMENT_ONLY: ' + adapter.qualification_evidence,
    )


def issued_context(context, project, mode='ultra'):
    """Use the genuine canonical CLI capability; no fabricated route or issuer."""
    from programs.tests.test_execution_receipt_chain import real_entry
    import execution_policy as policy
    declaration = Path(project) / 'input/step_0_5ic_answers.json'
    delivery = json.loads(declaration.read_text()).get('answers', {}).get('deliverable') if declaration.is_file() else None
    path = 'IP' if delivery == 'HARDMACRO' else 'IC'
    payload = real_entry(path, mode, project)
    return replace(context, project_digest=payload['route']['project_digest'],
                   **policy.controller_fields(ic_ip_path=path, route_receipt=payload['route']))
