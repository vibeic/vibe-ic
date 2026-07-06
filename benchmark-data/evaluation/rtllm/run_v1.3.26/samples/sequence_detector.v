module sequence_detector(
    input  wire clk,
    input  wire reset_n,
    input  wire data_in,
    output wire sequence_detected
);

localparam IDLE = 3'd0,
           S1   = 3'd1, // "1"
           S2   = 3'd2, // "10"
           S3   = 3'd3, // "100"
           S4   = 3'd4; // "1001" detected

reg [2:0] state;

always @(posedge clk or negedge reset_n) begin
    if (!reset_n) begin
        state <= IDLE;
    end else begin
        case (state)
            IDLE: state <= data_in ? S1   : IDLE;
            S1:   state <= data_in ? S1   : S2;
            S2:   state <= data_in ? S1   : S3;
            S3:   state <= data_in ? S4   : IDLE;
            // DB craft: overlap-reseed — the trailing bit of a completed match
            // must resume the LONGEST prefix of "1001" that is also a suffix
            // of the extended stream, not blindly reset to IDLE. After S4,
            // data_in=1 -> "...10011" longest matching prefix is "1" -> S1;
            // data_in=0 -> "...10010" longest matching prefix is "10" -> S2.
            S4:   state <= data_in ? S1   : S2;  // overlap re-seed (KMP failure fn)
            default: state <= IDLE;
        endcase
    end
end

// Moore output: function of current (registered) state only
assign sequence_detected = (state == S4);

endmodule
