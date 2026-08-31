"""Issue #1971: Markdown headings inside fenced code are not structure."""

import sys
from pathlib import Path


PROGRAMS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROGRAMS))

import acceptance_evidence_in_fix_comment_check as acceptance  # noqa: E402
import organic_issue_body_lint as organic_lint  # noqa: E402


def test_acceptance_fence_shell_comment_does_not_truncate_section():
    body = """## 驗收

```bash
# comment line
echo hi
```

## 後續
not part of acceptance
"""

    section = acceptance.extract_acceptance_section(body)
    assert section == "```bash\n# comment line\necho hi\n```"

    commands, _criteria = acceptance.extract_commands(section)
    assert "echo hi" in commands


def test_acceptance_heading_inside_fence_is_ignored():
    body = """## Example

```markdown
## Acceptance
python3 programs/not_binding.py
```

## Acceptance

```bash
python3 programs/binding.py
```
"""

    section = acceptance.extract_acceptance_section(body)
    commands, _criteria = acceptance.extract_commands(section)
    assert commands == ["python3 programs/binding.py"]


def test_acceptance_fence_reaches_organic_lint_without_narrative_warning():
    body = """## Evidence

Defect artifact: programs/example.py

## Acceptance

```bash
# explain the check
python3 programs/example.py
```
"""

    rules = {finding["rule"] for finding in organic_lint.lint(body)}
    assert "ACCEPTANCE_NARRATIVE_ONLY" not in rules
