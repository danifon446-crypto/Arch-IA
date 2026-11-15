// Pruebas del motor de mallas de Modelar: todo debe quedar CERRADO (imprimible) y con las medidas correctas.
import * as M from '../malla_edit.js';
let ok = 0, mal = 0;
const prueba = (n, c, d = '') => { c ? ok++ : mal++; console.log((c ? '  ✔ ' : '  ✖ ') + n + (c ? '' : '  ' + d)); };
const cerca = (a, b, tol) => Math.abs(a - b) <= tol;

const cubo = M.cubo(20, 20, 20, 6);
prueba('cubo: cerrado y de 20×20×20 = 8000 mm³', M.cerrada(cubo) && cerca(M.volumen(cubo), 8000, 1e-3), M.volumen(cubo));
const lim = M.limites(cubo);
prueba('cubo: centrado en X/Y y apoyado en Z=0', cerca(lim.min[0], -10, 1e-6) && cerca(lim.min[2], 0, 1e-6) && cerca(lim.max[2], 20, 1e-6));
const esf = M.esfera(20, 3);
prueba('esfera: cerrada y con volumen cercano a 4/3·π·r³', M.cerrada(esf) && cerca(M.volumen(esf), 4 / 3 * Math.PI * 1000, 4189 * 0.03), M.volumen(esf));
const cil = M.cilindro(20, 30, 32, 6);
prueba('cilindro: cerrado y con volumen cercano a π·r²·h', M.cerrada(cil) && cerca(M.volumen(cil), Math.PI * 100 * 30, 9425 * 0.02), M.volumen(cil));
prueba('cono: cerrado', M.cerrada(M.cono(20, 30)) && M.volumen(M.cono(20, 30)) > 0);
const tor = M.toro(30, 8);
prueba('toro: cerrado', M.cerrada(tor) && M.volumen(tor) > 0);
const sub = M.subdividir(cubo);
prueba('subdividir: 4 veces más triángulos, sigue cerrado y con el mismo volumen', M.nTri(sub) === M.nTri(cubo) * 4 && M.cerrada(sub) && cerca(M.volumen(sub), 8000, 1e-2));
const suave = M.suavizar(esf, 3);
prueba('suavizar no rompe la malla ni la encoge mucho', M.cerrada(suave) && M.volumen(suave) > M.volumen(esf) * 0.9);

// --- extruir la cara de arriba del cubo 10 mm
const vec = M.triangulosVecinos(cubo);
let arriba = 0;
for (let t = 0; t < M.nTri(cubo); t++) { const n = M.normalTri(cubo, t); if (n[2] > 0.99) { arriba = t; break; } }
const region = M.regionPlana(cubo, arriba, 0.995, vec);
prueba('tocar un triángulo de arriba elige toda la cara de arriba', region.size === 6 * 6 * 2, region.size);
const info = M.infoRegion(cubo, region);
prueba('la cara de arriba: normal hacia arriba y centro en z=20', cerca(info.normal[2], 1, 1e-6) && cerca(info.centro[2], 20, 1e-6));
let { malla: ext, nuevos } = M.anillo(cubo, region);
prueba('al empezar a extruir sigue cerrada (anillo sin grosor)', M.cerrada(ext));
M.moverVertices(ext, nuevos, (x, y, z) => [x, y, z + 10]);
prueba('extruir 10 mm: cerrada y de 20×20×30 = 12000 mm³', M.cerrada(ext) && cerca(M.volumen(ext), 12000, 1e-2), M.volumen(ext));
// insertar (inset): misma operación, achicando hacia el centro
let ins = M.anillo(cubo, region);
M.moverVertices(ins.malla, ins.nuevos, (x, y, z) => [x * 0.5, y * 0.5, z]);
prueba('insertar: cerrada y el volumen no cambia (solo se dibuja una cara adentro)', M.cerrada(ins.malla) && cerca(M.volumen(ins.malla), 8000, 1e-2));
// extruir esa cara de adentro hacia abajo = un hueco
const r2 = M.regionPlana(ins.malla, [...region][0], 0.995);
prueba('después de insertar, tocar la cara de adentro elige SOLO esa cara (como en Blender)', r2.size === region.size, r2.size);
let hueco = M.anillo(ins.malla, r2);
M.moverVertices(hueco.malla, hueco.nuevos, (x, y, z) => [x, y, z - 5]);
prueba('insertar y luego hundir 5 mm = un hueco de 10×10×5 (500 mm³ menos)', M.cerrada(hueco.malla) && cerca(M.volumen(hueco.malla), 7500, 1e-2), M.volumen(hueco.malla));

