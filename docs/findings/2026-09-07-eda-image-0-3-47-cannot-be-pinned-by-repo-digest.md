# The 0.3.47 image exists, and the pin cannot move to it — measured, not argued

Lane `czimage47`, host 8HD-4 (192.168.1.120), 2026-09-07.
Branch `next/czimage47pin`. **Nothing in this repository's pin was changed.**
This file records why, so the change is a ruling and not a quiet loosening.

## What was built

`vibeic-eda:0.3.47`, a DERIVED image built `FROM` the campaign digest
`ghcr.io/vibeic/vibeic-eda@sha256:06537f7e…` (its own label reads `0.3.46`),
carrying four changes. Recipe and evidence: `vibeic/vibeic-eda` branch
`release/0.3.47-derived` @ `d5049b0db599`.

Owner ruling 2026-09-07: build it derived, distribute it by
`docker save` / `scp` / `docker load`, **never push it to ghcr**, and pin the
fleet to the LOADED image's identity.

## The blocker, in one sentence

An image that is never pushed to a registry has no registry digest, and every
place this repository pins the runtime requires one.

## The measurement

```
$ docker image inspect vibeic-eda:0.3.47 --format '{{.Id}} {{.RepoDigests}}'
sha256:f7aa4c31ca3db6f87c0f8690551966627361e28cff0d9a55c5207976dfbe44e7  []

$ docker image inspect ghcr.io/vibeic/vibeic-eda@sha256:06537f7e… --format '{{.RepoDigests}}'
[ghcr.io/vibeic/vibeic-eda@sha256:06537f7e8d3c17c6c9c60c20638e94faab0421533a55656ad1819f383c373aba]
```

`RepoDigests` is `[]` for the derived image and populated for the pulled one.
That is not a property of how it was built; it is what "never pushed" means.

## The three places that require the shape a loaded image cannot have

| file:line | what it requires |
|---|---|
| `tools/ci/hermetic_candidate_runner.py:721-723` | `IMAGE_REPO_DIGEST not in repo_digests` → `Refusal("fixed image inspection does not bind the requested digest")`. Unconditional, in `_image_profile`, on every hermetic arm. |
| `tools/ci/protected_landing_transition.py:92-93,416-417` | `IMAGE_RE = r"[a-z0-9./_-]+@sha256:[0-9a-f]{64}\Z"` → `Refusal("...image is not an immutable digest reference")`. |
| `tools/ci/run_suite_in_eda_image.sh:170-176` | `case "$IMAGE_DEFAULT" in *"@sha256:"*)` … else REFUSE, with "there is deliberately no fallback literal here". |

Plus the literal in `vibe-ic-marketplace/plugins/vibe-ic/programs/landing_pytest_runtime_preflight.py:93-94`
and the tests that assert it (`tools/ci/test_hermetic_candidate_runner.py:36`,
`tools/ci/test_protected_landing_transition.py:32`,
`vibe-ic-marketplace/plugins/vibe-ic/programs/tests/test_trusted_pytest_entry.py:16`).

**None of these is a bug.** Each exists so that a floating tag can never become
the runtime. The reason the pin cannot move is the same reason they are there.

## What this lane did NOT do, on purpose

It did not relax `IMAGE_RE`, and it did not change `_image_profile` to accept an
empty `RepoDigests`. Either would make the branch green in an afternoon and would
also delete the property those lines exist to hold. Standing prohibition: never
weaken an assertion to turn a row green. This is a design question about what
"immutable runtime identity" means when the artefact is deliberately not in a
registry, and it belongs to the owner.

## AND THE PIN IS NOT WHERE IT WAS BELIEVED TO BE

Measured on `main` at `2fbb2932` (v1.18.3): the repository still pins

```
ghcr.io/vibeic/vibeic-eda@sha256:66c33ff2e05781758f596d82bff61ad8a404ef0a7eae3d21ab8a9d55df0d01ff
```

which is **0.3.6** — not 0.3.46, the digest the whole campaign has been measured
on. `run_suite_in_eda_image.sh:142-145` already describes this exact drift as a
past defect it fixed by reading the constant instead of copying it; the constant
it now reads has itself never been moved. So the fleet's landing runtime and the
campaign's measurement runtime are forty patch releases apart, today, before
0.3.47 enters the picture at all.

That is worth a ruling on its own and is independent of everything above.

## The two candidate designs, for the ruling

1. **Identity by content.** Pin `sha256:<image id>` and verify `Id` plus the
   `org.opencontainers.image.version` label, accepting an empty `RepoDigests`
   when the reference is a bare image ID. An image ID is the digest of the image
   config, so it is not weaker than a repo digest — but it is not re-pullable,
   and every host must be given the bytes. The tarball sha256 becomes part of the
   provenance record rather than an aside.
2. **Publish it after all.** Push 0.3.47 to ghcr and keep every line above
   exactly as it is. This contradicts the 2026-09-07 ruling, so it is a change of
   ruling, not an implementation choice.

Option 1 is the one consistent with the ruling as given. It still needs the
owner to say so, because it changes what the landing gate means by "pinned".

## The bytes, so the ruling can be acted on without rebuilding

```
image tag       vibeic-eda:0.3.47
image ID        sha256:f7aa4c31ca3db6f87c0f8690551966627361e28cff0d9a55c5207976dfbe44e7
base            ghcr.io/vibeic/vibeic-eda@sha256:06537f7e8d3c17c6c9c60c20638e94faab0421533a55656ad1819f383c373aba
tarball         vibeic-eda-0.3.47.tar.zst
tarball sha256  0fce7566d3a80c521091a271dcf3b114645266161427f976011aa4a133695c05
recipe          vibeic/vibeic-eda @ d5049b0db599 (branch release/0.3.47-derived)
openroad        cad013df982140fb5c78fd584fb1c7ae8a0d3c55, `openroad -version` = 26Q3-2065-gcad013df98
```

Per-host loaded IDs are in the lane's `LAND.md` on 8HD-4.
