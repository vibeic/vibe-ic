module TopModule (
  input clk,
  input load,
  input [255:0] data,
  output reg [255:0] q
);

  integer r, c;
  integer rr, cc;
  integer dr, dc;
  integer count;
  reg [255:0] nextq;

  function automatic integer idx;
    input integer row;
    input integer col;
    begin
      idx = row * 16 + col;
    end
  endfunction

  always @(*) begin
    for (r = 0; r < 16; r = r + 1) begin
      for (c = 0; c < 16; c = c + 1) begin
        count = 0;
        for (dr = -1; dr <= 1; dr = dr + 1) begin
          for (dc = -1; dc <= 1; dc = dc + 1) begin
            if (!(dr == 0 && dc == 0)) begin
              rr = (r + dr + 16) % 16;
              cc = (c + dc + 16) % 16;
              count = count + q[idx(rr, cc)];
            end
          end
        end
        case (count)
          2:       nextq[idx(r, c)] = q[idx(r, c)];
          3:       nextq[idx(r, c)] = 1'b1;
          default: nextq[idx(r, c)] = 1'b0;
        endcase
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
