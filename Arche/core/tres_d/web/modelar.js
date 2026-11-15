// Modelar: como Blender, pero pensado para las manos.
//   Modo Objeto     agregar formas, moverlas / girarlas / escalarlas (con flechas por eje), modificadores
//   Modo Edición    tocar caras o vértices, extruir, insertar, biselar, mover, escalar, subdividir
//   Modo Escultura  el dedo es el pincel: inflar, hundir, alisar, agarrar, aplanar, pellizcar (con simetría)
// Todo queda cerrado (imprimible). Al guardar, Arché une los objetos en un sólido y lo deja en tus modelos.
import * as THREE from 'three';
import { OrbitControls } from './lib/OrbitControls.js';
import { STLLoader } from './lib/STLLoader.js';
import * as M from './malla_edit.js';

const RAD = Math.PI / 180;
const COLORES = [0x9a8cff, 0x6aa8ff, 0x5fd3c4, 0xffc65c, 0xff8ad8, 0x4fd08b];
const NARANJA = 0xffa040;            // la selección, como en Blender
const MODOS = { objeto: 'Objeto', edicion: 'Edición', escultura: 'Escultura' };
const HERRAMIENTAS = { extruir: 'Extruir', insertar: 'Insertar', biselar: 'Biselar', mover: 'Mover' };
const AYUDA_MANOS = {
  objeto: [['Pellizco rápido', 'elegir un objeto o un botón'], ['Pellizca el objeto y mueve', 'moverlo sobre la cama'],
    ['Pellizca una flecha roja/verde/azul', 'moverlo solo en ese eje'], ['Dos manos', 'escalar (de lado = ancho, arriba/abajo = alto) y girar como volante'],
    ['Dedos en V', 'duplicar'], ['Pulgar abajo', 'borrar'], ['Mano abierta izq./der.', 'deshacer / rehacer'], ['Pulgar arriba', 'guardar']],
  edicion: [['Pellizco rápido', 'elegir una cara (o un vértice)'], ['Pellizca la cara elegida y jala', 'extruir / insertar / biselar / mover (según la herramienta)'],
    ['Dos manos', 'escalar y girar lo elegido'], ['Dedos en V', 'insertar rápido'], ['Pulgar abajo', 'soltar la selección'],
    ['Mano abierta izq./der.', 'deshacer / rehacer']],
  escultura: [['Apunta', 'el círculo es tu pincel'], ['Pellizca y mueve sobre la pieza', 'esculpir'], ['Dos manos', 'pincel más grande o más chico'],
    ['Dedos en V', 'inflar ⇄ hundir'], ['Pulgar abajo', 'siguiente pincel'], ['Mano abierta izq./der.', 'deshacer / rehacer']],
};

