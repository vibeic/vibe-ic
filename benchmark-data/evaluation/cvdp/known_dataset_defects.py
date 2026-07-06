"""known_dataset_defects.py — CVDP upstream dataset-defect registry (waiver).

Mirrors the RTLLM precedent (benchmark-data/evaluation/rtllm/score_rtllm.py
KNOWN_DATASET_DEFECTS): a git-tracked, by-problem-id list of CVDP problems whose
prompt/given-context contradicts its own hidden oracle, so NO §4.05-blind author can
recover them without peeking (= cheating). These are benchmark-dataset defects, NOT
vibe-ic plugin gaps. Durable rationale lives in the matching ORGANIC backlog entries.

Keyed by CVDP problem id (a benchmark record id, NOT a chip / vendor / SKU — so this
is a legitimate scoring annotation, not chip-detection logic). A per-run passrate.py
imports this and excludes these ids from the "recoverable-via-plugin-fix" denominator,
so a fail on one is never re-diagnosed as a fresh plugin gap.

Usage:
    from known_dataset_defects import KNOWN_DATASET_DEFECTS, is_known_defect
    if is_known_defect(problem_id): ...   # exclude from the recoverable stat
"""

KNOWN_DATASET_DEFECTS = {
    "cvdp_copilot_skid_buffer_0001":
        "prompt template names top-level ports data_i/valid_i, but the hidden cocotb "
        "TB and the golden reference RTL both use i_data/i_valid — the prompt "
        "contradicts its own oracle. "
        "(ORGANIC-20260704-cvdp-skid-buffer-prompt-oracle-port-name-contradiction)",
    "cvdp_copilot_hebbian_rule_0012":
        "TB pins opcode 2'b10=NAND / 2'b11=NOR, but the only given mapping is the "
        "opposite and NAND/NOR are never mentioned in the prompt — the harness "
        "contradicts the given context itself. "
        "(ORGANIC-20260704-floor-record-harness-contradicts-given-context)",
}


def is_known_defect(problem_id: str) -> bool:
    """True iff problem_id is a registered upstream dataset defect (exclude from the
    recoverable-via-plugin-fix denominator)."""
    return problem_id in KNOWN_DATASET_DEFECTS
