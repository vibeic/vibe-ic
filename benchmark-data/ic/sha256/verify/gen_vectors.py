#!/usr/bin/env python3
"""
gen_vectors.py -- generate NIST-padded SHA-256/224 message blocks + golden
digests (golden = Python hashlib, which is the de-facto NIST FIPS-180-4 oracle)
for the comprehensive functional/coverage testbench.

Output format (one test per line):
  <mode> <nblocks> <exp_digest_64hex> <blk0_128hex> [<blk1_128hex> ...]
where:
  mode      = 1 (SHA-256) / 0 (SHA-224)
  nblocks   = number of 512-bit blocks after padding
  exp       = 64-hex (256 bit). For SHA-224 the low 32 bits are zero-filled.
  blkN      = 128-hex (512 bit) padded block, BLOCK0 = most-significant word.

Padding is FIPS-180-4 sec 5.1.1 (done in SW per L2/L4: HW takes padded blocks).
"""
import hashlib, sys, random

def pad(msg: bytes):
    ml = len(msg) * 8
    padded = msg + b'\x80'
    while (len(padded) % 64) != 56:
        padded += b'\x00'
    padded += ml.to_bytes(8, 'big')
    # split into 512-bit (64-byte) blocks
    return [padded[i:i+64] for i in range(0, len(padded), 64)]

def blk_hex(b: bytes) -> str:
    # BLOCK0 is most-significant 32-bit word; bytes are already big-endian.
    return b.hex()

def emit(f, mode, msg):
    blocks = pad(msg)
    if mode == 1:
        d = hashlib.sha256(msg).hexdigest()
    else:
        d = hashlib.sha224(msg).hexdigest() + ('0' * 8)  # zero-fill low word
    parts = [str(mode), str(len(blocks)), d] + [blk_hex(b) for b in blocks]
    f.write(' '.join(parts) + '\n')

def main():
    out = sys.argv[1] if len(sys.argv) > 1 else 'vectors.txt'
    random.seed(0xC0FFEE)
    with open(out, 'w') as f:
        # --- NIST FIPS-180-4 official KAT vectors (App A/B/C) ---
        emit(f, 1, b'abc')                          # SHA-256 "abc"
        emit(f, 1, b'')                             # SHA-256 empty
        emit(f, 1, b'abcdbcdecdefdefgefghfghighijhijkijkljklmklmnlmnomnopnopq')  # 448-bit 2-block
        emit(f, 0, b'abc')                          # SHA-224 "abc"
        emit(f, 0, b'abcdbcdecdefdefgefghfghighijhijkijkljklmklmnlmnomnopnopq')  # SHA-224 multi-block
        emit(f, 1, b'a' * 1000000)                  # 1M 'a' long message (NIST AppB)
        emit(f, 0, b'a' * 1000000)                  # 1M 'a' SHA-224 long message
        # --- message-length corner cases (L7 7.1.2) ---
        for n in [1, 55, 56, 64, 119, 120, 1024]:
            emit(f, 1, bytes((random.randint(0, 255) for _ in range(n))))
            emit(f, 0, bytes((random.randint(0, 255) for _ in range(n))))
        # --- 1000 random messages, lengths 0..2KB (L7 7.1.2) ---
        for _ in range(1000):
            n = random.randint(0, 2048)
            msg = bytes((random.randint(0, 255) for _ in range(n)))
            mode = random.choice([0, 1])
            emit(f, mode, msg)
    print("wrote", out)

if __name__ == '__main__':
    main()
