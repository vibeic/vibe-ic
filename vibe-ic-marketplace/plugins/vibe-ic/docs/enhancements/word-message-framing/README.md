# Source-bound fixed-length word framing

This local capture extends the existing serial protocol producer and waveform
checker. It is a deterministic plugin enhancement, with bounded independent review completed and
runtime composition still pending. It makes no official benchmark score claim.

`serial_protocol_fsm_synth.synth` and the ordinary
`spec_artifact_registry.generate` consumer accept a closed word-message contract:
one clock, one reset, one input word, a packed output message and a completion
flag. The public header supplies literal descending, zero-based widths. The
source supplies the fixed word count, first-word marker bit and level, packing
order, sampling edge, reset polarity/type, and completion one cycle after the
last accepted word. The implementation uses separate pending-message and output
registers so a new first word can be accepted while the previous message is
reported. Reset clears partial framing, pending completion and completion state.

The supported bounds are 2–64 bits per word and 2–16 words per message. The
first two packed slices establish order; every further stated slice must agree.
A complete design document can omit a waveform when edge, one-cycle pulse and
reporting-cycle acceptance are explicit. A supplied waveform must agree with
the parsed contract. It may establish the sampling edge and concurrent intake
only when its observations distinguish those choices. Unsupported interfaces,
unresolved choices and recognized contradictory facts return the existing
`None` result for normal fallback. This is a closed grammar, not a universal
natural-language parser or a per-protocol implementation lookup.

`waveform_table_conformance_check` adds a separate replay envelope for the same
public interface shape. All columns must bind declared ports, with only unique
clock/reset role aliases allowed. Public widths, radix, reset and valid-qualified
data semantics are required. Hexadecimal, decimal, binary, sized literals and
explicit radix prefixes are decoded without treating a printed word as a scalar.
The table must show regular alternating clock observations and stable inputs and
outputs over each active-edge half-cycle. Inputs are set up before the bound
edge; both completion and valid packed data are compared after settling, at
every supplied observation. Invalid packed data are unconstrained. Unknown DUT
values fail a concrete source comparison.

Ambiguous radix, unknown accepted inputs, incomplete or irregular observations,
unsupported roles and unstable half-cycles remain `WTC_SKIP_*`. The existing
single-output envelopes and their input scheduling remain unchanged. No-tool
and compilation dispositions also retain their existing distinct outcomes.

The owning tests use invented public documents and an independent word-list
model. They vary width, count, marker level/location, packing order, port names,
clock edge, reset polarity/type and role aliases. They exercise uninterrupted
back-to-back frames and reset at every partial/pending position. Executable
negative RTL controls cover early or stale completion, swapped words, data
clobbered by concurrent intake, lost reporting-cycle input and omitted reset.
Unsupported/conflicting specifications must decline or skip without PASS.

The external local evidence packet retains pre-edit producer/registry refusal,
checker SKIP, matched base/candidate/reverse/restored receipts, tool identities
and a public-source-only failed-artifact discriminator. Corpus-dependent
historical tests are reported as skipped when the corpus is absent. They are not
replaced by fabricated measurements, and no hidden testbench or scorer is used.

Capture metadata routes these two owners through existing subtype entries
`phase2.rtl_gen.word_message_framing` and `phase2.sim.multi_output_waveform`.
They reuse the existing spec-to-rtl and testbench-gen skills; they add no flow
row, framework, acceptance rule or runtime invocation.
