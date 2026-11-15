// Mallas editables para el modo Modelar (como Blender): sin three.js, solo números, para poder probarlo solo.
//
// Una malla es { v: Float32Array (x,y,z,...), f: Uint32Array (a,b,c,...), g: Int32Array (grupo de cada
// triángulo) }: triángulos que comparten vértices y miran hacia afuera (antihorario visto desde fuera).
// El grupo dice qué «cara» es cada triángulo (como las caras de Blender): al insertar o extruir, lo
// nuevo es otra cara aunque quede en el mismo plano. Todas las operaciones de aquí
// la dejan CERRADA (cada arista la comparten exactamente dos triángulos), que es lo que una impresora necesita.

// ---------------------------------------------------------------- utilidades
export function soldar(puntos, caras, tol = 1e-4) {
  // une vértices repetidos (misma posición) -> malla que comparte vértices
  const mapa = new Map(), v = [], remap = new Uint32Array(puntos.length / 3);
  for (let i = 0; i < puntos.length / 3; i++) {
    const k = `${Math.round(puntos[i * 3] / tol)},${Math.round(puntos[i * 3 + 1] / tol)},${Math.round(puntos[i * 3 + 2] / tol)}`;
    let j = mapa.get(k);
    if (j === undefined) { j = v.length / 3; mapa.set(k, j); v.push(puntos[i * 3], puntos[i * 3 + 1], puntos[i * 3 + 2]); }
    remap[i] = j;
  }
  const f = [], g = [];
  for (let t = 0; t < caras.length; t += 3) {
    const a = remap[caras[t]], b = remap[caras[t + 1]], c = remap[caras[t + 2]];
    if (a !== b && b !== c && a !== c) { f.push(a, b, c); g.push(0); }
  }
  return { v: Float32Array.from(v), f: Uint32Array.from(f), g: Int32Array.from(g) };
}

const grupos = (m) => m.g && m.g.length === m.f.length / 3 ? m.g : new Int32Array(m.f.length / 3);
export const conGrupos = (m) => (m.g && m.g.length === m.f.length / 3 ? m : { ...m, g: new Int32Array(m.f.length / 3) });
export const maxGrupo = (m) => grupos(m).reduce((a, b) => Math.max(a, b), 0);

export const copiar = (m) => ({ v: Float32Array.from(m.v), f: Uint32Array.from(m.f), g: Int32Array.from(grupos(m)) });
export const nVert = (m) => m.v.length / 3;
export const nTri = (m) => m.f.length / 3;

export function cerrada(m) {
  // cada arista dirigida a->b aparece una vez y su opuesta b->a también una vez
  const aristas = new Map();
  for (let t = 0; t < m.f.length; t += 3) {
    for (let k = 0; k < 3; k++) {
      const a = m.f[t + k], b = m.f[t + (k + 1) % 3];
      const clave = a + ',' + b;
      if (aristas.has(clave)) return false;
      aristas.set(clave, true);
    }
  }
  for (const clave of aristas.keys()) {
    const [a, b] = clave.split(',');
    if (!aristas.has(b + ',' + a)) return false;
  }
  return true;
}

export function volumen(m) {
  let s = 0;
  const v = m.v;
  for (let t = 0; t < m.f.length; t += 3) {
    const a = m.f[t] * 3, b = m.f[t + 1] * 3, c = m.f[t + 2] * 3;
    s += v[a] * (v[b + 1] * v[c + 2] - v[b + 2] * v[c + 1]) - v[a + 1] * (v[b] * v[c + 2] - v[b + 2] * v[c]) + v[a + 2] * (v[b] * v[c + 1] - v[b + 1] * v[c]);
  }
  return s / 6;
}

export function limites(m) {
  const mn = [Infinity, Infinity, Infinity], mx = [-Infinity, -Infinity, -Infinity];
  for (let i = 0; i < m.v.length; i += 3) for (let k = 0; k < 3; k++) { mn[k] = Math.min(mn[k], m.v[i + k]); mx[k] = Math.max(mx[k], m.v[i + k]); }
  return { min: mn, max: mx };
}

