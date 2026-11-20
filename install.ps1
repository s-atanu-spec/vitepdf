# VitePDF installer. Run install.bat, not this file.
#
# 1. Checks every file of this copy against SHA256SUMS.txt.
# 2. Shows what VitePDF is, what will be installed, and the terms.
#    Nothing is downloaded or installed before you accept.
# 3. Finds Python 3.12 or 3.13 (64-bit). If there is none, downloads the
#    official installer from python.org, checks its digital signature and
#    installs it for the current user only.
# 4. Hands over to "vitepdf.py --setup", which does everything else.
#
# Created by Atanu Sarkar. Made with Claude.

$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'

$AppVersion = '1.4.0'
$Here = Split-Path -Parent $MyInvocation.MyCommand.Path
# Python 3.13.17 is the last 3.13 release with a Windows installer. Older
# patch levels miss security fixes and are not accepted.
$PyVersion = '3.13.17'
$PyUrl = 'https://www.python.org/ftp/python/' + $PyVersion + '/python-' + $PyVersion + '-amd64.exe'
$PyCheck = "import sys, platform, tkinter, venv; print('VITEPDF_OK' if sys.version_info[:2] == (3, 13) and sys.version_info[:3] >= (3, 13, 17) and platform.machine() == 'AMD64' and sys.maxsize > 2**32 else 'VITEPDF_NO')"

function Test-Checksums($dir) {
    $sumFile = Join-Path $dir 'SHA256SUMS.txt'
    if (-not (Test-Path -LiteralPath $sumFile)) {
        throw 'SHA256SUMS.txt is missing. Get VitePDF again from its original source.'
    }
    $listed = @()
    foreach ($raw in (Get-Content -LiteralPath $sumFile)) {
        $line = $raw.Trim()
        if ($line -eq '') { continue }
        if ($line.StartsWith('#')) { continue }
        $parts = $line -split '\s+', 2
        if ($parts.Count -ne 2) { throw 'SHA256SUMS.txt is not readable.' }
        $name = $parts[1].TrimStart('*')
        if ($name -match '[\\/:]') { throw ('Suspicious file name in SHA256SUMS.txt: ' + $name) }
        if ($name -match '\.\.') { throw ('Suspicious file name in SHA256SUMS.txt: ' + $name) }
        $file = Join-Path $dir $name
        if (-not (Test-Path -LiteralPath $file)) { throw ('A file is missing: ' + $name) }
        $hash = (Get-FileHash -LiteralPath $file -Algorithm SHA256).Hash
        if ($hash -ne $parts[0]) { throw ('This file was changed or damaged: ' + $name) }
        $listed += $name
    }
    foreach ($need in @('vitepdf.py', 'vp_core.py', 'vp_ops.py', 'vp_ui.py', 'vp_shell.py', 'vp_main.py', 'install.ps1', 'install.bat', 'requirements.txt', 'launcher.cs', 'vitepdf_sign.py', 'TERMS.txt')) {
        if ($listed -notcontains $need) { throw ('SHA256SUMS.txt does not cover ' + $need) }
    }
    return $listed.Count
}

