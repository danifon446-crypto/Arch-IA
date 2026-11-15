// Construir: armas tu propia pieza juntando formas (y restando agujeros), con las manos o con el mouse.
// Lo que ves mientras mueves son las partes; al soltar, Arché arma el sólido EXACTO en el PC
// (el mismo que se imprime) y te dice si algo no va a salir bien.
import * as THREE from 'three';
import { OrbitControls } from './lib/OrbitControls.js';
import { STLLoader } from './lib/STLLoader.js';

const FORMAS = {
  caja: { nombre: 'Caja', medidas: { x: [20, 1, 300], y: [20, 1, 300], z: [10, 0.6, 300] } },
  cilindro: { nombre: 'Cilindro', medidas: { diametro: [16, 1, 300], alto: [12, 0.6, 300] } },
  esfera: { nombre: 'Esfera', medidas: { diametro: [16, 1, 300] } },
  cono: { nombre: 'Cono', medidas: { diametro: [18, 1, 300], punta: [0, 0, 300], alto: [18, 0.6, 300] } },
  prisma: { nombre: 'Prisma', medidas: { lados: [6, 3, 12], diametro: [16, 1, 300], alto: [10, 0.6, 300] } },
  modelo: { nombre: 'Pieza', medidas: { escala: [1, 0.1, 5] } },
};
const NOMBRE_MEDIDA = { x: 'Largo (X)', y: 'Ancho (Y)', z: 'Alto (Z)', diametro: 'Diámetro', alto: 'Alto', punta: 'Punta', lados: 'Lados', escala: 'Escala' };
const PLANTILLAS = {
  'Placa con 4 agujeros': [
    { forma: 'caja', medidas: { x: 80, y: 50, z: 4 }, pos: [0, 0, 0] },
    ...[[-32, -17], [32, -17], [-32, 17], [32, 17]].map(([x, y]) => ({ forma: 'cilindro', restar: true, medidas: { diametro: 3.2, alto: 10 }, pos: [x, y, -3] })),
  ],
  'Soporte en L': [
    { forma: 'caja', medidas: { x: 50, y: 30, z: 4 }, pos: [0, 0, 0] },
    { forma: 'caja', medidas: { x: 4, y: 30, z: 40 }, pos: [-23, 0, 4] },
    { forma: 'cilindro', restar: true, medidas: { diametro: 4.3, alto: 10 }, pos: [10, 0, -3] },
    { forma: 'cilindro', restar: true, medidas: { diametro: 4.3, alto: 10 }, pos: [-27, 0, 28], rot: [0, 90, 0] },
  ],
  'Caja abierta': [
    { forma: 'caja', medidas: { x: 60, y: 40, z: 30 }, pos: [0, 0, 0] },
    { forma: 'caja', restar: true, medidas: { x: 56, y: 36, z: 30 }, pos: [0, 0, 2] },
  ],
};
const PASO = 1;                   // mm: todo se acomoda a milímetros enteros
const IMAN = 2.5;                 // mm: a esta distancia se pega a bordes y centros de otras partes
const RAD = Math.PI / 180;
const norm = (t) => (t || '').toLowerCase().normalize('NFD').replace(/[̀-ͯ]/g, '').replace(/\s+/g, ' ').trim();

