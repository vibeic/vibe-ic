module TopModule (
  input clk,
  input j,
  input k,
  input reset,
  output out
);

  localparam A = 1'b0, B = 1'b1;
  reg state = A;
  reg next;

  always @(*) begin
    case (state)
      A: next = j ? B : A;
      B: next = k ? A : B;
      default: next = A;
    endcase
  end

  always @(posedge clk) begin
    if (reset)
      state <= A;
    else
      state <= next;
  end

  assign out = (state == B);

endmodule
