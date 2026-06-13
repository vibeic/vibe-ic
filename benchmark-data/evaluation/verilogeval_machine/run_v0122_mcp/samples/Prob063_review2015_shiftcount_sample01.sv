// Prob063_review2015_shiftcount — 4-bit shift/down-counter register.
// shift_ena priority: shift right, data -> MSB (q[3]).
// else count_ena: decrement.
// No reset; reset-less registered output powers up at 0 via initial block.
module TopModule (
  input clk,
  input shift_ena,
  input count_ena,
  input data,
  output reg [3:0] q
);

  initial q = 4'b0;

  always @(posedge clk) begin
    if (shift_ena)
      q <= {data, q[3:1]};
    else if (count_ena)
      q <= q - 4'd1;
    // both low: hold
  end

endmodule
