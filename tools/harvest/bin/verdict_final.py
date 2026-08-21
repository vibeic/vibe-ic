#!/usr/bin/env python3
"""verdict2.py -- LANDED / RECOVER / ABANDON for every vibe-ic worktree, fleet-wide.

vibe-ic squash-lands, so ancestry (merge-base --is-ancestor, branch --merged,
rev-list origin/main..HEAD) calls landed work unlanded. Everything here is decided
on CONTENT.

The load-bearing number is `nadd`: added lines of `git diff --numstat origin/main
<head>` restricted to the files the worktree itself touched. It is the content the
worktree HAS that main DOES NOT. Its mirror `ndel` measures only how far BEHIND
main the tree is, and summing the two (which an earlier pass did) makes a merely
stale tree look like thousands of lines of recoverable work.

Rules, in priority order; the id lands in the `rule` column.
  L0  nadd == 0, clean                     LANDED   nothing here is absent from main
  L1  content state LANDED_*, clean        LANDED   byte-identical / hunks already in main
  L2  as above but tracked edits present   RECOVER  the uncommitted edits are the work
  N1  nadd > 0 only in version manifests
      / README version strings, clean      LANDED   residue of an older release, not work
  A1  PR-verification merge, PR MERGED     ABANDON  landed squashed as that PR
  A2  PR-verification merge, PR closed     ABANDON  rejected
  R1  PR-verification merge, PR OPEN       RECOVER
  A3  "[vX.Y.Z] candidate batch", X<main   ABANDON  spent landing staging tree
  A5  tip is a bare integration merge and
      nadd is trivial (<= 20)              ABANDON  merge-queue scratch
  A4  identical HEAD to a tree kept above  ABANDON  duplicate
  R2  anything else                        RECOVER  sized by nadd
Ties break toward RECOVER: a wrong ABANDON destroys work nobody can reconstruct.
"""
import json, re, os, glob

PRIV = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
L = lambda n: json.load(open(os.path.join(PRIV, n)))
pr = {x["number"]: x for x in L("prs.json")}

def norm_subject(s):
    """Normalise a commit subject so a squash-landed copy matches its source tree.
    vibe-ic rewrites the type(scope): prefix and appends the PR ref at landing, but
    keeps the prose verbatim -- that prose is the reliable identity."""
    s = s.strip().lower()
    s = re.sub(r"\(#\d+[^)]*\)\s*$", "", s)                  # trailing (#1516)
    s = re.sub(r"^\[[^\]]+\]\s*", "", s)                     # [v1.10.x]
    s = re.sub(r"^[a-z0-9_.\-]+(\([^)]*\))?:\s*", "", s)     # fix(landing):
    s = re.sub(r"#\d+", "", s)
    s = re.sub(r"[^a-z0-9 ]+", " ", s)
    return re.sub(r"\s+", " ", s).strip()

MAIN_SUBJECTS = set()
for _l in open(os.path.join(PRIV, "main_subjects.txt"), errors="replace"):
    _n = norm_subject(_l)
    if len(_n) >= 25: MAIN_SUBJECTS.add(_n)
MAIN_VER = (1, 11, 18)

# issue numbers that a LANDED main commit references -- the work for them is in main
LANDED_ISSUES = {int(x) for x in open(os.path.join(PRIV, "landed_issues.txt")) if x.strip().isdigit()}
# issue -> (sha, subject) of the most recent main commit that references it, so every
# A6 ABANDON names the landing that supersedes it and a human can audit the call.
LANDING = {}
for _l in open(os.path.join(PRIV, "issue_landed_map.tsv"), errors="replace"):
    _p = _l.rstrip("\n").split("\t")
    if len(_p) >= 3 and _p[0].isdigit(): LANDING.setdefault(int(_p[0]), (_p[1], _p[2]))
NOPUSH = re.compile(r"not for push|do not push|throwaway|scratch only|local only", re.I)

NOISE = re.compile(r"(\.claude-plugin/plugin\.json|marketplace\.json|^README\.md|"
                   r"docs/INSTALL\.md|/VERSION$|CHANGELOG\.md|\.image-version-ignore)")

EX = ("repo path branch head state nfiles ndiffer nnovel nadd ndel code_add trk "
      "unt subject topdirs novelfiles cdate mainref wtdir").split()
