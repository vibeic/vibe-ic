import hashlib
import json

import pytest
import foundry_handoff_pack_gen as release


def test_one_owner_input_approves_the_exact_final_gds(tmp_path):
    gds = tmp_path / 'final.gds'
    gds.write_bytes(b'original final GDS')
    approval = {'approved': True, 'approved_by': 'Accountable owner',
                'gds': 'final.gds', 'gds_sha256': hashlib.sha256(gds.read_bytes()).hexdigest()}
    path = tmp_path / release.RELEASE_APPROVAL_REL
    path.parent.mkdir()
    path.write_text(json.dumps(approval))
    assert release.read_release_approval(tmp_path, gds) == approval
    assert release.RELEASE_APPROVAL_REL == 'input/release_approval.json'
    gds.write_bytes(b'new release bytes')
    with pytest.raises(ValueError, match='final GDS bytes'):
        release.read_release_approval(tmp_path, gds)
