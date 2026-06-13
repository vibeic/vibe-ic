module TopModule (
    input  clk,
    input  reset,
    input  s,
    input  w,
    output z
);

    // States
    localparam A      = 4'd0;  // idle, waiting for s
    localparam S1     = 4'd1;  // window cycle 1 (count = 0)
    localparam S2_0   = 4'd2;  // window cycle 2, count 0
    localparam S2_1   = 4'd3;  // window cycle 2, count 1
    localparam S3_0   = 4'd4;  // window cycle 3, count 0
    localparam S3_1   = 4'd5;  // window cycle 3, count 1
    localparam S3_2   = 4'd6;  // window cycle 3, count 2
    localparam RZ1    = 4'd7;  // result: exactly two ones -> z=1, start new window
    localparam RZ0    = 4'd8;  // result: not two ones    -> z=0, start new window

    reg [3:0] state, next;

    always @(*) begin
        case (state)
            A:    next = s ? S1 : A;
            S1:   next = w ? S2_1 : S2_0;
            S2_0: next = w ? S3_1 : S3_0;
            S2_1: next = w ? S3_2 : S3_1;
            S3_0: next = w ? RZ0  : RZ0;   // total 0 or 1 -> not two
            S3_1: next = w ? RZ1  : RZ0;   // total 2 or 1
            S3_2: next = w ? RZ0  : RZ1;   // total 3 or 2
            RZ1:  next = S1;   // z-output cycle; next window begins after
            RZ0:  next = S1;
            default: next = A;
        endcase
    end

    always @(posedge clk) begin
        if (reset)
            state <= A;
        else
            state <= next;
    end

    assign z = (state == RZ1);

endmodule
