module TopModule (
  input clk,
  input reset,
  input in,
  output disc,
  output flag,
  output err
);
  // Moore FSM. States encode how many consecutive 1s have been seen,
  // plus terminal output states DISC/FLAG/ERR which assert for one cycle.
  localparam S0   = 4'd0;  // saw 0 ones (or just reset)
  localparam S1   = 4'd1;  // 1 one
  localparam S2   = 4'd2;
  localparam S3   = 4'd3;
  localparam S4   = 4'd4;
  localparam S5   = 4'd5;  // 5 ones
  localparam S6   = 4'd6;  // 6 ones
  localparam DISC = 4'd7;  // discard a bit (after 0111110)
  localparam FLAG = 4'd8;  // flag (after 01111110)
  localparam ERR  = 4'd9;  // error (>=7 ones), sticky until a 0

  reg [3:0] state, next;

  always @(*) begin
    case (state)
      S0:   next = in ? S1 : S0;
      S1:   next = in ? S2 : S0;
      S2:   next = in ? S3 : S0;
      S3:   next = in ? S4 : S0;
      S4:   next = in ? S5 : S0;
      S5:   next = in ? S6 : DISC;   // 5 ones then 0 -> discard
      S6:   next = in ? ERR : FLAG;  // 6 ones then 1 -> error, then 0 -> flag
      DISC: next = in ? S1 : S0;
      FLAG: next = in ? S1 : S0;
      ERR:  next = in ? ERR : S0;    // stay in err until a 0
      default: next = S0;
    endcase
  end

  always @(posedge clk) begin
    if (reset) state <= S0;
    else       state <= next;
  end

  assign disc = (state == DISC);
  assign flag = (state == FLAG);
  assign err  = (state == ERR);
endmodule
