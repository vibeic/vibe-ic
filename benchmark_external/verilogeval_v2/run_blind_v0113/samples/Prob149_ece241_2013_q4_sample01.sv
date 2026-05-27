module TopModule(
    input        clk,
    input        reset,
    input  [2:0] s,
    output       fr2,
    output       fr1,
    output       fr0,
    output       dfr
);
    // Level region from sensors (sensors fill bottom-up):
    //   s=000 -> level0 (below s0)
    //   s=001 -> level1 (between s0,s1)
    //   s=011 -> level2 (between s1,s2)
    //   s=111 -> level3 (above s2)
    reg [1:0] level;     // registered current level
    reg       dfr_r;     // supplemental valve, held across cycles

    // decode incoming sensor reading to a level index
    reg [1:0] s_level;
    always @(*) begin
        case (s)
            3'b000:  s_level = 2'd0;
            3'b001:  s_level = 2'd1;
            3'b011:  s_level = 2'd2;
            3'b111:  s_level = 2'd3;
            default: s_level = level;  // illegal combo: hold
        endcase
    end

    always @(posedge clk) begin
        if (reset) begin
            level <= 2'd0;     // lowest level
            dfr_r <= 1'b1;     // all four outputs asserted at reset
        end else begin
            level <= s_level;
            if (s_level < level)      dfr_r <= 1'b1;  // level falling -> supplement
            else if (s_level > level) dfr_r <= 1'b0;  // level rising  -> no supplement
            // else: hold dfr_r
        end
    end

    // Moore outputs from registered level
    assign fr0 = (level <= 2'd2);            // asserted for levels 0,1,2
    assign fr1 = (level <= 2'd1);            // asserted for levels 0,1
    assign fr2 = (level == 2'd0);            // asserted for level 0
    assign dfr = dfr_r;
endmodule
