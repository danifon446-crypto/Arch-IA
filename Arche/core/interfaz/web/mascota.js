/* Mascota de Arché para la interfaz nueva: Chispa, Robot o Gato.
   Reacciona a lo que pasa de verdad (habla, piensa, estudia, se cansa, se duerme),
   da consejos con órdenes reales y guía el recorrido por la interfaz.
   Para agregar un consejo: suma una línea a CONSEJOS. Para otro paso del recorrido: a RECORRIDO. */
"use strict";

const M = {
  cv: null, c: null, celebraHasta: 0, saltoTs: -10, parpadeoTs: -1, proxParpadeo: Date.now() + 3000,
  mirar: [0, 0], ultimaActividad: Date.now(), proxConsejo: Date.now() + 40000, globoHasta: 0,
  paso: null, ultConsejo: -1, ultEstado: "", arrastre: null,
};

const CONSEJOS = [
  ["Con Ctrl+K buscas cualquier cosa o me pides lo que quieras.", null],
  ["En Mente › Redes puedes ver mis neuronas y probar cómo entiendo una frase.", ["mente", "redes"]],
  ["¿Muchas cosas a la vez? Ajustes › Lo esencial › Cantidad de información.", ["ajustes"]],
  ["Prueba el modo Programar desde el botón de modo, arriba a la derecha.", null],
  ["El pomodoro sigue contando aunque cambies de sección.", ["hoy", "enfoque"]],
  ["Guarda tus órdenes favoritas como botones en Ajustes › Mis botones.", ["ajustes"]],
  ["Di «recuérdame tomar agua en 30 minutos» y te aviso.", null],
  ["Las rutinas hacen varias cosas con un clic: Equipo › Rutinas.", ["equipo", "rutinas"]],
  ["Puedes cambiar mi forma: esfera, ondas, anillos… en Ajustes › Lo esencial.", ["ajustes"]],
  ["Si arrastras a tu mascota la puedes poner donde quieras.", null],
  ["Marca tus hábitos cada día en Hoy › Tareas y mira tu racha.", ["hoy", "tareas"]],
  ["«Hazme un diagnóstico del pc» y te digo por qué va lento.", null],
];

// [selector del elemento, texto, sección a abrir, pestaña]
const RECORRIDO = [
  [null, "¡Hola! Soy {nombre}. Te muestro la interfaz en un minuto.", "inicio"],
  ["#form-chat", "Aquí le escribes a Arché. Enter envía y la flecha ↑ repite lo último que pediste.", "inicio"],
  ['#nav [data-sec="hoy"]', "En Hoy están tus pendientes, el pomodoro, los gastos, las notas y el clima.", "inicio"],
  ['#nav [data-sec="equipo"]', "En Equipo manejas el PC: volumen, brillo, programas y rutinas.", "inicio"],
  ['#nav [data-sec="mente"]', "En Mente ves cómo aprende Arché: sus redes neuronales y todo lo que sabe hacer.", "inicio"],
  ["#modo-chip", "Aquí cambias de modo: programar, trabajo, técnico… Cada modo recuerda su propio aspecto.", "inicio"],
  ["#abrir-paleta", "Con Ctrl+K buscas cualquier cosa o le pides algo a Arché desde donde estés.", "inicio"],
  ['#nav [data-sec="ajustes"]', "Y en Ajustes cambias todo: estilos rápidos, colores, la forma de la esfera… y a mí. ¡Listo!", "inicio"],
];

/* ------------------------------------------------------------ estado */
function mascotaEstado() {
  const a = S.ajustes;
  if (a.mascota_reacciones === false) return "feliz";
  if (S.estado === "hablando") return "hablando";
  if (S.estado === "pensando") return "pensando";
  if (Date.now() < M.celebraHasta) return "celebrando";
  if ((S.equipo?.cpu ?? 0) >= 90) return "sudando";
  if ((S.controles || []).some((c) => (c.id === "examen" || c.id === "estudio") && c.trabajando)) return "estudiando";
  const quieto = (Date.now() - M.ultimaActividad) / 1000, h = new Date().getHours();
  if (quieto > 600 || (h < 6 && quieto > 120)) return "dormida";
  return "feliz";
}

