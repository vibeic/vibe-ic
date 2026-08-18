"""Layer 2 of the v0.50 testing strategy (_shared/TESTING_STRATEGY.md).

Parametric test across every compliance.yaml in plugins/vibe-ic/skills/:

  For each requirement with a `pattern`:
    (a) assert the regex compiles
    (b) if positive_sample provided: assert pattern matches it
    (c) if negative_sample provided: assert pattern does NOT match it

Unlike the auto-generated `test_good_output_passes_all_required` (Layer 3),
this test does NOT try to synthesise a full markdown document; it only
verifies the regex itself behaves as the author intended. This decouples
fixture quality from compliance-engine correctness.

Authors add samples inline in the yaml:

    - id: R_has_output_section
      description: "Output format/schema section present"
      pattern: '(##\\s+(?:Output|Findings|Result|Report))'
      positive_sample: "## Output format"
      negative_sample: "# Not an h2"
"""
from __future__ import annotations
import re
import pytest
from pathlib import Path

try:
    import yaml
except ImportError as e:
    pytest.skip(f"PyYAML required: {e}", allow_module_level=True)


SKILLS_ROOT = Path(__file__).resolve().parent.parent / "skills"


def _load_yaml(path: Path) -> dict:
    with path.open() as f:
        return yaml.safe_load(f) or {}


def _collect_patterns():
    """Yield (skill_name, requirement_id, pattern, pos_sample, neg_sample)."""
    for yml in sorted(SKILLS_ROOT.glob("*/compliance.yaml")):
        skill = yml.parent.name
        data = _load_yaml(yml)
        for section in ("requirements", "cross_checks", "postchecks"):
            for req in data.get(section) or []:
                if not isinstance(req, dict):
                    continue
                pat = req.get("pattern")
                if not pat:
                    continue
                yield (
                    skill,
                    req.get("id", "?"),
                    pat,
                    req.get("positive_sample"),
                    req.get("negative_sample"),
                )


_ALL = list(_collect_patterns())


@pytest.mark.parametrize("skill,req_id,pattern,pos,neg",
                         _ALL,
                         ids=[f"{s}:{r}" for s, r, _, _, _ in _ALL])
def test_pattern_compiles_and_matches(skill, req_id, pattern, pos, neg):
    # (a) regex must compile
    try:
        rx = re.compile(pattern, re.MULTILINE | re.DOTALL)
    except re.error as e:
        pytest.fail(f"{skill}:{req_id}: pattern `{pattern}` failed to compile: {e}")

    # (b) positive sample if provided
    if pos is not None:
        assert rx.search(pos), (
            f"{skill}:{req_id}: pattern `{pattern}` did NOT match its "
            f"positive_sample `{pos[:80]}`")

    # (c) negative sample if provided
    if neg is not None:
        assert not rx.search(neg), (
            f"{skill}:{req_id}: pattern `{pattern}` unexpectedly matched its "
            f"negative_sample `{neg[:80]}`")
