# Historical commit archive

The source branches cited by `RESULT.md` were merged into a squash landing and
then deleted. Git does not promise to retain unreachable commit objects, so a
fresh main-only clone no longer resolves nine source commit IDs even though the
report must retain those IDs as historical evidence.

`HISTORICAL_COMMITS.bundle` preserves exactly those nine named commits and the
intervening source history. It is an incremental Git bundle whose prerequisites
are all ancestors of the repository commit that carries it.

- Bundle SHA-256: `55746a973279c500d9bcf361e47d80fa1e56099c4028ab0f8f259486434034cd`
- Bundle bytes: `7547498`
- Common declared base: `a758f4adc6187533d4ca0b56cc843275d033b634`
- Source: the repository object database before the last source refs were
  retired; no file content was reconstructed.

Archived refs:

```text
22b18cb1077a1b36c3ec33479617eb59279840b8 refs/archive/ppa-eco/tip-main
4c544a6612b076c1a25f38c6897049fa376acc4f refs/archive/ppa-eco/followup
4fc81d2a293d773524a48d346ce1b643507d3669 refs/archive/ppa-eco/incident
8e2931587c182d0f8b623424e6841b2eaa4821f7 refs/archive/ppa-eco/exemption
a5d3fea186ff800daee6bd09097a77558e11a0da refs/archive/ppa-eco/backlog-a
d54bdfb67f5242659afec1343c4dd272661edd58 refs/archive/ppa-eco/axis-count
dd7a55eaf2133f9db2d893b06ef7e793d8f1993a refs/archive/ppa-eco/backlog-b
f872a0482f9905d8902a61dbef62e5ab3bd27e5f refs/archive/ppa-eco/incident-merge
fabbcdcfe9142007b760f6e01622f15a4d6c6b02 refs/archive/ppa-eco/docs-correction
```

Verification and optional recovery:

```sh
git bundle verify docs/campaigns/ppa-eco-axis-audit/HISTORICAL_COMMITS.bundle
git bundle list-heads docs/campaigns/ppa-eco-axis-audit/HISTORICAL_COMMITS.bundle
git fetch docs/campaigns/ppa-eco-axis-audit/HISTORICAL_COMMITS.bundle \
  'refs/archive/ppa-eco/*:refs/archive/ppa-eco/*'
```

The archive proves identity and recoverability. It does not by itself prove
that a source branch landed; squash landing must still be established by
content comparison.
