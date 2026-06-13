module TopModule (
  input clk,
  input j,
  input k,
  input areset,
  output out
);

  localparam A = 1'b0, B = 1'b1;
  reg state;
  reg next;

  always @(*) begin
    case (state)
      A: next = j ? B : A;
      B: next = k ? A : B;
      default: next = A;
    endcase
  end

  always @(posedge clk or posedge areset) begin
    if (areset)
      state <= A;
    else
      state <= next;
  end

  assign out = (state == B);

endmodule
