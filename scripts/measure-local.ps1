param([int]$Seconds = 600, [string]$OutputPath = 'docs\local-resource-samples.csv')
$ErrorActionPreference = 'Stop'
$samples = @()
for ($index = 0; $index -lt $Seconds; $index++) {
    $osState = Get-CimInstance Win32_OperatingSystem
    $gpuData = & nvidia-smi --query-gpu=memory.used,memory.total,utilization.gpu --format=csv,noheader,nounits 2>$null
    $samples += [pscustomobject]@{
        utc = [DateTime]::UtcNow.ToString('o')
        system_ram_used_mib = [math]::Round(($osState.TotalVisibleMemorySize - $osState.FreePhysicalMemory)/1024)
        ollama_working_set_mib = [math]::Round((Get-Process -ErrorAction SilentlyContinue | Where-Object { $_.ProcessName -match '^(ollama|llama-server)' } | Measure-Object WorkingSet64 -Sum).Sum/1MB)
        gpu_observation = if ($LASTEXITCODE -eq 0) { ($gpuData -join ';') } else { 'unavailable' }
    }
    $samples | Export-Csv -LiteralPath $OutputPath -NoTypeInformation
    Start-Sleep -Seconds 1
}
Write-Output "Saved $($samples.Count) approximately one-second samples. System RAM includes unrelated apps and Docker; this is sampled system pressure, not exact model allocation."
