module TopModule (
  input clk,
  input reset,
  input in,
  output disc,
  output flag,
  output err
);
    // Moore FSM. State = run-length of consecutive 1s, plus output states.
    localparam ZERO = 4'd0,  // previous input was 0 (also reset state)
               ONE  = 4'd1,
               TWO  = 4'd2,
               THREE= 4'd3,
               FOUR = 4'd4,
               FIVE = 4'd5,
               SIX  = 4'd6,
               DISC = 4'd7,  // saw 0111110 -> discard
               FLAG = 4'd8,  // saw 01111110 -> flag
               ERR  = 4'd9;  // 7+ ones -> error, hold until a 0

    reg [3:0] state, next;

    always @(*) begin
        case (state)
            ZERO : next = in ? ONE  : ZERO;
            ONE  : next = in ? TWO  : ZERO;
            TWO  : next = in ? THREE: ZERO;
            THREE: next = in ? FOUR : ZERO;
            FOUR : next = in ? FIVE : ZERO;
            FIVE : next = in ? SIX  : DISC;  // 5 ones then 0 -> discard
            SIX  : next = in ? ERR  : FLAG;  // 6 ones then 0 -> flag; 7th 1 -> err
            DISC : next = in ? ONE  : ZERO;
            FLAG : next = in ? ONE  : ZERO;
            ERR  : next = in ? ERR  : ZERO;  // hold error while 1s continue
            default: next = ZERO;
        endcase
    end

    always @(posedge clk) begin
        if (reset) state <= ZERO;
        else       state <= next;
    end

    assign disc = (state == DISC);
    assign flag = (state == FLAG);
    assign err  = (state == ERR);
endmodule
