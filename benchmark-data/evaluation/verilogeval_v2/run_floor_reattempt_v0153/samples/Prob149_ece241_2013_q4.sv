module TopModule (
    input        clk,
    input        reset,
    input  [2:0] s,
    output reg   fr2,
    output reg   fr1,
    output reg   fr0,
    output reg   dfr
);
    // Decode current level from sensors (s=00000xxx where consecutive 1s
    // start from LSB indicate which sensors below water).
    reg [1:0] prev_level;
    reg [1:0] curr_level;
    always @(*) begin
        case (s)
            3'b000: curr_level = 2'd0;  // below s[0]
            3'b001: curr_level = 2'd1;  // between s[1]/s[0]
            3'b011: curr_level = 2'd2;  // between s[2]/s[1]
            3'b111: curr_level = 2'd3;  // above s[2]
            default: curr_level = 2'd0;
        endcase
    end
    always @(posedge clk) begin
        if (reset) begin
            prev_level <= 2'd0;
            dfr <= 1'b1;
            fr2 <= 1'b1;
            fr1 <= 1'b1;
            fr0 <= 1'b1;
        end else begin
            dfr <= (prev_level < curr_level);
            prev_level <= curr_level;
            // flow rate from current level
            case (curr_level)
                2'd0: {fr2, fr1, fr0} <= 3'b111;
                2'd1: {fr2, fr1, fr0} <= 3'b011;
                2'd2: {fr2, fr1, fr0} <= 3'b001;
                2'd3: {fr2, fr1, fr0} <= 3'b000;
            endcase
        end
    end
endmodule
