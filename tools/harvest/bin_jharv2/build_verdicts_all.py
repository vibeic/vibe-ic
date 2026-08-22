#!/usr/bin/env python3
"""verdicts_joined.tsv is scoped to the 355-row roster. My 1084 extra rows cover worktrees found on
8HD-9 and 8HD-7 that the roster never listed, and they are invisible to anything reading the
consumable -- 1083 decided rows that an executor would never see.

Merging them INTO verdicts_joined.tsv would silently change that file's meaning from "the roster" to
"everything", in a file three agents write. So this builds a UNION consumable instead and leaves
verdicts_joined.tsv alone.

Rows are keyed by (host, path). Where the same key appears in both inputs the verdicts are compared:
agreement is merged and recorded as such; DISAGREEMENT IS NOT SILENTLY RESOLVED -- both are emitted
with source=CONFLICT so a reader sees the dispute rather than whichever row happened to be written
last. Precedence is a decision, and inventing one here would bury exactly the thing worth surfacing.
"""
import csv, sys, os

def main():
    base = sys.argv[1] if len(sys.argv) > 1 else 'tools/harvest'
    out_path = os.path.join(base, 'verdicts_all.tsv')
    rows, seen = [], {}
    def add(host, path, verdict, evidence, shard, source):
        k = (host, path)
        if k in seen:
            prev = seen[k]
            if prev['verdict'] != verdict:
                prev['source'] = 'CONFLICT'
                rows.append(dict(host=host, path=path, verdict=verdict, evidence=evidence,
                                 shard=shard, source='CONFLICT'))
            return
        d = dict(host=host, path=path, verdict=verdict, evidence=evidence, shard=shard, source=source)
        seen[k] = d; rows.append(d)
    jp = os.path.join(base, 'verdicts_joined.tsv')
    with open(jp) as f:
        for r in list(csv.reader(f, delimiter='\t'))[1:]:
            if len(r) >= 5: add(r[0], r[1], r[2], r[3], r[4], 'verdicts_joined.tsv')
    ep = os.path.join(base, 'verdicts_extras_joined.tsv')
    with open(ep) as f:
        for r in list(csv.reader(f, delimiter='\t'))[1:]:
            if len(r) >= 5: add(r[0], r[1], r[2], r[3], r[4], 'verdicts_extras_joined.tsv')
    with open(out_path, 'w', newline='') as f:
        w = csv.writer(f, delimiter='\t', lineterminator='\n')
        w.writerow(['host', 'path', 'verdict', 'evidence', 'shard', 'source'])
        for d in rows:
            w.writerow([d['host'], d['path'], d['verdict'], d['evidence'], d['shard'], d['source']])
    conflicts = [d for d in rows if d['source'] == 'CONFLICT']
    print(f"  wrote {len(rows)} rows to {out_path}")
    from collections import Counter
    for k, n in Counter(d['source'] for d in rows).most_common():
        print(f"    {n:5}  {k}")
    for k, n in Counter(d['verdict'] for d in rows).most_common():
        print(f"    verdict {k:9} {n}")
    if conflicts:
        print(f"\n  CONFLICTS ({len(conflicts)}) -- same (host,path), different verdict, both emitted:")
        for d in conflicts[:20]:
            print(f"    {d['host']} {d['path']}  -> {d['verdict']}")
    return 0

if __name__ == '__main__':
    sys.exit(main())
