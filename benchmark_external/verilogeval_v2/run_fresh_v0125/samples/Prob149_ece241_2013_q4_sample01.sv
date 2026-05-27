module TopModule (
    input        clk,
    input        reset,
    input  [2:0] s,
    output       fr2,
    output       fr1,
    output       fr0,
    output       dfr
);
    // level: 0 = below s0 (s=000), 1 = between s1,s0 (s=001),
    //        2 = between s2,s1 (s=011), 3 = above s2 (s=111)
    function [1:0] level;
        input [2:0] ss;
        begin
            case (ss)
                3'b000: level = 2'd0;
                3'b001: level = 2'd1;
                3'b011: level = 2'd2;
                3'b111: level = 2'd3;
                default: level = 2'd0;
            endcase
        end
    endfunction

    reg [1:0] cur_level;   // currently registered water level
    reg       dfr_reg;     // supplemental valve state

    wire [1:0] new_level = level(s);

    always @(posedge clk) begin
        if (reset) begin
            cur_level <= 2'd0;   // low for a long time
            dfr_reg   <= 1'b1;   // supplemental asserted
        end else begin
            if (new_level > cur_level)      dfr_reg <= 1'b1;  // rising
            else if (new_level < cur_level) dfr_reg <= 1'b0;  // falling
            // else: unchanged, hold dfr_reg
            cur_level <= new_level;
        end
    end

    // nominal flow rates based on current registered level
    assign fr0 = (cur_level <= 2'd2);  // asserted for levels 0,1,2
    assign fr1 = (cur_level <= 2'd1);  // asserted for levels 0,1
    assign fr2 = (cur_level == 2'd0);  // asserted only at lowest level
    assign dfr = dfr_reg;
endmodule
