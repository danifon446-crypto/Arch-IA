/* cara.js  El celular montado al frente del perro hace de CARA: ojos animados a pantalla completa.
   Mientras tanto la camara frontal sigue siendo los ojos de verdad (manda video y fotos a Arche).

   Los ojos:
   * parpadean solos y miran hacia la cara (o la pelota) que detecta Arche,
   * cambian con el animo del perro: alegre, asustado, cauteloso, cazador, aburrido, dormido, enojado.
   Para salir: mantener el dedo 2 segundos en la pantalla.

   Uso: Cara.abrir({estado: () => E, deteccion: () => ultimo}), Cara.cerrar()
*/
const Cara = (() => {
  let lienzo = null, ctx = null, corriendo = false, fuentes = null, aviso = null;
  // estado animado (se acerca suave a la meta en cada cuadro)
  const s = {abre: 1, pupila: 0.27, ceno: 0, feliz: 0, mx: 0, my: 0, temblor: 0, color: [143, 240, 255]};
  let parpadeo = 0, proximoParpadeo = 0, mirarHasta = 0, miradaLibre = {x: 0, y: 0};

  const COLOR = {normal: [143, 240, 255], enojado: [255, 110, 90], dormido: [110, 170, 200], alegre: [160, 255, 200]};

  // animo -> forma de los ojos
  function meta(E, det) {
    const accion = E && E.modo !== "paro" ? E.accion_actual : null;
    const mood = E && E.perro ? E.perro.mood : "tranquilo";
    let m = {abre: 1, pupila: 0.27, ceno: 0, feliz: 0, temblor: 0, color: COLOR.normal, zzz: false};
    if (["feliz", "saludar", "cola"].includes(accion) || mood === "alegre") Object.assign(m, {feliz: 1, color: COLOR.alegre});
    if (accion === "enojado" || accion === "ladrar") Object.assign(m, {abre: 0.72, ceno: 1, pupila: 0.24, color: COLOR.enojado});
    if (mood === "asustado" || accion === "asustarse") Object.assign(m, {abre: 1.12, pupila: 0.13, temblor: 1});
    if (mood === "cauteloso") Object.assign(m, {abre: 0.55, pupila: 0.25});
    if (mood === "cazador") Object.assign(m, {abre: 0.66, ceno: 0.55, pupila: 0.26});
    if (mood === "aburrido") Object.assign(m, {abre: 0.42, pupila: 0.24});
    if (mood === "dormido" || accion === "acostarse") Object.assign(m, {abre: 0.05, feliz: 0, ceno: 0, color: COLOR.dormido, zzz: true});

    // mirada: hacia la cara o la pelota (la camara frontal ve "en espejo" respecto a quien mira la pantalla)
    let objetivo = null;
    const cajas = det && det.cajas ? det.cajas : [];
    const c = cajas.find(k => k[0] === "cara") || cajas.find(k => k[0] === "pelota");
    if (c) objetivo = {x: -(((c[1] + c[3]) / 2) - 0.5) * 2, y: (((c[2] + c[4]) / 2) - 0.5) * 2};
    const t = performance.now();
    if (objetivo) { m.mx = Math.max(-1, Math.min(1, objetivo.x * 1.2)); m.my = Math.max(-1, Math.min(1, objetivo.y)); }
    else {
      if (t > mirarHasta) {                       // sin nadie a la vista: mira de un lado a otro de vez en cuando
        miradaLibre = Math.random() < 0.55 ? {x: 0, y: 0} : {x: (Math.random() * 2 - 1) * 0.8, y: (Math.random() * 2 - 1) * 0.4};
        mirarHasta = t + 1200 + Math.random() * 2600;
      }
      m.mx = miradaLibre.x; m.my = miradaLibre.y;
      if (mood === "aburrido") m.my = 0.6;
    }
    return m;
  }

  const acercar = (a, b, k) => a + (b - a) * k;

  function ojo(cx, cy, w, h, lado, sm, t) {
    const abre = Math.max(0.04, sm.abre * (1 - parpadeo));
    const alto = h * abre;
    const r = Math.min(w, alto) * 0.42;
    const [cr, cg, cb] = sm.color.map(Math.round);
    const col = `rgb(${cr},${cg},${cb})`;
    ctx.save();
    ctx.shadowColor = `rgba(${cr},${cg},${cb},0.55)`;
    ctx.shadowBlur = w * 0.18;
    ctx.fillStyle = col;
    const x0 = cx - w / 2, y0 = cy - alto / 2;
    if (sm.feliz > 0.5 && parpadeo < 0.5) {
      // ojos felices: arco "^"
      ctx.lineWidth = h * 0.16; ctx.lineCap = "round"; ctx.strokeStyle = col;
      ctx.beginPath();
      ctx.arc(cx, cy + h * 0.18, w * 0.42, Math.PI * 1.12, Math.PI * 1.88);
      ctx.stroke();
      ctx.restore();
      return;
    }
    ctx.beginPath();
    ctx.roundRect ? ctx.roundRect(x0, y0, w, alto, r) : ctx.rect(x0, y0, w, alto);
    ctx.fill();
    ctx.shadowBlur = 0;
    // pupila
    if (abre > 0.25) {
      ctx.save();
      ctx.beginPath();
      ctx.roundRect ? ctx.roundRect(x0, y0, w, alto, r) : ctx.rect(x0, y0, w, alto);
      ctx.clip();
      const pr = w * sm.pupila;
      const px = cx + sm.mx * (w / 2 - pr) * 0.9, py = cy + sm.my * (alto / 2 - pr * 0.7) * 0.8;
      ctx.fillStyle = "#05080b";
      ctx.beginPath(); ctx.arc(px, py, pr, 0, Math.PI * 2); ctx.fill();
      ctx.fillStyle = "rgba(255,255,255,0.9)";
      ctx.beginPath(); ctx.arc(px - pr * 0.35, py - pr * 0.4, pr * 0.22, 0, Math.PI * 2); ctx.fill();
      ctx.restore();
    }
    // ceño: un parpado inclinado tapa la parte de arriba hacia adentro
    if (sm.ceno > 0.05) {
      ctx.fillStyle = "#000";
      const dentro = lado < 0 ? x0 + w : x0, fuera = lado < 0 ? x0 : x0 + w;
      ctx.beginPath();
      ctx.moveTo(fuera, y0 - 4);
      ctx.lineTo(dentro, y0 - 4);
      ctx.lineTo(dentro, y0 + alto * 0.55 * sm.ceno);
      ctx.lineTo(fuera, y0 + alto * 0.08 * sm.ceno);
      ctx.closePath(); ctx.fill();
    }
    ctx.restore();
  }

  function dibujar() {
    if (!corriendo) return;
    requestAnimationFrame(dibujar);
    const dpr = window.devicePixelRatio || 1;
    const W = lienzo.clientWidth, H = lienzo.clientHeight;
    if (lienzo.width !== Math.round(W * dpr) || lienzo.height !== Math.round(H * dpr)) {
      lienzo.width = Math.round(W * dpr); lienzo.height = Math.round(H * dpr);
    }
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.fillStyle = "#000"; ctx.fillRect(0, 0, W, H);

    const t = performance.now();
    const E = fuentes.estado(), det = fuentes.deteccion();
    const m = meta(E, det);
    const k = 0.18;
    for (const c of ["abre", "pupila", "ceno", "feliz", "mx", "my", "temblor"]) s[c] = acercar(s[c], m[c], k);
    s.color = s.color.map((v, i) => acercar(v, m.color[i], 0.1));

    // parpadeo cada 2.5 a 6 s (dormido no parpadea)
    if (!proximoParpadeo) proximoParpadeo = t + 2500 + Math.random() * 3500;
    if (t > proximoParpadeo && !m.zzz) {
      const fase = (t - proximoParpadeo) / 160;
      parpadeo = fase < 1 ? fase : fase < 2 ? 2 - fase : 0;
      if (fase >= 2) { parpadeo = 0; proximoParpadeo = t + 2500 + Math.random() * 3500; }
    }

    const horizontal = W >= H;
    const w = horizontal ? Math.min(W * 0.24, H * 0.46) : W * 0.32;
    const h = w * 1.25;
    const sep = horizontal ? W * 0.17 : W * 0.21;
    const cy = H / 2 + (s.temblor > 0.3 ? Math.sin(t / 25) * 3 * s.temblor : 0);
    ojo(W / 2 - sep, cy, w, h, -1, s, t);
    ojo(W / 2 + sep, cy, w, h, 1, s, t);

    if (m.zzz) {
      ctx.fillStyle = "rgba(143,200,230,0.8)";
      for (let i = 0; i < 3; i++) {
        const f = ((t / 1400) + i / 3) % 1;
        ctx.globalAlpha = 1 - f;
        ctx.font = `700 ${Math.round(w * (0.18 + i * 0.05))}px ui-rounded, system-ui, sans-serif`;
        ctx.fillText("z", W / 2 + sep + w * 0.45 + f * w * 0.35, cy - h * 0.12 - f * h * 0.38);
      }
      ctx.globalAlpha = 1;
    }
    if (E && E.modo === "paro") {
      ctx.fillStyle = "rgba(255,255,255,0.35)";
      ctx.font = `600 ${Math.round(Math.max(12, H * 0.035))}px system-ui, sans-serif`;
      ctx.textAlign = "center";
      ctx.fillText("en paro", W / 2, H - Math.max(18, H * 0.05));
      ctx.textAlign = "left";
    }
  }

  // salir: mantener el dedo 2 s
  let toque = 0;
  function abajo() { toque = setTimeout(cerrar, 2000); mostrarAviso("Sigue presionando para salir…"); }
  function arriba() { clearTimeout(toque); }

  function mostrarAviso(texto) {
    aviso.textContent = texto; aviso.style.opacity = 1;
    clearTimeout(aviso._t); aviso._t = setTimeout(() => aviso.style.opacity = 0, 2200);
  }

  let alCerrar = null;
  function abrir(f) {
    fuentes = f; alCerrar = f.alCerrar || null;
    if (!lienzo) {
      lienzo = document.createElement("canvas");
      lienzo.id = "cara-lienzo";
      Object.assign(lienzo.style, {position: "fixed", inset: "0", width: "100vw", height: "100vh", zIndex: 50, background: "#000",
        touchAction: "none", cursor: "none"});
      aviso = document.createElement("div");
      Object.assign(aviso.style, {position: "fixed", left: "50%", bottom: "8vh", transform: "translateX(-50%)", zIndex: 51,
        color: "rgba(255,255,255,.75)", font: "500 15px system-ui, sans-serif", transition: "opacity .4s", pointerEvents: "none",
        background: "rgba(255,255,255,.08)", padding: ".4rem .8rem", borderRadius: "99px"});
      lienzo.addEventListener("pointerdown", abajo);
      ["pointerup", "pointercancel", "pointerleave"].forEach(ev => lienzo.addEventListener(ev, arriba));
      ctx = lienzo.getContext("2d");
    }
    document.body.append(lienzo, aviso);
    corriendo = true;
    try { document.documentElement.requestFullscreen && document.documentElement.requestFullscreen().catch(() => {}); } catch (e) {}
    mostrarAviso("Para salir, mantén el dedo 2 segundos");
    requestAnimationFrame(dibujar);
  }

  function cerrar() {
    if (!corriendo) return;
    corriendo = false;
    lienzo.remove(); aviso.remove();
    try { document.fullscreenElement && document.exitFullscreen(); } catch (e) {}
    if (alCerrar) alCerrar();
  }

  return {abrir, cerrar, abierta: () => corriendo};
})();
window.Cara = Cara;