rows = []
_seen = set()
# extras first (x_*, 19 cols incl. wtdir, measured with the GONE fix), then the
# brief-set (r2_*, 18 cols). First writer wins, so the better measurement holds.
for pat, hre in (("x_*.tsv", r"x_(\d+)"), ("r2_*.tsv", r"r2_(\d+)")):
    for f in sorted(glob.glob(os.path.join(PRIV, pat))):
        host = re.search(hre, f).group(1)
        for line in open(f, errors="replace"):
            p = line.rstrip("\n").split("\t")
            if len(p) < 18 or p[0].startswith(("NOMAIN", "SELFTEST")): continue
            r = dict(zip(EX, p)); r["host"] = host
            if r["path"] == r["repo"]: continue      # the clone's own checkout
            k = (host, r["path"])
            if k in _seen: continue
            _seen.add(k)
            r["nloc"] = "0"; r["_pre"] = True
            rows.append(r)

def side(pat, idx):
    """Keyed by (HOST, path): worktree paths repeat across machines."""
    d = {}
    for f in glob.glob(os.path.join(PRIV, pat)):
        m = re.search(r"_(\d{3})\.tsv$", f)
        host = m.group(1) if m else "?"
        for line in open(f, errors="replace"):
            p = line.rstrip("\n").split("\t")
            if len(p) > max(idx): d[(host, p[0])] = [p[i] for i in idx]
    return d

d2 = side("xd_*.tsv", [1, 2, 3, 4]); d2.update({k: v for k, v in side("e2_*.tsv", [1, 2, 3, 4]).items() if k not in d2})
num = lambda v: int(v) if str(v).lstrip("-").isdigit() else 0
for r in rows:
    for k in ("nadd", "ndel", "code_add", "trk", "unt"): r[k] = num(r[k])
    r["has_nadd"] = r["has_code"] = True
    k = (r["host"], r["path"])
    if k in d2:
        m, dl, un, on = (num(x) for x in d2[k])
        r["trk"], r["unt"], r["ondisk"] = m, un, on
        r["emptied"] = (dl > 50 and m == 0)

def issue_of(r):
    m = re.search(r"#(\d{2,5})", r["subject"])
    if m: return int(m.group(1))
    for s in (r["branch"], r["path"]):
        m = re.search(r"(?:issue|fix/|_i|_L|_gk|pr)(\d{3,4})", s)
        if m and 100 <= int(m.group(1)) <= 2200: return int(m.group(1))
    return None

rows.sort(key=lambda r: (r["head"], r["host"], r["path"]))
kept = {}
PRM = re.compile(r"(?:pr|pull)/(\d{2,5})")
VB = re.compile(r"^\[v(\d+)\.(\d+)\.(\d+)\]\s*candidate batch")

