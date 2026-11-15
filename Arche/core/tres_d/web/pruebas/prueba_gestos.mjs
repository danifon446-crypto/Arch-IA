import { crearInterprete } from '../gestos.js';
import { mano } from './mano_falsa.mjs';
let ok = 0, mal = 0;
const prueba = (n, c, d = '') => { c ? ok++ : mal++; console.log((c ? '  ✔ ' : '  ✖ ') + n + (c ? '' : '  ' + d)); };
let g = crearInterprete(), t = 0, o;
const paso = (lista) => { t += 1 / 30; return g.paso(lista.map((p, i) => ({ puntos: p, lado: i ? 'Left' : 'Right' })), t); };

o = paso([]); prueba('sin manos: no hace nada', o.modo === 'nada' && !o.girar[0] && o.zoom === 1);
o = paso([mano(0.5, 0.5)]); prueba('mano relajada: no gira', o.modo === 'nada' && !o.girar[0]);
// pellizcar y mover a la derecha
paso([mano(0.5, 0.5, { pellizco: true })]);
let total = 0;
for (let i = 1; i <= 10; i++) { o = paso([mano(0.5 + i * 0.01, 0.5, { pellizco: true })]); total += o.girar[0]; }
prueba('pellizco + mover a la derecha: gira a la derecha', o.modo === 'girar' && total > 0.06, total);
prueba('y casi nada en vertical', Math.abs(o.girar[1]) < 0.002);
o = paso([mano(0.6, 0.5)]); prueba('al soltar el pellizco avisa para la inercia', o.soltar === true);
o = paso([mano(0.6, 0.5)]); prueba('soltado: deja de girar', o.modo === 'nada' && o.girar[0] === 0);
// volver a pellizcar en otro sitio no da un salto
o = paso([mano(0.2, 0.3, { pellizco: true })]); prueba('pellizcar de nuevo en otro lado no salta', o.girar[0] === 0 && o.girar[1] === 0);
// dos manos: separar = acercar
g = crearInterprete();
paso([mano(0.4, 0.5, { pellizco: true }), mano(0.6, 0.5, { pellizco: true })]);
let z = 1;
for (let i = 1; i <= 8; i++) { o = paso([mano(0.4 - i * 0.01, 0.5, { pellizco: true }), mano(0.6 + i * 0.01, 0.5, { pellizco: true })]); z *= o.zoom; }
prueba('dos manos separándose: acerca (zoom < 1)', o.modo === 'zoom' && z < 0.85, z);
for (let i = 1; i <= 8; i++) o = paso([mano(0.32 + i * 0.01, 0.5, { pellizco: true }), mano(0.68 - i * 0.01, 0.5, { pellizco: true })]);
prueba('juntándose: aleja (zoom > 1)', o.zoom > 1, o.zoom);
let mv = 0;
for (let i = 1; i <= 5; i++) { o = paso([mano(0.4, 0.5 + i * 0.01, { pellizco: true }), mano(0.6, 0.5 + i * 0.01, { pellizco: true })]); mv += o.mover[1]; }
prueba('dos manos moviéndose juntas: desplaza', mv > 0.03 && Math.abs(o.zoom - 1) < 0.01, mv);
// palma abierta quieta -> reiniciar una sola vez
g = crearInterprete(); t = 0;
let reinicios = 0, prog = 0;
for (let i = 0; i < 45; i++) { o = paso([mano(0.5, 0.5, { abierta: true })]); reinicios += o.reiniciar ? 1 : 0; prog = Math.max(prog, o.progreso); }
prueba('palma abierta quieta 1,5 s: reinicia UNA vez', reinicios === 1 && prog === 1, reinicios);
g = crearInterprete(); t = 0; reinicios = 0;
for (let i = 0; i < 45; i++) { o = paso([mano(0.3 + (i % 2) * 0.05, 0.5, { abierta: true })]); reinicios += o.reiniciar ? 1 : 0; }
prueba('palma abierta pero moviéndose (saludando): no reinicia', reinicios === 0);
// un salto loco de detección no hace girar de golpe
g = crearInterprete();
paso([mano(0.5, 0.5, { pellizco: true })]); paso([mano(0.51, 0.5, { pellizco: true })]);
o = paso([mano(0.95, 0.1, { pellizco: true })]);
prueba('un salto de detección no da un giro enorme', Math.abs(o.girar[0]) < 0.3, o.girar[0]);
// histéresis: dedos a medio separar no sueltan el pellizco
g = crearInterprete();
paso([mano(0.5, 0.5, { pellizco: true })]);
const medio = mano(0.5, 0.5, { pellizco: true }); medio[4] = { x: medio[8].x + 0.12 * 0.42, y: medio[8].y, z: 0 };
o = paso([medio]); prueba('dedos un poco separados no sueltan el pellizco (no parpadea)', o.modo === 'girar');

