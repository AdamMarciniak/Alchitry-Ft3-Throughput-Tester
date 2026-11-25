from pathlib import Path
p=Path('tests/rtl/tb_ctrl_lease.v');s=p.read_text().replace("32'h00010004","32'h0001000c");p.write_text(s)
p=Path('tests/rtl/tb_capture_ready.v');s=p.read_text().replace('    integer shots=0', '''    integer test_method=0, half_count=0;
    reg prev_drive=0;
    reg [7:0] signs=0;
    integer on_at=0;
    integer shots=0''').replace('if (elem !== (shots%48))','if (elem !== ((test_method==1 ? shots/2 : shots)%48))').replace('                previous_shot=cyc;', '''                if (kind !== (test_method==1 ? 1+shots%2 : test_method==2 ? 3 : 0))
                    $fatal(1,"Unexpected pulse member tag");
                half_count=0; signs=0;
                previous_shot=cyc;''').replace("            if (ctrl.sstate==3'd4 && !previous_rx) begin","""            if (oe && (ina == inb) && !prev_drive) begin
                signs[half_count]=!ina;half_count=half_count+1;on_at=cyc;
            end
            if (prev_drive && ina!=inb && arm && cyc-on_at!=10)
                $fatal(1,"Wrong drive width");
            prev_drive=oe && (ina == inb);
            if (ctrl.sstate==3'd4 && !previous_rx) begin
                if (test_method==1 && (half_count!=8 || signs!==(shots%2 ? 8'h6a : 8'h9a)))
                    $fatal(1,"Incorrect complementary sequence");
                if (test_method==2 && (pulser.switching_rx || pulser.shift_data == 0 ||
                    pulser.shift_data !== rx_word(elem ^ 6'd1))) $fatal(1,"Incorrect receive switch");
""").replace('gate_at-sync_at !=1602','gate_at-sync_at != (test_method==2 ? 2202 : 1602)').replace("(ctrl.sstate==3'd2 || ctrl.sstate==3'd4)", "((ctrl.sstate==3'd2 && test_method!=2) || ctrl.sstate==3'd4)").replace("tx_data[31:22]==10'h384","tx_data[31:24]==8'hE1").replace("if (tx_data[21:16] !== (packets%48))", """if (tx_data[23:22] !== (test_method==1 ? 1+packets%2 : test_method==2 ? 3 : 0))
                        $fatal(1,"Incorrect packet method");
                    if (tx_data[21:16] !== ((test_method==1 ? packets/2 : packets)%48))""").replace('    task command','''    function [63:0] rx_word(input [5:0] position);
        reg [5:0] hw;
        begin
            hw=pulser.mux_code(position);
            rx_word=(64'h1 << (16+16*hw[5:4]+hw[3:0])) |
                    (64'h1 << (hw[5:4]==0 ? 5 : hw[5:4]==1 ? 7 : 11));
        end
    endfunction
    task command''').replace('        repeat(4) @(negedge clk);rst=0;', '''        if (!$value$plusargs("METHOD=%d",test_method)) test_method=0;
        repeat(4) @(negedge clk);rst=0;
        command(32'h20000000 | test_method);''').replace("command(32'h0c000640);","command(test_method==2 ? 32'h0c000898 : 32'h0c000640);")
p.write_text(s)
p=Path('tools/bench_capture_sim.ps1');s=p.read_text().split("& (Join-Path $Bin 'xsim.bat')")[0]+'''foreach ($method in 0,1,2) {
    & (Join-Path $Bin 'xsim.bat') capture_ready_test -testplusarg "METHOD=$method" -runall
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
}
''';p.write_text(s)
p=Path('tools/bench_build.py');s=p.read_text().replace("if 'CAPTURE_READY_TEST_PASS' not in text:","if text.count('CAPTURE_READY_TEST_PASS') != 3:");p.write_text(s)
