# astryx install for Windows: sets up WSL2 + Ubuntu with systemd, then runs the Linux installer inside it (goal 10224 S3).
#
#   irm https://raw.githubusercontent.com/Umair444/astryx/main/install.ps1 | iex
#
# astryx runs on Linux, so on Windows it lives inside WSL2. This script:
#   1. checks it runs as Administrator (and relaunches itself elevated if not);
#   2. checks the Windows build and virtualization;
#   3. installs WSL2 + Ubuntu if they're missing (a reboot is unavoidable the first time);
#   4. makes sure the distro is WSL2, not WSL1;
#   5. turns on systemd inside the distro (/etc/wsl.conf [boot] systemd=true), then restarts WSL;
#   6. looks at Docker and recommends docker-ce inside WSL;
#   7. runs install.sh inside the distro, which takes it from there.
# Safe to re-run: each step checks first. After the reboot, run the same line again.
#
# Env: ASTRYX_DISTRO (default Ubuntu), ASTRYX_DRY_RUN=1 (print the commands, change nothing),
#      ASTRYX_INSTALL_BASE (default https://raw.githubusercontent.com/Umair444/astryx/main).
# Written for Windows PowerShell 5.1 (the one every Windows has) and PowerShell 7.
# Everything runs inside Install-Astryx and stops with `return`, never `exit`: under `irm | iex`, exit would close
# the person's PowerShell window along with the message explaining what to do next.

