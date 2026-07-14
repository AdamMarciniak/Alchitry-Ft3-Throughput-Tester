//==============================================================================
// AFE5804 LVDS receiver
//   LCLK 240 MHz -> BUFIO  -> rx_clk  (ISERDES CLK)
//                -> BUFR/3 -> rx_div  (ISERDES CLKDIV, 80 MHz)
//   ISERDESE2 DDR, DATA_WIDTH=6 -> 6 bits per rx_div cycle
//   2 cycles = one 12-bit frame @ 40 MSPS
//
// NOTE: on this part/config ISERDESE2 emits bits in reverse time order
//       (Q6 = first bit received), so both lanes are reversed below.
//
// Eye-scan metric is STABILITY, not equality: with a static pattern the
// deserialized word must be identical every cycle.  Any variation = bit
// error.  This is immune to bitslip parity (0x15 vs 0x2A on deskew), which
// is what made the earlier equality-based scan give contradictory maps.
//==============================================================================
module afe_rx (
  input  wire        sys_clk,       // 100 MHz
  input  wire        rst,

  input  wire        lclk_p, lclk_n,// 240 MHz bit clock  (F5/E5, MRCC)
  input  wire        fclk_p, fclk_n,// 40 MHz frame clock (F4/F3)
  input  wire        out1_p, out1_n,// 480 Mbps data      (B4/A3)

  // control (sys_clk domain, all *_req / *_load are 1-cycle pulses)
  input  wire        bitslip_req,
  input  wire [4:0]  dat_tap,
  input  wire [4:0]  fclk_tap,
  input  wire        tap_load,
  input  wire        scan_clr,      // clear sticky error flags

  // 32-word scratch capture
  input  wire        cap_req,
  input  wire        cap_raw,       // 1 = raw ISERDES words, 0 = assembled
  output reg         cap_done,
  input  wire [4:0]  rd_addr,
  output wire [15:0] rd_data,

  // 8192-sample deep capture
  input  wire        deep_req,
  output reg         deep_done,
  input  wire [12:0] deep_addr,
  output wire [15:0] deep_data,

  // status (sys_clk domain)
  output wire        err_dat,       // data lane unstable at current tap
  output wire        err_fclk,      // frame lane not 3F/00 -> word misaligned
  output wire        lclk_alive,
  output wire        fclk_alive,
  output wire        out1_alive,
  output wire        idelay_rdy,

  // continuous sample stream (samp_clk = rx_div, 80 MHz; one pulse per sample)
  output wire        samp_clk,
  output wire [11:0] samp_data,
  output wire        samp_valid
);

  //--------------------------------------------------------------------------
  // 200 MHz reference for IDELAYCTRL
  //--------------------------------------------------------------------------
  wire mmcm_fb_raw, mmcm_fb, clk200_raw, clk200, mmcm_locked;

  MMCME2_BASE #(
    .CLKIN1_PERIOD    (10.0),   // 100 MHz
    .DIVCLK_DIVIDE    (1),
    .CLKFBOUT_MULT_F  (10.0),   // VCO = 1000 MHz
    .CLKOUT0_DIVIDE_F (5.0)     // 200 MHz
  ) u_mmcm (
    .CLKIN1   (sys_clk),
    .CLKFBIN  (mmcm_fb),
    .CLKFBOUT (mmcm_fb_raw),
    .CLKFBOUTB(),
    .CLKOUT0  (clk200_raw), .CLKOUT0B(),
    .CLKOUT1  (),           .CLKOUT1B(),
    .CLKOUT2  (),           .CLKOUT2B(),
    .CLKOUT3  (),           .CLKOUT3B(),
    .CLKOUT4  (), .CLKOUT5(), .CLKOUT6(),
    .LOCKED   (mmcm_locked),
    .PWRDWN   (1'b0),
    .RST      (rst)
  );

  BUFG u_bufg_fb  (.I(mmcm_fb_raw), .O(mmcm_fb));
  BUFG u_bufg_200 (.I(clk200_raw),  .O(clk200));

  reg [7:0] dlyctrl_rst_cnt = 8'hFF;
  always @(posedge sys_clk) begin
    if (!mmcm_locked)              dlyctrl_rst_cnt <= 8'hFF;
    else if (dlyctrl_rst_cnt != 0) dlyctrl_rst_cnt <= dlyctrl_rst_cnt - 1'b1;
  end
  wire dlyctrl_rst = (dlyctrl_rst_cnt != 0);

  (* IODELAY_GROUP = "afe_grp" *)
  IDELAYCTRL u_idelayctrl (.REFCLK(clk200), .RST(dlyctrl_rst), .RDY(idelay_rdy));

  //--------------------------------------------------------------------------
  // Clock recovery
  //--------------------------------------------------------------------------
  wire lclk_i, rx_clk, rx_div;

  IBUFDS #(.IOSTANDARD("LVDS_25")) u_ib_lclk (.I(lclk_p), .IB(lclk_n), .O(lclk_i));
  BUFIO u_bufio (.I(lclk_i), .O(rx_clk));                          // 240 MHz
  BUFR #(.BUFR_DIVIDE("3"), .SIM_DEVICE("7SERIES"))
        u_bufr  (.I(lclk_i), .O(rx_div), .CE(1'b1), .CLR(1'b0));   // 80 MHz

  (* ASYNC_REG="TRUE" *) reg [2:0] rstd = 3'b111;
  always @(posedge rx_div) rstd <= {rstd[1:0], rst};
  wire rst_div = rstd[2];

  //--------------------------------------------------------------------------
  // Input delays
  //--------------------------------------------------------------------------
  wire fclk_i, out1_i, fclk_dly, out1_dly;

  IBUFDS #(.IOSTANDARD("LVDS_25")) u_ib_fclk (.I(fclk_p), .IB(fclk_n), .O(fclk_i));
  IBUFDS #(.IOSTANDARD("LVDS_25")) u_ib_out1 (.I(out1_p), .IB(out1_n), .O(out1_i));

  (* IODELAY_GROUP = "afe_grp" *)
  IDELAYE2 #(
    .IDELAY_TYPE("VAR_LOAD"), .DELAY_SRC("IDATAIN"),
    .HIGH_PERFORMANCE_MODE("TRUE"), .IDELAY_VALUE(0),
    .REFCLK_FREQUENCY(200.0), .SIGNAL_PATTERN("DATA")
  ) u_dly_fclk (
    .C(sys_clk), .REGRST(rst), .LD(tap_load), .CE(1'b0), .INC(1'b0),
    .CINVCTRL(1'b0), .CNTVALUEIN(fclk_tap), .CNTVALUEOUT(),
    .IDATAIN(fclk_i), .DATAIN(1'b0), .LDPIPEEN(1'b0), .DATAOUT(fclk_dly)
  );

  (* IODELAY_GROUP = "afe_grp" *)
  IDELAYE2 #(
    .IDELAY_TYPE("VAR_LOAD"), .DELAY_SRC("IDATAIN"),
    .HIGH_PERFORMANCE_MODE("TRUE"), .IDELAY_VALUE(0),
    .REFCLK_FREQUENCY(200.0), .SIGNAL_PATTERN("DATA")
  ) u_dly_out1 (
    .C(sys_clk), .REGRST(rst), .LD(tap_load), .CE(1'b0), .INC(1'b0),
    .CINVCTRL(1'b0), .CNTVALUEIN(dat_tap), .CNTVALUEOUT(),
    .IDATAIN(out1_i), .DATAIN(1'b0), .LDPIPEEN(1'b0), .DATAOUT(out1_dly)
  );

  //--------------------------------------------------------------------------
  // BITSLIP: sys_clk pulse -> toggle -> rx_div 1-cycle pulse
  //--------------------------------------------------------------------------
  reg bs_tog = 1'b0;
  always @(posedge sys_clk) if (bitslip_req) bs_tog <= ~bs_tog;

  (* ASYNC_REG="TRUE" *) reg [2:0] bs_s = 3'b000;
  always @(posedge rx_div) bs_s <= {bs_s[1:0], bs_tog};
  wire bitslip = bs_s[2] ^ bs_s[1];

  //--------------------------------------------------------------------------
  // Deserializers
  //--------------------------------------------------------------------------
  wire [5:0] q_dat, q_fclk;

  ISERDESE2 #(
    .DATA_RATE("DDR"), .DATA_WIDTH(6), .INTERFACE_TYPE("NETWORKING"),
    .IOBDELAY("IFD"), .NUM_CE(2), .SERDES_MODE("MASTER"),
    .DYN_CLKDIV_INV_EN("FALSE"), .DYN_CLK_INV_EN("FALSE"), .OFB_USED("FALSE")
  ) u_ser_dat (
    .Q1(q_dat[0]), .Q2(q_dat[1]), .Q3(q_dat[2]),
    .Q4(q_dat[3]), .Q5(q_dat[4]), .Q6(q_dat[5]), .Q7(), .Q8(),
    .O(), .SHIFTOUT1(), .SHIFTOUT2(),
    .BITSLIP(bitslip), .CE1(1'b1), .CE2(1'b1),
    .CLK(rx_clk), .CLKB(~rx_clk), .CLKDIV(rx_div), .CLKDIVP(1'b0),
    .D(1'b0), .DDLY(out1_dly), .RST(rst_div),
    .SHIFTIN1(1'b0), .SHIFTIN2(1'b0),
    .OCLK(1'b0), .OCLKB(1'b0), .OFB(1'b0),
    .DYNCLKDIVSEL(1'b0), .DYNCLKSEL(1'b0)
  );

  ISERDESE2 #(
    .DATA_RATE("DDR"), .DATA_WIDTH(6), .INTERFACE_TYPE("NETWORKING"),
    .IOBDELAY("IFD"), .NUM_CE(2), .SERDES_MODE("MASTER"),
    .DYN_CLKDIV_INV_EN("FALSE"), .DYN_CLK_INV_EN("FALSE"), .OFB_USED("FALSE")
  ) u_ser_fclk (
    .Q1(q_fclk[0]), .Q2(q_fclk[1]), .Q3(q_fclk[2]),
    .Q4(q_fclk[3]), .Q5(q_fclk[4]), .Q6(q_fclk[5]), .Q7(), .Q8(),
    .O(), .SHIFTOUT1(), .SHIFTOUT2(),
    .BITSLIP(bitslip), .CE1(1'b1), .CE2(1'b1),
    .CLK(rx_clk), .CLKB(~rx_clk), .CLKDIV(rx_div), .CLKDIVP(1'b0),
    .D(1'b0), .DDLY(fclk_dly), .RST(rst_div),
    .SHIFTIN1(1'b0), .SHIFTIN2(1'b0),
    .OCLK(1'b0), .OCLKB(1'b0), .OFB(1'b0),
    .DYNCLKDIVSEL(1'b0), .DYNCLKSEL(1'b0)
  );

  // reverse: Q6 is the first bit in time
  wire [5:0] d_bits = {q_dat[0],  q_dat[1],  q_dat[2],
                       q_dat[3],  q_dat[4],  q_dat[5]};
  wire [5:0] f_bits = {q_fclk[0], q_fclk[1], q_fclk[2],
                       q_fclk[3], q_fclk[4], q_fclk[5]};

  //--------------------------------------------------------------------------
  // Frame assembly.  FCLK high half = first 6 bits (D0..D5, LSB-first).
  //--------------------------------------------------------------------------
  wire f_hi = (f_bits == 6'b111111);
  wire f_lo = (f_bits == 6'b000000);

  reg [5:0]  half0    = 6'd0;
  reg        have0    = 1'b0;
  reg [11:0] sample   = 12'd0;
  reg        samp_val = 1'b0;

  always @(posedge rx_div) begin
    samp_val <= 1'b0;
    if (rst_div) begin
      have0 <= 1'b0;
    end else if (f_hi) begin
      half0 <= d_bits;
      have0 <= 1'b1;
    end else if (f_lo && have0) begin
      sample   <= {d_bits, half0};      // {D11..D6, D5..D0}
      samp_val <= 1'b1;
      have0    <= 1'b0;
    end
  end

  assign samp_clk   = rx_div;
  assign samp_data  = sample;
  assign samp_valid = samp_val;

  //--------------------------------------------------------------------------
  // Sticky error flags
  //--------------------------------------------------------------------------
  reg clr_tog = 1'b0;
  always @(posedge sys_clk) if (scan_clr) clr_tog <= ~clr_tog;

  (* ASYNC_REG="TRUE" *) reg [2:0] clr_s = 3'b000;
  always @(posedge rx_div) clr_s <= {clr_s[1:0], clr_tog};
  wire clr_pulse = clr_s[2] ^ clr_s[1];

  // err_dat  : STABILITY.  With any static pattern (deskew/sync/custom) the
  //            deserialized word must not change.  Immune to bitslip parity.
  // err_fclk : frame lane must read 3F or 00.  Used by the auto-align FSM.
  reg [5:0] dref   = 6'd0;
  reg       dref_v = 1'b0;
  reg       e_d = 1'b0, e_f = 1'b0;

  always @(posedge rx_div) begin
    if (rst_div || clr_pulse) begin
      e_d <= 1'b0; e_f <= 1'b0; dref_v <= 1'b0;
    end else begin
      if (!dref_v) begin
        dref <= d_bits; dref_v <= 1'b1;
      end else if (d_bits != dref) begin
        e_d <= 1'b1;
      end
      if (f_bits != 6'h3F && f_bits != 6'h00) e_f <= 1'b1;
    end
  end

  (* ASYNC_REG="TRUE" *) reg [1:0] ed_s = 2'b00, ef_s = 2'b00;
  always @(posedge sys_clk) begin
    ed_s <= {ed_s[0], e_d};
    ef_s <= {ef_s[0], e_f};
  end
  assign err_dat  = ed_s[1];
  assign err_fclk = ef_s[1];

  //--------------------------------------------------------------------------
  // Liveness
  //--------------------------------------------------------------------------
  reg [24:0] ldiv = 25'd0;
  always @(posedge rx_div) ldiv <= ldiv + 1'b1;

  reg [5:0]  fprev = 6'd0, dprev = 6'd0;
  reg [19:0] fact  = 20'd0, dact = 20'd0;
  always @(posedge rx_div) begin
    fprev <= f_bits;  dprev <= d_bits;
    if (f_bits != fprev) fact <= 20'hFFFFF; else if (fact != 0) fact <= fact - 1'b1;
    if (d_bits != dprev) dact <= 20'hFFFFF; else if (dact != 0) dact <= dact - 1'b1;
  end

  (* ASYNC_REG="TRUE" *) reg [1:0] l_s = 2'b00, f_s = 2'b00, d_s = 2'b00;
  always @(posedge sys_clk) begin
    l_s <= {l_s[0], ldiv[24]};
    f_s <= {f_s[0], (fact != 0)};
    d_s <= {d_s[0], (dact != 0)};
  end
  assign lclk_alive = l_s[1];
  assign fclk_alive = f_s[1];
  assign out1_alive = d_s[1];

  //--------------------------------------------------------------------------
  // 32-word scratch capture (distributed RAM, async read)
  //--------------------------------------------------------------------------
  reg [15:0] cap_mem [0:31];
  assign rd_data = cap_mem[rd_addr];

  reg cap_tog = 1'b0, raw_l = 1'b0;
  always @(posedge sys_clk) if (cap_req) begin cap_tog <= ~cap_tog; raw_l <= cap_raw; end

  (* ASYNC_REG="TRUE" *) reg [2:0] cap_s = 3'b000;
  always @(posedge rx_div) cap_s <= {cap_s[1:0], cap_tog};
  wire cap_go = cap_s[2] ^ cap_s[1];

  reg       capturing = 1'b0;
  reg [5:0] wptr      = 6'd0;
  reg       cdone_tog = 1'b0;

  always @(posedge rx_div) begin
    if (rst_div) begin
      capturing <= 1'b0; wptr <= 6'd0;
    end else if (cap_go) begin
      capturing <= 1'b1; wptr <= 6'd0;
    end else if (capturing) begin
      if (raw_l) begin
        cap_mem[wptr[4:0]] <= {2'b00, f_bits, 2'b00, d_bits};
        if (wptr == 6'd31) begin capturing <= 1'b0; cdone_tog <= ~cdone_tog; end
        else wptr <= wptr + 1'b1;
      end else if (samp_val) begin
        cap_mem[wptr[4:0]] <= {4'b0000, sample};
        if (wptr == 6'd31) begin capturing <= 1'b0; cdone_tog <= ~cdone_tog; end
        else wptr <= wptr + 1'b1;
      end
    end
  end

  (* ASYNC_REG="TRUE" *) reg [2:0] cdone_s = 3'b000;
  always @(posedge sys_clk) begin
    cdone_s  <= {cdone_s[1:0], cdone_tog};
    cap_done <= cdone_s[2] ^ cdone_s[1];
  end

  //--------------------------------------------------------------------------
  // 8192-sample deep capture (block RAM, synchronous read)
  //   8192 @ 40 MSPS = 204.8 us
  //--------------------------------------------------------------------------
  reg [15:0] bmem [0:8191];

  reg deep_tog = 1'b0;
  always @(posedge sys_clk) if (deep_req) deep_tog <= ~deep_tog;

  (* ASYNC_REG="TRUE" *) reg [2:0] dp_s = 3'b000;
  always @(posedge rx_div) dp_s <= {dp_s[1:0], deep_tog};
  wire deep_go = dp_s[2] ^ dp_s[1];

  reg        dcap      = 1'b0;
  reg [12:0] dwp       = 13'd0;
  reg        ddone_tog = 1'b0;

  always @(posedge rx_div) begin
    if (rst_div) begin
      dcap <= 1'b0; dwp <= 13'd0;
    end else if (deep_go) begin
      dcap <= 1'b1; dwp <= 13'd0;
    end else if (dcap && samp_val) begin
      bmem[dwp] <= {4'b0000, sample};
      if (dwp == 13'd8191) begin
        dcap <= 1'b0; ddone_tog <= ~ddone_tog;
      end else dwp <= dwp + 1'b1;
    end
  end

  reg [15:0] deep_q = 16'd0;
  always @(posedge sys_clk) deep_q <= bmem[deep_addr];
  assign deep_data = deep_q;

  (* ASYNC_REG="TRUE" *) reg [2:0] dd_s = 3'b000;
  always @(posedge sys_clk) begin
    dd_s      <= {dd_s[1:0], ddone_tog};
    deep_done <= dd_s[2] ^ dd_s[1];
  end

endmodule