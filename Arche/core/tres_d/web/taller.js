// Taller: ver modelos sobre la cama de la impresora, medirlos, editarlos y prepararlos.
import * as THREE from 'three';
import { OrbitControls } from './lib/OrbitControls.js';
import { STLLoader } from './lib/STLLoader.js';

const COLOR_PIEZA = new THREE.Color(0x9a8cff);
const COLOR_VOLADIZO = new THREE.Color(0xff5d7a);
const ENTEROS = new Set(['dientes', 'rayos', 'agujeros_largo', 'agujeros_ancho', 'drenaje']);
const INTERRUPTORES = new Set(['tapa', 'postes', 'hexagonal', 'refuerzo']);
const IDEAS = ['crea una caja de 80x50x30 con tapa', 'crea un engranaje de 20 dientes módulo 2',
  'crea un soporte para servo mg996r', 'crea un soporte para celular', 'analiza el modelo', 'ayuda 3d'];

export function crearTaller(ctx) {
  const { render, apiJson, api, enviar, aviso, $ } = ctx;
  const escena = new THREE.Scene();
  escena.fog = new THREE.Fog(0x0c0c14, 900, 2600);
  const camara = new THREE.PerspectiveCamera(38, 1, 1, 6000);
  camara.up.set(0, 0, 1);
  camara.position.set(260, -330, 240);
  const controles = new OrbitControls(camara, render.domElement);
  controles.enableDamping = true;
  controles.dampingFactor = 0.09;
  controles.target.set(0, 0, 30);
  controles.maxPolarAngle = Math.PI * 0.495;
  controles.enabled = false;

  escena.add(new THREE.HemisphereLight(0xcfd4ff, 0x1a1a26, 1.15));
  const sol = new THREE.DirectionalLight(0xffffff, 1.5);
  sol.position.set(0.4, -0.6, 1);
  camara.add(sol);
  escena.add(camara);

  // ---- la cama de la impresora ----
  const cama = new THREE.Group();
  escena.add(cama);
  function pintarCama(medidas) {
    cama.clear();
    const [x, y, z] = medidas;
    const piso = new THREE.Mesh(new THREE.PlaneGeometry(x, y),
      new THREE.MeshBasicMaterial({ color: 0x14141f, transparent: true, opacity: 0.92, side: THREE.DoubleSide }));
    piso.position.z = -0.15;
    cama.add(piso);
    const puntos = [];
    for (let i = -x / 2; i <= x / 2 + 0.01; i += 10) puntos.push(i, -y / 2, 0, i, y / 2, 0);
    for (let j = -y / 2; j <= y / 2 + 0.01; j += 10) puntos.push(-x / 2, j, 0, x / 2, j, 0);
    const g = new THREE.BufferGeometry();
    g.setAttribute('position', new THREE.Float32BufferAttribute(puntos, 3));
    cama.add(new THREE.LineSegments(g, new THREE.LineBasicMaterial({ color: 0x2c2c40 })));
    const borde = new THREE.LineSegments(new THREE.EdgesGeometry(new THREE.BoxGeometry(x, y, z)),
      new THREE.LineBasicMaterial({ color: 0x8b7cff, transparent: true, opacity: 0.22 }));
    borde.position.z = z / 2;
    cama.add(borde);
  }
  let camaActual = [220, 220, 250];
  pintarCama(camaActual);

  // ---- la pieza ----
  const corte = new THREE.Plane(new THREE.Vector3(0, 0, -1), 1e6);
  const material = new THREE.MeshStandardMaterial({ vertexColors: true, roughness: 0.55, metalness: 0.08,
    side: THREE.DoubleSide, clippingPlanes: [corte] });
  const matLineas = new THREE.LineBasicMaterial({ color: 0x0c0c14, transparent: true, opacity: 0.45, clippingPlanes: [corte] });
  const pieza = new THREE.Group();
  escena.add(pieza);
  const cargador = new STLLoader();
  const etqs = { x: ctx.etiqueta('x'), y: ctx.etiqueta('y'), z: ctx.etiqueta('z') };
  const caja = new THREE.Box3();
  let hayPieza = false;

  // ---- medir con el dedo (o el mouse): dos toques sobre la pieza ----
  const medida = new THREE.Group();
  escena.add(medida);
  const etqMedida = ctx.etiqueta('medida');
  const rayo = new THREE.Raycaster();
  const matPunto = new THREE.MeshBasicMaterial({ color: 0x5fd3c4, depthTest: false });
  const matRegla = new THREE.LineBasicMaterial({ color: 0x5fd3c4, depthTest: false });
  let puntosMedida = [];
  function limpiarMedida() {
    puntosMedida = [];
    medida.children.forEach((h) => h.geometry && h.geometry.dispose());
    medida.clear();
    etqMedida.style.display = 'none';
  }
  function puntoEnPieza(x, y) {
    const malla = pieza.children[0];
    if (!malla) return null;
    rayo.setFromCamera(new THREE.Vector2((x / innerWidth) * 2 - 1, -(y / innerHeight) * 2 + 1), camara);
    const toque = rayo.intersectObject(malla, false).find((h) => h.point.z <= corte.constant + 0.01);
    return toque ? toque.point.clone() : null;
  }
  function medirEn(x, y) {
    const p = puntoEnPieza(x, y);
    if (!p) { aviso('Toca sobre la pieza para medir.'); return; }
    if (puntosMedida.length >= 2) limpiarMedida();
    puntosMedida.push(p);
    const radio = Math.max(caja.getSize(new THREE.Vector3()).length() / 180, 0.5);
    const bola = new THREE.Mesh(new THREE.SphereGeometry(radio, 16, 12), matPunto);
    bola.renderOrder = 10;
    bola.position.copy(p);
    medida.add(bola);
    if (puntosMedida.length === 2) {
      const [a, b] = puntosMedida;
      const linea = new THREE.Line(new THREE.BufferGeometry().setFromPoints([a, b]), matRegla);
      linea.renderOrder = 10;
      medida.add(linea);
      const d = a.distanceTo(b);
      etqMedida.textContent = `${fmt(d)} mm`;
      aviso(`Distancia ${fmt(d)} mm  ·  X ${fmt(Math.abs(b.x - a.x))}  Y ${fmt(Math.abs(b.y - a.y))}  Z ${fmt(Math.abs(b.z - a.z))}`);
    } else {
      aviso('Ahora toca el segundo punto.');
    }
  }
  // un clic con el mouse sobre la pieza también mide (si no fue para girar)
  let abajo = null;
  render.domElement.addEventListener('pointerdown', (e) => { if (st.visible && st.midiendo) abajo = [e.clientX, e.clientY]; });
  render.domElement.addEventListener('pointerup', (e) => {
    if (!abajo) return;
    const quieto = Math.hypot(e.clientX - abajo[0], e.clientY - abajo[1]) < 5;
    abajo = null;
    if (quieto && st.visible && st.midiendo) medirEn(e.clientX, e.clientY);
  });

  const st = { midiendo: false, sugerencias: null, modelos: [], actual: null, analisis: null, catalogo: null, version: -1, voladizos: true,
               capa: 1, simulando: false, visible: false, ocupado: false, carpeta: '' };

  function colorear(geometria) {
    const pos = geometria.getAttribute('position');
    const colores = new Float32Array(pos.count * 3);
    const a = new THREE.Vector3(), b = new THREE.Vector3(), c = new THREE.Vector3(), n = new THREE.Vector3();
    const limite = -Math.cos(Math.PI / 4);
    for (let i = 0; i < pos.count; i += 3) {
      a.fromBufferAttribute(pos, i); b.fromBufferAttribute(pos, i + 1); c.fromBufferAttribute(pos, i + 2);
      n.subVectors(b, a).cross(c.clone().sub(a)).normalize();
      const enCama = Math.max(a.z, b.z, c.z) < 0.05;
      const col = (st.voladizos && n.z < limite && !enCama) ? COLOR_VOLADIZO : COLOR_PIEZA;
      for (let k = 0; k < 3; k++) { colores[(i + k) * 3] = col.r; colores[(i + k) * 3 + 1] = col.g; colores[(i + k) * 3 + 2] = col.b; }
    }
    geometria.setAttribute('color', new THREE.BufferAttribute(colores, 3));
  }

  function encuadrar() {
    const tam = caja.getSize(new THREE.Vector3());
    const radio = Math.max(tam.length() / 2, 20);
    const centro = caja.getCenter(new THREE.Vector3());
    controles.target.copy(centro);
    const dir = new THREE.Vector3(0.55, -0.8, 0.5).normalize();
    camara.position.copy(centro).addScaledVector(dir, radio / Math.sin((camara.fov / 2) * Math.PI / 180) * 1.75);
  }

  async function cargarPieza(nombre, reencuadrar) {
    const r = await api('/api/modelo?n=' + encodeURIComponent(nombre));
    if (!r.ok) throw new Error('no está');
    const geometria = cargador.parse(await r.arrayBuffer());
    geometria.computeVertexNormals();
    colorear(geometria);
    pieza.children.forEach((h) => h.geometry.dispose());
    pieza.clear();
    pieza.add(new THREE.Mesh(geometria, material));
    if (geometria.getAttribute('position').count < 450000) {
      pieza.add(new THREE.LineSegments(new THREE.EdgesGeometry(geometria, 28), matLineas));
    }
    geometria.computeBoundingBox();
    caja.copy(geometria.boundingBox);
    hayPieza = true;
    ponerCapa(1);
    if (reencuadrar) encuadrar();
  }

  function ponerCapa(fraccion) {
    st.capa = fraccion;
    const alto = caja.max.z - caja.min.z;
    corte.constant = fraccion >= 0.999 ? 1e6 : caja.min.z + alto * fraccion + 0.001;
    const deslizador = $('#capaRango');
    if (deslizador) deslizador.value = String(Math.round(fraccion * 1000));
    const texto = $('#capaTexto');
    if (texto) {
      const capas = Math.max(1, Math.round(alto / 0.2));
      texto.textContent = fraccion >= 0.999 ? `${capas} capas` : `capa ${Math.max(1, Math.round(capas * fraccion))} de ${capas}`;
    }
  }

  // ---- panel ----
  const fmt = (n, d = 1) => Number(n).toLocaleString('es', { maximumFractionDigits: d, minimumFractionDigits: 0 });
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

  function tarjetaModelos() {
    const lista = el('div', { class: 'modelos' });
    for (const m of st.modelos) {
      lista.append(el('button', { class: m.nombre === st.actual ? 'activo' : '', title: m.nombre + '.stl',
        onclick: () => elegir(m.nombre, true) }, el('span', { text: m.nombre }), el('small', { text: m.que })));
    }
    return el('div', { class: 'tarjeta' }, el('h2', { text: `Modelos · ${st.modelos.length}` }), lista);
  }

  function tarjetaVacia() {
    return el('div', { class: 'tarjeta' }, el('h2', { text: 'Empieza aquí' }),
      el('p', { class: 'tenue', text: 'Todavía no hay modelos. Pide una pieza en la barra de abajo, o arrastra un archivo .stl u .obj a esta ventana para revisarlo.' }));
  }

  function tarjetaAnalisis() {
    const a = st.analisis;
    const t = el('div', { class: 'tarjeta' }, el('h2', { text: 'Para imprimir' }), el('h3', { text: st.actual + '.stl' }));
    if (!a) { t.append(el('p', { class: 'tenue', text: 'Midiendo…' })); return t; }
    const d = a.dimensiones;
    t.append(el('div', { class: 'cifras' },
      el('div', { class: 'cifra ancha' }, el('b', { text: `${fmt(d[0])} × ${fmt(d[1])} × ${fmt(d[2])}` }), el('span', { text: 'milímetros (X × Y × Z)' })),
      el('div', { class: 'cifra' }, el('b', { text: `${fmt(a.gramos, 0)} g` }), el('span', { text: `${a.material.toUpperCase()} · relleno ${Math.round(a.relleno * 100)} %` })),
      el('div', { class: 'cifra' }, el('b', { text: a.tiempo }), el('span', { text: 'tiempo aproximado' })),
      el('div', { class: 'cifra' }, el('b', { text: `${fmt(a.metros_filamento)} m` }), el('span', { text: 'de filamento' })),
      el('div', { class: 'cifra' }, el('b', { text: `${fmt(a.soporte_pct, 0)} %` }), el('span', { text: 'en voladizo' }))));
    const avisos = el('ul', { class: 'avisos' });
    if (!a.avisos.length) avisos.append(el('li', { class: 'bien', text: 'Lista para imprimir: cerrada, cabe en la cama y casi no necesita soportes.' }));
    for (const texto of a.avisos) avisos.append(el('li', { text: texto }));
    t.append(avisos);
    t.append(el('div', { class: 'acciones' },
      el('button', { class: 'btn' + (st.voladizos ? ' activo' : ''), text: 'Ver voladizos', title: 'Pinta de rojo lo que necesitaría soporte',
        onclick: () => { st.voladizos = !st.voladizos; const m = pieza.children[0]; if (m) colorear(m.geometry); pintar(); } }),
      el('button', { class: 'btn', text: 'Orientar', title: 'Gira la pieza a la posición que necesita menos soportes', onclick: () => ordenar('orienta el modelo para imprimir') }),
      el('button', { class: 'btn', text: 'Espejo', title: 'Crea la pieza del otro lado', onclick: () => ordenar('espejo del modelo') }),
      el('button', { class: 'btn' + (st.midiendo ? ' activo' : ''), text: st.midiendo ? 'Midiendo…' : 'Medir',
        title: 'Toca dos puntos de la pieza (con el mouse o con la mano) y te digo la distancia',
        onclick: () => { st.midiendo = !st.midiendo; limpiarMedida(); if (st.midiendo) aviso('Toca un punto de la pieza.'); pintar(); } }),
      el('button', { class: 'btn', text: 'Editar en Construir', title: 'Ábrela en Construir para agregarle o quitarle partes', onclick: () => ctx.irA('construir', st.actual) }),
      el('button', { class: 'btn', text: 'Editar en Modelar', title: 'Esculpirla o editar sus caras, estilo Blender', onclick: () => ctx.irA('modelar', st.actual) }),
      el('button', { class: 'btn', text: 'Descargar STL', onclick: descargar }),
      el('button', { class: 'btn peligro', text: 'Borrar', onclick: borrar })));
    return t;
  }

  function tarjetaArche() {
    const t = el('div', { class: 'tarjeta arche-sugiere' }, el('h2', { text: 'Arché sugiere' }));
    const datos = st.sugerencias;
    if (!datos) { t.append(el('p', { class: 'tenue', text: 'Revisando la pieza…' })); return t; }
    const lista = datos.sugerencias;
    if (!lista.length) {
      t.append(el('p', { class: 'tenue', text: 'No le cambiaría nada: está lista para imprimir.' }));
      return t;
    }
    const primera = lista.find((x) => x.tipo === 'arreglo');
    if (primera) t.append(el('p', { class: 'tenue pista', text: '👍 Pulgar arriba aplica el primer arreglo.' }));
    for (const sug of lista) {
      const fila = el('div', { class: 'sugerencia ' + sug.tipo },
        el('div', { class: 'sug-cabeza' },
          el('span', { class: 'sug-tipo', text: { arreglo: 'Arreglo', idea: 'Idea', consejo: 'En el slicer' }[sug.tipo] }),
          el('b', { text: sug.titulo })),
        el('p', { text: sug.por_que }));
      if (sug.antes && sug.despues) {
        fila.append(el('div', { class: 'sug-cambio' }, el('span', { text: sug.antes }), el('i', { text: '→' }), el('span', { text: sug.despues })));
      }
      if (sug.orden) {
        fila.append(el('button', { class: 'btn sug-aplicar', text: sug.tipo === 'idea' ? 'Hacerlo' : 'Aplicar',
          onclick: () => aplicarSugerencia(sug) }));
      }
      t.append(fila);
    }
    return t;
  }

  async function aplicarSugerencia(sug) {
    if (!sug || !sug.orden || st.ocupado) return;
    const previo = st.analisis, modeloPrevio = st.actual;
    await enviar('/api/usar', { n: st.actual }).catch(() => {});
    await ordenar(sug.orden);
    // el antes y el después, medidos de nuevo (no lo que se esperaba: lo que de verdad quedó)
    const ahora = st.analisis;
    if (previo && ahora && st.actual === modeloPrevio) {
      const r = $('#respuesta');
      const dp = previo.dimensiones, da = ahora.dimensiones;
      const filas = [
        ['Medidas (mm)', `${fmt(dp[0])}×${fmt(dp[1])}×${fmt(dp[2])}`, `${fmt(da[0])}×${fmt(da[1])}×${fmt(da[2])}`],
        ['Voladizo', `${fmt(previo.soporte_pct, 0)} %`, `${fmt(ahora.soporte_pct, 0)} %`],
        ['Plástico', `${fmt(previo.gramos, 0)} g`, `${fmt(ahora.gramos, 0)} g`],
        ['Tiempo', previo.tiempo, ahora.tiempo],
        ['¿Cabe?', previo.cabe ? 'sí' : 'no', ahora.cabe ? 'sí' : 'no'],
      ].filter(([, a, b]) => a !== b);
      if (filas.length) {
        r.append(document.createTextNode('\n\nAntes → después:'));
        for (const [n, a, b] of filas) r.append(document.createTextNode(`\n  ${n}: ${a} → ${b}`));
      }
    }
  }

  function tarjetaCapas() {
    const rango = el('input', { type: 'range', id: 'capaRango', min: '0', max: '1000', value: String(Math.round(st.capa * 1000)),
      'aria-label': 'Altura de corte', oninput: (e) => { st.simulando = false; ponerCapa(e.target.value / 1000); } });
    return el('div', { class: 'tarjeta' }, el('h2', { text: 'Capa por capa' }),
      el('div', { class: 'medida' }, el('label', { text: 'Altura de corte', for: 'capaRango' }), el('output', { id: 'capaTexto', text: '' }), rango),
      el('div', { class: 'acciones' },
        el('button', { class: 'btn', text: 'Simular impresión', onclick: () => { st.simulando = true; ponerCapa(0); } }),
        el('button', { class: 'btn', text: 'Ver completa', onclick: () => { st.simulando = false; ponerCapa(1); } })));
  }

  let relojMedidas = 0;
  function tarjetaMedidas() {
    const m = st.modelos.find((x) => x.nombre === st.actual);
    if (!m || !m.editable || !st.catalogo || !st.catalogo[m.pieza]) return null;
    const reglas = st.catalogo[m.pieza].medidas;
    const t = el('div', { class: 'tarjeta' }, el('h2', { text: 'Medidas (mm)' }),
      el('p', { class: 'tenue', text: 'Mueve y la pieza se rehace al instante.' }));
    const mandar = (clave, valor) => {
      m.medidas[clave] = valor;
      clearTimeout(relojMedidas);
      relojMedidas = setTimeout(async () => {
        const r = await enviar('/api/medidas', { n: st.actual, medidas: { [clave]: valor } });
        if (!r.ok) { aviso(r.error || 'No se pudo cambiar.'); return; }
        m.medidas = r.medidas;
        st.version = r.version;
        if (r.notas && r.notas.length) aviso('Ojo: ' + r.notas[0]);
        await cargarPieza(st.actual, false);
        st.analisis = await apiJson('/api/analisis?n=' + encodeURIComponent(st.actual));
        st.sugerencias = await apiJson('/api/sugerencias?n=' + encodeURIComponent(st.actual)).catch(() => st.sugerencias);
        pintar();
      }, 160);
    };
    for (const [clave, regla] of Object.entries(reglas)) {
      const valor = m.medidas[clave];
      const nombre = clave.replace(/_/g, ' ');
      if (regla.opciones) {
        const sel = el('select', { class: 'btn', 'aria-label': nombre, onchange: (e) => mandar(clave, e.target.value) });
        for (const o of regla.opciones) sel.append(el('option', { value: o, text: o.toUpperCase(), selected: o === valor }));
        t.append(el('div', { class: 'interruptor' }, el('span', { text: nombre }), sel));
      } else if (INTERRUPTORES.has(clave)) {
        const caja = el('input', { type: 'checkbox', id: 'm_' + clave, checked: !!valor, onchange: (e) => mandar(clave, e.target.checked ? 1 : 0) });
        t.append(el('div', { class: 'interruptor' }, caja, el('label', { for: 'm_' + clave, text: nombre })));
      } else {
        const entero = ENTEROS.has(clave);
        const tope = Math.min(regla.max, Math.max(valor * 3, regla.defecto * 3, regla.min + 10));
        const salida = el('output', { text: fmt(valor) });
        const rango = el('input', { type: 'range', id: 'm_' + clave, min: String(regla.min), max: String(tope), step: entero ? '1' : '0.5', value: String(valor),
          oninput: (e) => { const v = Number(e.target.value); salida.textContent = fmt(v); mandar(clave, v); } });
        t.append(el('div', { class: 'medida' }, el('label', { for: 'm_' + clave, text: nombre }), salida, rango));
      }
    }
    return t;
  }

  function pintar() {
    if (!st.visible) return;
    const foco = document.activeElement && document.activeElement.id;
    const p = ctx.panel;
    const arriba = p.scrollTop;
    p.innerHTML = '';
    if (!st.modelos.length) { p.append(tarjetaVacia()); return; }
    p.append(tarjetaModelos());
    if (st.actual) {
      p.append(tarjetaArche());
      p.append(tarjetaAnalisis());
      const medidas = tarjetaMedidas();
      if (medidas) p.append(medidas);
      p.append(tarjetaCapas());
      ponerCapa(st.capa);
    }
    p.scrollTop = arriba;
    if (foco && foco.startsWith('m_')) { const e = document.getElementById(foco); if (e) e.focus(); }
  }

  // ---- acciones ----
  async function elegir(nombre, reencuadrar) {
    if (nombre !== st.actual) limpiarMedida();
    st.actual = nombre;
    st.analisis = null;
    st.sugerencias = null;
    st.simulando = false;
    pintar();
    try {
      enviar('/api/usar', { n: nombre }).catch(() => {});      // las órdenes («hazla más alta») van a este modelo
      await cargarPieza(nombre, reencuadrar);
      st.analisis = await apiJson('/api/analisis?n=' + encodeURIComponent(nombre));
      st.sugerencias = await apiJson('/api/sugerencias?n=' + encodeURIComponent(nombre)).catch(() => ({ sugerencias: [] }));
    } catch (e) { aviso('No pude abrir ese modelo.'); }
    pintar();
  }

  async function refrescar(preferido) {
    const datos = await apiJson('/api/modelos');
    st.modelos = datos.modelos;
    st.carpeta = datos.carpeta;
    const nombres = st.modelos.map((m) => m.nombre);
    const objetivo = (preferido && nombres.includes(preferido)) ? preferido
      : (nombres.includes(st.actual) ? st.actual : (nombres.includes(datos.ultimo) ? datos.ultimo : nombres[0]));
    if (!objetivo) {
      st.actual = null; st.analisis = null; hayPieza = false;
      pieza.clear();
      Object.values(etqs).forEach((e) => { e.style.display = 'none'; });
      pintar();
      return;
    }
    await elegir(objetivo, objetivo !== st.actual || !hayPieza);
  }

  function responder(lineas, bien) {
    const r = $('#respuesta');
    r.innerHTML = '';
    lineas.forEach((linea, i) => { r.append(i === 0 ? el('b', { text: linea }) : document.createTextNode('\n' + linea)); });
    r.classList.add('ver');
    r.style.borderColor = bien ? '' : 'rgba(255,198,92,.4)';
  }

  async function ordenar(texto) {
    if (st.ocupado || !texto.trim()) return;
    st.ocupado = true;
    const boton = $('#pedir button');
    boton.disabled = true;
    boton.textContent = '…';
    try {
      const r = await enviar('/api/orden', { texto });
      responder(r.lineas && r.lineas.length ? r.lineas : ['Hecho.'], r.ok);
      st.version = r.version;
      await refrescar(r.ultimo);
    } catch (e) { responder(['No pude hablar con Arché. ¿Sigue abierto?'], false); }
    st.ocupado = false;
    boton.disabled = false;
    boton.textContent = 'Crear';
  }

  async function descargar() {
    const r = await api('/api/modelo?n=' + encodeURIComponent(st.actual));
    const enlace = el('a', { href: URL.createObjectURL(await r.blob()), download: st.actual + '.stl' });
    document.body.append(enlace);
    enlace.click();
    setTimeout(() => { URL.revokeObjectURL(enlace.href); enlace.remove(); }, 500);
  }

  let borrarArmado = 0;
  async function borrar() {
    if (Date.now() - borrarArmado > 3000) { borrarArmado = Date.now(); aviso('Pulsa «Borrar» otra vez para mandarlo a la papelera de modelos.'); return; }
    borrarArmado = 0;
    const r = await enviar('/api/borrar', { n: st.actual });
    st.version = r.version;
    st.actual = null;
    await refrescar();
  }

  async function subir(archivo) {
    if (!/\.(stl|obj)$/i.test(archivo.name)) { aviso('Solo abro archivos .stl y .obj.'); return; }
    aviso('Abriendo ' + archivo.name + '…');
    const r = await (await api('/api/subir?n=' + encodeURIComponent(archivo.name), { method: 'POST', body: archivo })).json();
    if (!r.ok) { aviso(r.error || 'No pude abrir ese archivo.'); return; }
    st.version = r.version;
    await refrescar(r.nombre);
  }

  // ---- la barra y el arrastrar archivos (se enganchan una vez) ----
  $('#pedir').addEventListener('submit', (e) => {
    e.preventDefault();
    const campo = $('#texto');
    const texto = campo.value;
    campo.value = '';
    // en Construir, primero lo intenta Construir («agrega un cilindro», «deshaz»…); si no es suyo, va a Arché
    if (document.body.dataset.vista === 'construir') {
      const v = ctx.vistaActiva();
      if (v && v.ordenEscrita && v.ordenEscrita(texto)) { $('#respuesta').classList.remove('ver'); return; }
    }
    ordenar(texto);
  });
  for (const idea of IDEAS) $('#ideas').append(el('button', { type: 'button', text: idea, onclick: () => ordenar(idea) }));
  let arrastres = 0;
  addEventListener('dragenter', (e) => { if (st.visible && e.dataTransfer && [...e.dataTransfer.types].includes('Files')) { arrastres++; $('#soltar').classList.add('ver'); } });
  addEventListener('dragleave', () => { arrastres = Math.max(0, arrastres - 1); if (!arrastres) $('#soltar').classList.remove('ver'); });
  addEventListener('dragover', (e) => e.preventDefault());
  addEventListener('drop', (e) => {
    e.preventDefault();
    arrastres = 0;
    $('#soltar').classList.remove('ver');
    if (st.visible && e.dataTransfer && e.dataTransfer.files[0]) subir(e.dataTransfer.files[0]);
  });

  const pA = new THREE.Vector3();
  return {
    escena, camara, controles,
    reencuadrar() { if (hayPieza) encuadrar(); },
    mostrar(nombre) { refrescar(nombre).catch(() => {}); },
    // con la mano: tocar mide (si «Medir» está encendido); deslizar cambia de pieza; pulgar aplica el arreglo
    tocar(x, y) {
      if (st.midiendo) medirEn(x, y);
      else if (puntoEnPieza(x, y)) aviso('Para medir, toca «Medir» y luego dos puntos de la pieza.');
    },
    deslizar(dir) {
      if (st.modelos.length < 2) { aviso('Solo hay una pieza.'); return true; }
      const i = Math.max(0, st.modelos.findIndex((m) => m.nombre === st.actual));
      const sig = st.modelos[(i + (dir === 'derecha' ? 1 : st.modelos.length - 1)) % st.modelos.length];
      elegir(sig.nombre, true);
      aviso(sig.nombre + '.stl');
      return true;
    },
    aceptar() {
      const sug = st.sugerencias && st.sugerencias.sugerencias.find((x) => x.tipo === 'arreglo');
      if (!sug) { aviso('Esta pieza no necesita arreglos.'); return; }
      aviso('Aplicando: ' + sug.titulo);
      aplicarSugerencia(sug);
    },
    entrar() {
      st.visible = true;
      controles.enabled = true;
      pintar();
      if (!st.catalogo) apiJson('/api/catalogo').then((c) => { st.catalogo = c; pintar(); }).catch(() => {});
      refrescar().catch(() => {});
    },
    salir() { st.visible = false; controles.enabled = false; },
    alEstado(e) {
      if (e.ajustes && e.ajustes.cama.join() !== camaActual.join()) { camaActual = e.ajustes.cama; pintarCama(camaActual); }
      if (!st.visible || st.ocupado) return;
      if (st.version !== -1 && e.version !== st.version) {       // Arché cambió algo por voz o por la consola
        st.version = e.version;
        refrescar(e.ultimo).catch(() => {});
      } else if (st.version === -1) st.version = e.version;
    },
    actualizar(dt) {
      if (st.simulando) {
        const siguiente = st.capa + dt / 7;
        if (siguiente >= 1) { st.simulando = false; ponerCapa(1); } else ponerCapa(siguiente);
      }
      if (puntosMedida.length === 2) ctx.colocar(etqMedida, pA.copy(puntosMedida[0]).add(puntosMedida[1]).multiplyScalar(0.5), camara);
      if (hayPieza && st.actual) {
        const mn = caja.min, mx = caja.max;
        const d = [mx.x - mn.x, mx.y - mn.y, mx.z - mn.z];
        etqs.x.textContent = 'X ' + fmt(d[0]);
        etqs.y.textContent = 'Y ' + fmt(d[1]);
        etqs.z.textContent = 'Z ' + fmt(d[2]);
        ctx.colocar(etqs.x, pA.set((mn.x + mx.x) / 2, mn.y - 6, 0), camara);
        ctx.colocar(etqs.y, pA.set(mx.x + 6, (mn.y + mx.y) / 2, 0), camara);
        ctx.colocar(etqs.z, pA.set(mx.x + 6, mx.y + 6, (mn.z + mx.z) / 2), camara);
      }
    },
  };
}
