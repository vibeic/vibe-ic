#!/usr/bin/env python3
"""J103 — re-resolve every DESIGN-DOCUMENT coordinate this report publishes.

`cite_audit.py` resolves the report's `file.py:NNN` coordinates, and its `TREES` table
covers the flow's own files: pnr.tcl, pad_ring_gen.py, the runner, a PDK model card.
It does NOT cover `L1:33` / `L8:26` / `L9:37` -- the coordinates that carry the REASON
for a NOT FEASIBLE verdict, quoted from a design's own L1-L27 documents.  So the one
family of citation nobody could re-resolve was the family a verdict rests on.

This asks each of them the only question that matters: **does the line the report cites
carry the text the report attributes to it**, and if not, WHERE does that text live?

Method, and the part that can be wrong:
  * candidates are ENUMERATED from bdata/ic/*/input/docs/L<n>_*.md -- a coordinate does
    not name its design, so every design that has that L-doc is tried.
  * the report's associated text is taken from the citation's own form: the fenced
    `L1:33  <text>` block form takes the rest of the line; the inline `(L9:37)` form
    takes the nearest preceding quoted phrase on the same line.
  * a SHORT quote is noisy -- 20 normalised characters scored 0.550 against a line it
    does not come from -- so every row prints the quote's normalised length and rows
    under 24 characters are marked `short`, because an OK there is weaker evidence.
  * matching is on NORMALISED text (CJK/ASCII punctuation folded, arrows folded,
    markdown emphasis and whitespace stripped) and is a SUBSEQUENCE ratio, because the
    report abridges some quotes.  The threshold is not chosen by taste: it is
    CONTROLLED below against the one coordinate already known to be wrong.

Exit 0 all coordinates carry their text; 1 any does not; 2 the instrument could not run.
"""
import os
import pathlib
import re
import sys
from difflib import SequenceMatcher

ROOT = pathlib.Path(os.environ.get("J103_ROOT", "/home/reyerchu/_jself_priv"))
BDATA = pathlib.Path(os.environ.get(
    "J103_BDATA", "/home/reyerchu/_gf180_priv/bdata/ic"))
DOC = ROOT / "RESULT.md"
THRESHOLD = float(os.environ.get("J103_THRESHOLD", "0.85"))

FOLD = {"，": ",", "、": ",", "；": ";", "：": ":", "（": "(", "）": ")",
        "「": '"', "」": '"', "。": ".", "→": "->", "⇒": "->", "—": "-",
        "–": "-", "×": "x", "µ": "u", "μ": "u"}


def norm(s):
    for k, v in FOLD.items():
        s = s.replace(k, v)
    s = re.sub(r"\*+|`|\\", "", s)
    s = re.sub(r"\s+", "", s)
    return s


def ratio(a, b):
    """How much of a survives inside b, order-preserving."""
    if not a:
        return 0.0
    return SequenceMatcher(None, a, b, autojunk=False).ratio() * 2 * len(b) / \
        (len(a) + len(b)) if False else _subseq_ratio(a, b)


def _subseq_ratio(a, b):
    m = SequenceMatcher(None, a, b, autojunk=False)
    matched = sum(bl.size for bl in m.get_matching_blocks())
    return matched / len(a)


def docs_for(layer):
    out = []
    if not BDATA.is_dir():
        return out
    for d in sorted(BDATA.iterdir()):
        if not d.is_dir():
            continue
        dd = d / "input/docs"
        if not dd.is_dir():
            continue
        for f in sorted(dd.glob(f"L{layer}_*.md")):
            out.append((d.name, f))
    return out


text = DOC.read_text(errors="replace")
lines = text.splitlines()

cites = []          # (result_line_no, layer, docline, associated_text, form)
BLOCK = re.compile(r"^L(\d+):(\d+)\s\s+(\S.*)$")
INLINE = re.compile(r"L(\d+):(\d+)")
QUOTED = re.compile(r'["“「]([^"”」]{6,})["”」]')

# The inline form attributes a quote to a coordinate ONLY when the two are adjacent --
# the quote ends just before it (`...integration"* (L1:7)`) or begins just after it
# (`L9:37's *"..."*`).  A looser "nearest quote in the paragraph" rule was tried first
# and would have attributed a quote of the USER'S REQUEST to a design document two lines
# later.  Anything it cannot attribute is reported as UNATTRIBUTED and COUNTED, never
# silently dropped: a sweep that skips quietly is the defect it is looking for.
NEAR = 40
unattributed = []
for i, ln in enumerate(lines, 1):
    m = BLOCK.match(ln)
    if m:
        cites.append((i, int(m.group(1)), int(m.group(2)), m.group(3), "block"))
        continue
    # Quotes span lines, and a quote may follow its coordinate as well as precede it --
    # so the window is the two lines BEFORE, this line, and the one AFTER.  A
    # backward-only window mis-attributed a real citation of mine within minutes of my
    # writing it: the quote belonging to the coordinate had wrapped onto the next line,
    # so the nearest visible quote was the PREVIOUS coordinate's, and the row came back
    # OFF-BY against a coordinate that is correct.
    start = max(0, i - 3)
    prev = lines[start:i - 1]
    win = " ".join(prev + [ln] + lines[i:i + 1])
    off = len(" ".join(prev)) + (1 if prev else 0)
    for m in INLINE.finditer(ln):
        a, b = m.start() + off, m.end() + off
        # CLOSEST wins, measured in characters, with a tie going to the quote that
        # PRECEDES the coordinate -- `"..." (L1:7)` is the form English uses.  Taking
        # "the last one in document order" instead broke two citations that are correct:
        # where two quotes bracket one coordinate, the FOLLOWING quote belongs to the
        # NEXT coordinate, not to this one.
        said, bestd = None, None
        for q in QUOTED.finditer(win):
            if 0 <= a - q.end() <= NEAR:
                dist = (a - q.end(), 0)       # before: tie-break wins
            elif 0 <= q.start() - b <= NEAR:
                dist = (q.start() - b, 1)
            else:
                continue
            if bestd is None or dist < bestd:
                said, bestd = q.group(1), dist
        if said:
            cites.append((i, int(m.group(1)), int(m.group(2)), said, "inline"))
        else:
            unattributed.append((i, f"L{m.group(1)}:{m.group(2)}", ln.strip()[:60]))

