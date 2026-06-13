module TopModule (
    input  clk,
    input  reset,
    input  s,
    input  w,
    output z
);
    // States
    localparam A     = 4'd0;  // wait for s
    localparam C1_0  = 4'd1;  // window cycle 1, z=0
    localparam C1_1  = 4'd2;  // window cycle 1, z=1 (output)
    localparam C2_0  = 4'd3;  // window cycle 2, 0 ones so far
    localparam C2_1  = 4'd4;  // window cycle 2, 1 one so far
    localparam C3_0  = 4'd5;  // window cycle 3, 0 ones so far
    localparam C3_1  = 4'd6;  // window cycle 3, 1 one so far
    localparam C3_2  = 4'd7;  // window cycle 3, 2 ones so far

    reg [3:0] state;

    always @(posedge clk) begin
        if (reset)
            state <= A;
        else begin
            case (state)
                A:    state <= s ? C1_0 : A;
                // window cycle 1 (sample w): ones count starts at 0
                C1_0: state <= w ? C2_1 : C2_0;
                C1_1: state <= w ? C2_1 : C2_0;
                // window cycle 2 (sample w)
                C2_0: state <= w ? C3_1 : C3_0;
                C2_1: state <= w ? C3_2 : C3_1;
                // window cycle 3 (sample w): then restart window with z reflecting count==2
                C3_0: state <= w ? C1_0 : C1_0;          // total 0 or 1 -> z=0
                C3_1: state <= w ? C1_1 : C1_0;          // total 2 (w=1) -> z=1 ; else 1 -> z=0
                C3_2: state <= w ? C1_0 : C1_1;          // total 3 -> z=0 ; total 2 (w=0) -> z=1
                default: state <= A;
            endcase
        end
    end

    // Moore output
    assign z = (state == C1_1);
endmodule
