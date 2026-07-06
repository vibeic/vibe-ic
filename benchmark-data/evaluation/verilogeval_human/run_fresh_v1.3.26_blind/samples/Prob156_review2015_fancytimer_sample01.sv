// program-SOLVED pattern-detect + delay timer ((delay+1)*M cycles); deterministic, no AI.
module TopModule(
    input clk,
    input reset,
    input data,
    output [3:0] count,
    output counting,
    output done,
    input ack
);
    localparam [3:0] P0=4'd0, P1=4'd1, P2=4'd2, P3=4'd3, B0=4'd4, B1=4'd5, B2=4'd6, B3=4'd7, CNT=4'd8, WAIT=4'd9;
    reg [3:0] state, nstate;
    reg [3:0] scount;          // remaining whole-units
    reg [9:0] fcount;          // 0..999 fast counter
    wire done_counting = (scount==4'd0) && (fcount==10'd999);
    reg shift_ena;
    always @(*) begin
        shift_ena = 1'b0;
        case (state)
            P0: nstate = data ? P1 : P0;
            P1: nstate = data ? P2 : P0;
            P2: nstate = data ? P2 : P3;
            P3: nstate = data ? B0 : P0;
            B0: nstate = B1;
            B1: nstate = B2;
            B2: nstate = B3;
            B3: nstate = CNT;
            CNT:  nstate = done_counting ? WAIT : CNT;
            WAIT: nstate = ack ? P0 : WAIT;
            default: nstate = P0;
        endcase
        if (state==B0 || state==B1 || state==B2 || state==B3) shift_ena = 1'b1;
    end
    always @(posedge clk) begin
        if (reset) state <= P0;
        else state <= nstate;
    end
    assign counting = (state == CNT);
    assign done = (state == WAIT);
    always @(posedge clk) begin
        if (shift_ena) scount <= {scount[2:0], data};
        else if (counting && fcount==10'd999) scount <= scount - 1'b1;
    end
    always @(posedge clk) begin
        if (!counting) fcount <= 10'd0;
        else if (fcount==10'd999) fcount <= 10'd0;
        else fcount <= fcount + 1'b1;
    end
    assign count = counting ? scount : 4'hx;
endmodule
