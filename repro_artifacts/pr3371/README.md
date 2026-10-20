# PR3371 original compatibility evidence

This evidence-only branch supplies the original60 source/design files and six full historical negative reports used by the PR author, together with a portable normal-P0 reproducer and measured sparse-mount outputs. The product PR's qualified source remains abeaf1df50ee26c248911871f340c1233bf246b6; the artifact commit is for evidence download.

Archive: portable-evidence.tar.gz
SHA256: 12ce993669b8d30eb9bf4bce6bb71b438de6c10147d7f33aa87bee683a3176c2
Bytes: 494067
Members:153

Extract into a new directory, read its README.md, then run reproduce.py with --out pointing at a new empty output directory. The default runner fetches both exact public Git source commits; --repo can instead select an existing repository read-only. It verifies Git tree IDs and input/source SHA256 values, uses the pinned EDA0.4.26 image and mounts no HOME, historical cache or original host data.

Observed full registry results, four arms each with real history and an explicit replay control:

- Original history storage: FAIL/PASS/FAIL/PASS; encoding remains INCOMPLETE.
- Context replay encoding: PASS/INCOMPLETE/PASS/INCOMPLETE; storage remains FAIL.
- All243 registry IDs and all241 non-target verdicts are preserved per scene, and all66 original bytes remain unchanged.

Fresh encoding receipts/context/native JSON/script/log bytes are included as content-addressed objects. They are reproduction outputs and do not reconstruct missing historical proof. The fixture is an original Subservient subset, not the full3.1GB project and not a SHA256 project. Other fixture FAIL/INCOMPLETE/BLOCKED results remain; this is not a whole-P0, Phase2 or IC PASS. Source51/candidate qualification remains separate from official52 shipping.

The original per-file SPDX notices and the upstream ISC notice are retained. No files under the plugin prefix changed in this evidence commit.

Raw launch.json source_postimages fields describe the underlying host source export. For reverse, the five base overlays listed in mounts determine the effective product bytes. effective-product-postimages.json records four additional read-only in-container probes of those exact source/overlay configurations, confirming base/reverse and candidate/restore identity. These probes neither rerun nor replace the preserved native P0 results. The archive and historical input bytes remain unchanged.
