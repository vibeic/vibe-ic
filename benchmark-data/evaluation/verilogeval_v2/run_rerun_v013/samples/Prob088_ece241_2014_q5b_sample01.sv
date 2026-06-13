module TopModule (
  input  clk,
  input  areset,
  input  x,
  output z
);

  // One-hot encoding: state[0] = A, state[1] = B.
  // Mealy 2's complementer.
  //   A,x=0 (z=0)->A    A,x=1 (z=1)->B
  //   B,x=0 (z=1)->B    B,x=1 (z=0)->B
  reg [1:0] state;

  localparam A = 2'b01;
  localparam B = 2'b10;

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

  // Mealy output: depends on current state and input.
  assign z = (state == A) ? x : ~x;

endmodule
