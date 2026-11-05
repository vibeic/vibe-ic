"""D12 actual public route with explicitly isolated upstream admission/child process.

The child invokes the real retained metric/owner/canonical writer in process.
SOFTWARE per-use qualification comes from the adjacent source fixture; these
controls establish routing/publication behavior, not native or product PASS.
"""
import json
import sys

from test_flow109_d12_metric_binding import case
from test_flow109_selection import _public_d09_entry


def setup_public(p, context, monkeypatch, *, named=True):
    runner = _public_d09_entry(p, monkeypatch)
    manifest = p / 'manifest.json'
    body = {'features': context['features']}
    for key in ('runtime_tool_uses', 'qualification_registry'):
        if context.get(key) is not None: body[key] = context[key]
    manifest.write_text(json.dumps(body))
    argv = list(sys.argv)
    for flag in ('--entry-step', '--exit-step'):
        argv[argv.index(flag) + 1] = 'D12' if named else '3'
    monkeypatch.setattr(sys, 'argv', argv)
    return runner




def test_d12_unsupported_legacy_entry_still_refuses(case, monkeypatch, capsys):
    p, context = case
    runner = setup_public(p, context, monkeypatch, named=False)
    issued = []
    monkeypatch.setattr(runner.subprocess, 'run', lambda *a, **kw: issued.append(a))
    assert runner._main() == 2
    assert issued == []
    assert "FLOW109_STEP_NOT_SELECTED: 3" in capsys.readouterr().err
