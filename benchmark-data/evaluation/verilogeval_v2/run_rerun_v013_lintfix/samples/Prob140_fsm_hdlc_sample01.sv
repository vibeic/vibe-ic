module TopModule (
  input  clk,
  input  reset,
  input  in,
  output disc,
  output flag,
  output err
);

  // States track number of consecutive 1s seen (0..6), plus output states
  localparam S0    = 4'd0;  // 0 consecutive 1s
  localparam S1    = 4'd1;  // 1 consecutive 1
  localparam S2    = 4'd2;
  localparam S3    = 4'd3;
  localparam S4    = 4'd4;
  localparam S5    = 4'd5;  // 5 consecutive 1s
  localparam S6    = 4'd6;  // 6 consecutive 1s
  localparam DISC  = 4'd7;  // saw 0 after exactly 5 ones
  localparam FLAG  = 4'd8;  // saw 0 after exactly 6 ones
  localparam ERR   = 4'd9;  // 7+ consecutive 1s

  reg [3:0] state, next;

  always @(*) begin
    case (state)
      S0:   next = in ? S1   : S0;
      S1:   next = in ? S2   : S0;
      S2:   next = in ? S3   : S0;
      S3:   next = in ? S4   : S0;
      S4:   next = in ? S5   : S0;
      S5:   next = in ? S6   : DISC;  // after 5 ones, a 0 -> discard
      S6:   next = in ? ERR  : FLAG;  // after 6 ones, a 0 -> flag; another 1 -> err
      DISC: next = in ? S1   : S0;
      FLAG: next = in ? S1   : S0;
      ERR:  next = in ? ERR  : S0;    // stay in err until a 0 arrives
      default: next = S0;
    endcase
  end

  always @(posedge clk) begin
    if (reset)
      state <= S0;
    else
      state <= next;
  end

  assign disc = (state == DISC);
  assign flag = (state == FLAG);
  assign err  = (state == ERR);

endmodule
