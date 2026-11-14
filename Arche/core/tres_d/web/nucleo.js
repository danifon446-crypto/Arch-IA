// Núcleo: Arché en vivo. La esfera cambia de color, de ritmo y de forma según lo que esté haciendo.
import * as THREE from 'three';
import { OrbitControls } from './lib/OrbitControls.js';

const RUIDO = /* glsl */`
vec3 mod289(vec3 x){return x-floor(x*(1.0/289.0))*289.0;}
vec4 mod289(vec4 x){return x-floor(x*(1.0/289.0))*289.0;}
vec4 permute(vec4 x){return mod289(((x*34.0)+1.0)*x);}
vec4 taylorInvSqrt(vec4 r){return 1.79284291400159-0.85373472095314*r;}
float snoise(vec3 v){
  const vec2 C=vec2(1.0/6.0,1.0/3.0);const vec4 D=vec4(0.0,0.5,1.0,2.0);
  vec3 i=floor(v+dot(v,C.yyy));vec3 x0=v-i+dot(i,C.xxx);
  vec3 g=step(x0.yzx,x0.xyz);vec3 l=1.0-g;vec3 i1=min(g.xyz,l.zxy);vec3 i2=max(g.xyz,l.zxy);
  vec3 x1=x0-i1+C.xxx;vec3 x2=x0-i2+C.yyy;vec3 x3=x0-D.yyy;
  i=mod289(i);
  vec4 p=permute(permute(permute(i.z+vec4(0.0,i1.z,i2.z,1.0))+i.y+vec4(0.0,i1.y,i2.y,1.0))+i.x+vec4(0.0,i1.x,i2.x,1.0));
  float n_=0.142857142857;vec3 ns=n_*D.wyz-D.xzx;
  vec4 j=p-49.0*floor(p*ns.z*ns.z);vec4 x_=floor(j*ns.z);vec4 y_=floor(j-7.0*x_);
  vec4 x=x_*ns.x+ns.yyyy;vec4 y=y_*ns.x+ns.yyyy;vec4 h=1.0-abs(x)-abs(y);
  vec4 b0=vec4(x.xy,y.xy);vec4 b1=vec4(x.zw,y.zw);
  vec4 s0=floor(b0)*2.0+1.0;vec4 s1=floor(b1)*2.0+1.0;vec4 sh=-step(h,vec4(0.0));
  vec4 a0=b0.xzyw+s0.xzyw*sh.xxyy;vec4 a1=b1.xzyw+s1.xzyw*sh.zzww;
  vec3 p0=vec3(a0.xy,h.x);vec3 p1=vec3(a0.zw,h.y);vec3 p2=vec3(a1.xy,h.z);vec3 p3=vec3(a1.zw,h.w);
  vec4 norm=taylorInvSqrt(vec4(dot(p0,p0),dot(p1,p1),dot(p2,p2),dot(p3,p3)));
  p0*=norm.x;p1*=norm.y;p2*=norm.z;p3*=norm.w;
  vec4 m=max(0.6-vec4(dot(x0,x0),dot(x1,x1),dot(x2,x2),dot(x3,x3)),0.0);m=m*m;
  return 42.0*dot(m*m,vec4(dot(p0,x0),dot(p1,x1),dot(p2,x2),dot(p3,x3)));
}`;

// cómo se ve cada estado: colores, cuánto se deforma, qué tan rápido, y cuánto late
const ESTADOS = {
  reposo:     { a: 0x8b7cff, b: 0x3b2fb8, amp: 0.10, vel: 0.22, grano: 1.3, latido: 0.00, anillos: 0.25,
                titulo: 'En reposo', texto: 'Tranquila, esperando que le hables.' },
  escuchando: { a: 0x6aa8ff, b: 0x1f4fd0, amp: 0.15, vel: 0.50, grano: 1.9, latido: 0.06, anillos: 0.6,
                titulo: 'Escuchando', texto: 'El micrófono está abierto y te está oyendo.' },
  pensando:   { a: 0xffc65c, b: 0xd9541e, amp: 0.24, vel: 1.25, grano: 2.6, latido: 0.02, anillos: 2.2,
                titulo: 'Pensando', texto: 'Está resolviendo lo que le pediste.' },
  hablando:   { a: 0x4fd08b, b: 0x0e8f7a, amp: 0.20, vel: 0.85, grano: 1.7, latido: 0.11, anillos: 1.0,
                titulo: 'Hablando', texto: 'Te está respondiendo en voz alta.' },
};

