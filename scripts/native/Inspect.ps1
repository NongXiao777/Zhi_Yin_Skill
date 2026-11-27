#Requires -Version 7.0
<#
.SYNOPSIS
Read installed client DLL metadata without loading or executing the assemblies.
.EXAMPLE
pwsh -File scripts/native/Inspect.ps1 -AppDirectory "$env:LOCALAPPDATA\Programs\ZYing" -TypeMatch 'ABSs|HuxA|ZResult' -MethodMatch 'LBgK|bBge|iBgU|IqkW'
.EXAMPLE
pwsh -File scripts/native/Inspect.ps1 -AppDirectory "$env:LOCALAPPDATA\Programs\ZYing" -RpcCandidates
#>
param(
    [Parameter(Mandatory=$true)][string]$AppDirectory,
    [string]$TypeMatch = '',
    [string]$MethodMatch = '.*',
    [switch]$IncludeIL,
    [switch]$RpcCandidates
)
$ErrorActionPreference = 'Stop'
# Only file metadata and PE bytes are read. Assembly.Load/LoadFrom is deliberately
# absent, so vendor initializers cannot run or initiate network requests.
$directory = Get-Item -LiteralPath $AppDirectory -ErrorAction Stop
if (-not $directory.PSIsContainer) { throw 'AppDirectory must be a directory.' }
$typePattern = [regex]::new($TypeMatch)
$methodPattern = [regex]::new($MethodMatch)
$files = @(Get-ChildItem -LiteralPath $directory.FullName -Filter 'ZYing*.dll' -File | Sort-Object Name)
if (-not $files.Count) { throw 'No ZYing*.dll files were found in AppDirectory.' }
$opcodes = @{}
foreach ($field in [System.Reflection.Emit.OpCodes].GetFields([System.Reflection.BindingFlags]'Public,Static')) {
    $op = [System.Reflection.Emit.OpCode]$field.GetValue($null)
    $opcodes[([int]$op.Value -band 0xffff)] = $op
}
function Read-SigUInt([byte[]]$bytes,[ref]$index) {
    $first=[int]$bytes[$index.Value];$index.Value++
    if(($first-band0x80)-eq0){return $first}
    if(($first-band0xc0)-eq0x80){$second=[int]$bytes[$index.Value];$index.Value++;return (($first-band0x3f)-shl8)-bor$second}
    $v=(($first-band0x1f)-shl24)-bor([int]$bytes[$index.Value]-shl16)-bor([int]$bytes[$index.Value+1]-shl8)-bor[int]$bytes[$index.Value+2];$index.Value+=3;return $v
}
function Read-SigType([byte[]]$bytes,[ref]$index) {
    $code=[int]$bytes[$index.Value];$index.Value++
    switch($code) {
      1 {return 'void'};2{return 'bool'};3{return 'char'};4{return 'sbyte'};5{return 'byte'};6{return 'short'};7{return 'ushort'};8{return 'int'};9{return 'uint'};10{return 'long'};11{return 'ulong'};12{return 'float'};13{return 'double'};14{return 'string'};28{return 'object'}
      {$_-in17,18} {$coded=Read-SigUInt $bytes $index;$rid=$coded-shr2;$table=switch($coded-band3){0{0x02000000};1{0x01000000};2{0x1b000000}};return Resolve-StaticToken ($table-bor$rid)}
      21 {$generic=Read-SigType $bytes $index;$count=Read-SigUInt $bytes $index;$args=@();for($i=0;$i-lt$count;$i++){$args+=Read-SigType $bytes $index};return $generic+'<'+($args-join',')+'>'}
      29 {return (Read-SigType $bytes $index)+'[]'}
      15 {return (Read-SigType $bytes $index)+'*'}
      16 {return (Read-SigType $bytes $index)+'&'}
      19 {$number=Read-SigUInt $bytes $index;return '!'+$number}
      30 {$number=Read-SigUInt $bytes $index;return '!!'+$number}
      default {return ('sig:0x{0:X2}'-f$code)}
    }
}
function Resolve-StaticToken([int]$token) {
    $rid = $token -band 0x00ffffff
    switch ($token -band 0xff000000) {
        0x70000000 { return '"' + $script:reader.GetUserString([System.Reflection.Metadata.Ecma335.MetadataTokens]::UserStringHandle($rid)) + '"' }
        0x01000000 { $row=$script:reader.GetTypeReference([System.Reflection.Metadata.Ecma335.MetadataTokens]::TypeReferenceHandle($rid)); return ($script:reader.GetString($row.Namespace)+'.'+$script:reader.GetString($row.Name)).Trim('.') }
        0x02000000 { return Get-DefinitionName ([System.Reflection.Metadata.Ecma335.MetadataTokens]::TypeDefinitionHandle($rid)) }
        0x06000000 { $row=$script:reader.GetMethodDefinition([System.Reflection.Metadata.Ecma335.MetadataTokens]::MethodDefinitionHandle($rid)); return (Resolve-StaticToken ([System.Reflection.Metadata.Ecma335.MetadataTokens]::GetToken([System.Reflection.Metadata.EntityHandle]$row.GetDeclaringType())))+'::'+$script:reader.GetString($row.Name) }
        0x04000000 { $row=$script:reader.GetFieldDefinition([System.Reflection.Metadata.Ecma335.MetadataTokens]::FieldDefinitionHandle($rid)); return (Resolve-StaticToken ([System.Reflection.Metadata.Ecma335.MetadataTokens]::GetToken([System.Reflection.Metadata.EntityHandle]$row.GetDeclaringType())))+'::'+$script:reader.GetString($row.Name) }
        0x0a000000 { $row=$script:reader.GetMemberReference([System.Reflection.Metadata.Ecma335.MetadataTokens]::MemberReferenceHandle($rid)); return (Resolve-StaticToken ([System.Reflection.Metadata.Ecma335.MetadataTokens]::GetToken([System.Reflection.Metadata.EntityHandle]$row.Parent)))+'::'+$script:reader.GetString($row.Name) }
        0x2b000000 { $row=$script:reader.GetMethodSpecification([System.Reflection.Metadata.Ecma335.MetadataTokens]::MethodSpecificationHandle($rid)); return (Resolve-StaticToken ([System.Reflection.Metadata.Ecma335.MetadataTokens]::GetToken([System.Reflection.Metadata.EntityHandle]$row.Method)))+'<generic>' }
        0x1b000000 { $row=$script:reader.GetTypeSpecification([System.Reflection.Metadata.Ecma335.MetadataTokens]::TypeSpecificationHandle($rid));$bytes=$script:reader.GetBlobBytes($row.Signature);$idx=0;return Read-SigType $bytes ([ref]$idx) }
        default { return ('token:0x{0:X8}' -f $token) }
    }
}
function Get-DefinitionName($handle) {
    $row=$script:reader.GetTypeDefinition($handle)
    $parent=$row.GetDeclaringType()
    if (-not $parent.IsNil) { return (Get-DefinitionName $parent)+'+'+$script:reader.GetString($row.Name) }
    return ($script:reader.GetString($row.Namespace)+'.'+$script:reader.GetString($row.Name)).Trim('.')
}
function Get-StaticIL($method) {
    if ($method.RelativeVirtualAddress -eq 0) { return @() }
    $body=[System.Reflection.Metadata.PEReaderExtensions]::GetMethodBody($script:pe,$method.RelativeVirtualAddress)
    $bytes=$body.GetILBytes(); $pos=0; $lines=@()
    while ($pos -lt $bytes.Length) {
        $start=$pos; $code=[int]$bytes[$pos]; $pos++
        if ($code -eq 0xfe) { $code=0xfe00 -bor [int]$bytes[$pos]; $pos++ }
        $op=$opcodes[$code]
        if ($null -eq $op) { throw "Unknown opcode $code at $start" }
        $arg=''
        switch ($op.OperandType.ToString()) {
            {$_ -in 'InlineString','InlineMethod','InlineField','InlineType','InlineTok'} { $token=[BitConverter]::ToInt32($bytes,$pos); $pos+=4; $arg=Resolve-StaticToken $token }
            'InlineI' { $arg=[BitConverter]::ToInt32($bytes,$pos); $pos+=4 }
            'ShortInlineI' { $arg=[int]$bytes[$pos]; if ($arg -gt 127) { $arg-=256 }; $pos++ }
            'InlineI8' { $arg=[BitConverter]::ToInt64($bytes,$pos); $pos+=8 }
            'InlineBrTarget' { $offset=[BitConverter]::ToInt32($bytes,$pos); $pos+=4; $arg='IL_{0:X4}' -f ($pos+$offset) }
            'ShortInlineBrTarget' { $offset=[int]$bytes[$pos]; if($offset -gt 127){$offset-=256}; $pos++; $arg='IL_{0:X4}' -f ($pos+$offset) }
            'InlineSwitch' {
                $count=[BitConverter]::ToInt32($bytes,$pos); $pos+=4
                $base=$pos+4*$count; $targets=@()
                for($n=0;$n-lt$count;$n++) {
                    $targets+=('IL_{0:X4}'-f($base+[BitConverter]::ToInt32($bytes,$pos+4*$n)))
                }
                $arg=$targets-join', '; $pos=$base
            }
            'ShortInlineVar' { $arg=[int]$bytes[$pos]; $pos++ }
            'InlineVar' { $arg=[BitConverter]::ToUInt16($bytes,$pos); $pos+=2 }
            'InlineSig' { $pos+=4 }
            'ShortInlineR' { $arg=[BitConverter]::ToSingle($bytes,$pos); $pos+=4 }
            'InlineR' { $arg=[BitConverter]::ToDouble($bytes,$pos); $pos+=8 }
        }
        $lines += ('IL_{0:X4}: {1} {2}' -f $start,$op.Name,$arg)
    }
    return $lines
}
function Get-MethodSignature($method) {
    $bytes = $script:reader.GetBlobBytes($method.Signature)
    $index = 0
    $flags = [int]$bytes[$index]; $index++
    $genericCount = 0
    if (($flags -band 0x10) -ne 0) { $genericCount = Read-SigUInt $bytes ([ref]$index) }
    $count = Read-SigUInt $bytes ([ref]$index)
    $returnType = Read-SigType $bytes ([ref]$index)
    $parameters = @()
    for ($number = 0; $number -lt $count; $number++) {
        $parameters += Read-SigType $bytes ([ref]$index)
    }
    $generic = if ($genericCount) { "<$genericCount generic parameters>" } else { '' }
    return "$($script:reader.GetString($method.Name))$generic ($($parameters -join ', ')) => $returnType"
}

