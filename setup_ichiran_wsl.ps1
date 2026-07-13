<#
.SYNOPSIS
    Provision a native (no-Docker) offline Ichiran install inside WSL for the
    Daisho OCR app / japReader offline parser.

.DESCRIPTION
    Installs SBCL + PostgreSQL natively in the target WSL distro, downloads and
    restores Ichiran's dictionary database dump, builds the ichiran-cli binary,
    and installs the WSL wrapper scripts. Replaces the previous Docker-based
    setup, whose daemon frequently failed to start.

    Safe to re-run: each step is idempotent. Use -ResetDatabase to drop and
    re-restore the dictionary database, or -DumpPath to install from a local
    .pgdump instead of downloading the latest release.

.PARAMETER Distro
    WSL distro name (default: Ubuntu).

.PARAMETER DumpPath
    Optional Windows path to a local ichiran .pgdump file. When omitted, the
    latest release dump is downloaded automatically from GitHub.

.PARAMETER ResetDatabase
    Drop and recreate the jmdict database before restoring.
#>
param(
    [string]$Distro = "Ubuntu",
    [string]$DumpPath = "",
    [switch]$ResetDatabase
)

$ErrorActionPreference = "Stop"
$OutputEncoding = New-Object System.Text.UTF8Encoding $false
$projectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path

# ---------------------------------------------------------------------------
# WSL helpers: write the bash script to a UTF-8 (no BOM, LF) temp file and run
# `bash <file>`. Piping a string to wsl.exe stdin is unreliable on Windows
# PowerShell (it injects a BOM and CRLF, which bash chokes on). Values from
# PowerShell are injected as a small assignment header so bash bodies can stay
# literal (single-quoted).
# ---------------------------------------------------------------------------
$script:Utf8NoBom = New-Object System.Text.UTF8Encoding $false

function ConvertTo-WslPath {
    param([string]$WinPath)
    $full = [System.IO.Path]::GetFullPath($WinPath)
    $drive = $full.Substring(0, 1).ToLower()
    $rest = $full.Substring(2) -replace '\\', '/'
    return "/mnt/$drive$rest"
}

function Invoke-WslScriptFile {
    param([string]$Script, [switch]$Capture, [switch]$Root)
    $unix = ($Script -replace "`r`n", "`n") -replace "`r", "`n"
    $tmp = [System.IO.Path]::GetTempFileName()
    try {
        [System.IO.File]::WriteAllText($tmp, $unix, $script:Utf8NoBom)
        $wslPath = ConvertTo-WslPath $tmp
        $prefix = @("-d", $Distro)
        if ($Root) { $prefix += @("-u", "root") }
        if ($Capture) {
            $out = (& wsl.exe @prefix -- bash "$wslPath" | Out-String)
            if ($LASTEXITCODE -ne 0) { throw "WSL step failed with exit code $LASTEXITCODE" }
            return $out.Trim()
        }
        & wsl.exe @prefix -- bash "$wslPath"
        if ($LASTEXITCODE -ne 0) { throw "WSL step failed with exit code $LASTEXITCODE" }
    }
    finally {
        Remove-Item $tmp -ErrorAction SilentlyContinue
    }
}

function Invoke-WslBash {
    param(
        [Parameter(Mandatory = $true)][string]$Script,
        [switch]$Root
    )
    if ($Root) { Invoke-WslScriptFile -Script $Script -Root }
    else { Invoke-WslScriptFile -Script $Script }
}

function Get-WslText {
    param([Parameter(Mandatory = $true)][string]$Script)
    Invoke-WslScriptFile -Script $Script -Capture
}

Write-Host "== Native Ichiran setup for WSL distro '$Distro' =="

$wslUser = Get-WslText -Script 'whoami'
if (-not $wslUser) { throw "Could not determine the default WSL user" }

# ---------------------------------------------------------------------------
# 1. System packages + Japanese locale
# ---------------------------------------------------------------------------
Write-Host "[1/8] Installing system packages (sbcl, postgresql, build tools)..."
Invoke-WslBash -Root -Script @'
set -eu
export DEBIAN_FRONTEND=noninteractive
apt-get update
apt-get install -y \
    sbcl wget curl git rlwrap build-essential ca-certificates \
    postgresql postgresql-client locales
