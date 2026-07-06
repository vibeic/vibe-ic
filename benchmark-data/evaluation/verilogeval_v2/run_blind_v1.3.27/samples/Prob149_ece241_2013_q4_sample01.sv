module TopModule(
    input  clk,
    input  reset,
    input  [2:0] s,
    output fr2,
    output fr1,
    output fr0,
    output dfr
);
    reg [1:0] level;
    reg       dfr_r;
    reg [1:0] new_level;

    always @(*) begin
        case (s)
            3'b000: new_level = 2'd0;
            3'b001: new_level = 2'd1;
            3'b011: new_level = 2'd2;
            3'b111: new_level = 2'd3;
            default: new_level = level; // non-thermometer code: hold previous level
        endcase
    end

    always @(posedge clk) begin
        if (reset) begin
            level <= 2'd0;
            dfr_r <= 1'b1;
        end else begin
            if (new_level < level)      dfr_r <= 1'b1;
            else if (new_level > level) dfr_r <= 1'b0;
            level <= new_level;
        end
    end

    assign fr0 = (level != 2'd3);
    assign fr1 = (level <= 2'd1);
    assign fr2 = (level == 2'd0);
    assign dfr = dfr_r;

endmodule
