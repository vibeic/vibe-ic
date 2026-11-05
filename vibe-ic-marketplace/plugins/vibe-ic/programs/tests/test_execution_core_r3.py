"""Public reverse controls for exact R2 findings; no production test issuer."""
from dataclasses import replace

from programs.tests import test_execution_modes as H




def test_same_engine_source_with_different_argv_and_aliases_is_one_arm(tmp_path):
    first = H.adapter('a', cost=9)
    second = replace(first, arm_id='b', tool_id='invented', tool_version='other',
                     engine_families=('different',), components=tuple(
                         replace(c, argv=(*c.argv[:-1], '1')) for c in first.components))
    plan = H.controller(first, second).plan(H.context(tmp_path), 'ultra-mode')
    assert plan['arms'] == ['a']
    assert plan['portfolio'][1]['admission'] == 'SAME_ENGINE_FAMILY'
