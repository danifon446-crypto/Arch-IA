// Gestos: convierte los puntos de las manos (MediaPipe) en órdenes.
// No sabe nada de three.js ni de la página: recibe manos, devuelve órdenes. Así se puede probar solo.
//
//   apuntar con el índice                -> mueve el puntero por la pantalla
//   pellizco rápido (tocar en el aire)   -> toca lo que está bajo el puntero (botones, piezas, medir)
//   pellizcar y mover una mano           -> girar
//   pellizcar con las dos manos          -> separarlas acerca, juntarlas aleja; moverlas juntas desplaza
//   mano abierta quieta ~1 segundo       -> reiniciar (volver a encuadrar)
//   mano abierta pasando rápido de lado  -> deslizar (siguiente / anterior)
//   pulgar arriba ~0,6 segundos          -> aceptar (aplica lo que Arché recomienda / guarda)
//   pulgar abajo ~0,6 segundos           -> rechazar (borra la parte elegida en Construir)
//   dos dedos en V ~0,5 segundos         -> duplicar (en Construir)
//   dos manos pellizcando también dicen cuánto se separan en horizontal y en vertical, y cuánto
//   giran (para estirar y girar partes en Construir)
//
// Los puntos vienen normalizados (0..1) sobre la imagen ya volteada como espejo.

const PELLIZCO_SI = 0.33;        // dedos así de juntos (en tamaños de mano) = pellizco
const PELLIZCO_NO = 0.50;        // y se suelta recién al separarlos esto (histéresis: no parpadea)
const SUAVE = 0.45;              // suavizado de los puntos (0 = nada, 1 = congelado)
const QUIETA = 0.012;            // cuánto se puede mover una mano "quieta" por cuadro
const TIEMPO_PALMA = 0.9;        // segundos de palma abierta quieta para reiniciar
const SALTO_MAX = 0.25;          // un salto mayor entre cuadros es un error de detección: se ignora
const TOQUE_MAX_S = 0.6;         // un pellizco más corto que esto es un toque...
const TOQUE_MAX_MOV = 0.035;     // ...si además casi no se movió
const DESLIZ_DIST = 0.20;        // la palma recorre esto de lado...
const DESLIZ_TIEMPO = 0.50;      // ...en menos de esto = deslizar
const ESPERA_DESLIZ = 0.8;       // y no se repite antes de esto
const TIEMPO_PULGAR = 0.6;       // segundos con el pulgar arriba (o abajo) para aceptar (o rechazar)
const TIEMPO_V = 0.5;            // segundos con los dedos en V para duplicar

const d2 = (a, b) => Math.hypot(a.x - b.x, a.y - b.y);

function rasgos(p) {
  const tam = Math.max(d2(p[0], p[9]), 1e-4);                       // muñeca -> nudillo del medio
  const pellizco = d2(p[4], p[8]) / tam;
  const lejos = (i, f) => d2(p[i], p[0]) > f * tam;
  const estirados = [8, 12, 16, 20].filter((i) => lejos(i, 1.55)).length;
  const doblados = [12, 16, 20].filter((i) => !lejos(i, 1.25)).length;
  // apuntar: el índice estirado y los otros tres doblados
  const apunta = lejos(8, 1.55) && doblados === 3 && pellizco > 0.6;
  // pulgar arriba / abajo: los cuatro dedos doblados y el pulgar bien por encima (o por debajo) de su nudillo
  const cerrada = [8, 12, 16, 20].every((i) => !lejos(i, 1.3)) && lejos(4, 1.2);
  const pulgar = cerrada && (p[2].y - p[4].y) > 0.55 * tam;
  const pulgarAbajo = cerrada && (p[4].y - p[2].y) > 0.55 * tam;
  // V: índice y medio estirados y separados; anular y meñique doblados
  const ve = lejos(8, 1.55) && lejos(12, 1.55) && !lejos(16, 1.25) && !lejos(20, 1.25) && d2(p[8], p[12]) > 0.35 * tam && pellizco > 0.6;
  return { tam, pellizco, abierta: estirados === 4 && pellizco > 0.6, apunta: apunta && !ve, pulgar, pulgarAbajo, ve,
           punto: { x: (p[4].x + p[8].x) / 2, y: (p[4].y + p[8].y) / 2 }, indice: p[8], palma: p[9] };
}

