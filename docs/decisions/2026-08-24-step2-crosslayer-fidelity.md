## Layer Contract Decision — cross-layer rewrite-fidelity flow ownership

Producing layer: n/a — not a layer fact; this is a repository flow-step ownership declaration.
Consuming layer: n/a — `flow_compliance_check.py` and `design_one_shot_runner.py` consume the flow declaration directly.
Consumer program: `programs/flow_compliance_check.py` and `programs/design_one_shot_runner.py` — they execute and enforce the Step-2 gate.
Boundary class: structural — the step owner, gate command, required output, dependency and fallback are closed enumerable YAML fields.
Declarative alignment: n/a — this is neither a register map nor an interface, memory map or hierarchy schema.
Actionable form required: one existing Step-2 declaration carrying the unconditional judge command, its required report, and fallback to Step 1.
Bucket A (program): the flow and runner wiring are deterministic repository structure; no synthesis or expert database is involved.
evidence: `flow/phase1_phase2_phase3.yaml` declares Step 2 as the first deterministic consumer of Step-1 RTL; `programs/design_one_shot_runner.py` invokes `step_crosslayer_rewrite_fidelity` before the remaining Step-2 checks.

**Verdict**: NOT_A_LAYER_FACT

The former Step 1.6x belongs inside Step 2. Step 1 is the irreducible authoring step and its fallback target; placing the judge there would make one step both author and reject its own output and would turn `fallback_to: 1` into a self-loop. Step 2 already consumes Step-1 RTL and already falls back to Step 1, so it owns rewrite fidelity without adding a 69th step.

Next: /vibe-ic-phase1
