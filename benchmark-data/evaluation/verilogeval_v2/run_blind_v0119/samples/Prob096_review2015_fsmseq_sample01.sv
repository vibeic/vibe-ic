module TopModule (
    input  clk,
    input  reset,
    input  data,
    output start_shifting
);
    // Detect the sequence 1101. Once seen, lock in DONE forever (until reset).
    localparam S0 = 3'd0,  // no useful prefix
               S1 = 3'd1,  // "1"
               S2 = 3'd2,  // "11"
               S3 = 3'd3,  // "110"
               DN = 3'd4;  // "1101" detected
    reg [2:0] state = S0;

    always @(posedge clk) begin
        if (reset)
            state <= S0;
        else begin
            case (state)
                S0:      state <= data ? S1 : S0;
                S1:      state <= data ? S2 : S0;
                S2:      state <= data ? S2 : S3;
                S3:      state <= data ? DN : S0;
                DN:      state <= DN;
                default: state <= S0;
            endcase
        end
    end

    assign start_shifting = (state == DN);
endmodule
