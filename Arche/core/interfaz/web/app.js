/* Interfaz de Arché — versión 3.
   Habla con core/interfaz/web/__init__.py: /api/estado cada segundo y
   /api/enviar para mandar órdenes (le llegan a Arché como si las escribieras). */
"use strict";

const LLAVE = (location.hash.match(/llave=([\w\-]+)/) || [])[1] || sessionStorage.getItem("arche_llave") || "";
if (LLAVE) { sessionStorage.setItem("arche_llave", LLAVE); history.replaceState(null, "", location.pathname); }

const $ = (s, el = document) => el.querySelector(s);
const $$ = (s, el = document) => [...el.querySelectorAll(s)];
const esc = (t) => String(t ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const guardado = (k, d) => { try { const v = localStorage.getItem("arche_" + k); return v === null ? d : JSON.parse(v); } catch { return d; } };
const guardar = (k, v) => { try { localStorage.setItem("arche_" + k, JSON.stringify(v)); } catch {} };
const icono = (n, cls = "") => `<svg${cls ? ` class="${cls}"` : ""}><use href="#i-${esc(n)}"/></svg>`;
const plata = (v) => "$" + Math.round(v || 0).toLocaleString("es-CO");
const hace = (ts) => { const s = Math.max(0, Date.now() / 1000 - ts); return s < 60 ? "ahora" : s < 3600 ? `hace ${Math.round(s / 60)} min` : `hace ${Math.round(s / 3600)} h`; };

const S = {
  ajustes: {}, tema: null, ultimoId: 0, mensajes: [], estado: "reposo", seccion: null, pestana: {},
  historialCPU: [], historialRAM: [], sinLeer: 0, ultimaOrden: "", historialOrdenes: guardado("ordenes", []),
  posHist: -1, conectado: false, comandos: null, inicio: null, temas: [], catalogo: [], pers: [], estilos: [],
  equipo: {}, controles: [], aplica: {}, rutinas: [], fondos: [], intenciones: [], alarmas: [], pendientes: [],
};

async function api(ruta, cuerpo) {
  const op = { headers: { "X-Llave": LLAVE } };
  if (cuerpo !== undefined) { op.method = "POST"; op.headers["Content-Type"] = "application/json"; op.body = JSON.stringify(cuerpo); }
  const r = await fetch(ruta, op);
  if (r.status === 401) throw new Error("llave");
  return r.json();
}

/* =========================================================== secciones y pestañas */
const SECCIONES = ["inicio", "hoy", "equipo", "mente", "ajustes"];
const NOMBRE_SECCION = { inicio: "Arché", hoy: "Hoy", equipo: "Equipo", mente: "Mente", ajustes: "Ajustes" };
const ICONO_SECCION = { inicio: "chat", hoy: "calendario", equipo: "pc", mente: "arche", ajustes: "ajustes" };
const PESTANAS = {
  hoy: [["tareas", "Tareas", "check"], ["enfoque", "Enfoque", "reloj"], ["dinero", "Dinero", "dinero"], ["notas", "Notas", "nota"], ["mundo", "Mundo", "globo"]],
  equipo: [["controles", "Controles", "app"], ["rendimiento", "Rendimiento", "sistema"], ["rutinas", "Rutinas", "play"]],
  mente: [["trabajo", "Cómo trabajo", "arche"], ["redes", "Redes", "app"], ["aprendizaje", "Aprendizaje", "libro"], ["sabe", "Lo que sé hacer", "comandos"], ["actividad", "Actividad", "sistema"]],
};

function pestanasDe(sec) {
  let lista = PESTANAS[sec] || [];
  if (sec === "hoy") {
    const orden = ordenHoy(S.ajustes.web_hoy_pestanas).filter((x) => x.ver).map((x) => x.id);
    lista = orden.map((id) => lista.find((p) => p[0] === id)).filter(Boolean);
  }
  return lista;
}

function irA(sec, pestana) {
  if (!SECCIONES.includes(sec) || $(`#nav [data-sec="${sec}"]`)?.hidden) sec = "inicio";
  const cambio = S.seccion !== sec;
  S.seccion = sec;
  document.documentElement.dataset.seccion = sec;
  $$(".seccion").forEach((s) => { s.hidden = s.id !== "s-" + sec; });
  $$("#nav button").forEach((b) => b.classList.toggle("activo", b.dataset.sec === sec));
  $("#titulo-sec").textContent = sec === "inicio" ? "" : NOMBRE_SECCION[sec];
  guardar("seccion", sec);
  const ps = pestanasDe(sec);
  $("#pestanas").innerHTML = ps.map(([id, n, ic]) => `<button role="tab" data-pestana-ir="${id}">${icono(ic)}${esc(n)}</button>`).join("");
  if (ps.length) {
    let p = pestana || S.pestana[sec] || guardado("pestana_" + sec, ps[0][0]);
    if (!ps.some((x) => x[0] === p)) p = ps[0][0];
    mostrarPestana(sec, p, cambio);
  }
  if (sec === "inicio") { S.sinLeer = 0; pintarInsignia(); bajarChat(true); setTimeout(() => $("#chat-txt").focus(), 60); }
  if (sec === "ajustes") cargarAjustes();
}

function mostrarPestana(sec, id, animar = true) {
  S.pestana[sec] = id; guardar("pestana_" + sec, id);
  $$(`#s-${sec} .pestana`).forEach((p) => {
    const on = p.dataset.pestana === id; p.hidden = !on;
    if (on && animar) { p.classList.remove("entra"); void p.offsetWidth; p.classList.add("entra"); }
  });
  $$("#pestanas button").forEach((b) => { const on = b.dataset.pestanaIr === id; b.classList.toggle("activo", on); b.setAttribute("aria-selected", on); });
  const clave = sec + ":" + id;
  if (clave === "hoy:mundo" || clave === "hoy:notas") cargarInicio();
  if (clave === "equipo:rutinas") cargarRutinas();
  if (clave === "equipo:rendimiento") { S._pes = null; S._medidores = null; requestAnimationFrame(() => { pintarEquipo(S.equipo); pintarGrafica(); }); }
  if (clave === "mente:trabajo") { S._ctrl = null; pintarControles(S.controles); }
  if (clave === "mente:aprendizaje") cargarArche();
  if (clave === "mente:redes") cargarRedes();
  if (clave === "mente:sabe") cargarComandos();
}

function seccionesOrdenadas(lista) {
  const guard = (lista || []).filter((x) => SECCIONES.includes(x.id));
  const ids = guard.map((x) => x.id);
  return [...guard, ...SECCIONES.filter((s) => !ids.includes(s)).map((id) => ({ id, ver: true }))];
}
function ordenHoy(lista) {
  const todas = PESTANAS.hoy.map((p) => p[0]);
  const guard = (lista || []).filter((x) => todas.includes(x.id));
  const ids = guard.map((x) => x.id);
  return [...guard, ...todas.filter((s) => !ids.includes(s)).map((id) => ({ id, ver: true }))];
}
function aplicarSecciones() {
  const nav = $("#nav");
  for (const x of seccionesOrdenadas(S.ajustes.web_secciones)) {
    const b = nav.querySelector(`[data-sec="${x.id}"]`);
    nav.appendChild(b);
    b.hidden = !x.ver && !["inicio", "ajustes"].includes(x.id);
  }
  if (S.seccion && $(`#nav [data-sec="${S.seccion}"]`)?.hidden) irA("inicio");
  if (S.seccion && PESTANAS[S.seccion]) {
    const actuales = $$("#pestanas button").map((b) => b.dataset.pestanaIr).join();
    if (actuales !== pestanasDe(S.seccion).map((p) => p[0]).join()) irA(S.seccion);
  }
}

/* =========================================================== tema y personalización */
function aplicarTema(t) {
  if (!t || !t.colores) return;
  const c = t.colores, r = document.documentElement.style;
  const mapa = { fondo: "--fondo", panel: "--panel", panel2: "--panel2", borde: "--borde", texto: "--texto", tenue: "--tenue",
    rojo_claro: "--a3", rojo: "--a3o", ok: "--ok", atencion: "--aten", alerta: "--alerta" };
  for (const [k, v] of Object.entries(mapa)) if (c[k]) r.setProperty(v, c[k]);
  S.colores = c;
  aplicarAcentos(S.ajustes);
  if (S.temas.length && S.seccion === "ajustes") pintarTemas();
}

function aplicarAcentos(a) {
  const r = document.documentElement.style, c = S.colores || {};
  const ac = a.web_acento, ac2 = a.web_acento_2;
  r.setProperty("--a2", ac || c.morado_claro || "#9b6bff");
  r.setProperty("--a2o", ac ? `color-mix(in srgb, ${ac} 72%, #000)` : c.morado || "#6b34c9");
  r.setProperty("--a1", ac2 || c.azul_claro || "#5b7cff");
  r.setProperty("--a1o", ac2 ? `color-mix(in srgb, ${ac2} 72%, #000)` : c.azul || "#2f4fd1");
  S.colorEsfera = { a: ac2 || null, b: ac || null };
}

/* Cada opción de personalizacion.py se aplica sola: atributo data-<clave> y, si tiene, su variable CSS */
function aplicarPersonalizacion(a) {
  const html = document.documentElement;
  for (const [k, info] of Object.entries(S.aplica)) {
    if (info.tipo === "lista") continue;
    const v = a[k];
    if (v === undefined) continue;
    html.setAttribute("data-" + k, v === true ? "si" : v === false ? "no" : String(v));
    if (info.css) {
      if (v === "" || v === null) html.style.removeProperty(info.css);
      else html.style.setProperty(info.css, typeof v === "number" ? v + (info.unidad || "") : v);
    }
  }
}

function aplicarAjustes(a) {
  const r = document.documentElement.style;
  aplicarPersonalizacion(a);
  aplicarAcentos(a);
  r.setProperty("--escala", (a.ui_escala || 100) / 100);
  r.setProperty("--texto-escala", (a.texto_escala || 100) / 100);
  r.setProperty("--vel", Math.max(.25, (a.anim_velocidad || 100) / 100));
  r.setProperty("--chat-tam", ((a.chat_tam || 11) / 11 * .97).toFixed(3) + "rem");
  r.setProperty("--chat-espacio", (a.chat_espacio ?? 10) + "px");
  r.setProperty("--usuario", a.chat_color_usuario || "var(--a2o)");
  r.setProperty("--arche-msg", a.chat_color_arche || "var(--panel2)");
  if (a.fuente && (!a.web_fuente || a.web_fuente === "sistema")) { r.setProperty("--fuente", `"${a.fuente}", "Segoe UI", system-ui, sans-serif`); r.setProperty("--fuente-titulo", `"${a.fuente}", "Segoe UI", system-ui, sans-serif`); }
  else if (!a.web_fuente || a.web_fuente === "sistema") { r.removeProperty("--fuente"); r.removeProperty("--fuente-titulo"); }
  else { r.removeProperty("--fuente"); r.removeProperty("--fuente-titulo"); }
  document.body.classList.toggle("reducido", !!a.reducir_movimiento);
  $("#btn-mic").classList.toggle("encendido", !!a.escucha);
  $("#chat-mic").classList.toggle("encendido", !!a.escucha);
  $("#avisos").classList.toggle("arriba", a.notif_posicion === "arriba");
  $("#p-clima").hidden = a.web_clima === false;
  $("#p-noticias").hidden = a.web_noticias === false;
  const fi = $("#fondo-img");
  if (a.fondo && /\.(png|jpe?g|webp|gif|bmp)$/i.test(a.fondo)) { fi.style.backgroundImage = `url("/fondo/${encodeURIComponent(a.fondo)}")`; fi.classList.add("con"); }
  else fi.classList.remove("con");
  fi.style.setProperty("--oscuridad", (a.fondo_oscuridad ?? 55) / 100);
  fi.style.filter = a.fondo_desenfoque ? `blur(${a.fondo_desenfoque}px)` : "";
  $$("#nav button, .rail-pie button").forEach((b) => { b.dataset.nombre = b.querySelector(".rail-txt")?.textContent || b.title; });
  aplicarSecciones();
  pintarDock();
  pintarVistazos();
  pintarSugerencias();
  pomoRefrescar();
  if (S.seccion === "ajustes") { pintarOrden(); pintarListaBotones(); }
}

async function fijarAjuste(clave, valor) {
  S.ajustes[clave] = valor;
  aplicarAjustes(S.ajustes);
  try {
    const r = await api("/api/ajuste", { clave, valor });
    if (!r.ok) aviso(r.error || "No pude guardar ese ajuste.", "error");
    else { S.ajustes[clave] = r.valor; if (clave === "tema") setTimeout(sondear, 150); }
  } catch { aviso("Se perdió la conexión con Arché.", "error"); }
}

/* =========================================================== enviar órdenes */
async function enviar(texto, { mostrar = true } = {}) {
  texto = String(texto || "").trim();
  if (!texto) return;
  S.ultimaOrden = texto;
  S.historialOrdenes = [texto, ...S.historialOrdenes.filter((x) => x !== texto)].slice(0, 50);
  guardar("ordenes", S.historialOrdenes);
  S.posHist = -1;
  S.esperandoDesde = Date.now();
  if (S.ajustes.web_sonido_envio) clic();
  try {
    await api("/api/enviar", { texto });
    if (mostrar && S.seccion !== "inicio") aviso(`Le pedí a Arché: «${texto}»`, "info", 2500);
  } catch { aviso("No pude hablar con Arché. ¿Sigue abierta la consola?", "error"); }
  setTimeout(sondear, 250);
}

let audio;
function clic() {
  try {
    audio = audio || new AudioContext();
    const o = audio.createOscillator(), g = audio.createGain();
    o.frequency.value = 880; g.gain.setValueAtTime(.05, audio.currentTime); g.gain.exponentialRampToValueAtTime(.0001, audio.currentTime + .08);
    o.connect(g).connect(audio.destination); o.start(); o.stop(audio.currentTime + .09);
  } catch {}
}
function campanita() {
  try {
    audio = audio || new AudioContext();
    [0, .25, .5].forEach((t, i) => {
      const o = audio.createOscillator(), g = audio.createGain();
      o.frequency.value = [880, 1175, 1568][i];
      g.gain.setValueAtTime(.0001, audio.currentTime + t); g.gain.exponentialRampToValueAtTime(.15, audio.currentTime + t + .02);
      g.gain.exponentialRampToValueAtTime(.0001, audio.currentTime + t + .6);
      o.connect(g).connect(audio.destination); o.start(audio.currentTime + t); o.stop(audio.currentTime + t + .65);
    });
  } catch {}
}

function confirmar(texto) {
  return new Promise((ok) => {
    const v = $("#confirmar");
    $("#conf-txt").textContent = texto;
    v.hidden = false; $("#conf-si").focus();
    const fin = (r) => { v.hidden = true; $("#conf-si").onclick = $("#conf-no").onclick = v.onclick = null; ok(r); };
    $("#conf-si").onclick = () => fin(true);
    $("#conf-no").onclick = () => fin(false);
    v.onclick = (e) => { if (e.target === v) fin(false); };
  });
}

function aviso(texto, tipo = "info", ms) {
  const a = S.ajustes;
  if (a.notif_silencio && tipo !== "error") return;
  if ((tipo === "info" && a.notif_info === false) || (tipo === "exito" && a.notif_exito === false) || (tipo === "error" && a.notif_error === false)) return;
  const el = document.createElement("div");
  el.className = "aviso " + tipo;
  el.innerHTML = `<span>${esc(texto)}</span>`;
  const quitar = () => { el.classList.add("sale"); setTimeout(() => el.remove(), 260); };
  el.onclick = () => { if (tipo === "arche") irA("inicio"); quitar(); };
  $("#avisos").appendChild(el);
  setTimeout(quitar, ms || (a.notif_segundos || 6) * 1000);
  while ($("#avisos").children.length > 4) $("#avisos").firstChild.remove();
}

/* =========================================================== escenario y conversación */
function horaCorta(ts) { return new Date(ts * 1000).toLocaleTimeString("es-CO", { hour: "numeric", minute: "2-digit", hour12: !S.ajustes.web_reloj_24h }); }
function nombreDia(ts) {
  const d = new Date(ts * 1000), hoy = new Date(), ayer = new Date(Date.now() - 864e5);
  if (d.toDateString() === hoy.toDateString()) return "Hoy";
  if (d.toDateString() === ayer.toDateString()) return "Ayer";
  return d.toLocaleDateString("es-CO", { weekday: "long", day: "numeric", month: "long" });
}

function conversando() { return S.mostrarAnterior || S.mensajes.some((m) => !m.viejo && !m.fondo); }

function pintarEscenario() {
  const conv = conversando();
  $("#escenario").classList.toggle("conversando", conv);
  const viejos = S.mensajes.filter((m) => m.viejo && !m.fondo).length;
  const va = $("#ver-anterior");
  va.hidden = conv || !viejos;
  va.textContent = `Ver la conversación anterior (${viejos} mensajes)`;
  pintarSugerencias();
}

function pintarChat() {
  const caja = $("#mensajes"), filtro = $("#chat-filtro").value.trim().toLowerCase();
  const modoFondo = S.ajustes.web_avisos_fondo || "agrupados";
  let lista = S.mensajes.filter((m) => !(m.fondo && modoFondo === "ocultos"));
  if (filtro) lista = lista.filter((m) => m.t.toLowerCase().includes(filtro));
  if (filtro && !lista.length) { caja.innerHTML = `<p class="vacio" style="text-align:center">Nada coincide con «${esc(filtro)}».</p>`; return pintarEscenario(); }
  let html = "", dia = "", prev = null;
  for (let k = 0; k < lista.length; k++) {
    const m = lista[k];
    const d = new Date(m.ts * 1000).toDateString();
    if (d !== dia) { dia = d; prev = null; html += `<div class="separador-dia">${esc(nombreDia(m.ts))}</div>`; }
    if (m.fondo && modoFondo === "agrupados" && !filtro) {
      const grupo = [m];
      while (k + 1 < lista.length && lista[k + 1].fondo && new Date(lista[k + 1].ts * 1000).toDateString() === d) grupo.push(lista[++k]);
      const id = grupo[0].id, abierto = S.gruposAbiertos?.has(id);
      html += `<div class="fondo-grupo${abierto ? " abierto" : ""}"><button class="fondo-linea" data-grupo="${id}">${icono("arche")}<span>${esc(grupo[grupo.length - 1].t)}</span>${grupo.length > 1 ? `<em>${abierto ? "ocultar" : "+" + (grupo.length - 1)}</em>` : ""}</button>`
        + (abierto && grupo.length > 1 ? `<ul>${grupo.slice(0, -1).map((g) => `<li><span>${horaCorta(g.ts)}</span>${esc(g.t)}</li>`).join("")}</ul>` : "") + `</div>`;
      prev = null; continue;
    }
    const seguido = prev && prev.q === m.q && m.ts - prev.ts < 180;
    html += htmlMensaje(m, filtro, seguido);
    prev = m;
  }
  caja.innerHTML = html;
  pintarEscenario();
}

function entendiDe(m) {
  if (m.q !== "tu" || S.ajustes.web_entendi === false) return "";
  const i = S.intenciones.find((x) => x.cmd.trim() === m.t.trim() && Math.abs(x.ts - m.ts) < 120);
  return i ? i.intencion.replace(/_/g, " ") : "";
}

function htmlMensaje(m, filtro, seguido) {
  let t = esc(m.t);
  if (filtro) t = t.replace(new RegExp(filtro.replace(/[.*+?^${}()|[\]\\]/g, "\\$&"), "gi"), (x) => `<mark>${x}</mark>`);
  const partes = [];
  if (S.ajustes.chat_marcas_tiempo) partes.push(horaCorta(m.ts));
  const ent = entendiDe(m);
  if (ent) partes.push(`<span class="entendi">entendí: ${esc(ent)}</span>`);
  const meta = partes.length ? `<div class="meta">${partes.join("")}</div>` : "";
  const copiar = m.q === "arche" ? `<button class="copiar" data-copiar="${m.id}" title="Copiar" aria-label="Copiar">${icono("copiar")}</button>` : "";
  return `<div class="msg ${m.q}${seguido ? " seguido" : ""}${m.viejo ? " viejo" : ""}${m.fondo ? " de-fondo" : ""}${m.nuevo ? " nuevo" : ""}" data-id="${m.id}"><div class="fila"><span class="avatar" aria-hidden="true"></span><div class="burbuja">${t}${copiar}</div></div>${meta}</div>`;
}

function bajarChat(forzar) {
  const c = $("#mensajes");
  if (forzar || c.scrollHeight - c.scrollTop - c.clientHeight < 160) c.scrollTop = c.scrollHeight;
}

function recibirMensajes(nuevos) {
  if (!nuevos.length) return;
  let ultArche = null;
  for (const m of nuevos) {
    const i = S.mensajes.findIndex((x) => x.q === m.q && x.ts === m.ts);
    if (i >= 0) S.mensajes[i] = m; else S.mensajes.push(m);
    if (S.ultimoId) m.nuevo = true;
    if (m.q === "arche" && !m.viejo && !m.fondo) ultArche = m;
  }
  S.mensajes = S.mensajes.slice(-300);
  if (S.ultimoId && ultArche) {
    if (S.seccion !== "inicio") {
      S.sinLeer++; pintarInsignia();
      if (S.ajustes.web_aviso_respuesta !== false && Date.now() - (S.esperandoDesde || 0) < 60000) aviso(ultArche.t.slice(0, 160) + (ultArche.t.length > 160 ? "…" : ""), "arche");
    }
    S.esperandoDesde = 0;
  }
  pintarChat(); bajarChat(!S.ultimoId || nuevos.some((m) => m.q === "tu"));
  pintarRespuestasRapidas();
  S.mensajes.forEach((m) => delete m.nuevo);
}

function pintarInsignia() {
  const b = $("#insignia-chat");
  b.hidden = !S.sinLeer;
  b.textContent = S.sinLeer > 9 ? "9+" : S.sinLeer;
}

function pintarRespuestasRapidas() {
  const ult = S.mensajes[S.mensajes.length - 1], caja = $("#respuestas-rapidas");
  if (!ult || ult.q !== "arche" || ult.viejo || ult.fondo) { caja.innerHTML = ""; return; }
  const t = ult.t.toLowerCase();
  let opciones = [];
  if (/\[s\/n\]|\(s\/n\)|\bs\/n\b/.test(t)) opciones = [["s", "Sí"], ["n", "No"]];
  else if (/\?\s*$/.test(t.split("\n").pop())) opciones = [["sí", "Sí"], ["no", "No"], ["cancela", "Cancelar"]];
  const nums = [...ult.t.matchAll(/^\s*(\d{1,2})[.)]\s+(.{1,40})/gm)].slice(0, 6);
  if (nums.length >= 2) opciones = nums.map((n) => [n[1], `${n[1]}. ${n[2]}`]);
  caja.innerHTML = opciones.map(([v, e]) => `<button class="chip" data-orden="${esc(v)}">${esc(e)}</button>`).join("");
}

