$appRoot = Split-Path -Parent $PSScriptRoot
$bundledMaterials = Join-Path $appRoot 'materials'
if (Test-Path -LiteralPath $bundledMaterials) { $env:BEATSCOPE_MATERIAL_ROOT = $bundledMaterials }
$env:PYTHONPATH = $appRoot
Push-Location -LiteralPath $appRoot
try { python -c "from beatscope.server import serve; serve(port=8871,open_browser=True)" }
finally { Pop-Location }
