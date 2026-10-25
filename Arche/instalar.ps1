# Instalador de Arche para Windows.
# Uso (en PowerShell):
#   irm https://raw.githubusercontent.com/danifon446-crypto/Arch-IA/main/instalar.ps1 | iex

$ErrorActionPreference = "Continue"
$Repo = "https://github.com/danifon446-crypto/Arch-IA.git"
$Destino = Join-Path $env:USERPROFILE "Arch-IA"

function Paso($texto) { Write-Host ""; Write-Host "> $texto" -ForegroundColor Cyan }
function Fallo($texto) { Write-Host ""; Write-Host "ERROR: $texto" -ForegroundColor Red; Read-Host "Pulsa Enter para cerrar"; exit 1 }
function Tiene($cmd) { return [bool](Get-Command $cmd -ErrorAction SilentlyContinue) }
function Refrescar-Path {
    $m = [Environment]::GetEnvironmentVariable("Path", "Machine")
    $u = [Environment]::GetEnvironmentVariable("Path", "User")
    $env:Path = "$m;$u"
}
function Instalar-Con-Winget($id, $nombre) {
    if (-not (Tiene "winget")) {
        Fallo "No encuentro winget, necesario para instalar $nombre. Actualiza Windows o instala $nombre a mano y vuelve a correr este comando."
    }
    Write-Host "Instalando $nombre ..."
    winget install -e --id $id --silent --accept-package-agreements --accept-source-agreements
    Refrescar-Path
}
function Buscar-Python {
    # Devuelve la ruta de un Python 3.10+ real (ignora el atajo de la Microsoft Store).
    foreach ($intento in @(@("py", "-3.12"), @("py", "-3"), @("python"))) {
        if (-not (Tiene $intento[0])) { continue }
        $extra = @()
        if ($intento.Count -gt 1) { $extra = $intento[1..($intento.Count - 1)] }
        $ruta = & $intento[0] @extra -c "import sys; print(sys.executable if sys.version_info >= (3,10) else '')" 2>$null
        if ($LASTEXITCODE -eq 0 -and $ruta -and (Test-Path $ruta)) { return $ruta.Trim() }
    }
    return $null
}

Write-Host "Instalador de Arche" -ForegroundColor Green

Paso "Revisando Python"
$python = Buscar-Python
if (-not $python) {
    Instalar-Con-Winget "Python.Python.3.12" "Python 3.12"
    $python = Buscar-Python
    if (-not $python) { Fallo "Instale Python pero no lo encuentro. Cierra esta ventana, abre otra y corre el comando de nuevo." }
}
Write-Host "Python: $python"

Paso "Revisando Git"
if (-not (Tiene "git")) {
    Instalar-Con-Winget "Git.Git" "Git"
    if (-not (Tiene "git")) { Fallo "Instale Git pero no lo encuentro. Cierra esta ventana, abre otra y corre el comando de nuevo." }
}

Paso "Descargando Arche en $Destino"
if (Test-Path (Join-Path $Destino ".git")) {
    git -C $Destino pull
    if ($LASTEXITCODE -ne 0) { Fallo "No pude actualizar la carpeta existente. Revisa tu conexion o los cambios locales." }
} else {
    git clone $Repo $Destino
    if ($LASTEXITCODE -ne 0) { Fallo "No pude descargar el repositorio. Si es privado, pide que te den acceso en GitHub e inicia sesion con git." }
}

$Arche = Join-Path $Destino "Arche"
if (-not (Test-Path (Join-Path $Arche "main.py"))) { Fallo "No encuentro Arche\main.py dentro de $Destino." }

Paso "Creando entorno de Python (solo para Arche)"
$venv = Join-Path $Destino ".venv"
if (-not (Test-Path (Join-Path $venv "Scripts\python.exe"))) {
    & $python -m venv $venv
    if ($LASTEXITCODE -ne 0) { Fallo "No pude crear el entorno de Python." }
}
$py = Join-Path $venv "Scripts\python.exe"

Paso "Instalando dependencias (puede tardar varios minutos)"
& $py -m pip install --upgrade pip
$req = $null
foreach ($candidato in @((Join-Path $Arche "requirements.txt"), (Join-Path $Destino "requirements.txt"))) {
    if (Test-Path $candidato) { $req = $candidato; break }
}
if ($req) {
    & $py -m pip install -r $req
    if ($LASTEXITCODE -ne 0) { Fallo "Fallo la instalacion de dependencias. Copia el mensaje de arriba y envialo para revisarlo." }
} else {
    Write-Host "No encontre requirements.txt; sigo sin instalar dependencias." -ForegroundColor Yellow
}

Paso "Conectando la red de aprendizaje"
$parche = Join-Path $Arche "aplicar_parche_red.py"
$main = Join-Path $Arche "main.py"
if ((Test-Path $parche) -and -not (Select-String -Path $main -Pattern "compartir" -Quiet)) {
    Push-Location $Arche
    & $py "aplicar_parche_red.py"
    Pop-Location
} else {
    Write-Host "La red de aprendizaje ya esta incluida."
}

Paso "Cerebro local (opcional)"
$resp = Read-Host "Quieres instalar Ollama para usar Arche sin internet? (s/n)"
if ($resp -match "^[sSyY]") {
    if (-not (Tiene "ollama")) { Instalar-Con-Winget "Ollama.Ollama" "Ollama" }
    else { Write-Host "Ollama ya esta instalado." }
}

Paso "Creando acceso directo"
$bat = Join-Path $Destino "Arche.bat"
$lineas = @(
    "@echo off",
    "cd /d `"$Arche`"",
    "`"$py`" main.py",
    "pause"
)
Set-Content -Path $bat -Value $lineas -Encoding ASCII
try {
    $escritorio = [Environment]::GetFolderPath("Desktop")
    $shell = New-Object -ComObject WScript.Shell
    $atajo = $shell.CreateShortcut((Join-Path $escritorio "Arche.lnk"))
    $atajo.TargetPath = $bat
    $atajo.WorkingDirectory = $Arche
    $atajo.Save()
    Write-Host "Acceso directo creado en el escritorio."
} catch {
    Write-Host "No pude crear el acceso directo; abre $bat para iniciar Arche." -ForegroundColor Yellow
}

Write-Host ""
Write-Host "Listo. Arche quedo instalado en $Destino" -ForegroundColor Green
Write-Host "Para empezar: abre 'Arche' en el escritorio."
Write-Host "Para unirte a la red de aprendizaje, dile a Arche: unirme a la red ARCHE-... (con el codigo que te dieron)."
Read-Host "Pulsa Enter para cerrar"