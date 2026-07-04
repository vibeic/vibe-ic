module sorting_engine #(
    parameter N = 8,             // Number of elements to sort
    parameter WIDTH = 8          // Bit-width of each element
)(
    input  wire                clk,
    input  wire                rst,
    input  wire                start,
    input  wire [N*WIDTH-1:0]  in_data,
    output reg                 done,
    output wire [N*WIDTH-1:0]  out_data
);

    //-------------------------------------------------
    // Local Parameters & Functions
    //-------------------------------------------------
    localparam IDLE  = 0;
    localparam LOAD  = 1;
    localparam SORT  = 2;
    localparam MERGE = 3;

    // Function to compute floor(log2(value)) at compile time
    function integer clog2;
        input integer value;
        integer i;
        begin
            clog2 = 0;
            for (i = 1; i < value; i = i << 1) begin
                clog2 = clog2 + 1;
            end
        end
    endfunction

    // AREA OPTIMIZATION: the merge-sort indices never exceed 2*N, so an address
    // of clog2(2*N)+1 bits is sufficient. The original used clog2(4*N)+1 bits
    // (a wider, partly dead range).
    localparam ADDR_WIDTH = clog2(2 * N) + 1;

    //-------------------------------------------------
    // Internal Signals
    //-------------------------------------------------
    // AREA OPTIMIZATION: removing the DONE state leaves 4 states, so 2 state
    // bits suffice instead of 3.
    reg [1:0]                 state;

    // Internal memory of N elements
    reg [WIDTH-1:0]           data_mem [0:N-1];

    // Indices and counters with widened bit-width
    reg [ADDR_WIDTH-1:0]      base_idx;
    reg [ADDR_WIDTH-1:0]      left_idx;
    reg [ADDR_WIDTH-1:0]      right_idx;
    reg [ADDR_WIDTH-1:0]      merge_idx;
    reg [ADDR_WIDTH-1:0]      subarray_size;

    // Temporary buffer for merged sub-array
    reg [WIDTH-1:0]           tmp_merge [0:N-1];

    // Temporary registers for current left/right values
    reg [WIDTH-1:0]           left_val;
    reg [WIDTH-1:0]           right_val;

    integer i, k;
    // AREA OPTIMIZATION: these address/boundary helpers are bounded by 2*N, so
    // sized nets replace the original 32-bit `integer` comparators/index muxes.
    reg [ADDR_WIDTH:0] left_end, right_end;
    reg [ADDR_WIDTH:0] l_addr,   r_addr;

    //-------------------------------------------------
    // State Machine
    //-------------------------------------------------
    always @(posedge clk or posedge rst) begin
        if (rst) begin
            // Reset
            state         <= IDLE;
            done          <= 1'b0;
            base_idx      <= 0;
            left_idx      <= 0;
            right_idx     <= 0;
            merge_idx     <= 0;
            subarray_size <= 1;
        end else begin
            case (state)

                //----------------------------------
                // IDLE: Wait for start signal
                //----------------------------------
                IDLE: begin
                    done <= 1'b0;
                    if (start) begin
                        state <= LOAD;
                    end
                end

                //----------------------------------
                // LOAD: Copy from in_data to data_mem
                //----------------------------------
                LOAD: begin
                    for (i = 0; i < N; i = i + 1) begin
                        data_mem[i]  <= in_data[i*WIDTH +: WIDTH];
                        // AREA OPTIMIZATION: keep tmp_merge as a full shadow of
                        // data_mem so the per-pair write-back can be a straight
                        // copy (no base_idx barrel network).
                        tmp_merge[i] <= in_data[i*WIDTH +: WIDTH];
                    end

                    // Initialize for sorting
                    base_idx      <= 0;
                    left_idx      <= 0;
                    right_idx     <= 0;
                    merge_idx     <= 0;
                    subarray_size <= 1;

                    state <= SORT;
                end

                //----------------------------------
                // SORT: Each pass merges sub-arrays of size subarray_size
                //----------------------------------
                SORT: begin
                    // If subarray_size is >= N, the array is fully sorted.
                    // LATENCY OPTIMIZATION: drive the output and assert `done`
                    // directly here, removing the original dedicated DONE state
                    // (saves exactly one clock cycle).
                    if (subarray_size >= N) begin
                        // AREA OPTIMIZATION: out_data is a pure concatenation of
                        // data_mem (driven combinationally below), so the final
                        // N*WIDTH output register and its copy mux network are
                        // removed. done/state timing is unchanged.
                        done  <= 1'b1;
                        state <= IDLE;
                    end else begin
                        // Prepare to merge pairs of sub-arrays
                        base_idx  <= 0;
                        merge_idx <= 0;
                        left_idx  <= 0;
                        right_idx <= 0;
                        state     <= MERGE;
                    end
                end

                //----------------------------------
                // MERGE: Merge one pair of sub-arrays
                //----------------------------------
                MERGE: begin
                    // Compare/pick smaller
                    if ((l_addr <= left_end) && (r_addr <= right_end)) begin
                        if (left_val <= right_val) begin
                            tmp_merge[base_idx + merge_idx] <= left_val;
                            left_idx <= left_idx + 1;
                        end else begin
                            tmp_merge[base_idx + merge_idx] <= right_val;
                            right_idx <= right_idx + 1;
                        end
                        merge_idx <= merge_idx + 1;
                    end
                    else if (l_addr <= left_end) begin
                        // Only left sub-array has data
                        tmp_merge[base_idx + merge_idx] <= left_val;
                        left_idx <= left_idx + 1;
                        merge_idx <= merge_idx + 1;
                    end
                    else if (r_addr <= right_end) begin
                        // Only right sub-array has data
                        tmp_merge[base_idx + merge_idx] <= right_val;
                        right_idx <= right_idx + 1;
                        merge_idx <= merge_idx + 1;
                    end
                    else begin
                        // Both sub-arrays are exhausted => write back merged
                        // results. tmp_merge mirrors data_mem everywhere except
                        // the just-merged region, so a straight indexed copy
                        // syncs it back without a base_idx-offset mux network.
                        for (k = 0; k < N; k = k + 1) begin
                            data_mem[k] <= tmp_merge[k];
                        end

                        // Move base_idx to next pair of sub-arrays
                        base_idx  <= base_idx + (subarray_size << 1);
                        left_idx  <= 0;
                        right_idx <= 0;
                        merge_idx <= 0;

                        // If we merged all pairs in this pass, double subarray_size
                        if ((base_idx + (subarray_size << 1)) >= N) begin
                            subarray_size <= subarray_size << 1;
                            state         <= SORT;
                        end
                    end
                end

                default: state <= IDLE;
            endcase
        end
    end