function pintarSugerencias() {
  const ver = !conversando() && S.ajustes.web_sugerencias !== false;
  const base = ["¿Cómo está el clima?", "Recuérdame tomar agua en 30 minutos", "Hazme un diagnóstico del pc", "Dame las noticias"];
  $("#sugerencias").innerHTML = ver ? base.map((s) => `<button class="chip" data-orden="${esc(s)}">${esc(s)}</button>`).join("") : "";
}

function pintarDock() {
  const lista = S.ajustes.web_botones || [];
  const k = JSON.stringify(lista); if (k === S._dock) return; S._dock = k;
  $("#dock").innerHTML = lista.map((b) => `<button data-orden="${esc(b.orden)}" title="${esc(b.orden)}">${icono(b.icono || "rayo")}${esc(b.texto)}</button>`).join("");
}

function saludo() {
  const h = new Date().getHours();
  const base = h < 5 ? "Buenas noches" : h < 12 ? "Buenos días" : h < 19 ? "Buenas tardes" : "Buenas noches";
  const propio = (S.ajustes.web_saludo || "").trim();
  if (propio) return propio.replace(/\{nombre\}/g, S.usuario || "").replace(/\s+([,.!?])/g, "$1").replace(/\s{2,}/g, " ");
  return S.usuario ? `${base}, ${S.usuario}.` : `${base}.`;
}

function reloj() {
  const ahora = new Date();
  $("#reloj").textContent = ahora.toLocaleTimeString("es-CO", { hour: "numeric", minute: "2-digit", second: S.ajustes.web_segundos ? "2-digit" : undefined, hour12: !S.ajustes.web_reloj_24h });
  const f = ahora.toLocaleDateString("es-CO", { weekday: "long", day: "numeric", month: "long" });
  $("#fecha-larga").textContent = f.charAt(0).toUpperCase() + f.slice(1);
  $("#saludo").textContent = saludo();
}

/* vistazos: lo justo para saber cómo va el día, sin cajas */
function iconoClima(cod) {
  if (cod === 0 || cod === 1) return "sol";
  if (cod >= 51 && cod <= 82) return "gota";
  if (cod >= 95) return "rayo";
  return "nube";
}
function pintarVistazos() {
  const a = S.ajustes, v = [];
  if (a.web_info !== "minima") {
    const cl = S.inicio?.clima;
    if (a.web_v_clima !== false && a.web_clima !== false && cl && cl.actual) v.push(["mundo", iconoClima(cl.actual.codigo), `<strong>${cl.actual.temp}°</strong> ${esc(cl.actual.estado.toLowerCase())}`]);
    const al = S.alarmas[0];
    if (a.web_v_recordatorio !== false && al) {
      const cuando = (al.describe || "").match(/\(faltan? ([^)]+)\)/);
      v.push(["tareas", "campana", `<strong>${esc(al.texto || "Aviso")}</strong> ${cuando ? "en " + esc(cuando[1]) : ""}`]);
    }
    const faltan = S.pendientes.filter((p) => !p.hecho).length;
    if (a.web_v_pendientes !== false && faltan) v.push(["tareas", "check", `<strong>${faltan}</strong> ${faltan === 1 ? "pendiente" : "pendientes"}`]);
    if (a.web_v_pomodoro !== false && P.corriendo) v.push(["enfoque", "reloj", `<strong>${$("#pomo-tiempo").textContent}</strong> ${P.fase === "foco" ? "de concentración" : "de descanso"}`]);
    const e = S.equipo;
    if (a.web_v_equipo !== false && e && (e.ram >= (a.limite_ram || 90) - 5 || e.cpu >= (a.limite_cpu || 90) - 5)) v.push(["rendimiento", "cpu", e.ram >= e.cpu ? `RAM al <strong>${Math.round(e.ram)}%</strong>` : `CPU al <strong>${Math.round(e.cpu)}%</strong>`]);
    if (a.web_info === "completa" && typeof e?.bateria === "number") v.push(["rendimiento", "rayo", `batería <strong>${Math.round(e.bateria)}%</strong>`]);
  }
  const html = v.map(([dest, ic, txt]) => `<button class="vistazo" data-vistazo="${dest}">${icono(ic)}<span>${txt}</span></button>`).join("");
  if (html !== S._vist) { S._vist = html; $("#vistazos").innerHTML = html; }
}

/* =========================================================== sondeo */
let fallos = 0;
async function sondear() {
  clearTimeout(S.t);
  try {
    const d = await api("/api/estado?desde=" + S.ultimoId);
    fallos = 0; S.conectado = true;
    if (d.tema && JSON.stringify(d.tema) !== JSON.stringify(S.tema)) { S.tema = d.tema; aplicarTema(d.tema); }
    if (JSON.stringify(d.ajustes) !== JSON.stringify(S.ajustesServidor)) { S.ajustesServidor = d.ajustes; S.ajustes = { ...S.ajustes, ...d.ajustes }; aplicarAjustes(S.ajustes); }
    S.usuario = d.usuario || "";
    if (d.modo && d.modo.nombre !== S.modo?.nombre) { S.modo = d.modo; $("#modo-txt").textContent = d.modo.texto || "Modo"; if (S.seccion === "ajustes") pintarModos(); }
    S.intenciones = (d.intenciones || []).slice().reverse();
    ponerEstado(d.estado, d.voz);
    recibirMensajes(d.mensajes);
    S.ultimoId = d.ultimo_id;
    S.alarmas = d.alarmas || [];
    S.pendientes = d.pendientes || [];
    pintarEquipo(d.equipo);
    pintarAlarmas(d.alarmas);
    pintarPendientes(d.pendientes);
    pintarHabitos(d.habitos);
    pintarGastos(d.gastos);
    pintarPesados(d.pesados);
    pintarProcesos(d.procesos, d.intenciones);
    S.controles = d.controles;
    if (S.seccion === "mente") pintarControles(d.controles);
    pintarVistazos();
    (d.avisos || []).forEach((a) => aviso(a.texto, a.tipo === "error" ? "error" : a.tipo === "ok" ? "exito" : "info"));
  } catch (e) {
    fallos++;
    if (e.message === "llave") { ponerEstado("desconectado"); $("#estado-txt").textContent = "ábreme desde Arché"; return; }
    if (fallos > 2) { S.conectado = false; ponerEstado("desconectado"); }
  }
  S.t = setTimeout(sondear, document.hidden ? 4000 : 1000);
}

const NOMBRE_ESTADO = { reposo: "en reposo", escuchando: "escuchando", pensando: "pensando…", hablando: "hablando", desconectado: "sin conexión" };
function ponerEstado(est, voz) {
  S.estado = est;
  document.documentElement.dataset.estado = est;
  const t = NOMBRE_ESTADO[est] || est;
  $("#estado-txt").textContent = t;
  $("#estado-pastilla-txt").textContent = t;
  $("#conv-estado").textContent = t;
  $("#pensando").hidden = !(est === "pensando" && S.ajustes.chat_indicador !== false);
  if (voz) $("#btn-voz").classList.toggle("encendido", !!voz.activa);
}

