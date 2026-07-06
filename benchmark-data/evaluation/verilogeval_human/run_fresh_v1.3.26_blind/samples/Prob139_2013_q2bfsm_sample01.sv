module TopModule (
  input clk,
  input resetn,
  input x,
  input y,
  output f,
  output g
);

  // States
  localparam S_A     = 4'd0,  // reset / begin
             S_F     = 4'd1,  // f=1 for one cycle
             S_X0    = 4'd2,  // watching x, no progress
             S_X1    = 4'd3,  // saw 1
             S_X2    = 4'd4,  // saw 1,0
             S_G1    = 4'd5,  // g=1, first y-check cycle
             S_G2    = 4'd6,  // g=1, second y-check cycle
             S_GPERM = 4'd7,  // g=1 forever
             S_GOFF  = 4'd8;  // g=0 forever

  reg [3:0] state, next;

  always @(*) begin
    case (state)
      S_A:     next = S_F;
      S_F:     next = S_X0;
      S_X0:    next = x ? S_X1 : S_X0;
      S_X1:    next = x ? S_X1 : S_X2;      // saw 1; on 0 -> saw 1,0
      S_X2:    next = x ? S_G1 : S_X0;      // saw 1,0; on 1 -> detected 1,0,1
      S_G1:    next = y ? S_GPERM : S_G2;
      S_G2:    next = y ? S_GPERM : S_GOFF;
      S_GPERM: next = S_GPERM;
      S_GOFF:  next = S_GOFF;
      default: next = S_A;
    endcase
  end

  always @(posedge clk) begin
    if (!resetn)
      state <= S_A;
    else
      state <= next;
  end

  assign f = (state == S_F);
  assign g = (state == S_G1) || (state == S_G2) || (state == S_GPERM);

endmodule