function Install-Astryx {
    $ErrorActionPreference = 'Stop'
    Set-StrictMode -Version 2.0

    $Base   = if ($env:ASTRYX_INSTALL_BASE) { $env:ASTRYX_INSTALL_BASE } else { 'https://raw.githubusercontent.com/Umair444/astryx/main' }
    $Distro = if ($env:ASTRYX_DISTRO) { $env:ASTRYX_DISTRO } else { 'Ubuntu' }
    $Dry    = ($env:ASTRYX_DRY_RUN -eq '1')
    $OneLine = "irm $Base/install.ps1 | iex"
    $env:WSL_UTF8 = '1'   # wsl.exe prints UTF-16 unless told otherwise, which breaks reading its output

    function Say([string]$m)  { Write-Host "[astryx] $m" -ForegroundColor Cyan }
    function Ok([string]$m)   { Write-Host "  + $m" -ForegroundColor Green }
    function Warn([string]$m) { Write-Host "  o $m" -ForegroundColor Yellow }
    function Bad([string]$m)  { Write-Host "[astryx] $m" -ForegroundColor Red }
    function Show([string]$c) { Write-Host "    > $c" -ForegroundColor DarkYellow }

    # Runs wsl.exe, showing the line first; output goes straight to the console. Returns the exit code.
    function Invoke-Wsl([string[]]$WslArgs) {
        Show ('wsl ' + ($WslArgs -join ' '))
        if ($Dry) { return 0 }
        & wsl.exe @WslArgs | Out-Host
        return $LASTEXITCODE
    }
    # A shell script for the distro travels base64-encoded: no Windows argument quoting or CRLF ever touches it.
    function Get-B64Cmd([string]$Script, [string]$Shell = 'sh') {
        $b64 = [Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes(($Script -replace "`r", '')))
        return "echo $b64 | base64 -d | $Shell"
    }
    function Invoke-InDistro([string]$Script, [string]$User) {
        $a = @('-d', $Distro)
        if ($User) { $a += @('-u', $User) }
        Show ('wsl ' + ($a -join ' ') + ' -- sh -c <this script>:')
        Write-Host (($Script -replace "`r", '') -replace '(?m)^', '        | ')
        if ($Dry) { return 0 }
        $a += @('--', 'sh', '-c', (Get-B64Cmd $Script))
        & wsl.exe @a | Out-Host
        return $LASTEXITCODE
    }
    # Read-only probes inside the distro: no echo, output returned as one trimmed string ('' on failure).
    function Read-InDistro([string]$Cmd, [string]$User) {
        # Windows PowerShell 5.1 under 'Stop' throws on ANY native stderr, even discarded; a probe must not read noise as ''
        $ErrorActionPreference = 'Continue'
        $a = @('-d', $Distro)
        if ($User) { $a += @('-u', $User) }
        $a += @('--', 'sh', '-c', (Get-B64Cmd $Cmd))
        try { $out = & wsl.exe @a 2>$null } catch { return '' }
        if ($null -eq $out) { return '' }
        return (($out | Out-String).Trim())
    }
    function Get-WslDistros {
        # NAME / STATE / VERSION rows from `wsl -l -v`; the default distro is marked with '*'.
        $ErrorActionPreference = 'Continue'   # see Read-InDistro
        $rows = @()
        try { $raw = & wsl.exe -l -v 2>$null } catch { return $rows }
        if ($LASTEXITCODE -ne 0 -or $null -eq $raw) { return $rows }
        foreach ($line in ($raw | Select-Object -Skip 1)) {
            $l = ($line -replace "`0", '').Trim().TrimStart('*').Trim()
            if (-not $l) { continue }
            $p = $l -split '\s+'
            if ($p.Length -ge 3) { $rows += [pscustomobject]@{ Name = $p[0]; State = $p[1]; Version = $p[$p.Length - 1] } }
        }
        return $rows
    }

    Say 'astryx installer for Windows'
    if ($Dry) { Say 'DRY RUN (ASTRYX_DRY_RUN=1): printing commands, changing nothing' }
    Write-Host @'

  Before you start: astryx agents get full control of the machine they run on. They run commands,
  install software and edit files around the clock. That is the design, so give them a machine of
  their own: a dedicated PC or VM, not your daily computer.

  Also good to know: on Windows the org lives inside WSL2, so when Windows sleeps, the org sleeps.
  For an always-on org, set Power & sleep to "Never" on this machine, or use a Linux server.

'@

    # ── 1. Administrator ────────────────────────────────────────────────────────────────────────────────────────
    $isAdmin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole(
        [Security.Principal.WindowsBuiltInRole]::Administrator)
    if (-not $isAdmin) {
        Say 'Setting up WSL needs Administrator rights. Opening an elevated PowerShell to continue (approve the prompt).'
        # Under `irm | iex` there is no script file to relaunch, so the elevated window re-runs the one-liner.
        $envs = ''
        if ($env:ASTRYX_DISTRO)       { $envs += "`$env:ASTRYX_DISTRO='$Distro'; " }
        if ($Dry)                     { $envs += "`$env:ASTRYX_DRY_RUN='1'; " }
        if ($env:ASTRYX_INSTALL_BASE) { $envs += "`$env:ASTRYX_INSTALL_BASE='$Base'; " }
        $cmd = "$envs$OneLine"
        Show "Start-Process powershell -Verb RunAs -ArgumentList '-NoExit -Command $cmd'"
        try {
            Start-Process powershell.exe -Verb RunAs -ArgumentList @('-NoProfile', '-ExecutionPolicy', 'Bypass', '-NoExit', '-Command', $cmd)
        } catch {
            Bad 'The Administrator prompt was declined, so nothing changed. Open PowerShell with "Run as administrator" and run:'
            Write-Host "    $OneLine"
        }
        return
    }
    Ok 'running as Administrator'

    # ── 2. Windows build and virtualization ─────────────────────────────────────────────────────────────────────
    $build = [Environment]::OSVersion.Version.Build
    if ($build -lt 19041) {
        Bad "Windows build $build is too old for 'wsl --install' (it needs Windows 10 version 2004, build 19041, or Windows 11). Update Windows, then run this again."
        return
    }
    Ok "Windows build $build"
    try {
        $hv = (Get-CimInstance Win32_ComputerSystem).HypervisorPresent
        $fw = @(Get-CimInstance Win32_Processor | ForEach-Object { $_.VirtualizationFirmwareEnabled })
        if ($hv) {
            # once Hyper-V/WSL2 is on, the firmware flag reads false: the running hypervisor is the real answer
            Ok 'virtualization: a hypervisor is already running (good for WSL2)'
        } elseif ($fw -contains $true) {
            Ok 'virtualization: enabled in firmware'
        } else {
            Warn 'virtualization looks OFF. WSL2 needs it: enable Intel VT-x / AMD-V (SVM) in your BIOS/UEFI settings.'
            Warn 'If this machine is itself a VM, turn on nested virtualization for it. Continuing; WSL will say so if it truly fails.'
        }
    } catch {
        Warn "couldn't read the virtualization state ($($_.Exception.Message)); continuing"
    }

    # ── 3. WSL and the distro ───────────────────────────────────────────────────────────────────────────────────
    $distros = @()
    $hadWsl = [bool](Get-Command wsl.exe -ErrorAction SilentlyContinue)
    if ($hadWsl) {
        $distros = @(Get-WslDistros)
        # wsl.exe ships with Windows; WSL itself is installed only if `wsl --status` succeeds
        $ErrorActionPreference = 'Continue'
        & wsl.exe --status *> $null
        if ($LASTEXITCODE -ne 0 -and $distros.Count -eq 0) { $hadWsl = $false }
        $ErrorActionPreference = 'Stop'
    }
    $mine = $distros | Where-Object { $_.Name -eq $Distro } | Select-Object -First 1
    if (-not $mine -and -not $env:ASTRYX_DISTRO) {
        # already running e.g. Ubuntu-24.04? use it rather than installing a second Ubuntu
        $mine = $distros | Where-Object { $_.Name -like 'Ubuntu*' } | Select-Object -First 1
        if ($mine) { $Distro = $mine.Name }
    }
    if (-not $mine) {
        Say "Installing WSL2 with $Distro."
        Show "wsl --install -d $Distro"
        $rc = 0
        if (-not $Dry) {
            # called directly (not piped), so the distro's first-launch user prompt, when it appears, reaches this console
            & wsl.exe --install -d $Distro
            $rc = $LASTEXITCODE
        }
        if ($rc -ne 0) {
            Bad "wsl --install failed (exit $rc). If it mentions virtualization, enable VT-x/AMD-V in BIOS/UEFI, restart, and run this again."
            return
        }
        if ($hadWsl) {
            # WSL was already on: no reboot, only the new distro's first launch.
            Write-Host @"

  $Distro is installed. One step only you can do: open "$Distro" from the Start menu once and
  create your Linux username and password. Then run the same line again:

    $OneLine

"@
            return
        }
        Write-Host @"

  WSL is installed. Two steps only you can do, then this picks up where it left off:

    1. Restart Windows. WSL turns on a Windows feature that needs one restart; there is no way around it.
    2. After the restart, open "$Distro" from the Start menu once and create your Linux username and password.

  Then open PowerShell and run the same line again:

    $OneLine

"@
        return
    }
    Ok "WSL distro: $($mine.Name) (WSL$($mine.Version), $($mine.State))"

    # ── 4. WSL2, not WSL1 ───────────────────────────────────────────────────────────────────────────────────────
    [void](Invoke-Wsl @('--set-default-version', '2'))
    if ("$($mine.Version)" -ne '2') {
        Say "$Distro runs on WSL1; astryx needs WSL2 (a real Linux kernel, systemd, docker). Converting; this can take a few minutes."
        $rc = Invoke-Wsl @('--set-version', $Distro, '2')
        if ($rc -ne 0) { Bad "converting $Distro to WSL2 failed (exit $rc). Check that virtualization is enabled, then run this again."; return }
    }
    Ok "$Distro is WSL2"

    # The distro needs its Linux user first: its first launch asks for one, and only a human can answer.
    $uid = Read-InDistro 'id -u'
    if (-not $Dry -and ($uid -eq '' -or $uid -eq '0')) {
        Write-Host @"

  $Distro has no regular Linux user yet (it would run everything as root). Open "$Distro" from the
  Start menu, create your username and password, close it, then run this again:

    $OneLine

"@
        return
    }

    # ── 5. systemd inside the distro ────────────────────────────────────────────────────────────────────────────
    $pid1 = Read-InDistro 'ps -p 1 -o comm= 2>/dev/null'
    if ($pid1 -eq 'systemd') {
        Ok 'systemd is running inside WSL'
    } else {
        Say 'Turning on systemd inside WSL (astryx runs its services and its one-minute pulse as systemd units).'
        # Edit /etc/wsl.conf in place, keeping whatever else is there ([user] default=..., [network], ...).
        $conf = @'
set -e
f=/etc/wsl.conf
touch "$f"
if grep -q '^[[:space:]]*systemd[[:space:]]*=' "$f"; then
  sed -i 's/^[[:space:]]*systemd[[:space:]]*=.*/systemd=true/' "$f"
elif grep -q '^\[boot\]' "$f"; then
  sed -i '/^\[boot\]/a systemd=true' "$f"
else
  printf '\n[boot]\nsystemd=true\n' >> "$f"
fi
echo "/etc/wsl.conf is now:"; cat "$f"
'@
        $rc = Invoke-InDistro $conf 'root'
        if ($rc -ne 0) { Bad "couldn't write /etc/wsl.conf inside $Distro (exit $rc)."; return }
        Say 'Restarting WSL so systemd starts.'
        [void](Invoke-Wsl @('--shutdown'))
        if (-not $Dry) {
            Start-Sleep -Seconds 3
            $pid1 = Read-InDistro 'ps -p 1 -o comm= 2>/dev/null'
            if ($pid1 -ne 'systemd') {
                Bad "systemd still isn't PID 1 inside $Distro (got '$pid1'). Your WSL may be too old: run 'wsl --update', then run this again."
                return
            }
            Ok 'systemd is running inside WSL'
        }
    }

    # ── 6. Docker ───────────────────────────────────────────────────────────────────────────────────────────────
    $desktopExe = Join-Path $env:ProgramFiles 'Docker\Docker\Docker Desktop.exe'
    $hasDesktop = Test-Path $desktopExe
    $dockerOs = Read-InDistro "docker info --format '{{.OperatingSystem}}' 2>/dev/null"
    if ($dockerOs -like '*Docker Desktop*') {
        Ok 'docker: Docker Desktop, with WSL integration serving this distro. That works.'
        Warn 'Docker Desktop must be running for the org to reach its database. docker-ce inside WSL removes that dependency.'
    } elseif ($dockerOs) {
        Ok "docker: docker-ce inside WSL ($dockerOs). This is the recommended setup."
    } elseif ($hasDesktop) {
        Warn 'Docker Desktop is installed but not serving this distro. Either turn on'
        Warn "Docker Desktop > Settings > Resources > WSL integration > $Distro, or (recommended) let install.sh put docker-ce inside WSL."
    } else {
        Say 'Docker: install.sh will offer docker-ce inside WSL (recommended).'
    }
    Write-Host @'
  Why docker-ce inside WSL: one docker daemon in the same Linux as the org, started by systemd along
  with everything else. Nothing on the Windows side has to be running, and containers reach the org
  on docker0 (172.17.0.1) exactly as on a Linux server. Docker Desktop also works if you prefer it.

'@

    # ── 7. the Linux installer, inside WSL ──────────────────────────────────────────────────────────────────────
    Say "Running the Linux installer inside $Distro."
    $inner = "curl -fsSL $Base/install.sh | bash"
    if ($Dry) { $inner = "curl -fsSL $Base/install.sh | bash -s -- --dry-run" }
    Show "wsl -d $Distro --cd ~ -- bash -lc '$inner'"
    if (-not $Dry) {
        # Called directly, not through Invoke-Wsl, so its prompts reach this console.
        & wsl.exe -d $Distro --cd '~' -- bash -lc (Get-B64Cmd $inner 'bash')
        if ($LASTEXITCODE -ne 0) {
            Bad "the installer inside WSL stopped (exit $LASTEXITCODE). Open $Distro and run:  $inner"
            return
        }
    }
    Say "Done. Open $Distro from the Start menu any time; inside it, 'astryx doctor' (or ~/astryx/init.sh doctor) checks everything."
    Warn 'Remember: when Windows sleeps, the org sleeps.'
}

Install-Astryx
