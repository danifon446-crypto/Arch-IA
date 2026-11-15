// Arché 3D — arranque: la llave, el lienzo, las vistas y el pulso con Arché.
import * as THREE from 'three';
import { crearTaller } from './taller.js';
import { crearNucleo } from './nucleo.js';
import { crearPerro } from './perro.js';
import { crearCerebro } from './cerebro.js';
import { crearManos } from './manos.js';
import { crearConstruir } from './construir.js';
import { crearModelar } from './modelar.js';

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
  construir: ['Construir', 'Arma tu pieza juntando formas y abriendo agujeros, con las manos o el mouse.'],
  modelar: ['Modelar', 'Como Blender, con tus manos: esculpe, extruye caras y usa modificadores.'],
  nucleo: ['Núcleo', 'Arché en vivo: cambia cuando escucha, piensa, habla o trabaja.'],
  perro: ['Perro', 'Prueba los movimientos aquí antes de mandarlos al robot.'],
  cerebro: ['Cerebro', 'Cada punto es un archivo de Arché; las líneas, quién usa a quién.'],
};
const vistas = {};
let activa = null;
let manos = null;
let pedidosVistos = null;
let irVistos = null;
ctx.vistaActiva = () => vistas[activa];
const ORDEN_VISTAS = ['taller', 'construir', 'modelar', 'nucleo', 'perro', 'cerebro'];
// mano abierta pasando de lado: cada vista decide qué es «siguiente»; si no, cambia de vista
ctx.deslizar = (dir) => {
  const v = vistas[activa];
  if (v && v.deslizar && v.deslizar(dir)) return;
  const i = ORDEN_VISTAS.indexOf(activa);
  cambiar(ORDEN_VISTAS[(i + (dir === 'derecha' ? 1 : ORDEN_VISTAS.length - 1)) % ORDEN_VISTAS.length]);
};
// pulgar arriba: aplica lo que Arché recomienda en esta vista
ctx.aceptar = () => {
  const v = vistas[activa];
  if (v && v.aceptar) v.aceptar();
  else aviso('Aquí no hay nada que aceptar. En el Taller, el pulgar aplica el arreglo que recomienda Arché.');
};
// pulgar abajo y dedos en V: solo tienen sentido donde hay algo que borrar o duplicar (Construir)
ctx.rechazar = () => { const v = vistas[activa]; if (v && v.rechazar) v.rechazar(); else aviso('El pulgar abajo borra la parte elegida en Construir o Modelar.'); };
ctx.duplicar = () => { const v = vistas[activa]; if (v && v.duplicar) v.duplicar(); else aviso('Los dedos en V duplican la parte elegida en Construir o Modelar.'); };
// ir a otra vista con un modelo: «Editar en Construir» desde el taller, «Verla en el Taller» desde Construir
ctx.irA = (nombre, modelo) => {
  cambiar(nombre);
  if (modelo && (nombre === 'construir' || nombre === 'modelar')) vistas[nombre].cargar(modelo).catch(() => aviso('No pude abrir esa pieza.'));
  if (modelo && nombre === 'taller' && vistas.taller.mostrar) vistas.taller.mostrar(modelo);
};
ctx.alManos = (encendidas) => {
  const b = $('#botonManos');
  if (b) b.classList.toggle('activo', encendidas);
};

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
  document.querySelectorAll('#riel button[data-vista]').forEach((b) => b.classList.toggle('activo', b.dataset.vista === nombre));
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
    // «controla con las manos» dicho a Arché enciende las manos en esta página
    if (e.pedidos) {
      if (pedidosVistos !== null && e.pedidos.manos > pedidosVistos && manos && !manos.activo()) manos.encender();
      pedidosVistos = e.pedidos.manos;
      if (irVistos !== null && e.pedidos.ir > irVistos && e.pedidos.ir_a) ctx.irA(e.pedidos.ir_a.vista, e.pedidos.ir_a.modelo);
      irVistos = e.pedidos.ir;
    }
  } catch (err) { /* Arché cerrado o sin llave: se reintenta */ }
}

function iniciar() {
  vistas.taller = crearTaller(ctx);
  vistas.nucleo = crearNucleo(ctx);
  vistas.perro = crearPerro(ctx);
  vistas.cerebro = crearCerebro(ctx);
  vistas.construir = crearConstruir(ctx);
  vistas.modelar = crearModelar(ctx);
  // cada vista puede volver a como empezó (lo usa el gesto de la palma abierta)
  for (const v of Object.values(vistas)) {
    if (v.reencuadrar) continue;
    const pos = v.camara.position.clone(), obj = v.controles.target.clone(), auto = v.controles.autoRotate;
    v.reencuadrar = () => { v.camara.position.copy(pos); v.controles.target.copy(obj); v.controles.autoRotate = auto; };
  }
  manos = crearManos(ctx);
  $('#botonManos').addEventListener('click', () => manos.alternar());
  window.__arche3d = { manos, vistas, activa: () => activa };       // para las pruebas automáticas
  tamano();
  addEventListener('resize', tamano);
  document.querySelectorAll('#riel button[data-vista]').forEach((b) => b.addEventListener('click', () => cambiar(b.dataset.vista)));
  addEventListener('hashchange', () => cambiar(location.hash.slice(1).split('+')[0]));
  const [vistaInicial, extra] = decodeURIComponent(location.hash.slice(1) || 'taller').split('+');
  cambiar(vistaInicial);
  if (extra === 'manos') manos.encender();
  else if (extra && (vistaInicial === 'construir' || vistaInicial === 'modelar')) vistas[vistaInicial].cargar(extra).catch(() => {});
  pulso();
  setInterval(pulso, 1200);

  const reloj = new THREE.Clock();
  render.setAnimationLoop(() => {
    const dt = Math.min(reloj.getDelta(), 0.1);
    const v = vistas[activa];
    if (!v) return;
    manos.actualizar(dt);
    v.controles && v.controles.update();
    v.actualizar(dt, reloj.elapsedTime);
    render.render(v.escena, v.camara);
  });
}

if (!llave) $('#sinllave').hidden = false;
else iniciar();
