"""Bounded original component evidence, never full-row tool qualification."""

from _hostpaths import require_repo


















def test_real_flow_contract_requires_executed_rewrite_rom_and_hygiene():
    path = require_repo('vibe-ic-marketplace', 'plugins', 'vibe-ic', 'flow', 'phase1_phase2_phase3.yaml')
    import yaml
    doc = yaml.safe_load(path.read_text())
    # Consume the checked-in contract, not a second handwritten requirement list.
    steps = doc['flow']['steps'] if 'flow' in doc else doc['steps']
    row = next(s for s in steps if str(s['id']) == '2')
    commands = [r.get('program_exit_zero', '') for r in row['input_contracts']['original']['gate']['all_of']]
    assert all(any(name in command for command in commands) for name in
        ('crosslayer_rewrite_equivalence_check', 'rtl_hygiene_lint', 'rom_init_lint'))
