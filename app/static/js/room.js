/*
 * Sala virtual: sinalização WebRTC via WebSocket.
 * - O médico é sempre o iniciador (cria a oferta) quando os dois participantes estão na sala.
 * - Os estados exibidos refletem os eventos reais do RTCPeerConnection; nada é simulado.
 */
(function () {
  "use strict";

  const cfg = JSON.parse(document.getElementById("room-config").textContent);
  const CONNECT_TIMEOUT_MS = 25000;

  const $ = (id) => document.getElementById(id);
  const els = {
    signal: $("st-signal"), peer: $("st-peer"), pc: $("st-pc"), ice: $("st-ice"),
    cam: $("st-cam"), mic: $("st-mic"), warning: $("media-warning"),
    localVideo: $("local-video"), remoteVideo: $("remote-video"),
    remotePlaceholder: $("remote-placeholder"), remoteLabel: $("remote-media-label"),
    btnCam: $("btn-cam"), btnMic: $("btn-mic"), btnRetry: $("btn-retry"), btnHangup: $("btn-hangup"),
    chatLog: $("chat-log"), chatForm: $("chat-form"), chatInput: $("chat-input"), chatSend: $("chat-send"),
    eventLog: $("event-log"),
  };

  let ws = null;
  let pc = null;
  let dc = null;
  let localStream = null;
  let isInitiator = false;
  let pendingCandidates = [];
  let connectTimer = null;
  let leaving = false;
  let wsRetry = 0;

  const PC_LABELS = {
    new: ["nova", "idle"], connecting: ["conectando…", "warn"], connected: ["conectada", "ok"],
    disconnected: ["desconectada", "warn"], failed: ["falhou", "err"], closed: ["encerrada", "idle"],
  };
  const ICE_LABELS = {
    new: "novo", checking: "verificando candidatos…", connected: "conectado", completed: "concluído",
    failed: "falhou", disconnected: "desconectado", closed: "encerrado",
  };

  function setStatus(el, text, kind) {
    el.textContent = text;
    el.className = "st st-" + kind;
  }

  function logEvent(text) {
    const li = document.createElement("li");
    li.textContent = new Date().toLocaleTimeString("pt-BR") + " — " + text;
    els.eventLog.prepend(li);
    while (els.eventLog.children.length > 40) els.eventLog.lastChild.remove();
  }

  function showWarning(text) {
    els.warning.textContent = text;
    els.warning.hidden = !text;
  }

  function send(msg) {
    if (ws && ws.readyState === WebSocket.OPEN) ws.send(JSON.stringify(msg));
  }

  // ---------- Mídia local ----------
  function describeMediaError(err) {
    switch (err && err.name) {
      case "NotAllowedError": return "permissão negada";
      case "NotFoundError": return "dispositivo não encontrado";
      case "NotReadableError": return "em uso por outro aplicativo";
      case "OverconstrainedError": return "configuração não suportada";
      case "SecurityError": return "bloqueado pelo navegador";
      default: return "indisponível";
    }
  }

  async function initMedia() {
    if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
      setStatus(els.cam, "indisponível (requer HTTPS ou localhost)", "err");
      setStatus(els.mic, "indisponível (requer HTTPS ou localhost)", "err");
      logEvent("API de mídia indisponível neste contexto.");
      return;
    }
    const attempts = [{ video: true, audio: true }, { audio: true }, { video: true }];
    let lastError = null;
    for (const constraints of attempts) {
      try {
        localStream = await navigator.mediaDevices.getUserMedia(constraints);
        break;
      } catch (err) {
        lastError = err;
      }
    }
    if (!localStream) {
      const reason = describeMediaError(lastError);
      setStatus(els.cam, reason, "err");
      setStatus(els.mic, reason, "err");
      logEvent("Não foi possível acessar câmera/microfone: " + reason + ". A conexão seguirá sem mídia local.");
      return;
    }
    els.localVideo.srcObject = localStream;
    const v = localStream.getVideoTracks()[0];
    const a = localStream.getAudioTracks()[0];
    setStatus(els.cam, v ? "ativa" : "indisponível", v ? "ok" : "err");
    setStatus(els.mic, a ? "ativo" : "indisponível", a ? "ok" : "err");
    els.btnCam.disabled = !v;
    els.btnMic.disabled = !a;
    logEvent("Mídia local obtida: " + [v && "câmera", a && "microfone"].filter(Boolean).join(" e ") + ".");
  }

  els.btnCam.addEventListener("click", () => {
    const t = localStream && localStream.getVideoTracks()[0];
    if (!t) return;
    t.enabled = !t.enabled;
    setStatus(els.cam, t.enabled ? "ativa" : "desligada", t.enabled ? "ok" : "warn");
    els.btnCam.textContent = t.enabled ? "Desligar câmera" : "Ligar câmera";
  });

  els.btnMic.addEventListener("click", () => {
    const t = localStream && localStream.getAudioTracks()[0];
    if (!t) return;
    t.enabled = !t.enabled;
    setStatus(els.mic, t.enabled ? "ativo" : "silenciado", t.enabled ? "ok" : "warn");
    els.btnMic.textContent = t.enabled ? "Silenciar microfone" : "Ativar microfone";
  });

  // ---------- RTCPeerConnection ----------
  function updateRemoteLabel() {
    const stream = els.remoteVideo.srcObject;
    if (!stream) { els.remoteLabel.textContent = "(sem mídia)"; return; }
    const kinds = [];
    if (stream.getVideoTracks().length) kinds.push("vídeo");
    if (stream.getAudioTracks().length) kinds.push("áudio");
    els.remoteLabel.textContent = kinds.length ? "(recebendo " + kinds.join(" e ") + ")" : "(sem mídia)";
  }

  function closePeer() {
    clearTimeout(connectTimer);
    if (dc) { try { dc.close(); } catch (e) { /* ignorar */ } dc = null; }
    if (pc) {
      pc.onicecandidate = pc.ontrack = pc.onconnectionstatechange = pc.oniceconnectionstatechange = pc.ondatachannel = null;
      pc.close();
      pc = null;
    }
    pendingCandidates = [];
    els.remoteVideo.srcObject = null;
    els.remotePlaceholder.hidden = false;
    els.remotePlaceholder.textContent = "Aguardando o outro participante…";
    updateRemoteLabel();
    setChatEnabled(false);
    setStatus(els.pc, "não iniciada", "idle");
    setStatus(els.ice, "—", "idle");
  }

  function createPeer() {
    closePeer();
    if (typeof RTCPeerConnection === "undefined") {
      setStatus(els.pc, "não suportada pelo navegador", "err");
      showWarning("Este navegador não suporta WebRTC. Teste em uma versão atual do Chrome, Edge ou Firefox.");
      return null;
    }
    pc = new RTCPeerConnection({ iceServers: cfg.iceServers || [] });

    if (localStream) localStream.getTracks().forEach((t) => pc.addTrack(t, localStream));
    if (isInitiator) {
      // Garante que a oferta inclua áudio e vídeo para receber mídia mesmo sem mídia local.
      const kinds = new Set(localStream ? localStream.getTracks().map((t) => t.kind) : []);
      ["audio", "video"].forEach((k) => { if (!kinds.has(k)) pc.addTransceiver(k, { direction: "recvonly" }); });
      setupDataChannel(pc.createDataChannel("chat"));
    }

    pc.onicecandidate = (e) => { if (e.candidate) send({ type: "ice", candidate: e.candidate.toJSON() }); };
    pc.ontrack = (e) => {
      let stream = els.remoteVideo.srcObject;
      if (!stream) { stream = new MediaStream(); els.remoteVideo.srcObject = stream; }
      if (!stream.getTracks().includes(e.track)) stream.addTrack(e.track);
      e.track.onunmute = updateRemoteLabel;
      if (e.track.kind === "video") els.remotePlaceholder.hidden = true;
      updateRemoteLabel();
    };
    pc.ondatachannel = (e) => setupDataChannel(e.channel);
    pc.oniceconnectionstatechange = () => {
      const s = pc.iceConnectionState;
      setStatus(els.ice, ICE_LABELS[s] || s, s === "connected" || s === "completed" ? "ok" : s === "failed" ? "err" : "warn");
    };
    pc.onconnectionstatechange = () => {
      const s = pc.connectionState;
      const [label, kind] = PC_LABELS[s] || [s, "warn"];
      setStatus(els.pc, label, kind);
      logEvent("Conexão WebRTC: " + label + ".");
      if (s === "connected") {
        clearTimeout(connectTimer);
        showWarning("");
        const remote = els.remoteVideo.srcObject;
        if (!remote || !remote.getVideoTracks().length) {
          els.remotePlaceholder.textContent = "Conectado — o outro participante não está enviando vídeo.";
        }
        if (!remote || !remote.getTracks().length) {
          logEvent("Conexão estabelecida, mas o outro participante não está enviando mídia.");
        }
      } else if (s === "failed") {
        reportConnectionProblem();
      }
    };
    setStatus(els.pc, "nova", "idle");
    return pc;
  }

  function reportConnectionProblem() {
    showWarning(
      "Não foi possível estabelecer a conexão de mídia neste ambiente. " +
      "Teste com navegadores atualizados (Chrome, Edge ou Firefox), acessando por localhost ou HTTPS, " +
      "e verifique se câmera e microfone estão liberados. Em redes diferentes ou com firewall, " +
      "pode ser necessário configurar servidores STUN/TURN (variável STUN_URLS)."
    );
  }

  function startConnectTimer() {
    clearTimeout(connectTimer);
    connectTimer = setTimeout(() => {
      if (pc && pc.connectionState !== "connected") {
        logEvent("Tempo limite atingido sem conexão WebRTC.");
        reportConnectionProblem();
      }
    }, CONNECT_TIMEOUT_MS);
  }

  async function flushCandidates() {
    const list = pendingCandidates;
    pendingCandidates = [];
    for (const c of list) {
      try { await pc.addIceCandidate(c); } catch (e) { logEvent("Candidato ICE inválido ignorado."); }
    }
  }

  async function handleSignal(msg) {
    switch (msg.type) {
      case "joined":
        setStatus(els.signal, "conectado", "ok");
        logEvent("Entrou na sala de sinalização.");
        if (msg.present.length < 2) setStatus(els.peer, "ausente — aguardando", "warn");
        break;
      case "ready":
        isInitiator = !!msg.initiator;
        setStatus(els.peer, "presente", "ok");
        logEvent("Outro participante presente. " + (isInitiator ? "Enviando oferta…" : "Aguardando oferta…"));
        if (!createPeer()) return;
        startConnectTimer();
        if (isInitiator) {
          const offer = await pc.createOffer();
          await pc.setLocalDescription(offer);
          send({ type: "offer", sdp: pc.localDescription.toJSON() });
          logEvent("Oferta (SDP) enviada.");
        }
        break;
      case "offer":
        if (!pc) { createPeer(); startConnectTimer(); }
        logEvent("Oferta recebida.");
        await pc.setRemoteDescription(msg.sdp);
        await flushCandidates();
        await pc.setLocalDescription(await pc.createAnswer());
        send({ type: "answer", sdp: pc.localDescription.toJSON() });
        logEvent("Resposta (SDP) enviada.");
        break;
      case "answer":
        if (!pc) return;
        logEvent("Resposta recebida.");
        await pc.setRemoteDescription(msg.sdp);
        await flushCandidates();
        break;
      case "ice":
        if (!msg.candidate) return;
        if (pc && pc.remoteDescription) {
          try { await pc.addIceCandidate(msg.candidate); } catch (e) { logEvent("Candidato ICE inválido ignorado."); }
        } else {
          pendingCandidates.push(msg.candidate);
        }
        break;
      case "peer-left":
      case "hangup":
        setStatus(els.peer, "saiu da sala", "warn");
        logEvent("O outro participante saiu.");
        closePeer();
        showWarning("");
        break;
      case "replaced":
        leaving = true;
        logEvent("Esta sala foi aberta em outra aba/janela com a mesma conta.");
        showWarning("Esta sala foi aberta em outra aba ou janela com a mesma conta. Esta conexão foi encerrada.");
        closePeer();
        break;
      case "error":
        logEvent("Servidor: " + msg.message);
        break;
    }
  }

  // ---------- Canal de dados (chat) ----------
  function setChatEnabled(on) {
    els.chatInput.disabled = !on;
    els.chatSend.disabled = !on;
  }

  function appendChat(who, text) {
    if (els.chatLog.querySelector(".muted")) els.chatLog.innerHTML = "";
    const p = document.createElement("p");
    const b = document.createElement("strong");
    b.textContent = who + ": ";
    p.append(b, document.createTextNode(text));
    els.chatLog.append(p);
    els.chatLog.scrollTop = els.chatLog.scrollHeight;
  }

  function setupDataChannel(channel) {
    dc = channel;
    dc.onopen = () => { setChatEnabled(true); logEvent("Canal de dados P2P aberto."); };
    dc.onclose = () => setChatEnabled(false);
    dc.onmessage = (e) => appendChat(cfg.role === "medico" ? "Paciente" : "Médico(a)", String(e.data).slice(0, 500));
  }

  els.chatForm.addEventListener("submit", (e) => {
    e.preventDefault();
    const text = els.chatInput.value.trim();
    if (!text || !dc || dc.readyState !== "open") return;
    dc.send(text);
    appendChat("Você", text);
    els.chatInput.value = "";
  });

  // ---------- WebSocket ----------
  function connectSignaling() {
    const proto = location.protocol === "https:" ? "wss://" : "ws://";
    setStatus(els.signal, "conectando…", "warn");
    ws = new WebSocket(proto + location.host + cfg.wsPath);
    ws.onopen = () => { wsRetry = 0; };
    ws.onmessage = (e) => {
      let msg;
      try { msg = JSON.parse(e.data); } catch (err) { return; }
      handleSignal(msg).catch((err) => {
        logEvent("Erro ao processar sinalização: " + (err && err.message ? err.message : err));
        reportConnectionProblem();
      });
    };
    ws.onclose = (e) => {
      setStatus(els.peer, "desconhecido", "idle");
      if (e.code === 4403 || e.code === 1008) {
        setStatus(els.signal, "acesso negado", "err");
        showWarning("Acesso à sala negado. Entre com a conta do paciente ou do médico vinculados à consulta.");
        return;
      }
      setStatus(els.signal, "desconectado", "err");
      if (leaving) return;
      closePeer();
      if (wsRetry < 5) {
        wsRetry += 1;
        logEvent("Sinalização desconectada. Tentando reconectar (" + wsRetry + "/5)…");
        setTimeout(connectSignaling, 1500 * wsRetry);
      } else {
        showWarning("Não foi possível manter a conexão com o servidor de sinalização. Recarregue a página.");
      }
    };
  }

  els.btnRetry.addEventListener("click", () => {
    logEvent("Reconexão solicitada.");
    leaving = false;
    wsRetry = 0;
    showWarning("");
    closePeer();
    if (ws && ws.readyState <= WebSocket.OPEN) {
      ws.onclose = null;
      ws.close();
    }
    connectSignaling();
  });

  els.btnHangup.addEventListener("click", () => {
    leaving = true;
    send({ type: "hangup" });
    closePeer();
    if (ws) ws.close();
    if (localStream) localStream.getTracks().forEach((t) => t.stop());
    setStatus(els.signal, "encerrado", "idle");
    setStatus(els.cam, "desligada", "idle");
    setStatus(els.mic, "desligado", "idle");
    els.btnCam.disabled = els.btnMic.disabled = true;
    logEvent("Você saiu da sala.");
    location.href = "/consultas/" + cfg.appointmentId;
  });

  window.addEventListener("beforeunload", () => { leaving = true; if (ws) ws.close(); });

  (async function start() {
    await initMedia();
    connectSignaling();
  })();
})();
