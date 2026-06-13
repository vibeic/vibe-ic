module TopModule (
    input        clk,
    input        reset,
    input  [2:0] s,
    output       fr2,
    output       fr1,
    output       fr0,
    output reg   dfr
);

    // Decode current water level from the thermometer-coded sensors.
    //   s = 000 -> below s0 (level 0, lowest)
    //   s = 001 -> at s0    (level 1)
    //   s = 011 -> at s1    (level 2)
    //   s = 111 -> at s2    (level 3, highest)
    function [1:0] level;
        input [2:0] sin;
        begin
            case (sin)
                3'b000:  level = 2'd0;
                3'b001:  level = 2'd1;
                3'b011:  level = 2'd2;
                3'b111:  level = 2'd3;
                default: level = 2'd0;
            endcase
        end
    endfunction

    reg [1:0] prev_level;
    wire [1:0] cur_level = level(s);

    always @(posedge clk) begin
        if (reset) begin
            // Equivalent to water having been low for a long time:
            // no sensors asserted and rising (supplemental valve open).
            prev_level <= 2'd0;
            dfr        <= 1'b1;
        end else begin
            if (cur_level > prev_level)
                dfr <= 1'b1;       // water rising -> open supplemental valve
            else if (cur_level < prev_level)
                dfr <= 1'b0;       // water falling -> close supplemental valve
            // else: no sensor change, hold dfr
            prev_level <= cur_level;
        end
    end

    // Nominal flow valves: combinational on current level.
    //   level 0 (below s0): fr0,fr1,fr2
    //   level 1 (s0):       fr0,fr1
    //   level 2 (s1):       fr0
    //   level 3 (s2):       none
    assign fr0 = (cur_level <= 2'd2);
    assign fr1 = (cur_level <= 2'd1);
    assign fr2 = (cur_level == 2'd0);

endmodule
