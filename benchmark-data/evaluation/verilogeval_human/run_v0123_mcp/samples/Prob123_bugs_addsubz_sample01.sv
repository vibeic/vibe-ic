module TopModule (
  input do_sub,
  input [7:0] a,
  input [7:0] b,
  output reg [7:0] out,
  output reg result_is_zero
);

  always @(*) begin
    case (do_sub)
      1'b0: out = a + b;
      1'b1: out = a - b;
    endcase

    // Bug fix: result_is_zero must be assigned in every path (else latch),
    // and the original only ever set it to 1.
    if (out == 8'h00)
      result_is_zero = 1'b1;
    else
      result_is_zero = 1'b0;
  end

endmodule