if not cites:
    print("no design-document coordinates found — the extractor matched nothing,")
    print("which is a broken instrument and not a clean report.")
    sys.exit(2)

rows, bad = [], []
for rline, layer, dline, said, form in cites:
    cands = docs_for(layer)
    if not cands:
        rows.append(("NO-DOC", rline, f"L{layer}:{dline}", form, "-", 0.0, "", len(norm(said))))
        bad.append((rline, f"L{layer}:{dline}"))
        continue
    want = norm(said)
    best = (0.0, None, None, None)          # score, design, at-line, line-text
    at_cited = (0.0, None, None)
    for design, f in cands:
        dl = f.read_text(errors="replace").splitlines()
        if 1 <= dline <= len(dl):
            s = _subseq_ratio(want, norm(dl[dline - 1]))
            if s > at_cited[0]:
                at_cited = (s, design, dl[dline - 1])
        for k, raw in enumerate(dl, 1):
            s = _subseq_ratio(want, norm(raw))
            if s > best[0]:
                best = (s, design, k, raw)
    # A coordinate does not name its design, so every design is tried -- and that is a
    # laundering path: at a low threshold, `u_hawaii_adc`'s L9:37 scores 0.341 against a
    # quote from `edge_llm_accel`'s L9, on punctuation alone, and would have ACCEPTED a
    # coordinate that is wrong.  Raising the threshold until that stops is tolerance
    # chosen by taste, which is J83's defect.  So the DESIGN is part of the answer: an
    # accepted line must come from the same design where the text actually lives.
    if at_cited[0] >= THRESHOLD and best[0] >= THRESHOLD \
            and at_cited[1] != best[1]:
        rows.append(("CROSS-DESIGN", rline, f"L{layer}:{dline}", form, at_cited[1],
                     at_cited[0], f"but the text lives in {best[1]} at L{layer}:{best[2]}",
                     len(want)))
        bad.append((rline, f"L{layer}:{dline} accepted in {at_cited[1]}, "
                           f"text is in {best[1]}"))
        continue
    if at_cited[0] >= THRESHOLD and best[0] >= THRESHOLD and at_cited[1] == best[1]:
        rows.append(("OK", rline, f"L{layer}:{dline}", form, at_cited[1],
                     at_cited[0], at_cited[2][:70], len(want)))
    elif best[0] >= THRESHOLD:
        rows.append(("OFF-BY", rline, f"L{layer}:{dline}", form, best[1],
                     best[0], f"text lives at L{layer}:{best[2]} — {best[3][:50]}",
                     len(want)))
        bad.append((rline, f"L{layer}:{dline} -> L{layer}:{best[2]}"))
    else:
        rows.append(("NOT-FOUND", rline, f"L{layer}:{dline}", form,
                     best[1] or "-", best[0], (best[3] or "")[:50], len(want)))
        bad.append((rline, f"L{layer}:{dline}"))

print("=== every design-document coordinate in RESULT.md ===")
for st, rline, coord, form, design, sc, note, qlen in rows:
    mark = "short" if qlen < 24 else "     "
    print(f"  {st:<12} RESULT.md:{rline:<5} {coord:<9} {form:<6} "
          f"{str(design):<22} {sc:.2f} {mark} n={qlen:<3} {note}")

print(f"\n  {len(rows)} coordinate(s) audited, threshold {THRESHOLD:.2f}")
print(f"\n=== coordinates with no quote adjacent — NOT audited, and counted ===")
for rline, coord, ctx in unattributed:
    print(f"  UNATTRIBUTED  RESULT.md:{rline:<5} {coord:<9} {ctx}")
print(f"  {len(unattributed)} coordinate(s) carry no adjacent quote, so there is no text")
print("  to check them against.  Named rather than skipped.")
print()
if bad:
    print(f"{len(bad)} coordinate(s) do not carry the text the report attributes to them:")
    for rline, c in bad:
        print(f"    RESULT.md:{rline}  {c}")
    print("A quote is evidence; the coordinate beside it is the address that makes it")
    print("checkable, and an address that resolves elsewhere is not one.")
    sys.exit(1)
print("Every design-document coordinate carries its own quoted text.")
sys.exit(0)
