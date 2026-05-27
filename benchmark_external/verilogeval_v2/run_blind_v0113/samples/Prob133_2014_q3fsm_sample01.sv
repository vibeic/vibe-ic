module TopModule (
    input  clk,
    input  reset,
    input  s,
    input  w,
    output z
);
    localparam A    = 4'd0;
    localparam S1   = 4'd1;  // 1st sample of window
    localparam S2_0 = 4'd2;  // 2nd sample, count 0 so far
    localparam S2_1 = 4'd3;  // 2nd sample, count 1 so far
    localparam S3_0 = 4'd4;  // 3rd sample, count 0 so far
    localparam S3_1 = 4'd5;  // 3rd sample, count 1 so far
    localparam S3_2 = 4'd6;  // 3rd sample, count 2 so far
    localparam SZ0  = 4'd7;  // result: not exactly two -> z=0, also 1st sample of next window
    localparam SZ1  = 4'd8;  // result: exactly two -> z=1, also 1st sample of next window

    reg [3:0] state;

    always @(posedge clk) begin
        if (reset)
            state <= A;
        else begin
            case (state)
                A:    state <= s ? S1 : A;
                S1:   state <= w ? S2_1 : S2_0;
                S2_0: state <= w ? S3_1 : S3_0;
                S2_1: state <= w ? S3_2 : S3_1;
                S3_0: state <= SZ0;                 // final count 0 or 1 -> never two
                S3_1: state <= w ? SZ1 : SZ0;       // final count 2 or 1
                S3_2: state <= w ? SZ0 : SZ1;       // final count 3 or 2
                SZ0:  state <= w ? S2_1 : S2_0;     // next window first sample
                SZ1:  state <= w ? S2_1 : S2_0;
                default: state <= A;
            endcase
        end
    end

    // Moore output
    assign z = (state == SZ1);
endmodule