/* ------------------------------------------------------------ dibujo */
function colorVar(n) { return getComputedStyle(document.documentElement).getPropertyValue(n).trim() || "#888"; }
function mezcla(a, b, t) {
  const p = (h) => { h = h.replace("#", ""); if (h.length === 3) h = h.split("").map((x) => x + x).join(""); return [0, 2, 4].map((i) => parseInt(h.substr(i, 2), 16) || 0); };
  const x = p(a), y = p(b);
  return "#" + x.map((v, i) => Math.round(v + (y[i] - v) * t).toString(16).padStart(2, "0")).join("");
}

function dibujarMascota(t) {
  const cv = M.cv, c = M.c; if (!cv || cv.offsetParent === null) return;
  const W = cv.width, s = W * 0.24, est = mascotaEstado(), ahora = Date.now();
  if (ahora > M.proxParpadeo) { M.parpadeoTs = ahora; M.proxParpadeo = ahora + 2500 + Math.random() * 3500; }
  const parp = ahora - M.parpadeoTs < 140;
  const salto = (ahora - M.saltoTs) / 1000;
  const rebote = salto < 0.8 ? -Math.abs(Math.sin(salto * 7)) * s * 0.5 * (1 - salto / 0.8) : 0;
  const flota = Math.sin(t / 500) * s * 0.05 * (est === "dormida" ? 0.3 : 1);
  const x = W / 2, y = W * 0.56 + flota + rebote;
  c.clearRect(0, 0, W, W);
  c.fillStyle = "rgba(0,0,0,.28)"; c.beginPath(); c.ellipse(x, W * 0.56 + s * 1.12, s * 0.8, s * 0.13, 0, 0, 7); c.fill();
  const pj = S.ajustes.mascota_personaje || "chispa";
  ({ robot: robot, gato: gato }[pj] || chispa)(c, x, y, s, est, t / 1000, parp);
  accesorios(c, x, y, s, est, t / 1000);
}

function ojo(c, cx, cy, rx, ry, est, parp, color = "#fff", pupila = "#15122e") {
  c.lineCap = "round";
  if (est === "dormida" || parp) { c.strokeStyle = pupila; c.lineWidth = Math.max(2, rx * 0.35); c.beginPath(); c.moveTo(cx - rx, cy); c.lineTo(cx + rx, cy); c.stroke(); return; }
  if (est === "celebrando") { c.strokeStyle = pupila; c.lineWidth = Math.max(2, rx * 0.4); c.beginPath(); c.arc(cx, cy + ry * 0.5, rx, Math.PI * 1.15, Math.PI * 1.85); c.stroke(); return; }
  c.fillStyle = color; c.beginPath(); c.ellipse(cx, cy, rx, ry, 0, 0, 7); c.fill();
  let [dx, dy] = M.mirar;
  if (est === "pensando") [dx, dy] = [0.6, -0.8];
  if (est === "estudiando") [dx, dy] = [Math.sin(Date.now() / 800) * 0.5, 0.7];
  c.fillStyle = pupila; c.beginPath(); c.ellipse(cx + dx * rx * 0.38, cy + dy * ry * 0.35, rx * 0.55, ry * 0.58, 0, 0, 7); c.fill();
  c.fillStyle = "#fff"; c.beginPath(); c.arc(cx + dx * rx * 0.38 - rx * 0.2, cy + dy * ry * 0.35 - ry * 0.25, rx * 0.18, 0, 7); c.fill();
}

