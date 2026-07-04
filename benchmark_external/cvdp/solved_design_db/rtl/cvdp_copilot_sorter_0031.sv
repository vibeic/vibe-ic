module sorting_engine #(
    parameter N = 8,          // number of elements to sort
    parameter WIDTH = 8       // bit-width of each element
)(
    input  wire                clk,
    input  wire                rst,
    input  wire                start,
    input  wire [N*WIDTH-1:0]  in_data,
    output reg                 done,
    output reg [N*WIDTH-1:0]   out_data
);

    //-----------------------------------------------------
    // State machine definitions
    //-----------------------------------------------------
    localparam [3:0]
        S_IDLE         = 4'd0,
        S_LOAD_INPUT   = 4'd1,
        S_FIND_MAX     = 4'd2,
        S_COUNT        = 4'd3,
        S_PREFIX_SUM   = 4'd4,
        S_BUILD_OUTPUT = 4'd5,
        S_COPY_OUTPUT  = 4'd6,
        S_DONE         = 4'd7;

    //-----------------------------------------------------
    // Registered signals (updated in sequential always)
    //-----------------------------------------------------
    reg [3:0]           current_state;
    reg [WIDTH-1:0]     data_array [0:N-1];
    reg [WIDTH-1:0]     out_array  [0:N-1];
    reg [$clog2(N):0]   count_array[0:(1<<WIDTH)-1];

    reg [WIDTH-1:0]     max_val;
    reg [$clog2(N):0]   load_cnt;
    reg [$clog2(N):0]   find_cnt;
    reg [$clog2(N):0]   count_cnt;
    reg [WIDTH-1:0]     prefix_cnt;
    reg [$clog2(N):0]   build_cnt;
    reg [$clog2(N):0]   copy_cnt;

    //-----------------------------------------------------
    // Wires/reg for "next" values (computed combinationally)
    //-----------------------------------------------------
    reg [3:0]           next_state;

    // Arrays get "shadow copies" for combinational updates
    reg [WIDTH-1:0]     next_data_array [0:N-1];
    reg [WIDTH-1:0]     next_out_array  [0:N-1];
    reg [$clog2(N):0]   next_count_array[0:(1<<WIDTH)-1];

    reg [WIDTH-1:0]     next_max_val;
    reg [$clog2(N):0]   next_load_cnt;
    reg [$clog2(N):0]   next_find_cnt;
    reg [$clog2(N):0]   next_count_cnt;
    reg [WIDTH-1:0]     next_prefix_cnt;
    reg [$clog2(N):0]   next_build_cnt;
    reg [$clog2(N):0]   next_copy_cnt;

    reg                 next_done;
    reg [N*WIDTH-1:0]   next_out_data;
    integer rev_idx;
    reg [WIDTH-1:0] val;
    reg [$clog2(N):0] pos;

    integer i;
    always @(*) begin
        // Default: hold all state (no latches: every reg has a default).
        next_state       = current_state;
        for (i = 0; i < N; i = i + 1) next_data_array[i] = data_array[i];
        for (i = 0; i < N; i = i + 1) next_out_array[i]  = out_array[i];
        for (i = 0; i < (1<<WIDTH); i = i + 1) next_count_array[i] = count_array[i];
        next_max_val   = max_val;
        next_load_cnt  = load_cnt;
        next_find_cnt  = find_cnt;
        next_count_cnt = count_cnt;
        next_prefix_cnt= prefix_cnt;
        next_build_cnt = build_cnt;
        next_copy_cnt  = copy_cnt;
        next_done      = 1'b0;
        next_out_data  = out_data;
        rev_idx        = 0;
        val            = {WIDTH{1'b0}};
        pos            = {($clog2(N)+1){1'b0}};

        case (current_state)
            S_IDLE: begin
                // 1 cycle: latch start, clear the histogram + counters.
                if (start) begin
                    next_load_cnt   = 0;
                    next_find_cnt   = 0;
                    next_count_cnt  = 0;
                    next_prefix_cnt = 0;
                    next_build_cnt  = 0;
                    next_copy_cnt   = 0;
                    next_max_val    = {WIDTH{1'b0}};
                    for (i = 0; i < (1<<WIDTH); i = i + 1)
                        next_count_array[i] = {($clog2(N)+1){1'b0}};
                    next_state = S_LOAD_INPUT;
                end
            end

            S_LOAD_INPUT: begin
                // N cycles to load, +1 transition cycle.
                if (load_cnt < N) begin
                    next_data_array[load_cnt] = in_data[load_cnt*WIDTH +: WIDTH];
                    next_load_cnt = load_cnt + 1;
                end else begin
                    next_state = S_FIND_MAX;
                end
            end

            S_FIND_MAX: begin
                // N cycles to find max, +1 transition cycle.
                if (find_cnt < N) begin
                    if (data_array[find_cnt] > max_val)
                        next_max_val = data_array[find_cnt];
                    next_find_cnt = find_cnt + 1;
                end else begin
                    next_state = S_COUNT;
                end
            end

            S_COUNT: begin
                // N cycles to build the histogram, +1 transition cycle.
                if (count_cnt < N) begin
                    next_count_array[data_array[count_cnt]] =
                        count_array[data_array[count_cnt]] + 1'b1;
                    next_count_cnt = count_cnt + 1;
                end else begin
                    next_state = S_PREFIX_SUM;
                end
            end

            S_PREFIX_SUM: begin
                // max_val cycles to make the cumulative histogram, +1 transition.
                if (prefix_cnt < max_val) begin
                    next_count_array[prefix_cnt + 1] =
                        count_array[prefix_cnt + 1] + count_array[prefix_cnt];
                    next_prefix_cnt = prefix_cnt + 1;
                end else begin
                    next_state = S_BUILD_OUTPUT;
                end
            end

            S_BUILD_OUTPUT: begin
                // N cycles, MSB->LSB, +1 transition cycle (stable counting sort).
                if (build_cnt < N) begin
                    rev_idx = N - 1 - build_cnt;
                    val = data_array[rev_idx];
                    pos = count_array[val] - 1'b1;
                    next_out_array[pos]   = val;
                    next_count_array[val] = count_array[val] - 1'b1;
                    next_build_cnt = build_cnt + 1;
                end else begin
                    next_state = S_COPY_OUTPUT;
                end
            end

            S_COPY_OUTPUT: begin
                // 1 cycle: pack the unpacked sorted array into out_data and move
                // to S_DONE. Per the spec latency breakdown, `done` is asserted
                // one cycle LATER, on the S_DONE -> S_IDLE transition (not here),
                // so out_data is registered-stable before the done pulse.
                for (i = 0; i < N; i = i + 1)
                    next_out_data[i*WIDTH +: WIDTH] = next_out_array[i];
                next_state = S_DONE;
            end

            S_DONE: begin
                // 1 cycle: assert the done pulse exactly on the transition back
                // to S_IDLE (matches "1 clock cycle to transition from S_DONE to
                // S_IDLE and assert the done output").
                next_done  = 1'b1;
                next_state = S_IDLE;
            end

            default: next_state = S_IDLE;
        endcase
    end

    always @(posedge clk or posedge rst) begin
        if (rst) begin
            // synchronous reset
            current_state <= S_IDLE;
            done          <= 1'b0;
            out_data      <= {N*WIDTH{1'b0}};
            max_val       <= {WIDTH{1'b0}};

            load_cnt      <= 0;
            find_cnt      <= 0;
            count_cnt     <= 0;
            prefix_cnt    <= 0;
            build_cnt     <= 0;
            copy_cnt      <= 0;

            // Clear arrays
            for (i = 0; i < N; i = i + 1) begin
                data_array[i] <= {WIDTH{1'b0}};
                out_array[i]  <= {WIDTH{1'b0}};
            end
            for (i = 0; i < (1<<WIDTH); i = i + 1) begin
                count_array[i] <= {($clog2(N)+1){1'b0}};
            end

        end else begin
            current_state <= next_state;
            for (i = 0; i < N; i = i + 1) data_array[i] <= next_data_array[i];
            for (i = 0; i < N; i = i + 1) out_array[i]  <= next_out_array[i];
            for (i = 0; i < (1<<WIDTH); i = i + 1) count_array[i] <= next_count_array[i];
            max_val    <= next_max_val;
            load_cnt   <= next_load_cnt;
            find_cnt   <= next_find_cnt;
            count_cnt  <= next_count_cnt;
            prefix_cnt <= next_prefix_cnt;
            build_cnt  <= next_build_cnt;
            copy_cnt   <= next_copy_cnt;
            done       <= next_done;
            out_data   <= next_out_data;
        end
    end

endmodule
