"""SOURCE_ONLY native neutral controls; no ADC, PVT population or row qualification.

The scalar fixture runs the existing nominal producer and normal completion.
PVT parser cases explicitly use a partial native-format source fixture: they
exercise refusals, never attest an executed PVT population.
"""
import json

from _hostpaths import require_repo


































def test_real_registry_obligations_are_the_owned_two_consumers():
    # Actual repository artifact, not a parallel registry or an edited row.
    registry = json.loads(require_repo('vibe-ic-marketplace/plugins/vibe-ic/flow/flow109.json').read_text())
    rows = {r['position']: r for r in registry['rows']}
    assert [o['metric'] for o in rows[15]['obligations']] == ['nominal_performance', 'early_model_correlation']
    assert [o['metric'] for o in rows[28]['obligations']] == ['pvt_load_modes', 'prelayout_performance']
