$ErrorActionPreference = 'Stop'
[Console]::InputEncoding = [Text.UTF8Encoding]::new($false)
[Console]::OutputEncoding = [Text.UTF8Encoding]::new($false)
Add-Type -AssemblyName System.Runtime.WindowsRuntime
$null = [Windows.Media.Ocr.OcrEngine, Windows.Foundation, ContentType=WindowsRuntime]
$null = [Windows.Globalization.Language, Windows.Globalization, ContentType=WindowsRuntime]
$null = [Windows.Storage.Streams.InMemoryRandomAccessStream, Windows.Storage.Streams, ContentType=WindowsRuntime]
$null = [Windows.Storage.Streams.DataWriter, Windows.Storage.Streams, ContentType=WindowsRuntime]
$null = [Windows.Graphics.Imaging.BitmapDecoder, Windows.Graphics.Imaging, ContentType=WindowsRuntime]
$taskAwaitMethod = [System.WindowsRuntimeSystemExtensions].GetMethods() | Where-Object {
    $_.Name -eq 'AsTask' -and $_.IsGenericMethodDefinition -and $_.GetGenericArguments().Count -eq 1 -and
    $_.GetParameters().Count -eq 1 -and $_.GetParameters()[0].ParameterType.Name -eq 'IAsyncOperation`1'
} | Select-Object -First 1
function Await-Operation($Operation, [Type]$ResultType) {
    $taskPending = $taskAwaitMethod.MakeGenericMethod($ResultType).Invoke($null, @($Operation))
    if (-not $taskPending.Wait(5000)) { throw 'Windows OCR operation timed out' }
    return $taskPending.Result
}
$taskEngines = @{}
while ($null -ne ($taskLine = [Console]::ReadLine())) {
    $taskStream = $null; $taskWriter = $null; $taskBitmap = $null
    try {
        $taskRequest = $taskLine | ConvertFrom-Json
        $taskLanguage = if ($taskRequest.language) { [string]$taskRequest.language } else { 'en-US' }
        if (-not $taskEngines.ContainsKey($taskLanguage)) {
            $taskEngine = [Windows.Media.Ocr.OcrEngine]::TryCreateFromLanguage([Windows.Globalization.Language]::new($taskLanguage))
            if ($null -eq $taskEngine) { throw "Windows OCR language is unavailable: $taskLanguage" }
            $taskEngines[$taskLanguage] = $taskEngine
        }
        $taskStream = [Windows.Storage.Streams.InMemoryRandomAccessStream]::new()
        $taskWriter = [Windows.Storage.Streams.DataWriter]::new($taskStream)
        $taskWriter.WriteBytes([Convert]::FromBase64String($taskRequest.png))
        $null = Await-Operation $taskWriter.StoreAsync() ([uint32])
        $null = $taskWriter.DetachStream()
        $taskStream.Seek(0)
        $taskDecoder = Await-Operation ([Windows.Graphics.Imaging.BitmapDecoder]::CreateAsync($taskStream)) ([Windows.Graphics.Imaging.BitmapDecoder])
        $taskBitmap = Await-Operation ($taskDecoder.GetSoftwareBitmapAsync()) ([Windows.Graphics.Imaging.SoftwareBitmap])
        $taskResult = Await-Operation ($taskEngines[$taskLanguage].RecognizeAsync($taskBitmap)) ([Windows.Media.Ocr.OcrResult])
        [Console]::WriteLine((@{ok=$true; text=$taskResult.Text} | ConvertTo-Json -Compress))
    } catch {
        [Console]::WriteLine((@{ok=$false; error=$_.Exception.Message} | ConvertTo-Json -Compress))
    } finally {
        if ($null -ne $taskBitmap) { $taskBitmap.Dispose() }
        if ($null -ne $taskWriter) { $taskWriter.Dispose() }
        if ($null -ne $taskStream) { $taskStream.Dispose() }
    }
}