for r in rows:
    r["issue"] = issue_of(r)
    landed_state = r["state"].startswith("LANDED")
    nadd, novel = r["nadd"], [x for x in r["novelfiles"].split(",") if x]
    only_noise = bool(novel) and all(NOISE.search(x) for x in novel)
    m, vb = PRM.search(r["subject"]), VB.match(r["subject"])
    bare_merge = r["subject"].startswith("Merge ")

    def set_(v, rule, why): r["verdict"], r["rule"], r["why"] = v, rule, why

    # An UNMEASURED row is not a zero row (findings F34).
    if r["state"] in ("GONE", "NOHEAD", "NOMERGEBASE"):
        set_("RECOVER", "U1", f"NOT MEASURED (state {r['state']}) - verdict withheld, defaulting to keep")
    elif r["trk"] > 0:
        # an uncommitted edit exists on exactly one disk; it can never be ABANDON
        where = "committed content is in main, but" if (landed_state or nadd == 0) else \
                f"holds {nadd} committed lines absent from main, plus"
        set_("RECOVER", "L2", f"{where} {r['trk']} tracked file(s) uncommitted")
    elif r["has_nadd"] and nadd == 0 and r["trk"] == 0:
        set_("LANDED", "L0", f"holds 0 lines main lacks (it is {r['ndel']} lines BEHIND main)")
    elif landed_state and r["trk"] == 0 and (r["code_add"] <= 200 or r["ndel"] > nadd):
        set_("LANDED", "L1", f"content already in main ({r['state'].lower()})"
                             + (f"; {r['code_add']} stale authored lines remain" if r["code_add"] else ""))
    elif (norm_subject(r["subject"]) in MAIN_SUBJECTS and r["trk"] == 0
          and not bare_merge                       # merge prose is too weak an identity key
          and (r["code_add"] <= 200 or r["ndel"] > nadd)):
        # guard: if the tree holds a lot of authored content and main holds nothing
        # extra (ndel small), the prose match is not enough -- main may have landed
        # the commit and later WITHDRAWN the content. Measured: .121:_LRNdh holds 558
        # authored lines whose subject matched, but main carries
        # "[v1.10.85] withdraw the four upstream studies and the plan from the repo".
        set_("LANDED", "L3", f"this tip landed in main under the same prose; tree is {r['ndel']} lines behind")
    elif only_noise and nadd <= 40 and r["trk"] == 0:
        set_("LANDED", "N1", f"only version/README residue of an older release ({nadd} lines)")
    elif m and int(m.group(1)) in pr:
        n = int(m.group(1)); s = pr[n]["state"]
        if s == "MERGED":   set_("ABANDON", "A1", f"PR-verification merge of #{n}; that PR MERGED (squashed into main)")
        elif s == "OPEN":   set_("RECOVER", "R1", f"PR-verification merge of #{n}, still OPEN")
        else:               set_("ABANDON", "A2", f"PR-verification merge of #{n}; closed WITHOUT merge (rejected)")
    elif vb and tuple(map(int, vb.groups())) < MAIN_VER:
        set_("ABANDON", "A3", f"spent landing staging tree for v{'.'.join(vb.groups())}; main is v1.11.18")
    elif bare_merge and nadd <= 20:
        set_("ABANDON", "A5", f"merge-queue integration scratch; only {nadd} lines absent from main")
    elif NOPUSH.search(r["subject"]) and r["trk"] == 0:
        set_("ABANDON", "A7", "the tip commit declares itself a local probe not meant to be pushed")
    elif (r["issue"] in LANDED_ISSUES and r["ndel"] >= 2 * max(nadd, 1)
          and r["trk"] == 0 and nadd > 0):
        _sha, _sub = LANDING.get(r["issue"], ("", ""))
        _land = f" as {_sha} \"{_sub[:70]}\"" if _sha else ""
        set_("ABANDON", "A6", f"issue #{r['issue']} landed{_land}; this tree is {r['ndel']} lines "
                              f"behind main and holds {r['code_add']} authored - a superseded attempt")
    elif r["head"] in kept:
        set_("ABANDON", "A4", f"identical HEAD to {kept[r['head']]} (kept there)")
    else:
        extra = f"; issue #{r['issue']}" if r["issue"] else ""
        if r["has_code"] and r["code_add"] < nadd:
            gen = nadd - r["code_add"]
            set_("RECOVER", "R2", f"{r['code_add']} authored lines absent from main "
                                  f"(+{gen} regenerable){extra}")
        else:
            set_("RECOVER", "R2", f"{nadd} lines in {r['nnovel']} file(s) absent from main{extra}")
    if r.get("wtdir") == "REMOVED":
        r["why"] += "; worktree DIRECTORY has been deleted - the commit survives in the object store, so recover the REF, not the directory"
    if r.get("emptied"):
        r["why"] += "; worktree dir has been EMPTIED - only its commit survives"
    if r["verdict"] == "RECOVER":
        kept.setdefault(r["head"], f"{r['host']}:{r['path']}")

hdr = ["host","repo","path","branch","head","state","nfiles","nnovel","nadd","ndel","code_add",
       "trk_dirty","untracked","issue","cdate","verdict","rule","subject","topdirs","novelfiles","wtdir","why"]
print("\t".join(hdr))
rows.sort(key=lambda r: (r["host"], r["path"]))
for r in rows:
    print("\t".join(str(x) for x in [r["host"], r.get("repo","/home/reyerchu/vibe-ic"), r["path"], r["branch"], r["head"][:9],
        r["state"], r["nfiles"], r["nnovel"], r["nadd"], r["ndel"], r["code_add"], r["trk"], r["unt"],
        r["issue"] or "", r["cdate"], r["verdict"], r["rule"], r["subject"], r["topdirs"], r.get("novelfiles",""), r.get("wtdir",""), r["why"]]))
