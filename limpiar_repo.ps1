# Deja de versionar archivos que Arché genera solo (sin borrarlos de tu PC).
# Úsalo UNA vez, DESPUÉS de aplicar el parche, desde la carpeta del repo:
#   powershell -ExecutionPolicy Bypass -File .\limpiar_repo.ps1
# Luego:  git commit -m "Dejar de versionar archivos generados"  y  git push
# "git rm --cached" quita el archivo de GitHub pero lo deja en tu carpeta.

$archivos = @(
  "Arche/core/IA/cambios_codigo_log.jsonl",
  "Arche/core/IA/para_revisar.jsonl",
  "Arche/core/IA/errores_aprendidos.json",
  "Arche/core/IA/estudio_estado.json",
  "Arche/core/IA/examen_progreso.json",
  "Arche/core/IA/historial_versiones.json",
  "Arche/core/IA/guia_comandos_vistos.json",
  "Arche/busqueda.txt",
  "Arche/Perro_robotico/robot_config.json"
)
foreach ($a in $archivos) {
  if (git ls-files --error-unmatch $a 2>$null) {
    git rm --cached -q $a
    Write-Host "Ya no se versiona: $a"
  }
}
Write-Host "Listo. Haz commit y push."