function Get-FieldType($field) {
    $bytes = $script:reader.GetBlobBytes($field.Signature)
    $index = 1
    return Read-SigType $bytes ([ref]$index)
}

function Find-RpcCandidates {
    $resultType = 'System.Threading.Tasks.Task`1<ZYing.ZResult>'
    $recordSignature = '(ZYing.Data.Record[]) => ' + $resultType
    $idSignature = '(string, int) => ' + $resultType
    foreach ($handle in $script:reader.TypeDefinitions) {
        $type = $script:reader.GetTypeDefinition($handle)
        # Start with the socket field, then check both public instance send signatures.
        $hasTcpClient = $false
        foreach ($fieldHandle in $type.GetFields()) {
            $field = $script:reader.GetFieldDefinition($fieldHandle)
            if ((Get-FieldType $field) -ceq 'System.Net.Sockets.TcpClient') {
                $hasTcpClient = $true
                break
            }
        }
        if (-not $hasTcpClient) { continue }

        $recordMethods = @()
        $idMethods = @()
        foreach ($methodHandle in $type.GetMethods()) {
            $method = $script:reader.GetMethodDefinition($methodHandle)
            if (($method.Attributes -band [Reflection.MethodAttributes]::MemberAccessMask) -ne
                    [Reflection.MethodAttributes]::Public -or
                    ($method.Attributes -band [Reflection.MethodAttributes]::Static)) { continue }
            $signature = Get-MethodSignature $method
            $name = $script:reader.GetString($method.Name)
            if ($signature -ceq "$name $recordSignature") { $recordMethods += $name }
            if ($signature -ceq "$name $idSignature") { $idMethods += $name }
        }
        if (-not $recordMethods.Count -or -not $idMethods.Count) { continue }

        $serverTypes = @(foreach ($nestedHandle in $type.GetNestedTypes()) {
            $nested = $script:reader.GetTypeDefinition($nestedHandle)
            $constructible = $false
            $endpointMethods = @(foreach ($methodHandle in $nested.GetMethods()) {
                $method = $script:reader.GetMethodDefinition($methodHandle)
                if (($method.Attributes -band [Reflection.MethodAttributes]::MemberAccessMask) -ne
                        [Reflection.MethodAttributes]::Public -or
                        ($method.Attributes -band [Reflection.MethodAttributes]::Static)) { continue }
                $name = $script:reader.GetString($method.Name)
                $signature = Get-MethodSignature $method
                if ($signature -ceq '.ctor (System.Net.IPEndPoint) => void') { $constructible = $true }
                if ($signature -ceq "$name () => System.Net.IPEndPoint") { $name }
            })
            if ($constructible -and $endpointMethods.Count) {
                [ordered]@{type = Get-DefinitionName $nestedHandle; endpoint_methods = $endpointMethods}
            }
        })
        [ordered]@{
            rpc_type = Get-DefinitionName $handle
            send_id_methods = $idMethods
            send_records_methods = $recordMethods
            server_types = $serverTypes
        }
    }
}

