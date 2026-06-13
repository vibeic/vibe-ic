module TopModule (
  input  clk,
  input  areset,
  input  x,
  output z
);
  // One-hot encoding: state[0]=A, state[1]=B
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

  // Mealy output: A & x=1 -> z=1; B & x=0 -> z=1; otherwise z=0
  assign z = (state == A) ? x : ~x;
endmodule
