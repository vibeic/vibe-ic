module TopModule (
    input  clk,
    input  reset,
    input  s,
    input  w,
    output z
);

    localparam A     = 4'd0,
               P1    = 4'd1,  // sample 1 of window
               P2_c0 = 4'd2,  // sample 2, count so far 0
               P2_c1 = 4'd3,  // sample 2, count so far 1
               P3_c0 = 4'd4,  // sample 3, count so far 0
               P3_c1 = 4'd5,  // sample 3, count so far 1
               P3_c2 = 4'd6,  // sample 3, count so far 2
               WZ0   = 4'd7,  // z=0, also sample 1 of next window
               WZ1   = 4'd8;  // z=1, also sample 1 of next window

    reg [3:0] state, next;

    always @(*) begin
        case (state)
            A:     next = s ? P1 : A;
            P1:    next = w ? P2_c1 : P2_c0;
            P2_c0: next = w ? P3_c1 : P3_c0;
            P2_c1: next = w ? P3_c2 : P3_c1;
            P3_c0: next = WZ0;
            P3_c1: next = w ? WZ1 : WZ0;
            P3_c2: next = w ? WZ0 : WZ1;
            WZ0:   next = w ? P2_c1 : P2_c0;
            WZ1:   next = w ? P2_c1 : P2_c0;
            default: next = A;
        endcase
    end

    always @(posedge clk) begin
        if (reset)
            state <= A;
        else
            state <= next;
    end

    assign z = (state == WZ1);

endmodule
