"""
medios.py
---------
Ubicacion: Arche/core/medios.py

"pon <algo> en spotify | youtube": que SUENE, no solo que se busque, y sin abrir
una pestaña nueva cada vez.

  * Si ya hay una ventana del navegador con Spotify / YouTube al frente (o con
    algo sonando: Spotify pone "Cancion • Artista" de titulo), la reutiliza:
    la trae al frente, escribe la direccion en esa pestaña y listo.
  * YouTube: busca el primer video (DuckDuckGo) y abre ESE; los videos
    arrancan solos.
  * Spotify: abre la busqueda y le da "play" al primer resultado, buscando el
    boton por su nombre accesible (UI Automation de Windows, sin coordenadas
    de pantalla ni clics a ciegas). Si no lo logra, deja la busqueda abierta y lo dice.

Limites honestos: solo ve la pestaña ACTIVA de cada ventana (si Spotify esta en
una pestaña de fondo, abre otra); y el boton de play depende de como arme
Spotify su pagina, asi que si cambia su diseño puede dejar de encontrarlo.

Lo que toca el sistema esta en funciones "_" para poder probarlo sin Windows.
"""

import os
import re
import threading
import time

from core import control_pc

SITIOS = {
    # nombre, como se reconoce la ventana, si un titulo "A • B" cuenta (Spotify lo usa mientras suena)
    "spotify": {"nombre": "Spotify", "titulo": re.compile(r"spotify|^.{2,}\s•\s.{2,}$", re.I)},
    "youtube": {"nombre": "YouTube", "titulo": re.compile(r"youtube", re.I)},
}
EXES_NAVEGADOR = {"chrome.exe", "msedge.exe", "firefox.exe", "brave.exe", "opera.exe", "vivaldi.exe",
                  "opera_gx.exe", "launcher.exe"}
ESPERA_CARGA = 4.0         # segundos de margen para que cargue la pagina antes de buscar el boton
_ULTIMOS_BOTONES = ""      # nombres de botones vistos en el ultimo intento fallido (diagnostico)
ESPERA_BOTON = 15.0        # cuanto insiste buscando el boton de play


def _msg(texto):
    print(f"Arché: {texto}")


# ------------------------------------------------------------------
# Reutilizar la ventana que ya esta abierta
# ------------------------------------------------------------------

def _ventanas():
    from core import acciones_pc
    return acciones_pc._ventanas_visibles()


def ventana_del_sitio(sitio):
    """La ventana de navegador (la de mas arriba) cuya pestaña activa es de ese sitio, o None."""
    cfg = SITIOS.get(sitio)
    if not cfg or not control_pc.ES_WINDOWS:
        return None
    for v in _ventanas():
        if v.get("exe") in EXES_NAVEGADOR and cfg["titulo"].search(v.get("titulo", "")):
            return v
    return None


def _escribir_en_ventana(hwnd, url):
    """Trae la ventana al frente y navega en su pestaña activa."""
    from core import acciones_pc
    if not acciones_pc._enfocar(hwnd):
        return False
    acciones_pc._tecla(["ctrl", "l"])
    time.sleep(0.2)
    acciones_pc._escribir_texto(url)
    time.sleep(0.1)
    acciones_pc._tecla(["enter"])
    return True


def abrir_reutilizando(sitio, url):
    """Abre `url`: en la ventana de ese sitio si ya hay una, y si no, como siempre (preguntando navegador).
    Devuelve (abierto, hwnd_o_None)."""
    v = ventana_del_sitio(sitio)
    if v is not None:
        try:
            if _escribir_en_ventana(v["hwnd"], url):
                return True, v["hwnd"]
        except Exception:
            pass
    return control_pc.abrir_url(url), None


# ------------------------------------------------------------------
# YouTube: ir directo al primer video
# ------------------------------------------------------------------

_RE_VIDEO = re.compile(r"^https?://(?:www\.|m\.)?youtube\.com/watch\?v=[\w-]{11}")


def _buscar_web(consulta, maximo=6):
    try:
        from ddgs import DDGS
        with DDGS() as d:
            return list(d.text(consulta, max_results=maximo))
    except Exception:
        return []


def primer_video(consulta):
    """URL del primer video de YouTube que sale para `consulta`, o None."""
    for r in _buscar_web(f"{consulta} site:youtube.com/watch"):
        url = (r.get("href") or r.get("url") or "").split("&")[0]
        if _RE_VIDEO.match(url):
            return url
    return None


# ------------------------------------------------------------------
# Spotify: darle play al primer resultado (UI Automation)
# ------------------------------------------------------------------

