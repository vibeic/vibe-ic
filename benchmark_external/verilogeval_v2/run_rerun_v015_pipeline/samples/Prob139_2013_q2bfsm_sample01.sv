module TopModule (
    input  clk,
    input  resetn,
    input  x,
    input  y,
    output f,
    output g
);

    // States
    localparam A   = 4'd0;  // reset / beginning state
    localparam F1  = 4'd1;  // assert f=1 for one cycle
    localparam X0  = 4'd2;  // x-monitor: no useful history
    localparam X1  = 4'd3;  // x-monitor: last x ended in "1"
    localparam X2  = 4'd4;  // x-monitor: last x ended in "10"
    localparam G1  = 4'd5;  // g=1, y-monitor cycle 1
    localparam G2  = 4'd6;  // g=1, y-monitor cycle 2
    localparam GP  = 4'd7;  // g=1 permanently
    localparam G0  = 4'd8;  // g=0 permanently

    reg [3:0] state, next;

    always @(*) begin
        case (state)
            A:  next = F1;                 // leave reset -> assert f next cycle
            F1: next = X0;                 // f was 1 here; start monitoring x
            // detect "1,0,1" over three successive cycles (overlapping)
            X0: next = x ? X1 : X0;
            X1: next = x ? X1 : X2;
            X2: next = x ? G1 : X0;        // "101" detected -> g=1 next cycle
            // g=1, monitor y for up to two cycles
            G1: next = y ? GP : G2;
            G2: next = y ? GP : G0;
            GP: next = GP;                 // g stays 1 until reset
            G0: next = G0;                 // g stays 0 until reset
            default: next = A;
        endcase
    end

    // Synchronous active-low reset
    always @(posedge clk) begin
        if (!resetn)
            state <= A;
        else
            state <= next;
    end

    // f = 1 only during the single F1 cycle
    assign f = (state == F1);

    // g = 1 while monitoring y and once locked permanently high
    assign g = (state == G1) || (state == G2) || (state == GP);

endmodule
