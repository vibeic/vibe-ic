"""SOFTWARE controls over the shipped dispatcher/public manifest boundary.

Neutral visible task only; no dataset, RTL answer, hidden harness, native
qualification, score or fabricated semantic route approval.
"""

import pytest
import benchmark_dispatch as dispatch
































def test_unapproved_route_still_refuses_before_any_runner(tmp_path):
    with pytest.raises(ValueError):
        dispatch._require_route_admission(tmp_path,{}, {},require_d1=False)
    assert not (tmp_path/'runner_invocation.json').exists()
