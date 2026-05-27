module TopModule(
    input        clk,
    input        reset,
    input  [2:0] s,
    output       fr2,
    output       fr1,
    output       fr0,
    output       dfr
);
    // Decode current water level (0 = below s0/lowest .. 3 = above s2/highest)
    reg [1:0] level;
    always @(*) begin
        case (s)
            3'b000: level = 2'd0; // no sensors -> lowest
            3'b001: level = 2'd1; // s0
            3'b011: level = 2'd2; // s0,s1
            3'b111: level = 2'd3; // s0,s1,s2
            default: level = 2'd0;
        endcase
    end

    // Remember previous level to detect a rising change
    reg [1:0] prev_level;
    reg       dfr_r;

    always @(posedge clk) begin
        if (reset) begin
            prev_level <= 2'd0; // as if water low for a long time
            dfr_r      <= 1'b1; // supplemental valve open at reset
        end else begin
            if (level > prev_level)      dfr_r <= 1'b1; // rising -> open supplemental
            else if (level < prev_level) dfr_r <= 1'b0; // falling -> close supplemental
            // unchanged: hold dfr_r
            prev_level <= level;
        end
    end

    // Nominal flow rate outputs depend on current level (combinational/Moore on level)
    assign fr0 = (level <= 2'd2); // asserted unless above s2 (level 3)
    assign fr1 = (level <= 2'd1); // asserted at level 0 or 1
    assign fr2 = (level == 2'd0); // asserted only at lowest level

    assign dfr = dfr_r;
endmodule
