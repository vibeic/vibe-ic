module TopModule (
    input        clk,
    input        reset,
    input  [2:0] s,
    output       fr2,
    output       fr1,
    output       fr0,
    output       dfr
);
    // Level encoding (higher water = higher number)
    localparam L0 = 2'd0;  // below s0   : s=000
    localparam L1 = 2'd1;  // between s1,s0: s=001
    localparam L2 = 2'd2;  // between s2,s1: s=011
    localparam L3 = 2'd3;  // above s2   : s=111

    reg [1:0] state;   // current/last level
    reg       dfr_r;   // supplemental valve, holds between changes

    // decode sensors into a level
    reg [1:0] lvl;
    always @(*) begin
        case (s)
            3'b000:  lvl = L0;
            3'b001:  lvl = L1;
            3'b011:  lvl = L2;
            3'b111:  lvl = L3;
            default: lvl = state;  // illegal codes: hold
        endcase
    end

    always @(posedge clk) begin
        if (reset) begin
            state <= L0;       // lowest level
            dfr_r <= 1'b1;     // all four outputs asserted at reset
        end else begin
            if (lvl > state)      dfr_r <= 1'b1;  // water rose -> supplement
            else if (lvl < state) dfr_r <= 1'b0;  // water fell
            // else: no change -> hold dfr_r
            state <= lvl;
        end
    end

    // Moore nominal-flow outputs from current level
    assign fr0 = (state != L3);                 // off only above s2
    assign fr1 = (state == L1) || (state == L0); // between s1,s0 and below s0
    assign fr2 = (state == L0);                  // only below s0
    assign dfr = dfr_r;
endmodule
