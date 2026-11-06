/* rtc.js  Video en vivo del celular al panel por WebRTC (como una videollamada).

   Por que: mandar foto por foto (JPEG) no llega a 60 fps nitidos. Con WebRTC el chip de video del
   celular comprime en H.264 y el video va DIRECTO del celular al panel (el PC solo hace de "cartero"
   para presentarlos). Arche sigue analizando con las fotos chicas de siempre.

   Emisor (el celular que es la camara):   RTC.emitir(flujo, {bitrate, fps}), RTC.dejarDeEmitir()
   Visor (el panel, en el PC u otro cel):  RTC.ver(alRecibir(stream|null), alEstado(texto))
*/
const RTC = (() => {
  // STUN solo sirve cuando el celular esta en otra red (tunel). En la misma WiFi o Tailscale no hace falta.
  const ICE = [{urls: "stun:stun.l.google.com:19302"}];
  const MAX_VISORES = 3;
  const espera = ms => new Promise(r => setTimeout(r, ms));
  const nuevoId = () => Math.random().toString(36).slice(2, 10) + Date.now().toString(36).slice(-4);

  async function post(url, cuerpo) {
    const r = await fetch(url, {method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify(cuerpo || {})});
    if (!r.ok) throw new Error("http " + r.status);
    return r.json();
  }

  async function buzon(yo) {               // espera mensajes (hasta ~15 s)
    const r = await fetch(`/rtc/buzon?yo=${encodeURIComponent(yo)}&t=${Date.now()}`, {cache: "no-store"});
    if (!r.ok) throw new Error("http " + r.status);
    return (await r.json()).mensajes || [];
  }

  function esperarIce(pc, ms = 2500) {     // se manda todo junto (sin "trickle"): mas simple y en la WiFi es instantaneo
    if (pc.iceGatheringState === "complete") return Promise.resolve();
    return new Promise(res => {
      const fin = () => { pc.removeEventListener("icegatheringstatechange", rev); res(); };
      const rev = () => { if (pc.iceGatheringState === "complete") fin(); };
      pc.addEventListener("icegatheringstatechange", rev);
      setTimeout(fin, ms);
    });
  }

  function preferirH264(transceptor) {     // H.264 lo comprime el chip del celular: menos calor, mas fps
    try {
      const caps = RTCRtpSender.getCapabilities && RTCRtpSender.getCapabilities("video");
      if (!caps || !transceptor.setCodecPreferences) return;
      const h264 = caps.codecs.filter(c => /h264/i.test(c.mimeType));
      const resto = caps.codecs.filter(c => !/h264/i.test(c.mimeType));
      if (h264.length) transceptor.setCodecPreferences(h264.concat(resto));
    } catch (e) {}
  }

  // WebRTC arranca con poco bitrate y sube despacio (~20 s hasta 720p60). En la WiFi se puede empezar alto:
  // Chrome/Android entiende estos parametros; Safari los ignora sin problema.
  function arranqueRapido(sdp, bitrate) {
    const ini = Math.round(Math.min(bitrate, 4e6) / 1000), min = Math.round(Math.min(bitrate, 4e6) / 2500);
    return sdp.replace(/^(a=fmtp:\d+ [^\r\n]*)$/gm, l =>
      /x-google-start-bitrate/.test(l) ? l : `${l};x-google-start-bitrate=${ini};x-google-min-bitrate=${min}`);
  }

  async function ajustarCalidad(sender, bitrate, fps) {
    try {
      const p = sender.getParameters();
      if (!p.encodings || !p.encodings.length) p.encodings = [{}];
      p.encodings[0].maxBitrate = bitrate;
      p.encodings[0].maxFramerate = fps;
      // con fluidez alta se protege el fps: si la red aprieta, baja un poco la nitidez pero no se traba
      p.degradationPreference = fps >= 60 ? "maintain-framerate" : "balanced";
      await sender.setParameters(p);
    } catch (e) {}
  }

  // ================================================================ emisor
  let em = null;      // {id, flujo, opciones, pcs: Map(visor -> {pc, sender}), activo}

  async function emitir(flujo, opciones) {
    dejarDeEmitir();
    em = {id: "cam-" + nuevoId(), flujo, opciones: Object.assign({bitrate: 6e6, fps: 60}, opciones || {}), pcs: new Map(), activo: true};
    const yo = em;
    try { await post("/rtc/emisor", {yo: yo.id}); } catch (e) {}
    while (yo.activo) {
      let mensajes = [];
      try { mensajes = await buzon(yo.id); }
      catch (e) { await espera(1500); try { await post("/rtc/emisor", {yo: yo.id}); } catch (e2) {} continue; }
      for (const m of mensajes) {
        if (!yo.activo) break;
        if (m.tipo === "visor") atenderVisor(yo, m.de).catch(() => cerrarVisor(yo, m.de));
        else if (m.tipo === "answer" && yo.pcs.has(m.de)) {
          const v = yo.pcs.get(m.de);
          try { await v.pc.setRemoteDescription({type: "answer", sdp: arranqueRapido(m.sdp, yo.opciones.bitrate)}); }
          catch (e) {
            try { await v.pc.setRemoteDescription({type: "answer", sdp: m.sdp}); } catch (e2) { cerrarVisor(yo, m.de); }
          }
        }
      }
    }
  }

  async function atenderVisor(yo, visor) {
    cerrarVisor(yo, visor);
    if (yo.pcs.size >= MAX_VISORES) cerrarVisor(yo, yo.pcs.keys().next().value);   // el mas viejo
    const pc = new RTCPeerConnection({iceServers: ICE});
    const pista = yo.flujo.getVideoTracks()[0];
    if (!pista) return;
    try { pista.contentHint = "motion"; } catch (e) {}
    const tr = pc.addTransceiver(pista, {direction: "sendonly", streams: [yo.flujo]});
    preferirH264(tr);
    yo.pcs.set(visor, {pc, sender: tr.sender});
    pc.onconnectionstatechange = () => {
      if (pc.connectionState === "connected") ajustarCalidad(tr.sender, yo.opciones.bitrate, yo.opciones.fps);
      if (["failed", "closed"].includes(pc.connectionState)) cerrarVisor(yo, visor, pc);
    };
    await ajustarCalidad(tr.sender, yo.opciones.bitrate, yo.opciones.fps);
    await pc.setLocalDescription(await pc.createOffer());
    await esperarIce(pc);
    if (!yo.activo || yo.pcs.get(visor)?.pc !== pc) return;
    await post("/rtc/enviar", {para: visor, de: yo.id, tipo: "offer", sdp: pc.localDescription.sdp});
  }

  function cerrarVisor(yo, visor, soloEste) {
    const v = yo.pcs.get(visor);
    if (!v || (soloEste && v.pc !== soloEste)) return;
    try { v.pc.close(); } catch (e) {}
    yo.pcs.delete(visor);
  }

  function dejarDeEmitir() {
    if (!em) return;
    em.activo = false;
    for (const k of [...em.pcs.keys()]) cerrarVisor(em, k);
    em = null;
  }

  function opciones(o) {                      // cambiar bitrate/fps en caliente
    if (!em) return;
    Object.assign(em.opciones, o);
    for (const v of em.pcs.values()) ajustarCalidad(v.sender, em.opciones.bitrate, em.opciones.fps);
  }

  function visoresConectados() {
    if (!em) return 0;
    let n = 0;
    for (const v of em.pcs.values()) if (v.pc.connectionState === "connected") n++;
    return n;
  }

  async function estadoEmisor() {             // como esta saliendo el video (para mostrarlo en Ojos)
    if (!em) return null;
    for (const v of em.pcs.values()) {
      if (v.pc.connectionState !== "connected") continue;
      try {
        const st = await v.pc.getStats();
        for (const r of st.values()) if (r.type === "outbound-rtp" && r.kind === "video")
          return {fps: r.framesPerSecond || 0, ancho: r.frameWidth || 0, alto: r.frameHeight || 0,
                  limite: r.qualityLimitationReason || "none", codificador: r.encoderImplementation || "",
                  kbps: r.targetBitrate ? Math.round(r.targetBitrate / 1000) : null};
      } catch (e) {}
    }
    return null;
  }

  // ================================================================ visor
  let viendo = null;

  function ver(alRecibir, alEstado) {
    dejarDeVer();
    const yo = {id: "vis-" + nuevoId(), activo: true, pc: null};
    viendo = yo;
    const estado = t => { try { alEstado && alEstado(t); } catch (e) {} };
    (async () => {
      while (yo.activo) {
        let r;
        try { r = await post("/rtc/pedir", {yo: yo.id}); } catch (e) { r = {ok: false}; }
        if (!r.ok) { estado("sin cámara"); await espera(2500); continue; }
        estado("conectando");
        // espera la oferta del celular
        let oferta = null;
        const hasta = Date.now() + 9000;
        while (yo.activo && !oferta && Date.now() < hasta) {
          try { oferta = (await buzon(yo.id)).filter(m => m.tipo === "offer").pop() || null; }
          catch (e) { await espera(800); }
        }
        if (!oferta || !yo.activo) { await espera(1000); continue; }

        const pc = new RTCPeerConnection({iceServers: ICE});
        yo.pc = pc;
        pc.ontrack = e => {
          // un colchón chiquito (60 ms) absorbe los saltos de la WiFi: el video se ve parejo, sin tirones
          try { if ("jitterBufferTarget" in e.receiver) e.receiver.jitterBufferTarget = 60; else e.receiver.playoutDelayHint = 0.06; } catch (x) {}
          alRecibir(e.streams && e.streams[0] ? e.streams[0] : new MediaStream([e.track]));
        };
        try {
          await pc.setRemoteDescription({type: "offer", sdp: oferta.sdp});
          await pc.setLocalDescription(await pc.createAnswer());
          await esperarIce(pc);
          await post("/rtc/enviar", {para: oferta.de, de: yo.id, tipo: "answer", sdp: pc.localDescription.sdp});
        } catch (e) { try { pc.close(); } catch (e2) {} await espera(1500); continue; }

        // espera a que conecte (o falle) y luego mientras siga conectado
        const t0 = Date.now();
        let conecto = false, caidaDesde = 0, cuadros = -1, quietoDesde = 0, ultRevision = 0;
        while (yo.activo) {
          const s = pc.connectionState;
          if (s === "connected") {
            conecto = true; caidaDesde = 0; estado("en vivo");
            if (Date.now() - ultRevision > 1000) {     // si dejan de llegar cuadros (apagaron la camara), se suelta rapido
              ultRevision = Date.now();
              let n = null;
              try { for (const r of (await pc.getStats()).values()) if (r.type === "inbound-rtp" && r.kind === "video") n = r.framesDecoded || 0; } catch (e) {}
              if (n !== null) {
                if (n !== cuadros) { cuadros = n; quietoDesde = 0; }
                else if (!quietoDesde) quietoDesde = Date.now();
                else if (Date.now() - quietoDesde > 2500) break;
              }
            }
          }
          else if (s === "failed" || s === "closed") break;
          else if (s === "disconnected") { if (!caidaDesde) caidaDesde = Date.now(); else if (Date.now() - caidaDesde > 4000) break; }
          else if (!conecto && Date.now() - t0 > 12000) break;
          await espera(500);
        }
        try { pc.close(); } catch (e) {}
        yo.pc = null;
        alRecibir(null);
        estado(conecto ? "se cortó" : "no conectó");
        await espera(conecto ? 800 : 4000);
      }
    })();
  }

  function dejarDeVer() {
    if (!viendo) return;
    viendo.activo = false;
    try { viendo.pc && viendo.pc.close(); } catch (e) {}
    viendo = null;
  }

  async function fpsRecibidos() {             // fps reales del video que llega (para mostrarlo)
    const pc = viendo && viendo.pc;
    if (!pc) return null;
    try {
      const st = await pc.getStats();
      for (const r of st.values()) if (r.type === "inbound-rtp" && r.kind === "video")
        return {fps: r.framesPerSecond || null, ancho: r.frameWidth || null, alto: r.frameHeight || null};
    } catch (e) {}
    return null;
  }

  return {emitir, dejarDeEmitir, opciones, visoresConectados, estadoEmisor, ver, dejarDeVer, fpsRecibidos,
          disponible: typeof RTCPeerConnection !== "undefined"};
})();

window.RTC = RTC;   // la app y el panel preguntan por window.RTC
