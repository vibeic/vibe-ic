module TopModule (
  input clk,
  input reset,
  input s,
  input w,
  output reg z
);

  localparam A    = 4'd0;
  localparam S0   = 4'd1;  // about to take 1st w of a window
  localparam S1_0 = 4'd2;  // after 1st w, ones=0
  localparam S1_1 = 4'd3;  // after 1st w, ones=1
  localparam S2_0 = 4'd4;  // after 2nd w, ones=0
  localparam S2_1 = 4'd5;  // after 2nd w, ones=1
  localparam S2_2 = 4'd6;  // after 2nd w, ones=2
  localparam ZON  = 4'd7;  // z=1 cycle, also acts as 1st-sample of next window
  localparam ZOFF = 4'd8;  // z=0 cycle, also acts as 1st-sample of next window

  reg [3:0] state, next;

  always @(*) begin
    case (state)
      A:    next = s ? S0 : A;
      S0:   next = w ? S1_1 : S1_0;
      ZON:  next = w ? S1_1 : S1_0;
      ZOFF: next = w ? S1_1 : S1_0;
      S1_0: next = w ? S2_1 : S2_0;
      S1_1: next = w ? S2_2 : S2_1;
      S2_0: next = ZOFF;              // final ones in {0,1}, never 2
      S2_1: next = w ? ZON : ZOFF;    // final ones = 2 if w=1
      S2_2: next = w ? ZOFF : ZON;    // final ones = 2 if w=0
      default: next = A;
    endcase
  end

  always @(posedge clk) begin
    if (reset)
      state <= A;
    else
      state <= next;
  end

  always @(*) begin
    z = (state == ZON);
  end

endmodule
