module TopModule (
    input  clk,
    input  reset,
    input  s,
    input  w,
    output z
);

    localparam A     = 4'd0,
               C1    = 4'd1,  // sampling 1st of 3, count=0
               C2_0  = 4'd2,  // sampling 2nd, prior count 0
               C2_1  = 4'd3,  // sampling 2nd, prior count 1
               C3_0  = 4'd4,  // sampling 3rd, prior count 0
               C3_1  = 4'd5,  // sampling 3rd, prior count 1
               C3_2  = 4'd6,  // sampling 3rd, prior count 2
               OUT0  = 4'd7,  // output cycle, z=0
               OUT1  = 4'd8;  // output cycle, z=1

    reg [3:0] state, next;

    always @(*) begin
        case (state)
            A:    next = s ? C1 : A;
            C1:   next = w ? C2_1 : C2_0;
            C2_0: next = w ? C3_1 : C3_0;
            C2_1: next = w ? C3_2 : C3_1;
            C3_0: next = w ? OUT0 : OUT0;          // total 0 or 1 -> z=0
            C3_1: next = w ? OUT1 : OUT0;          // total 2 -> z=1, else 1
            C3_2: next = w ? OUT0 : OUT1;          // total 2 -> z=1, else 3
            OUT0: next = C1;
            OUT1: next = C1;
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
