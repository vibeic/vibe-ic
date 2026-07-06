// DB-informed re-author: reviewed IC-Expert-DB craft for this design class;
// verified by hand-trace that the existing implementation already satisfies the
// relevant DB lesson (or the lesson does not apply here) -- kept functionally unchanged.
module adder_pipe_64bit (
    input         clk,
    input         rst_n,
    input         i_en,
    input  [63:0] adda,
    input  [63:0] addb,
    output reg [64:0] result,
    output reg        o_en
);

    reg [63:0] a_s1, b_s1, a_s2, b_s2, a_s3, b_s3;
    reg [15:0] sum_s1;
    reg [31:0] sum_s2;
    reg [47:0] sum_s3;
    reg        c_s1, c_s2, c_s3;
    reg        en_s1, en_s2, en_s3;

    // Stage 1: capture inputs, add bits [15:0]
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            a_s1   <= 64'd0;
            b_s1   <= 64'd0;
            sum_s1 <= 16'd0;
            c_s1   <= 1'b0;
            en_s1  <= 1'b0;
        end else begin
            a_s1 <= adda;
            b_s1 <= addb;
            {c_s1, sum_s1} <= adda[15:0] + addb[15:0];
            en_s1 <= i_en;
        end
    end

    // Stage 2: add bits [31:16]
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            a_s2   <= 64'd0;
            b_s2   <= 64'd0;
            sum_s2 <= 32'd0;
            c_s2   <= 1'b0;
            en_s2  <= 1'b0;
        end else begin
            a_s2 <= a_s1;
            b_s2 <= b_s1;
            sum_s2[15:0] <= sum_s1;
            {c_s2, sum_s2[31:16]} <= a_s1[31:16] + b_s1[31:16] + c_s1;
            en_s2 <= en_s1;
        end
    end

    // Stage 3: add bits [47:32]
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            a_s3   <= 64'd0;
            b_s3   <= 64'd0;
            sum_s3 <= 48'd0;
            c_s3   <= 1'b0;
            en_s3  <= 1'b0;
        end else begin
            a_s3 <= a_s2;
            b_s3 <= b_s2;
            sum_s3[31:0] <= sum_s2;
            {c_s3, sum_s3[47:32]} <= a_s2[47:32] + b_s2[47:32] + c_s2;
            en_s3 <= en_s2;
        end
    end

    // Stage 4: add bits [63:48], produce final result + carry
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            result <= 65'd0;
            o_en   <= 1'b0;
        end else begin
            result[47:0] <= sum_s3;
            {result[64], result[63:48]} <= a_s3[63:48] + b_s3[63:48] + c_s3;
            o_en <= en_s3;
        end
    end

endmodule
