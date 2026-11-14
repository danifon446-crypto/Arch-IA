// Cerebro: el mapa de Arché. Cada punto es un archivo de core/; cada línea, un archivo que usa a otro.
import * as THREE from 'three';
import { OrbitControls } from './lib/OrbitControls.js';

const COLORES = { nucleo: 0x8b7cff, IA: 0xffc65c, interfaz: 0x6aa8ff, agente: 0x4fd08b, cerebro: 0xff8ad8,
                  seguridad: 0xff7088, tres_d: 0x5fd3c4 };
const NOMBRES = { nucleo: 'Funciones base', IA: 'Inteligencia', interfaz: 'Interfaz', agente: 'Agente autónomo',
                  cerebro: 'Intenciones', seguridad: 'Seguridad', tres_d: 'Arché 3D' };
const colorDe = (grupo) => COLORES[grupo] || 0x9494a8;

// Acomoda los nodos: todos se repelen, los conectados se atraen, y cada grupo tira hacia su rincón.
function acomodar(nodos, enlaces) {
  const n = nodos.length;
  const grupos = [...new Set(nodos.map((x) => x.grupo))];
  const ancla = {};
  grupos.forEach((g, i) => {
    const a = (i / grupos.length) * Math.PI * 2;
    ancla[g] = [Math.cos(a) * 55, Math.sin(a * 2.1) * 26, Math.sin(a) * 55];
  });
  let semilla = 7;
  const azar = () => { semilla = (semilla * 16807) % 2147483647; return semilla / 2147483647 - 0.5; };
  const p = nodos.map((x) => ancla[x.grupo].map((v) => v + azar() * 60));
  const f = nodos.map(() => [0, 0, 0]);
  for (let vuelta = 0; vuelta < 260; vuelta++) {
    const calor = 1 - vuelta / 260;
    for (let i = 0; i < n; i++) { f[i][0] = f[i][1] = f[i][2] = 0; }
    for (let i = 0; i < n; i++) {
      for (let j = i + 1; j < n; j++) {
        const dx = p[i][0] - p[j][0], dy = p[i][1] - p[j][1], dz = p[i][2] - p[j][2];
        const d2 = dx * dx + dy * dy + dz * dz + 0.5;
        const k = 900 / (d2 * Math.sqrt(d2));
        f[i][0] += dx * k; f[i][1] += dy * k; f[i][2] += dz * k;
        f[j][0] -= dx * k; f[j][1] -= dy * k; f[j][2] -= dz * k;
      }
    }
    for (const [a, b] of enlaces) {
      const dx = p[b][0] - p[a][0], dy = p[b][1] - p[a][1], dz = p[b][2] - p[a][2];
      const d = Math.sqrt(dx * dx + dy * dy + dz * dz) + 0.01;
      const k = (d - 22) * 0.012 / d;
      f[a][0] += dx * k * d; f[a][1] += dy * k * d; f[a][2] += dz * k * d;
      f[b][0] -= dx * k * d; f[b][1] -= dy * k * d; f[b][2] -= dz * k * d;
    }
    for (let i = 0; i < n; i++) {
      const an = ancla[nodos[i].grupo];
      for (let c = 0; c < 3; c++) {
        f[i][c] += (an[c] - p[i][c]) * 0.02;
        const paso = Math.max(-6, Math.min(6, f[i][c])) * (0.25 + calor);
        p[i][c] += paso;
      }
    }
  }
  return p;
}