/* =========================================================== hoy */
async function cargarInicio(forzar) {
  if (S.inicio && !forzar && Date.now() - S.inicioTs < 120000) return pintarInicio();
  try { S.inicio = await api("/api/inicio"); S.inicioTs = Date.now(); pintarInicio(); } catch {}
}
function pintarInicio() {
  const d = S.inicio; if (!d) return;
  if ("clima" in d) pintarClima(d.clima, d.ciudad);
  $("#frase").textContent = d.frase || "";
  $("#fechas").innerHTML = (d.fechas || []).map((f) => `<li>${icono("calendario")}<span class="txt">${esc(f.texto)}</span><span class="der">${f.dias === 0 ? "hoy" : f.dias === 1 ? "mañana" : "en " + f.dias + " días"}</span></li>`).join("");
  $("#noticias").innerHTML = (d.noticias || []).length
    ? d.noticias.map((n) => `<li><span class="txt">${esc(n.titulo)}</span><span class="fuente">${esc(n.fuente)}</span></li>`).join("")
    : `<li class="vacio">Sin titulares por ahora.</li>`;
  pintarNotas(d.notas || []);
  pintarVistazos();
}

function pintarClima(c, ciudad) {
  const caja = $("#clima");
  if (!c || c.error) { caja.innerHTML = `<p class="vacio">${esc(c?.error || `No pude traer el clima de ${ciudad}. Revisa la conexión o cambia la ciudad en Ajustes.`)}</p>`; return; }
  if (typeof c === "string") { caja.innerHTML = `<p>${esc(c)}</p>`; return; }
  $("#clima-ciudad").textContent = c.lugar || ciudad;
  const a = c.actual, dias = c.dias || [];
  caja.innerHTML = `<div class="clima-ahora">${icono(iconoClima(a.codigo), "clima-icono")}<strong>${a.temp}°</strong>
      <div><span>${esc(a.estado)}</span><span>Se siente como ${a.sensacion}°</span><span>Humedad ${a.humedad}%, viento ${a.viento} km/h</span></div></div>
    <div class="pronostico">${dias.map((x, i) => {
      const n = i === 0 ? "Hoy" : new Date(x.fecha + "T12:00").toLocaleDateString("es-CO", { weekday: "short" }).replace(".", "");
      return `<div title="${esc(x.estado)}"><span>${esc(n)}</span>${icono(iconoClima(x.codigo), "clima-icono")}<strong>${x.max}°</strong><span>${x.min}°</span><span class="lluvia">${icono("gota")}${x.lluvia}%</span></div>`;
    }).join("")}</div>`;
}

function pintarAlarmas(lista) {
  const k = JSON.stringify(lista); if (k === S._alarmas) return; S._alarmas = k;
  $("#alarmas").innerHTML = lista && lista.length
    ? lista.map((a) => `<li>${icono("campana")}<span class="txt">${esc(a.texto || "Aviso")}<small>${esc(a.describe || a.cuando)}</small></span></li>`).join("")
    : `<li class="vacio">Nada pendiente. Prueba con «recuérdame llamar a mamá a las 6».</li>`;
}

function pintarPendientes(lista) {
  const k = JSON.stringify(lista); if (!lista || k === S._pend) return; S._pend = k;
  const orden = [...lista].sort((a, b) => (a.hecho - b.hecho) || (b.ts - a.ts));
  $("#pendientes").innerHTML = orden.length
    ? orden.map((p) => `<li class="${p.hecho ? "hecho" : ""}"><button class="caja" data-pend="marcar" data-id="${p.id}" aria-label="Marcar">${icono("check")}</button><span class="txt">${esc(p.texto)}</span><button class="ico-btn acc" data-pend="borrar" data-id="${p.id}" aria-label="Borrar">${icono("x")}</button></li>`).join("")
    : `<li class="vacio">Sin pendientes. Escribe uno arriba.</li>`;
  $("#limpiar-hechos").hidden = !lista.some((p) => p.hecho);
  const faltan = lista.filter((p) => !p.hecho).length, ins = $("#insignia-hoy");
  ins.hidden = !faltan; ins.textContent = faltan;
}

function pintarHabitos(lista) {
  const k = JSON.stringify(lista); if (!lista || k === S._hab) return; S._hab = k;
  $("#habitos").innerHTML = lista.length ? lista.map((h) => `<li class="${h.hoy ? "hecho-hoy" : ""}">
      <button class="caja" data-habito="marcar" data-id="${h.id}" aria-label="Hecho hoy">${icono("check")}</button>
      <span class="txt">${esc(h.nombre)}<span class="semana" aria-label="últimos 7 días">${h.semana.map((x) => `<i class="${x ? "si" : ""}"></i>`).join("")}</span></span>
      <span class="racha ${h.racha ? "viva" : ""}" title="días seguidos">${h.racha ? h.racha + (h.racha === 1 ? " día" : " días") : ""}</span>
      <button class="ico-btn acc" data-habito="borrar" data-id="${h.id}" aria-label="Borrar hábito">${icono("x")}</button></li>`).join("")
    : `<li class="vacio">Anota algo que quieras hacer cada día y márcalo cuando lo hagas.</li>`;
}

function pintarGastos(g) {
  const k = JSON.stringify(g); if (!g || k === S._gastos) return; S._gastos = k;
  $("#gasto-hoy").textContent = plata(g.total_hoy);
  $("#gasto-semana-total").textContent = plata(g.total_semana);
  $("#gasto-mes").textContent = plata(g.total_mes);
  const max = Math.max(1, ...g.por_dia.map((d) => d.total));
  const ahora = new Date(), hoy = `${ahora.getFullYear()}-${String(ahora.getMonth() + 1).padStart(2, "0")}-${String(ahora.getDate()).padStart(2, "0")}`;
  $("#gasto-semana").innerHTML = g.por_dia.map((d) => {
    const dia = new Date(d.dia + "T12:00").toLocaleDateString("es-CO", { weekday: "short" }).replace(".", "");
    return `<div class="${d.dia === hoy ? "hoy" : ""}" title="${plata(d.total)}"><i style="height:${Math.max(4, d.total / max * 100)}%"></i><span>${dia}</span></div>`;
  }).join("");
  $("#gastos-hoy").innerHTML = g.hoy.length ? g.hoy.slice().reverse().map((x) => `<li><span class="txt">${esc(x.concepto)}</span><span class="der">${plata(x.valor)}</span><button class="ico-btn acc" data-gasto-borrar="${x.id}" aria-label="Borrar gasto">${icono("x")}</button></li>`).join("")
    : `<li class="vacio">Hoy no has anotado gastos.</li>`;
}

function pintarNotas(notas) {
  S.notas = notas;
  $("#notas").innerHTML = notas.length
    ? notas.map((n) => `<button class="nota" data-nota="${esc(n.nombre)}"><strong>${esc(n.nombre)}</strong><span>${esc(n.texto.slice(0, 220))}</span></button>`).join("")
    : `<p class="vacio">Aún no hay notas. Las que crees aquí también las ve Arché («lee la nota …»).</p>`;
}
function abrirNota(nombre) {
  const n = (S.notas || []).find((x) => x.nombre === nombre);
  $("#nota-nombre").value = n ? n.nombre : "";
  $("#nota-texto").value = n ? n.texto : "";
  $("#nota-nombre").dataset.original = n ? n.nombre : "";
  $("#nota-borrar").hidden = !n;
  $("#editor-nota").hidden = false;
  (n ? $("#nota-texto") : $("#nota-nombre")).focus();
}

/* =========================================================== pomodoro */
const P = guardado("pomodoro", { fase: "foco", fin: 0, restante: 0, corriendo: false, dia: "", hechos: 0 });
function pomoGuardar() { guardar("pomodoro", P); }
function pomoDuracion(fase) { return ((fase === "foco" ? S.ajustes.web_pomodoro_min : S.ajustes.web_descanso_min) || (fase === "foco" ? 25 : 5)) * 60; }
function pomoRestante() { return P.corriendo ? Math.max(0, Math.round((P.fin - Date.now()) / 1000)) : (P.restante || pomoDuracion(P.fase)); }
function pomoRefrescar() {
  const hoy = new Date().toDateString();
  if (P.dia !== hoy) { P.dia = hoy; P.hechos = 0; pomoGuardar(); }
  const r = pomoRestante(), total = pomoDuracion(P.fase);
  $("#pomo-tiempo").textContent = `${String(Math.floor(r / 60)).padStart(2, "0")}:${String(r % 60).padStart(2, "0")}`;
  $("#pomo-fase").textContent = P.fase === "foco" ? "Concentración" : "Descanso";
  $("#pomodoro").classList.toggle("descanso", P.fase !== "foco");
  $("#pomo-iniciar").textContent = P.corriendo ? "Pausar" : r < total ? "Seguir" : "Empezar";
  $("#pomo-saltar").textContent = P.fase === "foco" ? "Ir al descanso" : "Volver a concentrarme";
  $("#pomo-hoy").textContent = P.hechos ? `${P.hechos} ${P.hechos === 1 ? "pomodoro" : "pomodoros"} hoy` : "";
  const cv = $("#pomo-canvas");
  if (cv.offsetParent !== null) {
    const c = cv.getContext("2d"), W = cv.width, css = getComputedStyle(document.documentElement);
    c.clearRect(0, 0, W, W); c.lineCap = "round"; c.lineWidth = 10;
    c.strokeStyle = css.getPropertyValue("--panel2"); c.beginPath(); c.arc(W / 2, W / 2, W / 2 - 14, 0, Math.PI * 2); c.stroke();
    const col = css.getPropertyValue(P.fase === "foco" ? "--a2" : "--ok").trim();
    const prog = 1 - r / total, ang = -Math.PI / 2 + Math.PI * 2 * prog;
    if (prog > 0.002) {
      c.strokeStyle = col; c.shadowColor = col; c.shadowBlur = 18;
      c.beginPath(); c.arc(W / 2, W / 2, W / 2 - 14, -Math.PI / 2, ang); c.stroke(); c.shadowBlur = 0; c.fillStyle = "#fff"; c.beginPath(); c.arc(W / 2 + Math.cos(ang) * (W / 2 - 14), W / 2 + Math.sin(ang) * (W / 2 - 14), 7, 0, 7); c.fill(); }
  }
  document.title = P.corriendo ? `${$("#pomo-tiempo").textContent} · Arché` : "Arché";
  if (P.corriendo && r === 0) pomoTerminar();
}
function pomoTerminar() {
  const eraFoco = P.fase === "foco";
  if (eraFoco) P.hechos++;
  P.fase = eraFoco ? "descanso" : "foco"; P.corriendo = false; P.restante = 0; pomoGuardar();
  aviso(eraFoco ? "Terminaste un pomodoro. Tómate un descanso." : "Se acabó el descanso. ¿Seguimos?", "exito", 12000);
  if (eraFoco) window.mascotaCelebrar?.("¡Pomodoro terminado! Estira un poco.");
  if (S.ajustes.web_pomodoro_sonido !== false) campanita();
  if (S.ajustes.web_pomodoro_arche) enviar(`recuérdame en 1 segundo ${eraFoco ? "tomar un descanso" : "volver a concentrarme"}`, { mostrar: false });
  pomoRefrescar();
}

/* =========================================================== equipo */
function pintarEquipo(e) {
  e = e || {}; S.equipo = e;
  if (typeof e.cpu === "number") { S.historialCPU.push(e.cpu); S.historialRAM.push(e.ram || 0); }
  if (S.historialCPU.length > 180) { S.historialCPU.shift(); S.historialRAM.shift(); }
  if (!(S.seccion === "equipo" && S.pestana.equipo === "rendimiento")) return;
  const ocultar = new Set(S.ajustes.sistema_ocultar || []);
  const lim = { cpu: S.ajustes.limite_cpu || 90, ram: S.ajustes.limite_ram || 90, disco: S.ajustes.limite_disco || 95 };
  const items = [["cpu", "CPU", e.cpu, ""], ["ram", "RAM", e.ram, ""], ["disco", "Disco", e.disco, ""]];
  if (typeof e.bateria === "number") items.push(["bateria", "Batería", e.bateria, e.enchufado ? "cargando" : "con batería"]);
  const colorDe = (k, v) => k === "bateria" ? (v < 20 ? "--alerta" : "--ok") : v >= lim[k] ? "--alerta" : v >= lim[k] - 20 ? "--aten" : "--a1";
  const visibles = items.filter((i) => typeof i[2] === "number" && !ocultar.has(i[0]));
  const cont = $("#medidores");
  if (!visibles.length) { cont.innerHTML = `<p class="vacio">Instala psutil para ver tu equipo: pip install psutil</p>`; return; }
  if (S._medidores !== visibles.map((v) => v[0]).join()) {
    S._medidores = visibles.map((v) => v[0]).join();
    cont.innerHTML = visibles.map(([k]) => `<article class="panel medidor" data-m="${k}"><canvas width="168" height="168"></canvas><div><div class="nombre"></div><div class="valor"></div><div class="det"></div></div></article>`).join("");
  }
  const css = getComputedStyle(document.documentElement);
  for (const [k, n, v, det] of visibles) {
    const el = cont.querySelector(`[data-m="${k}"]`); if (!el) continue;
    el.querySelector(".nombre").textContent = n;
    el.querySelector(".valor").textContent = Math.round(v) + "%";
    el.querySelector(".det").textContent = det || (k !== "bateria" && v >= lim[k] ? "por encima de tu límite" : "");
    dibujarMedidor(el.querySelector("canvas"), v, css.getPropertyValue(colorDe(k, v)).trim());
  }
  pintarGrafica();
}

function dibujarMedidor(cv, v, col) {
  const W = cv.width, c = cv.getContext("2d"), fondo = getComputedStyle(document.documentElement).getPropertyValue("--panel2");
  const r = W / 2 - 12, cx = W / 2, ini = Math.PI * .75, arco = Math.PI * 1.5;
  c.clearRect(0, 0, W, W); c.lineCap = "round"; c.lineWidth = 14;
  c.strokeStyle = fondo; c.beginPath(); c.arc(cx, cx, r, ini, ini + arco); c.stroke();
  c.strokeStyle = col; c.shadowColor = col; c.shadowBlur = 12;
  c.beginPath(); c.arc(cx, cx, r, ini, ini + arco * Math.min(1, Math.max(.01, v / 100))); c.stroke(); c.shadowBlur = 0;
}

function pintarGrafica() {
  const cv = $("#grafica"); if (!cv || cv.offsetParent === null) return;
  const W = cv.clientWidth * devicePixelRatio, H = cv.clientHeight * devicePixelRatio; if (!W) return;
  cv.width = W; cv.height = H;
  const c = cv.getContext("2d"), css = getComputedStyle(document.documentElement), pad = 8 * devicePixelRatio;
  c.strokeStyle = css.getPropertyValue("--borde"); c.lineWidth = 1; c.globalAlpha = .45;
  for (let i = 0; i <= 4; i++) { const y = pad + (H - 2 * pad) * i / 4; c.beginPath(); c.moveTo(0, y); c.lineTo(W, y); c.stroke(); }
  c.globalAlpha = 1;
  const linea = (datos, col) => {
    if (datos.length < 2) return;
    const paso = W / 179, x0 = W - (datos.length - 1) * paso;
    c.beginPath();
    datos.forEach((v, i) => { const x = x0 + i * paso, y = pad + (H - 2 * pad) * (1 - v / 100); i ? c.lineTo(x, y) : c.moveTo(x, y); });
    c.strokeStyle = col; c.lineWidth = 2 * devicePixelRatio; c.lineJoin = "round"; c.stroke();
    c.lineTo(W, H); c.lineTo(x0, H); c.closePath();
    const g = c.createLinearGradient(0, 0, 0, H); g.addColorStop(0, col + "44"); g.addColorStop(1, col + "00");
    c.fillStyle = g; c.fill();
  };
  linea(S.historialRAM, css.getPropertyValue("--a2").trim());
  linea(S.historialCPU, css.getPropertyValue("--a1").trim());
}