function Show-Welcome($dir) {
    Add-Type -AssemblyName System.Windows.Forms
    Add-Type -AssemblyName System.Drawing
    [System.Windows.Forms.Application]::EnableVisualStyles()

    $terms = [System.IO.File]::ReadAllText((Join-Path $dir 'TERMS.txt'))
    $terms = $terms -replace "`r?`n", "`r`n"

    $form = New-Object System.Windows.Forms.Form
    $form.Text = 'VitePDF ' + $AppVersion + ' Setup'
    $form.StartPosition = [System.Windows.Forms.FormStartPosition]::CenterScreen
    $form.FormBorderStyle = [System.Windows.Forms.FormBorderStyle]::FixedDialog
    $form.MaximizeBox = $false
    $form.MinimizeBox = $false
    $form.ClientSize = New-Object System.Drawing.Size(620, 580)
    $form.Font = New-Object System.Drawing.Font('Segoe UI', 9)
    $form.TopMost = $true

    try {
        $icon = New-Object System.Drawing.Icon((Join-Path $dir 'vitepdf.ico'), 48, 48)
        $form.Icon = $icon
        $pic = New-Object System.Windows.Forms.PictureBox
        $pic.Location = New-Object System.Drawing.Point(20, 16)
        $pic.Size = New-Object System.Drawing.Size(48, 48)
        $pic.Image = $icon.ToBitmap()
        $form.Controls.Add($pic)
    } catch { }

    $title = New-Object System.Windows.Forms.Label
    $title.Text = 'VitePDF ' + $AppVersion
    $title.Font = New-Object System.Drawing.Font('Segoe UI', 14, [System.Drawing.FontStyle]::Bold)
    $title.Location = New-Object System.Drawing.Point(80, 12)
    $title.AutoSize = $true
    $form.Controls.Add($title)

    $sub = New-Object System.Windows.Forms.Label
    $sub.Text = 'Right-click image and PDF tools.  Created by Atanu Sarkar. Made with Claude.'
    $sub.Location = New-Object System.Drawing.Point(82, 44)
    $sub.AutoSize = $true
    $form.Controls.Add($sub)

    $box = New-Object System.Windows.Forms.RichTextBox
    $box.ReadOnly = $true
    $box.DetectUrls = $false
    $box.ScrollBars = [System.Windows.Forms.RichTextBoxScrollBars]::Vertical
    $box.BackColor = [System.Drawing.Color]::White
    $box.Location = New-Object System.Drawing.Point(20, 80)
    $box.Size = New-Object System.Drawing.Size(580, 410)
    # One left edge for plain text and one for list items; wrapped lines of
    # an item start under its first word.
    $bold = New-Object System.Drawing.Font('Segoe UI', 9, [System.Drawing.FontStyle]::Bold)
    foreach ($line in ($terms -split "`r?`n")) {
        $m = [regex]::Match($line, '^(\s*)((?:-|\d+\.)\s+)?(.*)$')
        $lead = $m.Groups[1].Value.Length
        $mark = $m.Groups[2].Value.Trim()
        $rest = $m.Groups[3].Value
        $box.SelectionStart = $box.TextLength
        $box.SelectionLength = 0
        $box.SelectionFont = $form.Font
        if ($mark -ne '' -or ($lead -gt 0 -and $lead -lt 4)) {
            if ($mark -eq '') { $mark = [string][char]0x2022 }
            $box.SelectionIndent = 12
            $box.SelectionHangingIndent = 22
            $box.SelectionTabs = @(34)
            $box.AppendText($mark + "`t" + $rest + "`n")
        } elseif ($lead -ge 4) {
            $box.SelectionIndent = 34
            $box.SelectionHangingIndent = 0
            $box.AppendText($rest + "`n")
        } else {
            $box.SelectionIndent = 0
            $box.SelectionHangingIndent = 0
            if ($rest.Length -gt 3 -and $rest -ceq $rest.ToUpper()) { $box.SelectionFont = $bold }
            $box.AppendText($rest + "`n")
        }
    }
    $box.SelectionStart = 0
    $box.ScrollToCaret()
    $box.TabStop = $false
    $form.Controls.Add($box)

    $install = New-Object System.Windows.Forms.Button
    $install.Text = 'Install'
    $install.Location = New-Object System.Drawing.Point(418, 536)
    $install.Size = New-Object System.Drawing.Size(86, 28)
    $install.Enabled = $false
    $install.DialogResult = [System.Windows.Forms.DialogResult]::OK
    $form.Controls.Add($install)
    $form.AcceptButton = $install

    $cancel = New-Object System.Windows.Forms.Button
    $cancel.Text = 'Cancel'
    $cancel.Location = New-Object System.Drawing.Point(514, 536)
    $cancel.Size = New-Object System.Drawing.Size(86, 28)
    $cancel.DialogResult = [System.Windows.Forms.DialogResult]::Cancel
    $form.Controls.Add($cancel)
    $form.CancelButton = $cancel

    $check = New-Object System.Windows.Forms.CheckBox
    $check.Text = 'I have read and accept the terms. Install VitePDF.'
    $check.Location = New-Object System.Drawing.Point(20, 502)
    $check.AutoSize = $true
    $check.Add_CheckedChanged({ $this.FindForm().AcceptButton.Enabled = $this.Checked })
    $form.Controls.Add($check)

    $form.Add_Shown({ $this.Activate() })
    $result = $form.ShowDialog()
    $form.Dispose()
    return ($result -eq [System.Windows.Forms.DialogResult]::OK)
}

function Test-Python($exe) {
    if (-not $exe) { return $false }
    if (-not (Test-Path -LiteralPath $exe)) { return $false }
    if ($exe -like '*\WindowsApps\*') { return $false }
    $old = $ErrorActionPreference
    $ErrorActionPreference = 'SilentlyContinue'
    $out = ''
    try { $out = (& $exe -I -c $PyCheck 2>$null) | Out-String } catch { $out = '' }
    $ErrorActionPreference = $old
    return ($out -match 'VITEPDF_OK')
}

function Find-Python {
    $list = @(
        (Join-Path $env:LOCALAPPDATA 'Programs\Python\Python313\python.exe'),
        (Join-Path $env:ProgramFiles 'Python313\python.exe')
    )
    foreach ($root in @('HKCU:\Software\Python\PythonCore', 'HKLM:\Software\Python\PythonCore')) {
        foreach ($ver in @('3.13')) {
            $key = $root + '\' + $ver + '\InstallPath'
            $item = Get-ItemProperty -LiteralPath $key -ErrorAction SilentlyContinue
            if ($item -and $item.ExecutablePath) { $list += $item.ExecutablePath }
        }
    }
    foreach ($p in $list) {
        if (Test-Python $p) { return $p }
    }
    return $null
}

