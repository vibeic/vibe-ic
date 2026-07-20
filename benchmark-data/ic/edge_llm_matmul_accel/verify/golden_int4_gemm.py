#!/usr/bin/env python3
# ---------------------------------------------------------------------------
# golden_int4_gemm.py  --  INDEPENDENT bit-true golden for edge_llm_matmul_accel
#
# Built PURELY from the L-doc MATH CONTRACT (not from the DUT RTL datapath):
#   * INT4 signed operands, two's complement, range -8..+7            (L15)
#   * C = A x B, exact 32-bit signed accumulate over K               (L2/FR1,FR2)
#   * requant: out = saturate_int8( round( acc * scale >> OUT_SHIFT ))(P3,FR3)
#       - scale is a single Q1.15 UNSIGNED register value (raw int)   (L4,L15)
#       - "round" = round-half-up: add 2^(shift-1) then arithmetic
#         right-shift by `shift` (canonical fixed-point requant round)
#       - saturate to signed INT8 [-128, +127]                        (L15)
#   * word_pack: 32-bit bus word = 8 x INT4, LSB-first                (L15)
#
# This file ALSO emits DUT stimulus vectors + golden EXPECTED bytes so the
# Verilog testbench can replay operands and compare against these expected
# values WITHOUT containing any golden arithmetic itself.
#
# NOTE ON INDEPENDENCE: the requant expressions here are derived from the
# contract words ("round", "arithmetic >> shift", "saturate INT8"), not copied
# from the RTL. They coincide with any correct implementation of the same spec.
# ---------------------------------------------------------------------------
import os
import json
import random

VDIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "vectors")

TILE = 16  # fixed 16x16 compute tile (ARRAY_ROWS x ARRAY_COLS)


# --------------------------------------------------------------------------
# Core math contract
# --------------------------------------------------------------------------
def int4_clip(v):
    """Assert operand is a legal signed INT4 (-8..+7)."""
    assert -8 <= v <= 7, "operand %d outside INT4 range" % v
    return v


def int4_matmul(A, W, K):
    """Exact signed integer matmul over the first K contraction terms.
    A: MxKfull list-of-lists (A[m][k]); W: KfullxN (W[k][n]).
    Returns MxN python-int accumulator matrix (no truncation)."""
    M = len(A)
    N = len(W[0])
    acc = [[0] * N for _ in range(M)]
    for m in range(M):
        for n in range(N):
            s = 0
            for k in range(K):
                s += int4_clip(A[m][k]) * int4_clip(W[k][n])
            acc[m][n] = s
    return acc


def requant(acc, scale, shift):
    """out = saturate_int8( round_half_up( acc * scale >> shift ) ).
    scale: raw unsigned Q1.15 register value (0..65535). shift: 0..31."""
    full = acc * scale
    if shift == 0:
        q = full
    else:
        q = (full + (1 << (shift - 1))) >> shift   # python >> = arithmetic floor
    if q > 127:
        return 127
    if q < -128:
        return -128
    return q


def requant_tile(acc_mat, scale, shift):
    return [[requant(acc_mat[m][n], scale, shift) for n in range(len(acc_mat[0]))]
            for m in range(len(acc_mat))]


# --------------------------------------------------------------------------
# Operand packing into the DUT's SRAM word layout (interface/driving contract).
#   weight word 2k   nibbles n=0..7  = W[k][0..7]   (LSB-first)
#   weight word 2k+1 nibbles n=0..7  = W[k][8..15]
#   act    word 2k   nibbles m=0..7  = A[0..7][k]
#   act    word 2k+1 nibbles m=0..7  = A[8..15][k]
# (derived from the RTL port/decode + L15 word_pack; used only to STIMULATE.)
# --------------------------------------------------------------------------
def _nib(v):
    return v & 0xF  # two's-complement low nibble


def pack_weight_words(Wtile):
    """Wtile: 16x16 W[k][n]. Returns 32 x 32-bit ints."""
    words = [0] * 32
    for wi in range(32):
        w = 0
        for p in range(8):
            L = wi * 8 + p
            k = L // 16
            n = L % 16
            w |= _nib(Wtile[k][n]) << (p * 4)
        words[wi] = w & 0xFFFFFFFF
    return words


def pack_act_words(Atile):
    """Atile: 16x16 A[m][k]. Returns 32 x 32-bit ints."""
    words = [0] * 32
    for wi in range(32):
        w = 0
        for p in range(8):
            L = wi * 8 + p
            k = L // 16
            m = L % 16
            w |= _nib(Atile[m][k]) << (p * 4)
        words[wi] = w & 0xFFFFFFFF
    return words


def expected_bytes_o_order(int8_tile):
    """int8_tile: 16x16 signed INT8. Return 256 unsigned-byte ints in o order
    (o = m*16 + n)."""
    out = []
    for o in range(256):
        m = o // 16
        n = o % 16
        out.append(int8_tile[m][n] & 0xFF)
    return out


