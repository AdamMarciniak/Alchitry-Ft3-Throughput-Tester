param(
    [Parameter(Mandatory=$true)][string]$Vivado,
    [Parameter(Mandatory=$true)][string]$Script,
    [Parameter(Mandatory=$true)][string]$Source,
    [Parameter(Mandatory=$true)][string]$Output,
    [string]$Part='xc7a35tftg256-2'
)
$ErrorActionPreference='Stop'
& $Vivado -mode batch -nojournal -nolog -source $Script -tclargs $Source $Output $Part
exit $LASTEXITCODE
