"""R5 controls exercise the tracked providers and actual emitted run records."""
from dataclasses import replace
import json

from programs.tests import test_execution_modes as H
from programs.tests.test_execution_core_r4 import issued_context




def test_interpreter_options_preserve_distinct_actual_entries(tmp_path):
    ctx = issued_context(tmp_path)
    first, second = H.adapter('a'), H.adapter('b')
    second_entry = second.components[0].argv[1]
    second = replace(second, components=tuple(
        replace(c, argv=(c.argv[0], '-B', '-Wignore', *c.argv[1:]))
        for c in second.components))
    controller = H.controller(first, second)
    root = tmp_path / 'run'
    result = controller.run(ctx, root)
    plan = json.loads((root / 'plan.json').read_text())
    assert plan['arms'] == ['a', 'b']
    assert result['candidate_statuses'] == {'a': 'ELIGIBLE', 'b': 'ELIGIBLE'}
    assert {r['invocation_sources']['transform']['entry'] for r in plan['portfolio']} == {
        first.components[0].argv[1], second_entry}
    assert controller.adopt(ctx, root, H.choice(ctx, root))['status'] == 'ADOPTED'
    assert controller.verify_adoption(ctx, root)['status'] == 'ADOPTED'
