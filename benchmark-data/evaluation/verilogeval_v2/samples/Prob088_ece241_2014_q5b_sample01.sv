module TopModule (
  input  clk,
  input  areset,
  input  x,
  output z
);
  // One-hot encoded Mealy 2's complementer
  localparam A = 2'b01, B = 2'b10;
  reg [1:0] state;
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
  // Mealy outputs
  assign z = state[0] ? (x ? 1'b1 : 1'b0)   // in A
                      : (x ? 1'b0 : 1'b1);  // in B
endmodule
