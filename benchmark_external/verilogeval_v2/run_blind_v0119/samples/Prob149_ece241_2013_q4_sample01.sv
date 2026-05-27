module TopModule (
    input        clk,
    input        reset,
    input  [2:0] s,
    output       fr2,
    output       fr1,
    output       fr0,
    output       dfr
);
    // current water band derived from sensors (index: 3=highest .. 0=lowest)
    // above s2 : s=111 -> level 3
    // s2..s1   : s=011 -> level 2
    // s1..s0   : s=001 -> level 1
    // below s0 : s=000 -> level 0
    reg [1:0] cur_level;
    always @(*) begin
        case (s)
            3'b111:  cur_level = 2'd3;
            3'b011:  cur_level = 2'd2;
            3'b001:  cur_level = 2'd1;
            default: cur_level = 2'd0; // 3'b000 (and any unexpected) -> lowest
        endcase
    end

    // previous band, registered. Seed at reset as if water had been HIGH and
    // has just dropped to the bottom -> dfr asserted at the low level.
    reg [1:0] prev_level;
    reg       dfr_r;

    always @(posedge clk) begin
        if (reset) begin
            prev_level <= 2'd3;        // came from above
            dfr_r      <= 1'b1;        // supplemental valve open at reset (low-for-long)
        end else begin
            // dfr asserts when entering the current band from a higher band
            // (water dropped); holds while level unchanged; clears when rising.
            if (cur_level < prev_level)
                dfr_r <= 1'b1;         // dropped -> open supplemental
            else if (cur_level > prev_level)
                dfr_r <= 1'b0;         // rose    -> close supplemental
            // else: level unchanged -> hold dfr_r
            prev_level <= cur_level;
        end
    end

    // nominal valves: pure function of current band
    assign fr0 = ~(s[2] & s[1] & s[0]);  // on unless above s2
    assign fr1 = ~s[1];                  // on when at/below the s1 band
    assign fr2 = ~s[0];                  // on when below s0
    assign dfr = dfr_r;
endmodule
