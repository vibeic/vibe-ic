# Eight files are ABSENT from this bundle, by the repo's rule, and here are their hashes

`git add` **silently skipped** eight files when this bundle was committed:
`.gitignore:31` excludes `*.log` and `.gitignore:84` excludes `*.def`. Adding a
directory does not error on ignored paths — it drops them and says nothing. The
push reported success and shipped an incomplete bundle.

**I did not force-add them, and that is deliberate.** Both rules are the repo's,
and the three capture bundles already under `docs/capture/` contain **zero**
`.log` or `.def` files — they are `.py`, `.yaml`, `.json` and `.md` only. Raw
logs and layout artefacts are exactly what those rules exist to keep out. A
bundle that overrode them to ship 700 KB of DEFs would not be following the
convention it claims to follow.

**So this bundle is a SUBSET, and says so.** `evidence/MANIFEST.sha256` lists all
47 evidence files, including these eight. Verifying it here yields **8 FAILED**
for absence — which is correct behaviour and not a corruption. The eight, with
the sha256 the manifest records, so they remain checkable wherever they are
retrieved from:

    merge_preview/g_gate_zero_denominator_refuses_check.log    1aaffcbd48b0d573523c19a1f07c4538...
    merge_preview/g_prose_polarity_consulted_check.log         33ba9a93fa21ca4823f00558a882e4ad...
    merge_preview/g_silent_decline_audit.log                   bca6baeda85c8563ad824c8dfb33b689...
    merge_preview/g_source_chip_agnostic_check.log             ba74214c9e396577be3ef47326d7a85c...
    merge_preview/pytest_merged.log                            2eba7ffc8efad69f298d6189007af843...
    rotation_probe/probe.def                                   4a5a97b24d27e36e1ec154e64c4726cf...
    sha256_gf180_padring.def                                   488180d11979fdabe267059e2716f203...
    sha256_gf180_padring_DEFAULT_R0.def                        b6400ec94e0ea39330fa4f617b98564c...

**What is lost by their absence, stated honestly.** The five `.log` files are the
raw stdout of the four gates and the merge-preview pytest run; their VERDICTS and
DENOMINATORS are quoted in `evidence/merge_preview/MERGE_PREVIEW.md`, which is
here. The three `.def` files are the placed pad rings; every figure derived from
them — 81 components, the `FW`/`W` orientation counts, pad and corner positions —
is re-derived by `evidence/arithmetic_selfcheck.py` from the JSON artefacts,
which ARE here. **No claim in RESULT.md rests on an absent file alone.**

`arithmetic_selfcheck.py` will report **rc=2 NOT VERIFIED** in this bundle rather
than passing, because two of its checks read a `.def`. That is the correct
outcome: a question it cannot ask has not passed.
