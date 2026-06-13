module TopModule (
  input              clk,
  input              load,
  input      [255:0] data,
  output reg [255:0] q
);

  // 16x16 toroid. Cell (r,c) lives at index r*16+c. Neighbours wrap modulo 16.
  integer r, c;
  reg [255:0] nxt;
  reg [3:0] rn, rp, cn, cp;   // r+1, r-1, c+1, c-1  (mod 16)
  reg [3:0] cnt;

  initial q = 256'b0;     // deterministic power-up (avoids decl-init PROCASSINIT)

  always @(*) begin
    for (r = 0; r < 16; r = r + 1) begin
      for (c = 0; c < 16; c = c + 1) begin
        rn = (r + 1) % 16;
        rp = (r + 15) % 16;
        cn = (c + 1) % 16;
        cp = (c + 15) % 16;
        cnt = q[rp*16 + cp] + q[rp*16 + c] + q[rp*16 + cn]
            + q[r *16 + cp]                + q[r *16 + cn]
            + q[rn*16 + cp] + q[rn*16 + c] + q[rn*16 + cn];
        case (cnt)
          4'd2:    nxt[r*16 + c] = q[r*16 + c];  // 2 neighbours: unchanged
          4'd3:    nxt[r*16 + c] = 1'b1;         // 3 neighbours: alive
          default: nxt[r*16 + c] = 1'b0;         // 0-1 or 4+: dead
        endcase
      end
    end
  end

  always @(posedge clk) begin
    if (load) q <= data;
    else      q <= nxt;
  end

endmodule