export function normalTri(m, t) {
  const v = m.v, a = m.f[t * 3] * 3, b = m.f[t * 3 + 1] * 3, c = m.f[t * 3 + 2] * 3;
  const ux = v[b] - v[a], uy = v[b + 1] - v[a + 1], uz = v[b + 2] - v[a + 2];
  const wx = v[c] - v[a], wy = v[c + 1] - v[a + 1], wz = v[c + 2] - v[a + 2];
  const nx = uy * wz - uz * wy, ny = uz * wx - ux * wz, nz = ux * wy - uy * wx;
  const l = Math.hypot(nx, ny, nz) || 1;
  return [nx / l, ny / l, nz / l, l / 2];
}

export function normalesVertices(m, salida) {
  const n = salida || new Float32Array(m.v.length);
  n.fill(0);
  const v = m.v;
  for (let t = 0; t < m.f.length; t += 3) {
    const a = m.f[t] * 3, b = m.f[t + 1] * 3, c = m.f[t + 2] * 3;
    const ux = v[b] - v[a], uy = v[b + 1] - v[a + 1], uz = v[b + 2] - v[a + 2];
    const wx = v[c] - v[a], wy = v[c + 1] - v[a + 1], wz = v[c + 2] - v[a + 2];
    const nx = uy * wz - uz * wy, ny = uz * wx - ux * wz, nz = ux * wy - uy * wx;   // ponderada por área
    for (const i of [a, b, c]) { n[i] += nx; n[i + 1] += ny; n[i + 2] += nz; }
  }
  for (let i = 0; i < n.length; i += 3) {
    const l = Math.hypot(n[i], n[i + 1], n[i + 2]) || 1;
    n[i] /= l; n[i + 1] /= l; n[i + 2] /= l;
  }
  return n;
}

export function vecinos(m) {
  // para cada vértice, los vértices unidos a él por una arista
  const vec = Array.from({ length: nVert(m) }, () => new Set());
  for (let t = 0; t < m.f.length; t += 3) {
    const a = m.f[t], b = m.f[t + 1], c = m.f[t + 2];
    vec[a].add(b); vec[a].add(c); vec[b].add(a); vec[b].add(c); vec[c].add(a); vec[c].add(b);
  }
  return vec.map((s) => Uint32Array.from(s));
}

// ---------------------------------------------------------------- primitivas (ya con detalle para esculpir)
export function cubo(lx = 20, ly = 20, lz = 20, div = 8) {
  const p = [], f = [];
  const cara = (origen, u, w) => {
    const base = p.length / 3;
    for (let j = 0; j <= div; j++) for (let i = 0; i <= div; i++) {
      p.push(origen[0] + u[0] * i / div + w[0] * j / div, origen[1] + u[1] * i / div + w[1] * j / div, origen[2] + u[2] * i / div + w[2] * j / div);
    }
    for (let j = 0; j < div; j++) for (let i = 0; i < div; i++) {
      const a = base + j * (div + 1) + i, b = a + 1, c = a + div + 1, d = c + 1;
      f.push(a, b, d, a, d, c);
    }
  };
  const x = lx / 2, y = ly / 2;
  cara([-x, -y, 0], [lx, 0, 0], [0, 0, lz]);        // frente (-Y)
  cara([x, y, 0], [-lx, 0, 0], [0, 0, lz]);         // atrás (+Y)
  cara([x, -y, 0], [0, ly, 0], [0, 0, lz]);         // derecha (+X)
  cara([-x, y, 0], [0, -ly, 0], [0, 0, lz]);        // izquierda (-X)
  cara([-x, -y, lz], [lx, 0, 0], [0, ly, 0]);       // arriba
  cara([-x, y, 0], [lx, 0, 0], [0, -ly, 0]);        // abajo
  return soldar(p, f);
}

