

```
1. (optional) read ADDR_NAME0/1/VERSION to confirm chip identity
2. write ADDR_BLOCK0..15 = 512-bit padded message block
3. write ADDR_CTRL bit2 = MODE (1=SHA-256, 0=SHA-224)
   write ADDR_CTRL bit0 = 1 (INIT — single block) OR bit1 = 1 (NEXT — multi-block continuation)
4. poll ADDR_STATUS until bit0 (READY) = 1  // ~66 clk cycles
5. (optional) check bit1 (VALID) = 1
6. read ADDR_DIGEST0..7 = 256-bit digest (SHA-256) or first 224 bits (SHA-224)
7. for multi-block: repeat 2-6 with NEXT instead of INIT
```

