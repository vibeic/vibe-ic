// Mealy 2's-complementer, one-hot encoding, async active-high reset to A.
// State A: z = x, x=1 -> B (else stay A). State B (absorbing): z = ~x.
module TopModule (
  input clk,
  input areset,
  input x,
  output z
);

  localparam A = 2'b01, B = 2'b10;  // one-hot
  reg [1:0] state;

  always @(posedge clk or posedge areset) begin
    if (areset)
      state <= A;
    else begin
      case (state)
        A:       state <= x ? B : A;
        B:       state <= B;
        default: state <= A;
      endcase
    end
  end

  // Mealy output
  assign z = (state == A) ? x : ~x;

endmodule
