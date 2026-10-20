# PR 3371: exact official54 integration and original compatibility inputs

Base **ae5600157f8ac19e63ce21e92a8de51e07ded91c**, tree **98b655df5915e7983151629a3044bd66033f0c1a** (official1.30.54).
Candidate **85a1bdd67e138fb6063eca5fce6f69fd2f952b14**, tree **bd81308b8dca2de6086dabccb1e2abc935c4db96**.
Image **ghcr.io/vibeic/vibeic-eda@sha256:97fb48e8ed7c61697818144586b601cfa6e932abef7842588a0384b6aeb5a5e5**.
The candidate is an isolated clean merge of official54 into the existing contributor PR, not an official installed release. No main push, version assignment or installed cache edit.

## One-command replay

After extracting this packet, with Docker and Git available:

    docker pull ghcr.io/vibeic/vibeic-eda@sha256:97fb48e8ed7c61697818144586b601cfa6e932abef7842588a0384b6aeb5a5e5
    python3 reproduce.py --out /a/new/empty/output-directory

The default mode fetches both exact public Git commits and verifies their trees. It never needs the author HOME, old install cache, full historical project or another machine. All containers mount a plugin and driver RO, isolated project/result RW, and /tmp as tmpfs; the original path strings are preserved only as Docker destinations. `--repo /a/local/repo` is optional read-only acceleration, not required. The driver and reproducer are byte-identical to the earlier portable packet; only the source manifest changes to this additive54epoch.

`fixture/` contains the same60 original source/design files plus **all six complete original failed reports**. All66 are byte-identical, SHA-pinned in manifest.json. `replay-fixture/` is a separate three-file **synthetic negative control**. Old missing producer proof was not recreated. SERV copyright/license notices are retained. No benchmark oracle/reference firmware/harness is included.

## Measured result

Owner selection is frozen once: two full owning test files, two exact existing native-driver nodes and the five existing producer-domain controls affected by the merge. **165 same IDs**, base25FAIL/140PASS -> candidate165PASS -> product-only reverse same25FAIL/140PASS -> restore165PASS. Exact rc1/0/1/0; zero errors/skips. Both reds contain **25 observed-value failures, zero presence-only, zero undecided**. All source mounts RO, no writable source alias. NoGit's internal source-write guard is NOT_CHECKED; the actual RO mounts and file hashes are independently verified.

Eight normal **243-record P0** runs on these exact original66files and separate3file controls: real-history storageFAIL/PASS/FAIL/PASS while encoding staysINCOMPLETE; replay encodingPASS/INCOMPLETE/PASS/INCOMPLETE while storage staysFAIL. All241otherverdicts and all original input bytes are unchanged. Actual child invocations are159real/223replay, not243processes.

A second default replay using a fresh anonymous public Git fetch with global/system Git config disabled completed all eight arms with the same results; readback and log are included. The core case outputs in observed/ are the first local exact-tree epoch. Other P0 FAIL/INCOMPLETE/BLOCKED results remain visible. This is component/native-consumer compatibility on the author's subset, not another unavailable corpus, full3.1GBproject, whole-P0, Phase2, shipping-release or whole-IC acceptance.

The same ten word-domain fixtures were also rerun against the candidate: six contractPASS/four actual-valueFAIL remain, and all ten edge values equal official54. Eight functional-negative simulationsrc1 (binary2observed3), two genuine scalar four-state positivesrc0. Individual populations unchanged (nine7rowcases, parent6rows). This PR **does not fix or mask #3378** and must not count those scalar MATCH values as semantic closure.

## Evidence identity

`payload-sha256.json` hashes every payload except itself. `observed/` includes raw JUnit/logs/launches, source-hash probes, P0 reports and readbacks. Raw launch `source_postimages` describe underlying exports; effective base-test and reverse-product overlays are independently measured in review3371-effective-source-r6.json: productsbase=reverse/candidate=restore, all four test-file bytes identical across arms. Initial source-probe setup lacked writable/tmp and terminated; it is separately retained and **not credited as a product red**. Corrected fresh probes supplied tmpfs and passed all four arms.

`observed/native-index.json` maps current/prior encoding receipt/context/model/script/log files to content-addressed raw bytes in native-objects/. The bytes are fresh production evidence or explicitly adversarial context-replay outputs, not restored historical proof. Preserve the index role and source scope when reading them. Older source51 packets and their commit-pinned archives remain unchanged; this additive54epoch does not rewrite them. The protected canonical IC run remains official49/canonical18 FAIL; wholeIC/Phase3/GDS NOT_MEASURED.
