module TopModule (
    input        clk,
    input        reset,
    input  [2:0] s,
    output       fr2,
    output       fr1,
    output       fr0,
    output       dfr
);

    // Reservoir level controller (hysteresis on the supplemental valve dfr).
    // Thermometer sensors map to a registered level: 000=0(bottom)..111=3(top).
    // Non-thermometer codes hold the level. Nominal outputs (fr0/fr1/fr2)
    // decode from the REGISTERED level (Moore). dfr is a HELD flag updated only
    // on a level CHANGE: fall->1, rise->0, dwell->hold. Reset == "low for a
    // long time": level=bottom and all four outputs asserted (so dfr=1).

    reg [1:0] level;   // 0=bottom .. 3=top
    reg       dfr_r;

    // decode the current sensor reading into a level (only valid thermometer
    // codes change the level; others hold)
    reg [1:0] new_level;
    reg       valid_code;
    always @(*) begin
        valid_code = 1'b1;
        case (s)
            3'b000:  new_level = 2'd0;   // below s0
            3'b001:  new_level = 2'd1;   // between s1 and s0
            3'b011:  new_level = 2'd2;   // between s2 and s1
            3'b111:  new_level = 2'd3;   // above s2
            default: begin new_level = level; valid_code = 1'b0; end
        endcase
    end

    always @(posedge clk) begin
        if (reset) begin
            level <= 2'd0;     // bottom
            dfr_r <= 1'b1;     // supplemental open (all outputs asserted)
        end else if (valid_code) begin
            level <= new_level;
            if (new_level < level)      dfr_r <= 1'b1;   // fell -> open supplemental
            else if (new_level > level) dfr_r <= 1'b0;   // rose -> close supplemental
            // else dwell: hold dfr_r
        end
    end

    // Moore decode from registered level
    assign fr0 = (level <= 2'd2);   // asserted for bottom, L1, L2
    assign fr1 = (level <= 2'd1);   // asserted for bottom, L1
    assign fr2 = (level == 2'd0);   // asserted only at bottom
    assign dfr = dfr_r;

endmodule
