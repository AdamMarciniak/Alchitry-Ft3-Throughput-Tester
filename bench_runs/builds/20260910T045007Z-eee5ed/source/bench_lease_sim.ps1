param([string]$Bin, [string]$Source, [string]$Testbench)
$ErrorActionPreference='Stop'
& (Join-Path $Bin 'xvlog.bat') $Source $Testbench
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
& (Join-Path $Bin 'xelab.bat') tb_ctrl_lease -s lease_test
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
& (Join-Path $Bin 'xsim.bat') lease_test -runall
exit $LASTEXITCODE