# Japanese UTF-8 locale is required by createdb -l ja_JP.utf8.
sed -i "s/^# *ja_JP.UTF-8 UTF-8/ja_JP.UTF-8 UTF-8/" /etc/locale.gen || true
grep -q "^ja_JP.UTF-8 UTF-8" /etc/locale.gen || echo "ja_JP.UTF-8 UTF-8" >> /etc/locale.gen
locale-gen
'@

# ---------------------------------------------------------------------------
# 2. Install the WSL wrapper scripts into /usr/local/bin
# ---------------------------------------------------------------------------
Write-Host "[2/8] Installing Ichiran wrapper scripts..."
$scriptsWin = Join-Path $projectRoot "scripts"
$scriptsUnix = ConvertTo-WslPath $scriptsWin
if (-not $scriptsUnix) { throw "Could not resolve project scripts path inside WSL" }
$header = "SRC_DIR='$scriptsUnix'`n"
Invoke-WslBash -Root -Script ($header + @'
set -eu
for f in ichiran-common.sh ichiran-cli-wsl ichiran-service-wsl; do
    tmp="$(mktemp)"
    # Strip any CRLF that may have crept in from a Windows checkout.
    sed 's/\r$//' "$SRC_DIR/$f" > "$tmp"
    install -m 755 "$tmp" "/usr/local/bin/$f"
    rm -f "$tmp"
done
'@)

# ---------------------------------------------------------------------------
# 3. PostgreSQL: start, trust loopback, and allow the wrappers to start it
#    without a sudo password at runtime.
# ---------------------------------------------------------------------------
Write-Host "[3/8] Configuring PostgreSQL (loopback trust + passwordless service control)..."
$header = "SVC_USER='$wslUser'`n"
Invoke-WslBash -Root -Script ($header + @'
set -eu
service postgresql start || true
count=0
until pg_isready -q; do
    count=$((count + 1))
    [ "$count" -ge 30 ] && { echo "PostgreSQL did not become ready" >&2; exit 1; }
    sleep 1
done
# ichiran connects over localhost TCP as the postgres role using this password
# (must match settings.lisp). Setting the password is more robust than editing
# pg_hba trust rules, which the default scram-sha-256 loopback line overrides.
runuser -u postgres -- psql -c "ALTER USER postgres PASSWORD 'ichiran'" >/dev/null
# Let the runtime wrappers (running as $SVC_USER) start Postgres without a
# password prompt, which would otherwise hang the OCR app.
cat > /etc/sudoers.d/ichiran-postgres <<SUDOERS
$SVC_USER ALL=(root) NOPASSWD: /usr/sbin/service postgresql *, /usr/bin/systemctl * postgresql*, /usr/bin/pg_ctlcluster *
SUDOERS
chmod 440 /etc/sudoers.d/ichiran-postgres
'@)

# ---------------------------------------------------------------------------
# 4. Create / reset the jmdict database and restore the dump
# ---------------------------------------------------------------------------
$dbExists = Get-WslText -Script @'
export PGCONNECT_TIMEOUT=5
# Only connect to jmdict if it actually exists, so a missing DB never blocks.
exists=$(runuser -u postgres -- psql -tAc "SELECT 1 FROM pg_database WHERE datname='jmdict'" 2>/dev/null || true)
if [ "$exists" = "1" ]; then
  runuser -u postgres -- psql -tAqc "SELECT to_regclass('public.entry')" jmdict 2>/dev/null || true
fi
'@
$needRestore = $ResetDatabase -or ($dbExists -notmatch "entry")

if (-not $needRestore) {
    Write-Host "[4/8] jmdict database already populated; skipping restore (use -ResetDatabase to force)."
} else {
    Write-Host "[4/8] Preparing jmdict database..."
    $resetFlag = if ($ResetDatabase) { "1" } else { "0" }
    $header = "RESET_DB='$resetFlag'`n"
    Invoke-WslBash -Root -Script ($header + @'
set -eu
if [ "$RESET_DB" = "1" ]; then
    runuser -u postgres -- dropdb --if-exists jmdict
fi
if ! runuser -u postgres -- psql -tAqc "SELECT 1" jmdict >/dev/null 2>&1; then
    runuser -u postgres -- createdb -E UTF8 -l ja_JP.utf8 -T template0 jmdict
fi
'@)

    if ($DumpPath) {
        if (-not (Test-Path $DumpPath)) { throw "DumpPath not found: $DumpPath" }
        Write-Host "      Using local dump: $DumpPath"
        $dumpUnix = ConvertTo-WslPath $DumpPath
        $header = "DUMP_SRC='$dumpUnix'`n"
        Invoke-WslBash -Root -Script ($header + @'
set -eu
dest="/var/lib/postgresql/ichiran-import.pgdump"
cp "$DUMP_SRC" "$dest"
chown postgres:postgres "$dest"
# The dump recreates the public schema; drop the default one so restore is clean.
runuser -u postgres -- psql -d jmdict -c "DROP SCHEMA IF EXISTS public CASCADE" >/dev/null 2>&1 || true
# pg_restore can exit non-zero on benign object-exists notices; verify by row count.
runuser -u postgres -- pg_restore -d jmdict "$dest" --no-owner --no-privileges || true
rm -f "$dest"
cnt=$(runuser -u postgres -- psql -tAqc "SELECT count(*) FROM entry" jmdict 2>/dev/null || echo 0)
[ "${cnt:-0}" -ge 1000 ] || { echo "Ichiran DB restore failed: entry rows=${cnt:-0}" >&2; exit 1; }
echo "Restored jmdict (entry rows=$cnt)"
'@)
    } else {
        Write-Host "      Resolving latest Ichiran release dump..."
        $rel = Invoke-RestMethod -Uri "https://api.github.com/repos/tshatrov/ichiran/releases/latest" `
            -Headers @{ "User-Agent" = "daisho-ichiran-setup" }
        $asset = $rel.assets | Where-Object { $_.name -like "*.pgdump" } | Select-Object -First 1
        if (-not $asset) { throw "No .pgdump asset found on the latest Ichiran release" }
        Write-Host ("      Downloading {0} ({1:N0} bytes)..." -f $asset.name, $asset.size)
        $header = "DUMP_URL='$($asset.browser_download_url)'`nDUMP_NAME='$($asset.name)'`n"
        Invoke-WslBash -Root -Script ($header + @'
set -eu
dest="/var/lib/postgresql/$DUMP_NAME"
wget -c -O "$dest" "$DUMP_URL"
chown postgres:postgres "$dest"
# The dump recreates the public schema; drop the default one so restore is clean.
runuser -u postgres -- psql -d jmdict -c "DROP SCHEMA IF EXISTS public CASCADE" >/dev/null 2>&1 || true
# pg_restore can exit non-zero on benign object-exists notices; verify by row count.
runuser -u postgres -- pg_restore -d jmdict "$dest" --no-owner --no-privileges || true
cnt=$(runuser -u postgres -- psql -tAqc "SELECT count(*) FROM entry" jmdict 2>/dev/null || echo 0)
[ "${cnt:-0}" -ge 1000 ] || { echo "Ichiran DB restore failed: entry rows=${cnt:-0}" >&2; exit 1; }
echo "Restored jmdict (entry rows=$cnt)"
'@)
    }
}

# ---------------------------------------------------------------------------
# 5. Quicklisp (per WSL user)
# ---------------------------------------------------------------------------
Write-Host "[5/8] Ensuring Quicklisp is installed..."
Invoke-WslBash -Script @'
set -eu
if [ ! -d "$HOME/quicklisp" ]; then
    tmp="$(mktemp -d)"
    wget -qO "$tmp/quicklisp.lisp" https://beta.quicklisp.org/quicklisp.lisp
    sbcl --non-interactive \
        --load "$tmp/quicklisp.lisp" \
        --eval "(quicklisp-quickstart:install)" \
        --eval "(ql-util:without-prompting (ql:add-to-init-file))"
    rm -rf "$tmp"
fi
'@

# ---------------------------------------------------------------------------
# 6. Clone / update Ichiran + jmdictdb (jmdictdb supplies the runtime data CSVs
#    such as conj.csv that ichiran reads for conjugation).
# ---------------------------------------------------------------------------
Write-Host "[6/8] Cloning or updating Ichiran + jmdictdb source..."
Invoke-WslBash -Script @'
set -eu
dir="$HOME/quicklisp/local-projects/ichiran"
mkdir -p "$HOME/quicklisp/local-projects"
if [ -d "$dir/.git" ]; then
    git -C "$dir" pull --ff-only
else
    git clone https://github.com/tshatrov/ichiran.git "$dir"
fi
jm="$HOME/jmdictdb"
if [ -d "$jm/.git" ]; then
    git -C "$jm" pull --ff-only || true
else
    git clone --depth 1 https://gitlab.com/yamagoya/jmdictdb.git "$jm"
fi
test -f "$jm/jmdictdb/data/conj.csv" || { echo "jmdictdb data (conj.csv) missing" >&2; exit 1; }
'@

# ---------------------------------------------------------------------------
# 7. settings.lisp (loopback / trust connection)
# ---------------------------------------------------------------------------
Write-Host "[7/8] Writing settings.lisp..."
Invoke-WslBash -Script @'
set -eu
dir="$HOME/quicklisp/local-projects/ichiran"
data="$HOME/jmdictdb/jmdictdb/data/"
# Unquoted heredoc so $data expands; the Lisp body contains no other $ tokens.
# *jmdict-data* MUST point at real conj.csv/… (runtime conjugation); *jmdict-path*
# and *kanjidic-path* stay placeholders (build-time full-init only, unused here).
cat > "$dir/settings.lisp" <<LISP
(in-package #:ichiran/conn)

(defparameter *connection* '("jmdict" "postgres" "ichiran" "localhost"))

(defparameter *connections* '((:old "jmdict_old" "postgres" "ichiran" "localhost")
                              (:test "jmdict_test" "postgres" "ichiran" "localhost")))

(in-package #:ichiran/dict)

(defparameter *jmdict-path* #p"/home/you/dump/JMdict_e")

(defparameter *jmdict-data* #p"$data")

(in-package #:ichiran/kanji)

(defparameter *kanjidic-path* #P"/home/you/dump/kanjidic2.xml")
LISP
'@

# ---------------------------------------------------------------------------
# 8. Build ichiran-cli and install to /usr/local/bin
# ---------------------------------------------------------------------------
Write-Host "[8/8] Building ichiran-cli (this can take a few minutes)..."
Invoke-WslBash -Script @'
set -eu
dir="$HOME/quicklisp/local-projects/ichiran"
cd "$dir"
# Force a genuine rebuild: (ichiran/cli:build) ends in (asdf:make :ichiran/cli),
# which treats the program as up-to-date when only settings.lisp changed (it is
# not a tracked source component) and would keep a stale *jmdict-data* baked in.
# Removing the old binary and the fasl cache guarantees the current settings.lisp
# is compiled in.
rm -f "$dir/ichiran-cli"
rm -rf "$HOME/.cache/common-lisp"
sbcl --non-interactive \
    --eval "(ql:quickload :ichiran/cli)" \
    --eval "(ichiran/cli:build)"
test -x "$dir/ichiran-cli"
'@

$cliPath = Get-WslText -Script 'echo "$HOME/quicklisp/local-projects/ichiran/ichiran-cli"'
$header = "CLI_PATH='$cliPath'`n"
Invoke-WslBash -Root -Script ($header + @'
set -eu
ln -sf "$CLI_PATH" /usr/local/bin/ichiran-cli
'@)

# ---------------------------------------------------------------------------
# Verify
# ---------------------------------------------------------------------------
Write-Host "Verifying Ichiran (parsing a conjugated word)..."
# UTF-8 octal bytes for 食べたい (a conjugation that exercises the jmdictdb data
# CSVs), so this file stays pure ASCII and the check catches a missing/placeholder
# *jmdict-data* path.
Invoke-WslBash -Script @'
set -eu
out="$(printf '\351\243\237\343\201\271\343\201\237\343\201\204' | /usr/local/bin/ichiran-cli-wsl -f -l 1 2>&1)"
printf '%s\n' "$out" | head -c 200
echo
case "$out" in
    *DOES-NOT-EXIST*|*Unhandled*) echo "Ichiran runtime error (check *jmdict-data* / jmdictdb)" >&2; exit 1 ;;
    \[*|\{*) echo "Ichiran OK (conjugation resolved)." ;;
    *) echo "Ichiran returned unexpected output" >&2; exit 1 ;;
esac
'@

Write-Host ""
Write-Host "Native Ichiran is ready (no Docker)."
Write-Host "  CLI command:     wsl.exe -d $Distro -- /usr/local/bin/ichiran-cli-wsl"
Write-Host "  Service command: wsl.exe -d $Distro -- /usr/local/bin/ichiran-service-wsl"