function boca(c, cx, cy, w, est, t, color = "#15122e") {
  c.strokeStyle = color; c.fillStyle = color; c.lineWidth = Math.max(2, w * 0.14); c.lineCap = "round";
  if (est === "hablando") {
    const h = w * (0.25 + 0.35 * Math.abs(Math.sin(t * 14)));
    c.beginPath(); c.ellipse(cx, cy + h * 0.3, w * 0.4, h, 0, 0, 7); c.fill(); return;
  }
  if (est === "dormida" || est === "pensando") { c.beginPath(); c.arc(cx, cy + w * 0.2, w * 0.14, 0, 7); c.stroke(); return; }
  if (est === "sudando") { c.beginPath(); c.moveTo(cx - w * 0.4, cy + w * 0.2); for (let i = 0; i <= 4; i++) c.lineTo(cx - w * 0.4 + i * w * 0.2, cy + w * 0.2 + (i % 2 ? -w * 0.1 : w * 0.1)); c.stroke(); return; }
  const ancho = est === "celebrando" ? 1.25 : 1;
  c.beginPath(); c.arc(cx, cy - w * 0.15, w * 0.45 * ancho, Math.PI * 0.18, Math.PI * 0.82); c.stroke();
}

function chispa(c, x, y, s, est, t, parp) {
  const a1 = colorVar("--a1"), a2 = colorVar("--a2"), a2o = colorVar("--a2o"), a3 = colorVar("--a3");
  const cuerpo = mezcla(a2, "#ffffff", 0.12), claro = mezcla(cuerpo, "#ffffff", 0.35);
  const ax = x + s * 0.12 * Math.sin(t * 2), ay = y - s * 1.45;
  c.strokeStyle = a2o; c.lineWidth = s * 0.07; c.lineCap = "round"; c.beginPath(); c.moveTo(x, y - s * 0.95); c.lineTo(ax, y - s * 1.32); c.stroke();
  const r = s * 0.22 * (0.7 + 0.3 * Math.sin(t * 5));
  c.fillStyle = a1; c.shadowColor = a1; c.shadowBlur = s * 0.4;
  c.beginPath(); for (let k = 0; k < 8; k++) { const ang = k * Math.PI / 4, rr = k % 2 ? r * 0.35 : r; c.lineTo(ax + Math.cos(ang) * rr, ay + Math.sin(ang) * rr); } c.fill(); c.shadowBlur = 0;
  c.beginPath();
  for (let k = 0; k <= 72; k++) { const th = k / 72 * Math.PI * 2, rr = s * (1 + 0.04 * Math.sin(3 * th + t * 2)); c.lineTo(x + rr * Math.cos(th) * 1.05, y + rr * Math.sin(th) * (Math.sin(th) < 0 ? 1 : 0.95)); }
  const g = c.createRadialGradient(x - s * 0.4, y - s * 0.5, s * 0.1, x, y, s * 1.1); g.addColorStop(0, claro); g.addColorStop(1, cuerpo);
  c.fillStyle = g; c.fill(); c.strokeStyle = a2o; c.lineWidth = s * 0.05; c.stroke();
  for (const sx of [-1, 1]) {
    ojo(c, x + sx * s * 0.36, y - s * 0.12, s * 0.2, s * 0.24, est, parp);
    c.fillStyle = mezcla(cuerpo, a3, 0.55); c.globalAlpha = .7; c.beginPath(); c.ellipse(x + sx * s * 0.66, y + s * 0.19, s * 0.12, s * 0.07, 0, 0, 7); c.fill(); c.globalAlpha = 1;
  }
  boca(c, x, y + s * 0.32, s * 0.4, est, t);
}

