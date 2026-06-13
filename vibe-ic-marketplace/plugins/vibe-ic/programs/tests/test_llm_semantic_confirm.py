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