# --------------------------------------------------------------------------
# Golden self-test: hand-computed 2x2 example embedded in a 16x16 tile.
# --------------------------------------------------------------------------
def selftest_2x2():
    # Hand pick a 2x2 problem:
    #   A = [[ 3, -2],
    #        [ 7, -8]]
    #   W = [[ 1,  4],
    #        [-5,  2]]
    # C[0][0] = 3*1 + (-2)*(-5) = 3 + 10 = 13
    # C[0][1] = 3*4 + (-2)*2    = 12 - 4 = 8
    # C[1][0] = 7*1 + (-8)*(-5) = 7 + 40 = 47
    # C[1][1] = 7*4 + (-8)*2    = 28 - 16 = 12
    A = [[3, -2], [7, -8]]
    W = [[1, 4], [-5, 2]]
    acc = int4_matmul(A, W, K=2)
    hand = [[13, 8], [47, 12]]
    ok_acc = (acc == hand)

    # Requant hand-check with scale=32768 (Q1.15 = 1.0), shift=15 -> out=acc.
    # 13*32768 = 425984 ; +2^14=16384 -> 442368 ; >>15 = 13. etc.  (identity)
    rq = requant_tile(acc, scale=32768, shift=15)
    ok_rq_identity = (rq == hand)

    # Requant hand-check with a real fractional scale: scale=16384 (0.5), shift=15
    #   out = round(acc * 0.5).  13*0.5=6.5 -> 7(half-up); 8*0.5=4; 47*0.5=23.5->24; 12*0.5=6
    rq2 = requant_tile(acc, scale=16384, shift=15)
    exp2 = [[7, 4], [24, 6]]
    ok_rq_frac = (rq2 == exp2)

    # Saturation hand-check: scale=32768, shift=15, force out-of-range.
    #   acc 200 -> 127 ; acc -300 -> -128 ; acc 50 -> 50
    sat = [requant(200, 32768, 15), requant(-300, 32768, 15), requant(50, 32768, 15)]
    ok_sat = (sat == [127, -128, 50])

    passed = ok_acc and ok_rq_identity and ok_rq_frac and ok_sat
    detail = {
        "acc_matches_hand": ok_acc,
        "acc": acc,
        "requant_identity_ok": ok_rq_identity,
        "requant_frac_ok": ok_rq_frac,
        "requant_frac_got": rq2,
        "requant_frac_exp": exp2,
        "saturation_ok": ok_sat,
        "saturation_got": sat,
    }
    return passed, detail


# --------------------------------------------------------------------------
# Test-case generation
# --------------------------------------------------------------------------
def rand_tile(rng, lo=-8, hi=7):
    return [[rng.randint(lo, hi) for _ in range(TILE)] for _ in range(TILE)]


def const_tile(v):
    return [[v for _ in range(TILE)] for _ in range(TILE)]