function robot(c, x, y, s, est, t, parp) {
  const a1 = colorVar("--a1"), a1o = colorVar("--a1o"), a3 = colorVar("--a3"), fondo = colorVar("--fondo");
  const metal = mezcla(a1, "#ffffff", 0.3), oscuro = mezcla(fondo, a1o, 0.25);
  c.strokeStyle = metal; c.lineWidth = s * 0.07; c.beginPath(); c.moveTo(x, y - s * 0.85); c.lineTo(x, y - s * 1.22); c.stroke();
  c.fillStyle = mezcla(a1, a3, 0.5 + 0.5 * Math.sin(t * 4)); c.shadowColor = c.fillStyle; c.shadowBlur = s * 0.3;
  c.beginPath(); c.arc(x, y - s * 1.3, s * 0.13, 0, 7); c.fill(); c.shadowBlur = 0;
  c.fillStyle = a1o; for (const sx of [-1, 1]) c.fillRect(x + sx * s * 1.0 - s * 0.1, y - s * 0.2, s * 0.2, s * 0.5);
  c.fillStyle = metal; c.beginPath(); c.roundRect ? c.roundRect(x - s, y - s * 0.85, s * 2, s * 1.7, s * 0.3) : c.rect(x - s, y - s * 0.85, s * 2, s * 1.7); c.fill();
  c.strokeStyle = a1o; c.lineWidth = s * 0.05; c.stroke();
  c.fillStyle = oscuro; c.beginPath(); c.roundRect ? c.roundRect(x - s * 0.78, y - s * 0.6, s * 1.56, s * 1.1, s * 0.16) : c.rect(x - s * 0.78, y - s * 0.6, s * 1.56, s * 1.1); c.fill();
  const led = est === "sudando" ? a3 : a1;
  c.fillStyle = led; c.strokeStyle = led; c.shadowColor = led; c.shadowBlur = s * 0.25;
  for (const sx of [-1, 1]) {
    const cx = x + sx * s * 0.36, cy = y - s * 0.22;
    if (est === "dormida" || parp) { c.lineWidth = s * 0.08; c.beginPath(); c.moveTo(cx - s * 0.18, cy); c.lineTo(cx + s * 0.18, cy); c.stroke(); }
    else if (est === "celebrando") { c.lineWidth = s * 0.08; c.beginPath(); c.arc(cx, cy + s * 0.12, s * 0.17, Math.PI * 1.15, Math.PI * 1.85); c.stroke(); }
    else { let [dx, dy] = M.mirar; if (est === "pensando") [dx, dy] = [0.6, -0.7]; c.fillRect(cx - s * 0.16 + dx * s * 0.06, cy - s * 0.22 + dy * s * 0.06, s * 0.32, s * 0.44); }
  }
  c.shadowBlur = 0;
  boca(c, x, y + s * 0.22, s * 0.5, est, t, led);
}

function gato(c, x, y, s, est, t, parp) {
  const a3 = colorVar("--a3"), a3o = colorVar("--a3o"), texto = colorVar("--texto"), fondo = colorVar("--fondo");
  const pelo = mezcla(a3, texto, 0.25), oscuro = mezcla(pelo, fondo, 0.45);
  c.lineJoin = "round";
  for (const sx of [-1, 1]) {
    const mov = est === "feliz" ? Math.sin(t * 3 + sx) * s * 0.04 : 0;
    c.fillStyle = pelo; c.strokeStyle = oscuro; c.lineWidth = s * 0.05;
    c.beginPath(); c.moveTo(x + sx * s * 0.95, y - s * 0.2); c.lineTo(x + sx * s * 0.78 + mov, y - s * 1.2); c.lineTo(x + sx * s * 0.2, y - s * 0.78); c.closePath(); c.fill(); c.stroke();
    c.fillStyle = mezcla(pelo, "#ff9ab0", 0.5); c.beginPath(); c.moveTo(x + sx * s * 0.78, y - s * 0.42); c.lineTo(x + sx * s * 0.72 + mov, y - s * 0.95); c.lineTo(x + sx * s * 0.4, y - s * 0.72); c.closePath(); c.fill();
  }
  c.fillStyle = pelo; c.strokeStyle = oscuro; c.lineWidth = s * 0.05; c.beginPath(); c.ellipse(x, y + s * 0.02, s * 1.05, s * 0.88, 0, 0, 7); c.fill(); c.stroke();
  c.strokeStyle = oscuro; c.lineWidth = s * 0.06; c.lineCap = "round";
  for (const k of [-1, 0, 1]) { c.beginPath(); c.moveTo(x + k * s * 0.22, y - s * 0.8); c.lineTo(x + k * s * 0.18, y - s * 0.56); c.stroke(); }
  for (const sx of [-1, 1]) {
    ojo(c, x + sx * s * 0.42, y - s * 0.12, s * 0.2, s * 0.26, est, parp, mezcla("#c8ff9a", "#ffffff", 0.4));
    c.strokeStyle = oscuro; c.lineWidth = s * 0.035;
    for (const k of [-1, 1]) { c.beginPath(); c.moveTo(x + sx * s * 0.62, y + s * 0.3 + k * s * 0.05); c.lineTo(x + sx * s * 1.25, y + s * 0.3 + k * s * 0.22); c.stroke(); }
  }
  c.fillStyle = a3o; c.beginPath(); c.moveTo(x - s * 0.1, y + s * 0.1); c.lineTo(x + s * 0.1, y + s * 0.1); c.lineTo(x, y + s * 0.22); c.closePath(); c.fill();
  boca(c, x, y + s * 0.32, s * 0.34, est, t, oscuro);
}

