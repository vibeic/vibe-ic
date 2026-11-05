"""Exercise source-owned selection through the canonical front door.

These are configuration/dispatch tests, not EDA qualification or IC PASS.
"""
from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from programs.tests._hostpaths import require_repo












































































def test_obsolete_explicit_public_flow_refuses_before_project_access(tmp_path):
    runner = require_repo("vibe-ic-marketplace", "plugins", "vibe-ic",
                          "programs", "vibe_ic_one_shot_runner.py")
    absent = tmp_path / "does-not-exist"
    result = subprocess.run(
        [sys.executable, str(runner), str(absent), "--flow", "70"],
        text=True, capture_output=True)
    assert result.returncode == 2
    assert "invalid choice: '70'" in result.stderr
    assert not absent.exists()

















































































# Native completion is an owner answer, separate from whole-flow acceptance.





















































def test_dft_vocabulary_canonical_named_intent_rejects_legacy_key(tmp_path):
    import spec_declaration_emit as declaration
    import fault_scan_chain_insert as producer
    docs = tmp_path / 'input/docs'
    docs.mkdir(parents=True)
    (docs / 'L7_verification_plan.md').write_text(
        '# Verification\nThe Plugin MUST declare `plugin_output/dft_intent.json` '
        'before authoring:\n\n| Field | Required | Example |\n|---|---|---|\n'
        '| `dft` | Yes | object |\n')
    intent = {'scan_test': False, 'requires_scan': False, 'reason': 'no scan required'}
    assert declaration.main([str(tmp_path), '--set', 'dft=' + json.dumps(intent)]) == 0
    assert (tmp_path / 'plugin_output/dft_intent.json').is_file()
    binding, problems = producer.load_d09_dft_contract(tmp_path)
    assert binding is None and 'DFT_INTENT_SCHEMA_INVALID' in str(problems)
