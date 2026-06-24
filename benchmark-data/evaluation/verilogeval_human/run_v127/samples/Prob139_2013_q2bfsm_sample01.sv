module TopModule (
  input  clk,
  input  resetn,
  input  x,
  input  y,
  output f,
  output g
);

  // Moore motor-control FSM. Synchronous active-low reset to A.
  localparam A     = 4'd0;  // reset/begin state
  localparam B     = 4'd1;  // f=1 for one cycle
  localparam S0    = 4'd2;  // x-detector: nothing yet
  localparam S1    = 4'd3;  // x-detector: seen "1"
  localparam S2    = 4'd4;  // x-detector: seen "1,0"
  localparam G1    = 4'd5;  // g=1, first y-monitor cycle
  localparam G2    = 4'd6;  // g=1, second y-monitor cycle
  localparam GPERM = 4'd7;  // g=1 permanently
  localparam GOFF  = 4'd8;  // g=0 permanently

  reg [3:0] state, next;

  always @(*) begin
    case (state)
      A:     next = B;                 // reset deasserted -> pulse f next cycle
      B:     next = S0;                // f=1 this cycle, then monitor x
      S0:    next = x ? S1 : S0;
      S1:    next = x ? S1 : S2;       // overlap: a new 1 restarts the prefix
      S2:    next = x ? G1 : S0;       // "1,0,1" matched -> g state; "1,0,0" -> restart
      G1:    next = y ? GPERM : G2;
      G2:    next = y ? GPERM : GOFF;
      GPERM: next = GPERM;
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

  assign f = (state == B);
  assign g = (state == G1) || (state == G2) || (state == GPERM);

endmodule