function pintarPesados(lista) {
  if (!lista || !(S.seccion === "equipo" && S.pestana.equipo === "rendimiento")) return;
  const k = JSON.stringify(lista); if (k === S._pes) return; S._pes = k;
  const max = Math.max(1, ...lista.map((x) => x.ram_mb));
  $("#pesados").innerHTML = lista.length ? lista.map((x) => {
    const n = x.nombre.replace(/\.exe$/i, "");
    return `<li class="pesado"><span class="txt">${esc(n)}${x.procesos > 1 ? ` <span class="tenue">×${x.procesos}</span>` : ""}
      <span class="barra-mem"><i style="width:${x.ram_mb / max * 100}%"></i></span></span>
      <span class="der">${x.ram_mb >= 1024 ? (x.ram_mb / 1024).toFixed(1) + " GB" : x.ram_mb + " MB"}<br>${x.cpu}% CPU</span>
      <button class="ico-btn acc" data-orden="cierra ${esc(n.toLowerCase())}" data-confirmar="¿Cerrar ${esc(n)}? Si tiene algo sin guardar, se puede perder." aria-label="Cerrar ${esc(n)}">${icono("x")}</button></li>`;
  }).join("") : `<li class="vacio">Instala psutil para ver esto: pip install psutil</li>`;
}

function pintarProcesos(procs, intenc) {
  const k = JSON.stringify([procs, intenc, S.ultimoId]); if (k === S._procs) return; S._procs = k;
  const hp = (procs || []).length
    ? procs.map((p) => `<li><span class="punto ${p.activo ? "on" : ""}"></span><span class="txt">${esc(p.nombre)}${p.cantidad > 1 ? ` ×${p.cantidad}` : ""}<small>${esc(p.detalle || "")}</small></span></li>`).join("")
    : `<li class="vacio">Nada corriendo en segundo plano.</li>`;
  $("#procesos").innerHTML = hp; $("#procesos-2").innerHTML = hp;
  const it = (intenc || []).slice().reverse();
  const fondo = S.mensajes.filter((m) => m.fondo).slice(-15).reverse();
  $("#avisos-fondo").innerHTML = fondo.length ? fondo.map((m) => `<li><span class="txt">${esc(m.t)}<small>${horaCorta(m.ts)}</small></span></li>`).join("") : `<li class="vacio">Nada por ahora.</li>`;
  $("#actividad").innerHTML = it.length ? it.map((i) => `<li><span class="txt">«${esc(i.cmd)}»<small>${esc(i.intencion.replace(/_/g, " "))}${i.via ? ", por " + esc(i.via) : ""}, ${hace(i.ts)}</small></span></li>`).join("")
    : `<li class="vacio">Aún no me has pedido nada en esta sesión.</li>`;
}

async function cargarRutinas() { try { S.rutinas = await api("/api/rutinas"); } catch { S.rutinas = []; } pintarRutinas(); }
function pintarRutinas() {
  $("#rutinas").innerHTML = S.rutinas.length ? S.rutinas.map((r, i) => `<li>
      <button class="ico-btn grande principal-play" data-orden="ejecuta la rutina ${esc(r.nombre)}" aria-label="Ejecutar ${esc(r.nombre)}">${icono("play")}</button>
      <span class="txt"><strong>${esc(r.nombre)}</strong><span class="pasos">${esc(r.pasos.join(", luego "))}</span></span>
      <button class="ico-btn" data-editar-rutina="${i}" aria-label="Editar">${icono("lapiz")}</button></li>`).join("")
    : `<li class="vacio">Sin rutinas. Crea una para hacer varias cosas con un clic.</li>`;
}
function abrirEditorRutina(i) {
  const r = i === null ? { nombre: "", pasos: [] } : S.rutinas[i];
  S.rutinaEditando = i === null ? null : r.nombre;
  $("#rutina-nombre").value = r.nombre; $("#rutina-pasos").value = r.pasos.join("\n");
  $("#rutina-borrar").hidden = i === null;
  $("#editor-rutina").hidden = false; $("#rutina-nombre").focus();
}

/* =========================================================== mente */
async function cargarArche() {
  try { pintarArche(await api("/api/arche")); } catch {}
  clearTimeout(S.tArche);
  if (S.seccion === "mente" && S.pestana.mente === "aprendizaje") S.tArche = setTimeout(cargarArche, 8000);
}
function pintarControles(ctrls) {
  if (!ctrls || !ctrls.length) return;
  const k = JSON.stringify(ctrls); if (k === S._ctrl) return; S._ctrl = k;
  $("#controles").innerHTML = ctrls.map((c) => {
    const ctl = c.tipo === "switch"
      ? `<button class="interruptor ${c.valor ? "on" : ""}" role="switch" aria-checked="${!!c.valor}" aria-label="${esc(c.nombre)}" data-orden="${esc(c.valor ? c.off : c.on)}"></button>`
      : `<div class="segmentos">${c.niveles.map(([n, orden]) => `<button class="${c.valor === n ? "activo" : ""}" data-orden="${esc(orden)}">${esc(n)}</button>`).join("")}</div>`;
    return `<div class="control ${c.trabajando ? "trabajando" : ""}"><div class="info"><strong>${esc(c.nombre)}</strong><span>${esc(c.detalle || "")}</span></div>${ctl}</div>`;
  }).join("");
}
function pintarArche(d) {
  const nube = d.nube || {};
  $("#nube").innerHTML = nube.configurada ? `<p>${esc(`${nube.proveedor || ""} ${nube.modelo || ""}`)}</p><p class="tenue">Modo: ${esc(nube.modo || "")}</p>` : `<p class="vacio">Sin configurar.</p>`;
  const ex = d.examen || {};
  $("#examen").innerHTML = `<div class="cifras"><div><strong>${ex.nivel || 0}</strong><span>nivel</span></div><div><strong>${ex.listos || 0}/${(ex.dominios || []).length}</strong><span>temas listos</span></div><div><strong>${ex.automatico ? "Sí" : "No"}</strong><span>automático</span></div></div>`
    + (ex.dominios || []).slice(0, 10).map((x) => `<div class="barra-h ${x.listo ? "listo" : ""}"><span>${esc(x.nombre)}</span><span class="tenue">${x.listo ? "listo" : `racha ${x.racha} de ${ex.umbral}`}</span><span class="pista"><i style="width:${x.listo ? 100 : Math.min(100, x.racha / (ex.umbral || 4) * 100)}%"></i></span></div>`).join("");
  $("#mejora").innerHTML = (d.mejora || []).length ? d.mejora.map((m) => `<li><span class="txt">${esc(m.texto)}</span><span class="der">${m.ts ? hace(m.ts) : ""}</span></li>`).join("")
    : `<li class="vacio">Todavía nada. Sube el piloto de mejora para que trabaje cuando no me usas.</li>`;
}
/* ---------- redes neuronales: las de verdad, con sus neuronas ---------- */
async function cargarRedes() {
  clearTimeout(S.tRedes);
  if (!(S.seccion === "mente" && S.pestana.mente === "redes")) return;
  try {
    const n = S.ajustes.redes_neuronas || 10;
    const d = await api(`/api/redes?n=${n}` + (S.redClave ? `&clave=${encodeURIComponent(S.redClave)}` : "") + (S.redSeguir ? "&prueba=1" : ""));
    if (S.redSeguir && !d.probando) S.redSeguir = false;
    pintarRedes(d);
    const ocupado = !d.listo || d.probando || d.agregando || d.entreno?.corriendo;
    S.tRedes = setTimeout(cargarRedes, ocupado ? 800 : 4000);
  } catch { S.tRedes = setTimeout(cargarRedes, 4000); }
}
const pct = (p) => Math.round((p || 0) <= 1 ? (p || 0) * 100 : p);
function pintarRedes(d) {
  if (d.error && !d.redes?.length) { $("#redes-lista").innerHTML = `<li class="vacio">${esc(d.error)}</li>`; return; }
  if (!d.listo) { $("#redes-lista").innerHTML = `<li class="vacio">Leyendo las redes… (la primera vez tarda unos segundos)</li>`; return; }
  S.redClave = d.clave;
  const entrenadas = d.redes.filter((r) => r.entrenada).length;
  $("#redes-resumen").textContent = `${entrenadas} de ${d.redes.length} entrenadas`;
  const lk = JSON.stringify([d.redes, d.clave]);
  if (lk !== S._redLista) {
    S._redLista = lk;
    $("#redes-lista").innerHTML = d.redes.map((r) => `<li class="red-item nivel-${r.nivel} ${r.clave === d.clave ? "activa" : ""} ${r.entrenada || r.trivial ? "" : "apagada"}" data-red="${esc(r.clave)}" tabindex="0">
        <span class="punto ${r.entrenada ? "on" : ""}"></span><span class="txt">${esc(r.nombre)}${r.trivial ? "<small>una sola intención, no necesita red</small>" : !r.entrenada ? "<small>sin entrenar</small>" : ""}</span>
        ${r.entrenada ? `<span class="der">${pct(r.precision)}%</span>` : ""}${r.pendientes ? `<em class="pend" title="ejemplos nuevos sin entrenar">+${r.pendientes}</em>` : ""}</li>`).join("");
  }
  const r = d.redes.find((x) => x.clave === d.clave) || {};
  $("#red-nombre").textContent = r.nombre || "Red neuronal";
  $("#red-sub").textContent = r.entrenada ? (r.tipo === "dominios" ? "elige el tema de cada frase" : r.tipo === "subdominios" ? "elige el subtema" : "elige la intención exacta") : "todavía no está entrenada";
  $("#red-cifras").innerHTML = r.entrenada ? `<div><strong>${pct(r.precision)}%</strong><span>precisión</span></div><div><strong>${(r.ejemplos_red || 0).toLocaleString("es-CO")}</strong><span>ejemplos con los que aprendió</span></div><div><strong>${r.forma ? r.forma.ocultas.join(" · ") : "—"}</strong><span>neuronas ocultas</span></div><div><strong>${r.pendientes || 0}</strong><span>ejemplos nuevos sin entrenar</span></div>` : "";
  $("#red-entrenar").hidden = !r.entrenable;
  const ent = d.entreno || {};
  $("#redes-entrenar-todas").disabled = !!ent.corriendo;
  $("#redes-entrenar-todas").lastChild.textContent = ent.corriendo ? `Entrenando ${ent.hecho} de ${ent.total}…` : "Reentrenar todas";
  if (ent.mensaje && ent.mensaje !== S._entMsg) { S._entMsg = ent.mensaje; aviso(ent.mensaje, "info"); }
  S.redDibujo = d.dibujo || null;
  S.redPrueba = d.prueba && d.prueba.activaciones && d.prueba.clave === d.clave ? d.prueba : null;
  $("#red-nota").textContent = d.dibujo ? `Se ven ${d.dibujo.muestras.slice(0, -1).join(", ")} neuronas de ${d.dibujo.capas.slice(0, -1).map((c) => c.real).join(", ")} reales por capa. Azul: peso positivo. Rojo: negativo.` : (r.trivial ? "Esta parte no necesita red: solo hay una intención posible." : "Cuando la entrene, aquí verás sus neuronas.");
  dibujarRed();
  // prueba
  const p = d.prueba;
  $("#prueba").innerHTML = d.probando ? `<p class="vacio">Pensando…</p>` : !p ? `<p class="vacio">Escribe algo y verás qué red decide y con cuánta seguridad.</p>`
    : p.error ? `<p class="vacio">${esc(p.error)}</p>`
    : `<p class="prueba-frase">«${esc(p.frase)}»</p><ol class="camino">${p.pasos.map((x) => `<li><span>${esc(x.nombre)}</span><strong>${esc(x.etiqueta.replace(/_/g, " "))}</strong><em>${pct(x.confianza)}%</em></li>`).join("")}</ol>`
      + (p.probs ? p.probs.map(([c, v]) => `<div class="barra-h"><span>${esc(c.replace(/_/g, " "))}</span><span class="tenue">${pct(v)}%</span><span class="pista"><i style="width:${pct(v)}%"></i></span></div>`).join("") : "");
  // enseñados
  const rs = d.resultados || [];
  $("#ensenados").innerHTML = rs.map((x) => {
    let det = esc(x.mensaje || "");
    if (x.estado === "agregada") det = `aprendida como <strong>${esc((x.intencion || "").replace(/_/g, " "))}</strong>${x.deshecho ? " (deshecha)" : ` <button class="mini" data-red-deshacer="${x.id}">Deshacer</button>`}`;
    if (x.estado === "elegir") det = `¿A cuál va? ${x.opciones.map((o) => `<button class="chip" data-red-elegir="${esc(o)}" data-id="${x.id}">${esc(o.replace(/_/g, " "))}</button>`).join(" ")}`;
    return `<li><span class="txt">«${esc(x.frase)}»<small>${det}</small></span></li>`;
  }).join("");
}

function dibujarRed() {
  const cv = $("#red-canvas"); if (!cv || cv.offsetParent === null) return;
  const W = cv.clientWidth * devicePixelRatio, H = cv.clientHeight * devicePixelRatio; if (!W) return;
  cv.width = W; cv.height = H;
  const c = cv.getContext("2d"), css = getComputedStyle(document.documentElement), d = S.redDibujo;
  c.clearRect(0, 0, W, H);
  if (!d) return;
  const dpr = devicePixelRatio, capas = d.muestras, nC = capas.length;
  const mx = 70 * dpr, my = 26 * dpr, ancho = W - mx * 2, alto = H - my * 2;
  const pos = capas.map((n, i) => Array.from({ length: n }, (_, k) => [mx + ancho * i / (nC - 1), my + (n === 1 ? alto / 2 : alto * k / (n - 1))]));
  const pos_ = S.ajustes.redes_color_pos || "#4aa3ff", neg = S.ajustes.redes_color_neg || "#ff4d6d";
  const visibles = (S.ajustes.redes_conexiones ?? 55) / 100, act = S.redPrueba?.activaciones;
  for (let i = 0; i < nC - 1; i++) {
    const w = d.pesos[i] || [];
    for (let a = 0; a < pos[i].length; a++) for (let b = 0; b < pos[i + 1].length; b++) {
      const v = (w[a] || [])[Math.min(b, (w[a] || []).length - 1)] || 0;
      if (Math.abs(v) < 1 - visibles) continue;
      const brillo = act ? (act[i]?.[a] || 0) * Math.abs(v) : Math.abs(v) * .5;
      c.strokeStyle = v >= 0 ? pos_ : neg; c.globalAlpha = Math.min(.85, .06 + brillo * .7);
      c.lineWidth = (.5 + Math.abs(v) * 1.5) * dpr;
      c.beginPath(); c.moveTo(...pos[i][a]); c.lineTo(...pos[i + 1][b]); c.stroke();
    }
  }
  c.globalAlpha = 1;
  const a2 = css.getPropertyValue("--a2").trim(), panel2 = css.getPropertyValue("--panel2").trim(), texto = css.getPropertyValue("--tenue").trim();
  pos.forEach((capa, i) => capa.forEach(([x, y], k) => {
    const v = act ? (act[i]?.[k] || 0) : 0, r = (i === nC - 1 ? 7 : 5.5) * dpr;
    c.beginPath(); c.arc(x, y, r, 0, 7);
    c.fillStyle = panel2; c.fill();
    if (v > 0) { c.globalAlpha = Math.min(1, .25 + v); c.fillStyle = a2; c.shadowColor = a2; c.shadowBlur = 14 * v * dpr; c.fill(); c.shadowBlur = 0; c.globalAlpha = 1; }
    c.lineWidth = 1.2 * dpr; c.strokeStyle = a2; c.globalAlpha = .55; c.stroke(); c.globalAlpha = 1;
  }));
  c.font = `${11 * dpr}px ${css.getPropertyValue("--fuente")}`; c.fillStyle = texto; c.textBaseline = "middle";
  const ultima = pos[nC - 1];
  d.clases.forEach((cl, k) => { if (ultima[k]) c.fillText(cl.replace(/_/g, " ").slice(0, 22) + (act ? `  ${pct(act[nC - 1]?.[k] || 0)}%` : ""), ultima[k][0] + 12 * dpr, ultima[k][1]); });
  c.textAlign = "center";
  d.capas.forEach((cp, i) => c.fillText(`${cp.nombre} (${cp.real})`, pos[i][0][0], H - 8 * dpr));
}