// --- escultura
const bola = M.esfera(20, 4);
const v0 = M.volumen(bola);
const punta = [0, 0, 20];
const lista = M.pincelar(bola, 'inflar', punta, 6, 1);
prueba('inflar solo mueve los vértices bajo el pincel', lista.length > 0 && lista.length < M.nVert(bola) / 4, lista.length);
prueba('inflar aumenta el volumen', M.volumen(bola) > v0);
const v1 = M.volumen(bola);
M.pincelar(bola, 'hundir', punta, 6, 1);
M.pincelar(bola, 'hundir', punta, 6, 1);
prueba('hundir lo disminuye', M.volumen(bola) < v1);
const antes = Float32Array.from(bola.v);
M.pincelar(bola, 'agarrar', [10, 0, 10], 5, 1, { delta: [5, 0, 0] });
let maxMov = 0, lejosMov = 0;
for (let i = 0; i < M.nVert(bola); i++) {
  const d = Math.hypot(bola.v[i * 3] - antes[i * 3], bola.v[i * 3 + 1] - antes[i * 3 + 1], bola.v[i * 3 + 2] - antes[i * 3 + 2]);
  const dc = Math.hypot(antes[i * 3] - 10, antes[i * 3 + 1], antes[i * 3 + 2] - 10);
  maxMov = Math.max(maxMov, d);
  if (dc > 5) lejosMov = Math.max(lejosMov, d);
}
prueba('agarrar jala la zona (hasta 5 mm) y no toca lo que está lejos', cerca(maxMov, 5, 0.6) && lejosMov === 0, `${maxMov} ${lejosMov}`);
M.pincelar(bola, 'alisar', [10, 0, 10], 6, 1);
M.pincelar(bola, 'aplanar', [0, 0, 20], 6, 1);
M.pincelar(bola, 'pellizcar', [0, 0, 20], 6, 1);
prueba('después de todos los pinceles la malla sigue cerrada', M.cerrada(bola));

// --- modificadores
const esp = M.aplicarModificadores(cubo, [{ tipo: 'espejo', eje: 0 }]);
prueba('espejo: 2 piezas y la copia también cerrada (caras volteadas bien)', esp.length === 2 && M.cerrada(esp[1]) && cerca(M.volumen(esp[1]), 8000, 1e-3));
const mat = M.aplicarModificadores(cubo, [{ tipo: 'matriz', cantidad: 4, separacion: 30, circular: 0 }]);
prueba('matriz: 4 copias separadas 30 mm', mat.length === 4 && cerca(M.limites(mat[3]).min[0], 80, 1e-4));
const circ = M.aplicarModificadores(M.cubo(5, 5, 5, 2), [{ tipo: 'matriz', cantidad: 6, circular: 1 }]);
prueba('matriz circular: 6 copias girando', circ.length === 6);
const rueda = M.aplicarModificadores(M.cubo(2, 2, 2, 1), [{ tipo: 'matriz', cantidad: 4, circular: 1, radio: 20 }]);
prueba('matriz circular con radio: las copias quedan a esa distancia del centro',
  rueda.every((p) => { const l = M.limites(p); return Math.abs(Math.hypot((l.min[0] + l.max[0]) / 2, (l.min[1] + l.max[1]) / 2) - 20) < 1e-6; }));
const sd = M.aplicarModificadores(cubo, [{ tipo: 'subdividir', niveles: 2 }]);
prueba('subdividir 2 niveles: 16× triángulos, cerrada y más redondeada', M.nTri(sd[0]) === M.nTri(cubo) * 16 && M.cerrada(sd[0]) && M.volumen(sd[0]) < 8000);
const apagado = M.aplicarModificadores(cubo, [{ tipo: 'espejo', eje: 0, apagado: true }]);
prueba('un modificador apagado no hace nada', apagado.length === 1);
const soldado = M.soldar(Float32Array.from([0, 0, 0, 1, 0, 0, 0, 1, 0, 0, 0, 0.00001, 1, 0, 0, 0, 1, 0]), Uint32Array.from([0, 1, 2, 3, 4, 5]));
prueba('soldar une los vértices repetidos', M.nVert(soldado) === 3);
console.log(`\n${ok}/${ok + mal} pruebas de mallas pasaron.`);
process.exit(mal ? 1 : 0);