// ---- gestos nuevos ----
g = crearInterprete(); t = 0;
o = paso([mano(0.5, 0.5)]); prueba('mano relajada: no apunta ni acepta', o.modo === 'nada' && !o.puntero && !o.aceptar);
o = paso([mano(0.3, 0.4, { apunta: true })]); prueba('apuntar con el índice mueve el puntero', o.modo === 'apuntar' && o.puntero && o.puntero.x < 0.4);
// toque: pellizco corto y quieto
g = crearInterprete(); t = 0;
paso([mano(0.4, 0.4)]);
for (let i = 0; i < 4; i++) o = paso([mano(0.4, 0.4, { pellizco: true })]);
o = paso([mano(0.4, 0.4)]);
prueba('pellizco corto = toque en ese punto', o.toque && Math.abs(o.toque.x - 0.4 + 0.066) < 0.05, JSON.stringify(o.toque));
g = crearInterprete(); t = 0;
for (let i = 0; i < 5; i++) paso([mano(0.6, 0.3, { apunta: true })]);
for (let i = 0; i < 3; i++) o = paso([mano(0.6, 0.3, { pellizco: true })]);
o = paso([mano(0.6, 0.3)]);
prueba('apuntar y pellizcar toca DONDE apuntabas (la punta del índice)', o.toque && Math.abs(o.toque.x - (0.6 - 0.3 * 0.12)) < 0.01 && Math.abs(o.toque.y - (0.3 - 1.25 * 0.12)) < 0.01, JSON.stringify(o.toque));
g = crearInterprete(); t = 0;
paso([mano(0.4, 0.4)]);
for (let i = 0; i < 25; i++) o = paso([mano(0.4, 0.4, { pellizco: true })]);
o = paso([mano(0.4, 0.4)]);
prueba('pellizco largo (girar) NO es toque', !o.toque);
g = crearInterprete(); t = 0;
paso([mano(0.4, 0.4)]);
for (let i = 0; i < 6; i++) o = paso([mano(0.4 + i * 0.03, 0.4, { pellizco: true })]);
o = paso([mano(0.55, 0.4)]);
prueba('pellizco corto pero arrastrando NO es toque', !o.toque);
// deslizar
g = crearInterprete(); t = 0;
let desliz = [];
for (let i = 0; i < 9; i++) { o = paso([mano(0.2 + i * 0.05, 0.5, { abierta: true })]); if (o.deslizar) desliz.push(o.deslizar); }
prueba('palma abierta pasando rápido a la derecha = deslizar derecha (una vez)', desliz.length === 1 && desliz[0] === 'derecha', desliz);
g = crearInterprete(); t = 0; desliz = []; reinicios = 0;
for (let i = 0; i < 9; i++) { o = paso([mano(0.8 - i * 0.05, 0.5, { abierta: true })]); if (o.deslizar) desliz.push(o.deslizar); reinicios += o.reiniciar ? 1 : 0; }
prueba('y a la izquierda = deslizar izquierda, sin reiniciar la vista', desliz[0] === 'izquierda' && reinicios === 0);
g = crearInterprete(); t = 0; desliz = [];
for (let i = 0; i < 40; i++) { o = paso([mano(0.4 + (i % 2) * 0.02, 0.5, { abierta: true })]); if (o.deslizar) desliz.push(1); }
prueba('mano abierta casi quieta NO desliza', desliz.length === 0);
// pulgar arriba
g = crearInterprete(); t = 0;
let acepta = 0, progPulgar = 0;
for (let i = 0; i < 40; i++) { o = paso([mano(0.5, 0.5, { pulgar: true })]); acepta += o.aceptar ? 1 : 0; if (o.modo === 'pulgar') progPulgar = Math.max(progPulgar, o.progreso); }
prueba('pulgar arriba sostenido = aceptar UNA vez', acepta === 1 && progPulgar === 1, acepta);
g = crearInterprete(); t = 0; acepta = 0;
for (let i = 0; i < 10; i++) { o = paso([mano(0.5, 0.5, { pulgar: true })]); acepta += o.aceptar ? 1 : 0; }
prueba('pulgar arriba un instante NO acepta', acepta === 0);
g = crearInterprete(); t = 0; acepta = 0;
for (const f of [{}, { abierta: true }, { pellizco: true }, { apunta: true }]) for (let i = 0; i < 30; i++) { o = paso([mano(0.5, 0.5, f)]); acepta += o.aceptar ? 1 : 0; }
prueba('ningún otro gesto se confunde con el pulgar', acepta === 0);
// consejos de cámara
g = crearInterprete(); t = 0;
prueba('mano muy cerca: avisa', /cerca/.test(paso([mano(0.5, 0.5, { tam: 0.4 })]).consejo));
prueba('mano muy lejos: avisa', /lejos/.test(paso([mano(0.5, 0.5, { tam: 0.04 })]).consejo));
prueba('mano bien puesta: sin consejo', paso([mano(0.5, 0.5)]).consejo === '');