export function esfera(d = 20, niveles = 4) {
  const t = (1 + Math.sqrt(5)) / 2;
  let v = [-1, t, 0, 1, t, 0, -1, -t, 0, 1, -t, 0, 0, -1, t, 0, 1, t, 0, -1, -t, 0, 1, -t, t, 0, -1, t, 0, 1, -t, 0, -1, -t, 0, 1];
  let f = [0, 11, 5, 0, 5, 1, 0, 1, 7, 0, 7, 10, 0, 10, 11, 1, 5, 9, 5, 11, 4, 11, 10, 2, 10, 7, 6, 7, 1, 8,
    3, 9, 4, 3, 4, 2, 3, 2, 6, 3, 6, 8, 3, 8, 9, 4, 9, 5, 2, 4, 11, 6, 2, 10, 8, 6, 7, 9, 8, 1];
  let m = conGrupos({ v: Float32Array.from(v), f: Uint32Array.from(f) });
  for (let i = 0; i < niveles; i++) m = subdividir(m);
  const r = d / 2;
  for (let i = 0; i < m.v.length; i += 3) {
    const l = Math.hypot(m.v[i], m.v[i + 1], m.v[i + 2]);
    m.v[i] = m.v[i] / l * r; m.v[i + 1] = m.v[i + 1] / l * r; m.v[i + 2] = m.v[i + 2] / l * r + r;
  }
  return m;
}

export function cilindro(d = 20, alto = 20, lados = 32, anillos = 8) {
  const p = [], f = [], r = d / 2;
  for (let j = 0; j <= anillos; j++) for (let i = 0; i < lados; i++) {
    const a = 2 * Math.PI * i / lados;
    p.push(r * Math.cos(a), r * Math.sin(a), alto * j / anillos);
  }
  for (let j = 0; j < anillos; j++) for (let i = 0; i < lados; i++) {
    const a = j * lados + i, b = j * lados + (i + 1) % lados, c = a + lados, e = b + lados;
    f.push(a, b, e, a, e, c);
  }
  // tapas en abanico desde el centro, con anillos para poder esculpirlas
  const tapa = (z, arriba) => {
    const anillo0 = arriba ? anillos * lados : 0;
    const pasos = 3;
    let previo = Array.from({ length: lados }, (_, i) => anillo0 + i);
    for (let k = 1; k < pasos; k++) {
      const actual = [];
      for (let i = 0; i < lados; i++) {
        const a = 2 * Math.PI * i / lados, rr = r * (1 - k / pasos);
        actual.push(p.length / 3);
        p.push(rr * Math.cos(a), rr * Math.sin(a), z);
      }
      for (let i = 0; i < lados; i++) {
        const a = previo[i], b = previo[(i + 1) % lados], c = actual[i], e = actual[(i + 1) % lados];
        if (arriba) f.push(a, b, e, a, e, c); else f.push(a, e, b, a, c, e);
      }
      previo = actual;
    }
    const centro = p.length / 3;
    p.push(0, 0, z);
    for (let i = 0; i < lados; i++) {
      const a = previo[i], b = previo[(i + 1) % lados];
      if (arriba) f.push(a, b, centro); else f.push(a, centro, b);
    }
  };
  tapa(0, false);
  tapa(alto, true);
  return conGrupos({ v: Float32Array.from(p), f: Uint32Array.from(f) });
}

export function cono(d = 20, alto = 20, lados = 32) {
  const m = cilindro(d, alto, lados, 8);
  for (let i = 0; i < m.v.length; i += 3) {
    const k = 1 - m.v[i + 2] / alto * 0.999;
    m.v[i] *= k; m.v[i + 1] *= k;
  }
  return m;
}

export function toro(d = 30, grosor = 8, lados = 40, segmentos = 20) {
  const p = [], f = [], R = (d - grosor) / 2, r = grosor / 2;
  for (let i = 0; i < lados; i++) for (let j = 0; j < segmentos; j++) {
    const u = 2 * Math.PI * i / lados, w = 2 * Math.PI * j / segmentos;
    p.push((R + r * Math.cos(w)) * Math.cos(u), (R + r * Math.cos(w)) * Math.sin(u), r + r * Math.sin(w));
  }
  for (let i = 0; i < lados; i++) for (let j = 0; j < segmentos; j++) {
    const a = i * segmentos + j, b = ((i + 1) % lados) * segmentos + j, c = i * segmentos + (j + 1) % segmentos, e = ((i + 1) % lados) * segmentos + (j + 1) % segmentos;
    f.push(a, b, e, a, e, c);
  }
  return conGrupos({ v: Float32Array.from(p), f: Uint32Array.from(f) });
}