export function crearInterprete() {
  const manos = new Map();       // clave -> estado de esa mano
  let antes = null;              // referencia del gesto en curso
  let palmaDesde = 0, palmaUsada = false, ultimoT = 0, ultimoDesliz = -10, pulgarDesde = 0, pulgarUsado = false;
  const sostenidos = {};          // gesto -> { desde, usado }: los que se activan sosteniéndolos

  function claves(lista) {
    // "Left"/"Right"; si las dos dicen lo mismo (pasa), se distinguen por el orden
    const usadas = new Set();
    return lista.map((m) => {
      let c = m.lado || 'mano';
      if (usadas.has(c)) c = c + '2';
      usadas.add(c);
      return c;
    });
  }

  return {
    // lista: [{ puntos: [21 x {x,y,z}], lado: 'Left'|'Right' }]   t: segundos
    paso(lista, t) {
      const dt = ultimoT ? Math.min(0.2, t - ultimoT) : 0;
      ultimoT = t;
      const ks = claves(lista);
      const vivas = new Set(ks);
      for (const k of [...manos.keys()]) if (!vivas.has(k)) manos.delete(k);

      const orden = { girar: [0, 0], zoom: 1, mover: [0, 0], reiniciar: false, soltar: false, toque: null,
                      deslizar: null, aceptar: false, rechazar: false, duplicar: false, estirar: [1, 1], torcer: 0,
                      puntero: null, modo: 'nada', progreso: 0, consejo: '',
                      cursores: [], dt };
      lista.forEach((m, i) => {
        const r = rasgos(m.puntos);
        let e = manos.get(ks[i]);
        if (!e) {
          e = { pellizca: false, x: r.punto.x, y: r.punto.y, ix: r.indice.x, iy: r.indice.y, px: r.palma.x, py: r.palma.y,
                rastro: [] };
          manos.set(ks[i], e);
        }
        const antesPellizca = e.pellizca;
        e.pellizca = e.pellizca ? r.pellizco < PELLIZCO_NO : r.pellizco < PELLIZCO_SI;
        const salto = Math.hypot(r.punto.x - e.x, r.punto.y - e.y) > SALTO_MAX;
        e.salto = salto;                 // ese cuadro no cuenta como movimiento (fue la detección, no tu mano)
        const k = salto ? 0 : SUAVE;
        e.x = e.x * k + r.punto.x * (1 - k);
        e.y = e.y * k + r.punto.y * (1 - k);
        e.ix = e.ix * k + r.indice.x * (1 - k);
        e.iy = e.iy * k + r.indice.y * (1 - k);
        e.movPalma = Math.hypot(r.palma.x - e.px, r.palma.y - e.py);
        e.px = r.palma.x; e.py = r.palma.y;
        e.abierta = r.abierta && !e.pellizca;
        e.apunta = r.apunta && !e.pellizca;
        e.pulgar = r.pulgar && !e.pellizca;
        e.pulgarAbajo = r.pulgarAbajo && !e.pellizca;
        e.ve = r.ve && !e.pellizca;
        // Al pellizcar, el puntero NO salta: sigue donde lo veías (la punta del índice al apuntar)
        // y desde ahí se mueve con la mano. Así tocas justo lo que estabas señalando.
        if (e.pellizca && !antesPellizca) {
          const reciente = e.apuntaT && t - e.apuntaT < 0.5;
          e.pellizcoX = reciente ? e.apuntaX : e.x;
          e.pellizcoY = reciente ? e.apuntaY : e.y;
          e.ajX = e.pellizcoX - e.x; e.ajY = e.pellizcoY - e.y;
          e.pellizcoDesde = t;
          e.pellizcoMx = e.x; e.pellizcoMy = e.y;
        }
        if (!e.pellizca) { e.ajX = 0; e.ajY = 0; }
        if (r.apunta && !e.pellizca) { e.apuntaX = e.ix; e.apuntaY = e.iy; e.apuntaT = t; }
        if (!e.pellizca && antesPellizca && t - e.pellizcoDesde < TOQUE_MAX_S &&
            Math.hypot(e.x - e.pellizcoMx, e.y - e.pellizcoMy) < TOQUE_MAX_MOV) {
          orden.toque = { x: e.pellizcoX, y: e.pellizcoY };
        }
        // rastro de la palma abierta (para deslizar)
        e.rastro.push({ t, x: r.palma.x, y: r.palma.y, abierta: r.abierta });
        while (e.rastro.length && t - e.rastro[0].t > DESLIZ_TIEMPO) e.rastro.shift();
        // consejos sobre cómo te ve la cámara
        if (r.tam > 0.32) orden.consejo = 'Muy cerca: aleja un poco la mano de la cámara';
        else if (r.tam < 0.06) orden.consejo = 'Muy lejos: acerca la mano a la cámara';
        else if (r.palma.x < 0.05 || r.palma.x > 0.95 || r.palma.y < 0.05 || r.palma.y > 0.95) orden.consejo = 'La mano se sale del cuadro';
        orden.cursores.push({ x: e.apunta ? e.ix : e.x + (e.ajX || 0), y: e.apunta ? e.iy : e.y + (e.ajY || 0),
                              pellizca: e.pellizca, abierta: e.abierta, ve: e.ve, pulgarAbajo: e.pulgarAbajo,
                              apunta: e.apunta, pulgar: e.pulgar });
      });

      const todas = [...manos.values()];
      const pinzas = todas.filter((e) => e.pellizca);

      if (pinzas.length === 1) {
        const p = pinzas[0];
        if (antes && antes.modo === 'girar' && antes.mano === p && !p.salto) {
          orden.girar = [p.x - antes.x, p.y - antes.y];
        }
        antes = { modo: 'girar', mano: p, x: p.x, y: p.y };
        orden.modo = 'girar';
        orden.puntero = { x: p.x + (p.ajX || 0), y: p.y + (p.ajY || 0) };
      } else if (pinzas.length >= 2) {
        const [a, b] = pinzas;
        const dist = Math.max(Math.hypot(a.x - b.x, a.y - b.y), 0.02);
        const mx = (a.x + b.x) / 2, my = (a.y + b.y) / 2;
        const sx = Math.max(Math.abs(a.x - b.x), 0.04), sy = Math.max(Math.abs(a.y - b.y), 0.04);
        const ang = Math.atan2(b.y - a.y, b.x - a.x);
        if (antes && antes.modo === 'dos' && antes.a === a && antes.b === b && !a.salto && !b.salto) {
          orden.zoom = antes.dist / dist;                  // separar (dist crece) -> zoom < 1 -> más cerca
          orden.mover = [mx - antes.mx, my - antes.my];
          orden.estirar = [sx / antes.sx, sy / antes.sy];  // > 1: se separan en ese sentido
          let da = ang - antes.ang;
          if (da > Math.PI) da -= 2 * Math.PI;
          if (da < -Math.PI) da += 2 * Math.PI;
          orden.torcer = da;                               // radianes, + = en el sentido del reloj (en pantalla)
        }
        antes = { modo: 'dos', a, b, dist, mx, my, sx, sy, ang };
        orden.modo = 'zoom';
      } else {
        if (antes && antes.modo === 'girar') orden.soltar = true;   // para la inercia
        antes = null;
        const apunta = todas.find((e) => e.apunta);
        if (apunta) { orden.modo = 'apuntar'; orden.puntero = { x: apunta.ix, y: apunta.iy }; }
      }

      // deslizar: palma abierta que cruza rápido de lado
      if (!pinzas.length && t - ultimoDesliz > ESPERA_DESLIZ) {
        for (const e of todas) {
          const r = e.rastro;
          if (r.length < 3 || !r.every((q) => q.abierta)) continue;
          const dx = r[r.length - 1].x - r[0].x, dy = r[r.length - 1].y - r[0].y;
          if (Math.abs(dx) > DESLIZ_DIST && Math.abs(dy) < Math.abs(dx) * 0.6) {
            orden.deslizar = dx > 0 ? 'derecha' : 'izquierda';
            ultimoDesliz = t;
            e.rastro = [];
            palmaDesde = 0;
            break;
          }
        }
      }

      // palma abierta quieta -> reiniciar (una vez; hay que cerrarla para repetir)
      const palma = !pinzas.length && !orden.deslizar && todas.find((e) => e.abierta && e.movPalma < QUIETA);
      if (palma) {
        if (!palmaDesde) palmaDesde = t;
        orden.progreso = palmaUsada ? 0 : Math.min(1, (t - palmaDesde) / TIEMPO_PALMA);
        if (orden.progreso >= 1 && !palmaUsada) { orden.reiniciar = true; palmaUsada = true; }
        if (!palmaUsada) orden.modo = 'palma';
      } else if (!todas.some((e) => e.abierta)) {
        palmaDesde = 0; palmaUsada = false;
      } else {
        palmaDesde = 0;
      }

      // pulgar arriba sostenido -> aceptar (una vez; hay que bajarlo para repetir)
      const pulgar = !pinzas.length && todas.find((e) => e.pulgar);
      if (pulgar) {
        if (!pulgarDesde) pulgarDesde = t;
        const avance = pulgarUsado ? 0 : Math.min(1, (t - pulgarDesde) / TIEMPO_PULGAR);
        if (!pulgarUsado) { orden.modo = 'pulgar'; orden.progreso = avance; }
        if (avance >= 1 && !pulgarUsado) { orden.aceptar = true; pulgarUsado = true; }
      } else {
        pulgarDesde = 0; pulgarUsado = false;
      }
      // gestos que se activan sosteniéndolos un momento (una vez; hay que soltarlos para repetir)
      const sostener = (clave, activo, tiempo, salida) => {
        const s_ = sostenidos[clave] || (sostenidos[clave] = { desde: 0, usado: false });
        if (!activo) { s_.desde = 0; s_.usado = false; return; }
        if (!s_.desde) s_.desde = t;
        const avance = s_.usado ? 0 : Math.min(1, (t - s_.desde) / tiempo);
        if (!s_.usado && orden.modo === 'nada') { orden.modo = clave; orden.progreso = avance; }
        if (avance >= 1 && !s_.usado) { orden[salida] = true; s_.usado = true; }
      };
      sostener('abajo', !pinzas.length && todas.some((e) => e.pulgarAbajo), TIEMPO_PULGAR, 'rechazar');
      sostener('ve', !pinzas.length && todas.some((e) => e.ve), TIEMPO_V, 'duplicar');
      return orden;
    },
    reiniciar() {
      for (const k of Object.keys(sostenidos)) delete sostenidos[k];
      manos.clear(); antes = null; palmaDesde = 0; palmaUsada = false; ultimoT = 0;
      ultimoDesliz = -10; pulgarDesde = 0; pulgarUsado = false;
    },
  };
}
