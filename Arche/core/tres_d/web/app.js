// Arché 3D — arranque: la llave, el lienzo, las vistas y el pulso con Arché.
import * as THREE from 'three';
import { crearTaller } from './taller.js';
import { crearNucleo } from './nucleo.js';
import { crearPerro } from './perro.js';
import { crearCerebro } from './cerebro.js';

const $ = (s) => document.querySelector(s);

// ---- la llave: viene en la dirección (?k=...) la primera vez y se quita de la vista ----
let llave = new URLSearchParams(location.search).get('k');
try {
  if (llave) sessionStorage.setItem('arche3d', llave);
  else llave = sessionStorage.getItem('arche3d');
} catch (e) { /* sin almacenamiento: sirve mientras no recargues */ }
if (new URLSearchParams(location.search).has('k')) history.replaceState(null, '', location.pathname + location.hash);

async function api(ruta, opciones = {}) {
  const r = await fetch(ruta, { ...opciones, headers: { 'X-Arche-Llave': llave || '', ...(opciones.headers || {}) } });
  if (r.status === 401 || r.status === 403) { $('#sinllave').hidden = false; throw new Error('sin llave'); }
  return r;
}
const apiJson = async (ruta, opciones) => (await api(ruta, opciones)).json();
const enviar = (ruta, datos) => apiJson(ruta, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(datos) });

let avisoReloj = 0;
function aviso(texto) {
  const a = $('#aviso');
  a.textContent = texto;
  a.classList.add('ver');
  clearTimeout(avisoReloj);
  avisoReloj = setTimeout(() => a.classList.remove('ver'), 2600);
}

// ---- etiquetas HTML pegadas a puntos del espacio ----
const capaEtiquetas = $('#etiquetas');
const _v = new THREE.Vector3();
function etiqueta(clase) {
  const e = document.createElement('div');
  e.className = 'etq ' + (clase || '');
  e.style.display = 'none';
  capaEtiquetas.appendChild(e);
  return e;
}
function colocar(e, punto, camara) {
  _v.copy(punto).project(camara);
  if (_v.z > 1 || _v.z < -1) { e.style.display = 'none'; return false; }
  e.style.display = '';
  e.style.left = ((_v.x * 0.5 + 0.5) * innerWidth).toFixed(1) + 'px';
  e.style.top = ((-_v.y * 0.5 + 0.5) * innerHeight).toFixed(1) + 'px';
  return true;
}

// ---- el lienzo ----
const lienzo = $('#lienzo');
const render = new THREE.WebGLRenderer({ canvas: lienzo, antialias: true, powerPreference: 'high-performance' });
render.setPixelRatio(Math.min(devicePixelRatio || 1, 2));
render.setClearColor(0x0c0c14, 1);
render.localClippingEnabled = true;

const ctx = { THREE, render, lienzo, api, apiJson, enviar, aviso, etiqueta, colocar, panel: $('#panel'), $,
              estado: null, quieto: matchMedia('(prefers-reduced-motion: reduce)').matches };

const TITULOS = {
  taller: ['Taller', 'Crea, revisa y prepara piezas para imprimir.'],
  nucleo: ['Núcleo', 'Arché en vivo: cambia cuando escucha, piensa, habla o trabaja.'],
  perro: ['Perro', 'Prueba los movimientos aquí antes de mandarlos al robot.'],
  cerebro: ['Cerebro', 'Cada punto es un archivo de Arché; las líneas, quién usa a quién.'],
};
const vistas = {};
let activa = null;

function tamano() {
  render.setSize(innerWidth, innerHeight, false);
  for (const v of Object.values(vistas)) {
    v.camara.aspect = innerWidth / innerHeight;
    v.camara.updateProjectionMatrix();
  }
}

function cambiar(nombre) {
  if (!vistas[nombre]) nombre = 'taller';
  if (activa === nombre) return;
  if (activa) vistas[activa].salir();
  capaEtiquetas.querySelectorAll('.etq').forEach((e) => { e.style.display = 'none'; });
  activa = nombre;
  document.body.dataset.vista = nombre;
  document.querySelectorAll('#riel button').forEach((b) => b.classList.toggle('activo', b.dataset.vista === nombre));
  $('#titulo').textContent = TITULOS[nombre][0];
  $('#subtitulo').textContent = TITULOS[nombre][1];
  ctx.panel.innerHTML = '';
  vistas[nombre].entrar();
  if (location.hash !== '#' + nombre) history.replaceState(null, '', '#' + nombre);
}

const NOMBRE_ESTADO = { reposo: 'en reposo', escuchando: 'escuchando', pensando: 'pensando', hablando: 'hablando' };
async function pulso() {
  try {
    const e = await apiJson('/api/estado');
    ctx.estado = e;
    const caja = $('#estadoArche');
    const visual = e.arche.dentro_de_arche ? e.arche.visual : 'aparte';
    caja.className = 'estado-arche ' + visual;
    caja.querySelector('b').textContent = e.arche.dentro_de_arche ? (NOMBRE_ESTADO[visual] || visual) : 'sin Arché';
    for (const v of Object.values(vistas)) v.alEstado && v.alEstado(e);
  } catch (err) { /* Arché cerrado o sin llave: se reintenta */ }
}

function iniciar() {
  vistas.taller = crearTaller(ctx);
  vistas.nucleo = crearNucleo(ctx);
  vistas.perro = crearPerro(ctx);
  vistas.cerebro = crearCerebro(ctx);
  tamano();
  addEventListener('resize', tamano);
  document.querySelectorAll('#riel button').forEach((b) => b.addEventListener('click', () => cambiar(b.dataset.vista)));
  addEventListener('hashchange', () => cambiar(location.hash.slice(1)));
  cambiar(location.hash.slice(1) || 'taller');
  pulso();
  setInterval(pulso, 1200);

  const reloj = new THREE.Clock();
  render.setAnimationLoop(() => {
    const dt = Math.min(reloj.getDelta(), 0.1);
    const v = vistas[activa];
    if (!v) return;
    v.controles && v.controles.update();
    v.actualizar(dt, reloj.elapsedTime);
    render.render(v.escena, v.camara);
  });
}

if (!llave) $('#sinllave').hidden = false;
else iniciar();
