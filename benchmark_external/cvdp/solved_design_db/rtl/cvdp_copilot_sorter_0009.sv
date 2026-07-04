module sorting_engine #(
    parameter N = 8,
    parameter WIDTH = 8
)(
    input  wire                clk,
    input  wire                rst,
    input  wire                start,
    input  wire [N*WIDTH-1:0]  in_data,
    output reg                 done,
    output reg [N*WIDTH-1:0]   out_data
);
    localparam IDLE = 2'd0,
               LOAD = 2'd1,
               SORT = 2'd2,
               DONE = 2'd3;

    reg [1:0]  state, next_state;
    reg [WIDTH-1:0] data_array [0:N-1];
    reg [$clog2(N+1)-1:0] pass_cnt;
    reg [$clog2(N/2+1)-1:0] pair_idx;

    wire [$clog2(N/2+1)-1:0] pairs_in_this_pass;
    assign pairs_in_this_pass = (pass_cnt[0] == 1'b0) ? (N/2) : ( (N/2) > 0 ? (N/2) - 1 : 0 );

    integer i;
    integer lo;
    integer hi;

    // ---- next-state (combinational) ----
    always @(*) begin
        next_state = state;
        case (state)
            IDLE: if (start) next_state = LOAD;
            LOAD: next_state = SORT;
            SORT: if (pass_cnt >= N) next_state = DONE;
            DONE: next_state = IDLE;
            default: next_state = IDLE;
        endcase
    end

    // ---- datapath / sequential ----
    always @(posedge clk or posedge rst) begin
        if (rst) begin
            state    <= IDLE;
            done     <= 1'b0;
            pass_cnt <= 0;
            pair_idx <= 0;
            for (i = 0; i < N; i = i + 1)
                data_array[i] <= {WIDTH{1'b0}};
            // out_data intentionally left uninitialized at reset (per spec)
        end else begin
            state <= next_state;
            done  <= 1'b0;
            case (state)
                IDLE: begin
                    if (start) begin
                        pass_cnt <= 0;
                        pair_idx <= 0;
                    end
                end
                LOAD: begin
                    for (i = 0; i < N; i = i + 1)
                        data_array[i] <= in_data[i*WIDTH +: WIDTH];
                    pass_cnt <= 0;
                    pair_idx <= 0;
                end
                SORT: begin
                    if (pass_cnt < N) begin
                        if (pairs_in_this_pass == 0) begin
                            // empty (odd) pass for very small N — just advance
                            pair_idx <= 0;
                            pass_cnt <= pass_cnt + 1'b1;
                        end else begin
                            // index of the low element of the current pair
                            if (pass_cnt[0] == 1'b0)
                                lo = pair_idx << 1;        // even pass: (0,1),(2,3)...
                            else
                                lo = (pair_idx << 1) + 1;  // odd  pass: (1,2),(3,4)...
                            hi = lo + 1;
                            // compare-and-swap (ascending: smallest toward index 0)
                            if (data_array[lo] > data_array[hi]) begin
                                data_array[lo] <= data_array[hi];
                                data_array[hi] <= data_array[lo];
                            end
                            // advance pair / pass counters (one compare-swap per cycle)
                            if (pair_idx >= (pairs_in_this_pass - 1)) begin
                                pair_idx <= 0;
                                pass_cnt <= pass_cnt + 1'b1;
                            end else begin
                                pair_idx <= pair_idx + 1'b1;
                            end
                        end
                    end
                end
                DONE: begin
                    for (i = 0; i < N; i = i + 1)
                        out_data[i*WIDTH +: WIDTH] <= data_array[i];
                    done <= 1'b1;
                end
                default: ;
            endcase
        end
    end
endmodule