def build_cases():
    """Return list of 'pass' dicts. Each pass is ONE 16x16 hardware invocation:
       { 'name', 'A'(16x16), 'W'(16x16), 'scale', 'shift', 'k' }.
       Also returns a list of higher-level 'checks' describing tiled reconstructions.
    """
    passes = []
    checks = []

    # ---- Case 1..3 : single 16x16 tile, K=16, random operands, random scale/shift
    for seed in (1, 7, 4242):
        rng = random.Random(seed)
        A = rand_tile(rng)
        W = rand_tile(rng)
        scale = rng.randint(1, 65535)
        shift = rng.randint(15, 22)
        passes.append(dict(name="rand_seed%d_K16" % seed, A=A, W=W,
                           scale=scale, shift=shift, k=16))

    # ---- Case 4 : small K values (K=1,3,7) single tile ----------------------
    for seed, kk in ((11, 1), (12, 3), (13, 7)):
        rng = random.Random(seed)
        A = rand_tile(rng)
        W = rand_tile(rng)
        passes.append(dict(name="rand_seed%d_K%d" % (seed, kk), A=A, W=W,
                           scale=32768, shift=17, k=kk))

    # ---- Case 5 : saturation boundary (max +7 / min -8) ---------------------
    # +7 x +7 over K=16 = +784 -> saturates HIGH ; +7 x -8 = -896 -> sat LOW.
    passes.append(dict(name="sat_high_all+7", A=const_tile(7), W=const_tile(7),
                       scale=32768, shift=15, k=16))
    passes.append(dict(name="sat_low_A+7_W-8", A=const_tile(7), W=const_tile(-8),
                       scale=32768, shift=15, k=16))
    # min x min = +64 each -> +1024 -> sat HIGH
    passes.append(dict(name="sat_high_all-8", A=const_tile(-8), W=const_tile(-8),
                       scale=32768, shift=15, k=16))
    # mixed extreme with a scale that lands mid-range (round exercise)
    rng = random.Random(99)
    A = [[7 if (i + j) % 2 else -8 for j in range(TILE)] for i in range(TILE)]
    W = [[-8 if (i + j) % 3 else 7 for j in range(TILE)] for i in range(TILE)]
    passes.append(dict(name="extreme_mixed", A=A, W=W, scale=32768, shift=18, k=16))

    # ---- Case 6 : M/N software tiling -> 32x32 GEMM as 2x2 = 4 passes --------
    # One 32x32x16 problem, tiled into four 16x16 output sub-tiles.
    rng = random.Random(2024)
    Kbig = 16
    Mbig, Nbig = 32, 32
    Abig = [[rng.randint(-8, 7) for _ in range(Kbig)] for _ in range(Mbig)]
    Wbig = [[rng.randint(-8, 7) for _ in range(Nbig)] for _ in range(Kbig)]
    scale_mn, shift_mn = 32768, 17
    mn_pass_names = []
    for ti in range(2):        # row block
        for tj in range(2):    # col block
            Asub = [[Abig[ti * 16 + m][k] for k in range(16)] for m in range(16)]
            Wsub = [[Wbig[k][tj * 16 + n] for n in range(16)] for k in range(16)]
            nm = "mn_tile_r%d_c%d" % (ti, tj)
            passes.append(dict(name=nm, A=Asub, W=Wsub,
                               scale=scale_mn, shift=shift_mn, k=16))
            mn_pass_names.append(nm)
    checks.append(dict(kind="mn_tiling", desc="32x32x16 GEMM reconstructed from 4 sub-tiles",
                       passes=mn_pass_names))

    # ---- Case 7 : K software tiling -> K=32 as two K=16 passes ---------------
    # scale=1.0 (32768), shift=15 so each pass out == its partial acc EXACTLY
    # (operands kept small so partials AND total stay within INT8 range); host
    # adds the two pass outputs to reconstruct the full-K result.
    rng = random.Random(555)
    Kfull = 32
    # keep magnitudes small: operands in [-2,2] -> |partial| <= 16*4=64, |full|<=128
    Ak = [[rng.randint(-2, 2) for _ in range(Kfull)] for _ in range(16)]
    Wk = [[rng.randint(-2, 2) for _ in range(16)] for _ in range(Kfull)]
    ktile_names = []
    for t in range(2):
        Asub = [[Ak[m][t * 16 + k] for k in range(16)] for m in range(16)]
        Wsub = [[Wk[t * 16 + k][n] for n in range(16)] for k in range(16)]
        nm = "k_tile_p%d" % t
        passes.append(dict(name=nm, A=Asub, W=Wsub, scale=32768, shift=15, k=16))
        ktile_names.append(nm)
    checks.append(dict(kind="k_tiling", desc="K=32 reconstructed by host-add of two K=16 passes",
                       passes=ktile_names,
                       full=dict(A=Ak, W=Wk, K=Kfull, scale=32768, shift=15)))

    return passes, checks


def emit(passes, checks):
    os.makedirs(VDIR, exist_ok=True)
    # per-pass golden expected + packed operands
    wmem_lines, amem_lines, exp_lines = [], [], []
    plan = []
    for idx, p in enumerate(passes):
        acc = int4_matmul(p["A"], p["W"], p["k"])
        int8 = requant_tile(acc, p["scale"], p["shift"])
        p["_int8"] = int8
        p["_acc"] = acc
        wwords = pack_weight_words(p["W"])
        awords = pack_act_words(p["A"])
        for w in wwords:
            wmem_lines.append("%08x" % w)
        for w in awords:
            amem_lines.append("%08x" % w)
        for b in expected_bytes_o_order(int8):
            exp_lines.append("%02x" % b)
        plan.append("%d %d %d" % (p["scale"], p["shift"], p["k"]))

    with open(os.path.join(VDIR, "wmem.txt"), "w") as f:
        f.write("\n".join(wmem_lines) + "\n")
    with open(os.path.join(VDIR, "amem.txt"), "w") as f:
        f.write("\n".join(amem_lines) + "\n")
    with open(os.path.join(VDIR, "expected.txt"), "w") as f:
        f.write("\n".join(exp_lines) + "\n")
    with open(os.path.join(VDIR, "passes.txt"), "w") as f:
        f.write("%d\n" % len(passes))
        f.write("\n".join(plan) + "\n")

    # human-readable manifest + golden for the Python cross-check
    manifest = dict(
        num_passes=len(passes),
        passes=[dict(name=p["name"], scale=p["scale"], shift=p["shift"], k=p["k"])
                for p in passes],
        checks=checks,
        int8=[p["_int8"] for p in passes],
    )
    with open(os.path.join(VDIR, "manifest.json"), "w") as f:
        json.dump(manifest, f, indent=2)
    return manifest


if __name__ == "__main__":
    ok, detail = selftest_2x2()
    print("GOLDEN SELF-TEST 2x2:", "PASS" if ok else "FAIL")
    print(json.dumps(detail, indent=2))
    if not ok:
        raise SystemExit(1)
    passes, checks = build_cases()
    manifest = emit(passes, checks)
    print("emitted %d passes to %s" % (len(passes), VDIR))
    for p in manifest["passes"]:
        print("  pass %-18s scale=%-6d shift=%-2d K=%d" %
              (p["name"], p["scale"], p["shift"], p["k"]))
