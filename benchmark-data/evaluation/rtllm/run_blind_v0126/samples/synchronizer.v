module synchronizer (
    input  clk_a,
    input  clk_b,
    input  arstn,
    input  brstn,
    input  [3:0] data_in,
    input  data_en,
    output reg [3:0] dataout
);

    reg [3:0] data_reg;
    reg       en_data_reg;
    reg       en_clap_one;
    reg       en_clap_two;

    // Capture data_in on clock A
    always @(posedge clk_a or negedge arstn) begin
        if (!arstn)
            data_reg <= 4'd0;
        else
            data_reg <= data_in;
    end

    // Capture data_en on clock A
    always @(posedge clk_a or negedge arstn) begin
        if (!arstn)
            en_data_reg <= 1'b0;
        else
            en_data_reg <= data_en;
    end

    // Two-stage synchronizer of enable into clock B domain
    always @(posedge clk_b or negedge brstn) begin
        if (!brstn) begin
            en_clap_one <= 1'b0;
            en_clap_two <= 1'b0;
        end else begin
            en_clap_one <= en_data_reg;
            en_clap_two <= en_clap_one;
        end
    end

    // MUX-based output capture in clock B domain
    always @(posedge clk_b or negedge brstn) begin
        if (!brstn)
            dataout <= 4'd0;
        else if (en_clap_two)
            dataout <= data_reg;
        // else retain previous value
    end

endmodule