function accesorios(c, x, y, s, est, t) {
  const tenue = colorVar("--tenue"), a1 = colorVar("--a1"), a2 = colorVar("--a2");
  if (est === "dormida") {
    c.fillStyle = tenue; c.textAlign = "center";
    for (let i = 0; i < 3; i++) { const f = (t * 0.6 + i / 3) % 1; c.globalAlpha = 1 - f; c.font = `600 ${s * (0.32 + 0.22 * f)}px sans-serif`; c.fillText("z", x + s * (0.9 + f * 0.7), y - s * (0.5 + f)); }
    c.globalAlpha = 1;
  } else if (est === "pensando") {
    c.fillStyle = a2;
    for (let i = 0; i < 3; i++) { c.globalAlpha = 0.35 + 0.65 * ((Math.sin(t * 4 - i) + 1) / 2); c.beginPath(); c.arc(x + s * (0.75 + i * 0.25), y - s * (1.0 + i * 0.22), s * (0.06 + i * 0.03), 0, 7); c.fill(); }
    c.globalAlpha = 1;
  } else if (est === "sudando") {
    const g = (t * 1.5) % 1, gx = x + s * 1.05, gy = y - s * 0.5 + g * s * 0.9;
    c.fillStyle = a1; c.beginPath(); c.moveTo(gx, gy - s * 0.18); c.quadraticCurveTo(gx + s * 0.13, gy + s * 0.02, gx, gy + s * 0.1); c.quadraticCurveTo(gx - s * 0.13, gy + s * 0.02, gx, gy - s * 0.18); c.fill();
  } else if (est === "estudiando") {
    const ly = y + s * 0.85; c.fillStyle = mezcla(colorVar("--a1o"), colorVar("--texto"), 0.15); c.strokeStyle = a1; c.lineWidth = s * 0.04;
    c.beginPath(); c.moveTo(x - s * 0.8, ly - s * 0.05); c.lineTo(x, ly - s * 0.25); c.lineTo(x + s * 0.8, ly - s * 0.05); c.lineTo(x + s * 0.8, ly + s * 0.45); c.lineTo(x, ly + s * 0.25); c.lineTo(x - s * 0.8, ly + s * 0.45); c.closePath(); c.fill(); c.stroke();
  } else if (est === "celebrando") {
    for (let i = 0; i < 10; i++) {
      const ang = i / 10 * Math.PI * 2 + t, rr = s * (1.25 + 0.15 * Math.sin(t * 6 + i));
      c.fillStyle = [a1, a2, colorVar("--a3"), "#facc15"][i % 4]; c.beginPath(); c.arc(x + Math.cos(ang) * rr, y + Math.sin(ang) * rr * 0.85, s * 0.06, 0, 7); c.fill();
    }
  }
}

