// Manos: la cámara del PC ve tus manos y con gestos mueves la vista 3D (sin tocar el mouse).
// Usa MediaPipe Hands (Google), que viene incluido en lib/manos: funciona sin internet
// y la imagen de la cámara NUNCA sale de tu PC (se procesa aquí mismo, en el navegador).
import * as THREE from 'three';
import { crearInterprete } from './gestos.js';

const CONEXIONES = [[0, 1], [1, 2], [2, 3], [3, 4], [0, 5], [5, 6], [6, 7], [7, 8], [5, 9], [9, 10], [10, 11], [11, 12],
  [9, 13], [13, 14], [14, 15], [15, 16], [13, 17], [0, 17], [17, 18], [18, 19], [19, 20]];
const SENSIBILIDAD_GIRO = 5.5;      // radianes por ancho de imagen
const SENSIBILIDAD_MOVER = 1.4;     // fracción de la distancia por ancho de imagen
const NOMBRE_MODO = { nada: 'Te veo. Apunta, pellizca o abre la mano', girar: 'Girando', zoom: 'Acercar / alejar',
  palma: 'Mantén la palma…', apuntar: 'Apuntando: pellizca rápido para tocar', pulgar: 'Aceptando…',
  abajo: 'Borrando…', ve: 'Duplicando…', agarrar: 'Moviendo la parte', estirar: 'Estirando / girando la parte' };

// la guía de gestos: cada paso dice qué hacer y cómo se nota que ya lo hiciste
const GUIA = [
  { texto: 'Apunta con el índice (los otros dedos doblados) y mueve el puntero por la pantalla.',
    hecho: (o, g, dt) => (g.apuntar = (g.apuntar || 0) + (o.modo === 'apuntar' ? dt : 0)) > 0.8 },
  { texto: 'Ahora toca: junta índice y pulgar rápido, como un clic en el aire.', hecho: (o) => !!o.toque },
  { texto: 'Pellizca y mueve la mano sin soltar: la pieza gira.',
    hecho: (o, g) => { const v = o.giroMano || o.girar; return (g.girar = (g.girar || 0) + Math.abs(v[0]) + Math.abs(v[1])) > 0.15; } },
  { texto: 'Pellizca con las DOS manos y sepáralas: te acercas.',
    hecho: (o, g) => Math.abs(g.zoom = (g.zoom || 0) + Math.log(o.zoom)) > 0.35 },
  { texto: 'Pasa la mano abierta rápido de un lado al otro: cambias de pieza.', hecho: (o) => !!o.deslizar },
  { texto: 'Pulgar arriba y quieto: aceptas lo que Arché recomienda.', hecho: (o) => o.aceptar },
  { texto: 'Por último, palma abierta quieta un segundo: la vista vuelve al inicio.', hecho: (o) => o.reiniciar },
];

function cargarScript(src) {
  return new Promise((ok, mal) => {
    if (window.Hands) return ok();
    const s = document.createElement('script');
    s.src = src;
    s.onload = ok;
    s.onerror = () => mal(new Error('no cargó ' + src));
    document.head.append(s);
  });
}