// ---------------------------------------------------------------- operaciones de toda la malla
export function subdividir(m) {
  // cada triángulo -> 4, con un vértice nuevo en el medio de cada arista (compartido)
  const v = Array.from(m.v), f = [], g = [], g0 = grupos(m), medio = new Map();
  const punto = (a, b) => {
    const k = a < b ? a + ',' + b : b + ',' + a;
    let i = medio.get(k);
    if (i === undefined) {
      i = v.length / 3;
      v.push((v[a * 3] + v[b * 3]) / 2, (v[a * 3 + 1] + v[b * 3 + 1]) / 2, (v[a * 3 + 2] + v[b * 3 + 2]) / 2);
      medio.set(k, i);
    }
    return i;
  };
  for (let t = 0; t < m.f.length; t += 3) {
    const a = m.f[t], b = m.f[t + 1], c = m.f[t + 2];
    const ab = punto(a, b), bc = punto(b, c), ca = punto(c, a);
    f.push(a, ab, ca, ab, b, bc, ca, bc, c, ab, bc, ca);
    const gr = g0[t / 3];
    g.push(gr, gr, gr, gr);
  }
  return { v: Float32Array.from(v), f: Uint32Array.from(f), g: Int32Array.from(g) };
}

export function suavizar(m, vueltas = 2, fuerza = 0.5, soloVert = null, taubin = true) {
  // taubin = true: alisa sin encoger la pieza (un paso hacia los vecinos y otro un poco hacia afuera).
  // taubin = false: redondea de verdad (las esquinas se comen), como la subdivisión de Blender.
  const vec = vecinos(m);
  const r = copiar(m);
  const paso = (lambda) => {
    const viejo = Float32Array.from(r.v);
    for (let i = 0; i < vec.length; i++) {
      if (soloVert && !soloVert.has(i)) continue;
      const n = vec[i];
      if (!n.length) continue;
      let x = 0, y = 0, z = 0;
      for (const j of n) { x += viejo[j * 3]; y += viejo[j * 3 + 1]; z += viejo[j * 3 + 2]; }
      x /= n.length; y /= n.length; z /= n.length;
      r.v[i * 3] += (x - viejo[i * 3]) * lambda;
      r.v[i * 3 + 1] += (y - viejo[i * 3 + 1]) * lambda;
      r.v[i * 3 + 2] += (z - viejo[i * 3 + 2]) * lambda;
    }
  };
  for (let k = 0; k < vueltas; k++) { paso(fuerza); if (taubin) paso(-fuerza * 1.06); }
  return r;
}

export function transformar(m, fn) {
  const r = copiar(m);
  for (let i = 0; i < r.v.length; i += 3) {
    const p = fn(r.v[i], r.v[i + 1], r.v[i + 2]);
    r.v[i] = p[0]; r.v[i + 1] = p[1]; r.v[i + 2] = p[2];
  }
  return r;
}

export function espejar(m, eje) {
  // la copia reflejada (con las caras volteadas para que sigan mirando afuera)
  const r = transformar(m, (x, y, z) => [eje === 0 ? -x : x, eje === 1 ? -y : y, eje === 2 ? -z : z]);
  for (let t = 0; t < r.f.length; t += 3) { const b = r.f[t + 1]; r.f[t + 1] = r.f[t + 2]; r.f[t + 2] = b; }
  return r;
}

export function juntar(lista) {
  const v = [], f = [], g = [];
  let baseG = 0;
  for (const m of lista) {
    const base = v.length / 3;
    for (const x of m.v) v.push(x);
    for (const i of m.f) f.push(i + base);
    const gm = grupos(m);
    for (const x of gm) g.push(x + baseG);
    baseG += maxGrupo(m) + 1;
  }
  return { v: Float32Array.from(v), f: Uint32Array.from(f), g: Int32Array.from(g) };
}

