module TopModule (
    input  clk,
    input  reset,
    input  in,
    output disc,
    output flag,
    output err
);
    // Moore FSM. State counts consecutive 1s and holds terminal outputs.
    localparam S0    = 4'd0;  // 0 consecutive ones (also reset state, prev=0)
    localparam S1    = 4'd1;  // 1 one
    localparam S2    = 4'd2;  // 2 ones
    localparam S3    = 4'd3;  // 3 ones
    localparam S4    = 4'd4;  // 4 ones
    localparam S5    = 4'd5;  // 5 ones
    localparam S6    = 4'd6;  // 6 ones
    localparam DISC  = 4'd7;  // saw 5 ones then a 0
    localparam FLAG  = 4'd8;  // saw 6 ones then a 0
    localparam ERR   = 4'd9;  // 7+ ones, hold until a 0

    reg [3:0] state, next;

    always @(*) begin
        case (state)
            S0:   next = in ? S1   : S0;
            S1:   next = in ? S2   : S0;
            S2:   next = in ? S3   : S0;
            S3:   next = in ? S4   : S0;
            S4:   next = in ? S5   : S0;
            S5:   next = in ? S6   : DISC;   // 5 ones then 0 -> discard
            S6:   next = in ? ERR  : FLAG;   // 6 ones then 0 -> flag; 7th one -> err
            DISC: next = in ? S1   : S0;     // disc output cycle, then resume counting
            FLAG: next = in ? S1   : S0;     // flag output cycle, then resume counting
            ERR:  next = in ? ERR  : S0;     // stay in error while 1s continue
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
