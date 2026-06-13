module TopModule (
  input clk,
  input resetn,
  input x,
  input y,
  output f,
  output g
);

  // Moore FSM.
  // A      : reset state (held while resetn=0)
  // FP     : f=1 for one cycle (right after reset release)
  // X0     : looking for first '1' of x-sequence 1,0,1
  // X1     : saw '1', looking for '0'
  // X2     : saw '1','0', looking for '1'
  // G1     : g=1, first cycle monitoring y
  // G2     : g=1, second cycle monitoring y
  // GHOLD  : g=1 permanently
  // GOFF   : g=0 permanently
  localparam A=4'd0, FP=4'd1, X0=4'd2, X1=4'd3, X2=4'd4,
             G1=4'd5, G2=4'd6, GHOLD=4'd7, GOFF=4'd8;

  reg [3:0] state, next;

  always @(*) begin
    case (state)
      A:     next = FP;                       // after reset de-assert, pulse f next
      FP:    next = X0;                        // f pulse done, start monitoring x
      X0:    next = x ? X1 : X0;
      X1:    next = x ? X1 : X2;               // saw 1; need a 0 next
      X2:    next = x ? G1 : X0;               // saw 1,0; a 1 completes 1,0,1
      G1:    next = y ? GHOLD : G2;            // first y-check cycle
      G2:    next = y ? GHOLD : GOFF;          // second y-check cycle
      GHOLD: next = GHOLD;
      GOFF:  next = GOFF;
      default: next = A;
    endcase
  end

  always @(posedge clk) begin
    if (!resetn)
      state <= A;
    else
      state <= next;
  end

  // Moore outputs.
  assign f = (state == FP);
  assign g = (state == G1) || (state == G2) || (state == GHOLD);

endmodule
