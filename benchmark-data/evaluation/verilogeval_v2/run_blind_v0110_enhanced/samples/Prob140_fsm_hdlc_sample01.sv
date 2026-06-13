module TopModule(
    input  clk,
    input  reset,
    input  in,
    output disc,
    output flag,
    output err
);
    // Moore FSM. States track number of consecutive 1s seen (CNT0..CNT6),
    // plus output-asserting states DISC, FLAG, ERR.
    localparam CNT0 = 4'd0, CNT1 = 4'd1, CNT2 = 4'd2, CNT3 = 4'd3,
               CNT4 = 4'd4, CNT5 = 4'd5, CNT6 = 4'd6,
               DISC = 4'd7, FLAG = 4'd8, ERR = 4'd9;

    reg [3:0] state, next;

    always @(*) begin
        case (state)
            CNT0: next = in ? CNT1 : CNT0;
            CNT1: next = in ? CNT2 : CNT0;
            CNT2: next = in ? CNT3 : CNT0;
            CNT3: next = in ? CNT4 : CNT0;
            CNT4: next = in ? CNT5 : CNT0;
            CNT5: next = in ? CNT6 : DISC;   // 0111110 -> discard
            CNT6: next = in ? ERR  : FLAG;   // 01111110 -> flag ; 7th 1 -> err
            ERR:  next = in ? ERR  : CNT0;   // stay in err while 1s continue
            DISC: next = in ? CNT1 : CNT0;   // the 0 already consumed
            FLAG: next = in ? CNT1 : CNT0;
            default: next = CNT0;
        endcase
    end

    always @(posedge clk) begin
        if (reset) state <= CNT0;
        else       state <= next;
    end

    assign disc = (state == DISC);
    assign flag = (state == FLAG);
    assign err  = (state == ERR);
endmodule
