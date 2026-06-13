module TopModule (
    input        clk,
    input        reset,
    input  [2:0] s,
    output       fr2,
    output       fr1,
    output       fr0,
    output       dfr
);
    // Water level decoded from thermometer-coded sensors (popcount of s):
    //   s=000 -> below s0      (level 0): assert fr0,fr1,fr2
    //   s=001 -> between s0,s1 (level 1): assert fr0,fr1
    //   s=011 -> between s1,s2 (level 2): assert fr0
    //   s=111 -> above s2      (level 3): assert none
    reg [1:0] level;     // registered current level (also serves as previous)
    reg       dfr_reg;   // supplemental valve

    reg [1:0] new_level;
    always @(*) begin
        case (s)
            3'b000: new_level = 2'd0;
            3'b001: new_level = 2'd1;
            3'b011: new_level = 2'd2;
            3'b111: new_level = 2'd3;
            default: new_level = level; // illegal codes: hold
        endcase
    end

    always @(posedge clk) begin
        if (reset) begin
            level   <= 2'd0;   // equivalent to having been low for a long time
            dfr_reg <= 1'b1;   // bottom state: supplemental valve open
        end else begin
            level <= new_level;
            // Supplemental valve opens when the level falls (more flow needed),
            // closes when the level rises, holds across no change.  Reset is the
            // bottom state with dfr asserted, i.e. as if it had fallen to bottom.
            if (new_level < level)      dfr_reg <= 1'b1;  // water fell
            else if (new_level > level) dfr_reg <= 1'b0;  // water rose
            // else: unchanged, hold dfr_reg
        end
    end

    // Nominal flow outputs decode from the current (registered) level.
    assign fr0 = (level <= 2'd2);  // asserted for levels 0,1,2
    assign fr1 = (level <= 2'd1);  // asserted for levels 0,1
    assign fr2 = (level == 2'd0);  // asserted for level 0
    assign dfr = dfr_reg;
endmodule
