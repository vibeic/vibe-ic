"""Tests for llm_semantic_confirm.py — the LLM double-confirm of program-extracted
semantic spec fields. A fake client exercises the confirm path deterministically and
offline (no real API call)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
import llm_semantic_confirm as lc          # noqa: E402
import _specrtl_common as c                 # noqa: E402


class _Blk:
    def __init__(self, t):
        self.text, self.type = t, "text"


class _Msg:
    def __init__(self, t):
        self.content = [_Blk(t)]


def _factory(reply):
    class Client:
        @property
        def messages(self):
            class M:
                def create(self, **kw):
                    return _Msg(reply)
            return M()
    return lambda: Client()


def test_offline_is_noop_unconfirmed(monkeypatch):
    # No backend → candidate preserved, marked unconfirmed (not silently trusted).
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    conf = lc.confirm_semantic("fsm_output_style", "moore", "Implement a Moore machine.")
    assert conf.value == "moore"
    assert conf.confirmed is False
    assert conf.source == "unconfirmed-no-backend"


def test_llm_agrees_keeps_value():
    conf = lc.confirm_semantic(
        "fsm_output_style", "moore", "Moore state machine.",
        client_factory=_factory('{"value":"moore","agree":true,"reason":"ok"}'))
    assert conf.confirmed and conf.agree and conf.value == "moore"
    assert conf.source == "llm"


def test_llm_corrects_value():
    conf = lc.confirm_semantic(
        "reset_mode", "synchronous", "reset is asserted asynchronously",
        client_factory=_factory('{"value":"asynchronous","agree":false,"reason":"async"}'))
    assert conf.confirmed and conf.agree is False
    assert conf.value == "asynchronous"          # LLM correction adopted


def test_out_of_range_llm_value_rejected():
    conf = lc.confirm_semantic(
        "fsm_output_style", "moore", "...",
        client_factory=_factory('{"value":"banana","agree":false,"reason":"x"}'))
    assert conf.confirmed is False               # bogus value not trusted
    assert conf.value == "moore"                 # falls back to candidate


def test_confirm_contract_adopts_correction_in_extract():
    spec = ("Implement a Moore state machine.\n - input clk\n - input x\n - output z\n"
            "Active-high synchronous reset.")
    fac = _factory('{"value":"mealy","agree":false,"reason":"output uses input"}')
    contract = c.extract_spec_contract(spec, confirm=True, client_factory=fac)
    assert contract.fsm_output_style == "mealy"  # parser said moore; LLM overrode
    fields = {d["field"] for d in contract.semantic_confirmations}
    assert "fsm_output_style" in fields


def test_json_contract_not_confirmed():
    # JSON is authoritative structured input — never sent for semantic confirmation.
    spec = '{"module":"m","ports":[],"reset":{"mode":"synchronous"}}'
    contract = c.extract_spec_contract(spec, is_json=True)
    assert contract.semantic_confirmations == []
    assert contract.reset_mode == "synchronous"


def test_existing_ai_review_fills_same_obligation_field_on_deterministic_miss():
    import json
    from dataclasses import asdict
    import spec_artifact_registry as registry

    sentence = 'Use the negated-conjunction building blocks, with all other elements excluded.'
    prefix = 'Implement a module named neutral.\n'
    text = prefix + sentence
    before = c.extract_spec_contract(text, confirm=False)
    assert not getattr(before, 'logic_obligations', [])
    row = {'kind': 'logic_basis', 'family': ['nand'],
           'source_span': [len(prefix), len(text)], 'source_sentence': sentence}
    contract = c.extract_spec_contract(text, confirm=True, client_factory=_factory(json.dumps({
        'value': [row], 'agree': False, 'reason': 'exclusive negated conjunction basis'})))
    observed = [r.family for r in getattr(contract, 'logic_obligations', [])]
    assert observed == [('nand',)], contract
    confirmation = next(r for r in contract.semantic_confirmations if r['field'] == 'logic_obligations')
    assert confirmation['confirmed'] and confirmation['source'] == 'llm'
    assert registry.generate(text, 'neutral', contract=contract) == (None, None)
    projected = c.extract_spec_contract(json.dumps(asdict(contract)), is_json=True)
    assert projected.logic_obligations == contract.logic_obligations


def test_ai_obligation_review_sees_full_source_and_can_clear_a_candidate():
    import json

    text = ('Source background. ' * 80) + 'Use NAND gates exclusively.'
    prompts = []
    class Client:
        @property
        def messages(self):
            class Messages:
                def create(self, **kwargs):
                    prompts.append(kwargs['messages'][0]['content'])
                    return _Msg(json.dumps({'value': [], 'agree': False, 'reason': 'withdrawn by review'}))
            return Messages()
    contract = c.extract_spec_contract(text, confirm=True, client_factory=Client)
    assert prompts and text in prompts[-1]
    assert getattr(contract, 'logic_obligations', None) == []


def test_malformed_ai_obligation_span_cannot_replace_a_detected_requirement():
    import json

    text = 'The implementation must be NAND-only.'
    row = {'kind': 'logic_basis', 'family': ['nand'],
           'source_span': [0, 5000], 'source_sentence': text}
    contract = c.extract_spec_contract(text, confirm=True, client_factory=_factory(json.dumps({
        'value': [row], 'agree': False, 'reason': 'invalid source slice'})))
    rows = getattr(contract, 'logic_obligations', [])
    assert rows and rows[0].family == ('nand',)
    confirmation = next(r for r in contract.semantic_confirmations if r['field'] == 'logic_obligations')
    assert confirmation['confirmed'] is False
    assert confirmation['source'] == 'error'


def test_ai_source_offsets_use_the_untrimmed_spec():
    import json

    text = '\n  Use the negated-conjunction building blocks, with all other elements excluded.\n'
    prompts = []
    row = {'kind': 'logic_basis', 'family': ['nand'],
           'source_span': [0, len(text)], 'source_sentence': text}
    class Client:
        @property
        def messages(self):
            class Messages:
                def create(self, **kwargs):
                    prompts.append(kwargs['messages'][0]['content'])
                    return _Msg(json.dumps({'value': [row], 'agree': False, 'reason': 'declared basis'}))
            return Messages()
    contract = c.extract_spec_contract(text, confirm=True, client_factory=Client)
    assert '\"\"\"\n' + text + '\n\"\"\"' in prompts[-1]
    assert contract.logic_obligations[0].source_span == (0, len(text))
