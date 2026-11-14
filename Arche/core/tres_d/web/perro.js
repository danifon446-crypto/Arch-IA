// Perro: el robot en 3D, movido con los MISMOS ángulos que Arché le manda a los servos.
import * as THREE from 'three';
import { OrbitControls } from './lib/OrbitControls.js';

const PATAS = [                      // orden de los servos: DD, DI, TD, TI (hombro, muslo, rodilla)
  { clave: 'DD', nombre: 'Delantera der.', x: 1, y: -1 }, { clave: 'DI', nombre: 'Delantera izq.', x: 1, y: 1 },
  { clave: 'TD', nombre: 'Trasera der.', x: -1, y: -1 }, { clave: 'TI', nombre: 'Trasera izq.', x: -1, y: 1 },
];
const CUERPO = { largo: 250, ancho: 110, alto: 62, ejes: 190 };   // aproximado (mm); ejes = distancia entre caderas
const RAD = Math.PI / 180;

export function crearPerro(ctx) {
  const { render, apiJson } = ctx;
  const escena = new THREE.Scene();
  escena.fog = new THREE.Fog(0x0c0c14, 1400, 3600);
  const camara = new THREE.PerspectiveCamera(36, 1, 5, 8000);
  camara.up.set(0, 0, 1);
  camara.position.set(520, -640, 360);
  const controles = new OrbitControls(camara, render.domElement);
  controles.enableDamping = true;
  controles.target.set(0, 0, 150);
  controles.maxPolarAngle = Math.PI * 0.495;
  controles.minDistance = 250;
  controles.maxDistance = 2600;
  controles.enabled = false;

  escena.add(new THREE.HemisphereLight(0xcfd4ff, 0x15151f, 1.1));
  const sol = new THREE.DirectionalLight(0xffffff, 1.6);
  sol.position.set(0.5, -0.7, 1);
  camara.add(sol);
  escena.add(camara);

  // piso: una cuadrícula que se desliza cuando camina
  const piso = new THREE.Group();
  const lineas = [];
  for (let i = -1500; i <= 1500; i += 50) lineas.push(i, -1500, 0, i, 1500, 0, -1500, i, 0, 1500, i, 0);
  const gPiso = new THREE.BufferGeometry();
  gPiso.setAttribute('position', new THREE.Float32BufferAttribute(lineas, 3));
  piso.add(new THREE.LineSegments(gPiso, new THREE.LineBasicMaterial({ color: 0x26263a })));
  escena.add(piso);
  const sombra = new THREE.Mesh(new THREE.CircleGeometry(1, 48), new THREE.MeshBasicMaterial({ color: 0x000000, transparent: true, opacity: 0.35 }));
  sombra.scale.set(190, 110, 1);
  sombra.position.z = 0.5;
  escena.add(sombra);

  // el robot
  const matCuerpo = new THREE.MeshStandardMaterial({ color: 0x4b4b6b, roughness: 0.5, metalness: 0.2 });
  const matPata = new THREE.MeshStandardMaterial({ color: 0x8b7cff, roughness: 0.45, metalness: 0.15 });
  const matEje = new THREE.MeshStandardMaterial({ color: 0xededf4, roughness: 0.35, metalness: 0.5 });
  const matPie = new THREE.MeshStandardMaterial({ color: 0x15151f, roughness: 0.9 });
  const robot = new THREE.Group();
  escena.add(robot);
  const torso = new THREE.Mesh(new THREE.BoxGeometry(CUERPO.largo, CUERPO.ancho, CUERPO.alto), matCuerpo);
  robot.add(torso);
  const lomo = new THREE.Mesh(new THREE.BoxGeometry(CUERPO.largo * 0.7, CUERPO.ancho * 0.6, 10), new THREE.MeshStandardMaterial({ color: 0x33334b, roughness: 0.6 }));
  lomo.position.z = CUERPO.alto / 2 + 5;
  robot.add(lomo);
  // la cara: un celular al frente, con dos ojos
  const cara = new THREE.Group();
  cara.position.set(CUERPO.largo / 2 + 9, 0, 34);
  cara.rotation.y = -12 * RAD;
  cara.add(new THREE.Mesh(new THREE.BoxGeometry(9, 76, 140), new THREE.MeshStandardMaterial({ color: 0x08080d, roughness: 0.25, metalness: 0.4 })));
  const matOjo = new THREE.MeshBasicMaterial({ color: 0x5fd3c4 });
  const ojos = [-17, 17].map((y) => {
    const o = new THREE.Mesh(new THREE.CircleGeometry(9, 28), matOjo);
    o.rotation.y = Math.PI / 2;
    o.position.set(4.8, y, 22);
    cara.add(o);
    return o;
  });
  robot.add(cara);

  const patas = [];
  let l1 = 122.5, l2 = 132, rodillasAtras = true, rodillaEn90 = 90;
  function armarPatas() {
    patas.forEach((p) => robot.remove(p.hombro));
    patas.length = 0;
    for (const def of PATAS) {
      const hombro = new THREE.Group();
      hombro.position.set(def.x * CUERPO.ejes / 2, def.y * (CUERPO.ancho / 2 + 16), -6);
      const eje = new THREE.Mesh(new THREE.CylinderGeometry(15, 15, 30, 24), matEje);
      hombro.add(eje);                                   // el cilindro ya queda a lo largo de Y
      const muslo = new THREE.Group();
      hombro.add(muslo);
      const mMuslo = new THREE.Mesh(new THREE.BoxGeometry(26, 20, l1), matPata);
      mMuslo.position.z = -l1 / 2;
      muslo.add(mMuslo);
      const rodilla = new THREE.Group();
      rodilla.position.z = -l1;
      muslo.add(rodilla);
      const ejeR = new THREE.Mesh(new THREE.CylinderGeometry(12, 12, 26, 20), matEje);
      rodilla.add(ejeR);
      const mPierna = new THREE.Mesh(new THREE.BoxGeometry(18, 16, l2), matPata);
      mPierna.position.z = -l2 / 2;
      rodilla.add(mPierna);
      const pie = new THREE.Mesh(new THREE.SphereGeometry(13, 20, 16), matPie);
      pie.position.z = -l2;
      rodilla.add(pie);
      robot.add(hombro);
      patas.push({ def, hombro, muslo, rodilla });
    }
  }
  armarPatas();

  const st = { visible: false, datos: null, pose: new Array(12).fill(90), desde: new Array(12).fill(90), hacia: new Array(12).fill(90),
               sec: null, nombre: null, cuadro: 0, t: 0, vueltas: 0, velocidad: 1, vivo: false, poseViva: null, relojTabla: 0 };

  // Los 12 ángulos -> la figura. Misma convención que acciones_robot.py:
  //   hombro: 90 vertical, más = pata hacia afuera · muslo: 90 vertical, más = adelante
  //   rodilla: doblez = 90 + RODILLA_EN_90 - ángulo (menos grados = más doblada)
  function aplicar(pose) {
    const fondo = [];
    patas.forEach((p, i) => {
      const abre = (pose[i * 3] - 90) * RAD;
      const theta = (pose[i * 3 + 1] - 90) * RAD;
      const doblez = (90 + rodillaEn90 - pose[i * 3 + 2]) * RAD * (rodillasAtras ? 1 : -1);
      p.hombro.rotation.x = p.def.y * abre;
      p.muslo.rotation.y = -theta;
      p.rodilla.rotation.y = -doblez;
      fondo.push((l1 * Math.cos(theta) + l2 * Math.cos(theta + doblez)) * Math.cos(abre) + 13);
    });
    // el cuerpo se apoya en las patas que más bajan en cada extremo
    const adelante = Math.max(fondo[0], fondo[1]), atras = Math.max(fondo[2], fondo[3]);
    robot.position.z = (adelante + atras) / 2 + 6;
    robot.rotation.y = Math.atan2(atras - adelante, CUERPO.ejes);
  }

  function reproducir(nombre) {
    const sec = st.datos && st.datos.secuencias[nombre];
    if (!sec) return;
    st.sec = sec; st.nombre = nombre; st.cuadro = 0; st.t = 0; st.vueltas = 0;
    st.desde = st.pose.slice();
    st.hacia = sec.frames[0].slice(0, 12).map((v, i) => (v == null ? st.pose[i] : v));
    pintar();
  }
  function parar() { st.sec = null; st.nombre = null; pintar(); }

  function pintar() {
    if (!st.visible) return;
    const p = ctx.panel;
    p.innerHTML = '';
    const t1 = document.createElement('div');
    t1.className = 'tarjeta';
    t1.innerHTML = '<h2>Movimientos</h2>';
    if (!st.datos) {
      t1.insertAdjacentHTML('beforeend', '<p class="tenue">Cargando…</p>');
    } else if (!st.datos.hay) {
      t1.insertAdjacentHTML('beforeend', '<p class="tenue">No encontré el módulo del perro (Perro_robotico/acciones_robot.py), así que solo se ve la pose de armado.</p>');
    } else {
      const nota = document.createElement('p'); nota.className = 'tenue';
      nota.textContent = st.vivo ? 'EN VIVO: sigue lo que Arché le está mandando al robot.' : 'Toca uno para verlo aquí. No mueve el robot real.';
      const lista = document.createElement('div'); lista.className = 'lista-acc';
      for (const nombre of Object.keys(st.datos.secuencias)) {
        const b = document.createElement('button');
        b.className = 'btn' + (st.nombre === nombre ? ' activo' : '');
        b.textContent = nombre.replace(/_/g, ' ');
        b.addEventListener('click', () => reproducir(nombre));
        lista.append(b);
      }
      t1.append(nota, lista);
      const fila = document.createElement('div'); fila.className = 'acciones';
      const alto = document.createElement('button'); alto.className = 'btn'; alto.textContent = 'Parar'; alto.disabled = !st.sec;
      alto.addEventListener('click', parar);
      fila.append(alto);
      t1.append(fila);
      const vel = document.createElement('div'); vel.className = 'medida';
      vel.innerHTML = `<label for="velPerro">Velocidad</label><output>${st.velocidad.toFixed(2)}×</output>`;
      const rango = document.createElement('input');
      Object.assign(rango, { type: 'range', id: 'velPerro', min: '0.1', max: '2', step: '0.05', value: String(st.velocidad) });
      rango.addEventListener('input', () => { st.velocidad = Number(rango.value); vel.querySelector('output').textContent = st.velocidad.toFixed(2) + '×'; });
      vel.append(rango);
      t1.append(vel);
    }
    p.append(t1);

    const t2 = document.createElement('div');
    t2.className = 'tarjeta';
    t2.innerHTML = '<h2>Ángulos de los servos</h2><ul class="relacion" id="tablaPerro"></ul>';
    p.append(t2);

    const t3 = document.createElement('div');
    t3.className = 'tarjeta';
    t3.innerHTML = '<h2>Medidas</h2>';
    const m = document.createElement('p'); m.className = 'tenue';
    m.textContent = `Patas con tus medidas: muslo ${l1} mm, pierna ${l2} mm, rodillas hacia ${rodillasAtras ? 'atrás' : 'adelante'}. `
      + 'El cuerpo y la cara son aproximados.';
    t3.append(m);
    p.append(t3);
    tabla();
  }

  function tabla() {
    const ul = document.getElementById('tablaPerro');
    if (!ul) return;
    ul.innerHTML = '';
    PATAS.forEach((def, i) => {
      const li = document.createElement('li');
      const a = st.pose.slice(i * 3, i * 3 + 3).map((v) => String(Math.round(v)).padStart(3, ' '));
      li.textContent = `${def.nombre.padEnd(15, ' ')} H ${a[0]}°  M ${a[1]}°  R ${a[2]}°`;
      li.style.whiteSpace = 'pre';
      ul.append(li);
    });
  }

  aplicar(st.pose);
  return {
    escena, camara, controles,
    entrar() {
      st.visible = true;
      controles.enabled = true;
      pintar();
      if (!st.datos) {
        apiJson('/api/perro').then((d) => {
          st.datos = d;
          if (d.hay) {
            l1 = d.muslo; l2 = d.pierna; rodillasAtras = d.rodillas !== 'adelante'; rodillaEn90 = d.rodilla_en_90;
            armarPatas();
            if (d.secuencias.pararse) reproducir('pararse');
          }
          pintar();
        }).catch(() => {});
      }
    },
    salir() { st.visible = false; controles.enabled = false; },
    alEstado(e) {
      const viva = e.pose_perro;
      const eraVivo = st.vivo;
      st.vivo = !!viva;
      if (viva) st.poseViva = viva.map((v, i) => (v == null ? st.pose[i] : v));
      if (eraVivo !== st.vivo) pintar();
    },
    actualizar(dt, t) {
      let avance = 0;
      if (st.sec) {
        const cuadro = st.sec.frames[st.cuadro];
        const dura = Math.max(0.04, cuadro[12] || 0.2);
        st.t += dt * st.velocidad / dura;
        const k = Math.min(1, st.t);
        const s = k * k * (3 - 2 * k);
        for (let i = 0; i < 12; i++) st.pose[i] = st.desde[i] + (st.hacia[i] - st.desde[i]) * s;
        if (st.nombre === 'avanzar' || st.nombre === 'correr') avance = 1;
        else if (st.nombre === 'retroceder') avance = -1;
        if (st.t >= 1) {
          st.t = 0;
          st.cuadro++;
          if (st.cuadro >= st.sec.frames.length) {
            st.cuadro = 0;
            st.vueltas++;
            if (st.sec.repetir != null && st.vueltas >= st.sec.repetir) { st.sec = null; st.nombre = null; pintar(); }
          }
          if (st.sec) {
            st.desde = st.pose.slice();
            st.hacia = st.sec.frames[st.cuadro].slice(0, 12).map((v, i) => (v == null ? st.pose[i] : v));
          }
        }
      } else if (st.vivo && st.poseViva) {
        const k = 1 - Math.exp(-dt * 12);
        for (let i = 0; i < 12; i++) st.pose[i] += (st.poseViva[i] - st.pose[i]) * k;
      }
      aplicar(st.pose);
      if (avance && !ctx.quieto) {
        piso.position.x -= avance * dt * 160 * st.velocidad * (st.nombre === 'correr' ? 1.6 : 1);
        piso.position.x = ((piso.position.x % 50) + 50) % 50;
      }
      ojos.forEach((o) => { o.scale.y = (t % 4.2) > 4.05 ? 0.12 : 1; });          // parpadea
      st.relojTabla += dt;
      if (st.visible && st.relojTabla > 0.15) { st.relojTabla = 0; tabla(); }
    },
  };
}
