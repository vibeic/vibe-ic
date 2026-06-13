module TopModule (
    input  clk,
    input  reset,
    input  in,
    output disc,
    output flag,
    output err
);
    // Moore FSM counting consecutive 1s.
    // States track # of consecutive 1s seen, plus dedicated output states.
    localparam S_IDLE = 4'd0; // last input was 0 (or counts reset)
    localparam S_1    = 4'd1; // 1 one
    localparam S_2    = 4'd2;
    localparam S_3    = 4'd3;
    localparam S_4    = 4'd4;
    localparam S_5    = 4'd5; // 5 consecutive ones
    localparam S_6    = 4'd6; // 6 consecutive ones
    localparam S_DISC = 4'd7; // saw 0111110 -> discard
    localparam S_FLAG = 4'd8; // saw 01111110 -> flag
    localparam S_ERR  = 4'd9; // 7+ consecutive ones -> error (stay until a 0)

    reg [3:0] state, next;

    always @(*) begin
        case (state)
            S_IDLE: next = in ? S_1 : S_IDLE;
            S_1:    next = in ? S_2 : S_IDLE;
            S_2:    next = in ? S_3 : S_IDLE;
            S_3:    next = in ? S_4 : S_IDLE;
            S_4:    next = in ? S_5 : S_IDLE;
            S_5:    next = in ? S_6   : S_DISC; // 5 ones then 0 -> discard
            S_6:    next = in ? S_ERR : S_FLAG; // 6 ones then 0 -> flag; else 7th 1 -> err
            S_DISC: next = in ? S_1   : S_IDLE; // resume normal counting
            S_FLAG: next = in ? S_1   : S_IDLE;
            S_ERR:  next = in ? S_ERR : S_IDLE; // hold err until a 0 arrives
            default:next = S_IDLE;
        endcase
    end

    always @(posedge clk) begin
        if (reset) state <= S_IDLE;
        else       state <= next;
    end

    assign disc = (state == S_DISC);
    assign flag = (state == S_FLAG);
    assign err  = (state == S_ERR);
endmodule
