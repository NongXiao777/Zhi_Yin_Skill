param(
    [Parameter(Mandatory=$true)][string]$AppDirectory,
    [string]$OutputDirectory,
    [string]$SourceFile = 'NativeTransport.cs'
)
$ErrorActionPreference='Stop'
try {
    if($SourceFile -notin @('NativeTransport.cs','NativeLoginHost.cs')){throw 'Unsupported native helper source'}
    $sourcePath=Join-Path $PSScriptRoot $SourceFile
    $source=Get-Content -Raw -LiteralPath $sourcePath
    $dotnet=(Get-Command dotnet -ErrorAction Stop).Source
    $shared=Join-Path ([IO.Path]::GetDirectoryName($dotnet)) 'shared'
    $frameworks=@('Microsoft.NETCore.App','Microsoft.WindowsDesktop.App')
    $runtimePaths=@(foreach($framework in $frameworks){
        $path=Get-ChildItem -LiteralPath (Join-Path $shared $framework) -Directory |
            Where-Object {$_.Name -match '^6\.0\.\d+$'} |
            Sort-Object {[version]$_.Name} -Descending | Select-Object -First 1
        if(-not $path){throw 'The installed application requires .NET 6 Desktop Runtime'}
        $path.FullName
    })
    if(-not $OutputDirectory){
        $hash=(Get-FileHash -LiteralPath $sourcePath -Algorithm SHA256).Hash
        $OutputDirectory=Join-Path ([IO.Path]::GetTempPath()) ('zhiying-cli-native-'+$hash.Substring(0,16))
    }
    $OutputDirectory=[IO.Path]::GetFullPath($OutputDirectory)
    New-Item -ItemType Directory -Path $OutputDirectory -Force | Out-Null
    $assemblyPath=Join-Path $OutputDirectory 'NativeTransport.dll'
    $configPath=Join-Path $OutputDirectory 'NativeTransport.runtimeconfig.json'
    if(-not (Test-Path -LiteralPath $assemblyPath) -or -not (Test-Path -LiteralPath $configPath)){
        $references=[Microsoft.CodeAnalysis.MetadataReference[]]@(foreach($file in Get-ChildItem -LiteralPath $runtimePaths -Filter '*.dll' -File){
            $stream=[IO.File]::OpenRead($file.FullName)
            try {
                $pe=[Reflection.PortableExecutable.PEReader]::new($stream)
                if($pe.HasMetadata){[Microsoft.CodeAnalysis.MetadataReference]::CreateFromFile($file.FullName)}
            }finally{if($pe){$pe.Dispose()};$stream.Dispose()}
        })
        $tree=[Microsoft.CodeAnalysis.CSharp.CSharpSyntaxTree]::ParseText($source)
        $options=[Microsoft.CodeAnalysis.CSharp.CSharpCompilationOptions]::new([Microsoft.CodeAnalysis.OutputKind]::ConsoleApplication)
        $compilation=[Microsoft.CodeAnalysis.CSharp.CSharpCompilation]::Create('NativeTransport',[Microsoft.CodeAnalysis.SyntaxTree[]]@($tree),$references,$options)
        $temporary=Join-Path $OutputDirectory ([Guid]::NewGuid().ToString()+'.dll')
        $output=[IO.File]::Create($temporary)
        try{
            $result=$compilation.Emit($output)
            if(-not $result.Success){throw 'Native transport compilation failed'}
        }finally{$output.Dispose()}
        [IO.File]::Move($temporary,$assemblyPath,$true)
        $config=@{runtimeOptions=@{tfm='net6.0';frameworks=@(
            @{name='Microsoft.NETCore.App';version='6.0.0'},
            @{name='Microsoft.WindowsDesktop.App';version='6.0.0'}
        )}} | ConvertTo-Json -Depth 5 -Compress
        [IO.File]::WriteAllText($configPath,$config)
    }
    @{ok=$true;executable=$dotnet;assembly=$assemblyPath;app_directory=[IO.Path]::GetFullPath($AppDirectory)} | ConvertTo-Json -Compress
}catch{
    @{ok=$false;error='native_build_failed';requirement='PowerShell 7 and .NET 6 Windows Desktop Runtime'} | ConvertTo-Json -Compress
    exit 1
}
