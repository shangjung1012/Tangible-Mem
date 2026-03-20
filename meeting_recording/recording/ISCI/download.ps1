$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$outputDir = Split-Path -Parent $MyInvocation.MyCommand.Path

for ($i = 1; $i -le 31; $i++) {
    $fileId = "{0:D3}" -f $i
    $fileName = "Bmr${fileId}.interaction.wav"
    $url = "https://groups.inf.ed.ac.uk/ami/ICSIsignals/NXT/$fileName"
    $destination = Join-Path $outputDir $fileName

    Write-Host "Downloading $fileName"
    Invoke-WebRequest -Uri $url -OutFile $destination
}