// ---------------------------------------------------------------- modo edición
export function triangulosVecinos(m) {
  // para cada triángulo, sus 3 vecinos (el que comparte cada arista)
  const arista = new Map(), vec = new Int32Array(m.f.length).fill(-1);
  for (let t = 0; t < m.f.length / 3; t++) for (let k = 0; k < 3; k++) {
    const a = m.f[t * 3 + k], b = m.f[t * 3 + (k + 1) % 3];
    arista.set(a + ',' + b, t * 3 + k);
  }
  for (let t = 0; t < m.f.length / 3; t++) for (let k = 0; k < 3; k++) {
    const a = m.f[t * 3 + k], b = m.f[t * 3 + (k + 1) % 3];
    const o = arista.get(b + ',' + a);
    if (o !== undefined) vec[t * 3 + k] = Math.floor(o / 3);
  }
  return vec;
}

export function regionPlana(m, semilla, tolerancia = 0.995, vec = null) {
  // la «cara» que ves: todos los triángulos unidos y casi paralelos al que tocaste
  vec = vec || triangulosVecinos(m);
  const n0 = normalTri(m, semilla);
  const g = grupos(m), g0 = g[semilla];
  const region = new Set([semilla]), cola = [semilla];
  while (cola.length) {
    const t = cola.pop();
    for (let k = 0; k < 3; k++) {
      const o = vec[t * 3 + k];
      if (o < 0 || region.has(o) || g[o] !== g0) continue;
      const n = normalTri(m, o);
      if (n[0] * n0[0] + n[1] * n0[1] + n[2] * n0[2] >= tolerancia) { region.add(o); cola.push(o); }
    }
  }
  return region;
}

export function infoRegion(m, region) {
  // centro y normal promedio (ponderada por área) de un grupo de triángulos
  let cx = 0, cy = 0, cz = 0, nx = 0, ny = 0, nz = 0, area = 0;
  const verts = new Set();
  for (const t of region) {
    const [x, y, z, a] = normalTri(m, t);
    nx += x * a; ny += y * a; nz += z * a; area += a;
    for (let k = 0; k < 3; k++) verts.add(m.f[t * 3 + k]);
  }
  for (const i of verts) { cx += m.v[i * 3]; cy += m.v[i * 3 + 1]; cz += m.v[i * 3 + 2]; }
  const l = Math.hypot(nx, ny, nz) || 1;
  return { centro: [cx / verts.size, cy / verts.size, cz / verts.size], normal: [nx / l, ny / l, nz / l], verts, area };
}

export function anillo(m, region) {
  // Base de extruir / insertar / biselar: duplica los vértices de la región y los une con el
  // borde viejo por un anillo de caras. Devuelve la malla nueva y qué vértices son los nuevos
  // (para moverlos). La malla queda cerrada (al principio el anillo no tiene grosor).
  const v = Array.from(m.v), f = Array.from(m.f), g = Array.from(grupos(m));
  const nuevo = new Map();
  const gInterior = maxGrupo(m) + 1, gAnillo = gInterior + 1;      // la cara de adentro y el anillo son caras nuevas
  const dup = (i) => {
    let j = nuevo.get(i);
    if (j === undefined) { j = v.length / 3; v.push(v[i * 3], v[i * 3 + 1], v[i * 3 + 2]); nuevo.set(i, j); }
    return j;
  };
  // aristas del borde: las de la región cuya arista opuesta no está en la región
  const dentro = new Set();
  for (const t of region) for (let k = 0; k < 3; k++) dentro.add(m.f[t * 3 + k] + ',' + m.f[t * 3 + (k + 1) % 3]);
  const borde = [];
  for (const t of region) for (let k = 0; k < 3; k++) {
    const a = m.f[t * 3 + k], b = m.f[t * 3 + (k + 1) % 3];
    if (!dentro.has(b + ',' + a)) borde.push([a, b]);
  }
  for (const t of region) { for (let k = 0; k < 3; k++) f[t * 3 + k] = dup(m.f[t * 3 + k]); g[t] = gInterior; }
  for (const [a, b] of borde) {
    const a2 = dup(a), b2 = dup(b);
    f.push(a, b, b2, a, b2, a2);
    g.push(gAnillo, gAnillo);
  }
  return { malla: { v: Float32Array.from(v), f: Uint32Array.from(f), g: Int32Array.from(g) }, nuevos: [...nuevo.values()], originales: [...nuevo.keys()] };
}

