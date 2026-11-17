$ErrorActionPreference = 'Stop'
New-Item -ItemType Directory -Path (Join-Path $PSScriptRoot '..\.tools') -Force | Out-Null
$ollamaExecutable = Join-Path $env:LOCALAPPDATA 'Programs\Ollama\ollama.exe'
if (-not (Test-Path -LiteralPath $ollamaExecutable)) {
    $ollamaExecutable = Join-Path $PSScriptRoot '..\.tools\ollama\ollama.exe'
}
if (-not (Test-Path -LiteralPath $ollamaExecutable)) { throw 'Install Ollama first: https://ollama.com/download/windows' }
$env:OLLAMA_HOST = '127.0.0.1:11434'
$env:OLLAMA_NO_CLOUD = '1'
$env:OLLAMA_NUM_PARALLEL = '1'
$env:OLLAMA_MAX_LOADED_MODELS = '2' # One LLM plus transient CPU embedding model.
$env:OLLAMA_MAX_QUEUE = '4'
$env:OLLAMA_CONTEXT_LENGTH = '4096'
$env:OLLAMA_MODELS = Join-Path $PSScriptRoot '..\.tools\models'
try {
    Invoke-RestMethod http://127.0.0.1:11434/api/version -TimeoutSec 2 | Out-Null
    throw 'Ollama is already running. Quit it first so these explicit local-only settings take effect.'
} catch [System.Net.WebException] { }
Start-Process -FilePath $ollamaExecutable -ArgumentList 'serve' -WindowStyle Hidden `
    -RedirectStandardOutput (Join-Path $PSScriptRoot '..\.tools\ollama.stdout.log') `
    -RedirectStandardError (Join-Path $PSScriptRoot '..\.tools\ollama.stderr.log')
Write-Output 'Started local-only Ollama on loopback. Cloud disabled; generation concurrency one.'
