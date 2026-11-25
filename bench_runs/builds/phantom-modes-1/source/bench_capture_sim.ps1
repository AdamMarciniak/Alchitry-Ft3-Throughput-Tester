param([string]$Bin, [string]$Source, [string]$Testbench)
$ErrorActionPreference='Stop'
& (Join-Path $Bin 'xvlog.bat') (Join-Path $Source 'ctrl_decode.v') (Join-Path $Source 'tx_sequencer.v') $Testbench
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
& (Join-Path $Bin 'xelab.bat') tb_capture_ready -s capture_ready_test
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
foreach ($method in 0,1,2) {
    & (Join-Path $Bin 'xsim.bat') capture_ready_test -testplusarg "METHOD=$method" -runall
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
}
