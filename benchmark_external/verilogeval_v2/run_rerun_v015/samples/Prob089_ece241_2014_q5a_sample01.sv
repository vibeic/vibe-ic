module TopModule (
  input  clk,
  input  areset,
  input  x,
  output z
);

  // Moore serial 2's complementer, LSB first: copy input up to and
  // including the first '1', then invert all subsequent bits.
  // States (output = function of state only):
  //   A: no '1' seen yet, emit 0
  //   B: a '1' has been seen, emit 1
  //   C: a '1' has been seen, emit 0
  localparam A = 2'd0, B = 2'd1, C = 2'd2;
  reg [1:0] state;

  always @(posedge clk or posedge areset) begin
    if (areset)
      state <= A;
    else begin
      case (state)
        A:       state <= x ? B : A;
        B:       state <= x ? C : B;  // seen 1: emit ~x
        C:       state <= x ? C : B;  // seen 1: emit ~x
        default: state <= A;
      endcase
    end
  end

  assign z = (state == B);

endmodule
