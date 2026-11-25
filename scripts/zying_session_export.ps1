param(
    [Parameter(Mandatory=$true)][string]$AppPath,
    [Parameter(Mandatory=$true)][string]$OutputPath,
    [Parameter(Mandatory=$true)][string]$DiagnosticsDir,
    [int]$ProcessId = 0
)

$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [Text.Encoding]::UTF8
$taskTarget = $null
try {
    $taskApp = [IO.Path]::GetFullPath($AppPath)
    $taskCandidates = @(Get-Process -Name ZYing -ErrorAction SilentlyContinue |
        Where-Object { $_.Path -and [IO.Path]::GetFullPath($_.Path) -ieq $taskApp -and
            ($ProcessId -eq 0 -or $_.Id -eq $ProcessId) })
    if ($taskCandidates.Count -ne 1) { throw 'Select exactly one running client for this executable' }
    $taskProcess = $taskCandidates[0]
    $taskWorkPath = Join-Path ([IO.Path]::GetDirectoryName($taskApp)) 'ZYing.Work.dll'
    $taskHash = (Get-FileHash -LiteralPath $taskWorkPath -Algorithm SHA256).Hash
    # Layout verified by static IL and ClrMD field metadata for this installation.
    if ($taskHash -ne '034C95CC20C59037D6177FCB409B7D87AE975AF46C5A1805B10175DF9774C934') {
        throw 'This client assembly layout has not been verified for session export'
    }
    [Reflection.Assembly]::LoadFrom((Join-Path $DiagnosticsDir 'diag\lib\net6.0\Microsoft.Diagnostics.NETCore.Client.dll')) | Out-Null
    [Reflection.Assembly]::LoadFrom((Join-Path $DiagnosticsDir 'clrmd\lib\net6.0\Microsoft.Diagnostics.Runtime.dll')) | Out-Null
    $taskTarget = [Microsoft.Diagnostics.Runtime.DataTarget]::AttachToProcess($taskProcess.Id, $false)
    $taskRuntime = $taskTarget.ClrVersions[0].CreateRuntime()
    $taskModules = @($taskRuntime.EnumerateModules() | Where-Object { $_.Name -ieq $taskWorkPath })
    if ($taskModules.Count -ne 1) { throw 'The running client module does not match this installation' }
    $taskModule = $taskModules[0]
    $taskDomain = $taskRuntime.AppDomains[0]
    $taskMember = $taskModule.GetTypeByName('ZYing.Member')
    $taskTransport = $taskModule.GetTypeByName('ze53.Fe5b')
    if (!$taskMember -or !$taskTransport) { throw 'Verified session types are unavailable' }
    $taskToken = $taskMember.GetStaticFieldByName('Token').Read[guid]($taskDomain)
    $taskClientId = $taskTransport.GetStaticFieldByName('deiW').Read[guid]($taskDomain)
    if ($taskToken -eq [guid]::Empty -or $taskClientId -eq [guid]::Empty) { throw 'The client has no initialized session' }
    $taskClient = $taskTransport.GetStaticFieldByName('JeDP').ReadObject($taskDomain)
    if ($taskClient.IsNull) { throw 'The current client transport has not been initialized' }
    $taskMode = $taskClient.ReadField[byte]('Neic')
    if ($taskMode -ne 77) { throw 'Only verified M-mode transport can be exported' }
    $taskEndpoint = $taskClient.ReadObjectField('Ceiy')
    if ($taskEndpoint.IsNull) { throw 'The current client transport has no selected endpoint' }
    $taskAddress = $taskEndpoint.ReadObjectField('_address')
    $taskNumbers = $taskAddress.ReadObjectField('_numbers')
    if (!$taskNumbers.IsNull) { throw 'IPv6 endpoint export has not been verified' }
    $taskHost = ([Net.IPAddress]::new([long]$taskAddress.ReadField[uint]('_addressOrScopeId'))).ToString()
    $taskPort = $taskEndpoint.ReadField[int]('_port')
    if ($taskPort -lt 1 -or $taskPort -gt 65535) { throw 'The client endpoint has an invalid port' }
    $taskConfig = @{
        host = $taskHost; port = $taskPort; mode = 'M';
        client_id = $taskClientId.ToString(); session_token = $taskToken.ToString();
        protocol_version = $taskTransport.GetStaticFieldByName('UeiO').Read[int]($taskDomain);
        app_revision = $taskTransport.GetStaticFieldByName('ceio').Read[int]($taskDomain);
        pid = $taskProcess.Id; app = $taskApp; work_sha256 = $taskHash.ToLowerInvariant();
        captured_at = [DateTime]::UtcNow.ToString('o')
    }
    $taskTarget.Dispose(); $taskTarget = $null
    $taskPlain = [Text.Encoding]::UTF8.GetBytes(($taskConfig | ConvertTo-Json -Compress))
    $taskEncrypted = [Security.Cryptography.ProtectedData]::Protect($taskPlain, $null,
        [Security.Cryptography.DataProtectionScope]::CurrentUser)
    $taskEnvelope = @{ format = 'zying-dpapi-session-v1'; protected = [Convert]::ToBase64String($taskEncrypted) }
    $taskOut = [IO.Path]::GetFullPath($OutputPath)
    [IO.Directory]::CreateDirectory([IO.Path]::GetDirectoryName($taskOut)) | Out-Null
    [IO.File]::WriteAllText($taskOut, ($taskEnvelope | ConvertTo-Json -Compress), [Text.UTF8Encoding]::new($false))
    [Array]::Clear($taskPlain, 0, $taskPlain.Length)
    @{ ok = $true; pid = $taskProcess.Id; mode = 'M'; protected = $true;
       session_file = $taskOut; source = 'readonly_clrmd'; business_requests_sent = 0 } | ConvertTo-Json -Compress
} catch {
    @{ ok = $false; error = $_.Exception.Message } | ConvertTo-Json -Compress
    exit 1
} finally {
    if ($taskTarget) { $taskTarget.Dispose() }
}
