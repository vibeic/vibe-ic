module TopModule(
    input  clk,
    input  reset,
    input  data,
    input  done_counting,
    input  ack,
    output shift_ena,
    output counting,
    output done
);
    localparam S0=4'd0, S1=4'd1, S2=4'd2, S3=4'd3,
               SH1=4'd4, SH2=4'd5, SH3=4'd6, SH4=4'd7,
               CNT=4'd8, DONE=4'd9;

    reg [3:0] state, next;

    always @(*) begin
        case (state)
            S0:  next = data ? S1 : S0;
            S1:  next = data ? S2 : S0;
            S2:  next = data ? S2 : S3;
            S3:  next = data ? SH1 : S0;
            SH1: next = SH2;
            SH2: next = SH3;
            SH3: next = SH4;
            SH4: next = CNT;
            CNT: next = done_counting ? DONE : CNT;
            DONE: next = ack ? S0 : DONE;
            default: next = S0;
        endcase
    end

    always @(posedge clk) begin
        if (reset) state <= S0;
        else       state <= next;
    end

    assign shift_ena = (state==SH1)||(state==SH2)||(state==SH3)||(state==SH4);
    assign counting  = (state==CNT);
    assign done      = (state==DONE);

endmodule
