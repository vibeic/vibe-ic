module TopModule (
    input  clk,
    input  reset,
    input  in,
    output disc,
    output flag,
    output err
);
    // Moore FSM. States count consecutive 1s seen so far.
    // C0..C6 = number of consecutive 1s currently accumulated (capped概念).
    // DISC  = reached after 0 following exactly 5 ones (pattern 0111110)
    // FLAG  = reached after 0 following exactly 6 ones (pattern 01111110)
    // ERR   = reached after 7th consecutive 1; stays until a 0 arrives.
    localparam C0   = 4'd0,  // 0 consecutive ones
               C1   = 4'd1,
               C2   = 4'd2,
               C3   = 4'd3,
               C4   = 4'd4,
               C5   = 4'd5,
               C6   = 4'd6,
               DISC = 4'd7,
               FLAG = 4'd8,
               ERR  = 4'd9;

    reg [3:0] state, next;

    always @(*) begin
        case (state)
            C0:   next = in ? C1   : C0;
            C1:   next = in ? C2   : C0;
            C2:   next = in ? C3   : C0;
            C3:   next = in ? C4   : C0;
            C4:   next = in ? C5   : C0;
            C5:   next = in ? C6   : DISC; // five 1s then 0 -> discard
            C6:   next = in ? ERR  : FLAG; // six 1s then 0 -> flag; 7th one -> err
            DISC: next = in ? C1   : C0;
            FLAG: next = in ? C1   : C0;
            ERR:  next = in ? ERR  : C0;   // remain in err until a 0
            default: next = C0;
        endcase
    end

    always @(posedge clk) begin
        if (reset)
            state <= C0;
        else
            state <= next;
    end

    assign disc = (state == DISC);
    assign flag = (state == FLAG);
    assign err  = (state == ERR);
endmodule
