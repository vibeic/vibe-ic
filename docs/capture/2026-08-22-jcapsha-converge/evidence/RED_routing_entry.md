# The red the routing entry ships with

The only behavioural change on this branch is one CAPTURE_ROUTING entry. Here
is the state without it, measured by reverting that file to `origin/main` and
re-running the emitter on the SAME `recoveries.json`.

## Without the entry (origin/main's routing)

    $ python3 programs/enhancement_emit.py --records recoveries.json --out-dir /tmp/red_out
    exit 0
    summary.json: "routing_used": {"bucket_A": []}
                  "bucket_A_files": []

Three Bucket A records in, ZERO program-rule sketches out, and **exit 0**.

## With the entry

    summary.json: "routing_used": {"bucket_A": [
                      "programs/pad_ring_gen.py",
                      "programs/upstream_contract_parity_check.py"]}
                  2 sketch files, 3 rules

## Why this is worth a line of its own

The failure is SILENT and it exits 0. `default_routing.bucket_A_program` is
`null`, so a capture from a step with no entry does not refuse, does not warn,
and does not route — it emits nothing and reports success. The flow declares
the step (`flow/phase1_phase2_phase3.yaml:2986`, "Pad Ring (chip/IC path
only)") and CAPTURE_ROUTING carried zero pad entries, so every Bucket A
recovery ever captured from the pad-ring step has been dropped on the floor
with a green exit code.

That is the same class as F1 one more time — a verdict that reads as an answer
("emitted, exit 0") while the thing being asked about was never reached. It is
recorded here rather than emitted as a fourth rule, for the reason given in
record 3's `prior_art`.

Two prior lanes of mine, independently, added the same `phase3.pad_ring` entry
(`origin/agent/jcapsha-capture`, `origin/jcapsha/sha256-capture`). Three
independent arrivals at the same missing entry is the entry being missing, not
three people having the same idea.