// ---- gestos de Construir ----
g = crearInterprete(); t = 0;
let n = 0;
for (let i = 0; i < 30; i++) { o = paso([mano(0.5, 0.5, { abajo: true })]); n += o.rechazar ? 1 : 0; }
prueba('pulgar abajo sostenido = rechazar UNA vez', n === 1, n);
g = crearInterprete(); t = 0; n = 0; let ac = 0;
for (let i = 0; i < 30; i++) { o = paso([mano(0.5, 0.5, { ve: true })]); n += o.duplicar ? 1 : 0; ac += o.aceptar ? 1 : 0; }
prueba('dedos en V sostenidos = duplicar UNA vez', n === 1 && ac === 0, n);
g = crearInterprete(); t = 0; n = 0;
for (const f of [{}, { abierta: true }, { apunta: true }, { pulgar: true }]) for (let i = 0; i < 30; i++) { o = paso([mano(0.5, 0.5, f)]); n += (o.duplicar || o.rechazar) ? 1 : 0; }
prueba('ni la mano relajada, ni abierta, ni apuntando, ni el pulgar arriba se confunden con V o pulgar abajo', n === 0, n);
g = crearInterprete(); t = 0;
paso([mano(0.4, 0.5, { pellizco: true }), mano(0.6, 0.5, { pellizco: true })]);
let ex = 1, ey = 1;
for (let i = 1; i <= 8; i++) { o = paso([mano(0.4 - i * 0.01, 0.5, { pellizco: true }), mano(0.6 + i * 0.01, 0.5, { pellizco: true })]); ex *= o.estirar[0]; ey *= o.estirar[1]; }
prueba('separar las manos en horizontal estira en X, no en Y', ex > 1.5 && Math.abs(ey - 1) < 0.05, `${ex} ${ey}`);
g = crearInterprete(); t = 0;
paso([mano(0.5, 0.35, { pellizco: true }), mano(0.5, 0.65, { pellizco: true })]);
ex = 1; ey = 1;
for (let i = 1; i <= 8; i++) { o = paso([mano(0.5, 0.35 - i * 0.01, { pellizco: true }), mano(0.5, 0.65 + i * 0.01, { pellizco: true })]); ex *= o.estirar[0]; ey *= o.estirar[1]; }
prueba('separarlas en vertical estira en Y (alto)', ey > 1.4 && Math.abs(ex - 1) < 0.05, `${ex} ${ey}`);
g = crearInterprete(); t = 0;
let giro = 0;
for (let i = 0; i <= 12; i++) {
  const a = i * 0.04;
  o = paso([mano(0.5 - 0.12 * Math.cos(a), 0.5 - 0.12 * Math.sin(a), { pellizco: true }), mano(0.5 + 0.12 * Math.cos(a), 0.5 + 0.12 * Math.sin(a), { pellizco: true })]);
  giro += o.torcer;
}
prueba('girar las dos manos como un volante = torcer', giro > 0.35 && giro < 0.6, giro);
console.log(`\n${ok}/${ok + mal} pruebas de gestos pasaron.`);
process.exit(mal ? 1 : 0);
