module TopModule (
  input              clk,
  input              load,
  input      [255:0] data,
  output reg [255:0] q
);

  integer r, c;
  integer rr, cc;
  integer dr, dc;
  integer nr, nc;
  integer cnt;
  reg [255:0] nextq;

  // index helper: cell at (row, col) -> bit row*16 + col
  function integer idx;
    input integer row;
    input integer col;
    begin
      idx = row*16 + col;
    end
  endfunction

  always @(*) begin
    nextq = 256'b0;
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
        if (cnt == 2)
          nextq[r*16 + c] = q[r*16 + c];
        else if (cnt == 3)
          nextq[r*16 + c] = 1'b1;
        else
          nextq[r*16 + c] = 1'b0;
      end
    end
  end

  always @(posedge clk) begin
    if (load)
      q <= data;
    else
      q <= nextq;
  end

endmodule
