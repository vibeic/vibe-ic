module sequence_detector (
    input  clk,
    input  reset_n,
    input  data_in,
    output reg sequence_detected
);

    // Moore-style FSM detecting the 4-bit sequence 1001 (with overlap support)
    localparam IDLE = 3'd0;
    localparam S1   = 3'd1; // got "1"
    localparam S2   = 3'd2; // got "10"
    localparam S3   = 3'd3; // got "100"
    localparam S4   = 3'd4; // got "1001" -> detected

    reg [2:0] state, next_state;

    always @(posedge clk or negedge reset_n) begin
        if (!reset_n)
            state <= IDLE;
        else
            state <= next_state;
    end

    always @(*) begin
        case (state)
            IDLE: next_state = data_in ? S1   : IDLE;
            S1:   next_state = data_in ? S1   : S2;    // "1" then 0 -> "10"
            S2:   next_state = data_in ? S1   : S3;    // "10" then 0 -> "100"; 1 -> "1"
            S3:   next_state = data_in ? S4   : IDLE;  // "100" then 1 -> "1001"
            S4:   next_state = data_in ? S1   : S2;    // overlap: trailing 1 starts new "1"
            default: next_state = IDLE;
        endcase
    end

    always @(*) begin
        sequence_detected = (state == S4);
    end

endmodule
