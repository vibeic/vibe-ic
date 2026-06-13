module TopModule (
    input  clk,
    input  reset,
    input  s,
    input  w,
    output z
);

    // States
    localparam A     = 4'd0;  // wait for s
    localparam B0    = 4'd1;  // window: 1st sample cycle, z=0 (after s)
    localparam B1_0  = 4'd2;  // 1 sample taken, count 0
    localparam B1_1  = 4'd3;  // 1 sample taken, count 1
    localparam B2_0  = 4'd4;  // 2 samples taken, count 0
    localparam B2_1  = 4'd5;  // 2 samples taken, count 1
    localparam B2_2  = 4'd6;  // 2 samples taken, count 2
    localparam OUT0  = 4'd7;  // 1st sample cycle of new window, z=0
    localparam OUT1  = 4'd8;  // 1st sample cycle of new window, z=1

    reg [3:0] state, next;

    always @(*) begin
        case (state)
            A:     next = s ? B0 : A;
            B0:    next = w ? B1_1 : B1_0;
            B1_0:  next = w ? B2_1 : B2_0;
            B1_1:  next = w ? B2_2 : B2_1;
            // 3rd sample; total = count + w; z asserted next cycle if total==2
            B2_0:  next = w ? OUT0 : OUT0;        // total 0 or 1 -> z=0
            B2_1:  next = w ? OUT1 : OUT0;        // total 2 -> z=1, else 1 -> z=0
            B2_2:  next = w ? OUT0 : OUT1;        // total 3 -> z=0, else 2 -> z=1
            // OUT states are also first sample cycle of next window
            OUT0:  next = w ? B1_1 : B1_0;
            OUT1:  next = w ? B1_1 : B1_0;
            default: next = A;
        endcase
    end

    always @(posedge clk) begin
        if (reset)
            state <= A;
        else
            state <= next;
    end

    assign z = (state == OUT1);

endmodule
