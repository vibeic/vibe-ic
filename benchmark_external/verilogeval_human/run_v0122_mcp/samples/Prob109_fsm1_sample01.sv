module TopModule (
  input clk,
  input in,
  input areset,
  output out
);

  localparam A = 1'b0, B = 1'b1;
  reg state;

  always @(posedge clk or posedge areset) begin
    if (areset)
      state <= B;
    else case (state)
      A:       state <= in ? A : B;
      B:       state <= in ? B : A;
      default: state <= B;
    endcase
  end

  assign out = (state == B);

endmodule
