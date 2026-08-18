"""tests/test_compliance.py — phase1-coverage-loop skill compliance.

Placeholder gate added in v1.6.270 so the universal
`TestEndToEndAllSkills::test_every_skill_has_test_file` integration
gate passes for this skill. The phase1-coverage-loop compliance
rules live in `../compliance.yaml`; this stub validates that the
YAML loads and carries the canonical top-level `skill:` field.
"""
from __future__ import annotations

from pathlib import Path

try:
    import yaml
except ImportError:  # pragma: no cover - PyYAML always available in CI
    yaml = None

_HERE = Path(__file__).resolve()
_COMPLIANCE_YAML = _HERE.parents[1] / "compliance.yaml"


def test_phase1_coverage_loop_compliance_yaml_loads() -> None:
    """compliance.yaml must exist and parse cleanly."""
    assert _COMPLIANCE_YAML.exists(), (
        f"compliance.yaml missing at {_COMPLIANCE_YAML}"
    )
    if yaml is None:
        return
    data = yaml.safe_load(_COMPLIANCE_YAML.read_text())
    assert isinstance(data, dict), (
        f"compliance.yaml must be a top-level mapping, got "
        f"{type(data).__name__}"
    )
    assert data.get("skill") == "phase1-coverage-loop", (
        f"compliance.yaml must declare skill: phase1-coverage-loop; "
        f"got {data.get('skill')!r}"
    )
