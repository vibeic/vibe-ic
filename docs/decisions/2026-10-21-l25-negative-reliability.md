## Layer Contract Decision — explicit negative reliability status and obligations

Producing layer: L25 (`L25_RELIABILITY_MISSION_PROFILE.json` key paths `fields.qualification_status` and `fields.unmeasured_obligations`)
Consuming layer: L25 (`L25_RELIABILITY_MISSION_PROFILE.json` reliability envelope contract)
Consumer program: `programs/l25_reliability_envelope_actionable_check.py` — dereferences every populated L25 field and independently reads its cited input literal
Boundary class: structural
Declarative alignment: n/a — these are flow qualification states and named reliability obligations, outside IP-XACT and SystemRDL register/component semantics
Actionable form required: a closed negative status token plus an enumerable obligation token, each bound to an unchanged project-relative source literal; numerical envelope and margin fields remain null without number-and-unit input
Bucket A (program): word-bounded negative qualification and unmeasured-obligation clauses are deterministic source extraction; no implementation synthesis or LLM judgement is needed
evidence: vibeic/vibe-ic#3408; v1.30.61 `phase1_post_process._LAYER_EXTRACTORS` has no L25 producer, while the fixed-image P0 record reports `l25_reliability_envelope_actionable_check=INCOMPLETE` over an applicable all-null L25

The producer writes L25 fields that the gate reads, so independence comes from the gate re-reading the cited literal from the unchanged input document. A missing, moved, or altered literal remains a consumer failure; producer output cannot certify itself.

**Verdict**: DEFECT_CONSUMING_LAYER

Next: /vibe-ic-phase1

