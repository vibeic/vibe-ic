module TopModule (
  input clk,
  input in,
  input areset,
  output out
);

  localparam A = 1'b0,
             B = 1'b1;

  reg state, next_state;

  always @(*) begin
    case (state)
      A:       next_state = in ? A : B;
      B:       next_state = in ? B : A;
      default: next_state = B;
    endcase
  end

  always @(posedge clk or posedge areset) begin
    if (areset)
      state <= B;
    else
      state <= next_state;
  end

  assign out = (state == B);

endmodule
