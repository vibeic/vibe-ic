// program-SOLVED HDLC consecutive-1s counter (Moore); deterministic, no AI.
module TopModule(
    input clk,
    input reset,
    input in,
    output disc,
    output flag,
    output err
);
    localparam [3:0] C0=4'd0, C1=4'd1, C2=4'd2, C3=4'd3, C4=4'd4, C5=4'd5, C6=4'd6, SERR=4'd7, SDISC=4'd8, SFLAG=4'd9;
    reg [3:0] state, nstate;
    always @(*) begin
        case (state)
            C0: nstate = in ? C1 : C0;
            C1: nstate = in ? C2 : C0;
            C2: nstate = in ? C3 : C0;
            C3: nstate = in ? C4 : C0;
            C4: nstate = in ? C5 : C0;
            C5: nstate = in ? C6 : SDISC;
            C6: nstate = in ? SERR : SFLAG;
            SERR:  nstate = in ? SERR : C0;
            SDISC: nstate = in ? C1 : C0;
            SFLAG: nstate = in ? C1 : C0;
            default: nstate = C0;
        endcase
    end
    always @(posedge clk) begin
        if (reset) state <= C0;
        else state <= nstate;
    end
    assign disc = (state == SDISC);
    assign flag = (state == SFLAG);
    assign err  = (state == SERR);
endmodule
