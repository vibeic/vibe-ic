module TopModule (
  input  clk,
  input  areset,
  input  x,
  output z
);
  // 2's complement LSB-first: copy bits up to and including the first 1,
  // then invert all subsequent bits.
  // State 0 (A): no 1 seen yet -> pass x through (z = x)
  // State 1 (B): a 1 has been seen -> invert (z = ~x)
  localparam A = 1'b0, B = 1'b1;
  reg state;

  always @(posedge clk or posedge areset) begin
    if (areset)
      state <= A;
    else begin
      case (state)
        A: state <= x ? B : A;
        B: state <= B;
        default: state <= A;
      endcase
    end
  end

  assign z = (state == A) ? x : ~x;
endmodule
