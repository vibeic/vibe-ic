# Producer advisory for an unfilled reference model

The professional testbench producer exposes `reference_model_handoff`, naming
its existing persistent `expert_reference_tb.py` input and the `testbench-gen`
skill. This metadata advises the caller where a missing model belongs. It does
not issue a coordinator completion task or grant acceptance.

The IC expert derives the model independently from the visible contract. The
ordinary native simulation result, substantive wrong-behavior controls and a
fresh independent review determine whether the verification is sufficient.
An unfilled hook remains unmeasured. The original RTL and failed measurements
stay preserved.

There is no separate model-author record, parent/source/model binding chain,
restricted model language or model archive admission gate. Attribution belongs
in the existing producer/task records.

Earlier bounded model experiments are component evidence only. Canonical
verification, whole-flow acceptance and official benchmark scoring remain
unestablished.