async function cargarComandos() {
  if (!S.comandos) { try { S.comandos = await api("/api/comandos"); } catch { S.comandos = []; } }
  const actual = S.catCmd || "todos";
  $("#cmd-categorias").innerHTML = ["todos", ...S.comandos.map((g) => g.categoria)].map((c) => `<button class="chip ${c === actual ? "activo" : ""}" data-cat="${esc(c)}">${c === "todos" ? "Todos" : esc(c.charAt(0).toUpperCase() + c.slice(1))}</button>`).join("");
  pintarComandos();
}
function pintarComandos() {
  const f = $("#cmd-filtro").value.trim().toLowerCase(), cat = S.catCmd || "todos";
  const grupos = (S.comandos || []).filter((g) => cat === "todos" || g.categoria === cat).map((g) => ({
    ...g, items: g.items.filter((i) => !f || (i.comando + " " + i.descripcion + " " + i.alias.join(" ")).toLowerCase().includes(f)),
  })).filter((g) => g.items.length);
  $("#lista-comandos").innerHTML = grupos.length ? grupos.map((g) => `<div class="grupo-cmd"><h3>${esc(g.categoria.charAt(0).toUpperCase() + g.categoria.slice(1))}</h3>${g.items.map((i) =>
    `<button class="cmd" data-cmd="${esc(i.comando)}"><strong>${esc(i.comando)}</strong>${i.descripcion ? `<span>${esc(i.descripcion)}</span>` : ""}</button>`).join("")}</div>`).join("")
    : `<p class="vacio">No encontré comandos con «${esc(f)}». Igual puedes pedírmelo con tus palabras.</p>`;
}
function usarComando(cmd) {
  irA("inicio");
  if (/<[^>]+>|\.\.\./.test(cmd)) {
    const t = $("#chat-txt"), limpio = cmd.replace(/\s*<[^>]+>\s*/g, " ").replace(/\s*\.\.\.\s*/g, " ").trim() + " ";
    t.value = limpio; t.focus(); t.setSelectionRange(limpio.length, limpio.length); autoAlto();
  } else enviar(cmd);
}

/* =========================================================== ajustes */
const MUESTRAS = ["#9b6bff", "#5b7cff", "#22d3ee", "#22c55e", "#facc15", "#fb923c", "#f43f5e", "#ec4899", "#e5e7eb"];
const ICONOS = ["rayo", "estrella", "diario", "libro", "musica", "play", "nube", "sol", "luna", "cpu", "pc", "app", "carpeta",
  "nota", "check", "campana", "calendario", "dinero", "casa", "corazon", "voz", "captura", "candado", "escoba", "chat", "arche", "globo"];

async function cargarAjustes() {
  try {
    const d = await api("/api/ajustes");
    Object.assign(S, { temas: d.temas, catalogo: d.catalogo, pers: d.personalizacion, fondos: d.fondos, estilos: d.estilos || [] });
    pintarEstilos(); pintarModos(); pintarTemas(); pintarCatalogo(); pintarFondos(); pintarOrden(); pintarListaBotones();
    if (document.activeElement !== $("#css-propio")) $("#css-propio").value = d.css_propio || "";
    $$("#grupo-fondo [data-aj]").forEach((el) => { el.value = S.ajustes[el.dataset.aj] ?? 0; el.nextElementSibling.textContent = el.value; el.style.setProperty("--p", el.value / el.max * 100 + "%"); });
    $("#aviso-pywebview").textContent = d.pywebview ? "La interfaz se abre en su propia ventana (pywebview está instalado)."
      : "Para que la interfaz tenga su propia ventana instala pywebview: pip install pywebview";
  } catch {}
}

function pintarEstilos() {
  $("#estilos").innerHTML = S.estilos.map((e) => `<button class="estilo-opc" data-estilo="${esc(e.nombre)}"><span class="vista"><i></i><b></b></span><strong>${esc(e.nombre)}</strong><span>${esc(e.descripcion)}</span></button>`).join("");
}
function pintarTemas() {
  const actual = S.ajustes.tema;
  $("#temas").innerHTML = S.temas.map((t) => {
    const [fondo, panel, a1, a2, a3, texto] = t.muestra;
    return `<button class="tema-opc ${t.nombre === actual ? "activo" : ""}" data-tema="${esc(t.nombre)}" aria-pressed="${t.nombre === actual}">
      <span class="vista" style="background:${fondo}"><span class="lado" style="background:${panel}"><i style="background:${texto}"></i><i style="background:${a2}"></i><i style="background:${texto}"></i></span>
      <span class="cuerpo" style="background:radial-gradient(circle at 50% 50%, ${a2}55, transparent 65%)"><i style="background:radial-gradient(circle at 35% 30%, #fffb, transparent 45%), linear-gradient(135deg, ${a1}, ${a2} 55%, ${a3})"></i></span></span>
      <span class="nombre">${esc(t.texto)}${t.propio ? " (tuyo)" : ""}</span></button>`;
  }).join("");
}
function pintarCatalogo() {
  const pers = S.pers || [];
  $("#ajustes-indice").innerHTML = `<a href="#grupo-estilos">Estilos rápidos</a><a href="#grupo-modos">Modos</a><a href="#grupo-temas">Tema</a>`
    + pers.map((s, i) => `<a href="#pers-${i}">${esc(s.seccion)}</a>`).join("")
    + `<a href="#grupo-fondo">Imagen de fondo</a><a href="#grupo-orden">Orden</a><a href="#grupo-botones">Mis botones</a><a href="#grupo-css">Mi estilo (CSS)</a><a href="#grupo-copia">Copia y restablecer</a>`
    + `<a href="#mas-ajustes" class="sub">Más ajustes de Arché</a>`
    + S.catalogo.map((s, i) => `<a href="#grupo-${i}">${esc(s.seccion)}</a>`).join("");
  $("#personalizacion").innerHTML = pers.map((s, i) => `<section class="grupo grupo-aj" id="pers-${i}"><header><h2>${esc(s.seccion)}</h2>
      <button class="mini" data-restablecer="${esc(s.seccion)}">Restablecer</button></header>${s.items.map(htmlAjuste).join("")}</section>`).join("");
  $("#ajustes").innerHTML = S.catalogo.map((s, i) => `<section class="grupo grupo-aj" id="grupo-${i}"><header><h2>${esc(s.seccion)}</h2></header>${s.items.map(htmlAjuste).join("")}</section>`).join("");
  filtrarAjustes();
}
function htmlAjuste(it) {
  const v = it.valor, k = esc(it.clave);
  let ctl = "";
  if (it.tipo === "bool") ctl = `<button class="interruptor ${v ? "on" : ""}" role="switch" aria-checked="${!!v}" data-aj="${k}" data-tipo="bool" aria-label="${esc(it.etiqueta)}"></button>`;
  else if (it.tipo === "int") ctl = `<input type="range" class="deslizador" min="${it.min}" max="${it.max}" value="${v}" data-aj="${k}" data-tipo="int" style="--p:${(v - it.min) / (it.max - it.min) * 100}%" aria-label="${esc(it.etiqueta)}"><span class="num">${v}</span>`;
  else if (it.tipo === "opc") ctl = `<select data-aj="${k}" data-tipo="opc" aria-label="${esc(it.etiqueta)}">${it.opciones.map(([o, e]) => `<option value="${esc(o)}" ${o === v ? "selected" : ""}>${esc(e)}</option>`).join("")}</select>`;
  else if (it.tipo === "hex") ctl = (it.clave.startsWith("web_acento") ? `<span class="muestras">${MUESTRAS.map((m) => `<button class="muestra ${m === v ? "activo" : ""}" style="background:${m}" data-muestra="${m}" data-clave="${k}" aria-label="${m}"></button>`).join("")}</span>` : "")
    + `<input type="color" value="${v || "#888888"}" data-aj="${k}" data-tipo="hex" aria-label="${esc(it.etiqueta)}">${v ? `<button class="mini" data-aj-reset="${k}">Del tema</button>` : `<span class="tenue">del tema</span>`}`;
  else if (it.tipo === "txt") ctl = `<input value="${esc(v)}" maxlength="${it.max}" data-aj="${k}" data-tipo="txt" aria-label="${esc(it.etiqueta)}">`;
  return `<div class="ajuste" data-buscar="${esc((it.etiqueta + " " + (it.ayuda || "") + " " + it.clave).toLowerCase())}">
    <div class="et"><strong>${esc(it.etiqueta)}${it.web ? "" : "<em>ventana clásica</em>"}</strong>${it.ayuda ? `<span>${esc(it.ayuda)}</span>` : ""}</div><div class="ctl">${ctl}</div></div>`;
}
function filtrarAjustes() {
  const f = $("#aj-filtro").value.trim().toLowerCase();
  $$(".ajuste[data-buscar]").forEach((a) => a.classList.toggle("oculto", !!f && !a.dataset.buscar.includes(f)));
  $$(".grupo-aj").forEach((g) => { g.hidden = !g.querySelector(".ajuste:not(.oculto)"); });
  $$(".ajustes-cuerpo > .grupo:not(.grupo-aj)").forEach((g) => { g.hidden = !!f; });
  $("#mas-ajustes").hidden = !!f && !$("#ajustes .ajuste:not(.oculto)");
}
function pintarFondos() {
  const act = S.ajustes.fondo || "";
  $("#fondos").innerHTML = `<label class="fondo-opc subir" for="fondo-archivo">${icono("subir")}<span>Subir imagen</span></label>`
    + `<button class="fondo-opc ${!act ? "activo" : ""}" data-fondo=""><span>Ninguna</span></button>`
    + S.fondos.map((f) => `<button class="fondo-opc ${f === act ? "activo" : ""}" data-fondo="${esc(f)}" style="background-image:url('/fondo/${encodeURIComponent(f)}')"><span>${esc(f)}</span></button>`).join("");
}
function filaOrden(x, i, total, attr, nombre, ic, fija) {
  return `<li class="${x.ver || fija ? "" : "oculta"}">${icono(ic)}<span class="txt">${esc(nombre)}</span>
    <button class="ico-btn" data-${attr}-mover="-1" data-i="${i}" aria-label="Subir" ${i === 0 ? "disabled" : ""}>${icono("arriba")}</button>
    <button class="ico-btn" data-${attr}-mover="1" data-i="${i}" aria-label="Bajar" ${i === total - 1 ? "disabled" : ""}>${icono("abajo")}</button>
    ${fija ? `<span style="width:44px"></span>` : `<button class="interruptor ${x.ver ? "on" : ""}" role="switch" aria-checked="${x.ver}" data-${attr}-ver="${i}" aria-label="Mostrar ${esc(nombre)}"></button>`}</li>`;
}
function pintarOrden() {
  const ls = seccionesOrdenadas(S.ajustes.web_secciones), lh = ordenHoy(S.ajustes.web_hoy_pestanas);
  $("#orden-secciones").innerHTML = `<li class="titulo">Barra lateral</li>` + ls.map((x, i) => filaOrden(x, i, ls.length, "sec", NOMBRE_SECCION[x.id], ICONO_SECCION[x.id], ["inicio", "ajustes"].includes(x.id))).join("");
  $("#orden-hoy").innerHTML = `<li class="titulo">Pestañas de Hoy</li>` + lh.map((x, i) => { const p = PESTANAS.hoy.find((y) => y[0] === x.id); return filaOrden(x, i, lh.length, "hoy", p[1], p[2], false); }).join("");
}
function pintarListaBotones() {
  const l = S.ajustes.web_botones || [];
  $("#lista-botones").innerHTML = l.length ? l.map((b, i) => `<li>${icono(b.icono || "rayo")}<span class="txt">${esc(b.texto)}<small>${esc(b.orden)}</small></span>
      <button class="ico-btn" data-bot-mover="-1" data-i="${i}" aria-label="Subir" ${i === 0 ? "disabled" : ""}>${icono("arriba")}</button>
      <button class="ico-btn" data-bot-mover="1" data-i="${i}" aria-label="Bajar" ${i === l.length - 1 ? "disabled" : ""}>${icono("abajo")}</button>
      <button class="ico-btn" data-editar-boton="${i}" aria-label="Editar">${icono("lapiz")}</button></li>`).join("")
    : `<li class="vacio">Aún no tienes botones.</li>`;
}
function abrirEditorBoton(i) {
  const b = i === null ? { texto: "", orden: S.ultimaOrden || "", icono: "rayo" } : (S.ajustes.web_botones || [])[i];
  S.botonEditando = i;
  $("#boton-texto").value = b.texto; $("#boton-orden").value = b.orden;
  S.iconoElegido = b.icono || "rayo";
  $("#boton-iconos").innerHTML = ICONOS.map((n) => `<button type="button" class="${n === S.iconoElegido ? "activo" : ""}" data-icono="${n}" aria-label="${n}">${icono(n)}</button>`).join("");
  $("#boton-borrar").hidden = i === null;
  $("#editor-boton").hidden = false; $("#boton-texto").focus();
}
async function guardarBoton() {
  const texto = $("#boton-texto").value.trim(), orden = $("#boton-orden").value.trim();
  if (!texto) return $("#boton-texto").focus();
  if (!orden) return $("#boton-orden").focus();
  const lista = [...(S.ajustes.web_botones || [])], nuevo = { texto, orden, icono: S.iconoElegido };
  if (S.botonEditando === null) lista.push(nuevo); else lista[S.botonEditando] = nuevo;
  $("#editor-boton").hidden = true;
  await fijarAjuste("web_botones", lista);
  aviso(`Botón «${texto}» guardado.`, "exito", 2000);
}
function mover(lista, i, paso) { const l = lista.map((x) => ({ ...x })); const j = i + paso; if (j < 0 || j >= l.length) return l; [l[i], l[j]] = [l[j], l[i]]; return l; }
/* =========================================================== esfera (la cara de Arché) */
const ORBES = [];
function registrarOrbe(cv, grande) { ORBES.push({ cv, grande, chispas: [] }); }