def _script_play(hwnd):
    """PowerShell que busca en la ventana `hwnd` el boton de play del resultado.
    1) un boton llamado 'Play <algo>' / 'Reproducir <algo>' (con titulo: no el de la barra de abajo);
    2) si no, uno llamado solo 'Play'/'Reproducir' que NO este en la barra inferior (el verde grande);
    Lo pulsa con InvokePattern y, si la pagina no lo deja, con un clic real en su centro.
    Si no encuentra nada responde 'NO:' + los nombres de botones que si ve (para diagnosticar)."""
    return f"""
Add-Type -AssemblyName UIAutomationClient
Add-Type -AssemblyName UIAutomationTypes
Add-Type @"
using System; using System.Runtime.InteropServices;
public class ArcheClic {{
  [DllImport("user32.dll")] public static extern bool SetCursorPos(int x, int y);
  [DllImport("user32.dll")] public static extern void mouse_event(uint f, uint x, uint y, uint d, UIntPtr e);
  [DllImport("user32.dll")] public static extern bool SetProcessDPIAware();
}}
"@
Add-Type -ReferencedAssemblies System.Drawing @"
using System; using System.Collections.Generic; using System.Drawing;
public class ArcheVerde {{
  static bool V(Color c) {{ return c.G > 190 && c.R < 80 && c.B < 140 && c.G - c.R > 120; }}
  // Devuelve "x,y" (pantalla) del circulo verde mas alto de la ventana, o "" si no hay.
  public static string Buscar(int x0, int y0, int w, int h) {{
    const int C = 6;
    using (Bitmap bmp = new Bitmap(w, h)) {{
      using (Graphics g = Graphics.FromImage(bmp)) {{ g.CopyFromScreen(x0, y0, 0, 0, new Size(w, h)); }}
      int cols = w / C, rows = h / C;
      bool[,] d = new bool[cols, rows];
      for (int cy = 0; cy < rows; cy++) for (int cx = 0; cx < cols; cx++) {{
        int n = 0;
        for (int a = 1; a < C; a += 2) for (int b = 1; b < C; b += 2) if (V(bmp.GetPixel(cx * C + b, cy * C + a))) n++;
        d[cx, cy] = n >= 8;
      }}
      bool[,] vis = new bool[cols, rows];
      int mejorY = int.MaxValue; string res = "";
      for (int cy = 0; cy < rows; cy++) for (int cx = 0; cx < cols; cx++) {{
        if (!d[cx, cy] || vis[cx, cy]) continue;
        Stack<int[]> st = new Stack<int[]>(); st.Push(new int[] {{cx, cy}}); vis[cx, cy] = true;
        int n2 = 0, minx = cx, maxx = cx, miny = cy, maxy = cy;
        while (st.Count > 0) {{
          int[] p = st.Pop(); n2++;
          minx = Math.Min(minx, p[0]); maxx = Math.Max(maxx, p[0]); miny = Math.Min(miny, p[1]); maxy = Math.Max(maxy, p[1]);
          int[][] vec = new int[][] {{ new int[] {{1,0}}, new int[] {{-1,0}}, new int[] {{0,1}}, new int[] {{0,-1}} }};
          foreach (int[] v in vec) {{
            int nx = p[0] + v[0], ny = p[1] + v[1];
            if (nx >= 0 && ny >= 0 && nx < cols && ny < rows && d[nx, ny] && !vis[nx, ny]) {{ vis[nx, ny] = true; st.Push(new int[] {{nx, ny}}); }}
          }}
        }}
        int bw = maxx - minx + 1, bh = maxy - miny + 1;
        double asp = (double)bw / bh;
        int topPx = miny * C;
        bool zonaOk = topPx > 90 && (maxy + 1) * C < h - 130;   // fuera de la barra de arriba y de la de abajo
        if (n2 >= 18 && bw * C >= 28 && asp > 0.7 && asp < 1.4 && zonaOk && topPx < mejorY) {{
          mejorY = topPx;
          res = (x0 + (minx + maxx + 1) * C / 2) + "," + (y0 + (miny + maxy + 1) * C / 2);
        }}
      }}
      return res;
    }}
  }}
}}
"@
[ArcheClic]::SetProcessDPIAware() | Out-Null
$raiz = [System.Windows.Automation.AutomationElement]::FromHandle([IntPtr]{int(hwnd)})
$ventana = $raiz.Current.BoundingRectangle
$boton = [System.Windows.Automation.ControlType]::Button
$cond = New-Object System.Windows.Automation.PropertyCondition([System.Windows.Automation.AutomationElement]::ControlTypeProperty, $boton)
$todos = $raiz.FindAll([System.Windows.Automation.TreeScope]::Descendants, $cond)
function Pulsar($b, $n) {{
  $p = $null
  try {{
    if ($b.TryGetCurrentPattern([System.Windows.Automation.InvokePattern]::Pattern, [ref]$p)) {{ $p.Invoke(); Write-Output "OK:$n"; exit 0 }}
  }} catch {{}}
  $r = $b.Current.BoundingRectangle
  if ($r.Width -gt 0 -and $r.Height -gt 0) {{
    $cx = [int]($r.X + $r.Width/2); $cy = [int]($r.Y + $r.Height/2)
    [ArcheClic]::SetCursorPos($cx - 6, $cy - 6) | Out-Null; Start-Sleep -Milliseconds 150
    [ArcheClic]::SetCursorPos($cx, $cy) | Out-Null; Start-Sleep -Milliseconds 350
    [ArcheClic]::mouse_event(2,0,0,0,[UIntPtr]::Zero); [ArcheClic]::mouse_event(4,0,0,0,[UIntPtr]::Zero)
    Write-Output "OK:$n"; exit 0
  }}
}}
$nombres = @()
foreach ($b in $todos) {{
  $n = $b.Current.Name
  if ($n) {{ $nombres += $n }}
  if ($n -match '^(Play|Reproducir)\\s+\\S') {{ Pulsar $b $n }}
}}
foreach ($b in $todos) {{
  $n = $b.Current.Name
  $r = $b.Current.BoundingRectangle
  $enBarra = ($r.Y -gt ($ventana.Y + $ventana.Height - 140))
  if ($n -match '^(Play|Reproducir|Reproducir canci.n)$' -and -not $enBarra -and $r.Y -gt ($ventana.Y + 100)) {{ Pulsar $b $n }}
}}
$pos = [ArcheVerde]::Buscar([int]$ventana.X, [int]$ventana.Y, [int]$ventana.Width, [int]$ventana.Height)
if ($pos) {{
  $xy = $pos.Split(",")
  [ArcheClic]::SetCursorPos([int]$xy[0] - 6, [int]$xy[1] - 6) | Out-Null; Start-Sleep -Milliseconds 150
  [ArcheClic]::SetCursorPos([int]$xy[0], [int]$xy[1]) | Out-Null; Start-Sleep -Milliseconds 350
  [ArcheClic]::mouse_event(2,0,0,0,[UIntPtr]::Zero); [ArcheClic]::mouse_event(4,0,0,0,[UIntPtr]::Zero)
  Write-Output "OK:el boton verde de play"; exit 0
}}
Write-Output ("NO:" + (($nombres | Select-Object -Unique | Select-Object -First 12) -join " | "))
"""