always @ (*) begin
    if(state == MERGE) begin
        left_end  = base_idx + subarray_size - 1;
        right_end = base_idx + (subarray_size << 1) - 1;

        // Boundaries of left and right sub-arrays
        if (left_end >= N) left_end = N - 1;
        if (right_end >= N) right_end = N - 1;

        // Calculate addresses
        l_addr = base_idx + left_idx;
        r_addr = base_idx + subarray_size + right_idx;

        // Safe read for left_val
        if ((l_addr <= left_end) && (l_addr < N))
            left_val = data_mem[l_addr];
        else
            left_val = {WIDTH{1'b1}};  // or '0' if you prefer

        // Safe read for right_val
        if ((r_addr <= right_end) && (r_addr < N))
            right_val = data_mem[r_addr];
        else
            right_val = {WIDTH{1'b1}};
    end else begin
        left_end = 0;
        right_end = 0;
        l_addr = 0;
        r_addr = 0;
        left_val = 0;
        right_val = 0;
    end
end


    // AREA OPTIMIZATION: combinational output drive (fixed wiring, no muxes).
    genvar gi;
    generate
        for (gi = 0; gi < N; gi = gi + 1) begin : g_out
            assign out_data[gi*WIDTH +: WIDTH] = data_mem[gi];
        end
    endgenerate

endmodule
