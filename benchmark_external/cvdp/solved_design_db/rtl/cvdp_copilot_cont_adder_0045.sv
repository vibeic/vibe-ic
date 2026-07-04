module cont_adder #(
  parameter DATA_WIDTH = 32,
  parameter signed THRESHOLD_VALUE_1 = 50,
  parameter signed THRESHOLD_VALUE_2 = 100,
  parameter signed THRESHOLD_VALUE_3 = 150,
  parameter ACCUM_MODE = 0,
  parameter WEIGHT = 1,
  parameter signed SAT_MAX = (2**(DATA_WIDTH-1))-1,
  parameter signed SAT_MIN = -(2**(DATA_WIDTH-1))
) (
  input  logic                         clk,
  input  logic                         reset,
  input  logic                         accum_clear,
  input  logic                         enable,
  input  logic signed [DATA_WIDTH-1:0] data_in,
  input  logic                         data_valid,
  input  logic [15:0]                  window_size,
  output logic signed [DATA_WIDTH-1:0] sum_out,
  output logic signed [DATA_WIDTH-1:0] avg_out,
  output logic                         threshold_1,
  output logic                         threshold_2,
  output logic                         threshold_3,
  output logic                         sum_ready,
  output logic                         busy
);
  // Smallest-magnitude threshold: OR of (|x|>=T1)|(|x|>=T2)|(|x|>=T3) == |x|>=min(T)
  localparam signed THRESH_MIN =
      (THRESHOLD_VALUE_1 < THRESHOLD_VALUE_2)
        ? ((THRESHOLD_VALUE_1 < THRESHOLD_VALUE_3) ? THRESHOLD_VALUE_1 : THRESHOLD_VALUE_3)
        : ((THRESHOLD_VALUE_2 < THRESHOLD_VALUE_3) ? THRESHOLD_VALUE_2 : THRESHOLD_VALUE_3);

  typedef enum logic [1:0] {IDLE, ACCUM, DONE} state_t;
  state_t state;
  logic signed [DATA_WIDTH-1:0] sum_accum;
  logic [15:0] sample_count;
  logic signed [DATA_WIDTH-1:0] weighted_in_reg;
  logic signed [DATA_WIDTH-1:0] sat_sum;

  // One (DATA_WIDTH+1)-bit add carries the true sum; signed saturation to the
  // full DATA_WIDTH range == overflow clamp (sign of bit[W] vs bit[W-1]).
  logic signed [DATA_WIDTH:0] wide_sum;
  assign wide_sum = $signed({sum_accum[DATA_WIDTH-1], sum_accum})
                  + $signed({weighted_in_reg[DATA_WIDTH-1], weighted_in_reg});
  logic                         sat_ovf;     // true sum left the DATA_WIDTH signed range
  logic                         sat_neg;     // overflow was on the negative side
  logic signed [DATA_WIDTH-1:0] sat_low;     // low DATA_WIDTH bits of the true sum
  logic signed [DATA_WIDTH-1:0] sat_next;
  assign sat_ovf  = (wide_sum[DATA_WIDTH] != wide_sum[DATA_WIDTH-1]);
  assign sat_neg  =  wide_sum[DATA_WIDTH];
  assign sat_low  =  wide_sum[DATA_WIDTH-1:0];
  assign sat_next = sat_ovf ? (sat_neg ? SAT_MIN : SAT_MAX) : sat_low;

  // Exact magnitude fold: (s>=T)||(s<=-T) for T>0 equals, with one's-complement
  // fold m = s ^ {W{s[W-1]}} (m=s if s>=0, m=|s|-1 if s<0), m >= (s<0 ? T-1 : T).
  logic [DATA_WIDTH-1:0] mag_fold;
  assign mag_fold = sum_accum ^ {DATA_WIDTH{sum_accum[DATA_WIDTH-1]}};

  always_ff @(posedge clk or posedge reset) begin
    if (reset)
      weighted_in_reg <= 0;
    else if (enable && data_valid)
      weighted_in_reg <= (WEIGHT == 1) ? data_in : data_in * WEIGHT;
  end

  always_ff @(posedge clk or posedge reset) begin
    if (reset)
      sat_sum <= 0;
    else if (enable && data_valid)
      sat_sum <= sat_next;
  end

  always_ff @(posedge clk or posedge reset) begin
    if (reset) begin
      state <= IDLE; sum_accum <= 0; sample_count <= 0;
    end else if (accum_clear) begin
      state <= IDLE; sum_accum <= 0; sample_count <= 0;
    end else if (enable && data_valid) begin
      case (state)
        IDLE: begin state <= ACCUM; sum_accum <= sat_sum; sample_count <= 1; end
        ACCUM: begin
          sum_accum <= sat_sum;
          sample_count <= sample_count + 1;
          if (ACCUM_MODE == 1) begin
            if ((sample_count + 1) >= window_size) state <= DONE;
          end else begin
            if ((sat_sum >= THRESH_MIN) || (sat_sum <= -THRESH_MIN)) state <= DONE;
          end
        end
        DONE: begin state <= IDLE; sum_accum <= 0; sample_count <= 0; end
        default: state <= IDLE;
      endcase
    end
  end

  always_ff @(posedge clk or posedge reset) begin
    if (reset) begin
      sum_out <= 0; avg_out <= 0; sum_ready <= 0;
      threshold_1 <= 0; threshold_2 <= 0; threshold_3 <= 0; busy <= 0;
    end else begin
      busy <= (state == ACCUM);
      if (state == DONE) begin
        sum_out <= sum_accum;
        avg_out <= (ACCUM_MODE == 1) ? (sum_accum / sample_count) : 0;
        sum_ready <= 1;
        threshold_1 <= (mag_fold >= (sum_accum[DATA_WIDTH-1] ? (THRESHOLD_VALUE_1-1) : THRESHOLD_VALUE_1));
        threshold_2 <= (mag_fold >= (sum_accum[DATA_WIDTH-1] ? (THRESHOLD_VALUE_2-1) : THRESHOLD_VALUE_2));
        threshold_3 <= (mag_fold >= (sum_accum[DATA_WIDTH-1] ? (THRESHOLD_VALUE_3-1) : THRESHOLD_VALUE_3));
      end else begin
        sum_out <= 0; avg_out <= 0; sum_ready <= 0;
        threshold_1 <= 0; threshold_2 <= 0; threshold_3 <= 0;
      end
    end
  end
endmodule