/* ------------------------------------------------------------ globo */
function mascotaDecir(texto, botones = [], seg = 9) {
  if (!S.ajustes.mascota) return;
  const nombre = S.ajustes.mascota_nombre || "Chispa";
  $("#globo-txt").textContent = texto.replace(/\{nombre\}/g, nombre);
  $("#globo-botones").innerHTML = botones.map(([t, id]) => `<button class="${id === "sig" ? "btn-acento" : "mini"}" data-globo="${id}">${esc(t)}</button>`).join("");
  $("#globo").hidden = false;
  M.globoHasta = seg ? Date.now() + seg * 1000 : Infinity;
}
function cerrarGlobo() { $("#globo").hidden = true; M.globoHasta = 0; }
window.mascotaCelebrar = (texto) => {
  if (!S.ajustes.mascota || S.ajustes.mascota_reacciones === false) return;
  M.celebraHasta = Date.now() + 2200; M.saltoTs = Date.now();
  if (texto && !M.paso) mascotaDecir(texto, [], 4);
};

function consejo() {
  let i; do { i = Math.floor(Math.random() * CONSEJOS.length); } while (i === M.ultConsejo && CONSEJOS.length > 1);
  M.ultConsejo = i;
  const [txt, ir] = CONSEJOS[i];
  mascotaDecir(txt, ir ? [["Llévame", "ir:" + ir.join(":")], ["Gracias", "cerrar"]] : [["Gracias", "cerrar"]], 12);
}

function menuMascota() {
  const n = S.ajustes.mascota_nombre || "Chispa";
  mascotaDecir(`¡Hola! Soy ${n}. ¿Qué hacemos?`, [["Un consejo", "consejo"], ["Recorrido", "recorrido"], ["Cambiar de personaje", "personaje"], ["Esconderme", "ocultar"]], 14);
}

/* ------------------------------------------------------------ recorrido */
function empezarRecorrido() { M.paso = 0; mostrarPaso(); }
function mostrarPaso() {
  const paso = RECORRIDO[M.paso]; if (!paso) return terminarRecorrido();
  const [sel, txt, sec] = paso;
  if (sec && S.seccion !== sec) irA(sec);
  const foco = $("#foco"), rec = $("#recorrido");
  rec.hidden = false;
  const el = sel && $(sel);
  if (el) { const r = el.getBoundingClientRect(); Object.assign(foco.style, { left: r.left - 8 + "px", top: r.top - 8 + "px", width: r.width + 16 + "px", height: r.height + 16 + "px", opacity: 1 }); }
  else Object.assign(foco.style, { left: "50%", top: "50%", width: "0px", height: "0px", opacity: 1 });
  const ultimo = M.paso === RECORRIDO.length - 1;
  mascotaDecir(txt, [[ultimo ? "Terminar" : "Siguiente", "sig"], ...(ultimo ? [] : [["Saltar", "saltar"]])], 0);
  $("#globo").dataset.paso = `${M.paso + 1} de ${RECORRIDO.length}`;
}
function terminarRecorrido() {
  M.paso = null; $("#recorrido").hidden = true; cerrarGlobo(); delete $("#globo").dataset.paso;
  guardar("recorrido_v3", true);
  window.mascotaCelebrar?.("¡Ya conoces todo! Si me necesitas, tócame.");
}

/* ------------------------------------------------------------ ciclo */
function mascotaCiclo(t) {
  const a = S.ajustes;
  const el = $("#mascota");
  el.hidden = !a.mascota;
  if (!a.mascota) return;
  el.style.setProperty("--tam", (a.mascota_tamano || 100) / 100);
  dibujarMascota(t);
  if (!$("#globo").hidden && Date.now() > M.globoHasta) cerrarGlobo();
  const est = mascotaEstado();
  if (est !== M.ultEstado) {
    if (est === "sudando" && a.mascota_reacciones !== false && !M.paso) mascotaDecir("¡Uf! El equipo va muy cargado. Mira Equipo › Rendimiento.", [["Ver", "ir:equipo:rendimiento"]], 8);
    M.ultEstado = est;
  }
  const cada = { poca: 480, normal: 240, mucha: 120 }[a.mascota_frecuencia || "normal"] * 1000;
  if (a.consejos !== false && Date.now() > M.proxConsejo && $("#globo").hidden && est !== "dormida" && !M.paso) { consejo(); M.proxConsejo = Date.now() + cada; }
}

