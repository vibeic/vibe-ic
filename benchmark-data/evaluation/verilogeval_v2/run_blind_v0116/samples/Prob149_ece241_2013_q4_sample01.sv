module TopModule (
    input        clk,
    input        reset,
    input  [2:0] s,
    output       fr2,
    output       fr1,
    output       fr0,
    output       dfr
);
    // level = number of asserted sensors (sensors fill bottom-up):
    //   0 = below s0 (lowest), 3 = above s2 (highest)
    reg [1:0] level;     // current (registered) level
    reg       dfr_r;     // supplemental valve state

    // sensor-derived level of the present input
    wire [1:0] s_level = s[0] + s[1] + s[2];

    always @(posedge clk) begin
        if (reset) begin
            level <= 2'd0;   // long-time-low: no sensors
            dfr_r <= 1'b1;   // supplemental valve open
        end else begin
            level <= s_level;
            if (s_level > level)      dfr_r <= 1'b1;   // level rising
            else if (s_level < level) dfr_r <= 1'b0;   // level falling
            // equal: hold dfr_r
        end
    end

    // Nominal flow outputs depend only on the current level:
    //   level 0 (below s0):        fr0,fr1,fr2
    //   level 1 (between s1,s0):    fr0,fr1
    //   level 2 (between s2,s1):    fr0
    //   level 3 (above s2):         none
    assign fr0 = (level <= 2'd2);
    assign fr1 = (level <= 2'd1);
    assign fr2 = (level == 2'd0);
    assign dfr = dfr_r;
endmodule