try {
    Write-Host ''
    Write-Host ('VitePDF ' + $AppVersion + ' installer')
    Write-Host '-----------------------'

    $count = Test-Checksums $Here
    Write-Host ('Checksums: all ' + $count + ' files match SHA256SUMS.txt.')

    $accepted = $false
    try {
        $accepted = Show-Welcome $Here
    }
    catch {
        Write-Host ''
        Write-Host (Get-Content -LiteralPath (Join-Path $Here 'TERMS.txt') | Out-String)
        $answer = Read-Host 'Type Y to accept the terms and install VitePDF'
        $accepted = ($answer -match '^\s*[Yy]')
    }
    if (-not $accepted) {
        Write-Host 'Installation cancelled.'
        exit 2
    }
    Write-Host 'Terms accepted.'

    $py = Find-Python
    if (-not $py) {
        Write-Host ('Python ' + $PyVersion + ' or newer 3.13 was not found. Downloading it from python.org (about 29 MB) ...')
        [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
        $tmp = Join-Path $env:TEMP ('python-' + $PyVersion + '-amd64.exe')
        Invoke-WebRequest -Uri $PyUrl -OutFile $tmp -UseBasicParsing

        $sig = Get-AuthenticodeSignature -FilePath $tmp
        if (($sig.Status -ne 'Valid') -or ($sig.SignerCertificate.Subject -notmatch 'Python Software Foundation')) {
            Remove-Item -LiteralPath $tmp -ErrorAction SilentlyContinue
            throw 'The downloaded Python installer did not pass the signature check.'
        }

        Write-Host 'Installing Python for the current user (no admin rights needed) ...'
        $setupArgs = @('/quiet', 'InstallAllUsers=0', 'PrependPath=0', 'Include_launcher=0',
                       'Include_test=0', 'Include_doc=0', 'Shortcuts=0', 'AssociateFiles=0')
        $proc = Start-Process -FilePath $tmp -ArgumentList $setupArgs -Wait -PassThru
        if ($proc.ExitCode -ne 0) {
            throw ('The Python installer stopped with code ' + $proc.ExitCode + '.')
        }
        Remove-Item -LiteralPath $tmp -ErrorAction SilentlyContinue

        $py = Find-Python
        if (-not $py) { throw 'Python was installed but could not be started.' }
    }

    Write-Host ('Using Python: ' + $py)
    & $py -I (Join-Path $Here 'vitepdf.py') --setup
    if ($LASTEXITCODE -ne 0) {
        throw ('Setup stopped with code ' + $LASTEXITCODE + '.')
    }

    $exe = Join-Path $env:LOCALAPPDATA 'VitePDF\VitePDF.exe'
    if (Test-Path -LiteralPath $exe) {
        try {
            $shell = New-Object -ComObject WScript.Shell
            $link = $shell.CreateShortcut((Join-Path $env:APPDATA 'Microsoft\Windows\Start Menu\Programs\VitePDF.lnk'))
            $link.TargetPath = $exe
            $link.WorkingDirectory = (Split-Path -Parent $exe)
            $link.Description = 'VitePDF: right-click image and PDF tools'
            $link.Save()
            $old = Join-Path $env:APPDATA 'Microsoft\Windows\Start Menu\Programs\VitePDF Capture area.lnk'
            if (Test-Path -LiteralPath $old) { Remove-Item -LiteralPath $old -Force -ErrorAction SilentlyContinue }
            $cap = $shell.CreateShortcut((Join-Path $env:APPDATA 'Microsoft\Windows\Start Menu\Programs\VitePDF Capture.lnk'))
            $cap.TargetPath = $exe
            $cap.Arguments = 'capture x desktop'
            $cap.WorkingDirectory = (Split-Path -Parent $exe)
            $cap.Hotkey = 'CTRL+ALT+SHIFT+P'
            $cap.IconLocation = (Join-Path (Split-Path -Parent $exe) 'app\vitepdf_capture.ico')
            $cap.Description = 'Capture an area of the screen to a PDF'
            $cap.Save()
            $long = $shell.CreateShortcut((Join-Path $env:APPDATA 'Microsoft\Windows\Start Menu\Programs\VitePDF Scroll.lnk'))
            $long.TargetPath = $exe
            $long.Arguments = 'scroll x desktop'
            $long.WorkingDirectory = (Split-Path -Parent $exe)
            $long.Hotkey = 'CTRL+ALT+SHIFT+S'
            $long.IconLocation = (Join-Path (Split-Path -Parent $exe) 'app\vitepdf_scroll.ico')
            $long.Description = 'Capture a long page to a PDF while it scrolls'
            $long.Save()
        } catch { }
    }
    exit 0
}
catch {
    Write-Host ''
    Write-Host ('ERROR: ' + $_.Exception.Message) -ForegroundColor Red
    exit 1
}
