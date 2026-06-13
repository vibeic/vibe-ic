module TopModule (
  input  clk,
  input  resetn,
  input  x,
  input  y,
  output f,
  output g
);

  localparam A    = 4'd0,  // reset state
             B    = 4'd1,  // f=1 for one cycle
             X0   = 4'd2,  // waiting for x sequence: looking for 1
             X1   = 4'd3,  // saw 1, expect 0
             X2   = 4'd4,  // saw 1,0, expect 1
             G1   = 4'd5,  // g=1, first y-check cycle
             G2   = 4'd6,  // g=1, second y-check cycle
             GON  = 4'd7,  // g=1 permanently
             GOFF = 4'd8;  // g=0 permanently

  reg [3:0] state, next;

  always @(*) begin
    case (state)
      A:    next = B;
      B:    next = X0;
      X0:   next = x ? X1 : X0;
      X1:   next = x ? X1 : X2;
      X2:   next = x ? G1 : X0;
      G1:   next = y ? GON : G2;
      G2:   next = y ? GON : GOFF;
      GON:  next = GON;
      GOFF: next = GOFF;
      default: next = A;
    endcase
  end

  always @(posedge clk) begin
    if (!resetn) state <= A;
    else         state <= next;
  end

  assign f = (state == B);
  assign g = (state == G1) || (state == G2) || (state == GON);

endmodule
