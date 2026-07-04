module sorting_engine #(
    parameter N = 8,             // Number of elements to sort
    parameter WIDTH = 8          // Bit-width of each element
)(
    input  wire                clk,
    input  wire                rst,
    input  wire                start,
    input  wire [N*WIDTH-1:0]  in_data,
    output reg                 done,
    output reg [N*WIDTH-1:0]   out_data
);

    // Internal registers to hold the array
    reg [WIDTH-1:0] array [0:N-1];

    // Top-level FSM states
    localparam IDLE    = 2'd0;
    localparam SORTING = 2'd1;
    localparam DONE    = 2'd2;

    reg [1:0] state;

    // Insertion-sort sub-phases handled by a case statement inside SORTING
    localparam PH_SETUP  = 3'd0;  // set up the start conditions
    localparam PH_ACCESS = 3'd1;  // access the next element to be sorted
    localparam PH_SHIFT  = 3'd2;  // shift each larger sorted element up by one
    localparam PH_INSERT = 3'd3;  // insert the element at the located spot

    reg [2:0] ph;

    // Insertion-sort working state
    reg [$clog2(N)-1:0] i;     // outer loop : element currently being inserted
    reg [$clog2(N)-1:0] j;     // inner loop : current shifting position
    reg [WIDTH-1:0]     key;   // value currently being inserted

    integer k, m;

    // Single sequential FSM (async active-high reset, identical to the original).
    always @(posedge clk or posedge rst) begin
        if (rst) begin
            state <= IDLE;
            ph    <= PH_SETUP;
            i     <= 0;
            j     <= 0;
            done  <= 0;
        end else begin
            case (state)
                IDLE: begin
                    done <= 0;
                    if (start) begin
                        // Latch the unsorted array from in_data on start.
                        for (k = 0; k < N; k = k + 1) begin
                            array[k] <= in_data[(k+1)*WIDTH-1 -: WIDTH];
                        end
                        state <= SORTING;
                        ph    <= PH_SETUP;
                    end
                end

                // The SORTING state implements the main insertion-sort logic
                // using a case statement over the algorithm's sub-phases.
                SORTING: begin
                    case (ph)
                        // 1 clock cycle to set up the start conditions.
                        PH_SETUP: begin
                            i <= 1;
                            j <= 0;
                            if (N <= 1)
                                state <= DONE;      // nothing to sort
                            else
                                ph <= PH_ACCESS;
                        end

                        // 1 clock cycle to access the element to be sorted.
                        PH_ACCESS: begin
                            key <= array[i];
                            j   <= i;
                            ph  <= PH_SHIFT;
                        end

                        // Every shift operation (until the correct spot is
                        // found) takes 1 clock cycle.  The cycle that finds the
                        // spot is the "iterations complete" detection cycle.
                        PH_SHIFT: begin
                            if (j != 0 && array[j-1] > key) begin
                                array[j] <= array[j-1];
                                j        <= j - 1;
                            end else begin
                                ph <= PH_INSERT;
                            end
                        end

                        // 1 clock cycle to insert the element at the spot found.
                        // After the final element is inserted the engine moves
                        // directly to the output/done cycle (the "all sorted"
                        // detection coincides with placing the last element).
                        PH_INSERT: begin
                            array[j] <= key;
                            if (i == N-1)
                                state <= DONE;      // last element placed
                            else begin
                                i  <= i + 1;
                                ph <= PH_ACCESS;
                            end
                        end

                        default: ph <= PH_SETUP;
                    endcase
                end

                // 1 clock cycle to output the sorted array and assert done.
                DONE: begin
                    done <= 1;
                    for (m = 0; m < N; m = m + 1) begin
                        out_data[(m+1)*WIDTH-1 -: WIDTH] <= array[m];
                    end
                    state <= IDLE;
                end

                default: state <= IDLE;
            endcase
        end
    end

endmodule
