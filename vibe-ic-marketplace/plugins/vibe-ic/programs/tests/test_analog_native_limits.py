"""Native analog measurements retain their declared engineering bounds."""
import json

import pytest

import analog_native_flow as native
import analog_pdk_availability as pdks


@pytest.mark.parametrize("length,count,expected", [
    (9, 0, "PASS"), (10, 0, "PASS"), (10.01, 0, "FAIL"),
    (9, 1, "FAIL"), (None, 0, "NOT_MEASURED"),
])
def test_top_native_values_against_original_limit(tmp_path, length, count, expected):
    limits = tmp_path / "requirements/analog_top_route/analog_sensitive_route_constraints.json"
    limits.parent.mkdir(parents=True)
    limits.write_text(json.dumps({"limits": {"sense": {"max": 10}},
                                  "units": {"sense": "um"}}))
    report = native._a18_metrics(tmp_path, {
        "checks": {"analog_top_pad_core_connectivity_errors": count},
        "route_measurements": [{"net": "sense", "length_um": length}],
    })
    assert report["status"] == expected
    assert json.loads(limits.read_text())["limits"]["sense"]["max"] == 10


def test_local_pdk_uses_native_environment_without_attestation(tmp_path, monkeypatch):
    monkeypatch.setenv("PDK_ROOT", str(tmp_path))
    monkeypatch.delenv("VIBEIC_LIBRELANE_LOCAL_ATTESTATION", raising=False)
    assert pdks.local_pdks_root() == str(tmp_path)
    monkeypatch.setenv("PDK_ROOT", str(tmp_path / "absent"))
    assert pdks.local_pdks_root() is None