function mascotaIniciar() {
  M.cv = $("#mascota-canvas"); M.c = M.cv.getContext("2d");
  const el = $("#mascota"), pos = guardado("mascota_pos", null);
  if (pos) { el.style.right = pos.r + "px"; el.style.bottom = pos.b + "px"; }
  ["pointermove", "keydown", "pointerdown"].forEach((ev) => document.addEventListener(ev, (e) => {
    M.ultimaActividad = Date.now();
    if (ev === "pointermove") {
      const r = M.cv.getBoundingClientRect(), dx = e.clientX - (r.left + r.width / 2), dy = e.clientY - (r.top + r.height / 2), d = Math.hypot(dx, dy) || 1;
      M.mirar = [dx / d * Math.min(1, d / 300), dy / d * Math.min(1, d / 300)];
    }
  }, { passive: true }));
  // arrastrar o tocar
  M.cv.addEventListener("pointerdown", (e) => { M.arrastre = { x: e.clientX, y: e.clientY, r: parseFloat(getComputedStyle(el).right), b: parseFloat(getComputedStyle(el).bottom), movio: false }; M.cv.setPointerCapture(e.pointerId); });
  M.cv.addEventListener("pointermove", (e) => {
    const a = M.arrastre; if (!a) return;
    const dx = e.clientX - a.x, dy = e.clientY - a.y;
    if (Math.hypot(dx, dy) > 5) a.movio = true;
    if (a.movio) { el.style.right = Math.max(0, Math.min(innerWidth - 80, a.r - dx)) + "px"; el.style.bottom = Math.max(0, Math.min(innerHeight - 80, a.b - dy)) + "px"; }
  });
  M.cv.addEventListener("pointerup", () => {
    const a = M.arrastre; M.arrastre = null; if (!a) return;
    if (a.movio) guardar("mascota_pos", { r: parseFloat(el.style.right), b: parseFloat(el.style.bottom) });
    else { M.saltoTs = Date.now(); M.paso === null && ($("#globo").hidden ? menuMascota() : cerrarGlobo()); }
  });
  $("#globo").addEventListener("click", (e) => {
    const b = e.target.closest("[data-globo]"); if (!b) return;
    const id = b.dataset.globo;
    if (id === "sig") { M.paso++; mostrarPaso(); }
    else if (id === "saltar") terminarRecorrido();
    else if (id === "cerrar") cerrarGlobo();
    else if (id === "ahora-no") { guardar("recorrido_v3", true); mascotaDecir("Cuando quieras, tócame y elige «Recorrido».", [], 5); }
    else if (id === "consejo") consejo();
    else if (id === "recorrido") empezarRecorrido();
    else if (id === "ocultar") { cerrarGlobo(); fijarAjuste("mascota", false); aviso("Escondí la mascota. Vuelve a activarla en Ajustes › Mascota.", "info", 6000); }
    else if (id === "personaje") {
      const l = ["chispa", "robot", "gato"], i = (l.indexOf(S.ajustes.mascota_personaje) + 1) % l.length;
      fijarAjuste("mascota_personaje", l[i]); M.saltoTs = Date.now(); mascotaDecir(`¿Qué tal así? Ahora soy ${l[i]}.`, [["Otro", "personaje"], ["Me gusta", "cerrar"]], 10);
    } else if (id.startsWith("ir:")) { const [, sec, pes] = id.split(":"); cerrarGlobo(); irA(sec, pes); }
  });
  addEventListener("resize", () => { if (M.paso !== null) mostrarPaso(); });
  const bucle = (t) => { mascotaCiclo(t); requestAnimationFrame(bucle); };
  requestAnimationFrame(bucle);
  // la primera vez, el recorrido
  setTimeout(() => { if (S.ajustes.mascota && !guardado("recorrido_v3", false)) { mascotaDecir("¡Hola! Soy {nombre}. ¿Te muestro la interfaz nueva?", [["Sí, muéstrame", "recorrido"], ["Ahora no", "ahora-no"]], 0); } }, 2500);
}
window.mascotaRecorrido = empezarRecorrido;
mascotaIniciar();