export function crearModelar(ctx) {
  const { render, apiJson, api, enviar, aviso, $ } = ctx;
  const escena = new THREE.Scene();
  escena.background = new THREE.Color(0x1d1d24);            // el gris de Blender
  const camara = new THREE.PerspectiveCamera(40, 1, 0.5, 8000);
  camara.up.set(0, 0, 1);
  camara.position.set(110, -150, 95);
  const controles = new OrbitControls(camara, render.domElement);
  controles.enableDamping = true;
  controles.dampingFactor = 0.1;
  controles.target.set(0, 0, 10);
  controles.enabled = false;
  escena.add(new THREE.HemisphereLight(0xe8eaff, 0x2a2a33, 1.2));
  const sol = new THREE.DirectionalLight(0xffffff, 1.4);
  sol.position.set(0.5, -0.6, 1);
  camara.add(sol);
  escena.add(camara);

  // piso como Blender: rejilla gris, eje X rojo, eje Y verde
  const piso = new THREE.Group();
  const grilla = new THREE.GridHelper(400, 40, 0x3a3a46, 0x2c2c36);
  grilla.rotation.x = Math.PI / 2;
  piso.add(grilla);
  const linea = (a, b, c) => new THREE.Line(new THREE.BufferGeometry().setFromPoints([new THREE.Vector3(...a), new THREE.Vector3(...b)]),
    new THREE.LineBasicMaterial({ color: c }));
  piso.add(linea([-200, 0, 0.05], [200, 0, 0.05], 0xc8454f), linea([0, -200, 0.05], [0, 200, 0.05], 0x6fa83c));
  escena.add(piso);

  const st = { visible: false, objetos: [], activo: null, modo: 'objeto', selModo: 'cara', sel: new Set(), herramienta: 'extruir',
               pincel: 'inflar', radio: 6, fuerza: 0.5, simetria: true, pasado: [], futuro: [], op: null, nombre: '', editando: null,
               modelos: [], ocupado: false, dos: null, ultimoDos: 0, punteroEn: null, info: null, aviso: '' };
  let sigId = 1;
  const nuevoId = () => 'o' + (sigId++) + Math.random().toString(36).slice(2, 5);
  const obj = (id = st.activo) => st.objetos.find((o) => o.id === id);

  // ---------------------------------------------------------------- dibujo de los objetos
  const grupo = new THREE.Group();
  escena.add(grupo);
  const vistas = new Map();          // id -> { nodo, malla, geom, mods (Mesh), alambre, puntos }
  const matSel = new THREE.MeshBasicMaterial({ color: NARANJA, transparent: true, opacity: 0.55, depthTest: true,
    polygonOffset: true, polygonOffsetFactor: -2, polygonOffsetUnits: -2, side: THREE.DoubleSide });
  const matAlambre = new THREE.LineBasicMaterial({ color: 0x000000, transparent: true, opacity: 0.35 });
  const matPuntos = new THREE.PointsMaterial({ color: 0x111111, size: 4, sizeAttenuation: false });
  const matPuntosSel = new THREE.PointsMaterial({ color: NARANJA, size: 7, sizeAttenuation: false, depthTest: false });
  const matFantasma = new THREE.MeshStandardMaterial({ color: 0x9a8cff, transparent: true, opacity: 0.22, depthWrite: false });

  function materialDe(o) {
    return new THREE.MeshStandardMaterial({ color: o.color, roughness: 0.55, metalness: 0.05, flatShading: o.plano });
  }
  function aplicarTransformacion(nodo, o) {
    nodo.position.set(...o.pos);
    nodo.rotation.order = 'ZYX';
    nodo.rotation.set(o.rot[0] * RAD, o.rot[1] * RAD, o.rot[2] * RAD);
    nodo.scale.set(...o.esc);
  }
  function geometriaDe(malla) {
    const g = new THREE.BufferGeometry();
    g.setAttribute('position', new THREE.BufferAttribute(malla.v, 3));        // el MISMO arreglo: esculpir se ve al instante
    g.setIndex(new THREE.BufferAttribute(malla.f, 1));
    g.computeVertexNormals();
    g.computeBoundingSphere();
    return g;
  }
  function aristasDe(malla, geom) {
    const vistas_ = new Set(), idx = [];
    for (let t = 0; t < malla.f.length; t += 3) for (let k = 0; k < 3; k++) {
      const a = malla.f[t + k], b = malla.f[t + (k + 1) % 3];
      const c = a < b ? a * 4294967296 + b : b * 4294967296 + a;
      if (!vistas_.has(c)) { vistas_.add(c); idx.push(a, b); }
    }
    const g = new THREE.BufferGeometry();
    g.setAttribute('position', geom.getAttribute('position'));
    g.setIndex(idx);
    return g;
  }

  function reconstruir(o) {
    // después de un cambio de forma (extruir, subdividir…): geometría nueva
    let v = vistas.get(o.id);
    if (v) { v.nodo.traverse((x) => { if (x.geometry) x.geometry.dispose(); }); grupo.remove(v.nodo); }
    const nodo = new THREE.Group();
    const geom = geometriaDe(o.malla);
    const malla = new THREE.Mesh(geom, materialDe(o));
    malla.userData.id = o.id;
    nodo.add(malla);
    v = { nodo, malla, geom, mods: null, alambre: null, puntos: null, contorno: null };
    vistas.set(o.id, v);
    grupo.add(nodo);
    aplicarTransformacion(nodo, o);
    actualizarExtras(o);
  }

  function actualizarExtras(o) {
    // modificadores, alambre de edición, contorno de selección
    const v = vistas.get(o.id);
    if (!v) return;
    for (const k of ['mods', 'alambre', 'puntos', 'contorno', 'selCaras', 'selPuntos']) {
      if (v[k]) { v.nodo.remove(v[k]); v[k].geometry && v[k].geometry.dispose(); v[k] = null; }
    }
    v.nodo.visible = o.visible !== false;
    const activo = o.id === st.activo;
    const editando = activo && st.modo !== 'objeto';
    if (o.mods.some((m) => !m.apagado)) {
      const piezas = M.aplicarModificadores(o.malla, o.mods);
      const juntas = M.juntar(piezas);
      const g = new THREE.BufferGeometry();
      g.setAttribute('position', new THREE.BufferAttribute(juntas.v, 3));
      g.setIndex(new THREE.BufferAttribute(juntas.f, 1));
      g.computeVertexNormals();
      v.mods = new THREE.Mesh(g, editando ? matFantasma : materialDe(o));
      v.mods.userData.id = o.id;
      v.nodo.add(v.mods);
      v.malla.visible = editando || !o.mods.some((m) => m.tipo === 'suavizar' || m.tipo === 'subdividir');
    } else {
      v.malla.visible = true;
    }
    if (activo && st.modo === 'objeto') {
      v.contorno = new THREE.BoxHelper(v.nodo, NARANJA);
      v.contorno.material.depthTest = false;
      v.contorno.renderOrder = 4;
      escena.add(v.contorno);
      v.contorno.userData.suelto = true;
    }
    if (activo && st.modo === 'edicion') {
      v.alambre = new THREE.LineSegments(aristasDe(o.malla, v.geom), matAlambre);
      v.nodo.add(v.alambre);
      if (st.selModo === 'vertice') {
        v.puntos = new THREE.Points(v.geom, matPuntos);
        v.nodo.add(v.puntos);
      }
      pintarSeleccion(o);
    }
  }
  function pintarSeleccion(o) {
    const v = vistas.get(o.id);
    if (!v) return;
    for (const k of ['selCaras', 'selPuntos']) if (v[k]) { v.nodo.remove(v[k]); v[k].geometry.dispose(); v[k] = null; }
    if (!st.sel.size) return;
    if (st.selModo === 'cara') {
      const idx = [];
      for (const t of st.sel) idx.push(o.malla.f[t * 3], o.malla.f[t * 3 + 1], o.malla.f[t * 3 + 2]);
      const g = new THREE.BufferGeometry();
      g.setAttribute('position', v.geom.getAttribute('position'));
      g.setIndex(idx);
      v.selCaras = new THREE.Mesh(g, matSel);
      v.selCaras.renderOrder = 3;
      v.nodo.add(v.selCaras);
    } else {
      const g = new THREE.BufferGeometry();
      g.setAttribute('position', v.geom.getAttribute('position'));
      g.setIndex([...st.sel]);
      v.selPuntos = new THREE.Points(g, matPuntosSel);
      v.selPuntos.renderOrder = 5;
      v.nodo.add(v.selPuntos);
    }
  }
  function limpiarContornos() {
    for (const c of escena.children.filter((x) => x.userData.suelto)) { escena.remove(c); c.geometry && c.geometry.dispose(); }
  }
  function redibujarTodo() {
    limpiarContornos();
    for (const [id, v] of vistas) if (!obj(id)) { grupo.remove(v.nodo); vistas.delete(id); }
    for (const o of st.objetos) { if (!vistas.has(o.id)) reconstruir(o); else { aplicarTransformacion(vistas.get(o.id).nodo, o); actualizarExtras(o); } }
    pintarGizmo();
  }
  function formaCambio(o, todo = false) {
    // la malla cambió de valores (esculpir / mover vértices): avisar a three.js sin reconstruir
    const v = vistas.get(o.id);
    if (!v) return;
    const pos = v.geom.getAttribute('position');
    pos.needsUpdate = true;
    v.geom.computeVertexNormals();
    v.geom.computeBoundingSphere();
    v.geom.computeBoundingBox();
    if (todo) actualizarExtras(o);
  }

  // ---------------------------------------------------------------- historial
  const fotoObjeto = (o) => ({ ...o, malla: M.copiar(o.malla), pos: [...o.pos], rot: [...o.rot], esc: [...o.esc], mods: JSON.parse(JSON.stringify(o.mods)) });
  const foto = () => ({ objetos: st.objetos.map(fotoObjeto), activo: st.activo, sel: [...st.sel] });
  function recordar() {
    st.pasado.push(foto());
    if (st.pasado.length > 40) st.pasado.shift();
    st.futuro = [];
  }
  function restaurar(f) {
    st.objetos = f.objetos.map(fotoObjeto);
    st.activo = f.activo;
    st.sel = new Set(f.sel);
    for (const [, v] of vistas) grupo.remove(v.nodo);
    vistas.clear();
    cambio();
  }
  function deshacer() { if (!st.pasado.length) return aviso('No hay nada que deshacer.'); st.futuro.push(foto()); restaurar(st.pasado.pop()); aviso('Deshecho'); }
  function rehacer() { if (!st.futuro.length) return aviso('No hay nada que rehacer.'); st.pasado.push(foto()); restaurar(st.futuro.pop()); aviso('Rehecho'); }

  function cambio() {
    redibujarTodo();
    revisarDetalle();
    revisar();
    pintarPanel();
    pintarBarra();
  }

  // ---------------------------------------------------------------- objetos
  const FABRICAS = {
    cubo: { nombre: 'Cubo', hacer: () => M.cubo(20, 20, 20, 8), plano: true },
    esfera: { nombre: 'Esfera', hacer: () => M.esfera(24, 4) },
    cilindro: { nombre: 'Cilindro', hacer: () => M.cilindro(20, 24, 40, 8) },
    cono: { nombre: 'Cono', hacer: () => M.cono(22, 26, 40) },
    toro: { nombre: 'Dona', hacer: () => M.toro(34, 10, 48, 24) },
  };
  function lugarLibre() {
    // a la derecha del último objeto, para que no aparezca encima de otro
    let x = 0;
    for (const o of st.objetos) {
      const b = cajaMundo(o);
      if (b) x = Math.max(x, b.max.x + 15);
    }
    return st.objetos.length ? Math.round(x + 5) : 0;
  }
  function agregar(tipo, malla, nombre) {
    recordar();
    const f = FABRICAS[tipo];
    const o = { id: nuevoId(), nombre: nombre || (f ? f.nombre : 'Pieza') + ' ' + (st.objetos.length + 1), malla: malla || f.hacer(),
                pos: [lugarLibre(), 0, 0], rot: [0, 0, 0], esc: [1, 1, 1], mods: [], visible: true,
                color: COLORES[st.objetos.length % COLORES.length], plano: !!(f && f.plano) };
    st.objetos.push(o);
    st.activo = o.id;
    st.sel.clear();
    if (st.modo !== 'objeto') st.modo = 'objeto';
    cambio();
    return o;
  }
  function borrarObjeto() {
    const o = obj();
    if (!o) return aviso('Primero toca un objeto.');
    recordar();
    st.objetos = st.objetos.filter((x) => x !== o);
    st.activo = st.objetos.length ? st.objetos[st.objetos.length - 1].id : null;
    aviso(`Borré «${o.nombre}» (mano abierta a la izquierda lo recupera).`);
    cambio();
  }
  function duplicarObjeto() {
    const o = obj();
    if (!o) return aviso('Primero toca un objeto.');
    recordar();
    const c = fotoObjeto(o);
    c.id = nuevoId();
    c.nombre = o.nombre + ' copia';
    const b = cajaMundo(o);
    c.pos[0] += b ? Math.round(b.max.x - b.min.x + 5) : 25;
    st.objetos.push(c);
    st.activo = c.id;
    aviso('Duplicado');
    cambio();
  }
  function cajaMundo(o) {
    const v = vistas.get(o.id);
    if (!v) return null;
    v.nodo.updateMatrixWorld(true);
    // lo que de verdad se va a imprimir: la malla y, si hay modificadores, sus copias
    const caja = new THREE.Box3().setFromObject(v.malla);
    if (v.mods) caja.union(new THREE.Box3().setFromObject(v.mods));
    return caja;
  }

  // ---------------------------------------------------------------- modos
  function ponerModo(modo) {
    if (modo !== 'objeto' && !obj()) { aviso('Primero agrega o toca un objeto.'); modo = 'objeto'; }
    st.modo = modo;
    st.sel.clear();
    st.op = null;
    cursor.visible = cursorEsp.visible = false;
    if (modo === 'escultura') revisarDetalle();
    cambio();
  }

  // ---------------------------------------------------------------- tocar y apuntar (manos y mouse)
  const rayo = new THREE.Raycaster();
  const raton = new THREE.Vector2();
  function rayoDesde(x, y) {
    raton.set((x / innerWidth) * 2 - 1, -(y / innerHeight) * 2 + 1);
    rayo.setFromCamera(raton, camara);
    return rayo;
  }
  function tocarObjeto(x, y, soloActivo) {
    rayoDesde(x, y);
    const lista = [];
    for (const o of st.objetos) {
      if (soloActivo && o.id !== st.activo) continue;
      const v = vistas.get(o.id);
      if (!v || o.visible === false) continue;
      lista.push(v.malla.visible ? v.malla : v.mods);
      if (v.mods && v.malla.visible && st.modo === 'objeto') lista.push(v.mods);
    }
    const hit = rayo.intersectObjects(lista.filter(Boolean), false)[0];
    if (!hit) return null;
    const o = obj(hit.object.userData.id);
    const v = vistas.get(o.id);
    const local = v.malla.worldToLocal(hit.point.clone());
    return { o, punto: hit.point, local, tri: hit.object === v.malla ? hit.faceIndex : null, normal: hit.face && hit.face.normal };
  }

  function tocar(x, y) {
    if (st.modo === 'objeto') {
      const t = tocarObjeto(x, y);
      st.activo = t ? t.o.id : st.activo;
      if (!t) st.activo = null;
      cambio();
    } else if (st.modo === 'edicion') {
      const t = cambiarSiOtro(tocarObjeto(x, y));
      if (!t || t.tri == null) { st.sel.clear(); pintarSeleccion(obj()); pintarPanel(); return; }
      const o = t.o;
      const aditivo = st.aditivo;
      if (!aditivo) st.sel.clear();
      if (st.selModo === 'cara') {
        for (const tri of M.regionPlana(o.malla, t.tri)) st.sel.add(tri);
      } else {
        let mejor = null;
        for (let k = 0; k < 3; k++) {
          const i = o.malla.f[t.tri * 3 + k];
          const d = Math.hypot(o.malla.v[i * 3] - t.local.x, o.malla.v[i * 3 + 1] - t.local.y, o.malla.v[i * 3 + 2] - t.local.z);
          if (!mejor || d < mejor.d) mejor = { i, d };
        }
        st.sel.add(mejor.i);
      }
      pintarSeleccion(o);
      pintarPanel();
    } else if (st.modo === 'escultura') {
      const t = cambiarSiOtro(tocarObjeto(x, y));
      if (t) { recordar(); toquePincel(t); }
    }
  }
  // en Edición / Escultura, tocar OTRO objeto lo vuelve el que editas (en vez de no hacer nada)
  function cambiarSiOtro(t) {
    if (!t || t.o.id === st.activo) return t;
    st.activo = t.o.id;
    st.sel.clear();
    cambio();
    aviso(`Ahora editas «${t.o.nombre}»`);
    return t.tri == null && st.modo === 'edicion' ? null : tocarObjetoDe(t);
  }
  function tocarObjetoDe(t) {
    // después de redibujar, el triángulo tocado sigue siendo el mismo (misma malla)
    const v = vistas.get(t.o.id);
    return v && v.malla.visible ? t : { ...t, tri: null };
  }

  // ---------------------------------------------------------------- gizmo de flechas (modo Objeto)
  const gizmo = new THREE.Group();
  gizmo.renderOrder = 10;
  escena.add(gizmo);
  const ejes = [[1, 0, 0, 0xff4d5e], [0, 1, 0, 0x7fd04b], [0, 0, 1, 0x4d8dff]];
  for (const [x, y, z, color] of ejes) {
    const mat = new THREE.MeshBasicMaterial({ color, depthTest: false });
    const flecha = new THREE.Group();
    const palo = new THREE.Mesh(new THREE.CylinderGeometry(0.035, 0.035, 0.8, 8), mat);
    palo.position.y = 0.4;
    const punta = new THREE.Mesh(new THREE.ConeGeometry(0.1, 0.25, 16), mat);
    punta.position.y = 0.9;
    flecha.add(palo, punta);
    flecha.quaternion.setFromUnitVectors(new THREE.Vector3(0, 1, 0), new THREE.Vector3(x, y, z));
    flecha.userData.eje = [x, y, z];
    flecha.traverse((m) => { m.renderOrder = 10; m.userData.eje = [x, y, z]; });
    gizmo.add(flecha);
  }
  function pintarGizmo() {
    const o = obj();
    gizmo.visible = st.visible && st.modo === 'objeto' && !!o && o.visible !== false;
    if (!gizmo.visible) return;
    const b = cajaMundo(o);
    if (!b) return;
    // las flechas salen desde fuera del objeto: así agarrar el objeto y agarrar una flecha no se confunden
    gizmo.position.set((b.min.x + b.max.x) / 2, (b.min.y + b.max.y) / 2, (b.min.z + b.max.z) / 2);
    const d = camara.position.distanceTo(gizmo.position);
    const k = d * 0.12;
    gizmo.scale.setScalar(k);
    const mitad = b.getSize(new THREE.Vector3()).multiplyScalar(0.5);
    gizmo.children.forEach((f) => { const [x, y, z] = f.userData.eje; f.position.set(x * (mitad.x / k + 0.1), y * (mitad.y / k + 0.1), z * (mitad.z / k + 0.1)); });
  }
  function tocaGizmo(x, y) {
    if (!gizmo.visible) return null;
    rayoDesde(x, y);
    const h = rayo.intersectObject(gizmo, true)[0];
    return h ? h.object.userData.eje : null;
  }
  // cuánto se movió (en mm) a lo largo de un eje del mundo, según cuánto se movió la mano en la pantalla
  function mmEnEje(origen, eje, dx, dy) {
    const a = origen.clone().project(camara), b = origen.clone().add(new THREE.Vector3(...eje)).project(camara);
    const sx = (b.x - a.x) * innerWidth / 2, sy = -(b.y - a.y) * innerHeight / 2;
    const largo2 = sx * sx + sy * sy;
    return largo2 < 1e-6 ? 0 : (dx * sx + dy * sy) / largo2;
  }
  function puntoEnPlano(x, y, z) {
    rayoDesde(x, y);
    const p = new THREE.Vector3();
    return rayo.ray.intersectPlane(new THREE.Plane(new THREE.Vector3(0, 0, 1), -z), p) ? p : null;
  }
  function planoVista(x, y, por) {
    // punto bajo el puntero en un plano de frente a la cámara que pasa por `por`
    rayoDesde(x, y);
    const n = camara.getWorldDirection(new THREE.Vector3());
    const p = new THREE.Vector3();
    return rayo.ray.intersectPlane(new THREE.Plane().setFromNormalAndCoplanarPoint(n, por), p) ? p : null;
  }

  // ---------------------------------------------------------------- agarrar / arrastrar / soltar
  function agarrar(x, y) {
    if (st.modo === 'objeto') {
      const eje = tocaGizmo(x, y);
      const o = obj();
      if (eje && o) {
        recordar();
        st.op = { tipo: 'eje', eje, x0: x, y0: y, pos0: [...o.pos], origen: gizmo.position.clone() };
        return true;
      }
      const t = tocarObjeto(x, y);
      if (!t) return false;
      recordar();
      st.activo = t.o.id;
      const p = puntoEnPlano(x, y, t.o.pos[2]);
      st.op = { tipo: 'mover', dx: t.o.pos[0] - (p ? p.x : 0), dy: t.o.pos[1] - (p ? p.y : 0) };
      cambio();
      return true;
    }
    if (st.modo === 'edicion') {
      const t = tocarObjeto(x, y, true) || cambiarSiOtro(tocarObjeto(x, y));
      const o = obj();
      if (!t || t.tri == null) return false;
      // si tocó algo no elegido, lo elige primero
      const enSel = st.selModo === 'cara' ? st.sel.has(t.tri) : [0, 1, 2].some((k) => st.sel.has(o.malla.f[t.tri * 3 + k]));
      if (!enSel) tocar(x, y);
      if (!st.sel.size) return false;
      recordar();
      empezarEdicion(o, x, y);
      return true;
    }
    if (st.modo === 'escultura') {
      const t = tocarObjeto(x, y, true) || cambiarSiOtro(tocarObjeto(x, y));
      if (!t) return false;
      recordar();
      st.op = { tipo: 'pincel', ultimo: [x, y], local: t.local, lista: null, plano: t.punto.clone() };
      toquePincel(t);
      return true;
    }
    return false;
  }

  function empezarEdicion(o, x, y) {
    const v = vistas.get(o.id);
    const herr = st.selModo === 'vertice' ? 'mover' : st.herramienta;
    if (herr === 'mover') {
      const verts = st.selModo === 'cara' ? [...M.infoRegion(o.malla, st.sel).verts] : [...st.sel];
      st.op = { tipo: 'mover_v', verts, orig: verts.map((i) => [o.malla.v[i * 3], o.malla.v[i * 3 + 1], o.malla.v[i * 3 + 2]]),
                inicio: planoVista(x, y, v.malla.localToWorld(new THREE.Vector3(...M.infoRegion(o.malla, st.sel.size && st.selModo === 'cara' ? st.sel : new Set()).centro || [0, 0, 0]))) };
      if (st.selModo === 'vertice') {
        const c = verts.reduce((s, i) => [s[0] + o.malla.v[i * 3] / verts.length, s[1] + o.malla.v[i * 3 + 1] / verts.length, s[2] + o.malla.v[i * 3 + 2] / verts.length], [0, 0, 0]);
        st.op.inicio = planoVista(x, y, v.malla.localToWorld(new THREE.Vector3(...c)));
      }
      st.op.x0 = x; st.op.y0 = y;
      return;
    }
    const info = M.infoRegion(o.malla, st.sel);
    const { malla, nuevos } = M.anillo(o.malla, st.sel);
    o.malla = malla;
    // la región elegida sigue siendo la cara de arriba (la nueva)
    reconstruir(o);
    pintarSeleccion(o);
    const orig = nuevos.map((i) => [o.malla.v[i * 3], o.malla.v[i * 3 + 1], o.malla.v[i * 3 + 2]]);
    const centroMundo = vistas.get(o.id).malla.localToWorld(new THREE.Vector3(...info.centro));
    const normalMundo = new THREE.Vector3(...info.normal).transformDirection(vistas.get(o.id).malla.matrixWorld);
    st.op = { tipo: herr, nuevos, orig, info, x0: x, y0: y, centroMundo, normalMundo: normalMundo.toArray() };
  }

  function arrastrar(x, y) {
    const op = st.op;
    if (!op) return;
    const o = obj();
    if (!o) return;
    if (op.tipo === 'mover') {
      const p = puntoEnPlano(x, y, o.pos[2]);
      if (!p) return;
      o.pos[0] = Math.round((p.x + op.dx) * 2) / 2;
      o.pos[1] = Math.round((p.y + op.dy) * 2) / 2;
      aplicarTransformacion(vistas.get(o.id).nodo, o);
      pintarGizmo();
      refrescarContorno(o);
    } else if (op.tipo === 'eje') {
      const mm = Math.round(mmEnEje(op.origen, op.eje, x - op.x0, y - op.y0) * 2) / 2;
      for (let k = 0; k < 3; k++) o.pos[k] = op.pos0[k] + op.eje[k] * mm;
      aplicarTransformacion(vistas.get(o.id).nodo, o);
      pintarGizmo();
      refrescarContorno(o);
      st.etiqueta = `${mm >= 0 ? '+' : ''}${mm} mm en ${op.eje[0] ? 'X' : op.eje[1] ? 'Y' : 'Z'}`;
    } else if (op.tipo === 'extruir' || op.tipo === 'biselar' || op.tipo === 'insertar') {
      const n = op.normalMundo;
      const esc = vistas.get(o.id).nodo.scale;
      let d = mmEnEje(op.centroMundo, n, x - op.x0, y - op.y0) / Math.max(1e-6, (esc.x + esc.y + esc.z) / 3);
      d = Math.round(d * 2) / 2;
      const [cx, cy, cz] = op.info.centro, [nx, ny, nz] = op.info.normal;
      if (op.tipo === 'insertar') {
        // jalar hacia afuera o adentro = más o menos margen (de 0 a 95 %)
        const k = Math.max(0.05, Math.min(1, 1 - Math.abs(x - op.x0) / 260));
        op.nuevos.forEach((i, j) => { const p = op.orig[j]; o.malla.v[i * 3] = cx + (p[0] - cx) * k; o.malla.v[i * 3 + 1] = cy + (p[1] - cy) * k; o.malla.v[i * 3 + 2] = cz + (p[2] - cz) * k; });
        st.etiqueta = `margen ${Math.round((1 - k) * 100)} %`;
      } else {
        op.nuevos.forEach((i, j) => {
          const p = op.orig[j];
          let px = p[0] + nx * d, py = p[1] + ny * d, pz = p[2] + nz * d;
          if (op.tipo === 'biselar') {
            // chaflán a 45°: lo que sube, se mete hacia el centro
            const hx = cx - p[0], hy = cy - p[1], hz = cz - p[2];
            const l = Math.hypot(hx, hy, hz);
            const m = Math.min(Math.abs(d), l * 0.95);
            if (l > 1e-6) { px += hx / l * m; py += hy / l * m; pz += hz / l * m; }
          }
          o.malla.v[i * 3] = px; o.malla.v[i * 3 + 1] = py; o.malla.v[i * 3 + 2] = pz;
        });
        st.etiqueta = `${d >= 0 ? '+' : ''}${d} mm`;
      }
      formaCambio(o);
    } else if (op.tipo === 'mover_v') {
      const v = vistas.get(o.id);
      const ahora = planoVista(x, y, op.inicio || new THREE.Vector3());
      if (!ahora || !op.inicio) return;
      const dMundo = ahora.clone().sub(op.inicio);
      const inv = new THREE.Matrix4().copy(v.malla.matrixWorld).invert();
      const dLocal = dMundo.clone().transformDirection(inv).multiplyScalar(dMundo.length() / Math.max(1e-6, dMundo.clone().transformDirection(inv).length()) / ((v.nodo.scale.x + v.nodo.scale.y + v.nodo.scale.z) / 3));
      if (!dMundo.length()) dLocal.set(0, 0, 0);
      op.verts.forEach((i, j) => { const p = op.orig[j]; o.malla.v[i * 3] = p[0] + dLocal.x; o.malla.v[i * 3 + 1] = p[1] + dLocal.y; o.malla.v[i * 3 + 2] = p[2] + dLocal.z; });
      st.etiqueta = `${dMundo.length().toFixed(1)} mm`;
      formaCambio(o);
    } else if (op.tipo === 'pincel') {
      const t = tocarObjeto(x, y, true);
      if (st.pincel === 'agarrar') {
        const v = vistas.get(o.id);
        const ahora = planoVista(x, y, op.plano);
        if (!ahora) return;
        const antes = op.planoUltimo || op.plano;
        const dMundo = ahora.clone().sub(antes);
        op.planoUltimo = ahora;
        const inv = new THREE.Matrix4().copy(v.malla.matrixWorld).invert();
        const a = antes.clone().applyMatrix4(inv), b = ahora.clone().applyMatrix4(inv);
        const delta = [b.x - a.x, b.y - a.y, b.z - a.z];
        if (!op.lista) op.lista = M.bajoPincel(o.malla, [op.local.x, op.local.y, op.local.z], radioLocal(o));
        M.pincelar(o.malla, 'agarrar', null, radioLocal(o), 1, { delta, lista: op.lista });
        if (st.simetria) {
          if (!op.listaEsp) op.listaEsp = M.bajoPincel(o.malla, [-op.local.x, op.local.y, op.local.z], radioLocal(o));
          M.pincelar(o.malla, 'agarrar', null, radioLocal(o), 1, { delta: [-delta[0], delta[1], delta[2]], lista: op.listaEsp });
        }
        formaCambio(o);
        ponerCursor(t || null);
        return;
      }
      if (t) toquePincel(t);
    }
  }
  function refrescarContorno(o) {
    const v = vistas.get(o.id);
    if (v && v.contorno) v.contorno.update();
  }

  function soltar() {
    const op = st.op;
    st.op = null;
    st.etiqueta = '';
    if (!op) return;
    const o = obj();
    if (op.tipo === 'pincel' && o) { formaCambio(o, true); revisarDetalle(); pintarPanel(); return; }
    if ((op.tipo === 'extruir' || op.tipo === 'biselar') && o) {
      // si casi no se jaló, no deja un anillo sin grosor (no sirve para nada)
      const movio = op.nuevos.some((i, j) => Math.hypot(o.malla.v[i * 3] - op.orig[j][0], o.malla.v[i * 3 + 1] - op.orig[j][1], o.malla.v[i * 3 + 2] - op.orig[j][2]) > 0.05);
      if (!movio) { const prev = st.pasado.pop(); if (prev) restaurar(prev); return; }
    }
    cambio();
  }

  // ---------------------------------------------------------------- dos manos
  function dosManos(orden) {
    const o = obj();
    if (!o) return false;
    const ahora = performance.now();
    const nuevo = !st.dos || ahora - st.ultimoDos > 400;
    st.ultimoDos = ahora;
    const [ex, ey] = orden.estirar;
    if (st.modo === 'escultura') {
      st.radio = Math.max(1, Math.min(80, st.radio * Math.sqrt(ex * ey)));
      st.dos = { tipo: 'radio' };
      st.etiqueta = `pincel ${st.radio.toFixed(1)} mm`;
      pintarBarra();
      return true;
    }
    if (st.modo === 'edicion') {
      if (!st.sel.size) return false;
      const verts = st.selModo === 'cara' ? [...M.infoRegion(o.malla, st.sel).verts] : [...st.sel];
      if (nuevo) {
        recordar();
        const info = st.selModo === 'cara' ? M.infoRegion(o.malla, st.sel) : null;
        const c = verts.reduce((s, i) => [s[0] + o.malla.v[i * 3] / verts.length, s[1] + o.malla.v[i * 3 + 1] / verts.length, s[2] + o.malla.v[i * 3 + 2] / verts.length], [0, 0, 0]);
        st.dos = { tipo: 'edicion', verts, c, normal: info ? info.normal : [0, 0, 1] };
      }
      const k = Math.sqrt(ex * ey);
      const [cx, cy, cz] = st.dos.c;
      for (const i of st.dos.verts) {
        o.malla.v[i * 3] = cx + (o.malla.v[i * 3] - cx) * k; o.malla.v[i * 3 + 1] = cy + (o.malla.v[i * 3 + 1] - cy) * k; o.malla.v[i * 3 + 2] = cz + (o.malla.v[i * 3 + 2] - cz) * k;
      }
      if (orden.torcer) {
        // girar lo elegido alrededor de su normal
        const ax = new THREE.Vector3(...st.dos.normal), q = new THREE.Quaternion().setFromAxisAngle(ax, -orden.torcer), p = new THREE.Vector3();
        for (const i of st.dos.verts) {
          p.set(o.malla.v[i * 3] - cx, o.malla.v[i * 3 + 1] - cy, o.malla.v[i * 3 + 2] - cz).applyQuaternion(q);
          o.malla.v[i * 3] = cx + p.x; o.malla.v[i * 3 + 1] = cy + p.y; o.malla.v[i * 3 + 2] = cz + p.z;
        }
      }
      formaCambio(o);
      return true;
    }
    // modo objeto: escalar por ejes y girar en Z
    if (nuevo) { recordar(); st.dos = { tipo: 'objeto', rot: o.rot[2] }; }
    const derecha = new THREE.Vector3().setFromMatrixColumn(camara.matrixWorld, 0);
    const lado = Math.abs(derecha.x) >= Math.abs(derecha.y) ? 0 : 1;
    o.esc[lado] = Math.max(0.05, Math.min(50, o.esc[lado] * ex));
    o.esc[2] = Math.max(0.05, Math.min(50, o.esc[2] * ey));
    if (orden.torcer) {
      st.dos.rot -= orden.torcer / RAD;
      let r = st.dos.rot;
      const cerca = Math.round(r / 15) * 15;
      if (Math.abs(r - cerca) < 4) r = cerca;
      o.rot[2] = Math.round(((r + 540) % 360 - 180) * 10) / 10;
    }
    aplicarTransformacion(vistas.get(o.id).nodo, o);
    refrescarContorno(o);
    pintarGizmo();
    return true;
  }

  // ---------------------------------------------------------------- escultura
  const cursor = new THREE.Mesh(new THREE.RingGeometry(0.92, 1, 48), new THREE.MeshBasicMaterial({ color: 0xffffff, transparent: true, opacity: 0.85, depthTest: false, side: THREE.DoubleSide }));
  cursor.renderOrder = 12;
  cursor.visible = false;
  escena.add(cursor);
  const cursorEsp = cursor.clone();
  cursorEsp.material = cursor.material.clone();
  cursorEsp.material.opacity = 0.35;
  escena.add(cursorEsp);
  function radioLocal(o) { return st.radio / ((o.esc[0] + o.esc[1] + o.esc[2]) / 3); }
  function ponerCursor(t) {
    const enEscultura = st.visible && st.modo === 'escultura' && t;
    cursor.visible = !!enEscultura;
    cursorEsp.visible = !!enEscultura && st.simetria;
    if (!enEscultura) return;
    const n = t.normal ? t.normal.clone().transformDirection(vistas.get(t.o.id).malla.matrixWorld) : new THREE.Vector3(0, 0, 1);
    cursor.position.copy(t.punto).addScaledVector(n, 0.2);
    cursor.quaternion.setFromUnitVectors(new THREE.Vector3(0, 0, 1), n);
    cursor.scale.setScalar(st.radio);
    cursor.material.color.setHex(st.pincel === 'hundir' ? 0x6aa8ff : st.pincel === 'agarrar' ? 0xffc65c : 0xffffff);
    if (st.simetria) {
      const v = vistas.get(t.o.id);
      const espejo = v.malla.localToWorld(new THREE.Vector3(-t.local.x, t.local.y, t.local.z));
      cursorEsp.position.copy(espejo);
      cursorEsp.quaternion.copy(cursor.quaternion);
      cursorEsp.scale.setScalar(st.radio);
    }
  }
  function toquePincel(t) {
    const o = t.o;
    if (st.pincel === 'agarrar') { ponerCursor(t); return; }
    const centro = [t.local.x, t.local.y, t.local.z];
    const r = radioLocal(o);
    const extra = { normales: vistas.get(o.id).geom.getAttribute('normal').array };
    if (st.pincel === 'alisar') extra.vecinos = vecinosDe(o);
    M.pincelar(o.malla, st.pincel, centro, r, st.fuerza, extra);
    if (st.simetria && Math.abs(centro[0]) > r * 0.15) M.pincelar(o.malla, st.pincel, [-centro[0], centro[1], centro[2]], r, st.fuerza, extra);
    formaCambio(o);
    ponerCursor(t);
  }
  const cacheVecinos = new WeakMap();
  function vecinosDe(o) {
    let v = cacheVecinos.get(o.malla.f);
    if (!v) { v = M.vecinos(o.malla); cacheVecinos.set(o.malla.f, v); }
    return v;
  }
  const PINCELES = Object.keys(M.PINCELES);

  // ---------------------------------------------------------------- operaciones de edición (botones y atajos)
  function subdividirObjeto() {
    const o = obj();
    if (!o) return;
    if (M.nTri(o.malla) * 4 > 300000) return aviso('Ya tiene demasiado detalle para subdividir otra vez.');
    recordar();
    o.malla = M.subdividir(o.malla);
    st.sel.clear();
    reconstruir(o);
    aviso(`Subdividido: ${M.nTri(o.malla).toLocaleString('es')} triángulos`);
    cambio();
  }
  function suavizarObjeto() {
    const o = obj();
    if (!o) return;
    recordar();
    o.malla = M.suavizar(o.malla, 3);
    o.plano = false;
    reconstruir(o);
    cambio();
  }
  function insertarRapido() {
    const o = obj();
    if (!o || st.modo !== 'edicion' || st.selModo !== 'cara' || !st.sel.size) return aviso('Elige una cara primero.');
    recordar();
    const info = M.infoRegion(o.malla, st.sel);
    const { malla, nuevos } = M.anillo(o.malla, st.sel);
    o.malla = malla;
    const [cx, cy, cz] = info.centro;
    M.moverVertices(o.malla, nuevos, (x, y, z) => [cx + (x - cx) * 0.75, cy + (y - cy) * 0.75, cz + (z - cz) * 0.75]);
    reconstruir(o);
    cambio();
    aviso('Insertado: ahora extruye la cara de adentro (o vuelve a insertar).');
  }
  function aplicarEscala(o) {
    // como Ctrl+A › Escala en Blender: la escala pasa a la malla y el objeto queda en 1 × 1 × 1 (mismo tamaño)
    const [ex, ey, ez] = o.esc;
    o.malla = M.transformar(o.malla, (x, y, z) => [x * ex, y * ey, z * ez]);
    for (const m of o.mods) { if (m.separacion != null) m.separacion *= ex; if (m.radio != null) m.radio *= ey; }
    o.esc = [1, 1, 1];
    reconstruir(o);
  }
  function aplicarModificadores() {
    const o = obj();
    if (!o || !o.mods.length) return;
    recordar();
    const piezas = M.aplicarModificadores(o.malla, o.mods);
    o.malla = piezas.length === 1 ? piezas[0] : M.juntar(piezas);
    o.mods = [];
    reconstruir(o);
    aviso('Modificadores aplicados a la malla.');
    cambio();
  }

  // ---------------------------------------------------------------- Arché revisa (ayudas con números)
  function revisarDetalle() {
    const o = obj();
    st.aviso = '';
    if (!o || st.modo !== 'escultura') return;
    const arista = M.largoAristaMedio(o.malla) * ((o.esc[0] + o.esc[1] + o.esc[2]) / 3);
    if (st.radio < arista * 2) st.aviso = `Los triángulos miden ${arista.toFixed(1)} mm y el pincel ${st.radio.toFixed(1)} mm: así el pincel hace bultos toscos (o nada). Subdivide para tener detalle, o agranda el pincel.`;
  }
  function revisar() {
    const avisos = [];
    for (const o of st.objetos) {
      if (o.visible === false) continue;
      const b = cajaMundo(o);
      if (!b) continue;
      if (b.min.z < -0.3) avisos.push({ texto: `«${o.nombre}» atraviesa la cama (${(-b.min.z).toFixed(1)} mm por debajo): esa parte no se imprime.`, arreglo: 'Subirlo a la cama', hacer: () => { recordar(); o.pos[2] = Math.round((o.pos[2] - b.min.z) * 10) / 10; cambio(); } });
      else if (b.min.z > 0.3 && !st.objetos.some((x) => x !== o && x.visible !== false && cajaMundo(x) && cajaMundo(x).max.z >= b.min.z - 0.3 && cajaMundo(x).intersectsBox(b.clone().expandByScalar(0.5)))) {
        avisos.push({ texto: `«${o.nombre}» flota ${b.min.z.toFixed(1)} mm sobre la cama, sin nada debajo: la impresora no puede empezar en el aire.`, arreglo: 'Bajarlo a la cama', hacer: () => { recordar(); o.pos[2] = Math.round((o.pos[2] - b.min.z) * 10) / 10; cambio(); } });
      }
      const noUniforme = Math.max(...o.esc) / Math.min(...o.esc) > 1.01;
      if (noUniforme && o.mods.some((m) => !m.apagado && (m.tipo === 'espejo' || (m.tipo === 'matriz' && m.circular)))) {
        // igual que en Blender: con escala desigual, las copias giradas salen deformadas
        avisos.push({ texto: `«${o.nombre}» tiene escala desigual (${o.esc.map((e) => fmt(e, 2)).join(' × ')}): las copias giradas del modificador salen deformadas.`,
          arreglo: 'Aplicar la escala', hacer: () => { recordar(); aplicarEscala(o); cambio(); } });
      }
      const esp = o.mods.find((m) => m.tipo === 'espejo' && !m.apagado);
      if (esp) {
        // la copia del espejo se hace respecto al centro del objeto (su origen): si no lo cruza, quedan separadas
        const e = esp.eje | 0, lim = M.limites(o.malla);
        const hueco = lim.min[e] > 0 ? lim.min[e] * 2 * o.esc[e] : lim.max[e] < 0 ? -lim.max[e] * 2 * o.esc[e] : 0;
        if (hueco > 0.2) avisos.push({ texto: `El espejo de «${o.nombre}» deja ${hueco.toFixed(1)} mm de hueco entre las dos mitades: saldrían separadas.`, arreglo: 'Pegar las mitades', hacer: () => {
          recordar();
          const d = lim.min[e] > 0 ? -lim.min[e] : -lim.max[e];
          o.malla = M.transformar(o.malla, (x, y, z) => { const p = [x, y, z]; p[e] += d; return p; });
          reconstruir(o); cambio();
        } });
      }
    }
    st.avisos = avisos;
  }

  // ---------------------------------------------------------------- guardar y abrir
  function serializar() {
    return { version: 1, objetos: st.objetos.map((o) => ({ nombre: o.nombre, pos: o.pos, rot: o.rot, esc: o.esc, mods: o.mods, visible: o.visible, color: o.color, plano: o.plano,
      v: Array.from(o.malla.v, (x) => Math.round(x * 1000) / 1000), f: Array.from(o.malla.f), g: Array.from(o.malla.g || []) })) };
  }
  function cargarEscena(e) {
    st.objetos = (e.objetos || []).map((o) => ({ id: nuevoId(), nombre: o.nombre, pos: o.pos, rot: o.rot, esc: o.esc, mods: o.mods || [], visible: o.visible !== false,
      color: o.color || COLORES[0], plano: !!o.plano, malla: M.conGrupos({ v: Float32Array.from(o.v), f: Uint32Array.from(o.f), g: o.g && o.g.length ? Int32Array.from(o.g) : undefined }) }));
    st.activo = st.objetos.length ? st.objetos[0].id : null;
    for (const [, v] of vistas) grupo.remove(v.nodo);
    vistas.clear();
    st.modo = 'objeto';
    cambio();
    encuadrar();
  }
  function mallaMundo(o) {
    // la malla final del objeto: con modificadores y en su lugar (como se va a imprimir)
    const v = vistas.get(o.id);
    v.nodo.updateMatrixWorld(true);
    const m4 = v.malla.matrixWorld;
    // cada copia de un modificador va por separado: Arché las une de verdad (si se tocan, quedan una sola pieza)
    return M.aplicarModificadores(o.malla, o.mods).map((junta) => {
      const p = new THREE.Vector3();
      const salida = new Float32Array(junta.v.length);
      for (let i = 0; i < junta.v.length; i += 3) { p.set(junta.v[i], junta.v[i + 1], junta.v[i + 2]).applyMatrix4(m4); salida[i] = p.x; salida[i + 1] = p.y; salida[i + 2] = p.z; }
      const f = Uint32Array.from(junta.f);
      if (m4.determinant() < 0) for (let t = 0; t < f.length; t += 3) { const b = f[t + 1]; f[t + 1] = f[t + 2]; f[t + 2] = b; }
      return { v: Array.from(salida, (x) => Math.round(x * 1000) / 1000), f: Array.from(f) };
    });
  }
  async function guardar(comoNueva) {
    const visibles = st.objetos.filter((o) => o.visible !== false);
    if (!visibles.length) return aviso('No hay nada que guardar.');
    if (st.ocupado) return;
    st.ocupado = true;
    pintarPanel();
    const nombre = (($('#nombreModelar') && $('#nombreModelar').value.trim()) || st.nombre || 'modelado');
    try {
      const r = await enviar('/api/modelar', { nombre, reemplazar: !comoNueva && st.editando === nombre, objetos: visibles.flatMap(mallaMundo), escena: serializar() });
      if (!r.ok) { aviso(r.error || 'No se pudo guardar.'); return; }
      st.nombre = r.nombre;
      st.editando = r.nombre;
      st.info = r.info;
      aviso(`Guardada como ${r.nombre}.stl`);
    } catch (e) { aviso('No pude guardar: ¿Arché sigue abierto?'); }
    finally { st.ocupado = false; pintarPanel(); }
  }
  const cargador = new STLLoader();
  async function importarModelo(nombre) {
    const r = await api('/api/modelo?n=' + encodeURIComponent(nombre));
    const g = cargador.parse(await r.arrayBuffer());
    const pos = g.getAttribute('position').array;
    const idx = Uint32Array.from({ length: pos.length / 3 }, (_, i) => i);
    let malla = M.soldar(pos, idx, 1e-3);
    const lim = M.limites(malla);
    malla = M.transformar(malla, (x, y, z) => [x - (lim.min[0] + lim.max[0]) / 2, y - (lim.min[1] + lim.max[1]) / 2, z - lim.min[2]]);
    agregar(null, M.conGrupos(malla), nombre);
    const o = obj();
    if (!M.cerrada(o.malla)) aviso('Ojo: esa pieza tiene la malla abierta; al guardar puede quedar afuera. Repárala en el Taller.');
  }
  async function cargar(nombre) {
    const d = await apiJson('/api/escena?n=' + encodeURIComponent(nombre)).catch(() => ({}));
    if (d.escena && d.escena.objetos) {
      recordar();
      cargarEscena(d.escena);
      st.nombre = nombre;
      st.editando = nombre;
      pintarPanel();
    } else {
      await importarModelo(nombre);
    }
  }
  function encuadrar() {
    const caja = new THREE.Box3();
    for (const o of st.objetos) { const b = cajaMundo(o); if (b) caja.union(b); }
    if (caja.isEmpty()) { camara.position.set(110, -150, 95); controles.target.set(0, 0, 10); return; }
    const c = caja.getCenter(new THREE.Vector3()), r = Math.max(caja.getSize(new THREE.Vector3()).length() / 2, 20);
    controles.target.copy(c);
    const dir = camara.position.clone().sub(controles.target).normalize();
    camara.position.copy(c).addScaledVector(dir.lengthSq() ? dir : new THREE.Vector3(0.55, -0.75, 0.5).normalize(), r / Math.sin(20 * RAD) * 1.25);
  }

  // ---------------------------------------------------------------- barra de arriba (modos y herramientas, como Blender)
  const barra = document.createElement('div');
  barra.id = 'barraModelar';
  barra.hidden = true;
  document.body.append(barra);
  const navegador = document.createElement('div');
  navegador.id = 'navModelar';
  navegador.hidden = true;
  navegador.innerHTML = ['x', 'y', 'z', '-x', '-y', '-z'].map((e) => `<button data-eje="${e}" data-tocable class="${e[0] === '-' ? 'neg' : ''} e${e.slice(-1)}" title="Vista desde ${e}">${e[0] === '-' ? '' : e.toUpperCase()}</button>`).join('');
  document.body.append(navegador);
  navegador.addEventListener('click', (e) => {
    const b = e.target.closest('button');
    if (!b) return;
    const eje = { x: [1, 0, 0], y: [0, 1, 0], z: [0, 0, 1], '-x': [-1, 0, 0], '-y': [0, -1, 0], '-z': [0, 0, -1] }[b.dataset.eje];
    const d = camara.position.distanceTo(controles.target);
    const n = new THREE.Vector3(...eje);
    if (Math.abs(n.z) > 0.9) n.y = -0.001;            // desde arriba: un pelito inclinado para que la cámara no se voltee
    camara.position.copy(controles.target).addScaledVector(n.normalize(), d);
  });
  function el(tag, attrs = {}, ...hijos) {
    const e = document.createElement(tag);
    for (const [k, v] of Object.entries(attrs)) {
      if (k === 'class') e.className = v;
      else if (k === 'text') e.textContent = v;
      else if (k.startsWith('on')) e.addEventListener(k.slice(2), v);
      else if (v !== false && v != null) e.setAttribute(k, v === true ? '' : v);
    }
    for (const h of hijos) if (h) e.append(h);
    return e;
  }
  const fmt = (n, d = 1) => Number(n).toLocaleString('es', { maximumFractionDigits: d });
  function pintarBarra() {
    if (!st.visible) return;
    barra.innerHTML = '';
    const modos = el('div', { class: 'segmento modos' });
    for (const [k, n] of Object.entries(MODOS)) modos.append(el('button', { class: st.modo === k ? 'activo' : '', text: n, title: k === 'edicion' ? 'Tab' : '', onclick: () => ponerModo(k) }));
    barra.append(modos);
    if (st.modo === 'objeto') {
      for (const [k, f] of Object.entries(FABRICAS)) barra.append(el('button', { class: 'btn', text: '+ ' + f.nombre, onclick: () => agregar(k) }));
    } else if (st.modo === 'edicion') {
      const sel = el('div', { class: 'segmento' });
      for (const [k, n] of [['cara', 'Caras (3)'], ['vertice', 'Vértices (1)']]) sel.append(el('button', { class: st.selModo === k ? 'activo' : '', text: n, onclick: () => { st.selModo = k; st.sel.clear(); cambio(); } }));
      barra.append(sel);
      if (st.selModo === 'cara') {
        const h = el('div', { class: 'segmento' });
        for (const [k, n] of Object.entries(HERRAMIENTAS)) h.append(el('button', { class: st.herramienta === k ? 'activo' : '', text: n, title: { extruir: 'E', insertar: 'I', biselar: 'Ctrl+B', mover: 'G' }[k], onclick: () => { st.herramienta = k; pintarBarra(); } }));
        barra.append(h);
      }
      barra.append(el('button', { class: 'btn' + (st.aditivo ? ' activo' : ''), text: 'Elegir varias', title: 'Mayúscula + clic', onclick: () => { st.aditivo = !st.aditivo; pintarBarra(); } }),
        el('button', { class: 'btn', text: 'Subdividir', onclick: subdividirObjeto }),
        el('button', { class: 'btn', text: 'Suavizar', onclick: suavizarObjeto }));
    } else {
      const p = el('div', { class: 'segmento' });
      for (const [k, n] of Object.entries(M.PINCELES)) p.append(el('button', { class: st.pincel === k ? 'activo' : '', text: n, onclick: () => { st.pincel = k; pintarBarra(); } }));
      barra.append(p);
      const des = (nombre, val, min, max, paso, fn) => {
        const salida = el('output', { text: fmt(val) });
        const r = el('input', { type: 'range', min, max, step: paso, value: val, 'aria-label': nombre, oninput: (e) => { fn(Number(e.target.value)); salida.textContent = fmt(Number(e.target.value)); } });
        return el('label', { class: 'mini' }, el('span', { text: nombre }), r, salida);
      };
      barra.append(des('Radio', st.radio, 1, 60, 0.5, (v) => { st.radio = v; revisarDetalle(); }), des('Fuerza', st.fuerza, 0.05, 1, 0.05, (v) => { st.fuerza = v; }),
        el('button', { class: 'btn' + (st.simetria ? ' activo' : ''), text: 'Simetría X', onclick: () => { st.simetria = !st.simetria; pintarBarra(); } }),
        el('button', { class: 'btn', text: 'Subdividir', onclick: subdividirObjeto }));
    }
  }

  // ---------------------------------------------------------------- panel (outliner + propiedades)
  function pintarPanel() {
    if (!st.visible) return;
    const p = ctx.panel;
    const arriba = p.scrollTop;
    const foco = document.activeElement && document.activeElement.id;
    p.innerHTML = '';
    // outliner
    const lista = el('div', { class: 'outliner' });
    for (const o of st.objetos) {
      lista.append(el('div', { class: 'fila-obj' + (o.id === st.activo ? ' activo' : '') },
        el('button', { class: 'ojo', title: o.visible === false ? 'Mostrar' : 'Ocultar', text: o.visible === false ? '◌' : '●', onclick: () => { o.visible = o.visible === false; cambio(); } }),
        el('button', { class: 'nombre', text: o.nombre, onclick: () => { st.activo = o.id; if (st.modo !== 'objeto') st.sel.clear(); cambio(); } }),
        el('small', { text: `${M.nTri(o.malla).toLocaleString('es')} △` })));
    }
    const t1 = el('div', { class: 'tarjeta' }, el('h2', { text: `Escena · ${st.objetos.length}` }), st.objetos.length ? lista : el('p', { class: 'tenue', text: 'Vacía. Agrega una forma con los botones de abajo (+ Cubo, + Esfera…).' }));
    const propias = st.modelos;
    if (propias.length) {
      const sel = el('select', { class: 'btn', 'aria-label': 'Traer una de tus piezas', onchange: (e) => { if (e.target.value) importarModelo(e.target.value).catch(() => aviso('No pude abrirla.')); e.target.value = ''; } },
        el('option', { value: '', text: '+ Traer una de tus piezas…' }));
      for (const m of propias) sel.append(el('option', { value: m.nombre, text: m.nombre }));
      sel.style.cssText = 'width:100%;margin-top:8px';
      t1.append(sel);
    }
    p.append(t1);

    // Arché revisa
    const avisos = (st.avisos || []).slice();
    if (st.aviso) avisos.unshift({ texto: st.aviso, arreglo: 'Subdividir', hacer: subdividirObjeto });
    if (avisos.length) {
      const ul = el('ul', { class: 'avisos' });
      for (const a of avisos) ul.append(el('li', { text: a.texto }, a.arreglo ? el('button', { class: 'btn sug-aplicar', text: a.arreglo, onclick: a.hacer }) : null));
      p.append(el('div', { class: 'tarjeta arche-sugiere' }, el('h2', { text: 'Arché revisa' }), ul));
    }

    const o = obj();
    if (o) {
      const t2 = el('div', { class: 'tarjeta' }, el('h2', { text: 'Objeto' }));
      const nombre = el('input', { id: 'nombreObj', class: 'btn campo', value: o.nombre, 'aria-label': 'Nombre del objeto', onchange: (e) => { o.nombre = e.target.value || o.nombre; pintarPanel(); } });
      t2.append(nombre);
      const b = cajaMundo(o);
      if (b) {
        const s = b.getSize(new THREE.Vector3());
        t2.append(el('div', { class: 'cifras' }, el('div', { class: 'cifra ancha' }, el('b', { text: `${fmt(s.x)} × ${fmt(s.y)} × ${fmt(s.z)}` }), el('span', { text: 'mm, cómo queda (con modificadores)' }))));
      }
      const fila = (titulo, arr, paso, clave) => {
        const g = el('div', { class: 'vec3' }, el('span', { text: titulo }));
        ['X', 'Y', 'Z'].forEach((n, i) => {
          const inp = el('input', { type: 'number', step: paso, id: `${clave}${i}`, value: String(Math.round(arr[i] * 1000) / 1000), 'aria-label': `${titulo} ${n}`, class: 'e' + n.toLowerCase(),
            onchange: (e) => { recordar(); arr[i] = Number(e.target.value) || 0; if (clave === 'esc') arr[i] = Math.max(0.01, arr[i]); cambio(); } });
          g.append(el('label', {}, el('i', { text: n }), inp));
        });
        return g;
      };
      t2.append(fila('Posición (mm)', o.pos, 0.5, 'pos'), fila('Giro (°)', o.rot, 5, 'rot'), fila('Escala', o.esc, 0.05, 'esc'));
      t2.append(el('div', { class: 'acciones' },
        el('button', { class: 'btn', text: 'Duplicar', title: 'Dedos en V · Mayús+D', onclick: duplicarObjeto }),
        el('button', { class: 'btn', text: 'Apoyar en la cama', onclick: () => { const bb = cajaMundo(o); if (bb) { recordar(); o.pos[2] = Math.round((o.pos[2] - bb.min.z) * 10) / 10; cambio(); } } }),
        o.esc.some((e) => Math.abs(e - 1) > 1e-6) ? el('button', { class: 'btn', text: 'Aplicar escala', title: 'Ctrl+A: la escala pasa a la malla', onclick: () => { recordar(); aplicarEscala(o); cambio(); } }) : null,
        el('button', { class: 'btn peligro', text: 'Borrar', title: 'Pulgar abajo · Supr', onclick: borrarObjeto })));
      p.append(t2);

      // modificadores
      const t3 = el('div', { class: 'tarjeta' }, el('h2', { text: 'Modificadores' }));
      o.mods.forEach((m, i) => {
        const cab = el('div', { class: 'mod-cab' },
          el('b', { text: M.MODIFICADORES[m.tipo].nombre }),
          el('button', { class: 'ojo', text: m.apagado ? '◌' : '●', title: m.apagado ? 'Encender' : 'Apagar', onclick: () => { recordar(); m.apagado = !m.apagado; cambio(); } }),
          el('button', { class: 'ojo', text: '✕', title: 'Quitar', onclick: () => { recordar(); o.mods.splice(i, 1); cambio(); } }));
        const cuerpo = el('div', { class: 'mod-cuerpo' });
        // `factor`: la separación se guarda en medidas del objeto, pero se muestra en mm reales (con su escala)
        const num = (etq, clave, min, max, paso, factor = 1) => el('label', {}, el('span', { text: etq }),
          el('input', { type: 'number', min, max, step: paso, value: Math.round(m[clave] * factor * 10) / 10, class: 'btn campo',
            onchange: (e) => { recordar(); m[clave] = Math.max(min, Math.min(max, Number(e.target.value) || 0)) / factor; cambio(); } }));
        if (m.tipo === 'espejo') {
          const seg = el('div', { class: 'segmento' });
          ['X', 'Y', 'Z'].forEach((n, k) => seg.append(el('button', { class: (m.eje | 0) === k ? 'activo' : '', text: n, onclick: () => { recordar(); m.eje = k; cambio(); } })));
          cuerpo.append(seg);
        } else if (m.tipo === 'matriz') {
          cuerpo.append(num('Copias', 'cantidad', 1, 24, 1));
          if (!m.circular) cuerpo.append(num('Separación (mm)', 'separacion', -500, 500, 1, o.esc[0]));
          else cuerpo.append(num('Radio (mm)', 'radio', 0, 500, 1, o.esc[1]));
          cuerpo.append(el('label', { class: 'interruptor' }, el('input', { type: 'checkbox', checked: !!m.circular, onchange: (e) => { recordar(); m.circular = e.target.checked ? 1 : 0; cambio(); } }), el('span', { text: 'En círculo (alrededor de su centro)' })));
        } else if (m.tipo === 'suavizar') cuerpo.append(num('Vueltas', 'vueltas', 1, 20, 1));
        else if (m.tipo === 'subdividir') cuerpo.append(num('Niveles', 'niveles', 1, 3, 1));
        t3.append(el('div', { class: 'modificador' + (m.apagado ? ' apagado' : '') }, cab, cuerpo));
      });
      const agregarMod = el('select', { class: 'btn', 'aria-label': 'Agregar modificador', onchange: (e) => {
        const tipo = e.target.value;
        if (!tipo) return;
        recordar();
        const mod = { tipo, ...JSON.parse(JSON.stringify(M.MODIFICADORES[tipo].valores)) };
        if (tipo === 'matriz') {
          // como el «desfase relativo» de Blender: cada copia pegada a la anterior (así sale una sola pieza)
          const lim = M.limites(o.malla);
          mod.separacion = Math.round((lim.max[0] - lim.min[0]) * 0.98 * 100) / 100;
        }
        o.mods.push(mod);
        cambio();
      } }, el('option', { value: '', text: '+ Agregar modificador…' }));
      for (const [k, d] of Object.entries(M.MODIFICADORES)) agregarMod.append(el('option', { value: k, text: d.nombre }));
      agregarMod.style.cssText = 'width:100%;margin-top:6px';
      t3.append(agregarMod);
      if (o.mods.length) t3.append(el('div', { class: 'acciones' }, el('button', { class: 'btn', text: 'Aplicar a la malla', title: 'Los vuelve parte de la malla (para esculpir encima)', onclick: aplicarModificadores })));
      p.append(t3);
    }

    // guardar
    const nombre = el('input', { id: 'nombreModelar', class: 'btn campo', value: st.nombre || '', placeholder: 'Nombre de la pieza', 'aria-label': 'Nombre de la pieza', oninput: (e) => { st.nombre = e.target.value; } });
    const t4 = el('div', { class: 'tarjeta' }, el('h2', { text: 'Guardar' }), nombre,
      el('div', { class: 'acciones' },
        el('button', { class: 'btn sug-aplicar', text: st.ocupado ? 'Guardando…' : (st.editando ? 'Guardar cambios' : 'Guardar pieza'), disabled: st.ocupado, title: 'Pulgar arriba · Ctrl+S', onclick: () => guardar(false) }),
        st.editando ? el('button', { class: 'btn', text: 'Guardar como nueva', onclick: () => guardar(true) }) : null,
        el('button', { class: 'btn', text: 'Deshacer', disabled: !st.pasado.length, onclick: deshacer }),
        el('button', { class: 'btn', text: 'Rehacer', disabled: !st.futuro.length, onclick: rehacer })));
    if (st.info) {
      const i = st.info, d = i.dimensiones;
      t4.append(el('p', { class: 'tenue', text: `${st.editando}.stl: ${fmt(d[0])} × ${fmt(d[1])} × ${fmt(d[2])} mm, ${fmt(i.gramos, 0)} g, ${i.tiempo}.` }));
      if (i.avisos.length) t4.append(el('ul', { class: 'avisos' }, ...i.avisos.map((a) => el('li', { text: a }))));
      t4.append(el('div', { class: 'acciones' }, el('button', { class: 'btn', text: 'Verla en el Taller', onclick: () => ctx.irA('taller', st.editando) })));
    }
    // ayuda de manos según el modo
    t4.append(el('details', { class: 'manos-detalles ayuda-construir', open: true }, el('summary', { text: `Con las manos (modo ${MODOS[st.modo]})` }),
      el('ul', { class: 'manos-ayuda' }, ...AYUDA_MANOS[st.modo].map(([g, q]) => el('li', {}, el('b', { text: g }), document.createTextNode(': ' + q))))));
    p.append(t4);
    p.scrollTop = arriba;
    if (foco) { const e = document.getElementById(foco); if (e && e.tagName === 'INPUT') e.focus(); }
  }

  // ---------------------------------------------------------------- mouse y teclado (atajos de Blender)
  let abajo = null;
  render.domElement.addEventListener('pointerdown', (e) => {
    if (!st.visible || e.button !== 0) return;
    abajo = [e.clientX, e.clientY];
    if (e.shiftKey) st.aditivoTecla = true;
    // en escultura y al tocar el gizmo / lo elegido, el arrastre es para la pieza (no para girar la vista)
    const quiere = st.modo === 'escultura' ? !!tocarObjeto(e.clientX, e.clientY, true)
      : st.modo === 'objeto' ? !!(tocaGizmo(e.clientX, e.clientY) || (obj() && tocarObjeto(e.clientX, e.clientY)?.o === obj()))
        : st.sel.size > 0 && !!tocarObjeto(e.clientX, e.clientY, true);
    if (quiere && agarrar(e.clientX, e.clientY)) { controles.enabled = false; render.domElement.setPointerCapture(e.pointerId); }
  });
  render.domElement.addEventListener('pointermove', (e) => {
    if (!st.visible) return;
    if (st.op) arrastrar(e.clientX, e.clientY);
    else if (st.modo === 'escultura') ponerCursor(tocarObjeto(e.clientX, e.clientY, true));
  });
  render.domElement.addEventListener('pointerup', (e) => {
    if (!st.visible) return;
    const quieto = abajo && Math.hypot(e.clientX - abajo[0], e.clientY - abajo[1]) < 5;
    abajo = null;
    const habiaOp = !!st.op;
    if (habiaOp) soltar();
    controles.enabled = st.visible;
    if (quieto && (!habiaOp || st.modo !== 'escultura')) {
      const prev = st.aditivo;
      if (st.aditivoTecla) st.aditivo = true;
      tocar(e.clientX, e.clientY);
      st.aditivo = prev;
    }
    st.aditivoTecla = false;
  });
  addEventListener('keydown', (e) => {
    if (!st.visible) return;
    const t = document.activeElement;
    if (t && /INPUT|SELECT|TEXTAREA/.test(t.tagName) && t.type !== 'range') return;
    const k = e.key.toLowerCase();
    const ctrl = e.ctrlKey || e.metaKey;
    if (k === 'tab') { e.preventDefault(); ponerModo(st.modo === 'edicion' ? 'objeto' : 'edicion'); }
    else if (ctrl && k === 'z') { e.preventDefault(); e.shiftKey ? rehacer() : deshacer(); }
    else if (ctrl && k === 'y') { e.preventDefault(); rehacer(); }
    else if (ctrl && k === 's') { e.preventDefault(); guardar(false); }
    else if (ctrl && k === 'a' && st.modo === 'objeto' && obj()) { e.preventDefault(); recordar(); aplicarEscala(obj()); cambio(); aviso('Escala aplicada'); }
    else if (e.shiftKey && k === 'd' && st.modo === 'objeto') { e.preventDefault(); duplicarObjeto(); }
    else if ((k === 'delete' || k === 'x') && st.modo === 'objeto' && obj()) { e.preventDefault(); borrarObjeto(); }
    else if (st.modo === 'edicion' && k === '1') { st.selModo = 'vertice'; st.sel.clear(); cambio(); }
    else if (st.modo === 'edicion' && k === '3') { st.selModo = 'cara'; st.sel.clear(); cambio(); }
    else if (st.modo === 'edicion' && k === 'a') { e.preventDefault(); const o = obj(); if (o) { st.sel = st.selModo === 'cara' ? new Set(Array.from({ length: M.nTri(o.malla) }, (_, i) => i)) : new Set(Array.from({ length: M.nVert(o.malla) }, (_, i) => i)); pintarSeleccion(o); } }
    else if (st.modo === 'edicion' && k === 'e') { st.herramienta = 'extruir'; pintarBarra(); aviso('Extruir: jala la cara elegida'); }
    else if (st.modo === 'edicion' && k === 'i') { insertarRapido(); }
    else if (st.modo === 'edicion' && ctrl && k === 'b') { e.preventDefault(); st.herramienta = 'biselar'; pintarBarra(); }
    else if (st.modo === 'edicion' && k === 'g') { st.herramienta = 'mover'; pintarBarra(); }
    else if (st.modo === 'escultura' && k === 'f') { st.radio = Math.min(60, st.radio * 1.2); pintarBarra(); }
    else if (st.modo === 'escultura' && e.key === '[') { st.radio = Math.max(1, st.radio / 1.2); pintarBarra(); }
    else if (st.modo === 'escultura' && e.key === ']') { st.radio = Math.min(60, st.radio * 1.2); pintarBarra(); }
    else if (k === '.' || e.key === 'Home') encuadrar();
  });

  const pA = new THREE.Vector3();
  const etqOp = ctx.etiqueta('medida');
  return {
    escena, camara, controles,
    entrar() {
      st.visible = true;
      controles.enabled = true;
      barra.hidden = false;
      navegador.hidden = false;
      document.body.classList.add('modelando');
      apiJson('/api/modelos').then((d) => { st.modelos = d.modelos; pintarPanel(); }).catch(() => {});
      if (!st.objetos.length) { agregar('cubo'); st.pasado = []; }
      cambio();
    },
    salir() {
      st.visible = false;
      controles.enabled = false;
      if (st.op) soltar();
      barra.hidden = true;
      navegador.hidden = true;
      cursor.visible = cursorEsp.visible = false;
      etqOp.style.display = 'none';
      document.body.classList.remove('modelando');
    },
    reencuadrar: encuadrar,
    cargar,
    // ---- desde las manos ----
    tocar, agarrar, arrastrar, soltar, dosManos,
    puntero(x, y) { if (st.modo === 'escultura' && !st.op) ponerCursor(x == null ? null : tocarObjeto(x, y, true)); },
    deslizar(dir) { if (dir === 'izquierda') deshacer(); else rehacer(); return true; },
    aceptar() { guardar(false); },
    rechazar() {
      if (st.modo === 'objeto') borrarObjeto();
      else if (st.modo === 'edicion') { st.sel.clear(); pintarSeleccion(obj()); pintarPanel(); aviso('Selección soltada'); }
      else { st.pincel = PINCELES[(PINCELES.indexOf(st.pincel) + 1) % PINCELES.length]; pintarBarra(); aviso('Pincel: ' + M.PINCELES[st.pincel]); }
    },
    duplicar() {
      if (st.modo === 'objeto') duplicarObjeto();
      else if (st.modo === 'edicion') insertarRapido();
      else { st.pincel = st.pincel === 'inflar' ? 'hundir' : 'inflar'; pintarBarra(); aviso('Pincel: ' + M.PINCELES[st.pincel]); }
    },
    // para pruebas
    estado: () => ({ modo: st.modo, objetos: st.objetos.map((o) => ({ nombre: o.nombre, pos: [...o.pos], rot: [...o.rot], esc: [...o.esc], tris: M.nTri(o.malla), verts: M.nVert(o.malla), cerrada: M.cerrada(o.malla), volumen: M.volumen(o.malla), mods: o.mods.length, lim: M.limites(o.malla) })),
                     sel: st.sel.size, activo: obj() ? obj().nombre : null, pincel: st.pincel, radio: st.radio, avisos: (st.avisos || []).map((a) => a.texto).concat(st.aviso ? [st.aviso] : []) }),
    ponerModo, agregar,
    pantalla(x, y, z) {
      const v = vistas.get(st.activo);
      v.malla.updateMatrixWorld(true);
      const q = v.malla.localToWorld(new THREE.Vector3(x, y, z)).project(camara);
      return [(q.x * 0.5 + 0.5) * innerWidth, (-q.y * 0.5 + 0.5) * innerHeight];
    },
    rayo: (x, y) => [tocarObjeto(x, y, true), tocarObjeto(x, y)].map((t) => t && t.o.nombre),
    alEstado() {},
    actualizar() {
      if (st.dos && performance.now() - st.ultimoDos > 450) {
        const tipo = st.dos.tipo;
        st.dos = null;
        st.etiqueta = '';
        if (tipo === 'radio') { revisarDetalle(); pintarPanel(); } else cambio();
      }
      pintarGizmo();
      if (st.etiqueta && st.visible) {
        etqOp.textContent = st.etiqueta;
        const o = obj();
        const b = o && cajaMundo(o);
        if (b) ctx.colocar(etqOp, pA.set((b.min.x + b.max.x) / 2, (b.min.y + b.max.y) / 2, b.max.z + 8), camara);
      } else etqOp.style.display = 'none';
      for (const [, v] of vistas) if (v.contorno) v.contorno.update();
    },
  };
}
