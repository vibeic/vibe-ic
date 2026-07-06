module intra_block #(
    parameter ROW_COL_WIDTH = 16,
    parameter DATA_WIDTH = ROW_COL_WIDTH*ROW_COL_WIDTH
)(
    input logic [DATA_WIDTH-1:0] in_data,  // Input: 256 bits
    output logic [DATA_WIDTH-1:0] out_data // Output: 256 bits rearranged
);

    // Area optimization:
    // The original design computed r_prime[256], c_prime[256] and
    // output_index[256] as intermediate wire arrays. These values are
    // data-INDEPENDENT: they only depend on the loop index, so they form a
    // fixed permutation of the input bit positions. Replacing the intermediate
    // arrays with a pure constant index function lets synthesis constant-fold
    // the permutation into simple wiring, removing the large intermediate wire
    // arrays and yielding a substantial wire-count reduction while remaining
    // functionally equivalent (out_data[j] == in_data[output_index(j)]).

    function automatic logic [7:0] scramble_index(input int i);
        logic [3:0] r_prime;
        logic [3:0] c_prime;
        begin
            if (i < 128) begin
                r_prime = (i - 2 * (i / 16)) % 16;
                c_prime = (i -     (i / 16)) % 16;
            end
            else begin
                r_prime = (i - 2 * (i / 16) - 1) % 16;
                c_prime = (i -     (i / 16) - 1) % 16;
            end
            scramble_index = r_prime * 16 + c_prime;
        end
    endfunction

    always_comb begin
        for (int j = 0; j < 256; j++) begin
            out_data[j] = in_data[scramble_index(j)];
        end
    end

endmodule