def _ejecutar_script(script, espera=25):
    from core import acciones_pc
    return acciones_pc._powershell(script, espera=espera)


def _ventana_al_frente():
    from core import acciones_pc
    return acciones_pc._u32().GetForegroundWindow()


def pulsar_play(hwnd, espera=ESPERA_BOTON):
    """Insiste hasta `espera` segundos buscando el boton de play. Devuelve el nombre del boton o None."""
    limite = time.time() + espera
    time.sleep(ESPERA_CARGA)
    while True:
        ok, salida = _ejecutar_script(_script_play(hwnd))
        if ok and salida.startswith("OK:"):
            return salida[3:].strip()
        if ok and salida.startswith("NO:"):
            global _ULTIMOS_BOTONES
            _ULTIMOS_BOTONES = salida[3:].strip()
        if time.time() >= limite:
            return None
        time.sleep(1.5)


def _dar_play_en_segundo_plano(hwnd, consulta):
    def trabajo():
        try:
            if hwnd is None:
                time.sleep(1.5)
                hwnd_real = _ventana_al_frente()      # la que se acaba de abrir
            else:
                hwnd_real = hwnd
            nombre = pulsar_play(hwnd_real)
        except Exception:
            nombre = None
        if nombre:
            limpio = re.sub(r"^(?:Play|Reproducir)\s+", "", nombre)
            _msg(f"Sonando: {limpio}.")
        else:
            _msg(f"Te dejé la búsqueda de '{consulta}' abierta, pero no pude darle play sola.")
            if _ULTIMOS_BOTONES:
                _msg(f"(Botones que vi: {_ULTIMOS_BOTONES})")
            else:
                _msg("(No vi ningún botón: el navegador no mostró la página a Windows. Prueba de nuevo en unos segundos.)")

    hilo = threading.Thread(target=trabajo, name="arche-play", daemon=True)
    hilo.start()
    return hilo


# ------------------------------------------------------------------
# Entrada principal
# ------------------------------------------------------------------

def reproducir(sitio, consulta):
    """'pon X en spotify|youtube'. Devuelve True si abrio algo."""
    sitio = control_pc._ALIAS_SITIO.get(control_pc._normalizar(sitio), control_pc._normalizar(sitio))
    consulta = (consulta or "").strip()
    if sitio == "youtube":
        url = primer_video(consulta)
        if url:
            _msg(f"Poniendo '{consulta}'.")
            abierto, _ = abrir_reutilizando("youtube", url)
            return abierto
        _msg(f"No encontré un video directo de '{consulta}'; te abro la búsqueda.")
        abierto, _ = abrir_reutilizando("youtube", control_pc.url_de_busqueda("youtube", consulta))
        return abierto
    if sitio == "spotify":
        _msg(f"Poniendo '{consulta}'.")
        abierto, hwnd = abrir_reutilizando("spotify", control_pc.url_de_busqueda("spotify", consulta))
        if abierto and control_pc.ES_WINDOWS:
            _dar_play_en_segundo_plano(hwnd, consulta)
        return abierto
    return control_pc.buscar_en_sitio(sitio, consulta)