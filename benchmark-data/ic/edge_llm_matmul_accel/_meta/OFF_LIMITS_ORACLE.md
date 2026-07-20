# §4.05 OFF-LIMITS for the blind forward run

The forward "plain-language → IC" run MUST NOT read ANY of the original
edge_llm_accel authoring artifacts. These are the ORACLE/answer and reading them
turns the experiment into copying:

FORBIDDEN (do not open, grep, cat, or reference):
  benchmark-data/ic/edge_llm_accel/input/docs/L*.md        (original L1-L9 docs)
  benchmark-data/ic/edge_llm_accel/phase2/**               (original RTL)
  benchmark-data/ic/edge_llm_accel/steps/**                (original RTL)
  benchmark-data/ic/edge_llm_accel/verify/**               (V1/V2 golden TBs, mapping)
  benchmark-data/ic/edge_llm_accel/plugin_output/declaration.json  (R3 choices)
  benchmark-data/ic/edge_llm_accel/**/VERDICT.md, RESULT.md, SOURCE_MANIFEST.md

ALLOWED:
  - this sandbox dir only:  _experiments/edge_llm_accel_vibe_forward/**
  - the plugin programs/skills/agents (the general tool)
  - general public knowledge / expert judgement

The ONLY sanctioned use of the original verify/ golden is the FINAL cross-check
stage, run by the orchestrator AFTER authoring is frozen — never during authoring.
