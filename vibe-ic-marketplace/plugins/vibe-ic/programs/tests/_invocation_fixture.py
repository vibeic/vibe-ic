from pathlib import Path

import pytest

import execution_policy


@pytest.fixture(autouse=True)
def preserve_invocation_runtime(monkeypatch):
    monkeypatch.setattr(execution_policy, '_ordinary_runtime',
                        execution_policy._ordinary_runtime)


def bind_invocation_top(project, top):
    previous = execution_policy._ordinary_runtime
    same_project = (previous is not None and
                    Path(previous['project']).resolve() == Path(project).resolve())
    runtime = dict(previous) if same_project else {'project': Path(project)}
    runtime['parameters'] = {**(runtime.get('parameters') or {}), 'top': top}
    execution_policy._ordinary_runtime = runtime
