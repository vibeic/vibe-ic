module TopModule (
  input  clk,
  input  areset,
  input  x,
  output z
);

  // One-hot encoding: A = 2'b01, B = 2'b10
  localparam [1:0] A = 2'b01,
                   B = 2'b10;

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

  // Mealy output: in A z=x, in B z=~x
  assign z = (state == A) ? x : ~x;

endmodule
