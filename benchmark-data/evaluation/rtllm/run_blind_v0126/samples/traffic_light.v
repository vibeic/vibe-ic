module traffic_light (
    input            rst_n,
    input            clk,
    input            pass_request,
    output     [7:0] clock,
    output reg       red,
    output reg       yellow,
    output reg       green
);

    // State encoding
    parameter idle      = 2'd0;
    parameter s1_red    = 2'd1;
    parameter s2_yellow = 2'd2;
    parameter s3_green  = 2'd3;

    reg [7:0] cnt;        // internal down-counter
    reg [1:0] state;      // current state
    reg       p_red, p_yellow, p_green;  // next values for the lights

    // First always block: state transition logic
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            state    <= idle;
            p_red    <= 1'b0;
            p_yellow <= 1'b0;
            p_green  <= 1'b0;
        end else begin
            case (state)
                idle: begin
                    p_red    <= 1'b0;
                    p_yellow <= 1'b0;
                    p_green  <= 1'b0;
                    state    <= s1_red;
                end
                s1_red: begin
                    p_red    <= 1'b1;
                    p_yellow <= 1'b0;
                    p_green  <= 1'b0;
                    if (cnt == 8'd3)
                        state <= s3_green;
                    else
                        state <= s1_red;
                end
                s2_yellow: begin
                    p_red    <= 1'b0;
                    p_yellow <= 1'b1;
                    p_green  <= 1'b0;
                    if (cnt == 8'd3)
                        state <= s1_red;
                    else
                        state <= s2_yellow;
                end
                s3_green: begin
                    p_red    <= 1'b0;
                    p_yellow <= 1'b0;
                    p_green  <= 1'b1;
                    if (cnt == 8'd3)
                        state <= s2_yellow;
                    else
                        state <= s3_green;
                end
                default: begin
                    p_red    <= 1'b0;
                    p_yellow <= 1'b0;
                    p_green  <= 1'b0;
                    state    <= idle;
                end
            endcase
        end
    end

    // Second always block: counting logic
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            cnt <= 8'd10;
        end else if (pass_request && green) begin
            cnt <= 8'd10;
        end else if (!green && p_green) begin
            cnt <= 8'd60;
        end else if (!yellow && p_yellow) begin
            cnt <= 8'd5;
        end else if (!red && p_red) begin
            cnt <= 8'd10;
        end else begin
            cnt <= cnt - 8'd1;
        end
    end

    // clock output reflects the internal counter
    assign clock = cnt;

    // Final always block: register the output light signals
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            red    <= 1'b0;
            yellow <= 1'b0;
            green  <= 1'b0;
        end else begin
            red    <= p_red;
            yellow <= p_yellow;
            green  <= p_green;
        end
    end

endmodule