function hexRgb(h) { h = (h || "#888888").replace("#", ""); return [0, 2, 4].map((i) => parseInt(h.substr(i, 2), 16)); }
function rgba(h, a) { const [r, g, b] = hexRgb(h); return `rgba(${r},${g},${b},${a})`; }

function dibujarOrbe(o, t) {
  const cv = o.cv, W = cv.width, H = cv.height, c = cv.getContext("2d");
  const a = S.ajustes, col = S.colores || {};
  const est = S.estado, estilo = a.estilo_voz || "esfera";
  const vel = (a.orbe_velocidad || 100) / 100, brillo = (a.efecto_brillo ?? 60) / 100;
  const tam = (a.orbe_tamano || 100) / 100;
  const ritmo = { reposo: .5, escuchando: 1.1, pensando: 1.6, hablando: 3.2, desconectado: .2 }[est] || .5;
  const amp = { reposo: .03, escuchando: .06, pensando: .05, hablando: .12, desconectado: 0 }[est] || .03;
  const tt = t / 1000 * vel;
  const pa = S.colorEsfera || {};
  const cA = a.orbe_color || pa.a || col.azul || "#2f4fd1", cB = pa.b || col.morado || "#6b34c9", cC = col.rojo || "#b81f45";
  const cAc = a.orbe_color || pa.a || col.azul_claro || "#5b7cff", cBc = pa.b || col.morado_claro || "#9b6bff";
  const cx = W / 2, cy = H / 2, R = Math.min(W, H) * .30 * Math.min(1.25, tam) * (1 + Math.sin(tt * ritmo * 2) * amp);
  c.clearRect(0, 0, W, H);
  if (est === "desconectado") c.globalAlpha = .45;

  // halo
  const halo = c.createRadialGradient(cx, cy, R * .6, cx, cy, R * 1.65);
  halo.addColorStop(0, rgba(est === "hablando" ? cC : est === "pensando" ? cBc : cAc, .35 * brillo));
  halo.addColorStop(1, rgba(cB, 0));
  c.fillStyle = halo; c.beginPath(); c.arc(cx, cy, R * 1.65, 0, Math.PI * 2); c.fill();

  if (estilo === "ondas") {
    for (let k = 0; k < 3; k++) {
      c.beginPath();
      for (let x = 0; x <= W; x += W / 120) {
        const u = (x - cx) / (R * 1.4), env = Math.max(0, 1 - u * u);
        const y = cy + Math.sin(x / W * 12 + tt * ritmo * 3 + k * 2) * R * (.12 + amp * 4) * env * (1 - k * .25);
        x ? c.lineTo(x, y) : c.moveTo(x, y);
      }
      c.strokeStyle = rgba([cAc, cBc, cC][k], .85 - k * .2); c.lineWidth = (o.grande ? 4 : 2.5) - k * .6; c.stroke();
    }
  } else if (estilo === "anillos") {
    for (let k = 0; k < 4; k++) {
      const f = ((tt * ritmo * .4 + k / 4) % 1);
      c.beginPath(); c.arc(cx, cy, R * (.35 + f * .9), 0, Math.PI * 2);
      c.strokeStyle = rgba(k % 2 ? cBc : cAc, (1 - f) * .9); c.lineWidth = o.grande ? 3 : 2; c.stroke();
    }
    esferaBase(c, cx, cy, R * .38, cA, cB, cC, tt, ritmo);
  } else if (estilo === "nucleo") {
    esferaBase(c, cx, cy, R * .45, cA, cB, cC, tt, ritmo);
    for (let k = 0; k < 9; k++) {
      const ang = tt * ritmo * (k % 2 ? 1 : -1) * .8 + k * 2.1, rr = R * (.7 + (k % 3) * .17);
      const x = cx + Math.cos(ang) * rr, y = cy + Math.sin(ang) * rr * .55;
      c.fillStyle = rgba(k % 3 === 0 ? cC : k % 3 === 1 ? cAc : cBc, .9);
      c.beginPath(); c.arc(x, y, (o.grande ? 4 : 2.5) * (1 + (y - cy) / (R * 2)), 0, Math.PI * 2); c.fill();
    }
  } else if (estilo === "geometrica") {
    const lados = 6, capas = 3;
    for (let k = 0; k < capas; k++) {
      c.beginPath();
      for (let i = 0; i <= lados; i++) {
        const ang = i / lados * Math.PI * 2 + tt * ritmo * .3 * (k % 2 ? -1 : 1);
        const rr = R * (1 - k * .25) * (1 + Math.sin(tt * ritmo * 2 + i) * amp);
        const x = cx + Math.cos(ang) * rr, y = cy + Math.sin(ang) * rr;
        i ? c.lineTo(x, y) : c.moveTo(x, y);
      }
      c.strokeStyle = rgba([cAc, cBc, cC][k], .9); c.lineWidth = o.grande ? 2.5 : 1.8; c.stroke();
    }
  } else {
    esferaBase(c, cx, cy, R, cA, cB, cC, tt, ritmo, est === "hablando" ? amp : amp * .6);
    if (est === "pensando") {
      c.beginPath(); c.arc(cx, cy, R * 1.18, tt * 3, tt * 3 + Math.PI * .6);
      c.strokeStyle = rgba(cBc, .9); c.lineWidth = o.grande ? 3 : 2; c.lineCap = "round"; c.stroke();
    }
    if (est === "escuchando") {
      const f = (tt * 1.2) % 1;
      c.beginPath(); c.arc(cx, cy, R * (1.05 + f * .5), 0, Math.PI * 2);
      c.strokeStyle = rgba(cAc, (1 - f) * .7); c.lineWidth = 2; c.stroke();
    }
  }

  // chispas
  const n = Math.round(((a.efecto_particulas || 0) / 100) * (o.grande ? 40 : 10));
  while (o.chispas.length < n) o.chispas.push({ a: Math.random() * 6.28, r: 1.1 + Math.random() * .6, v: .2 + Math.random() * .6, s: Math.random() });
  o.chispas.length = n;
  for (const p of o.chispas) {
    p.a += .004 * p.v * ritmo * vel * 4;
    const x = cx + Math.cos(p.a) * R * p.r, y = cy + Math.sin(p.a) * R * p.r;
    c.fillStyle = rgba(p.s > .5 ? cAc : cBc, .5 + .5 * Math.sin(tt * 3 + p.s * 9));
    c.beginPath(); c.arc(x, y, o.grande ? 2 : 1.2, 0, Math.PI * 2); c.fill();
  }
  c.globalAlpha = 1;
}

function esferaBase(c, cx, cy, R, cA, cB, cC, tt, ritmo, onda = 0.03) {
  c.save();
  c.beginPath();
  const pasos = 90;
  for (let i = 0; i <= pasos; i++) {
    const ang = i / pasos * Math.PI * 2;
    const rr = R * (1 + Math.sin(ang * 3 + tt * ritmo * 2.2) * onda * .6 + Math.sin(ang * 5 - tt * ritmo * 1.7) * onda * .4);
    const x = cx + Math.cos(ang) * rr, y = cy + Math.sin(ang) * rr;
    i ? c.lineTo(x, y) : c.moveTo(x, y);
  }
  c.closePath(); c.clip();
  // cuerpo: azul -> morado -> rojo girando despacio (la firma de Arché)
  const g = c.createLinearGradient(cx + Math.cos(tt * .4) * R, cy + Math.sin(tt * .4) * R, cx - Math.cos(tt * .4) * R, cy - Math.sin(tt * .4) * R);
  g.addColorStop(0, cA); g.addColorStop(.55, cB); g.addColorStop(1, cC);
  c.fillStyle = g; c.fillRect(cx - R * 1.3, cy - R * 1.3, R * 2.6, R * 2.6);
  // bandas internas
  for (let k = 0; k < 3; k++) {
    const y = cy + Math.sin(tt * ritmo * .7 + k * 2) * R * .5;
    const b = c.createRadialGradient(cx + Math.cos(tt * .6 + k) * R * .4, y, 0, cx, y, R * .9);
    b.addColorStop(0, "rgba(255,255,255,.18)"); b.addColorStop(1, "rgba(255,255,255,0)");
    c.fillStyle = b; c.fillRect(cx - R * 1.3, cy - R * 1.3, R * 2.6, R * 2.6);
  }
  // luz y sombra (volumen)
  const luz = c.createRadialGradient(cx - R * .35, cy - R * .4, R * .05, cx, cy, R * 1.05);
  luz.addColorStop(0, "rgba(255,255,255,.55)"); luz.addColorStop(.35, "rgba(255,255,255,.05)"); luz.addColorStop(1, "rgba(0,0,0,.45)");
  c.fillStyle = luz; c.fillRect(cx - R * 1.3, cy - R * 1.3, R * 2.6, R * 2.6);
  c.restore();
}

/* =========================================================== escena de fondo */
const ESC = { puntos: [] };
function dibujarEscena(t) {
  const cv = $("#escena"), a = S.ajustes, tipo = a.escena || "ninguna";
  if (tipo === "ninguna") { if (ESC.tipo !== tipo) { cv.getContext("2d").clearRect(0, 0, cv.width, cv.height); ESC.tipo = tipo; } return; }
  ESC.tipo = tipo;
  const W = innerWidth, H = innerHeight;
  if (cv.width !== W || cv.height !== H) { cv.width = W; cv.height = H; }
  const c = cv.getContext("2d"), col = S.colores || {}, inten = (a.escena_intensidad ?? 50) / 100;
  const vel = (a.escena_velocidad || 100) / 100, luz = (a.escena_brillo ?? 60) / 100, tt = t / 1000 * vel;
  c.clearRect(0, 0, W, H);
  if (tipo === "gradiente" || tipo === "nebulosa") {
    const manchas = tipo === "nebulosa" ? 5 : 3;
    for (let i = 0; i < manchas; i++) {
      const x = W * (.5 + .4 * Math.sin(tt * .07 + i * 2.1)), y = H * (.5 + .4 * Math.cos(tt * .05 + i * 1.7));
      const r = Math.max(W, H) * (tipo === "nebulosa" ? .35 : .55);
      const g = c.createRadialGradient(x, y, 0, x, y, r);
      g.addColorStop(0, rgba([col.azul, col.morado, col.rojo][i % 3] || "#444", .22 * inten * luz * 1.6));
      g.addColorStop(1, "rgba(0,0,0,0)");
      c.fillStyle = g; c.fillRect(0, 0, W, H);
    }
  }
  if (tipo === "particulas" || tipo === "nebulosa") {
    const n = Math.round(30 + inten * 90);
    while (ESC.puntos.length < n) ESC.puntos.push({ x: Math.random() * W, y: Math.random() * H, v: .2 + Math.random(), r: Math.random() * 1.6 + .4 });
    ESC.puntos.length = n;
    for (const p of ESC.puntos) {
      p.y -= p.v * .3 * vel; if (p.y < -5) { p.y = H + 5; p.x = Math.random() * W; }
      c.fillStyle = rgba(col.azul_claro || "#88f", .35 * luz + .2 * Math.sin(tt + p.x));
      c.beginPath(); c.arc(p.x, p.y, p.r, 0, 6.28); c.fill();
    }
  }
  if (tipo === "ondas") {
    for (let k = 0; k < 4; k++) {
      c.beginPath();
      for (let x = 0; x <= W; x += 12) { const y = H * (.55 + k * .08) + Math.sin(x / 220 + tt * .6 + k) * 40 * inten; x ? c.lineTo(x, y) : c.moveTo(x, y); }
      c.strokeStyle = rgba([col.azul_claro, col.morado_claro, col.rojo_claro, col.azul_claro][k] || "#88f", .18 * luz); c.lineWidth = 1.5; c.stroke();
    }
  }
  if (tipo === "rejilla") {
    const paso = 46, off = (tt * 12) % paso;
    c.strokeStyle = rgba(col.morado_claro || "#88f", .07 * luz + .08 * inten); c.lineWidth = 1;
    c.beginPath();
    for (let x = -off; x < W; x += paso) { c.moveTo(x, 0); c.lineTo(x, H); }
    for (let y = -off; y < H; y += paso) { c.moveTo(0, y); c.lineTo(W, y); }
    c.stroke();
  }
}

/* ondas de voz encima de la conversación: se mueven según lo que hace Arché */
const ONDA = { amp: 0.15 };
function dibujarOndasConv(t) {
  const cv = $("#ondas-conv"); if (!cv || cv.offsetParent === null) return;
  const modo = S.ajustes.web_ondas_chat || "siempre";
  const activo = S.estado === "hablando" || S.estado === "pensando" || S.estado === "escuchando";
  cv.classList.toggle("apagada", modo === "nunca" || (modo === "hablando" && !activo));
  if (cv.classList.contains("apagada")) return;
  const W = cv.clientWidth * devicePixelRatio, H = cv.clientHeight * devicePixelRatio; if (!W) return;
  if (cv.width !== W || cv.height !== H) { cv.width = W; cv.height = H; }
  const c = cv.getContext("2d"), col = S.colores || {}, pa = S.colorEsfera || {};
  const objetivo = { hablando: 1, pensando: .45, escuchando: .6, reposo: .22, desconectado: .03 }[S.estado] ?? .22;
  ONDA.amp += (objetivo - ONDA.amp) * .06;
  const vel = { hablando: 3.4, pensando: 1.8, escuchando: 2.2 }[S.estado] || .9;
  const tt = t / 1000 * vel * ((S.ajustes.orbe_velocidad || 100) / 100);
  c.clearRect(0, 0, W, H);
  const colores = [pa.a || col.azul_claro || "#5b7cff", pa.b || col.morado_claro || "#9b6bff", col.rojo_claro || "#e0435f"];
  for (let k = 0; k < 3; k++) {
    c.beginPath();
    for (let x = 0; x <= W; x += 3 * devicePixelRatio) {
      const u = x / W, env = Math.sin(Math.PI * u) ** 2;
      const y = H / 2 + env * H * .42 * ONDA.amp * (Math.sin(u * (9 + k * 3) + tt * (1.4 + k * .35) + k * 2) * .7 + Math.sin(u * 23 - tt * 2.1 + k) * .3) * (1 - k * .22);
      x ? c.lineTo(x, y) : c.moveTo(x, y);
    }
    const g = c.createLinearGradient(0, 0, W, 0);
    g.addColorStop(0, "rgba(0,0,0,0)"); g.addColorStop(.2, colores[k]); g.addColorStop(.8, colores[(k + 1) % 3]); g.addColorStop(1, "rgba(0,0,0,0)");
    c.strokeStyle = g; c.lineWidth = (2.8 - k * .6) * devicePixelRatio; c.globalAlpha = .95 - k * .2;
    c.shadowColor = colores[k]; c.shadowBlur = 10 * devicePixelRatio * ONDA.amp; c.stroke();
  }
  c.globalAlpha = 1; c.shadowBlur = 0;
}