export function crearNucleo(ctx) {
  const { render } = ctx;
  const escena = new THREE.Scene();
  const camara = new THREE.PerspectiveCamera(36, 1, 0.1, 200);
  camara.position.set(0, 1.2, 10.5);
  const controles = new OrbitControls(camara, render.domElement);
  controles.enableDamping = true;
  controles.enablePan = false;
  controles.minDistance = 4;
  controles.maxDistance = 18;
  controles.autoRotate = !ctx.quieto;
  controles.autoRotateSpeed = 0.5;
  controles.enabled = false;

  const u = { uT: { value: 0 }, uAmp: { value: 0.1 }, uGrano: { value: 1.3 },
              uA: { value: new THREE.Color(0x8b7cff) }, uB: { value: new THREE.Color(0x3b2fb8) } };
  const esfera = new THREE.Mesh(new THREE.IcosahedronGeometry(1.25, 48), new THREE.ShaderMaterial({
    uniforms: u,
    vertexShader: RUIDO + /* glsl */`
      uniform float uT; uniform float uAmp; uniform float uGrano;
      varying float vR; varying vec3 vN; varying vec3 vV;
      void main(){
        float r = snoise(normal*uGrano + vec3(uT*0.9, uT*0.7, -uT*0.8));
        r += 0.5*snoise(normal*uGrano*2.3 - vec3(uT*1.4));
        vR = r;
        vec3 p = position + normal*r*uAmp;
        vec4 mv = modelViewMatrix*vec4(p,1.0);
        vN = normalize(normalMatrix*normal); vV = normalize(-mv.xyz);
        gl_Position = projectionMatrix*mv;
      }`,
    fragmentShader: /* glsl */`
      uniform vec3 uA; uniform vec3 uB;
      varying float vR; varying vec3 vN; varying vec3 vV;
      void main(){
        float borde = pow(1.0-max(dot(vN,vV),0.0), 2.2);
        vec3 c = mix(uB, uA, smoothstep(-0.7,0.9,vR));
        c = c*(0.35+0.65*smoothstep(-0.9,0.8,vR)) + uA*borde*1.25 + vec3(1.0)*pow(borde,5.0)*0.5;
        gl_FragColor = vec4(c,1.0);
      }`,
  }));
  escena.add(esfera);

  // halo
  const halo = new THREE.Mesh(new THREE.SphereGeometry(1.25, 48, 48), new THREE.ShaderMaterial({
    uniforms: { uA: u.uA }, transparent: true, depthWrite: false, side: THREE.BackSide, blending: THREE.AdditiveBlending,
    vertexShader: `varying vec3 vN; varying vec3 vV; void main(){vec4 mv=modelViewMatrix*vec4(position,1.0);vN=normalize(normalMatrix*normal);vV=normalize(-mv.xyz);gl_Position=projectionMatrix*mv;}`,
    fragmentShader: `uniform vec3 uA; varying vec3 vN; varying vec3 vV; void main(){float f=pow(max(dot(-vN,vV),0.0),3.0);gl_FragColor=vec4(uA*f*0.9,f);}`,
  }));
  halo.scale.setScalar(1.75);
  escena.add(halo);

  // anillos
  const anillos = new THREE.Group();
  const matAnillo = new THREE.MeshBasicMaterial({ color: 0x8b7cff, transparent: true, opacity: 0.5, blending: THREE.AdditiveBlending, depthWrite: false });
  [[2.05, 0.3, 0.1], [2.35, -0.9, 0.5], [2.7, 1.25, -0.4]].forEach(([radio, rx, ry]) => {
    const a = new THREE.Mesh(new THREE.TorusGeometry(radio, 0.006, 6, 220), matAnillo);
    a.rotation.set(Math.PI / 2 + rx, ry, 0);
    anillos.add(a);
  });
  escena.add(anillos);

  // polvo de luz
  const N = 2600;
  const pos = new Float32Array(N * 3);
  for (let i = 0; i < N; i++) {
    const r = 1.9 + Math.pow(Math.random(), 1.6) * 3.2;
    const t = Math.acos(2 * Math.random() - 1), f = Math.random() * Math.PI * 2;
    pos[i * 3] = r * Math.sin(t) * Math.cos(f);
    pos[i * 3 + 1] = r * Math.cos(t) * 0.55;
    pos[i * 3 + 2] = r * Math.sin(t) * Math.sin(f);
  }
  const gPolvo = new THREE.BufferGeometry();
  gPolvo.setAttribute('position', new THREE.BufferAttribute(pos, 3));
  const matPolvo = new THREE.PointsMaterial({ color: 0x8b7cff, size: 0.022, transparent: true, opacity: 0.75, blending: THREE.AdditiveBlending, depthWrite: false });
  const polvo = new THREE.Points(gPolvo, matPolvo);
  escena.add(polvo);

  // satélites: una bolita por cada tarea de fondo
  const satelites = [];
  const gSat = new THREE.SphereGeometry(0.075, 16, 16);
  for (let i = 0; i < 6; i++) {
    const m = new THREE.Mesh(gSat, new THREE.MeshBasicMaterial({ color: 0xffc65c }));
    m.visible = false;
    escena.add(m);
    satelites.push({ malla: m, etq: ctx.etiqueta('tarea') });
  }

  const st = { visible: false, estado: 'reposo', prueba: null, hastaPrueba: 0, tareas: [], dentro: false, fase: 0 };
  const objetivo = { ...ESTADOS.reposo };
  const actual = { amp: 0.1, vel: 0.22, grano: 1.3, latido: 0, anillos: 0.25 };
  const cA = new THREE.Color(), cB = new THREE.Color();

  function pintar() {
    if (!st.visible) return;
    const p = ctx.panel;
    p.innerHTML = '';
    const e = ESTADOS[st.prueba || st.estado] || ESTADOS.reposo;
    const t1 = document.createElement('div');
    t1.className = 'tarjeta';
    t1.innerHTML = '<h2>Arché ahora</h2>';
    const h = document.createElement('h3'); h.textContent = e.titulo + (st.prueba ? ' (prueba)' : '');
    const d = document.createElement('p'); d.className = 'tenue'; d.textContent = e.texto;
    t1.append(h, d);
    if (!st.dentro) {
      const n = document.createElement('p'); n.className = 'tenue';
      n.textContent = 'El taller se abrió sin Arché corriendo, así que no hay estado en vivo. Ábrelo desde Arché con «abre el núcleo 3d».';
      t1.append(n);
    }
    p.append(t1);

    const t2 = document.createElement('div');
    t2.className = 'tarjeta';
    t2.innerHTML = '<h2>Trabajando de fondo</h2>';
    if (!st.tareas.length) {
      const n = document.createElement('p'); n.className = 'tenue';
      n.textContent = 'Nada por ahora. Cada tarea de fondo aparece como un satélite alrededor del núcleo.';
      t2.append(n);
    } else {
      const ul = document.createElement('ul'); ul.className = 'relacion';
      for (const t of st.tareas) { const li = document.createElement('li'); li.textContent = `tarea ${t.id}: ${t.orden} — ${t.estado}`; ul.append(li); }
      t2.append(ul);
    }
    p.append(t2);

    const t3 = document.createElement('div');
    t3.className = 'tarjeta';
    t3.innerHTML = '<h2>Ver cómo se pone</h2>';
    const fila = document.createElement('div'); fila.className = 'acciones';
    for (const [clave, datos] of Object.entries(ESTADOS)) {
      const b = document.createElement('button');
      b.className = 'btn' + ((st.prueba || st.estado) === clave ? ' activo' : '');
      b.textContent = datos.titulo;
      b.addEventListener('click', () => { st.prueba = clave; st.hastaPrueba = performance.now() + 6000; pintar(); });
      fila.append(b);
    }
    t3.append(fila);
    p.append(t3);
  }

  const pS = new THREE.Vector3();
  return {
    escena, camara, controles,
    entrar() { st.visible = true; controles.enabled = true; pintar(); },
    salir() { st.visible = false; controles.enabled = false; },
    alEstado(e) {
      const visual = ESTADOS[e.arche.visual] ? e.arche.visual : 'reposo';
      const firma = visual + '|' + e.arche.dentro_de_arche + '|' + JSON.stringify(e.arche.tareas);
      if (firma !== st.firma) {
        st.firma = firma;
        st.estado = visual;
        st.dentro = e.arche.dentro_de_arche;
        st.tareas = e.arche.tareas || [];
        pintar();
      }
    },
    actualizar(dt, t) {
      if (st.prueba && performance.now() > st.hastaPrueba) { st.prueba = null; pintar(); }
      const e = ESTADOS[st.prueba || st.estado] || ESTADOS.reposo;
      const k = 1 - Math.exp(-dt * 3.2);                 // transición suave entre estados
      for (const c of ['amp', 'vel', 'grano', 'latido', 'anillos']) actual[c] += (e[c] - actual[c]) * k;
      u.uA.value.lerp(cA.setHex(e.a), k);
      u.uB.value.lerp(cB.setHex(e.b), k);
      matAnillo.color.copy(u.uA.value);
      matPolvo.color.copy(u.uA.value);
      const paso = ctx.quieto ? 0 : dt;
      st.fase += paso * actual.vel;
      u.uT.value = st.fase;
      // al hablar la deformación sube y baja como una voz
      const voz = (st.prueba || st.estado) === 'hablando' ? 0.55 + 0.45 * Math.abs(Math.sin(t * 9.0) * Math.sin(t * 2.3)) : 1;
      u.uAmp.value = actual.amp * voz;
      u.uGrano.value = actual.grano;
      const latido = 1 + actual.latido * Math.sin(t * 4.2);
      esfera.scale.setScalar(latido);
      halo.scale.setScalar(1.75 * latido);
      anillos.children.forEach((a, i) => { a.rotation.z += paso * actual.anillos * (i % 2 ? -0.7 : 1) * (0.6 + i * 0.25); });
      polvo.rotation.y += paso * (0.03 + actual.vel * 0.05);

      satelites.forEach((s, i) => {
        const tarea = st.tareas[i];
        s.malla.visible = !!tarea;
        if (!tarea) { s.etq.style.display = 'none'; return; }
        const ang = t * 0.45 + i * (Math.PI * 2 / Math.max(1, st.tareas.length));
        s.malla.position.set(Math.cos(ang) * 2.35, Math.sin(ang * 1.3 + i) * 0.5, Math.sin(ang) * 2.35);
        s.etq.textContent = `tarea ${tarea.id} · ${tarea.orden}`;
        ctx.colocar(s.etq, pS.copy(s.malla.position).setY(s.malla.position.y + 0.25), camara);
      });
    },
  };
}