export function moverVertices(m, indices, fn) {
  for (const i of indices) {
    const p = fn(m.v[i * 3], m.v[i * 3 + 1], m.v[i * 3 + 2], i);
    m.v[i * 3] = p[0]; m.v[i * 3 + 1] = p[1]; m.v[i * 3 + 2] = p[2];
  }
  return m;
}

// ---------------------------------------------------------------- escultura
export const PINCELES = {
  inflar: 'Inflar', hundir: 'Hundir', alisar: 'Alisar', agarrar: 'Agarrar', aplanar: 'Aplanar', pellizcar: 'Pellizcar',
};

export function caida(d, radio) {
  // 1 en el centro del pincel, 0 en el borde, suave
  const x = d / radio;
  return x >= 1 ? 0 : (1 - x * x) * (1 - x * x);
}

export function bajoPincel(m, centro, radio) {
  // vértices dentro del radio (con su peso)
  const lista = [];
  const r2 = radio * radio, v = m.v;
  for (let i = 0; i < v.length / 3; i++) {
    const dx = v[i * 3] - centro[0], dy = v[i * 3 + 1] - centro[1], dz = v[i * 3 + 2] - centro[2];
    const d2 = dx * dx + dy * dy + dz * dz;
    if (d2 < r2) lista.push([i, caida(Math.sqrt(d2), radio)]);
  }
  return lista;
}

export function pincelar(m, pincel, centro, radio, fuerza, extra = {}) {
  // Aplica un toque del pincel en `centro` (coordenadas de la malla). Cambia m.v en su sitio.
  // extra: { normales, vecinos, delta (para agarrar), lista (vértices ya elegidos al empezar a agarrar) }
  const v = m.v;
  const lista = extra.lista || bajoPincel(m, centro, radio);
  if (!lista.length) return lista;
  const n = extra.normales || normalesVertices(m);
  const paso = radio * 0.06 * fuerza;
  if (pincel === 'inflar' || pincel === 'hundir') {
    // empuja según la normal promedio de la zona (así no se arruga)
    let nx = 0, ny = 0, nz = 0;
    for (const [i, w] of lista) { nx += n[i * 3] * w; ny += n[i * 3 + 1] * w; nz += n[i * 3 + 2] * w; }
    const l = Math.hypot(nx, ny, nz) || 1;
    const s = pincel === 'inflar' ? 1 : -1;
    for (const [i, w] of lista) {
      const k = s * paso * w;
      v[i * 3] += (n[i * 3] * 0.5 + nx / l * 0.5) * k; v[i * 3 + 1] += (n[i * 3 + 1] * 0.5 + ny / l * 0.5) * k; v[i * 3 + 2] += (n[i * 3 + 2] * 0.5 + nz / l * 0.5) * k;
    }
  } else if (pincel === 'alisar') {
    const vec = extra.vecinos || vecinos(m);
    const viejo = new Map(lista.map(([i]) => [i, [v[i * 3], v[i * 3 + 1], v[i * 3 + 2]]]));
    const pos = (j) => viejo.get(j) || [v[j * 3], v[j * 3 + 1], v[j * 3 + 2]];
    for (const [i, w] of lista) {
      const nb = vec[i];
      if (!nb.length) continue;
      let x = 0, y = 0, z = 0;
      for (const j of nb) { const p = pos(j); x += p[0]; y += p[1]; z += p[2]; }
      const k = Math.min(1, w * fuerza * 0.8);
      const p0 = viejo.get(i);
      v[i * 3] = p0[0] + (x / nb.length - p0[0]) * k; v[i * 3 + 1] = p0[1] + (y / nb.length - p0[1]) * k; v[i * 3 + 2] = p0[2] + (z / nb.length - p0[2]) * k;
    }
  } else if (pincel === 'agarrar') {
    const d = extra.delta || [0, 0, 0];
    for (const [i, w] of lista) { v[i * 3] += d[0] * w; v[i * 3 + 1] += d[1] * w; v[i * 3 + 2] += d[2] * w; }
  } else if (pincel === 'aplanar') {
    let cx = 0, cy = 0, cz = 0, nx = 0, ny = 0, nz = 0, sw = 0;
    for (const [i, w] of lista) { cx += v[i * 3] * w; cy += v[i * 3 + 1] * w; cz += v[i * 3 + 2] * w; nx += n[i * 3] * w; ny += n[i * 3 + 1] * w; nz += n[i * 3 + 2] * w; sw += w; }
    cx /= sw; cy /= sw; cz /= sw;
    const l = Math.hypot(nx, ny, nz) || 1;
    nx /= l; ny /= l; nz /= l;
    for (const [i, w] of lista) {
      const d = (v[i * 3] - cx) * nx + (v[i * 3 + 1] - cy) * ny + (v[i * 3 + 2] - cz) * nz;
      const k = d * Math.min(1, w * fuerza * 0.5);
      v[i * 3] -= nx * k; v[i * 3 + 1] -= ny * k; v[i * 3 + 2] -= nz * k;
    }
  } else if (pincel === 'pellizcar') {
    for (const [i, w] of lista) {
      const k = w * fuerza * 0.08;
      v[i * 3] += (centro[0] - v[i * 3]) * k; v[i * 3 + 1] += (centro[1] - v[i * 3 + 1]) * k; v[i * 3 + 2] += (centro[2] - v[i * 3 + 2]) * k;
    }
  }
  return lista;
}

