module TopModule (
  input clk,
  input load,
  input [255:0] data,
  output reg [255:0] q
);
  // 16x16 toroidal grid. Cell (r,c) is q[r*16 + c].
  integer r, c;
  integer rr, cc;
  integer dr, dc;
  integer cnt;
  reg [255:0] nextq;

  always @(*) begin
    nextq = 256'b0;
    for (r = 0; r < 16; r = r + 1) begin
      for (c = 0; c < 16; c = c + 1) begin
        cnt = 0;
        for (dr = -1; dr <= 1; dr = dr + 1) begin
          for (dc = -1; dc <= 1; dc = dc + 1) begin
            if (!(dr == 0 && dc == 0)) begin
              rr = (r + dr + 16) % 16;
              cc = (c + dc + 16) % 16;
              cnt = cnt + q[rr*16 + cc];
            end
          end
        end
        // 2 neighbours: unchanged; 3 neighbours: alive; else dead
        if (cnt == 3)
          nextq[r*16 + c] = 1'b1;
        else if (cnt == 2)
          nextq[r*16 + c] = q[r*16 + c];
        else
          nextq[r*16 + c] = 1'b0;
      end
    end
  end

  always @(posedge clk) begin
    if (load) q <= data;
    else      q <= nextq;
  end

  // power-up determinism (rtl_hygiene_lint --fix): reset-less registered
  // outputs default to 0 so they are not X at t=0.
  initial begin
    q = 0;
  end

endmodule
