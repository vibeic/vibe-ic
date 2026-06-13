module TopModule (
  input clk,
  input load,
  input [255:0] data,
  output reg [255:0] q
);

  // 16x16 toroidal Conway's Game of Life. Index = row*16 + col.
  integer r, c;
  integer rr, cc, dr, dc;
  reg [3:0] nr, nc;
  integer cnt;
  reg [255:0] nextq;

  always @(*) begin
    for (r = 0; r < 16; r = r + 1) begin
      for (c = 0; c < 16; c = c + 1) begin
        cnt = 0;
        for (dr = -1; dr <= 1; dr = dr + 1) begin
          for (dc = -1; dc <= 1; dc = dc + 1) begin
            if (!(dr == 0 && dc == 0)) begin
              nr = (r + dr + 16) % 16;
              nc = (c + dc + 16) % 16;
              cnt = cnt + q[nr*16 + nc];
            end
          end
        end
        // 2 neighbours: hold; 3 neighbours: alive; else dead
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