let ultimoCuadro = 0;
function animar(t) {
  const reducido = S.ajustes.reducir_movimiento;
  const intervalo = reducido ? 500 : document.hidden ? 1000 : 33;
  if (t - ultimoCuadro >= intervalo) {
    ultimoCuadro = t;
    for (const o of ORBES) if (o.cv.offsetParent !== null) dibujarOrbe(o, reducido ? 0 : t);
    dibujarOndasConv(reducido ? 0 : t);
    if (!reducido) dibujarEscena(t); else dibujarEscena(0);
  }
  requestAnimationFrame(animar);
}


/* =========================================================== modos */
async function cargarModos() { try { S.modos = await api("/api/modos"); } catch { S.modos = { lista: [] }; } return S.modos; }
async function activarModo(nombre) {
  const r = await api("/api/modo", { nombre });
  if (!r.ok) return aviso(r.error, "error");
  S.ajustesServidor = null; S.tema = null; await sondear();
  aviso(`Modo ${r.modo} activado.`, "exito", 2500);
  window.mascotaCelebrar?.();
  if (S.seccion === "ajustes") cargarAjustes();
}
async function abrirMenuModos() {
  const m = $("#menu-modos");
  if (!m.hidden) { m.hidden = true; return; }
  const d = await cargarModos(), r = $("#modo-chip").getBoundingClientRect();
  m.innerHTML = d.lista.map((x) => `<button role="menuitem" data-modo="${esc(x.nombre)}" class="${x.nombre === d.activo ? "activo" : ""}"><strong>${esc(x.texto)}</strong><span>${esc(x.descripcion || "")}</span></button>`).join("");
  m.style.top = r.bottom + 8 + "px"; m.style.right = innerWidth - r.right + "px";
  m.hidden = false;
}
async function pintarModos() {
  const d = await cargarModos();
  $("#modos").innerHTML = d.lista.map((x) => `<button class="modo-opc ${x.nombre === d.activo ? "activo" : ""}" data-modo="${esc(x.nombre)}"><strong>${esc(x.texto)}</strong><span>${esc(x.descripcion || "")}</span></button>`).join("");
}

/* =========================================================== búsqueda (Ctrl+K) */
const DESTINOS = [["inicio", null, "Ir a Arché (conversación)"], ["hoy", "tareas", "Ver pendientes y recordatorios"], ["hoy", "enfoque", "Abrir el pomodoro"],
  ["hoy", "dinero", "Ver gastos"], ["hoy", "notas", "Ver notas"], ["hoy", "mundo", "Ver el clima y titulares"], ["equipo", "controles", "Controles del equipo"],
  ["equipo", "rendimiento", "Cómo va el equipo"], ["equipo", "rutinas", "Mis rutinas"], ["mente", "trabajo", "Cómo trabajo (voz, autonomía…)"],
  ["mente", "aprendizaje", "Lo que he aprendido"], ["mente", "sabe", "Todo lo que sé hacer"], ["ajustes", null, "Abrir los ajustes"], ["mente", "redes", "Ver mis redes neuronales"]];
let paletaSel = 0, paletaItems = [];
async function abrirPaleta() {
  if (!S.comandos) { try { S.comandos = await api("/api/comandos"); } catch { S.comandos = []; } }
  if (!S.modos) await cargarModos();
  $("#paleta").hidden = false; $("#paleta-txt").value = ""; filtrarPaleta(); $("#paleta-txt").focus();
}
function cerrarPaleta() { $("#paleta").hidden = true; }
function filtrarPaleta() {
  const f = $("#paleta-txt").value.trim().toLowerCase(), items = [];
  if (f) items.push({ tipo: "orden", texto: $("#paleta-txt").value.trim(), sub: "Pedírselo a Arché tal cual" });
  (S.ajustes.web_botones || []).filter((b) => !f || (b.texto + " " + b.orden).toLowerCase().includes(f)).forEach((b) => items.push({ tipo: "orden", texto: b.orden, sub: "Mi botón: " + b.texto }));
  DESTINOS.filter(([, , e]) => !f || e.toLowerCase().includes(f)).forEach(([s, p, e]) => items.push({ tipo: "ir", texto: e, sec: s, pes: p }));
  (S.modos?.lista || []).filter((x) => !f || ("modo " + x.texto + " " + x.nombre).toLowerCase().includes(f)).slice(0, f ? 7 : 0).forEach((x) => items.push({ tipo: "modo", texto: "Modo " + x.texto, sub: x.descripcion, nombre: x.nombre }));
  if (!f || "recorrido guia mascota ayuda".includes(f)) items.push({ tipo: "recorrido", texto: "Hacer el recorrido con la mascota", sub: "Te muestra cada parte de la interfaz" });
  S.historialOrdenes.filter((x) => !f || x.toLowerCase().includes(f)).slice(0, f ? 4 : 5).forEach((x) => items.push({ tipo: "orden", texto: x, sub: "Lo pediste antes" }));
  if (f) for (const g of S.comandos || []) for (const i of g.items) {
    if ((i.comando + " " + i.descripcion).toLowerCase().includes(f)) items.push({ tipo: "cmd", texto: i.comando, sub: i.descripcion || g.categoria });
    if (items.length > 40) break;
  }
  paletaItems = items.slice(0, 40); paletaSel = 0; pintarPaleta();
}
function pintarPaleta() {
  $("#paleta-res").innerHTML = paletaItems.map((it, i) => `<li class="${i === paletaSel ? "sel" : ""}" data-i="${i}">${esc(it.texto)}${it.sub ? `<small>${esc(it.sub)}</small>` : ""}</li>`).join("");
  $("#paleta-res .sel")?.scrollIntoView({ block: "nearest" });
}
function usarPaleta(i) {
  const it = paletaItems[i]; if (!it) return;
  cerrarPaleta();
  if (it.tipo === "ir") irA(it.sec, it.pes);
  else if (it.tipo === "modo") activarModo(it.nombre);
  else if (it.tipo === "recorrido") { if (!S.ajustes.mascota) fijarAjuste("mascota", true); setTimeout(() => window.mascotaRecorrido?.(), 300); }
  else if (it.tipo === "cmd") usarComando(it.texto);
  else enviar(it.texto);
}

function autoAlto() { const t = $("#chat-txt"); t.style.height = "auto"; t.style.height = Math.min(180, t.scrollHeight + 2) + "px"; }