if ($RpcCandidates) {
    $stream = [IO.File]::OpenRead((Join-Path $directory.FullName 'ZYing.Work.dll'))
    $sha = [Security.Cryptography.SHA256]::Create()
    $script:pe = $null
    try {
        $hash = [BitConverter]::ToString($sha.ComputeHash($stream)).Replace('-', '')
        $stream.Position = 0
        $script:pe = [System.Reflection.PortableExecutable.PEReader]::new($stream)
        $candidates = @()
        $status = 'not_managed'
        if ($script:pe.HasMetadata) {
            $script:reader = [System.Reflection.Metadata.PEReaderExtensions]::GetMetadataReader($script:pe)
            $candidates = @(Find-RpcCandidates)
            $status = switch ($candidates.Count) {
                0 { 'not_found' }
                1 { 'found' }
                default { 'ambiguous' }
            }
        }
        [ordered]@{status = $status; work_sha256 = $hash; candidates = $candidates} | ConvertTo-Json -Depth 6 -Compress
    } finally {
        if ($script:pe) { $script:pe.Dispose() }
        $sha.Dispose()
        $stream.Dispose()
    }
    return
}

foreach ($file in $files) {
    $hash = (Get-FileHash -LiteralPath $file.FullName -Algorithm SHA256).Hash
    "ASSEMBLY $($file.Name) SHA256=$hash BYTES=$($file.Length)"
    $stream = [IO.File]::OpenRead($file.FullName)
    $script:pe = $null
    try {
        $script:pe = [System.Reflection.PortableExecutable.PEReader]::new($stream)
        if (-not $script:pe.HasMetadata) { 'NO_MANAGED_METADATA'; continue }
        $script:reader = [System.Reflection.Metadata.PEReaderExtensions]::GetMetadataReader($script:pe)
        foreach ($handle in $script:reader.TypeDefinitions) {
            $type = $script:reader.GetTypeDefinition($handle)
            $typeName = Get-DefinitionName $handle
            if ($TypeMatch) {
                if (-not $typePattern.IsMatch($typeName)) { continue }
            } else {
                $candidate = $typeName -match '^ZYing\.(MLogin|ZResult)$|登录'
                if (-not $candidate -and $file.Name -eq 'ZYing.Work.dll') {
                    foreach ($candidateHandle in $type.GetMethods()) {
                        $candidateMethod = $script:reader.GetMethodDefinition($candidateHandle)
                        if ((Get-MethodSignature $candidateMethod) -match 'ZYing.Data.Record\[\].*ZYing.ZResult') {
                            $candidate = $true; break
                        }
                    }
                }
                if (-not $candidate) { continue }
            }
            "TYPE $typeName"
            foreach ($fieldHandle in $type.GetFields()) {
                $field = $script:reader.GetFieldDefinition($fieldHandle)
                "FIELD $($script:reader.GetString($field.Name)) $(Get-FieldType $field) [$($field.Attributes)]"
            }
            foreach ($methodHandle in $type.GetMethods()) {
                $method = $script:reader.GetMethodDefinition($methodHandle)
                $methodName = $script:reader.GetString($method.Name)
                if (-not $methodPattern.IsMatch($methodName)) { continue }
                "METHOD $(Get-MethodSignature $method) [$($method.Attributes)] RVA=$($method.RelativeVirtualAddress)"
                if ($IncludeIL) { Get-StaticIL $method }
            }
        }
    } finally {
        if ($script:pe) { $script:pe.Dispose() }
        $stream.Dispose()
        $script:reader = $null
        $script:pe = $null
    }
}
