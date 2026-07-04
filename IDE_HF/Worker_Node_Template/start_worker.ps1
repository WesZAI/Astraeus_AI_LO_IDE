$LlamaPath = "C:\Path\To\Llama\bin"
$Port = 50055

Write-Host "Starte Llama RPC Worker auf Port $Port..." -ForegroundColor Cyan
Set-Location -Path $LlamaPath

if (Test-Path ".\rpc-server.exe") {
    Write-Host "Starte rpc-server.exe..." -ForegroundColor Green
    & ".\rpc-server.exe" -H 0.0.0.0 -p $Port
} else {
    Write-Host "Fehler: rpc-server.exe nicht gefunden in $LlamaPath" -ForegroundColor Red
    exit 1
}
