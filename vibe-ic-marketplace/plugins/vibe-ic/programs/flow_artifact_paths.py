from contextlib import contextmanager
from contextvars import ContextVar
from functools import wraps
from pathlib import Path
import re

GDS_SPEC = 'phase3/stage4/gds/*.gds'
_gate_parameters = ContextVar('flow_artifact_gate_parameters', default=None)


class OutputTopUnbound(ValueError):
    pass


@contextmanager
def gate_parameters(project, parameters):
    if parameters is None:
        yield
        return
    previous = current_parameters(project)
    if (previous is not None and 'top' in previous
            and parameters.get('top') != previous['top']):
        raise ValueError('OUTPUT_TOP_CONFLICT: nested invocation tops differ')
    token = _gate_parameters.set((Path(project).resolve(), parameters))
    try:
        yield
    finally:
        _gate_parameters.reset(token)


def with_top(function):
    @wraps(function)
    def invoke(project, top, *args, **kwargs):
        with gate_parameters(project, {'top': top}):
            return function(project, top, *args, **kwargs)
    return invoke


def current_parameters(project):
    project = Path(project).resolve()
    scoped = _gate_parameters.get()
    if scoped is not None and scoped[0] == project and scoped[1] is not None:
        return scoped[1]
    import execution_policy
    runtime = execution_policy._ordinary_runtime
    if runtime is not None and Path(runtime['project']).resolve() == project:
        return runtime.get('parameters')
    return None


def top_arguments(project):
    parameters = current_parameters(project)
    if parameters is None or 'top' not in parameters:
        return []
    resolve(project, GDS_SPEC, parameters)
    return ['--top', parameters['top']]


def resolve(project, pattern, parameters=None):
    if pattern != GDS_SPEC:
        return pattern
    import _flow_yaml
    row = next(row for row in _flow_yaml.load()['steps'] if str(row['id']) == '37')
    if row.get('required_output_selectors', {}).get(pattern) != 'invocation_top':
        raise ValueError('OUTPUT_TOP_SELECTOR_UNBOUND: ' + pattern)

    import execution_policy
    project = Path(project).resolve()
    sources = []
    if parameters is not None:
        sources.append(parameters)
    scoped = _gate_parameters.get()
    if scoped is not None and scoped[0] == project and scoped[1] is not None:
        sources.append(scoped[1])
    runtime = execution_policy._ordinary_runtime
    if runtime is not None and Path(runtime['project']).resolve() == project:
        sources.append(runtime.get('parameters', {}))
    tops = [source.get('top') for source in sources]
    if not tops or any(not isinstance(top, str) or not re.fullmatch(
            r'[A-Za-z_][A-Za-z0-9_$.-]*', top) for top in tops):
        raise OutputTopUnbound('OUTPUT_TOP_UNBOUND: typed invocation top is absent or unsafe')
    if len(set(tops)) != 1:
        raise ValueError('OUTPUT_TOP_CONFLICT: invocation and project tops differ')
    return str(Path(pattern).with_name(tops[0] + '.gds'))
