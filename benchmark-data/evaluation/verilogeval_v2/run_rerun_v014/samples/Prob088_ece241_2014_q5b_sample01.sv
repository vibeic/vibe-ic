module TopModule (
  input  clk,
  input  areset,
  input  x,
  output z
);

  // One-hot encoding: A = 2'b01, B = 2'b10
  localparam A = 2'b01;
  localparam B = 2'b10;

  reg [1:0] state, next;

  always @(*) begin
    case (state)
      A:       next = x ? B : A;
      B:       next = B;
      default: next = A;
    endcase
  end

  always @(posedge clk or posedge areset) begin
    if (areset)
      state <= A;
    else
      state <= next;
  end

  // Mealy output
  // A: x=0 -> z=0, x=1 -> z=1   (z = x)
  // B: x=0 -> z=1, x=1 -> z=0   (z = ~x)
  assign z = (state == A) ? x : ~x;

endmodule
