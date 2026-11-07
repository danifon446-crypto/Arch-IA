/* control.js  Control del perro desde otro celular o el PC.
   * Cruceta: mientras mantienes presionado camina; al soltar se queda quieto.
   * Trucos: sentarse, saludar, cola...
   * Ordenes escritas o habladas: "siéntate", "ve a la izquierda", "quieto"...
   En el PC tambien sirven las flechas o W A S D (mantener), espacio = quieto.

   Uso: Control.montar(elementoContenedor)
*/
const Control = (() => {
  const TRUCOS = [["Sentarse", "sentarse"], ["Pararse", "pararse"], ["Acostarse", "acostarse"], ["Saludar", "saludar"],
                  ["Cola", "cola"], ["Ladrar", "ladrar"], ["Feliz", "feliz"], ["Enojado", "enojado"]];
  let msgEl = null;

  const post = async (url, cuerpo) => {
    try {
      const r = await fetch(url, {method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify(cuerpo)});
      if (r.status === 401) { location.href = "/entrar?siguiente=" + location.pathname; return {ok: false}; }
      return await r.json();
    } catch (e) { return {ok: false, msg: "Sin conexión con Arché."}; }
  };
  const aviso = (t, bien) => { if (!msgEl) return; msgEl.textContent = t || ""; msgEl.dataset.bien = bien ? "1" : ""; };

  async function hacer(accion) {
    const r = await post("/api/probar", {accion});
    aviso(r.ok ? "" : (r.msg || "No se pudo."), r.ok);
    return r.ok;
  }
  async function ordenar(texto) {
    if (!texto.trim()) return;
    aviso("…");
    const r = await post("/api/orden", {texto});
    aviso(r.msg || "", r.ok);
  }

  // ----- cruceta: mantener = caminar, soltar = quieto
  let moviendo = null;
  function empezar(accion) { if (moviendo === accion) return; moviendo = accion; hacer(accion); }
  function soltar() { if (!moviendo) return; moviendo = null; hacer("quieto"); }

  const CSS = `
  .ctl { --c-bg: var(--capa, #1d2026); --c-bg2: var(--capa2, #2a2f37); --c-txt: var(--txt, #e8eaed); --c-sub: var(--sub, #9aa3ad); --c-ac: var(--ambar, #F2B544); }
  .ctl-fila { display:flex; flex-wrap:wrap; gap: 1rem; align-items: center; justify-content:center; }
  .ctl-cruz { display:grid; grid-template-columns: repeat(3, 3.6rem); grid-template-rows: repeat(3, 3.6rem); gap:.35rem; }
  .ctl-cruz button, .ctl-trucos button { border:0; border-radius:12px; background:var(--c-bg2); color:var(--c-txt); font:600 1rem system-ui, sans-serif;
    touch-action:none; -webkit-user-select:none; user-select:none; cursor:pointer; }
  .ctl-cruz button { font-size:1.5rem; }
  .ctl-cruz button.activo, .ctl-cruz button:active { background:var(--c-ac); color:#1b1306; }
  .ctl-cruz .q { font-size:.75rem; }
  .ctl-trucos { flex: 1 1 15rem; min-width:0; display:grid; grid-template-columns: repeat(auto-fit, minmax(6.4rem, 1fr)); gap:.35rem; }
  .ctl-trucos button { padding:.62rem .4rem; font-size:.92rem; }
  .ctl-trucos button:active { background:var(--c-ac); color:#1b1306; }
  .ctl-orden { display:flex; gap:.4rem; margin-top:.8rem; }
  .ctl-orden input { flex:1; min-width:0; font:inherit; font-size:1rem; padding:.7rem .8rem; border-radius:12px; border:0; background:var(--c-bg2); color:var(--c-txt); }
  .ctl-orden button { border:0; border-radius:12px; padding:0 1rem; font:600 1rem system-ui, sans-serif; background:var(--c-ac); color:#1b1306; cursor:pointer; }
  .ctl-orden button.mic { background:var(--c-bg2); color:var(--c-txt); font-size:1.2rem; padding:0 .85rem; }
  .ctl-orden button.mic.oyendo { background:#E5484D; color:#fff; }
  .ctl-msg { min-height:1.2em; font-size:.88rem; color:var(--c-ac); margin-top:.5rem; }
  .ctl-msg[data-bien="1"] { color:#46C08A; }
  .ctl-ayuda { color:var(--c-sub); font-size:.8rem; margin-top:.35rem; }
  @media (max-width: 380px) { .ctl-cruz { grid-template-columns: repeat(3, 3.1rem); grid-template-rows: repeat(3, 3.1rem); } }`;

  function montar(cont) {
    if (!document.getElementById("ctl-css")) {
      const st = document.createElement("style"); st.id = "ctl-css"; st.textContent = CSS; document.head.appendChild(st);
    }
    cont.classList.add("ctl");
    cont.innerHTML = `
      <div class="ctl-fila">
        <div class="ctl-cruz">
          <span></span><button data-m="avanzar" aria-label="Adelante">▲</button><span></span>
          <button data-m="izquierda" aria-label="Izquierda">◀</button><button class="q" data-q aria-label="Quieto">quieto</button><button data-m="derecha" aria-label="Derecha">▶</button>
          <span></span><button data-m="retroceder" aria-label="Atrás">▼</button><span></span>
        </div>
        <div class="ctl-trucos">${TRUCOS.map(([n, a]) => `<button data-t="${a}">${n}</button>`).join("")}</div>
      </div>
      <div class="ctl-orden">
        <input type="text" placeholder="Escribe una orden: siéntate, saluda…" enterkeyhint="send" autocomplete="off" aria-label="Orden">
        <button class="mic" type="button" aria-label="Decir la orden" hidden>🎤</button>
        <button class="env" type="button">Enviar</button>
      </div>
      <div class="ctl-msg" role="status"></div>
      <div class="ctl-ayuda">Mantén presionada una flecha para caminar; al soltar se queda quieto. Funciona en modo Manual.</div>`;
    msgEl = cont.querySelector(".ctl-msg");

    cont.querySelectorAll("[data-m]").forEach(b => {
      b.addEventListener("pointerdown", e => { e.preventDefault(); b.setPointerCapture && b.setPointerCapture(e.pointerId); b.classList.add("activo"); empezar(b.dataset.m); });
      ["pointerup", "pointercancel", "lostpointercapture"].forEach(ev => b.addEventListener(ev, () => { b.classList.remove("activo"); soltar(); }));
      b.addEventListener("contextmenu", e => e.preventDefault());
    });
    cont.querySelector("[data-q]").addEventListener("click", () => { moviendo = null; hacer("quieto"); });
    cont.querySelectorAll("[data-t]").forEach(b => b.addEventListener("click", () => hacer(b.dataset.t)));

    const input = cont.querySelector("input");
    const enviar = () => { ordenar(input.value); input.value = ""; };
    cont.querySelector(".env").addEventListener("click", enviar);
    input.addEventListener("keydown", e => { if (e.key === "Enter") enviar(); });

    // voz (Safari iOS 14.5+ y Chrome)
    const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
    const mic = cont.querySelector(".mic");
    if (SR) {
      mic.hidden = false;
      let rec = null;
      mic.addEventListener("click", () => {
        if (rec) { rec.stop(); return; }
        rec = new SR(); rec.lang = "es-CO"; rec.interimResults = false; rec.maxAlternatives = 1;
        mic.classList.add("oyendo"); aviso("Te escucho…");
        rec.onresult = e => { const t = e.results[0][0].transcript; input.value = t; ordenar(t); input.value = ""; };
        rec.onerror = e => aviso(e.error === "not-allowed" ? "Permite el micrófono para dar órdenes con la voz." : "No te entendí, intenta otra vez.");
        rec.onend = () => { mic.classList.remove("oyendo"); rec = null; };
        try { rec.start(); } catch (e) { mic.classList.remove("oyendo"); rec = null; }
      });
    }
  }

  // teclado (PC): flechas / WASD mantener = caminar
  const TECLAS = {ArrowUp: "avanzar", w: "avanzar", ArrowDown: "retroceder", s: "retroceder", ArrowLeft: "izquierda", a: "izquierda", ArrowRight: "derecha", d: "derecha"};
  document.addEventListener("keydown", e => {
    if (e.target && /INPUT|TEXTAREA|SELECT/.test(e.target.tagName)) return;
    const acc = TECLAS[e.key] || TECLAS[(e.key || "").toLowerCase()];
    if (acc) { e.preventDefault(); if (!e.repeat) empezar(acc); }
    else if (e.key === " ") { e.preventDefault(); moviendo = null; hacer("quieto"); }
  });
  document.addEventListener("keyup", e => {
    const acc = TECLAS[e.key] || TECLAS[(e.key || "").toLowerCase()];
    if (acc && moviendo === acc) soltar();
  });
  window.addEventListener("blur", soltar);           // si cambias de ventana mientras camina, se detiene

  return {montar, hacer, ordenar};
})();
window.Control = Control;
