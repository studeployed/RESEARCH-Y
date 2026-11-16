param([Parameter(Mandatory=$true)][string]$Launcher)
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName UIAutomationClient,UIAutomationTypes
$launcherFile = Get-Item -LiteralPath $Launcher
$python = Join-Path $launcherFile.Directory 'python.exe'
$dialogHelper = Join-Path (Split-Path $PSScriptRoot) 'windows_folder_dialog.py'
$testRoot = [IO.Directory]::CreateTempSubdirectory('ry-picker-').FullName
$parent = [IO.Directory]::CreateDirectory((Join-Path $testRoot 'Work')).FullName
$project = Join-Path $parent 'Picker-test'
$index = Join-Path $project 'project.ryproj'
$appHost = $null
$windowProcess = $null

function Wait-For($test, [string]$description, [int]$seconds=35) {
    $until = [DateTime]::UtcNow.AddSeconds($seconds)
    do {
        $result = & $test
        if ($result) { return $result }
        Start-Sleep -Milliseconds 200
    } while ([DateTime]::UtcNow -lt $until)
    throw "Timed out waiting for $description"
}
function Find-Control($root, $property, $value) {
    $condition = [Windows.Automation.PropertyCondition]::new($property, $value)
    $root.FindFirst([Windows.Automation.TreeScope]::Descendants,$condition)
}
function Find-Button([string]$text) {
    $condition = [Windows.Automation.PropertyCondition]::new(
        [Windows.Automation.AutomationElement]::ControlTypeProperty,[Windows.Automation.ControlType]::Button)
    $window.FindAll([Windows.Automation.TreeScope]::Descendants,$condition) |
        Where-Object { $_.Current.Name -eq $text } | Select-Object -First 1
}
function Click-Button([string]$text) {
    $button = Wait-For { Find-Button $text } $text
    $button.GetCurrentPattern([Windows.Automation.InvokePattern]::Pattern).Invoke()
}
function Choose-Folder([string]$path) {
    $select = 'import runpy,sys; from pathlib import Path; runpy.run_path(sys.argv[1])["choose_fixture_folder"]({int(sys.argv[2])},Path(sys.argv[3]) if sys.argv[3] else None)'
    & $python -I -B -c $select $dialogHelper $windowProcess.Id $path
    if ($LASTEXITCODE -ne 0) { throw 'Windows did not complete the requested picker action' }
}
try {
    $seed = 'import sys; from research_y.projects import create_project; create_project(sys.argv[1], "Existing")'
    & $python -I -B -c $seed $testRoot
    if ($LASTEXITCODE -ne 0) { throw 'Could not create the disposable open-project fixture' }
    $start = [Diagnostics.ProcessStartInfo]::new($launcherFile.FullName)
    $start.UseShellExecute = $false
    $start.WorkingDirectory = $launcherFile.Directory.FullName
    $start.EnvironmentVariables['LOCALAPPDATA'] = $testRoot
    $start.EnvironmentVariables['USERPROFILE'] = $testRoot
    $start.EnvironmentVariables.Remove('HOMEPATH')
    $started = [Diagnostics.Process]::Start($start)
    $appHost = Wait-For {
        Get-CimInstance Win32_Process -Filter "ParentProcessId=$($started.Id) AND Name='pythonw.exe'" |
            Where-Object { $_.ExecutablePath -eq (Join-Path $launcherFile.Directory 'pythonw.exe') }
    } 'packaged application'
    $windowProcess = Wait-For {
        Get-CimInstance Win32_Process -Filter "ParentProcessId=$($appHost.ProcessId) AND Name='pythonw.exe'" |
            ForEach-Object { Get-Process -Id $_.ProcessId -ErrorAction SilentlyContinue } |
            Where-Object { $_.MainWindowTitle -eq 'RESEARCH-Y' }
    } 'packaged desktop window'
    $window = [Windows.Automation.AutomationElement]::FromHandle($windowProcess.MainWindowHandle)
    $open = 'Open project folder'
    Click-Button $open
    Choose-Folder ''
    Wait-For { Find-Control $window ([Windows.Automation.AutomationElement]::NameProperty) 'Selection cancelled.' } 'cancellation feedback' | Out-Null
    Write-Output 'Open displayed and cancelled its Windows folder picker.'
    $name = Wait-For {
        Find-Control $window ([Windows.Automation.AutomationElement]::ControlTypeProperty) ([Windows.Automation.ControlType]::Edit)
    } 'project name'
    $name.GetCurrentPattern([Windows.Automation.ValuePattern]::Pattern).SetValue('Picker test')
    Click-Button 'Create project in folder'
    Choose-Folder $parent
    Wait-For { Test-Path -LiteralPath $index -PathType Leaf } 'created project index' | Out-Null
    Wait-For { Find-Control $window ([Windows.Automation.AutomationElement]::NameProperty) 'Project: Picker test' } 'open created project' | Out-Null
    Click-Button $open
    Choose-Folder (Join-Path $testRoot 'Existing')
    Wait-For { Find-Control $window ([Windows.Automation.AutomationElement]::NameProperty) 'Project: Existing' } 'opened existing project' | Out-Null
    Write-Output 'Packaged launcher created a project and opened a different existing project.'
} catch {
    Write-Output $_.ScriptStackTrace
    throw
} finally {
    if ($windowProcess) { $null=$windowProcess.CloseMainWindow() }
    if ($appHost) {
        $process = Get-Process -Id $appHost.ProcessId -ErrorAction SilentlyContinue
        if ($process -and !$process.WaitForExit(7000)) {
            if ($process.Path -eq (Join-Path $launcherFile.Directory 'pythonw.exe')) { $process.Kill($true); $process.WaitForExit() }
        }
    }
    $base = [IO.Path]::GetFullPath([IO.Path]::GetTempPath())
    $target = [IO.Path]::GetFullPath($testRoot)
    if ([IO.Path]::GetDirectoryName($target).TrimEnd('\') -eq $base.TrimEnd('\') -and
        [IO.Path]::GetFileName($target).StartsWith('ry-picker-')) {
        Remove-Item -LiteralPath $target -Recurse -Force
    }
}