export function largoAristaMedio(m) {
  let s = 0, n = 0;
  const v = m.v;
  for (let t = 0; t < Math.min(m.f.length, 30000); t += 3) {
    const a = m.f[t] * 3, b = m.f[t + 1] * 3;
    s += Math.hypot(v[a] - v[b], v[a + 1] - v[b + 1], v[a + 2] - v[b + 2]);
    n++;
  }
  return n ? s / n : 1;
}

// ---------------------------------------------------------------- modificadores (no destruyen la malla)
export const MODIFICADORES = {
  espejo: { nombre: 'Espejo', valores: { eje: 0 } },
  matriz: { nombre: 'Matriz', valores: { cantidad: 3, separacion: 25, circular: 0, radio: 0 } },
  suavizar: { nombre: 'Suavizar', valores: { vueltas: 3 } },
  subdividir: { nombre: 'Subdividir', valores: { niveles: 1 } },
};
const MAX_TRIANGULOS = 400000;

export function aplicarModificadores(base, mods) {
  // devuelve una lista de mallas (las copias del espejo y la matriz son piezas aparte; al guardar se unen)
  let piezas = [base];
  for (const mod of mods || []) {
    if (mod.apagado) continue;
    const total = piezas.reduce((s, p) => s + nTri(p), 0);
    if (mod.tipo === 'espejo') {
      piezas = piezas.concat(piezas.map((p) => espejar(p, mod.eje | 0)));
    } else if (mod.tipo === 'matriz') {
      const n = Math.max(1, Math.min(24, mod.cantidad | 0));
      if (total * n > MAX_TRIANGULOS) continue;
      const nuevas = [];
      for (let k = 0; k < n; k++) {
        for (const p of piezas) {
          if (mod.circular) {
            // en círculo alrededor del origen del objeto, a `radio` de distancia (como los dientes de una rueda)
            const a = 2 * Math.PI * k / n, c = Math.cos(a), s = Math.sin(a), r = Number(mod.radio) || 0;
            nuevas.push(transformar(p, (x, y, z) => { const yy = y + r; return [x * c - yy * s, x * s + yy * c, z]; }));
          } else {
            nuevas.push(transformar(p, (x, y, z) => [x + k * mod.separacion, y, z]));
          }
        }
      }
      piezas = nuevas;
    } else if (mod.tipo === 'suavizar') {
      piezas = piezas.map((p) => suavizar(p, Math.max(1, Math.min(20, mod.vueltas | 0))));
    } else if (mod.tipo === 'subdividir') {
      for (let k = 0; k < Math.max(1, Math.min(3, mod.niveles | 0)); k++) {
        if (piezas.reduce((s, p) => s + nTri(p), 0) * 4 > MAX_TRIANGULOS) break;
        piezas = piezas.map((p) => suavizar(subdividir(p), 2, 0.6, null, false));
      }
    }
  }
  return piezas;
}