export function crearConstruir(ctx) {
  const { render, apiJson, api, enviar, aviso, $ } = ctx;
  const escena = new THREE.Scene();
  escena.fog = new THREE.Fog(0x0c0c14, 900, 2600);
  const camara = new THREE.PerspectiveCamera(38, 1, 1, 6000);
  camara.up.set(0, 0, 1);
  camara.position.set(170, -230, 170);
  const controles = new OrbitControls(camara, render.domElement);
  controles.enableDamping = true;
  controles.dampingFactor = 0.09;
  controles.target.set(0, 0, 10);
  controles.maxPolarAngle = Math.PI * 0.495;
  controles.enabled = false;
  escena.add(new THREE.HemisphereLight(0xcfd4ff, 0x1a1a26, 1.15));
  const sol = new THREE.DirectionalLight(0xffffff, 1.5);
  sol.position.set(0.4, -0.6, 1);
  camara.add(sol);
  escena.add(camara);

  // ---- la cama ----
  const cama = new THREE.Group();
  escena.add(cama);
  let medidaCama = [220, 220, 250];
  function pintarCama() {
    cama.clear();
    const [x, y, z] = medidaCama;
    const piso = new THREE.Mesh(new THREE.PlaneGeometry(x, y), new THREE.MeshBasicMaterial({ color: 0x14141f, side: THREE.DoubleSide }));
    piso.position.z = -0.15;
    cama.add(piso);
    const pts = [];
    for (let i = -x / 2; i <= x / 2 + 0.01; i += 10) pts.push(i, -y / 2, 0, i, y / 2, 0);
    for (let j = -y / 2; j <= y / 2 + 0.01; j += 10) pts.push(-x / 2, j, 0, x / 2, j, 0);
    const g = new THREE.BufferGeometry();
    g.setAttribute('position', new THREE.Float32BufferAttribute(pts, 3));
    cama.add(new THREE.LineSegments(g, new THREE.LineBasicMaterial({ color: 0x2c2c40 })));
    const borde = new THREE.LineSegments(new THREE.EdgesGeometry(new THREE.BoxGeometry(x, y, z)),
      new THREE.LineBasicMaterial({ color: 0x8b7cff, transparent: true, opacity: 0.18 }));
    borde.position.z = z / 2;
    cama.add(borde);
  }
  pintarCama();

  // ---- estado ----
  const st = { visible: false, partes: [], sel: null, pasado: [], futuro: [], nombre: '', editando: null, info: null,
               error: '', pidiendo: 0, version: 0, arrastre: null, estirando: null, ultimoDos: 0, modelos: [], ocupado: false };
  let siguienteId = 1;
  const nuevoId = () => 'p' + (siguienteId++) + Math.random().toString(36).slice(2, 5);

  // ---- materiales ----
  const matSuma = new THREE.MeshStandardMaterial({ color: 0x9a8cff, roughness: 0.55, metalness: 0.08, transparent: true, opacity: 0.9 });
  const matResta = new THREE.MeshStandardMaterial({ color: 0xff5d7a, roughness: 0.6, transparent: true, opacity: 0.28, depthWrite: false });
  const matMal = new THREE.MeshStandardMaterial({ color: 0xff7088, roughness: 0.55, transparent: true, opacity: 0.85 });
  const matResultado = new THREE.MeshStandardMaterial({ color: 0x9a8cff, roughness: 0.55, metalness: 0.08 });
  const matBordeSel = new THREE.LineBasicMaterial({ color: 0x5fd3c4, depthTest: false, transparent: true });
  const matMarco = new THREE.LineDashedMaterial({ color: 0x5fd3c4, dashSize: 2, gapSize: 1.5, transparent: true, opacity: 0.7, depthTest: false });
  const matGuia = new THREE.LineBasicMaterial({ color: 0xffc65c, transparent: true, opacity: 0.85, depthTest: false });

  const grupoPartes = new THREE.Group();
  escena.add(grupoPartes);
  const resultado = new THREE.Mesh(new THREE.BufferGeometry(), matResultado);
  resultado.visible = false;
  escena.add(resultado);
  const guias = new THREE.Group();
  escena.add(guias);
  const etqs = { a: ctx.etiqueta('x'), b: ctx.etiqueta('y'), c: ctx.etiqueta('z'), giro: ctx.etiqueta('medida') };
  const cargador = new STLLoader();
  const geomModelo = {};            // nombre -> geometría centrada y apoyada (como la deja el servidor)

  async function geometriaModelo(nombre) {
    if (geomModelo[nombre]) return geomModelo[nombre];
    const r = await api('/api/modelo?n=' + encodeURIComponent(nombre));
    const g = cargador.parse(await r.arrayBuffer());
    g.computeBoundingBox();
    const b = g.boundingBox;
    g.translate(-(b.min.x + b.max.x) / 2, -(b.min.y + b.max.y) / 2, -b.min.z);
    g.computeVertexNormals();
    geomModelo[nombre] = g;
    return g;
  }

  // la geometría de una parte, igual a como la arma el servidor (centrada en X/Y, apoyada en Z=0)
  function geometria(p) {
    const m = p.medidas;
    let g;
    if (p.forma === 'caja') { g = new THREE.BoxGeometry(m.x, m.y, m.z); g.translate(0, 0, m.z / 2); }
    else if (p.forma === 'cilindro') { g = new THREE.CylinderGeometry(m.diametro / 2, m.diametro / 2, m.alto, 48); g.rotateX(Math.PI / 2); g.translate(0, 0, m.alto / 2); }
    else if (p.forma === 'esfera') { g = new THREE.SphereGeometry(m.diametro / 2, 40, 24); g.translate(0, 0, m.diametro / 2); }
    else if (p.forma === 'cono') { g = new THREE.CylinderGeometry(m.punta / 2, m.diametro / 2, m.alto, 48); g.rotateX(Math.PI / 2); g.translate(0, 0, m.alto / 2); }
    else if (p.forma === 'prisma') { g = new THREE.CylinderGeometry(m.diametro / 2, m.diametro / 2, m.alto, Math.round(m.lados)); g.rotateX(Math.PI / 2); g.rotateZ(Math.PI / 2); g.translate(0, 0, m.alto / 2); }
    else if (p.forma === 'modelo') {
      g = (geomModelo[p.modelo] || new THREE.BoxGeometry(10, 10, 10).translate(0, 0, 5)).clone();
      g.scale(m.escala || 1, m.escala || 1, m.escala || 1);
    }
    return g;
  }

  function pintarPartes() {
    grupoPartes.children.forEach((h) => { h.traverse((o) => o.geometry && o.geometry.dispose()); });
    grupoPartes.clear();
    const problemas = (st.info && st.info.problemas) || {};
    for (const p of st.partes) {
      const g = geometria(p);
      const malo = problemas[p.id];
      const malla = new THREE.Mesh(g, p.restar ? matResta : malo ? matMal : matSuma);
      const nodo = new THREE.Group();
      nodo.add(malla);
      nodo.position.set(...p.pos);
      nodo.rotation.order = 'ZYX';                     // igual que el servidor: primero X, luego Y, luego Z
      nodo.rotation.set((p.rot || [0, 0, 0])[0] * RAD, (p.rot || [0, 0, 0])[1] * RAD, (p.rot || [0, 0, 0])[2] * RAD);
      nodo.userData.id = p.id;
      malla.userData.id = p.id;
      if (p.restar) {
        const bordes = new THREE.LineSegments(new THREE.EdgesGeometry(g, 25), new THREE.LineBasicMaterial({ color: 0xff7088, transparent: true, opacity: 0.8 }));
        nodo.add(bordes);
      }
      if (p.id === st.sel) {
        // la elegida: su contorno y una caja que la abraza (se ve bien hasta en las esferas)
        const sel = new THREE.LineSegments(new THREE.EdgesGeometry(g, 25), matBordeSel);
        sel.renderOrder = 5;
        nodo.add(sel);
        g.computeBoundingBox();
        const bb = g.boundingBox, tam = bb.getSize(new THREE.Vector3()).addScalar(1.2);
        const marco = new THREE.LineSegments(new THREE.EdgesGeometry(new THREE.BoxGeometry(tam.x, tam.y, tam.z)), matMarco);
        marco.position.copy(bb.getCenter(new THREE.Vector3()));
        marco.computeLineDistances();
        marco.renderOrder = 5;
        nodo.add(marco);
      }
      grupoPartes.add(nodo);
    }
    actualizarVisibilidad();
  }

  // mientras mueves se ven las partes; quieto, el resultado exacto (con los agujeros de verdad)
  function actualizarVisibilidad() {
    const quieto = !st.arrastre && !st.estirando && st.info && !st.pidiendo && st.version === st.versionInfo;
    resultado.visible = !!quieto && resultado.geometry.attributes.position;
    for (const nodo of grupoPartes.children) {
      const p = st.partes.find((x) => x.id === nodo.userData.id);
      const malla = nodo.children[0];
      if (!p || !malla) continue;
      // con el resultado a la vista, las partes sólidas se esconden (salvo la elegida, como contorno)
      malla.visible = !resultado.visible || p.restar;
      if (resultado.visible && p.restar) malla.material = matResta;
    }
  }

  // ---- historial (deshacer / rehacer) ----
  const foto = () => JSON.stringify({ partes: st.partes, sel: st.sel });
  function recordar() {
    st.pasado.push(foto());
    if (st.pasado.length > 120) st.pasado.shift();
    st.futuro = [];
  }
  function restaurar(texto) {
    const d = JSON.parse(texto);
    st.partes = d.partes;
    st.sel = d.sel;
    cambio();
  }
  function deshacer() {
    if (!st.pasado.length) { aviso('No hay nada que deshacer.'); return; }
    st.futuro.push(foto());
    restaurar(st.pasado.pop());
    aviso('Deshecho');
  }
  function rehacer() {
    if (!st.futuro.length) { aviso('No hay nada que rehacer.'); return; }
    st.pasado.push(foto());
    restaurar(st.futuro.pop());
    aviso('Rehecho');
  }

  // ---- cada cambio: se dibuja, se guarda el borrador y se pide el sólido exacto ----
  let relojPrevia = 0;
  function cambio(inmediato) {
    st.version++;
    pintarPartes();
    pintarPanel();
    try { localStorage.setItem('arche3d-construir', JSON.stringify({ partes: st.partes, nombre: st.nombre, editando: st.editando })); } catch (e) { /* sin almacenamiento */ }
    clearTimeout(relojPrevia);
    if (st.arrastre || st.estirando) return;
    relojPrevia = setTimeout(pedirPrevia, inmediato ? 0 : 320);
  }

  async function pedirPrevia() {
    const v = st.version;
    if (!st.partes.length) { st.info = null; st.error = ''; resultado.visible = false; pintarPanel(); return; }
    st.pidiendo++;
    actualizarVisibilidad();
    try {
      const r = await enviar('/api/construir', { partes: st.partes });
      if (v !== st.version) return;                  // ya cambió otra vez: esta respuesta es vieja
      if (!r.ok) { st.error = r.error || 'No se pudo armar.'; st.info = null; }
      else {
        st.error = '';
        st.info = r.info;
        st.versionInfo = v;
        const bytes = Uint8Array.from(atob(r.stl), (c) => c.charCodeAt(0));
        const g = cargador.parse(bytes.buffer);
        g.computeVertexNormals();
        // el servidor la deja apoyada y centrada; la llevamos de vuelta a donde están las partes
        g.computeBoundingBox();
        const caja = cajaPartes(false);
        if (caja) {
          const b = g.boundingBox;
          g.translate((caja.min.x + caja.max.x) / 2 - (b.min.x + b.max.x) / 2, (caja.min.y + caja.max.y) / 2 - (b.min.y + b.max.y) / 2, caja.min.z - b.min.z);
        }
        resultado.geometry.dispose();
        resultado.geometry = g;
      }
    } catch (e) {
      if (v === st.version) st.error = 'No pude hablar con Arché.';
    } finally {
      st.pidiendo--;
    }
    pintarPartes();
    pintarPanel();
  }

  // caja que ocupan las partes sólidas (con sus giros), en mm
  function cajaPartes(conAgujeros) {
    const caja = new THREE.Box3();
    let hay = false;
    grupoPartes.updateMatrixWorld(true);
    for (const nodo of grupoPartes.children) {
      const p = st.partes.find((x) => x.id === nodo.userData.id);
      if (!p || (p.restar && !conAgujeros)) continue;
      caja.expandByObject(nodo.children[0]);
      hay = true;
    }
    return hay ? caja : null;
  }
  function cajaDe(id) {
    const nodo = grupoPartes.children.find((n) => n.userData.id === id);
    if (!nodo) return null;
    nodo.updateMatrixWorld(true);
    return new THREE.Box3().setFromObject(nodo.children[0]);
  }

  // ---- partes ----
  const parte = (id) => st.partes.find((p) => p.id === id);
  function agregar(forma, extra = {}) {
    recordar();
    const medidas = {};
    for (const [k, [def]] of Object.entries(FORMAS[forma].medidas)) medidas[k] = def;
    Object.assign(medidas, extra.medidas || {});
    const p = { id: nuevoId(), forma, medidas, pos: [0, 0, 0], rot: [0, 0, 0], restar: !!extra.restar, modelo: extra.modelo };
    // aparece junto a la elegida (o en el centro), sin quedar debajo de otra
    const ref = st.sel && cajaDe(st.sel);
    if (extra.pos) p.pos = extra.pos.slice();
    else if (ref && p.restar) p.pos = [Math.round((ref.min.x + ref.max.x) / 2), Math.round((ref.min.y + ref.max.y) / 2), Math.round(ref.min.z) - 1];
    else if (ref) p.pos = [Math.round(ref.max.x + 2 + (medidas.x || medidas.diametro || 20) / 2), Math.round((ref.min.y + ref.max.y) / 2), 0];
    if (p.restar && !(extra.medidas && (extra.medidas.alto || extra.medidas.z))) {
      // el agujero atraviesa la parte donde cae (con 1 mm de sobra por cada lado), no toda la pieza
      const alto = ref ? Math.ceil(ref.max.z - ref.min.z) + 2 : Math.max(10, Math.ceil((cajaPartes(false) || { max: { z: 10 } }).max.z) + 2);
      if (p.forma === 'cilindro') p.medidas.alto = alto;
      if (p.forma === 'caja') p.medidas.z = alto;
    }
    st.partes.push(p);
    st.sel = p.id;
    cambio();
    return p;
  }
  function borrar() {
    if (!st.sel) { aviso('Primero elige una parte (tócala).'); return; }
    recordar();
    st.partes = st.partes.filter((p) => p.id !== st.sel);
    st.sel = null;
    aviso('Parte borrada (deslizar a la izquierda la recupera).');
    cambio();
  }
  function duplicar() {
    const p = parte(st.sel);
    if (!p) { aviso('Primero elige una parte (tócala).'); return; }
    recordar();
    const b = cajaDe(p.id);
    const copia = JSON.parse(JSON.stringify(p));
    copia.id = nuevoId();
    copia.pos[0] = Math.round(copia.pos[0] + (b ? b.max.x - b.min.x : 10) + 4);
    st.partes.push(copia);
    st.sel = copia.id;
    aviso('Duplicada');
    cambio();
  }
  function elegirParte(id) {
    st.sel = id;
    pintarPartes();
    pintarPanel();
  }

  // ---- tocar / agarrar / mover ----
  const rayo = new THREE.Raycaster();
  const raton = new THREE.Vector2();
  function parteBajo(x, y) {
    raton.set((x / innerWidth) * 2 - 1, -(y / innerHeight) * 2 + 1);
    rayo.setFromCamera(raton, camara);
    const mallas = grupoPartes.children.map((n) => n.children[0]).filter((m) => m);
    // primero las sólidas (los agujeros son medio invisibles), luego los agujeros
    const toques = rayo.intersectObjects(mallas, false);
    const solida = toques.find((h) => !parte(h.object.userData.id)?.restar);
    const hit = toques.length ? (toques.find((h) => h.object.userData.id === st.sel) || solida || toques[0]) : null;
    return hit ? { id: hit.object.userData.id, punto: hit.point } : null;
  }
  function puntoEnPlano(x, y, z) {
    raton.set((x / innerWidth) * 2 - 1, -(y / innerHeight) * 2 + 1);
    rayo.setFromCamera(raton, camara);
    const plano = new THREE.Plane(new THREE.Vector3(0, 0, 1), -z);
    const p = new THREE.Vector3();
    return rayo.ray.intersectPlane(plano, p) ? p : null;
  }
  function empezarArrastre(x, y) {
    const toque = parteBajo(x, y);
    if (!toque) return false;
    const p = parte(toque.id);
    const plano = p.pos[2];
    const punto = puntoEnPlano(x, y, plano);
    if (!punto) return false;
    recordar();
    st.sel = p.id;
    st.arrastre = { id: p.id, dx: p.pos[0] - punto.x, dy: p.pos[1] - punto.y, z: plano, movio: false };
    controles.enabled = false;
    pintarPartes();
    pintarPanel();
    return true;
  }
  function arrastrar(x, y) {
    const a = st.arrastre;
    if (!a) return;
    const p = parte(a.id);
    const punto = puntoEnPlano(x, y, a.z);
    if (!p || !punto) return;
    let nx = Math.round((punto.x + a.dx) / PASO) * PASO, ny = Math.round((punto.y + a.dy) / PASO) * PASO;
    // imán: centros y bordes de las otras partes
    guias.clear();
    const yo = cajaDe(p.id);
    if (yo) {
      const ancho = [(yo.max.x - yo.min.x) / 2, (yo.max.y - yo.min.y) / 2];
      const desfase = [(yo.min.x + yo.max.x) / 2 - p.pos[0], (yo.min.y + yo.max.y) / 2 - p.pos[1]];
      for (const eje of [0, 1]) {
        let mejor = null;
        const centro = (eje ? ny : nx) + desfase[eje];
        for (const otra of st.partes) {
          if (otra.id === p.id) continue;
          const b = cajaDe(otra.id);
          if (!b) continue;
          const lo = eje ? b.min.y : b.min.x, hi = eje ? b.max.y : b.max.x;
          // mi centro con su centro, mis bordes con sus bordes, o pegada por fuera
          const candidatos = [[(lo + hi) / 2, 0], [lo, -ancho[eje]], [hi, ancho[eje]], [lo, ancho[eje]], [hi, -ancho[eje]]];
          for (const [linea, off] of candidatos) {
            const d = Math.abs(centro + off - linea);
            if (d < IMAN && (!mejor || d < mejor.d)) mejor = { d, valor: linea - off - desfase[eje], linea };
          }
        }
        if (mejor) {
          if (eje) ny = mejor.valor; else nx = mejor.valor;
          const g = new THREE.BufferGeometry().setFromPoints(eje
            ? [new THREE.Vector3(-medidaCama[0] / 2, mejor.linea, 0.2), new THREE.Vector3(medidaCama[0] / 2, mejor.linea, 0.2)]
            : [new THREE.Vector3(mejor.linea, -medidaCama[1] / 2, 0.2), new THREE.Vector3(mejor.linea, medidaCama[1] / 2, 0.2)]);
          const l = new THREE.Line(g, matGuia);
          l.renderOrder = 6;
          guias.add(l);
        }
      }
    }
    if (nx !== p.pos[0] || ny !== p.pos[1]) {
      p.pos[0] = Math.round(nx * 10) / 10;
      p.pos[1] = Math.round(ny * 10) / 10;
      a.movio = true;
      const nodo = grupoPartes.children.find((n) => n.userData.id === p.id);
      if (nodo) nodo.position.set(...p.pos);
      actualizarVisibilidad();
      pintarPosicion();
    }
  }
  function soltar() {
    const a = st.arrastre;
    if (!a) return;
    st.arrastre = null;
    guias.clear();
    controles.enabled = st.visible;
    if (!a.movio) st.pasado.pop();           // fue solo un toque: no ensucia el historial
    cambio(true);
  }

  // ---- dos manos sobre la parte elegida: estirar y girar ----
  function dosManos(orden) {
    const p = parte(st.sel);
    if (!p) return false;
    const ahora = performance.now();
    if (!st.estirando || ahora - st.ultimoDos > 400) {
      recordar();
      st.estirando = { rot: (p.rot || [0, 0, 0])[2], medidas: { ...p.medidas } };
    }
    st.ultimoDos = ahora;
    const [ex, ey] = orden.estirar;
    // ¿qué eje del mundo queda «de lado» en la pantalla? (X o Y, según hacia dónde mires)
    const derecha = new THREE.Vector3().setFromMatrixColumn(camara.matrixWorld, 0);
    const lado = Math.abs(derecha.x) >= Math.abs(derecha.y) ? 'x' : 'y';
    const m = p.medidas, lim = FORMAS[p.forma].medidas;
    const poner = (k, f) => { if (lim[k] && f !== 1) m[k] = Math.max(lim[k][1], Math.min(lim[k][2], Math.round(m[k] * f * 10) / 10)); };
    if (p.forma === 'caja') { poner(lado, ex); poner('z', ey); }
    else if (p.forma === 'esfera') poner('diametro', Math.abs(ex - 1) > Math.abs(ey - 1) ? ex : ey);
    else if (p.forma === 'modelo') poner('escala', Math.abs(ex - 1) > Math.abs(ey - 1) ? ex : ey);
    else { poner('diametro', ex); poner('alto', ey); }
    if (orden.torcer) {
      if (!p.rot) p.rot = [0, 0, 0];
      st.estirando.rot -= orden.torcer / RAD;
      let r = st.estirando.rot;
      const cerca = Math.round(r / 15) * 15;
      if (Math.abs(r - cerca) < 4) r = cerca;           // se pega a 0°, 15°, 30°, 45°, 90°…
      p.rot[2] = Math.round(((r + 540) % 360 - 180) * 10) / 10;
    }
    pintarPartes();
    pintarPanel();
    return true;
  }

  // ---- arreglos que propone Arché ----
  function juntar(id) {
    // acerca la parte suelta a la más cercana hasta que se crucen 1 mm, y la baja a la cama si flotaba
    const p = parte(id), yo = cajaDe(id);
    if (!p || !yo) return;
    let mejor = null;
    for (const otra of st.partes) {
      if (otra.id === id || otra.restar) continue;
      const b = cajaDe(otra.id);
      const d = yo.getCenter(new THREE.Vector3()).distanceTo(b.getCenter(new THREE.Vector3()));
      if (!mejor || d < mejor.d) mejor = { d, b };
    }
    if (!mejor) return;
    recordar();
    const b = mejor.b;
    const cy = yo.getCenter(new THREE.Vector3()), cb = b.getCenter(new THREE.Vector3());
    for (const [i, eje] of [[0, 'x'], [1, 'y']]) {
      if (yo.max[eje] < b.min[eje]) p.pos[i] += b.min[eje] - yo.max[eje] + 1;
      else if (yo.min[eje] > b.max[eje]) p.pos[i] -= yo.min[eje] - b.max[eje] + 1;
    }
    if (yo.min.z > b.max.z || yo.max.z < b.min.z) p.pos[2] += (cb.z - cy.z);
    if (yo.min.z > 0.01 && yo.min.z > b.max.z) p.pos[2] -= yo.min.z;
    p.pos = p.pos.map((v) => Math.round(v * 10) / 10);
    st.sel = id;
    aviso('La acerqué hasta que se cruzan 1 mm.');
    cambio(true);
  }
  function aplicarAviso(a) {
    if (a.cambio) {
      const p = parte(a.cambio.parte);
      if (!p) return;
      recordar();
      p.medidas[a.cambio.medida] = a.cambio.valor;
      st.sel = p.id;
      aviso(`Agujero a ${a.cambio.valor} mm`);
      cambio(true);
    } else if (a.id === 'sueltas') {
      // Arché calculó en el PC cuánto mover cada parte suelta para que toque a la más cercana (1 mm de cruce)
      const mover = (st.info && st.info.juntar) || {};
      const ids = Object.keys(mover).filter((id) => parte(id));
      if (!ids.length) { for (const id of Object.keys((st.info && st.info.problemas) || {})) juntar(id); return; }
      recordar();
      for (const id of ids) { const p = parte(id); p.pos = p.pos.map((v, i) => Math.round((v + mover[id][i]) * 10) / 10); }
      st.sel = ids[0];
      aviso(ids.length > 1 ? `Junté ${ids.length} partes sueltas.` : 'La acerqué hasta que se cruzan 1 mm.');
      cambio(true);
    } else if (a.id.startsWith('no_corta_')) {
      const p = parte(a.parte), caja = cajaPartes(false);
      if (!p || !caja) return;
      recordar();
      const c = caja.getCenter(new THREE.Vector3());
      p.pos = [Math.round(c.x), Math.round(c.y), Math.round(caja.min.z) - 1];
      st.sel = p.id;
      aviso('Llevé el agujero al centro de la pieza.');
      cambio(true);
    }
  }

  // ---- guardar ----
  async function guardar(comoNueva) {
    if (!st.partes.length) { aviso('No hay nada que guardar todavía.'); return; }
    if (st.ocupado) return;
    st.ocupado = true;
    const nombre = ($('#nombreConstruir') && $('#nombreConstruir').value.trim()) || st.nombre || 'mi_pieza';
    try {
      const r = await enviar('/api/construir', { partes: st.partes, guardar: nombre, reemplazar: !comoNueva && st.editando === nombre });
      if (!r.ok) { aviso(r.error || 'No se pudo guardar.'); return; }
      st.nombre = r.nombre;
      st.editando = r.nombre;
      aviso(`Guardada como ${r.nombre}.stl`);
      st.guardada = r.nombre;
      pintarPanel();
    } catch (e) { aviso('No pude guardar: ¿Arché sigue abierto?'); }
    finally { st.ocupado = false; }
  }

  async function cargar(nombre) {
    const d = await apiJson('/api/partes?n=' + encodeURIComponent(nombre));
    if (!d.partes || !d.partes.length) { aviso('Esa pieza no se hizo en Construir; la agrego como una parte.'); await agregarModelo(nombre); return; }
    recordar();
    for (const p of d.partes) if (p.forma === 'modelo') await geometriaModelo(p.modelo).catch(() => {});
    st.partes = d.partes.map((p) => ({ ...p, id: p.id || nuevoId() }));
    st.nombre = nombre;
    st.editando = nombre;
    st.sel = null;
    cambio(true);
    encuadrar();
  }
  async function agregarModelo(nombre) {
    try { await geometriaModelo(nombre); } catch (e) { aviso('No pude abrir ese modelo.'); return; }
    agregar('modelo', { modelo: nombre });
  }

  function encuadrar() {
    const caja = cajaPartes(true);
    if (!caja) { camara.position.set(170, -230, 170); controles.target.set(0, 0, 10); return; }
    const c = caja.getCenter(new THREE.Vector3());
    const r = Math.max(caja.getSize(new THREE.Vector3()).length() / 2, 25);
    controles.target.copy(c);
    camara.position.copy(c).add(new THREE.Vector3(0.55, -0.8, 0.55).normalize().multiplyScalar(r / Math.sin(19 * RAD) * 1.35));
  }

  // ---- órdenes escritas: «agrega un cilindro de 10 de diámetro», «haz un agujero de 3», «deshaz»… ----
  function numeros(t) { return (t.match(/\d+(?:[.,]\d+)?/g) || []).map((n) => Number(n.replace(',', '.'))); }
  function ordenEscrita(texto) {
    const t = norm(texto);
    const n = numeros(t);
    const sel = parte(st.sel);
    if (/^(deshaz|deshacer|deshazlo|atras)$/.test(t)) { deshacer(); return true; }
    if (/^(rehaz|rehacer|rehazlo)$/.test(t)) { rehacer(); return true; }
    if (/^(borra|borrala|borralo|elimina|eliminala|quita|quitala)( la parte| esa| esta)?$/.test(t)) { borrar(); return true; }
    if (/^(duplica|duplicala|duplicalo|copia|copiala)( la parte| esa| esta)?$/.test(t)) { duplicar(); return true; }
    if (/^(guarda|guardala|guardalo)(?: (?:como|la pieza como) (.+))?$/.test(t)) {
      const m = t.match(/como (.+)$/);
      if (m && $('#nombreConstruir')) $('#nombreConstruir').value = m[1];
      guardar(!!m);
      return true;
    }
    if (/^(empieza de nuevo|borra todo|nueva pieza|limpia todo)$/.test(t)) { recordar(); st.partes = []; st.sel = null; st.nombre = ''; st.editando = null; cambio(true); return true; }
    let m = t.match(/(?:haz|hazle|pon|ponle|agrega|agregale|abre)(?: un| una)? (agujero|hueco|ranura)(?: cuadrad[oa])?(?: de| para tornillo(?: de)?)? ?(?:m)?(\d+(?:[.,]\d+)?)?/);
    if (m) {
      const cuadrado = /cuadrad|ranura/.test(t);
      const d = m[2] ? Number(m[2].replace(',', '.')) : 3.2;
      if (cuadrado) agregar('caja', { restar: true, medidas: { x: d, y: d } });
      else agregar('cilindro', { restar: true, medidas: { diametro: d } });
      return true;
    }
    m = t.match(/(?:agrega|pon|anade|crea|haz|mete)(?: un| una| otro| otra)? (caja|cubo|bloque|cilindro|esfera|bola|cono|prisma|hexagono)/);
    if (m) {
      const forma = { cubo: 'caja', bloque: 'caja', bola: 'esfera', hexagono: 'prisma' }[m[1]] || m[1];
      const medidas = {};
      const x3 = t.match(/(\d+(?:[.,]\d+)?)\s*(?:x|por)\s*(\d+(?:[.,]\d+)?)(?:\s*(?:x|por)\s*(\d+(?:[.,]\d+)?))?/);
      if (forma === 'caja' && x3) { medidas.x = +x3[1].replace(',', '.'); medidas.y = +x3[2].replace(',', '.'); if (x3[3]) medidas.z = +x3[3].replace(',', '.'); }
      else if (forma === 'caja' && m[1] === 'cubo' && n[0]) { medidas.x = medidas.y = medidas.z = n[0]; }
      else {
        const dia = t.match(/(\d+(?:[.,]\d+)?)\s*(?:mm )?(?:de )?diametro|diametro (?:de )?(\d+(?:[.,]\d+)?)/);
        const alto = t.match(/(\d+(?:[.,]\d+)?)\s*(?:mm )?(?:de )?alto|alto (?:de )?(\d+(?:[.,]\d+)?)/);
        const lados = t.match(/(\d+) lados/);
        if (dia) medidas.diametro = +(dia[1] || dia[2]).replace(',', '.');
        if (alto) { medidas.alto = +(alto[1] || alto[2]).replace(',', '.'); if (forma === 'caja') medidas.z = medidas.alto; }
        if (lados) medidas.lados = +lados[1];
        if (!dia && !alto && n[0] && forma !== 'caja') medidas.diametro = n[0];
        if (forma === 'caja' && !alto && n[0]) medidas.x = medidas.y = n[0];
      }
      if (forma === 'prisma' && /hexagono/.test(t)) medidas.lados = 6;
      agregar(forma, { medidas });
      return true;
    }
    m = t.match(/^(?:mueve(?:la|lo)?|corre(?:la|lo)?|llevala|llevalo)? ?(\d+(?:[.,]\d+)?) ?(?:mm )?(?:a la |hacia (?:la |el )?|al |para )?(derecha|izquierda|adelante|atras|arriba|abajo)$/);
    if (m && sel) {
      recordar();
      const d = Number(m[1].replace(',', '.'));
      const eje = { derecha: [0, 1], izquierda: [0, -1], adelante: [1, 1], atras: [1, -1], arriba: [2, 1], abajo: [2, -1] }[m[2]];
      sel.pos[eje[0]] = Math.round((sel.pos[eje[0]] + eje[1] * d) * 10) / 10;
      cambio(true);
      return true;
    }
    m = t.match(/^(?:subela|subelo|sube(?:la|lo)?) (\d+(?:[.,]\d+)?)$/);
    if (m && sel) { recordar(); sel.pos[2] += Number(m[1].replace(',', '.')); cambio(true); return true; }
    if (/^(acuestala|acuestalo|tumbala|tumbalo|acostar)$/.test(t) && sel) { acostar(); return true; }
    m = t.match(/^(?:girala|giralo|rota(?:la|lo)?) (-?\d+)(?: grados)?$/);
    if (m && sel) { recordar(); sel.rot = sel.rot || [0, 0, 0]; sel.rot[2] = ((sel.rot[2] + Number(m[1]) + 540) % 360) - 180; cambio(true); return true; }
    if (/^(hazla|hazlo|conviertela|conviertelo|que sea)( un)? (agujero|hueco)$/.test(t) && sel) { recordar(); sel.restar = true; cambio(true); return true; }
    if (/^(hazla|hazlo|que sea) solid[oa]$/.test(t) && sel) { recordar(); sel.restar = false; cambio(true); return true; }
    m = t.match(/(diametro|alto|largo|ancho|lados|punta)(?: a| de| en)? (\d+(?:[.,]\d+)?)/);
    if (m && sel) {
      const clave = { largo: 'x', ancho: 'y' }[m[1]] || (m[1] === 'alto' && sel.forma === 'caja' ? 'z' : m[1]);
      if (clave in sel.medidas) { recordar(); sel.medidas[clave] = Number(m[2].replace(',', '.')); cambio(true); return true; }
    }
    return false;
  }
  function acostar() {
    const p = parte(st.sel);
    if (!p) return;
    recordar();
    p.rot = p.rot || [0, 0, 0];
    p.rot[0] = p.rot[0] ? 0 : 90;
    // al acostarla gira alrededor de su base: la volvemos a dejar sobre la cama
    cambio();
    const b = cajaDe(p.id);
    if (b && b.min.z < 0) { p.pos[2] = Math.round((p.pos[2] - b.min.z) * 10) / 10; cambio(true); }
  }

  // ---- panel ----
  const fmt = (n, d = 1) => Number(n).toLocaleString('es', { maximumFractionDigits: d });
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
  const ICONOS = {
    caja: '<rect x="5" y="7" width="14" height="11" rx="1"/><path d="M5 7l3-3h11l-3 3M19 4v11l-3 3"/>',
    cilindro: '<ellipse cx="12" cy="6" rx="7" ry="2.5"/><path d="M5 6v12c0 1.4 3.1 2.5 7 2.5s7-1.1 7-2.5V6"/>',
    esfera: '<circle cx="12" cy="12" r="8"/><ellipse cx="12" cy="12" rx="8" ry="3"/>',
    cono: '<path d="M12 3 5 18"/><path d="M12 3l7 15"/><ellipse cx="12" cy="18" rx="7" ry="2.5"/>',
    prisma: '<path d="M8 4h8l4 7-4 7H8l-4-7z"/>',
    agujero: '<circle cx="12" cy="12" r="8" stroke-dasharray="3 2"/><circle cx="12" cy="12" r="3"/>',
    ranura: '<rect x="4" y="4" width="16" height="16" rx="2" stroke-dasharray="3 2"/><rect x="9" y="9" width="6" height="6"/>',
  };
  const icono = (k) => { const s = document.createElementNS('http://www.w3.org/2000/svg', 'svg'); s.setAttribute('viewBox', '0 0 24 24'); s.innerHTML = ICONOS[k]; return s; };

  function tarjetaAgregar() {
    const rejilla = el('div', { class: 'paleta' });
    for (const [k, nombre] of [['caja', 'Caja'], ['cilindro', 'Cilindro'], ['esfera', 'Esfera'], ['cono', 'Cono'], ['prisma', 'Prisma']]) {
      rejilla.append(el('button', { class: 'pieza-btn', title: 'Agregar ' + nombre, onclick: () => agregar(k) }, icono(k), el('span', { text: nombre })));
    }
    rejilla.append(el('button', { class: 'pieza-btn resta', title: 'Agujero redondo', onclick: () => agregar('cilindro', { restar: true, medidas: { diametro: 3.2 } }) }, icono('agujero'), el('span', { text: 'Agujero' })));
    rejilla.append(el('button', { class: 'pieza-btn resta', title: 'Hueco cuadrado', onclick: () => agregar('caja', { restar: true, medidas: { x: 10, y: 10 } }) }, icono('ranura'), el('span', { text: 'Hueco' })));
    const t = el('div', { class: 'tarjeta' }, el('h2', { text: 'Agregar' }), rejilla);
    const propias = st.modelos.filter((m) => m.nombre !== st.editando);
    if (propias.length) {
      const sel = el('select', { class: 'btn', 'aria-label': 'Agregar una de tus piezas', onchange: (e) => { if (e.target.value) agregarModelo(e.target.value); e.target.value = ''; } },
        el('option', { value: '', text: '+ Una de tus piezas…' }));
      for (const m of propias) sel.append(el('option', { value: m.nombre, text: m.nombre }));
      sel.style.cssText = 'width:100%;margin-top:8px';
      t.append(sel);
    }
    if (!st.partes.length) {
      const fila = el('div', { class: 'acciones' });
      for (const nombre of Object.keys(PLANTILLAS)) {
        fila.append(el('button', { class: 'btn', text: nombre, onclick: () => {
          recordar();
          st.partes = PLANTILLAS[nombre].map((p) => ({ ...JSON.parse(JSON.stringify(p)), id: nuevoId(), rot: p.rot ? p.rot.slice() : [0, 0, 0] }));
          st.sel = null;
          st.nombre = norm(nombre).replace(/ /g, '_');
          cambio(true);
          encuadrar();
        } }));
      }
      t.append(el('p', { class: 'tenue', text: 'O empieza desde:' }), fila);
    }
    return t;
  }

  function deslizador(clave, etiqueta, valor, min, max, paso, alCambiar, alSoltar) {
    const salida = el('output', { text: fmt(valor) });
    const r = el('input', { type: 'range', id: 'c_' + clave, min: String(min), max: String(max), step: String(paso), value: String(valor),
      oninput: (e) => { const v = Number(e.target.value); salida.textContent = fmt(v); alCambiar(v); },
      onchange: () => alSoltar && alSoltar() });
    return el('div', { class: 'medida' }, el('label', { for: 'c_' + clave, text: etiqueta }), salida, r);
  }

  let deslizandoPanel = false;
  function tarjetaParte() {
    const p = parte(st.sel);
    if (!p) {
      return el('div', { class: 'tarjeta' }, el('h2', { text: 'Parte elegida' }),
        el('p', { class: 'tenue', text: st.partes.length ? 'Toca una parte para cambiarla. Arrástrala para moverla.' : 'Agrega una forma para empezar.' }));
    }
    const t = el('div', { class: 'tarjeta' }, el('h2', { text: 'Parte elegida' }),
      el('h3', { text: (p.forma === 'modelo' ? p.modelo : FORMAS[p.forma].nombre) + (p.restar ? ' (agujero)' : '') }));
    const tipo = el('div', { class: 'segmento' },
      el('button', { class: p.restar ? '' : 'activo', text: 'Sólido', onclick: () => { if (p.restar) { recordar(); p.restar = false; cambio(true); } } }),
      el('button', { class: p.restar ? 'activo' : '', text: 'Agujero', onclick: () => { if (!p.restar) { recordar(); p.restar = true; cambio(true); } } }));
    t.append(tipo);
    const empezar = () => { if (!deslizandoPanel) { recordar(); deslizandoPanel = true; } };
    const terminar = () => { deslizandoPanel = false; cambio(true); };
    for (const [k, [, min, max]] of Object.entries(FORMAS[p.forma].medidas)) {
      if (!(k in p.medidas)) continue;
      const tope = Math.min(max, Math.max(p.medidas[k] * 3, 60));
      t.append(deslizador(k, NOMBRE_MEDIDA[k] + (k === 'lados' || k === 'escala' ? '' : ' (mm)'), p.medidas[k], min, k === 'lados' ? max : tope,
        k === 'lados' ? 1 : k === 'escala' ? 0.05 : 0.5,
        (v) => { empezar(); p.medidas[k] = v; st.version++; pintarPartes(); }, terminar));
    }
    const [cx, cy, cz] = medidaCama;
    t.append(el('h2', { text: 'Posición (mm)', style: 'margin-top:12px' }));
    ['X', 'Y', 'Z'].forEach((nombre, i) => {
      const lim = i < 2 ? [-[cx, cy][i] / 2, [cx, cy][i] / 2] : [-30, cz];
      t.append(deslizador('pos' + i, nombre, p.pos[i], lim[0], lim[1], 0.5, (v) => { empezar(); p.pos[i] = v; st.version++; pintarPartes(); }, terminar));
    });
    t.append(deslizador('giro', 'Giro (°)', (p.rot || [0, 0, 0])[2], -180, 180, 5, (v) => { empezar(); p.rot = p.rot || [0, 0, 0]; p.rot[2] = v; st.version++; pintarPartes(); }, terminar));
    t.append(el('div', { class: 'acciones' },
      el('button', { class: 'btn', text: (p.rot || [0])[0] ? 'Pararla' : 'Acostarla', title: 'Girarla 90° para que quede acostada', onclick: acostar }),
      el('button', { class: 'btn', text: 'Duplicar', title: 'Dedos en V', onclick: duplicar }),
      el('button', { class: 'btn peligro', text: 'Borrar', title: 'Pulgar abajo', onclick: borrar })));
    return t;
  }
  function pintarPosicion() {
    const p = parte(st.sel);
    if (!p) return;
    [0, 1, 2].forEach((i) => {
      const r = document.getElementById('c_pos' + i);
      if (r) { r.value = String(p.pos[i]); r.previousElementSibling.textContent = fmt(p.pos[i]); }
    });
  }

  function tarjetaRevision() {
    const t = el('div', { class: 'tarjeta arche-sugiere' }, el('h2', { text: 'Arché revisa' }));
    if (!st.partes.length) { t.append(el('p', { class: 'tenue', text: 'Cuando agregues partes, aquí verás la pieza de verdad (con los agujeros hechos) y lo que hay que corregir.' })); return t; }
    if (st.error) { t.append(el('ul', { class: 'avisos' }, el('li', { text: st.error }))); return t; }
    const i = st.info;
    if (!i) { t.append(el('p', { class: 'tenue', text: 'Armando la pieza…' })); return t; }
    const d = i.dimensiones;
    t.append(el('div', { class: 'cifras' },
      el('div', { class: 'cifra ancha' }, el('b', { text: `${fmt(d[0])} × ${fmt(d[1])} × ${fmt(d[2])}` }), el('span', { text: 'mm, la pieza completa' })),
      el('div', { class: 'cifra' }, el('b', { text: `${fmt(i.gramos, 0)} g` }), el('span', { text: 'de plástico' })),
      el('div', { class: 'cifra' }, el('b', { text: i.tiempo }), el('span', { text: 'imprimiendo' }))));
    const lista = el('ul', { class: 'avisos' });
    if (!i.avisos.length) lista.append(el('li', { class: 'bien', text: `Es una sola pieza${i.cabe ? ', cabe en tu impresora' : ''} y los agujeros tienen medida de impresión.` }));
    for (const a of i.avisos) {
      const li = el('li', { text: a.texto });
      if (a.cambio || a.id === 'sueltas' || a.id.startsWith('no_corta_')) {
        li.append(el('button', { class: 'btn sug-aplicar', text: a.cambio ? `Usar ${a.cambio.valor} mm` : a.id === 'sueltas' ? 'Juntarlas' : 'Llevarlo a la pieza',
          onclick: () => aplicarAviso(a) }));
      }
      lista.append(li);
    }
    t.append(lista);
    return t;
  }

  function tarjetaGuardar() {
    const nombre = el('input', { id: 'nombreConstruir', class: 'btn', value: st.nombre || '', placeholder: 'Nombre de la pieza', 'aria-label': 'Nombre de la pieza' });
    nombre.style.cssText = 'width:100%;cursor:text;margin-bottom:8px';
    nombre.addEventListener('input', () => { st.nombre = nombre.value; });
    const t = el('div', { class: 'tarjeta' }, el('h2', { text: 'Guardar' }), nombre,
      el('div', { class: 'acciones' },
        el('button', { class: 'btn sug-aplicar', text: st.editando ? 'Guardar cambios' : 'Guardar pieza', title: 'Pulgar arriba', onclick: () => guardar(false) }),
        st.editando ? el('button', { class: 'btn', text: 'Guardar como nueva', onclick: () => guardar(true) }) : null,
        el('button', { class: 'btn', text: `Deshacer${st.pasado.length ? ' (' + st.pasado.length + ')' : ''}`, disabled: !st.pasado.length, title: 'Mano abierta hacia la izquierda', onclick: deshacer }),
        el('button', { class: 'btn', text: 'Rehacer', disabled: !st.futuro.length, title: 'Mano abierta hacia la derecha', onclick: rehacer })));
    if (st.guardada) {
      t.append(el('p', { class: 'tenue', text: `Guardada: ${st.guardada}.stl. En el Taller ves cuánto pesa, lo que Arché sugiere y la puedes descargar.` }),
        el('div', { class: 'acciones' }, el('button', { class: 'btn', text: 'Verla en el Taller', onclick: () => ctx.irA('taller', st.guardada) })));
    }
    t.append(el('details', { class: 'manos-detalles ayuda-construir' }, el('summary', { text: 'Con las manos aquí' }),
      el('ul', { class: 'manos-ayuda' },
        ...[['Pellizca una parte y mueve', 'la agarras y la llevas (se pega a bordes y centros)'],
            ['Pellizca el fondo y mueve', 'giras la vista'],
            ['Dos manos sobre la parte elegida', 'sepáralas de lado = más ancha, de arriba a abajo = más alta; gíralas como un volante = la giras'],
            ['Pellizco rápido', 'eliges una parte o tocas un botón'],
            ['Dedos en V', 'duplicas la parte'], ['Pulgar abajo', 'la borras'],
            ['Mano abierta a la izquierda / derecha', 'deshacer / rehacer'], ['Pulgar arriba', 'guardas la pieza']]
          .map(([g, q]) => el('li', {}, el('b', { text: g }), document.createTextNode(': ' + q))))));
    return t;
  }

  function pintarPanel() {
    if (!st.visible) return;
    const p = ctx.panel;
    const foco = document.activeElement && document.activeElement.id;
    const arriba = p.scrollTop;
    p.innerHTML = '';
    p.append(tarjetaAgregar(), tarjetaRevision(), tarjetaParte(), tarjetaGuardar());
    p.scrollTop = arriba;
    if (foco) { const e = document.getElementById(foco); if (e && e.tagName === 'INPUT' && e.type !== 'range') e.focus(); }
  }

  // ---- mouse y teclado ----
  let abajoMouse = null;
  render.domElement.addEventListener('pointerdown', (e) => {
    if (!st.visible || e.button !== 0) return;
    abajoMouse = [e.clientX, e.clientY];
    if (empezarArrastre(e.clientX, e.clientY)) render.domElement.setPointerCapture(e.pointerId);
  });
  render.domElement.addEventListener('pointermove', (e) => { if (st.visible && st.arrastre) arrastrar(e.clientX, e.clientY); });
  render.domElement.addEventListener('pointerup', (e) => {
    if (!st.visible) return;
    const quieto = abajoMouse && Math.hypot(e.clientX - abajoMouse[0], e.clientY - abajoMouse[1]) < 5;
    abajoMouse = null;
    if (st.arrastre) soltar();
    else if (quieto) elegirParte(null);
  });
  addEventListener('keydown', (e) => {
    if (!st.visible || /INPUT|SELECT|TEXTAREA/.test((document.activeElement || {}).tagName || '') && document.activeElement.type !== 'range') return;
    const p = parte(st.sel);
    if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'z') { e.preventDefault(); e.shiftKey ? rehacer() : deshacer(); }
    else if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'y') { e.preventDefault(); rehacer(); }
    else if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'd') { e.preventDefault(); duplicar(); }
    else if ((e.key === 'Delete' || e.key === 'Backspace') && p) { e.preventDefault(); borrar(); }
    else if (p && ['ArrowLeft', 'ArrowRight', 'ArrowUp', 'ArrowDown', 'PageUp', 'PageDown'].includes(e.key)) {
      e.preventDefault();
      recordar();
      const d = e.shiftKey ? 10 : 1;
      if (e.key === 'ArrowLeft') p.pos[0] -= d; if (e.key === 'ArrowRight') p.pos[0] += d;
      if (e.key === 'ArrowUp') p.pos[1] += d; if (e.key === 'ArrowDown') p.pos[1] -= d;
      if (e.key === 'PageUp') p.pos[2] += d; if (e.key === 'PageDown') p.pos[2] -= d;
      cambio();
    }
  });

  // retoma lo que dejaste a medias (solo en este navegador)
  try {
    const guardado = JSON.parse(localStorage.getItem('arche3d-construir') || 'null');
    if (guardado && Array.isArray(guardado.partes)) {
      st.partes = guardado.partes;
      st.nombre = guardado.nombre || '';
      st.editando = guardado.editando || null;
      for (const p of st.partes) if (p.forma === 'modelo') geometriaModelo(p.modelo).then(() => pintarPartes()).catch(() => {});
    }
  } catch (e) { /* sin almacenamiento */ }

  const _v = new THREE.Vector3();
  return {
    escena, camara, controles,
    entrar() {
      st.visible = true;
      controles.enabled = true;
      const campo = $('#texto');
      if (campo) campo.placeholder = 'Dile qué hacer: «agrega un cilindro de 20 de diámetro», «haz un agujero de 3», «deshaz»';
      apiJson('/api/modelos').then((d) => { st.modelos = d.modelos; pintarPanel(); }).catch(() => {});
      pintarPartes();
      pintarPanel();
      if (st.partes.length && !st.info) pedirPrevia();
    },
    salir() {
      st.visible = false;
      controles.enabled = false;
      if (st.arrastre) soltar();
      const campo = $('#texto');
      if (campo) campo.placeholder = 'Pídele una pieza: «crea una caja de 80x50x30 con tapa»';
    },
    reencuadrar: encuadrar,
    ordenEscrita,
    cargar,
    alEstado(e) {
      if (e.ajustes && e.ajustes.cama.join() !== medidaCama.join()) { medidaCama = e.ajustes.cama; pintarCama(); }
    },
    // ---- lo que le llega de las manos ----
    tocar(x, y) { const t = parteBajo(x, y); elegirParte(t ? t.id : null); },
    agarrar(x, y) { return empezarArrastre(x, y); },
    arrastrar,
    soltar,
    dosManos,
    deslizar(dir) { if (dir === 'izquierda') deshacer(); else rehacer(); return true; },
    aceptar() { guardar(false); },
    rechazar: borrar,
    duplicar,
    actualizar() {
      // terminar el estirado con dos manos cuando ya no llegan más cuadros de ese gesto
      if (st.estirando && performance.now() - st.ultimoDos > 450) { st.estirando = null; cambio(true); }
      // medidas de la parte elegida, flotando junto a ella
      const p = parte(st.sel);
      const b = p && cajaDe(p.id);
      if (!b || !st.visible) { Object.values(etqs).forEach((e) => { e.style.display = 'none'; }); return; }
      const m = p.medidas;
      const txt = p.forma === 'caja' ? [`X ${fmt(m.x)}`, `Y ${fmt(m.y)}`, `Z ${fmt(m.z)}`]
        : p.forma === 'esfera' ? [`⌀ ${fmt(m.diametro)}`, '', '']
          : p.forma === 'modelo' ? [`× ${fmt(m.escala, 2)}`, '', '']
            : [`⌀ ${fmt(m.diametro)}`, '', `alto ${fmt(m.alto)}`];
      etqs.a.textContent = txt[0]; etqs.b.textContent = txt[1]; etqs.c.textContent = txt[2];
      ctx.colocar(etqs.a, _v.set((b.min.x + b.max.x) / 2, b.min.y - 4, b.min.z), camara);
      if (txt[1]) ctx.colocar(etqs.b, _v.set(b.max.x + 4, (b.min.y + b.max.y) / 2, b.min.z), camara); else etqs.b.style.display = 'none';
      if (txt[2]) ctx.colocar(etqs.c, _v.set(b.max.x + 4, b.max.y + 4, (b.min.z + b.max.z) / 2), camara); else etqs.c.style.display = 'none';
      const giro = (p.rot || [0, 0, 0])[2];
      if (st.estirando || giro) { etqs.giro.textContent = `${fmt(giro, 0)}°`; ctx.colocar(etqs.giro, _v.set((b.min.x + b.max.x) / 2, (b.min.y + b.max.y) / 2, b.max.z + 6), camara); }
      else etqs.giro.style.display = 'none';
    },
  };
}