export function crearManos(ctx) {
  const { $ } = ctx;
  const caja = $('#manos');
  const lienzo = $('#manosVista');
  const dib = lienzo.getContext('2d');
  const etiqueta = $('#manosEstado');
  const cursores = [0, 1].map(() => {
    const c = document.createElement('div');
    c.className = 'cursor-mano';
    c.innerHTML = '<i></i>';
    document.body.append(c);
    return c;
  });
  const interprete = crearInterprete();
  const guiaCaja = $('#guiaManos');
  const st = { guia: null, arrastre: null, encima: null, modoAntes: 'nada', activo: false, arrancando: false, video: null, flujo: null, hands: null, orden: null,
               inercia: [0, 0], cuadros: 0, fps: 0, relojFps: 0, sinManos: 0, error: '' };

  // ---- mover la cámara de la vista que se esté viendo ----
  const _q = new THREE.Quaternion(), _qi = new THREE.Quaternion(), _o = new THREE.Vector3(),
        _s = new THREE.Spherical(), _y = new THREE.Vector3(0, 1, 0), _d = new THREE.Vector3(), _a = new THREE.Vector3();

  function girar(vista, az, pol) {
    const c = vista.camara, t = vista.controles.target;
    _q.setFromUnitVectors(c.up, _y); _qi.copy(_q).invert();
    _o.copy(c.position).sub(t).applyQuaternion(_q);
    _s.setFromVector3(_o);
    _s.theta -= az;
    const maxPol = Math.min(vista.controles.maxPolarAngle, Math.PI - 0.05);
    _s.phi = Math.max(0.05, Math.min(maxPol, _s.phi - pol));
    _o.setFromSpherical(_s).applyQuaternion(_qi);
    c.position.copy(t).add(_o);
    c.lookAt(t);
  }
  function acercar(vista, factor) {
    const c = vista.camara, t = vista.controles.target;
    _o.copy(c.position).sub(t);
    const d = Math.max(vista.controles.minDistance, Math.min(vista.controles.maxDistance, _o.length() * factor));
    c.position.copy(t).add(_o.setLength(d));
  }
  function desplazar(vista, dx, dy) {
    const c = vista.camara, t = vista.controles.target;
    const dist = c.position.distanceTo(t);
    c.matrixWorld.extractBasis(_d, _a, _o);               // derecha, arriba, atrás de la cámara
    const mov = _d.multiplyScalar(-dx * dist * SENSIBILIDAD_MOVER).add(_a.multiplyScalar(dy * dist * SENSIBILIDAD_MOVER));
    c.position.add(mov);
    t.add(mov);
  }

  // ---- dibujo de la ventanita (cámara + esqueleto de las manos) ----
  function dibujar(res) {
    const w = lienzo.width, h = lienzo.height;
    dib.save();
    dib.clearRect(0, 0, w, h);
    if (res.image) dib.drawImage(res.image, 0, 0, w, h);
    dib.fillStyle = 'rgba(12,12,20,.35)';
    dib.fillRect(0, 0, w, h);
    (res.multiHandLandmarks || []).forEach((p, i) => {
      const pellizca = st.orden && st.orden.cursores[i] && st.orden.cursores[i].pellizca;
      dib.strokeStyle = pellizca ? '#ffc65c' : '#8b7cff';
      dib.lineWidth = 2;
      dib.beginPath();
      for (const [a, b] of CONEXIONES) { dib.moveTo(p[a].x * w, p[a].y * h); dib.lineTo(p[b].x * w, p[b].y * h); }
      dib.stroke();
      dib.fillStyle = '#ededf4';
      for (const q of p) { dib.beginPath(); dib.arc(q.x * w, q.y * h, 2, 0, 7); dib.fill(); }
    });
    dib.restore();
  }

  function alResultado(res, tFijo) {
    const lista = (res.multiHandLandmarks || []).map((puntos, i) => ({
      puntos, lado: (res.multiHandedness && res.multiHandedness[i] && res.multiHandedness[i].label) || 'mano' }));
    const t = tFijo != null ? tFijo : performance.now() / 1000;
    const orden = interprete.paso(lista, t);
    st.orden = orden;
    st.cuadros++;
    if (t - st.relojFps > 1) { st.fps = st.cuadros / (t - st.relojFps || 1); st.cuadros = 0; st.relojFps = t; }
    st.sinManos = lista.length ? 0 : st.sinManos + 1;

    const vista = ctx.vistaActiva();
    const modoCrudo = orden.modo;          // el gesto tal como llegó (abajo se le puede cambiar el nombre)
    if (vista) {
      if (orden.modo !== 'nada') vista.controles.autoRotate = false;
      if (orden.modo === 'girar' && st.modoAntes !== 'girar' && orden.puntero) empezarArrastre(orden.puntero);
      if (orden.modo !== 'girar' && st.arrastre) {
        if (st.arrastre.tipo === 'vista' && vista.soltar) vista.soltar();
        st.arrastre = null;
      }
      // agarrar una parte (Construir): la mano la mueve en vez de girar la cámara
      if (st.arrastre && st.arrastre.tipo === 'vista' && orden.puntero && vista.arrastrar) {
        vista.arrastrar(orden.puntero.x * innerWidth, orden.puntero.y * innerHeight);
        orden.modo = 'agarrar';
      }
      const enEscena = !st.arrastre || st.arrastre.tipo === 'escena';
      orden.giroMano = orden.girar;
      if (!enEscena) orden.girar = [0, 0];
      if (orden.girar[0] || orden.girar[1]) {
        const az = orden.girar[0] * SENSIBILIDAD_GIRO, pol = orden.girar[1] * SENSIBILIDAD_GIRO;
        girar(vista, az, pol);
        if (orden.dt > 0) st.inercia = [az / orden.dt, pol / orden.dt];
      } else if (orden.modo === 'girar') {
        st.inercia = [0, 0];
      }
      // dos manos sobre una parte elegida (Construir): estirarla y girarla en vez de acercar la cámara
      if (orden.modo === 'zoom' && vista.dosManos && vista.dosManos(orden)) {
        orden.modo = 'estirar';
        st.inercia = [0, 0];
      }
      if (orden.modo === 'zoom') {
        st.inercia = [0, 0];
        if (orden.zoom !== 1) acercar(vista, Math.max(0.85, Math.min(1.18, orden.zoom)));
        if (orden.mover[0] || orden.mover[1]) desplazar(vista, orden.mover[0], orden.mover[1]);
      }
      if (orden.reiniciar) { st.inercia = [0, 0]; vista.reencuadrar && vista.reencuadrar(); ctx.aviso('Vista reiniciada'); }
    }
    manejarPuntero(orden);
    if (st.guia) avanzarGuia(orden);
    else {
      if (orden.toque) tocarEn(orden.toque.x * innerWidth, orden.toque.y * innerHeight);
      if (orden.deslizar) ctx.deslizar && ctx.deslizar(orden.deslizar);
      if (orden.aceptar) ctx.aceptar && ctx.aceptar();
      if (orden.rechazar) ctx.rechazar && ctx.rechazar();
      if (orden.duplicar) ctx.duplicar && ctx.duplicar();
    }
    st.modoAntes = modoCrudo;
    dibujar(res);
    pintarEstado();
  }

  // ---- tocar, arrastrar y señalar cosas de la página con la mano ----
  // todo lo que no sea un control o un panel cuenta como la escena 3D (la pieza, el fondo, los textos sueltos)
  const esEscena = (el) => !el || !el.closest('button, a, input, select, label, summary, [data-tocable], #panel, #riel, #manos, #guiaManos, #pedir, #ideas');
  function bajo(x, y) {
    const el = document.elementFromPoint(x, y);
    return el && !el.closest('.cursor-mano') ? el : null;
  }
  function moverRango(el, x) {
    const r = el.getBoundingClientRect();
    const f = Math.max(0, Math.min(1, (x - r.left) / Math.max(1, r.width)));
    const min = Number(el.min || 0), max = Number(el.max || 100), paso = Number(el.step) || 1;
    const v = Math.round((min + f * (max - min)) / paso) * paso;
    if (String(v) !== el.value) {
      el.value = String(v);
      el.dispatchEvent(new Event('input', { bubbles: true }));
      el.dispatchEvent(new Event('change', { bubbles: true }));
    }
  }
  function empezarArrastre(p) {
    const x = p.x * innerWidth, y = p.y * innerHeight;
    const el = bajo(x, y);
    if (esEscena(el)) {
      const v = ctx.vistaActiva();
      st.arrastre = { tipo: v && v.agarrar && v.agarrar(x, y) ? 'vista' : 'escena' };
      return;
    }
    const rango = el.closest('input[type=range]');
    // pellizcar sobre un panel y mover la mano arriba/abajo lo desplaza (como arrastrar con el dedo en el celular)
    const panel = el.closest('#panel, .modelos, .relacion, #respuesta');
    st.arrastre = rango ? { tipo: 'rango', el: rango, id: rango.id }
      : { tipo: 'panel', el: panel, y: p.y * innerHeight };
  }
  function manejarPuntero(o) {
    if (st.arrastre && st.arrastre.tipo === 'rango' && o.puntero) {
      // el panel se vuelve a dibujar mientras arrastras: se busca el deslizador por su id
      const el = (st.arrastre.id && document.getElementById(st.arrastre.id)) || st.arrastre.el;
      if (el && el.isConnected) moverRango(el, o.puntero.x * innerWidth);
    }
    if (st.arrastre && st.arrastre.tipo === 'panel' && st.arrastre.el && o.puntero) {
      const y = o.puntero.y * innerHeight;
      st.arrastre.el.scrollTop -= (y - st.arrastre.y) * 1.6;
      st.arrastre.y = y;
    }
    let nuevo = null;
    if (o.puntero) {
      const el = bajo(o.puntero.x * innerWidth, o.puntero.y * innerHeight);
      nuevo = el && !esEscena(el) ? el.closest('button, a, input, select, label, summary, [data-tocable]') : null;
      // el dedo apuntando a la escena (Modelar → el pincel sigue al dedo)
      const v = ctx.vistaActiva();
      if (v && v.puntero && esEscena(el)) v.puntero(o.puntero.x * innerWidth, o.puntero.y * innerHeight);
    }
    if (nuevo !== st.encima) {
      if (st.encima) st.encima.classList.remove('mano-encima');
      if (nuevo) nuevo.classList.add('mano-encima');
      st.encima = nuevo;
    }
  }
  function tocarEn(x, y) {
    const el = bajo(x, y);
    destello(x, y);
    if (esEscena(el)) {
      const v = ctx.vistaActiva();
      if (v && v.tocar) v.tocar(x, y);
      return;
    }
    const rango = el.closest('input[type=range]');
    if (rango) { moverRango(rango, x); return; }
    const objetivo = el.closest('button, a, input, select, label, summary, [data-tocable]');
    if (!objetivo) return;
    if (objetivo.matches('input[type=text], input[type=search], input:not([type])')) objetivo.focus();
    else objetivo.click();
  }
  function destello(x, y) {
    const d = document.createElement('div');
    d.className = 'toque-mano';
    d.style.left = x + 'px';
    d.style.top = y + 'px';
    document.body.append(d);
    setTimeout(() => d.remove(), 520);
  }

  // ---- guía de gestos ----
  function pintarGuia(bien) {
    if (!st.guia) { guiaCaja.hidden = true; return; }
    guiaCaja.hidden = false;
    const i = st.guia.paso;
    guiaCaja.querySelector('.guia-num').textContent = i < GUIA.length ? `Gesto ${i + 1} de ${GUIA.length}` : '¡Listo!';
    guiaCaja.querySelector('.guia-texto').textContent = i < GUIA.length ? GUIA[i].texto
      : 'Ya sabes todos los gestos. Puedes repasarlos cuando quieras con «Aprender gestos».';
    guiaCaja.querySelector('.guia-puntos').innerHTML = GUIA.map((_, k) => `<i class="${k < i ? 'hecho' : k === i ? 'ahora' : ''}"></i>`).join('');
    guiaCaja.classList.toggle('bien', !!bien);
  }
  function empezarGuia() {
    if (!st.activo && !st.arrancando) encender();
    st.guia = { paso: 0, datos: {}, pausa: 0 };
    pintarGuia();
  }
  function avanzarGuia(o) {
    const g = st.guia;
    if (g.paso >= GUIA.length) return;
    if (performance.now() < g.pausa) return;
    if (GUIA[g.paso].hecho(o, g.datos, o.dt || 0)) {
      g.paso++;
      g.datos = {};
      g.pausa = performance.now() + 900;
      pintarGuia(true);
      setTimeout(() => pintarGuia(false), 900);
      if (g.paso >= GUIA.length) setTimeout(() => { st.guia = null; pintarGuia(); }, 4000);
    }
  }
  $('#guiaCerrar').addEventListener('click', () => { st.guia = null; pintarGuia(); });
  $('#manosGuia').addEventListener('click', empezarGuia);

  function pintarEstado() {
    const o = st.orden;
    const n = o ? o.cursores.length : 0;
    let texto = n ? NOMBRE_MODO[o.modo] || '' : 'No veo tus manos';
    if (o && ['palma', 'pulgar', 'abajo', 've'].includes(o.modo)) texto += ` ${Math.round(o.progreso * 100)} %`;
    if (o && o.consejo) texto = o.consejo;
    etiqueta.textContent = texto;
    caja.dataset.modo = n ? o.modo : 'sin';
    cursores.forEach((c, i) => {
      const cur = o && o.cursores[i];
      if (!cur) { c.style.display = 'none'; return; }
      c.style.display = 'block';
      c.style.left = (cur.x * innerWidth).toFixed(1) + 'px';
      c.style.top = (cur.y * innerHeight).toFixed(1) + 'px';
      c.classList.toggle('pellizca', cur.pellizca);
      c.classList.toggle('abierta', cur.abierta);
      c.classList.toggle('apunta', !!cur.apunta);
      c.classList.toggle('pulgar', !!cur.pulgar);
      c.classList.toggle('abajo', !!cur.pulgarAbajo);
      c.classList.toggle('ve', !!cur.ve);
      const sostiene = (cur.abierta && o.modo === 'palma') || (cur.pulgar && o.modo === 'pulgar') ||
        (cur.pulgarAbajo && o.modo === 'abajo') || (cur.ve && o.modo === 've');
      c.style.setProperty('--progreso', sostiene ? o.progreso : 0);
    });
  }

  async function bucle() {
    while (st.activo) {
      if (st.video.readyState >= 2 && !st.simulando) {
        try { await st.hands.send({ image: st.video }); } catch (e) { /* un cuadro malo no detiene nada */ }
      }
      await new Promise((r) => requestAnimationFrame(r));
    }
  }

  async function encender() {
    if (st.activo || st.arrancando) return;
    st.arrancando = true;
    caja.hidden = false;
    caja.dataset.modo = 'cargando';
    etiqueta.textContent = 'Encendiendo la cámara…';
    try {
      if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) throw new Error('este navegador no deja usar la cámara');
      st.flujo = await navigator.mediaDevices.getUserMedia({ video: { width: { ideal: 640 }, height: { ideal: 480 }, facingMode: 'user' }, audio: false });
      st.video = document.createElement('video');
      st.video.playsInline = true;
      st.video.muted = true;
      st.video.srcObject = st.flujo;
      await st.video.play();
      etiqueta.textContent = 'Cargando el detector de manos…';
      if (!st.hands) {
        await cargarScript('/lib/manos/hands.js');
        st.hands = new window.Hands({ locateFile: (f) => '/lib/manos/' + f });
        st.hands.setOptions({ selfieMode: true, maxNumHands: 2, modelComplexity: 1, minDetectionConfidence: 0.6, minTrackingConfidence: 0.5 });
        st.hands.onResults(alResultado);
        await st.hands.initialize();
      }
      interprete.reiniciar();
      st.activo = true;
      st.relojFps = performance.now() / 1000;
      document.body.classList.add('con-manos');
      ctx.alManos && ctx.alManos(true);
      bucle();
    } catch (e) {
      apagarCamara();
      const txt = (e && e.name === 'NotAllowedError') ? 'No me diste permiso para la cámara (revisa el candado de la barra de direcciones).'
        : (e && e.name === 'NotFoundError') ? 'No encontré ninguna cámara conectada.'
        : (e && e.name === 'NotReadableError') ? 'La cámara la está usando otro programa (¿el perro o Zoom?).'
        : 'No pude encender el control con las manos: ' + (e && e.message ? e.message : e);
      st.error = txt;
      caja.dataset.modo = 'error';
      etiqueta.textContent = txt;
      ctx.alManos && ctx.alManos(false);
    }
    st.arrancando = false;
  }

  function apagarCamara() {
    st.activo = false;
    if (st.flujo) st.flujo.getTracks().forEach((t) => t.stop());
    st.flujo = null;
    if (st.video) { st.video.srcObject = null; st.video = null; }
  }

  function apagar() {
    apagarCamara();
    st.guia = null;
    pintarGuia();
    if (st.encima) { st.encima.classList.remove('mano-encima'); st.encima = null; }
    caja.hidden = true;
    st.orden = null;
    st.inercia = [0, 0];
    cursores.forEach((c) => { c.style.display = 'none'; });
    document.body.classList.remove('con-manos');
    ctx.alManos && ctx.alManos(false);
  }

  $('#manosCerrar').addEventListener('click', apagar);

  return {
    encender, apagar, empezarGuia,
    depurar: () => ({ arrastre: st.arrastre && st.arrastre.tipo, id: st.arrastre && st.arrastre.id, guia: st.guia && st.guia.paso }),
    activo: () => st.activo || st.arrancando,
    alternar() { (st.activo || st.arrancando) ? apagar() : encender(); },
    // cada cuadro de dibujo: la inercia del último giro se va frenando
    actualizar(dt) {
      if (!st.activo) return;
      const v = ctx.vistaActiva();
      const [az, pol] = st.inercia;
      if (v && (Math.abs(az) > 0.02 || Math.abs(pol) > 0.02) && (!st.orden || st.orden.modo !== 'girar')) {
        girar(v, az * dt, pol * dt);
        const freno = Math.exp(-dt * 3.5);
        st.inercia = [az * freno, pol * freno];
      }
    },
    // para las pruebas: meter manos falsas como si vinieran de la cámara
    simular(listaDePuntos, t) {
      st.simulando = true;              // la cámara real deja de mandar cuadros mientras se prueba
      caja.hidden = false;
      alResultado({ multiHandLandmarks: listaDePuntos, multiHandedness: listaDePuntos.map((_, i) => ({ label: i ? 'Left' : 'Right' })) }, t);
      return st.orden;
    },
  };
}
