r"""ORGANIC #606 [MEDIUM] — the L6 FSM state-to-state prose walker used a bare
`\s+to\s+` alternation as a transition operator, gated only by a ±300-char
"state machine"/"FSM" anchor window. Data-movement sentences in architecture
docs ("write/move/copy <data-noun> to <ADDR_*/REG_NAME>") then promoted BOTH
the data noun (e.g. `block`, via the trusted "state-to-state" label that
bypasses the UPPER_SNAKE shape guard) AND the address-map/register identifier
(e.g. `ADDR_BLOCK0`) as bogus FSM states.

Real on-disk evidence (a register-mapped crypto accelerator IC,
L6_CONTROL_LOGIC.json): fsm_states = [{"name":"BLOCK"},{"name":"ADDR_BLOCK0"}],
both from `l6_fsm_prose_walker_v1_6_484`, sourced from L2_architecture.md line
"1. SW write 512-bit block to ADDR_BLOCK0..15(16 個 32-bit register)" with the
only "state machine" mention ("內部 state machine 歸 idle") within ±300 chars.

Fix (chip-AGNOSTIC, no-leak — withOUT removing the R9 trusted state-to-state
label, which would regress legit lowercase ARROW states like `running`):
  (1) a data-movement-verb guard: a BARE-WORD `to` preceded by a data-movement
      verb (write/read/move/copy/store/load/send/fetch/transfer/push/pop) is a
      dataflow clause, not an FSM transition → skip the whole match. Arrow
      operators (-> / → / =>) are never gated.
  (2) a register/address-map token rejector (`^ADDR[_0-9]|_ADDR$|^REG_|_REG$|
      _REGISTER$|^OFFSET_`) applied on EVERY walker path — a register name
      never names a real FSM state.

POSITIVE: the real dataflow line yields ZERO fsm_states.
NEGATIVE no-leak: a real FSM transition (`IDLE -> BUSY`, or bare `IDLE to
ACTIVE` with no movement verb) is still captured; lowercase arrow states
(`running` -> `halted`, the R9 case) are never gated.
"""
import json
import sys
import tempfile
from pathlib import Path

PLUGIN = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PLUGIN / "programs"))
import phase1_doc_one_shot_runner as P  # noqa: E402

# Real #606 L2 prose, embedding the discriminating dataflow line VERBATIM.
REAL_L2 = (
    "# L2 Architecture\n\n## Control\n"
    "內部 state machine 歸 idle 後開始接收。\n資料流程:\n"
    "1. SW write 512-bit block to ADDR_BLOCK0..15(16 個 32-bit register)\n"
    "2. read result from STATUS_REG when done.\n"
    "## FSM\nThe control FSM transitions `IDLE` -> `BUSY` -> `DONE`.\n"
)


def test_regmap_name_rejector():
    rej = P._V1_6_606_REGMAP_NAME_RE.search
    for n in ("ADDR_BLOCK0", "ADDR_0", "CTRL_REG", "REG_STATUS", "STATUS_REG",
              "DATA_REGISTER", "OFFSET_BASE"):
        assert rej(n), f"{n} is a register/address-map id, not an FSM state"
    for n in ("IDLE", "BUSY", "DONE", "FETCH", "DECODE", "S_INIT", "RUN"):
        assert not rej(n), f"{n} is a legitimate FSM-state name"


def test_data_movement_to_guard():
    RE = P._V1_6_484_FSM_STATE_TO_STATE_RE
    line = "1. SW write 512-bit block to ADDR_BLOCK0..15(16 個 32-bit register)"
    ms = list(RE.finditer(line))
    assert ms and all(P._v1_6_606_is_data_movement_to(line, m) for m in ms)
    # bare `to` with NO movement verb → a real FSM transition, NOT gated
    ok = "The FSM goes IDLE to ACTIVE on start."
    assert all(not P._v1_6_606_is_data_movement_to(ok, m)
               for m in RE.finditer(ok))
    # arrow notation is never gated (R9 lowercase states)
    arr = "`running` -> `halted`"
    assert all(not P._v1_6_606_is_data_movement_to(arr, m)
               for m in RE.finditer(arr))


def _l6_states(l2_text):
    proj = Path(tempfile.mkdtemp())
    (proj / "phase1" / "generated_docs").mkdir(parents=True)
    res = P.gen_l6_control_logic(proj, {"L2_architecture.md": l2_text})
    data = json.loads(Path(res.path).read_text())
    states = data.get("fsm_states") or data.get("states") or []
    return sorted(s.get("name") for s in states if isinstance(s, dict))


def test_e2e_no_register_or_data_noun_leak():
    names = _l6_states(REAL_L2)
    for bogus in ("BLOCK", "ADDR_BLOCK0", "STATUS_REG"):
        assert bogus not in names, f"{bogus} must not be an FSM state (#606)"


def test_e2e_real_fsm_still_captured():
    # NO-LEAK: the genuine arrow-transition states survive the fix.
    names = _l6_states(REAL_L2)
    assert {"IDLE", "BUSY"} <= set(names), names