export function crearCerebro(ctx) {
  const { render, apiJson } = ctx;
  const escena = new THREE.Scene();
  escena.fog = new THREE.Fog(0x0c0c14, 180, 520);
  const camara = new THREE.PerspectiveCamera(42, 1, 1, 2000);
  camara.position.set(0, 60, 250);
  const controles = new OrbitControls(camara, render.domElement);
  controles.enableDamping = true;
  controles.autoRotate = !ctx.quieto;
  controles.autoRotateSpeed = 0.35;
  controles.minDistance = 40;
  controles.maxDistance = 600;
  controles.enabled = false;

  const st = { visible: false, datos: null, elegido: -1, sobre: -1, mallas: [], usa: [], loUsan: [], lineas: null, filtro: '' };
  const geo = new THREE.SphereGeometry(1, 20, 16);
  const grupoNodos = new THREE.Group();
  escena.add(grupoNodos);
  const etqs = Array.from({ length: 12 }, () => ctx.etiqueta('nodo'));
  const etqElegido = ctx.etiqueta('nodo fuerte');
  const rayo = new THREE.Raycaster();
  const raton = new THREE.Vector2();

  function construir(datos) {
    const pos = acomodar(datos.nodos, datos.enlaces);
    st.usa = datos.nodos.map(() => []);
    st.loUsan = datos.nodos.map(() => []);
    for (const [a, b] of datos.enlaces) { st.usa[a].push(b); st.loUsan[b].push(a); }
    datos.nodos.forEach((nodo, i) => {
      const m = new THREE.Mesh(geo, new THREE.MeshBasicMaterial({ color: colorDe(nodo.grupo) }));
      m.position.set(pos[i][0], pos[i][1], pos[i][2]);
      nodo.radio = 0.9 + Math.sqrt(nodo.lineas) * 0.085;
      m.scale.setScalar(nodo.radio);
      m.userData.i = i;
      grupoNodos.add(m);
      st.mallas.push(m);
    });
    const puntos = new Float32Array(datos.enlaces.length * 6);
    const colores = new Float32Array(datos.enlaces.length * 6);
    datos.enlaces.forEach(([a, b], k) => {
      puntos.set([pos[a][0], pos[a][1], pos[a][2], pos[b][0], pos[b][1], pos[b][2]], k * 6);
    });
    const g = new THREE.BufferGeometry();
    g.setAttribute('position', new THREE.BufferAttribute(puntos, 3));
    g.setAttribute('color', new THREE.BufferAttribute(colores, 3));
    st.lineas = new THREE.LineSegments(g, new THREE.LineBasicMaterial({ vertexColors: true, transparent: true, opacity: 0.9, blending: THREE.AdditiveBlending, depthWrite: false }));
    escena.add(st.lineas);
    // los más grandes llevan su nombre siempre
    st.grandes = datos.nodos.map((x, i) => i).sort((a, b) => datos.nodos[b].lineas - datos.nodos[a].lineas).slice(0, etqs.length);
    st.grandes.forEach((i, k) => { etqs[k].textContent = datos.nodos[i].nombre; });
    resaltar();
  }

  function resaltar() {
    if (!st.datos) return;
    const e = st.elegido;
    const cercanos = new Set(e >= 0 ? [e, ...st.usa[e], ...st.loUsan[e]] : []);
    const filtro = st.filtro.trim().toLowerCase();
    st.mallas.forEach((m, i) => {
      const nodo = st.datos.nodos[i];
      const base = new THREE.Color(colorDe(nodo.grupo));
      let fuerza = 1;
      if (e >= 0) fuerza = cercanos.has(i) ? 1 : 0.16;
      if (filtro) fuerza = nodo.id.toLowerCase().includes(filtro) ? 1 : 0.1;
      m.material.color.copy(base).multiplyScalar(fuerza);
      m.scale.setScalar(nodo.radio * (i === e ? 1.5 : 1));
    });
    const col = st.lineas.geometry.getAttribute('color');
    const c = new THREE.Color();
    st.datos.enlaces.forEach(([a, b], k) => {
      if (e >= 0 && (a === e || b === e)) c.setHex(a === e ? 0xffc65c : 0x6aa8ff);      // ámbar: lo que usa · azul: quién lo usa
      else c.setHex(0x8b7cff).multiplyScalar(e >= 0 || filtro ? 0.04 : 0.16);
      col.setXYZ(k * 2, c.r, c.g, c.b);
      col.setXYZ(k * 2 + 1, c.r, c.g, c.b);
    });
    col.needsUpdate = true;
  }

  function elegir(i) {
    st.elegido = i;
    controles.autoRotate = i < 0 && !ctx.quieto;
    resaltar();
    pintar();
  }

  function pintar() {
    if (!st.visible) return;
    const p = ctx.panel;
    const foco = document.activeElement && document.activeElement.id === 'buscaNodo';
    p.innerHTML = '';
    const t1 = document.createElement('div');
    t1.className = 'tarjeta';
    t1.innerHTML = '<h2>Arché por dentro</h2>';
    if (!st.datos) { t1.insertAdjacentHTML('beforeend', '<p class="tenue">Leyendo el código de Arché…</p>'); p.append(t1); return; }
    const d = st.datos;
    const cifras = document.createElement('div'); cifras.className = 'cifras';
    cifras.innerHTML = `<div class="cifra"><b>${d.nodos.length}</b><span>archivos</span></div>
      <div class="cifra"><b>${d.total_lineas.toLocaleString('es')}</b><span>líneas de código</span></div>
      <div class="cifra ancha"><b>${d.enlaces.length}</b><span>conexiones entre archivos</span></div>`;
    t1.append(cifras);
    const busca = document.createElement('input');
    Object.assign(busca, { id: 'buscaNodo', type: 'search', placeholder: 'Buscar un archivo…', value: st.filtro, className: 'btn' });
    busca.setAttribute('aria-label', 'Buscar un archivo');
    busca.style.cssText = 'width:100%;margin-top:10px;cursor:text';
    busca.addEventListener('input', () => { st.filtro = busca.value; resaltar(); });
    t1.append(busca);
    const leyenda = document.createElement('div'); leyenda.className = 'leyenda'; leyenda.style.marginTop = '11px';
    const cuenta = {};
    d.nodos.forEach((x) => { cuenta[x.grupo] = (cuenta[x.grupo] || 0) + 1; });
    Object.entries(cuenta).sort((a, b) => b[1] - a[1]).forEach(([g, n]) => {
      const s = document.createElement('span');
      const i = document.createElement('i'); i.style.background = '#' + colorDe(g).toString(16).padStart(6, '0');
      s.append(i, document.createTextNode(`${NOMBRES[g] || g} · ${n}`));
      leyenda.append(s);
    });
    t1.append(leyenda);
    p.append(t1);

    const t2 = document.createElement('div');
    t2.className = 'tarjeta';
    if (st.elegido < 0) {
      t2.innerHTML = '<h2>Explorar</h2><p class="tenue">Toca un punto para ver qué hace ese archivo, a quién usa (líneas ámbar) y quién lo usa (líneas azules). Arrastra para girar, rueda para acercar.</p>';
    } else {
      const nodo = d.nodos[st.elegido];
      t2.innerHTML = '<h2>Archivo</h2>';
      const h = document.createElement('h3'); h.textContent = nodo.id.replace(/\./g, '/') + '.py';
      const info = document.createElement('p'); info.className = 'tenue';
      info.textContent = `${nodo.lineas.toLocaleString('es')} líneas · ${NOMBRES[nodo.grupo] || nodo.grupo}`;
      t2.append(h, info);
      if (nodo.resumen) { const r = document.createElement('p'); r.style.cssText = 'font-size:12.5px;margin:8px 0 0'; r.textContent = nodo.resumen; t2.append(r); }
      for (const [titulo, lista] of [[`Usa a · ${st.usa[st.elegido].length}`, st.usa[st.elegido]], [`Lo usan · ${st.loUsan[st.elegido].length}`, st.loUsan[st.elegido]]]) {
        if (!lista.length) continue;
        const sub = document.createElement('h2'); sub.textContent = titulo; sub.style.marginTop = '12px';
        const ul = document.createElement('ul'); ul.className = 'relacion';
        for (const j of lista) {
          const li = document.createElement('li');
          const b = document.createElement('button');
          b.className = 'btn'; b.style.cssText = 'border:0;background:none;padding:1px 0;font:inherit;color:inherit';
          b.textContent = d.nodos[j].id.replace(/^core\./, '');
          b.addEventListener('click', () => elegir(j));
          li.append(b); ul.append(li);
        }
        t2.append(sub, ul);
      }
      const fila = document.createElement('div'); fila.className = 'acciones';
      const cerrar = document.createElement('button'); cerrar.className = 'btn'; cerrar.textContent = 'Ver todo';
      cerrar.addEventListener('click', () => elegir(-1));
      fila.append(cerrar); t2.append(fila);
    }
    p.append(t2);
    if (foco) { const b = document.getElementById('buscaNodo'); b.focus(); b.setSelectionRange(b.value.length, b.value.length); }
  }

  // tocar un nodo (sin confundirlo con arrastrar para girar)
  let abajo = null;
  function nodoBajo(ev) {
    raton.set((ev.clientX / innerWidth) * 2 - 1, -(ev.clientY / innerHeight) * 2 + 1);
    rayo.setFromCamera(raton, camara);
    const toque = rayo.intersectObjects(st.mallas, false)[0];
    return toque ? toque.object.userData.i : -1;
  }
  render.domElement.addEventListener('pointerdown', (ev) => { if (st.visible) abajo = [ev.clientX, ev.clientY]; });
  render.domElement.addEventListener('pointerup', (ev) => {
    if (!st.visible || !abajo) return;
    const movio = Math.hypot(ev.clientX - abajo[0], ev.clientY - abajo[1]) > 5;
    abajo = null;
    if (movio) return;
    elegir(nodoBajo(ev));
  });
  render.domElement.addEventListener('pointermove', (ev) => {
    if (!st.visible || !st.datos || ev.buttons) return;
    st.sobre = nodoBajo(ev);
    render.domElement.style.cursor = st.sobre >= 0 ? 'pointer' : '';
  });

  const pv = new THREE.Vector3();
  return {
    escena, camara, controles,
    entrar() {
      st.visible = true;
      controles.enabled = true;
      pintar();
      if (!st.datos && !st.pidiendo) {
        st.pidiendo = true;
        apiJson('/api/cerebro').then((d) => { st.datos = d; construir(d); pintar(); }).catch(() => { st.pidiendo = false; });
      }
    },
    salir() { st.visible = false; controles.enabled = false; render.domElement.style.cursor = ''; },
    actualizar() {
      if (!st.datos) return;
      const visibles = new Set();
      st.grandes.forEach((i, k) => {
        const apagado = (st.elegido >= 0 && i !== st.elegido && !st.usa[st.elegido].includes(i) && !st.loUsan[st.elegido].includes(i));
        if (apagado || i === st.elegido || i === st.sobre) { etqs[k].style.display = 'none'; return; }
        const m = st.mallas[i];
        ctx.colocar(etqs[k], pv.copy(m.position).setY(m.position.y + st.datos.nodos[i].radio + 2.2), camara);
        visibles.add(i);
      });
      const destacado = st.sobre >= 0 ? st.sobre : st.elegido;
      if (destacado >= 0) {
        const m = st.mallas[destacado];
        etqElegido.textContent = st.datos.nodos[destacado].id.replace(/^core\./, '');
        ctx.colocar(etqElegido, pv.copy(m.position).setY(m.position.y + st.datos.nodos[destacado].radio * 1.5 + 2.6), camara);
      } else etqElegido.style.display = 'none';
    },
  };
}