/* =========================================================== eventos */
function conectar() {
  $("#nav").addEventListener("click", (e) => { const b = e.target.closest("button[data-sec]"); if (b) irA(b.dataset.sec); });
  $(".rail-marca").addEventListener("click", () => irA("inicio"));
  $("#pestanas").addEventListener("click", (e) => { const b = e.target.closest("[data-pestana-ir]"); if (b) mostrarPestana(S.seccion, b.dataset.pestanaIr); });

  document.addEventListener("click", async (e) => {
    const q = (s) => e.target.closest(s);
    let el;
    if ((el = q("[data-editar-boton]"))) { e.stopPropagation(); return abrirEditorBoton(+el.dataset.editarBoton); }
    if ((el = q("[data-icono]"))) { S.iconoElegido = el.dataset.icono; $$("#boton-iconos button").forEach((b) => b.classList.toggle("activo", b === el)); return; }
    if ((el = q("[data-grupo]"))) { S.gruposAbiertos = S.gruposAbiertos || new Set(); const g = +el.dataset.grupo; S.gruposAbiertos.has(g) ? S.gruposAbiertos.delete(g) : S.gruposAbiertos.add(g); return pintarChat(); }
    if ((el = q("[data-red]"))) { S.redClave = el.dataset.red; S._redDib = null; return cargarRedes(); }
    if ((el = q("[data-red-elegir]"))) { await api("/api/redes", { accion: "elegir", id: +el.dataset.id, intencion: el.dataset.redElegir }); return cargarRedes(); }
    if ((el = q("[data-red-deshacer]"))) { await api("/api/redes", { accion: "deshacer", id: +el.dataset.redDeshacer }); return cargarRedes(); }
    if ((el = q("[data-vistazo]"))) { const d = el.dataset.vistazo; return d === "rendimiento" ? irA("equipo", d) : irA("hoy", d); }
    if ((el = q("[data-orden]"))) {
      if (el.dataset.confirmar && !(await confirmar(el.dataset.confirmar))) return;
      enviar(el.dataset.orden);
      if (el.classList.contains("interruptor")) el.classList.toggle("on");
      return;
    }
    if ((el = q("[data-pedir]"))) { irA("inicio"); const t = $("#chat-txt"); t.value = el.dataset.pedir; t.focus(); return; }
    if ((el = q("[data-pend]"))) { if (el.dataset.pend === "marcar" && !el.closest("li").classList.contains("hecho")) window.mascotaCelebrar?.("¡Uno menos!"); const r = await api("/api/pendiente", { accion: el.dataset.pend, id: +el.dataset.id }); S._pend = null; S.pendientes = r.pendientes; pintarPendientes(r.pendientes); pintarVistazos(); return; }
    if ((el = q("[data-habito]"))) { if (el.dataset.habito === "marcar" && !el.closest("li").classList.contains("hecho-hoy")) window.mascotaCelebrar?.("¡Bien! Sigue la racha."); const r = await api("/api/habito", { accion: el.dataset.habito, id: +el.dataset.id }); S._hab = null; pintarHabitos(r.habitos); return; }
    if ((el = q("[data-gasto-borrar]"))) { const r = await api("/api/gasto", { accion: "borrar", id: +el.dataset.gastoBorrar }); S._gastos = null; pintarGastos(r.gastos); return; }
    if ((el = q("[data-nota]"))) return abrirNota(el.dataset.nota);
    if ((el = q("[data-copiar]"))) { const m = S.mensajes.find((x) => x.id === +el.dataset.copiar); if (m) { navigator.clipboard?.writeText(m.t); aviso("Copiado.", "exito", 1500); } return; }
    if ((el = q("[data-cmd]"))) return usarComando(el.dataset.cmd);
    if ((el = q("[data-cat]"))) { S.catCmd = el.dataset.cat; cargarComandos(); return; }
    if ((el = q("[data-editar-rutina]"))) return abrirEditorRutina(+el.dataset.editarRutina);
    if ((el = q("[data-modo]"))) { $("#menu-modos").hidden = true; return activarModo(el.dataset.modo); }
    if (!e.target.closest("#menu-modos, #modo-chip")) $("#menu-modos").hidden = true;
    if ((el = q("[data-estilo]"))) {
      const r = await api("/api/estilo", { nombre: el.dataset.estilo });
      if (r.ok) { S.ajustesServidor = null; await sondear(); cargarAjustes(); aviso(`Estilo «${el.dataset.estilo}» aplicado.`, "exito", 2500); }
      return;
    }
    if ((el = q("[data-tema]"))) { S.ajustes.tema = el.dataset.tema; pintarTemas(); fijarAjuste("tema", el.dataset.tema); return; }
    if ((el = q("[data-muestra]"))) { fijarAjuste(el.dataset.clave, el.dataset.muestra).then(cargarAjustes); return; }
    if ((el = q("[data-aj-reset]"))) { await fijarAjuste(el.dataset.ajReset, ""); cargarAjustes(); return; }
    if ((el = q("[data-fondo]"))) { await fijarAjuste("fondo", el.dataset.fondo); pintarFondos(); return; }
    if ((el = q("[data-sec-mover]"))) return fijarAjuste("web_secciones", mover(seccionesOrdenadas(S.ajustes.web_secciones), +el.dataset.i, +el.dataset.secMover));
    if ((el = q("[data-sec-ver]"))) { const l = seccionesOrdenadas(S.ajustes.web_secciones); l[+el.dataset.secVer].ver = !l[+el.dataset.secVer].ver; return fijarAjuste("web_secciones", l); }
    if ((el = q("[data-hoy-mover]"))) return fijarAjuste("web_hoy_pestanas", mover(ordenHoy(S.ajustes.web_hoy_pestanas), +el.dataset.i, +el.dataset.hoyMover));
    if ((el = q("[data-hoy-ver]"))) {
      const l = ordenHoy(S.ajustes.web_hoy_pestanas); l[+el.dataset.hoyVer].ver = !l[+el.dataset.hoyVer].ver;
      if (!l.some((x) => x.ver)) return aviso("Deja al menos una pestaña en Hoy.", "info");
      return fijarAjuste("web_hoy_pestanas", l);
    }
    if ((el = q("[data-bot-mover]"))) return fijarAjuste("web_botones", mover(S.ajustes.web_botones || [], +el.dataset.i, +el.dataset.botMover));
    if ((el = q("[data-restablecer]"))) {
      const sec = el.dataset.restablecer, todo = sec === "__todo__";
      if (!(await confirmar(todo ? "¿Volver todo el aspecto a como venía de fábrica? Tus botones, notas y pendientes no se tocan." : sec === "__orden__" ? "¿Volver al orden de fábrica?" : `¿Restablecer «${sec}»?`))) return;
      await api("/api/restablecer", { seccion: todo ? null : sec });
      S.ajustesServidor = null; await sondear(); cargarAjustes(); aviso("Listo, restablecido.", "exito", 2500); return;
    }
    if ((el = q('[data-aj][data-tipo="bool"]'))) { const on = !el.classList.contains("on"); el.classList.toggle("on", on); el.setAttribute("aria-checked", on); fijarAjuste(el.dataset.aj, on); return; }
    if ((el = q("#paleta-res li[data-i]"))) return usarPaleta(+el.dataset.i);
  });

  document.addEventListener("input", (e) => {
    const el = e.target;
    if (el.matches('[data-aj][data-tipo="int"]')) {
      el.nextElementSibling.textContent = el.value;
      el.style.setProperty("--p", (el.value - el.min) / (el.max - el.min) * 100 + "%");
      clearTimeout(el._t); el._t = setTimeout(() => fijarAjuste(el.dataset.aj, +el.value), 200);
    }
    if (el.matches('[data-aj][data-tipo="hex"]')) { clearTimeout(el._t); el._t = setTimeout(() => fijarAjuste(el.dataset.aj, el.value), 200); }
  });
  document.addEventListener("change", (e) => {
    const el = e.target;
    if (el.matches('[data-aj][data-tipo="opc"]')) fijarAjuste(el.dataset.aj, el.value);
    if (el.matches('[data-aj][data-tipo="txt"]')) fijarAjuste(el.dataset.aj, el.value).then(() => { if (el.dataset.aj === "web_ciudad") cargarInicio(true); });
  });

  // conversación
  $("#form-chat").addEventListener("submit", (e) => { e.preventDefault(); const t = $("#chat-txt"); enviar(t.value, { mostrar: false }); t.value = ""; autoAlto(); });
  const ta = $("#chat-txt");
  ta.addEventListener("input", autoAlto);
  ta.addEventListener("keydown", (e) => {
    if (e.key === "Enter" && !e.shiftKey && (S.ajustes.web_enter_envia !== false || e.ctrlKey)) { e.preventDefault(); $("#form-chat").requestSubmit(); }
    if ((e.key === "ArrowUp" || e.key === "ArrowDown") && (!ta.value || S.posHist >= 0)) {
      e.preventDefault();
      S.posHist = Math.max(-1, Math.min(S.historialOrdenes.length - 1, S.posHist + (e.key === "ArrowUp" ? 1 : -1)));
      ta.value = S.posHist >= 0 ? S.historialOrdenes[S.posHist] : ""; autoAlto();
    }
  });
  $("#ver-anterior").addEventListener("click", () => { S.mostrarAnterior = true; pintarEscenario(); bajarChat(true); });
  $("#conv-buscar-btn").addEventListener("click", () => { $("#conv-buscar").hidden = false; $("#chat-filtro").focus(); });
  $("#conv-buscar-cerrar").addEventListener("click", () => { $("#conv-buscar").hidden = true; $("#chat-filtro").value = ""; pintarChat(); bajarChat(true); });
  $("#chat-filtro").addEventListener("input", pintarChat);
  $("#chat-limpiar").addEventListener("click", async () => { if (await confirmar("¿Vaciar la conversación de la pantalla? No olvido nada; solo se limpia la vista.")) { await api("/api/chat_limpiar", {}); S.mensajes = []; S.mostrarAnterior = false; pintarChat(); } });
  $("#chat-exportar").addEventListener("click", async () => { const r = await api("/api/chat_exportar", {}); aviso(`Guardé la conversación en ${r.ruta}`, "exito", 8000); });
  const mic = () => fijarAjuste("escucha", !S.ajustes.escucha).then(() => aviso(S.ajustes.escucha ? "Te escucho. Di «oye asistente» y tu orden." : "Dejé de escuchar el micrófono.", "info"));
  $("#btn-mic").addEventListener("click", mic);
  $("#chat-mic").addEventListener("click", mic);
  $("#btn-voz").addEventListener("click", () => enviar($("#btn-voz").classList.contains("encendido") ? "desactiva la voz" : "activa la voz"));
  $("#abrir-paleta").addEventListener("click", abrirPaleta);
  $("#modo-chip").addEventListener("click", abrirMenuModos);

  // hoy
  $("#form-pend").addEventListener("submit", async (e) => { e.preventDefault(); const i = $("#pend-txt"); if (!i.value.trim()) return; const r = await api("/api/pendiente", { accion: "agregar", texto: i.value }); i.value = ""; S._pend = null; S.pendientes = r.pendientes; pintarPendientes(r.pendientes); pintarVistazos(); });
  $("#limpiar-hechos").addEventListener("click", async () => { const r = await api("/api/pendiente", { accion: "limpiar_hechos" }); S._pend = null; pintarPendientes(r.pendientes); });
  $("#form-habito").addEventListener("submit", async (e) => { e.preventDefault(); const i = $("#habito-txt"); if (!i.value.trim()) return; const r = await api("/api/habito", { accion: "agregar", nombre: i.value }); i.value = ""; S._hab = null; pintarHabitos(r.habitos); });
  $("#form-gasto").addEventListener("submit", async (e) => {
    e.preventDefault();
    const c = $("#gasto-concepto"), v = $("#gasto-valor");
    const num = parseFloat(v.value.replace(/[$\s.]/g, "").replace(",", "."));
    if (!num) { v.focus(); return aviso("Escribe cuánto gastaste, por ejemplo 12000.", "info"); }
    const r = await api("/api/gasto", { accion: "agregar", concepto: c.value, valor: num });
    c.value = v.value = ""; c.focus(); S._gastos = null; pintarGastos(r.gastos);
  });
  $("#nota-nueva").addEventListener("click", () => abrirNota(null));
  $("#nota-cerrar").addEventListener("click", () => { $("#editor-nota").hidden = true; });
  $("#nota-guardar").addEventListener("click", async () => {
    const nombre = $("#nota-nombre").value.trim(), orig = $("#nota-nombre").dataset.original;
    if (!nombre) { $("#nota-nombre").focus(); return aviso("Ponle un nombre a la nota.", "info"); }
    if (orig && orig !== nombre.toLowerCase()) await api("/api/nota_borrar", { nombre: orig });
    const r = await api("/api/nota", { nombre, texto: $("#nota-texto").value });
    pintarNotas(r.notas); $("#editor-nota").hidden = true; aviso("Nota guardada.", "exito", 2000);
  });
  $("#nota-borrar").addEventListener("click", async () => {
    const n = $("#nota-nombre").dataset.original;
    if (!(await confirmar(`¿Borrar la nota «${n}»? Queda una copia en Database/web/notas_borradas.`))) return;
    const r = await api("/api/nota_borrar", { nombre: n }); pintarNotas(r.notas); $("#editor-nota").hidden = true;
  });
  $("#pomo-iniciar").addEventListener("click", () => {
    if (P.corriendo) { P.restante = pomoRestante(); P.corriendo = false; }
    else { P.fin = Date.now() + pomoRestante() * 1000; P.corriendo = true; try { audio = audio || new AudioContext(); } catch {} }
    pomoGuardar(); pomoRefrescar(); pintarVistazos();
  });
  $("#pomo-reiniciar").addEventListener("click", () => { P.corriendo = false; P.restante = 0; pomoGuardar(); pomoRefrescar(); pintarVistazos(); });
  $("#pomo-saltar").addEventListener("click", () => { P.fase = P.fase === "foco" ? "descanso" : "foco"; P.corriendo = false; P.restante = 0; pomoGuardar(); pomoRefrescar(); });
  setInterval(() => { pomoRefrescar(); if (P.corriendo) pintarVistazos(); }, 1000);

  // equipo
  const deslizar = (id, etiqueta, orden) => {
    const el = $(id), v0 = guardado(id, +el.value);
    el.value = v0; el.style.setProperty("--p", v0 + "%"); $(etiqueta).textContent = v0 + "%";
    el.addEventListener("input", () => { el.style.setProperty("--p", el.value + "%"); $(etiqueta).textContent = el.value + "%"; });
    el.addEventListener("change", () => { guardar(id, +el.value); enviar(orden(el.value)); });
  };
  deslizar("#vol", "#vol-valor", (v) => `pon el volumen a ${v}`);
  deslizar("#brillo", "#brillo-valor", (v) => `pon el brillo a ${v}`);
  $("#form-abrir").addEventListener("submit", (e) => { e.preventDefault(); const i = $("#abrir-txt"); if (i.value.trim()) enviar("abre " + i.value.trim()); i.value = ""; });
  $("#form-teclear").addEventListener("submit", (e) => { e.preventDefault(); const i = $("#teclear-txt"); if (i.value.trim()) enviar("teclea " + i.value); i.value = ""; });
  $("#apps").innerHTML = ["Chrome", "Spotify", "YouTube", "WhatsApp", "Explorador de archivos", "Calculadora", "Visual Studio Code"].map((a) => `<button class="chip" data-orden="abre ${a.toLowerCase()}">${a}</button>`).join("");
  $("#carpetas").innerHTML = ["Descargas", "Documentos", "Escritorio", "Imágenes", "Música", "Videos"].map((c) => `<button class="chip" data-orden="abre la carpeta de ${c.toLowerCase()}">${icono("carpeta")}${c}</button>`).join("");
  $("#atajos-teclado").innerHTML = [["Copiar", "ctrl+c"], ["Pegar", "ctrl+v"], ["Deshacer", "ctrl+z"], ["Guardar", "ctrl+s"], ["Cambiar de ventana", "alt+tab"]].map(([n, k]) => `<button class="chip" data-orden="presiona ${k}" title="${k}">${n}</button>`).join("");
  $("#rutina-nueva").addEventListener("click", () => abrirEditorRutina(null));
  $("#rutina-cerrar").addEventListener("click", () => { $("#editor-rutina").hidden = true; });
  $("#rutina-guardar").addEventListener("click", async () => {
    const nombre = $("#rutina-nombre").value.trim(), pasos = $("#rutina-pasos").value.split("\n").map((x) => x.trim()).filter(Boolean);
    if (!nombre) return $("#rutina-nombre").focus();
    if (!pasos.length) return $("#rutina-pasos").focus();
    if (S.rutinaEditando && S.rutinaEditando !== nombre) await api("/api/rutina", { accion: "borrar", nombre: S.rutinaEditando });
    const r = await api("/api/rutina", { accion: "guardar", nombre, pasos });
    S.rutinas = r.rutinas; pintarRutinas(); $("#editor-rutina").hidden = true; aviso(`Rutina «${nombre}» guardada.`, "exito", 2500);
  });
  $("#rutina-borrar").addEventListener("click", async () => {
    if (!(await confirmar(`¿Borrar la rutina «${S.rutinaEditando}»?`))) return;
    const r = await api("/api/rutina", { accion: "borrar", nombre: S.rutinaEditando });
    S.rutinas = r.rutinas; pintarRutinas(); $("#editor-rutina").hidden = true;
  });
  $("#cmd-filtro").addEventListener("input", pintarComandos);
  $("#form-probar").addEventListener("submit", async (e) => { e.preventDefault(); const t = $("#probar-txt").value.trim(); if (!t) return; await api("/api/redes", { accion: "probar", texto: t, clave: null }); S.redSeguir = true; cargarRedes(); });
  $("#form-ensenar").addEventListener("submit", async (e) => { e.preventDefault(); const i = $("#ensenar-txt"); if (!i.value.trim()) return; await api("/api/redes", { accion: "agregar", texto: i.value }); i.value = ""; cargarRedes(); });
  const entrenar = async (clave) => { const r = await api("/api/redes", { accion: "entrenar", clave }); if (!r.ok) aviso(r.error, "info"); else aviso("Entrenando en segundo plano. Puedes seguir usándome.", "info"); cargarRedes(); };
  $("#red-entrenar").addEventListener("click", () => entrenar(S.redClave));
  $("#redes-entrenar-todas").addEventListener("click", () => entrenar("todas"));
  $("#redes-lista").addEventListener("keydown", (e) => { if (e.key === "Enter" && e.target.dataset.red) e.target.click(); });

  // ajustes
  $("#aj-filtro").addEventListener("input", filtrarAjustes);
  $("#boton-nuevo").addEventListener("click", () => abrirEditorBoton(null));
  $("#boton-cerrar").addEventListener("click", () => { $("#editor-boton").hidden = true; });
  $("#boton-guardar").addEventListener("click", guardarBoton);
  $("#boton-borrar").addEventListener("click", async () => {
    const l = [...(S.ajustes.web_botones || [])]; const [b] = l.splice(S.botonEditando, 1);
    $("#editor-boton").hidden = true; await fijarAjuste("web_botones", l); aviso(`Borré el botón «${b.texto}».`, "info", 2500);
  });
  $("#abrir-clasica").addEventListener("click", () => { api("/api/clasica", {}); aviso("Abriendo la ventana clásica…", "info"); });
  $("#fondo-archivo").addEventListener("change", (e) => {
    const f = e.target.files[0]; if (!f) return;
    if (f.size > 15 * 1024 * 1024) return aviso("Esa imagen pesa más de 15 MB.", "error");
    const lector = new FileReader();
    lector.onload = async () => {
      const r = await api("/api/fondo_subir", { nombre: f.name, datos: lector.result });
      if (!r.ok) return aviso(r.error, "error");
      S.fondos = r.fondos; S.ajustes.fondo = r.fondo; aplicarAjustes(S.ajustes); pintarFondos();
      aviso((S.ajustes.web_vidrio || 0) < 25 ? "Fondo puesto. Sube la «Transparencia» de los paneles para verlo más." : "Fondo puesto.", "exito", 5000);
    };
    lector.readAsDataURL(f); e.target.value = "";
  });
  $("#css-guardar").addEventListener("click", async () => {
    await api("/api/mi_estilo", { css: $("#css-propio").value });
    $('link[href^="mi_estilo.css"]').href = "mi_estilo.css?v=" + Date.now();
    $("#css-estado").textContent = "Aplicado.";
    setTimeout(() => { $("#css-estado").textContent = ""; }, 2500);
  });
  $("#css-propio").addEventListener("keydown", (e) => { if (e.key === "s" && e.ctrlKey) { e.preventDefault(); $("#css-guardar").click(); } if (e.key === "Tab") { e.preventDefault(); document.execCommand("insertText", false, "  "); } });
  $("#exportar-pers").addEventListener("click", async () => {
    const d = await api("/api/personalizacion"), a = document.createElement("a");
    a.href = URL.createObjectURL(new Blob([JSON.stringify(d, null, 2)], { type: "application/json" }));
    a.download = "arche-personalizacion.json"; a.click();
    aviso("Listo. Si no ves la descarga, búscala en tu carpeta de Descargas.", "exito", 4000);
  });
  $("#importar-archivo").addEventListener("change", (e) => {
    const f = e.target.files[0]; if (!f) return;
    const lector = new FileReader();
    lector.onload = async () => {
      let d; try { d = JSON.parse(lector.result); } catch { return aviso("Ese archivo no se puede leer.", "error"); }
      const r = await api("/api/personalizacion_importar", d);
      if (!r.ok) return aviso(r.error, "error");
      S.ajustesServidor = null; await sondear(); cargarAjustes(); aviso(`Cargué tu personalización (${r.cambios} ajustes).`, "exito");
    };
    lector.readAsText(f); e.target.value = "";
  });

  // búsqueda y teclado
  $("#paleta-txt").addEventListener("input", filtrarPaleta);
  $("#paleta-txt").addEventListener("keydown", (e) => {
    if (e.key === "ArrowDown") { e.preventDefault(); paletaSel = Math.min(paletaItems.length - 1, paletaSel + 1); pintarPaleta(); }
    if (e.key === "ArrowUp") { e.preventDefault(); paletaSel = Math.max(0, paletaSel - 1); pintarPaleta(); }
    if (e.key === "Enter") { e.preventDefault(); usarPaleta(paletaSel); }
  });
  $("#paleta").addEventListener("click", (e) => { if (e.target.id === "paleta") cerrarPaleta(); });
  document.addEventListener("keydown", (e) => {
    if ((e.ctrlKey || e.metaKey) && (e.key === "k" || e.key === "K" || e.code === "Space")) { e.preventDefault(); abrirPaleta(); }
    if (e.key === "Escape") { cerrarPaleta(); ["#editor-nota", "#editor-boton", "#editor-rutina"].forEach((s) => { $(s).hidden = true; }); if (!$("#confirmar").hidden) $("#conf-no").click(); }
    if (e.altKey && /^[1-5]$/.test(e.key)) { e.preventDefault(); const vis = $$("#nav button:not([hidden])"); vis[+e.key - 1]?.click(); }
  });
  addEventListener("resize", () => { pintarGrafica(); dibujarRed(); });
  document.addEventListener("visibilitychange", () => { if (!document.hidden) sondear(); });
}

/* =========================================================== arranque */
async function arrancar() {
  conectar();
  registrarOrbe($("#orbe-mini"), false);
  registrarOrbe($("#orbe-grande"), true);
  registrarOrbe($("#orbe-conv"), false);
  requestAnimationFrame(animar);
  reloj(); setInterval(reloj, 1000);
  if (!LLAVE) aviso("Abre esta página desde Arché: escribe «abre la interfaz» en la consola.", "error", 15000);
  try { S.aplica = await api("/api/aplicar"); } catch {}
  await sondear();
  const ini = S.ajustes.web_inicio === "ultima" ? guardado("seccion", "inicio") : S.ajustes.web_inicio;
  irA(ini || "inicio");
  pintarChat(); bajarChat(true);
  cargarInicio(); setInterval(() => cargarInicio(true), 10 * 60 * 1000);
}
arrancar();
