// Manos falsas (21 puntos de MediaPipe) para probar los gestos sin cámara.
export function mano(x, y, { tam = 0.12, pellizco = false, abierta = false, apunta = false, pulgar = false, abajo = false, ve = false } = {}) {
  const p = Array.from({ length: 21 }, () => ({ x, y, z: 0 }));
  const en = (i, dx, dy) => { p[i] = { x: x + dx * tam, y: y + dy * tam, z: 0 }; };
  en(0, 0, 0.9);                                    // muñeca abajo
  en(9, 0, -0.1);                                   // nudillo del medio (muñeca->9 = 1 tamaño)
  en(5, -0.3, -0.05); en(13, 0.25, -0.05); en(17, 0.45, 0.05);
  const largo = abierta ? 1.0 : 0.35;               // dedos estirados o doblados
  en(12, 0, -0.1 - largo); en(16, 0.3, -0.05 - largo * 0.95); en(20, 0.55, 0.05 - largo * 0.8);
  if (pellizco) { en(8, -0.55, -0.5); en(4, -0.58, -0.47); }      // punta del índice y del pulgar juntas
  else if (abierta) { en(8, -0.35, -1.15); en(4, -0.95, 0.1); }
  else { en(8, -0.35, -0.45); en(4, -0.75, -0.05); }
  for (const i of [1, 2, 3, 6, 7, 10, 11, 14, 15, 18, 19]) p[i] = { x: p[0].x, y: p[0].y - tam * 0.5, z: 0 };
  if (apunta) { en(8, -0.3, -1.25); en(12, 0, 0.25); en(16, 0.25, 0.3); en(20, 0.45, 0.35); en(4, -0.5, 0.2); }
  if (pulgar) { en(8, -0.3, 0.2); en(12, 0, 0.25); en(16, 0.25, 0.3); en(20, 0.45, 0.35); en(2, -0.4, 0.4); en(4, -0.25, -0.65); }
  if (abajo) {          // pulgar arriba, con la mano girada 180°: el pulgar apunta al suelo
    const arriba = mano(x, y, { tam, pulgar: true });
    return arriba.map((q) => ({ x: 2 * x - q.x, y: 2 * y - q.y, z: 0 }));
  }
  if (ve) { en(8, -0.35, -1.25); en(12, 0.1, -1.3); en(16, 0.25, 0.3); en(20, 0.45, 0.35); en(4, -0.5, 0.2); }
  return p;
}
