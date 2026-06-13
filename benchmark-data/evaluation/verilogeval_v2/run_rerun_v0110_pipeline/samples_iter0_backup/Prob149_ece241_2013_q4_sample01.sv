module TopModule (
    input        clk,
    input        reset,
    input  [2:0] s,
    output       fr2,
    output       fr1,
    output       fr0,
    output       dfr
);
    // Decode current water level from thermometer-coded sensors.
    // level 0 = below s0 (s=000), 1 = between s0,s1 (s=001),
    // 2 = between s1,s2 (s=011), 3 = above s2 (s=111).
    reg [1:0] level;       // registered current level
    reg       dfr_reg;     // supplemental valve: 1 while rising

    reg [1:0] new_level;
    always @(*) begin
        case (s)
            3'b000: new_level = 2'd0;
            3'b001: new_level = 2'd1;
            3'b011: new_level = 2'd2;
            3'b111: new_level = 2'd3;
            default: new_level = level; // illegal codes hold level
        endcase
    end

    always @(posedge clk) begin
        if (reset) begin
            level   <= 2'd0;   // low for a long time
            dfr_reg <= 1'b1;   // rising into lowest level -> all outputs asserted
        end else begin
            level <= new_level;
            if (new_level > level)      dfr_reg <= 1'b1;  // level rose
            else if (new_level < level) dfr_reg <= 1'b0;  // level fell
            // else unchanged: hold dfr_reg
        end
    end

    // Nominal flow outputs depend only on current (registered) level.
    // level 0 -> fr0,fr1,fr2 ; level 1 -> fr0,fr1 ; level 2 -> fr0 ; level 3 -> none
    assign fr0 = (level <= 2'd2);
    assign fr1 = (level <= 2'd1);
    assign fr2 = (level == 2'd0);
    assign dfr = dfr_reg;
endmodule
