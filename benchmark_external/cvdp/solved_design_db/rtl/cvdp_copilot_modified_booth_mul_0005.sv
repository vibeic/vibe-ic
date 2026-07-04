// Pipelined Modified Booth Multiplier — 16x16 signed, radix-4 Booth recoding.
// 5 pipeline stages (1 cycle each); total input->output latency = 5 cycles.
// Asynchronous active-high reset clears all registers and outputs to zero.
module pipelined_modified_booth_multiplier (
    input  wire               clk,
    input  wire               rst,    // asynchronous active-high reset
    input  wire               start,  // active-high: begin a multiplication
    input  wire signed [15:0] X,
    input  wire signed [15:0] Y,
    output reg         [31:0] result, // 32-bit signed product
    output reg                done
);

    // ---- radix-4 Booth recode of one 3-bit group -> multiple of X (sign-extended to 32) ----
    function signed [31:0] booth_term;
        input signed [31:0] x32;
        input        [2:0]  g;
        begin
            case (g)
                3'b001, 3'b010: booth_term =  x32;          // +X
                3'b011:         booth_term =  (x32 <<< 1);   // +2X
                3'b100:         booth_term = -(x32 <<< 1);   // -2X
                3'b101, 3'b110: booth_term = -x32;          // -X
                default:        booth_term = 32'sd0;         // 000 / 111 -> 0
            endcase
        end
    endfunction

    // ---------------- Stage 1: input register + control valid ----------------
    reg signed [15:0] x_s1, y_s1;
    reg               v_s1;

    // ---------------- Stage 2: partial products ----------------
    reg signed [31:0] pp0, pp1, pp2, pp3, pp4, pp5, pp6, pp7;
    reg               v_s2;

    // ---------------- Stage 3: first reduction ----------------
    reg signed [31:0] sumA, sumB;
    reg               v_s3;

    // ---------------- Stage 4: final summation ----------------
    reg signed [31:0] total;
    reg               v_s4;

    // sign-extended multiplicand and the eight overlapping Booth groups of y_s1
    wire signed [31:0] x32 = {{16{x_s1[15]}}, x_s1};
    wire [2:0] g0 = { y_s1[1],  y_s1[0],  1'b0      };
    wire [2:0] g1 = { y_s1[3],  y_s1[2],  y_s1[1]   };
    wire [2:0] g2 = { y_s1[5],  y_s1[4],  y_s1[3]   };
    wire [2:0] g3 = { y_s1[7],  y_s1[6],  y_s1[5]   };
    wire [2:0] g4 = { y_s1[9],  y_s1[8],  y_s1[7]   };
    wire [2:0] g5 = { y_s1[11], y_s1[10], y_s1[9]   };
    wire [2:0] g6 = { y_s1[13], y_s1[12], y_s1[11]  };
    wire [2:0] g7 = { y_s1[15], y_s1[14], y_s1[13]  };

    always @(posedge clk or posedge rst) begin
        if (rst) begin
            x_s1 <= 16'sd0; y_s1 <= 16'sd0; v_s1 <= 1'b0;
            pp0 <= 32'sd0; pp1 <= 32'sd0; pp2 <= 32'sd0; pp3 <= 32'sd0;
            pp4 <= 32'sd0; pp5 <= 32'sd0; pp6 <= 32'sd0; pp7 <= 32'sd0;
            v_s2 <= 1'b0;
            sumA <= 32'sd0; sumB <= 32'sd0; v_s3 <= 1'b0;
            total <= 32'sd0; v_s4 <= 1'b0;
            result <= 32'd0; done <= 1'b0;
        end else begin
            // Stage 1
            x_s1 <= X;
            y_s1 <= Y;
            v_s1 <= start;

            // Stage 2 : Booth-encode + partial-product generation (each shifted 2*i)
            pp0 <= booth_term(x32, g0) <<< 0;
            pp1 <= booth_term(x32, g1) <<< 2;
            pp2 <= booth_term(x32, g2) <<< 4;
            pp3 <= booth_term(x32, g3) <<< 6;
            pp4 <= booth_term(x32, g4) <<< 8;
            pp5 <= booth_term(x32, g5) <<< 10;
            pp6 <= booth_term(x32, g6) <<< 12;
            pp7 <= booth_term(x32, g7) <<< 14;
            v_s2 <= v_s1;

            // Stage 3 : partial-product reduction
            sumA <= pp0 + pp1 + pp2 + pp3;
            sumB <= pp4 + pp5 + pp6 + pp7;
            v_s3 <= v_s2;

            // Stage 4 : final summation
            total <= sumA + sumB;
            v_s4  <= v_s3;

            // Stage 5 : output result (held stable until next valid) + done strobe
            if (v_s4)
                result <= total;
            done <= v_s4;
        end
    end
endmodule
