# Issue 3378: native producer domain closure counterexamples

Measured official plugin **1.30.53**, source `ec0ad93839cdac36420d87735e4faae6f9b8f58e`, tree `2b8ddab714e3ae2918862269f68da3d2e1dc3392`.
Image `ghcr.io/vibeic/vibeic-eda@sha256:97fb48e8ed7c61697818144586b601cfa6e932abef7842588a0384b6aeb5a5e5`.

All fixtures are neutral author-owned regressions. No benchmark RTL, oracle or firmware.
Each fixture has `neutral.v` and `tb.sv`; place source in an `rtl` directory, then run the shipped interface_encoding_audit.py with `--rtl-dir rtl --top-module neutral -I rtl --out-dir audit`.
Compile simulation with `iverilog -g2012 -s tb -o sim.vvp rtl/neutral.v tb.sv`; execute `vvp sim.vvp`.

Expected interface `link`: scalar_alias / two_scalar_aliases / control_only **UNKNOWN**, not BIT_VALUE/PREDICATE MATCH. Actual shipping result **MATCH** for each, audit rc0; simulation compile rc0 and simulation rc1 with binary=2 observed=3.
valid_scalar_alias / valid_scalar_guard: expected and actual **MATCH**; four-state native simulation rc0. Unused wider module inputs must not force rejection.
All five preserve the seven-row interface population.

`native-evidence.json.gz` contains JSON with base64-encoded original files and per-file SHA-256. Verify SHA256SUMS, decompress JSON, decode each `files[path].base64` and verify its SHA-256. It includes exact native context/model/script/log, source/TB, receipt, three Docker launch/mount readbacks, analysis scripts, positive simulation and finite metamorphic proof.
The miter completed 256 four-state source/selector probes and 64 serial frames: rc0, DOMAIN_METAMORPHIC_PASS. This is finite evidence, not unbounded formal proof.
Two initial fixture/metadata-reader setup failures are retained, explicitly excluded from product-red counts. Fresh successful native analysis has a separate log and readback; no previous receipts were rewritten.

This packet reopens the same producer word-domain defect. The original four direct forms became UNKNOWN in 1.30.53, but transitive aliases and control dependencies bypass its RHS-only width check. Native structural fan-in reaches data width3 / phase width2 in the three negatives; only seed width1 in both positives. Structural fan-in is not minimal Boolean support. No whole IC or shipping acceptance is claimed.

## Parent input binding (additional epoch)

`parent_alias` moves the same wider Gray projection into the parent and binds it to a one-bit producer input. The producer is just `assign flag = seed`. Local-only cone tracing would falsely admit this same serialized word. Actual source53 audit rc0: six rows,1MATCH/5UNKNOWN; link falselyBIT_VALUE/PREDICATE MATCH. Original native reconstruction compilesrc0 / runs exactrc1, binary2observed3. ExpectedlinkUNKNOWN. `parent-native-evidence.json.gz` separately preserves this fixture and original native receipts/model/context/logs/mounts. Its row population is six, not seven, and is never mixed with the earlier cases. A repair must follow actual hierarchical input bindings or carry an explicitly unproved contract; local leaf-port width is insufficient. Earlier64-filepacket remains byte-identical at741c722.
