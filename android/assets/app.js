"use strict";
// ================= F.R.I.D.A.Y. — centro de comando remoto (celular) =================
const $ = (q) => document.querySelector(q);
const $$ = (q) => Array.from(document.querySelectorAll(q));
const ls = { get: (k, d) => { try { return localStorage.getItem(k) ?? d; } catch { return d; } }, set: (k, v) => { try { localStorage.setItem(k, v); } catch {} } };
const defaultHost = (typeof window !== "undefined" && window.location && window.location.host && !window.location.protocol.startsWith("file"))
  ? window.location.host
  : "100.110.230.55:8790";
const cfg = { host: ls.get("host", defaultHost), tok: ls.get("tok", "") };
const http = () => "http://" + cfg.host;
const st = { online: false, on: false, state: "idle", mouth: 0, pulse: 0, ws: null, voice: null, camera: null, modes: {}, stats: null,
             micOn: false, camOn: false, anexos: [], aba: "conversa", devAlvo: "auto", agendaDia: 0 };
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);
const num = (v) => (v === null || v === undefined || v === "" || isNaN(+v)) ? null : +v;

function toast(t, ms = 2200) { const e = $("#toast"); if (!e) return; e.textContent = t; e.classList.add("on"); clearTimeout(toast.t); toast.t = setTimeout(() => e.classList.remove("on"), ms); }
function vibrar(ms = 15) { try { navigator.vibrate && navigator.vibrate(ms); } catch {} }
async function api(path, opt = {}) {
  opt.headers = Object.assign({ "X-Token": cfg.tok }, opt.headers || {});
  const r = await fetch(http() + path, opt);
  if (r.status === 401) { abrirSetup("Token inválido"); throw new Error("401"); }
  return r;
}
async function apiNova(path, opt) {
  try { return await api(path, opt); }
  catch (e) { if (String(e.message) === "401" || !st.online) throw e; return new Response('{"erro":"rota ausente"}', { status: 404, headers: { "Content-Type": "application/json" } }); }
}

// ---------------- abas ----------------
const aoMudarAba = [];
function irAba(nome) {
  st.aba = nome; ls.set("aba", nome);
  $$("#tabs button").forEach((b) => b.classList.toggle("on", b.dataset.aba === nome));
  $$(".aba").forEach((s) => s.classList.toggle("on", s.id === nome));
  aoMudarAba.forEach((f) => f(nome));
  if (nome === "conversa") $("#msgs").scrollTop = 1e9;
}
window.abrirAba = irAba;
$$("#tabs button").forEach((b) => b.onclick = () => { vibrar(); irAba(b.dataset.aba); });

// Atalhos rápidos na aba Conversa
$$("[data-atalho]").forEach((btn) => {
  btn.onclick = () => {
    vibrar(20);
    const tipo = btn.dataset.atalho;
    if (tipo === "agenda") return irAba("agenda");
    if (tipo === "dev") return irAba("dev");
    const txtIn = $("#txt");
    if (!txtIn) return;
    if (tipo === "pesquisa") { txtIn.value = "pesquise na web sobre "; txtIn.focus(); }
    else if (tipo === "pdf") { txtIn.value = "crie um documento resumo_executivo.pdf com "; txtIn.focus(); }
    else if (tipo === "comp_zap") { txtIn.value = "pesquise as notícias de inteligência artificial de hoje e envie no whatsapp para "; txtIn.focus(); }
    else if (tipo === "comp_doc") { txtIn.value = "pesquise sobre arquitetura de software e crie um arquivo resumo_arq.md"; txtIn.focus(); }
  };
});

// Card Agenda no Painel leva para aba AGENDA
const cpAg = $("#cardPainelAgenda");
if (cpAg) cpAg.onclick = () => { vibrar(); irAba("agenda"); };

// ---------------- reator holográfico ----------------
const cv = $("#fx"), cx = cv.getContext("2d");
let W = 0, H = 0;
function rs() { const r = cv.getBoundingClientRect(), d = Math.min(2, devicePixelRatio || 1); W = r.width; H = r.height; cv.width = W * d; cv.height = H * d; cx.setTransform(d, 0, 0, d, 0, 0); }
addEventListener("resize", rs);
const N = 70, P = [];
for (let i = 0; i < N; i++) {
  const u = Math.random() * 2 - 1, th = Math.random() * 6.283, r = Math.cbrt(Math.random()), s = Math.sqrt(1 - u * u);
  P.push({ x: s * Math.cos(th) * r, y: u * r, z: s * Math.sin(th) * r, sp: .2 + Math.random() * .6, ph: Math.random() * 6.28 });
}
const hud = { ang: 0, spin: 1, ondas: [] };
cv.addEventListener("pointerdown", () => { hud.spin = 6; hud.ondas.push(performance.now()); vibrar(20); });
function quadro(tms) {
  requestAnimationFrame(quadro);
  if (st.aba !== "conversa" || document.hidden) return;
  if (!W) rs();
  const t = tms / 1000, dt = Math.min(.05, (tms - (quadro.u || tms)) / 1000) || .016; quadro.u = tms;
  const alvo = st.state === "speaking" ? .35 + st.mouth * 1.1 : st.state === "listening" || st.micAtivo ? .25 : st.state === "thinking" ? .18 : .06;
  st.pulse += (alvo - st.pulse) * .25;
  const spinBase = st.state === "thinking" ? 3.2 : st.state === "listening" ? 1.6 : 1;
  hud.spin += (spinBase - hud.spin) * .05; hud.ang += dt * .25 * hud.spin;
  cx.clearRect(0, 0, W, H);
  const ccx = W / 2, ccy = H / 2 - 6, R0 = Math.min(W, H) * .26, R = R0 * (1 + st.pulse * .25), pensa = st.state === "thinking";
  const g = cx.createRadialGradient(ccx, ccy, 0, ccx, ccy, R0 * 2.4);
  g.addColorStop(0, `rgba(54,214,255,${.16 + st.pulse * .22})`); g.addColorStop(1, "rgba(54,214,255,0)"); cx.fillStyle = g; cx.fillRect(0, 0, W, H);
  for (const [rr, segs, lw, cor, sp] of [[1.7, [[0, 70], [95, 150], [180, 200], [230, 330]], 2.5, "#ff8a1f", -30],
                                          [1.5, [[10, 40], [60, 62], [120, 250], [290, 340]], 1.2, "rgba(216,246,255,.8)", 45],
                                          [1.32, [[0, 120], [160, 300]], 4, "rgba(54,214,255,.25)", -22]]) {
    const Rs = R0 * rr * (1 + st.pulse * .06), rot = hud.ang * sp * Math.PI / 180;
    cx.strokeStyle = cor; cx.lineWidth = lw;
    for (const [a, b] of segs) { cx.beginPath(); cx.arc(ccx, ccy, Rs, rot + a * Math.PI / 180, rot + b * Math.PI / 180); cx.stroke(); }
  }
  const Q = [];
  for (const p of P) {
    const an = hud.ang * 4 * p.sp, ca = Math.cos(an), sa = Math.sin(an), x = p.x * ca - p.z * sa, z = p.x * sa + p.z * ca;
    const wob = 1 + st.pulse * .35 * Math.sin(t * 9 + p.ph);
    Q.push([ccx + x * R * wob, ccy + p.y * R * wob, (z + 1) / 2]);
  }
  const md = R0 * .55; cx.lineWidth = 1;
  for (let i = 0; i < N; i++) for (let j = i + 1; j < N; j++) {
    const dx = Q[i][0] - Q[j][0], dy = Q[i][1] - Q[j][1]; if (Math.abs(dx) > md || Math.abs(dy) > md) continue;
    const d = Math.hypot(dx, dy); if (d < md) { cx.strokeStyle = `rgba(54,214,255,${(1 - d / md) * (.25 + st.pulse * .5)})`; cx.beginPath(); cx.moveTo(Q[i][0], Q[i][1]); cx.lineTo(Q[j][0], Q[j][1]); cx.stroke(); }
  }
  for (let i = 0; i < N; i++) { cx.fillStyle = i % 11 === 0 ? "rgba(255,138,31,.9)" : `rgba(216,246,255,${.45 + Q[i][2] * .55})`; cx.beginPath(); cx.arc(Q[i][0], Q[i][1], 1 + Q[i][2] * 1.8 + st.pulse * 1.2, 0, 7); cx.fill(); }
  const r0 = R0 * 1.16, amp = st.state === "speaking" ? st.mouth * R0 * .5 + 3 : st.state === "listening" || st.micAtivo ? 5 : pensa ? 4 : 2;
  cx.lineWidth = 2;
  for (let i = 0; i < 60; i++) {
    const a = i / 60 * 6.283 - 1.5708, n = .5 + .5 * Math.sin(t * 11 + i * .55) * Math.cos(t * 4.3 + i * .21), l = 2 + amp * n;
    cx.strokeStyle = i % 10 === 0 ? "rgba(255,138,31,.9)" : `rgba(54,214,255,${.35 + n * .55})`;
    cx.beginPath(); cx.moveTo(ccx + Math.cos(a) * r0, ccy + Math.sin(a) * r0); cx.lineTo(ccx + Math.cos(a) * (r0 + l), ccy + Math.sin(a) * (r0 + l)); cx.stroke();
  }
  hud.ondas = hud.ondas.filter((t0) => tms - t0 < 900);
  for (const t0 of hud.ondas) { const k = (tms - t0) / 900, e = 1 - Math.pow(1 - k, 3); cx.globalAlpha = 1 - k; cx.strokeStyle = "#ff8a1f"; cx.lineWidth = 2; cx.beginPath(); cx.arc(ccx, ccy, R0 * (.5 + e * 2), 0, 7); cx.stroke(); cx.globalAlpha = 1; }
  st.mouth *= .9;
}
requestAnimationFrame(quadro);

// ---------------- estado / conexão ----------------
const ROT_ESTADO = { speaking: "FALANDO", thinking: "PROCESSANDO", listening: "OUVINDO", idle: "PRONTA" };
function status() {
  const d = $("#dot"); d.className = !st.online ? "" : (["speaking", "thinking", "listening"].includes(st.state) ? st.state : "on");
  $("#sub").textContent = !st.online ? "OFFLINE (FRIDAY LOCAL DISPONÍVEL)" : !st.on ? "EM ESPERA" : (ROT_ESTADO[st.state] || st.state.toUpperCase());
  $("#estadoTxt").textContent = !st.online ? (localOk() ? "FRIDAY LOCAL ATIVA" : "SEM CONEXÃO") : !st.on ? "EM ESPERA" : (ROT_ESTADO[st.state] || "");
  renderControles();
}
function conectar() {
  if (!cfg.tok) return abrirSetup();
  clearTimeout(conectar.t);
  const velho = st.ws; st.ws = null; try { velho && velho.close(); } catch {}
  const ws = new WebSocket(`ws://${cfg.host}/ws?t=${encodeURIComponent(cfg.tok)}`);
  st.ws = ws;
  ws.onopen = () => { st.online = true; status(); bootFim(); carregarStatus(); };
  ws.onclose = () => { if (st.ws !== ws) return; st.online = false; status(); clearTimeout(conectar.t); conectar.t = setTimeout(conectar, 2500); };
  ws.onerror = () => { try { ws.close(); } catch {} };
  ws.onmessage = (ev) => { let m; try { m = JSON.parse(ev.data); } catch { return; } receber(m); };
}
function enviar(o) { if (st.ws && st.ws.readyState === 1) { st.ws.send(JSON.stringify(o)); return true; } toast("Sem conexão com o PC"); return false; }
async function carregarStatus() {
  try {
    const r = await api("/api/status"); if (!r.ok) return;
    const d = await r.json();
    if ("voice" in d) st.voice = d.voice; if ("camera" in d) st.camera = d.camera; if ("on" in d) st.on = !!d.on;
    if (d.state) st.state = d.state; if (d.modes) st.modes = d.modes; if (d.stats) stats(d.stats);
    status();
  } catch {}
}
async function cmd(c, ok) {
  vibrar(20);
  try {
    const r = await apiNova("/api/cmd", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(c) });
    if (r.status === 404) {
      if (c.type === "friday") return enviar({ type: "ligar", on: c.on });
      if (c.type === "stop") return enviar({ type: "pare" });
      return toast("Reinicie o daemon no PC para liberar este controle", 3500);
    }
    const j = await r.json(); if (!j.ok) return toast(j.msg || "Falhou", 3000);
    if (ok) toast(ok);
  } catch (e) { if (String(e.message) !== "401") toast("Falha ao falar com o PC"); }
}

function receber(m) {
  switch (m.type) {
    case "hello": st.on = !!m.on; st.state = m.state || "idle"; if (m.modes) st.modes = m.modes;
      if ("voice" in m) st.voice = m.voice; if ("camera" in m) st.camera = m.camera; status(); historico(); aprovCarregar(); break;
    case "friday": st.on = !!m.on; status(); break;
    case "state": if (m.state) st.state = m.state; status(); break;
    case "voice": st.voice = !!m.on; renderControles(); break;
    case "camera": st.camera = !!m.on; renderControles(); break;
    case "modes": { const { type, ...r } = m; st.modes = r; renderControles(); break; }
    case "mouth": st.mouth = Math.max(st.mouth, m.v || 0); break;
    case "text":
      if (m.role === "assistant") msg("a", m.text);
      else if (m.role === "user") msg("u", m.text);
      else if (m.role === "tool") msg("t", "[TOOL] " + m.text);
      break;
    case "friday_heard": case "remote_heard": ouvi(m.text); break;
    case "painel": holo(m.op, m.data || {}); break;
    case "acao_res": if (m.msg) toast(m.msg); break;
    case "voz": tocarVoz(m.wav); break;
    case "stats": stats(m); break;
    case "aprovacao": if (m.item) aprovReceber(m.item); break;
    case "aprovacao_fim": aprovFim(m.id, m.estado, m.msg); break;
    case "ide": if (st.aba === "dev") renderDevWs(m); break;
  }
}
function ouvi(t) {
  const o = $("#ouvi"); $("#ouviTxt").textContent = t || "—"; o.classList.toggle("vazio-o", !t);
  clearTimeout(ouvi.t); if (t) ouvi.t = setTimeout(() => { $("#ouviTxt").textContent = "—"; o.classList.add("vazio-o"); }, 8000);
}

// ---------------- voz no celular ----------------
let vozCtx, vozFim = 0, vozAn;
const somNoCelular = () => ls.get("som", "1") === "1";
async function tocarVoz(b64) {
  if (!somNoCelular() || !b64) return;
  try {
    vozCtx = vozCtx || new (window.AudioContext || window.webkitAudioContext)();
    await vozCtx.resume();
    const bin = Uint8Array.from(atob(b64), (c) => c.charCodeAt(0));
    const buf = await vozCtx.decodeAudioData(bin.buffer);
    const src = vozCtx.createBufferSource(); src.buffer = buf;
    if (!vozAn) { vozAn = vozCtx.createAnalyser(); vozAn.fftSize = 512; vozAn.connect(vozCtx.destination);
      const d = new Float32Array(512);
      setInterval(() => { vozAn.getFloatTimeDomainData(d); let s = 0; for (const v of d) s += v * v; const n = Math.sqrt(s / d.length); if (n > .01) st.mouth = Math.max(st.mouth, Math.min(1, n * 6)); }, 50); }
    src.connect(vozAn);
    const ini = Math.max(vozCtx.currentTime + .05, vozFim);
    src.start(ini); vozFim = ini + buf.duration;
  } catch (e) { console.log("voz:", e); }
}
addEventListener("pointerdown", () => { try { vozCtx = vozCtx || new (window.AudioContext || window.webkitAudioContext)(); vozCtx.resume(); } catch {} }, { once: true });

// ---------------- conversa ----------------
function linkify(s) {
  return esc(String(s ?? "").replace(/\[links\]/gi, "")).replace(/(https?:\/\/[^\s<)"']+)/g, (u) => `<a href="${u}" target="_blank" rel="noopener" style="color:#36d6ff;text-decoration:underline;word-break:break-all">${u}</a>`);
}
function msg(tipo, t, hist) {
  const box = $("#msgs"), perto = box.scrollHeight - box.scrollTop - box.clientHeight < 120;
  const e = document.createElement("div"); e.className = "m " + tipo + (hist ? " h" : ""); e.innerHTML = linkify(t); box.appendChild(e);
  while (box.children.length > 200) box.firstChild.remove();
  if (perto || tipo === "u") box.scrollTop = 1e9;
  return e;
}
async function historico() {
  try {
    const r = await (await api("/api/historico?n=60")).json();
    $("#msgs").textContent = "";
    for (const it of r.itens || []) msg(it.role === "user" ? "u" : it.role === "assistant" ? "a" : "t", String(it.text || ""), true);
    $("#msgs").scrollTop = 1e9;
  } catch {}
}
$("#bAnexo").onclick = () => $("#arq").click();
$("#arq").onchange = async () => {
  const fd = new FormData(); for (const f of $("#arq").files) fd.append("f", f, f.name);
  toast("Enviando anexos…");
  try {
    const r = await (await api("/api/anexo", { method: "POST", body: fd })).json();
    st.anexos.push(...(r.arquivos || []));
    $("#anexos").innerHTML = st.anexos.map((a) => `<span class="anx">[ANEXO] ${esc(a.split("/").pop())}</span>`).join("");
    toast(`${(r.arquivos || []).length} arquivo(s) no PC`);
  } catch { toast("Falha ao enviar"); }
  $("#arq").value = "";
};

// ---------------- Friday LOCAL (Android llama.cpp / WeSpeaker) ----------------
const localOk = () => { try { return !!(window.Nativo && Nativo.localDisponivel && Nativo.localDisponivel()); } catch { return false; } };
const cerebro = () => { const c = ls.get("cerebro", "local"); return c === "local" && !localOk() ? "pc" : c; };
const nomeModelo = () => { try { return Nativo.modeloLocal().replace(/-q4_0\.gguf$|\.gguf$/, "").toUpperCase(); } catch { return ""; } };
function cerebroRender() { const e = $("#cerebroNome"); if (e) e.textContent = cerebro() === "local" ? "LOCAL · " + nomeModelo() : "PC"; }

let cerebroLongo;
$("#cerebroSel").addEventListener("pointerdown", () => { cerebroLongo = setTimeout(() => {
  cerebroLongo = "feito"; if (!localOk()) return; vibrar(40);
  const m = Nativo.trocarModelo(); toast("Carregando " + m + "…", 4000); cerebroRender(); carregarModelos(); }, 650); });
$("#cerebroSel").addEventListener("pointerup", () => { if (cerebroLongo !== "feito") clearTimeout(cerebroLongo); });
$("#cerebroSel").onclick = () => {
  if (cerebroLongo === "feito") { cerebroLongo = null; return; }
  if (!localOk() && cerebro() === "pc") { toast("Cérebro local indisponível (modelo ausente)"); return; }
  ls.set("cerebro", cerebro() === "local" ? "pc" : "local"); cerebroRender(); vibrar();
  toast(cerebro() === "local" ? "Friday LOCAL: no celular (offline)" : "Friday do PC");
  if (cerebro() === "local") { try { Nativo.prepararLocal(); } catch {} }
};

window.fridayLocal = (tipo, t) => {
  if (tipo === "ouvi") { msg("u", t); $("#ouviTxt").textContent = t; st.state = "thinking"; }
  else if (tipo === "parcial") $("#ouviTxt").textContent = t;
  else if (tipo === "passo") msg("t", "[PASSO] " + t.slice(0, 140));
  else if (tipo === "resultado") msg("t", "↳ " + t.slice(0, 160));
  else if (tipo === "fim") { msg("a", t); st.state = "speaking"; setTimeout(() => { st.state = "idle"; }, 2500); }
  else if (tipo === "estado") { toast(t === "pronta" ? "Friday local pronta" : t); }
  else if (tipo === "erro") toast(t);
  else if (tipo === "recusada") {
    const e = msg("t", "[SEGURANÇA] " + t); const b = document.createElement("button");
    b.textContent = "FUI EU"; b.className = "fuiEu";
    b.onclick = () => { try { Nativo.fuiEu(); } catch {} b.disabled = true; b.textContent = "CONFIRMADO"; carregarVozStatus(); };
    e.appendChild(document.createTextNode(" ")); e.appendChild(b);
  }
  else if (tipo === "dev") {
    msg("a", t);
    appendDevLog("[friday] " + t);
  }
};

window.modoAssistente = () => {
  try { irAba("conversa"); } catch {}
  if (!localOk()) { toast("Cérebro local indisponível"); return; }
  if (ls.get("cerebro", "local") !== "local") { ls.set("cerebro", "local"); cerebroRender(); }
  vibrar(30); $("#ouviTxt").textContent = "ouvindo…"; Nativo.ouvirLocal();
};

function tsRender() {
  const e = $("#tsSel"); if (!e || !window.Nativo || !Nativo.tsAtivo) { if (e) e.hidden = true; return; }
  try {
    const quer = Nativo.tsManter(), ativo = Nativo.tsAtivo();
    $("#tsNome").textContent = !quer ? "DESLIGADO" : ativo ? "LIGADO" : "RELIGANDO";
    e.className = quer && ativo ? "on" : "off";
  } catch (err) {
    if (e) e.className = "off";
  }
}
$("#tsSel").onclick = () => { const on = !Nativo.tsManter(); Nativo.tsLigar(on); vibrar(); toast(on ? "Tailscale ligado (vigia ativo)" : "Tailscale desligado"); setTimeout(tsRender, 1500); tsRender(); };
setInterval(tsRender, 5000); setTimeout(tsRender, 800);

function devRender() { const e = $("#devSel"); if (!e || !window.Nativo || !Nativo.modoDev) { if (e) e.hidden = true; return; }
  const on = Nativo.modoDev(); $("#devNome").textContent = on ? "ON" : "OFF"; e.className = on ? "on" : ""; }
let devLongo;
$("#devSel").addEventListener("pointerdown", () => { devLongo = setTimeout(() => { devLongo = "feito"; vibrar(40); irAba("dev"); }, 650); });
$("#devSel").addEventListener("pointerup", () => { if (devLongo !== "feito") clearTimeout(devLongo); });
$("#devSel").onclick = () => {
  if (devLongo === "feito") { devLongo = null; return; }
  irAba("dev");
};
setTimeout(devRender, 800);

// Chip de voz no topo da conversa
$("#vozSel").onclick = () => {
  vibrar(25);
  irAba("controles");
  const el = $("#vozBioSlider");
  if (el) el.scrollIntoView({ behavior: "smooth" });
};

cerebroRender();
setTimeout(() => { try { if (cerebro() === "local") Nativo.prepararLocal(); if (Nativo.configurarHost) Nativo.configurarHost(cfg.host); } catch {} }, 1500);

$("#form").onsubmit = (e) => {
  e.preventDefault();
  const t = $("#txt").value.trim();
  if (cerebro() === "local" && t) { msg("u", t); $("#txt").value = ""; st.state = "thinking"; Nativo.local(t); vibrar(); return; }
  if (!t && !st.anexos.length) return;
  if (enviar({ type: "texto", text: t || "Veja os arquivos que mandei.", files: st.anexos })) {
    $("#txt").value = ""; st.anexos = []; $("#anexos").innerHTML = ""; vibrar();
  }
};

// ---------------- microfone (escuta e envio) ----------------
let micStream, procStream, actx, analyser, rec, chunks = [], gravando = false, silencio = 0, falaMs = 0, piso = .01, segurando = false, pttT0 = 0;
async function micPreparar() {
  if (micStream) { actx.resume(); return true; }
  try {
    micStream = await navigator.mediaDevices.getUserMedia({ audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: true, channelCount: 1, sampleRate: 16000 } });
    const fone = () => { try { window.Nativo && Nativo.audioFone && Nativo.audioFone(); } catch {} };
    fone(); setInterval(() => st.micOn && fone(), 4000);
    actx = new (window.AudioContext || window.webkitAudioContext)({ sampleRate: 16000 });
    const hp = actx.createBiquadFilter(); hp.type = "highpass"; hp.frequency.value = 85;
    const lp = actx.createBiquadFilter(); lp.type = "lowpass"; lp.frequency.value = 3800;
    const co = actx.createDynamicsCompressor(); co.threshold.value = -24; co.knee.value = 10; co.ratio.value = 8; co.attack.value = .003; co.release.value = .2;
    const src = actx.createMediaStreamSource(micStream), dest = actx.createMediaStreamDestination();
    analyser = actx.createAnalyser(); analyser.fftSize = 1024;
    src.connect(hp); hp.connect(lp); lp.connect(co); co.connect(analyser); co.connect(dest);
    procStream = dest.stream; vad(); actx.resume();
    return true;
  } catch (e) { toast("Microfone negado: " + e.message); return false; }
}
async function micLigar(on) {
  st.micOn = on; ls.set("mic", on ? "1" : "0");
  if (on && !(await micPreparar())) st.micOn = false;
  if (!st.micOn) pararGravacao(false);
  renderControles();
}
function nivel() { const b = new Float32Array(analyser.fftSize); analyser.getFloatTimeDomainData(b); let s = 0; for (const v of b) s += v * v; return Math.sqrt(s / b.length); }
function vad() {
  const passo = 50;
  setInterval(() => {
    if (!analyser) return;
    const n = nivel();
    if (gravando) st.mouth = Math.max(st.mouth, Math.min(1, n * 8));
    if (!st.micOn || segurando) return;
    if (!gravando) piso = piso * .97 + Math.min(n, .05) * .03;
    st.micAtivo = gravando;
    if (st.state === "speaking") return;
    if (n > Math.max(.015, piso * 2.6)) { silencio = 0; if (!gravando) iniciarGravacao(); falaMs += passo; }
    else if (gravando) { silencio += passo; if (silencio > 900) pararGravacao(falaMs > 350); }
    if (gravando && falaMs > 30000) pararGravacao(true);
  }, passo);
}
function iniciarGravacao() {
  if (gravando || !micStream) return;
  chunks = []; falaMs = 0; silencio = 0; gravando = true; st.micAtivo = true; $("#ptt").classList.add("talk");
  const mime = MediaRecorder.isTypeSupported("audio/webm;codecs=opus") ? "audio/webm;codecs=opus" : "";
  rec = new MediaRecorder(procStream || micStream, mime ? { mimeType: mime } : {});
  rec.ondataavailable = (e) => e.data.size && chunks.push(e.data);
  rec.onstop = async () => {
    $("#ptt").classList.remove("talk");
    if (!rec._enviar || !chunks.length) return;
    ouvi("transcrevendo…");
    try {
      const modoLocal = cerebro() === "local";
      const endpoint = modoLocal ? "/api/audio?so_transcrever=1" : "/api/audio";
      const r = await (await api(endpoint, { method: "POST", body: new Blob(chunks, { type: "audio/webm" }) })).json();
      if (r.recusada) {
        ouvi("");
        toast("[BIO] " + (r.msg || "Apenas a voz do dono é autorizada"), 4000);
        const e = msg("t", "[BIO] " + (r.msg || "Voz recusada: não é a voz do dono"));
        const b = document.createElement("button");
        b.textContent = "FUI EU"; b.className = "fuiEu";
        b.onclick = () => { try { Nativo.fuiEu(); } catch {} b.disabled = true; b.textContent = "CONFIRMADO"; carregarVozStatus(); };
        e.appendChild(document.createTextNode(" ")); e.appendChild(b);
        return;
      }
      ouvi(r.texto || "");
      if (r.texto) {
        if (modoLocal) {
          msg("u", r.texto);
          st.state = "thinking";
          try { Nativo.local(r.texto); } catch (e) { toast("Erro no cérebro local: " + e.message); }
          vibrar();
        }
      } else {
        toast("Não entendi o áudio");
      }
    } catch { ouvi(""); }
  };
  rec.start();
}
function pararGravacao(enviarIt) { if (!gravando) return; gravando = false; st.micAtivo = false; if (rec && rec.state !== "inactive") { rec._enviar = enviarIt; rec.stop(); } }
const ptt = $("#ptt");
ptt.addEventListener("pointerdown", async (e) => {
  e.preventDefault(); try { ptt.setPointerCapture(e.pointerId); } catch {}
  if (cerebro() === "local") { vibrar(30); $("#ouviTxt").textContent = "ouvindo…"; Nativo.ouvirLocal(); return; }
  segurando = true; pttT0 = performance.now(); vibrar(30);
  if (!(await micPreparar())) { segurando = false; return; }
  if (!segurando) return;
  pararGravacao(false); iniciarGravacao(); $("#pttDica").textContent = "SOLTE PARA ENVIAR (SÓ VOZ DO DONO)";
});
const pttFim = (cancelar) => () => {
  if (cerebro() === "local") { if (cancelar) try { Nativo.pararOuvir(); } catch {} return; }
  if (!segurando) return; segurando = false; $("#pttDica").textContent = "TOQUE EM ENVIAR OU SEGURE O MICROFONE (SÓ VOZ DO DONO)";
  const curto = performance.now() - pttT0 < 400; pararGravacao(!cancelar && !curto); if (curto && !cancelar) toast("Segure enquanto fala"); vibrar(15);
};
ptt.addEventListener("pointerup", pttFim(false));
ptt.addEventListener("pointercancel", pttFim(true));
ptt.addEventListener("pointerleave", (e) => { if (segurando && e.pointerType !== "mouse") pttFim(true)(); });
ptt.addEventListener("contextmenu", (e) => e.preventDefault());

// ---------------- câmera do celular ----------------
let camStream, camTimer, traseira = ls.get("traseira", "0") === "1";
async function camLigar(on) {
  st.camOn = on; ls.set("celcam", on ? "1" : "0"); clearInterval(camTimer);
  if (camStream) { camStream.getTracks().forEach((t) => t.stop()); camStream = null; }
  const v = $("#celCam"); v.style.display = on ? "block" : "none";
  renderControles();
  if (!on) return;
  try {
    camStream = await navigator.mediaDevices.getUserMedia({ video: { facingMode: traseira ? "environment" : "user", width: { ideal: 960 } } });
    v.srcObject = camStream; v.classList.toggle("traseira", traseira);
    const c = document.createElement("canvas");
    camTimer = setInterval(() => {
      if (!v.videoWidth || !st.online) return;
      c.width = 640; c.height = Math.round(640 * v.videoHeight / v.videoWidth);
      c.getContext("2d").drawImage(v, 0, 0, c.width, c.height);
      c.toBlob((b) => b && api("/api/foto", { method: "POST", body: b }).catch(() => {}), "image/jpeg", .7);
    }, 2000);
  } catch (e) { toast("Câmera negada: " + e.message); st.camOn = false; v.style.display = "none"; renderControles(); }
}
$("#tgCel").onclick = () => { vibrar(); camLigar(!st.camOn); };
$("#bVirar").onclick = () => { traseira = !traseira; ls.set("traseira", traseira ? "1" : "0"); if (st.camOn) camLigar(true); toast(traseira ? "Câmera traseira" : "Câmera frontal"); };

// ---------------- câmeras do PC ----------------
const CAM_NOME = { ptz: "PTZ · QUARTO", nativa: "NATIVA", porta: "PORTA" };
const camEst = {};
let camFull = null;
let ptzDesconectada = true;

function atualizarLayoutCams() {
  const ptzCard = $("#camCardPtz"), natCard = $("#camCardNativa");
  const pSlot = $("#camPrincipalSlot"), mSlot = $("#camsMinSlot");
  const ptzControle = $("#cardControlePtz"), ptzMsg = $("#ptzMsg");
  if (ptzDesconectada) {
    if (ptzControle) {
      ptzControle.style.opacity = "0.45";
      ptzControle.style.pointerEvents = "none";
    }
    if (ptzMsg) ptzMsg.textContent = "[DESCONECTADA]";
    if (pSlot && mSlot && natCard && ptzCard && pSlot.contains(ptzCard)) {
      pSlot.appendChild(natCard);
      mSlot.prepend(ptzCard);
    }
  } else {
    if (ptzControle) {
      ptzControle.style.opacity = "1";
      ptzControle.style.pointerEvents = "auto";
    }
    if (ptzMsg && ptzMsg.textContent === "[DESCONECTADA]") ptzMsg.textContent = "";
    if (pSlot && mSlot && ptzCard && natCard && pSlot.contains(natCard)) {
      pSlot.appendChild(ptzCard);
      mSlot.prepend(natCard);
    }
  }
}

async function camPuxar(nome) {
  const s = camEst[nome] = camEst[nome] || { busy: false, url: "" };
  if (s.busy) return; s.busy = true;
  try {
    const r = await apiNova(`/api/cam/${nome}`);
    const els = $$(`.cam[data-cam="${nome}"]`);
    if (r.status === 404) {
      const sem = await r.json().catch(() => ({}));
      if (nome === "ptz") {
        ptzDesconectada = true;
        atualizarLayoutCams();
      }
      els.forEach((e) => {
        e.classList.remove("viva");
        const off = e.querySelector(".off");
        if (off) {
          off.hidden = false;
          off.textContent = (nome === "ptz" || sem.erro === "desconectada") ? "DESCONECTADA" : "SEM SINAL";
        }
      });
      return;
    }
    if (!r.ok) return;
    if (nome === "ptz") {
      ptzDesconectada = false;
      atualizarLayoutCams();
    }
    const idade = parseFloat(r.headers.get("X-Idade") || "0"), b = await r.blob(), u = URL.createObjectURL(b);
    els.forEach((e) => {
      e.querySelector("img").src = u;
      e.querySelector(".off").hidden = true;
      e.classList.toggle("viva", idade < 3);
      e.querySelector(".idade").textContent = idade < 3 ? "AO VIVO" : `${Math.round(idade)} s`;
    });
    if (camFull === nome) $("#camFull img").src = u;
    if (s.url) URL.revokeObjectURL(s.url); s.url = u;
  } catch {} finally { s.busy = false; }
}
let camLoop;
function camerasAtivas(on) {
  clearInterval(camLoop); if (!on) return;
  const tick = () => {
    if (!st.online || document.hidden) return;
    if (camFull) return camPuxar(camFull);
    for (const n of ["nativa", "porta", "ptz"]) camPuxar(n);
  };
  tick(); camLoop = setInterval(tick, 330);
}
aoMudarAba.push((n) => camerasAtivas(n === "cameras" || !!camFull));
$$(".cam").forEach((c) => c.onclick = () => {
  camFull = c.dataset.cam; $("#camFull .rot").textContent = CAM_NOME[camFull]; $("#camFull img").src = c.querySelector("img").src; $("#camFull").classList.add("open"); camerasAtivas(true);
});
const fecharCamFull = () => { camFull = null; $("#camFull").classList.remove("open"); camerasAtivas(st.aba === "cameras"); };
$("#camFecha").onclick = fecharCamFull;
new MutationObserver(() => { if (camFull && !$("#camFull").classList.contains("open")) fecharCamFull(); }).observe($("#camFull"), { attributes: true });

async function ptzCmd(c, rot) { $("#ptzMsg").textContent = rot; await cmd(Object.assign({ type: "ptz" }, c)); }
$$("[data-ptz]").forEach((b) => b.onclick = () => ptzCmd({ op: "olhar", dir: b.dataset.ptz }, "OLHANDO: " + b.dataset.ptz.toUpperCase()));
const PTZ_ROT = { seguir: "SEGUINDO VOCÊ", vigiar: "VIGIANDO", auto: "AUTOMÁTICO", em_volta: "OLHANDO EM VOLTA", zoom: "ZOOM 2×", parar: "PARADA" };
$$("[data-op]").forEach((b) => b.onclick = () => ptzCmd(b.dataset.op === "zoom" ? { op: "zoom", fator: 2 } : { op: b.dataset.op }, PTZ_ROT[b.dataset.op]));

// ============================================================================
// ========================= AGENDA PRÓPRIA DA FRIDAY =========================
// ============================================================================
let agCache = null;
const NIVEL_CORES = {
  livre: { b: "var(--ok)", bg: "rgba(61,255,154,.12)", t: "LIVRE" },
  leve: { b: "var(--cia)", bg: "rgba(54,214,255,.12)", t: "LEVE" },
  moderado: { b: "var(--lar)", bg: "rgba(255,138,31,.15)", t: "MODERADO" },
  intenso: { b: "var(--lar)", bg: "rgba(255,138,31,.25)", t: "INTENSO" },
  critico: { b: "var(--err)", bg: "rgba(255,90,110,.2)", t: "CRÍTICO" }
};

// A tela usa {dias:[{data, dia_semana, nivel, livre_min, itens:[{id, titulo, hora, prioridade, feito}]}]}.
// A ponte nativa manda os itens soltos (ini em ms) e o PC manda inicio em segundos: os dois passam por aqui (18/10/2026).
const SEMANA = ["domingo", "segunda", "terça", "quarta", "quinta", "sexta", "sábado"];
function agendaNormalizar(j, nDias) {
  if (!j || typeof j !== "object") return null;
  if (Array.isArray(j.dias) && j.dias.length && Array.isArray(j.dias[0].itens)) return j;   // já no formato da tela
  const d0 = new Date(); d0.setHours(0, 0, 0, 0);
  const hoje = typeof j.hoje === "number" ? j.hoje : d0.getTime();
  const itens = (j.itens || []).map((it) => {
    const ini = typeof it.ini === "number" ? it.ini : (it.inicio || 0) * 1000;
    const hd = new Date(ini);
    return { id: it.id, titulo: it.titulo || it.texto || "", ini, feito: !!it.feito, notas: it.notas || "", categoria: it.tipo || it.categoria || "",
      prioridade: it.prio || it.prioridade || 2, removido: !!it.removido,
      hora: it.diaTodo || it.dia_todo ? "dia todo" : it.horaIni || (String(hd.getHours()).padStart(2, "0") + ":" + String(hd.getMinutes()).padStart(2, "0")) };
  }).filter((x) => !x.removido).sort((a, b) => a.ini - b.ini);
  const dias = [];
  for (let k = 0; k < (nDias || 7); k++) {
    const ini = hoje + k * 86400000, dt = new Date(ini), nat = (j.dias || [])[k] || {};
    const data = dt.getFullYear() + "-" + String(dt.getMonth() + 1).padStart(2, "0") + "-" + String(dt.getDate()).padStart(2, "0");
    const nivPc = j.niveis && (j.niveis[data] || {}).nivel;
    dias.push({ data, dia_semana: SEMANA[dt.getDay()], nivel: String(nat.nivel || nivPc || "livre").normalize("NFD").replace(/[\u0300-\u036f]/g, ""),
      livre_min: nat.livreMin || 0, itens: itens.filter((x) => x.ini >= ini && x.ini < ini + 86400000) });
  }
  return { status: j.status || "", dias };
}

function carregarAgenda() {
  let raw = "";
  try {
    if (window.Nativo && Nativo.agendaJson) raw = Nativo.agendaJson(7);
  } catch {}

  if (!raw && st.online) {
    apiNova("/api/agenda?dias=7").then(async (r) => {
      if (r.ok) {
        agCache = agendaNormalizar(await r.json(), 7);
        renderAgenda();
      }
    }).catch(() => {});
    return;
  }

  if (raw) {
    try { agCache = agendaNormalizar(JSON.parse(raw), 7); } catch { agCache = null; }
  }
  renderAgenda();
}

function renderAgenda() {
  if (!agCache || !Array.isArray(agCache.dias) || !agCache.dias.length) {
    $("#agLista").innerHTML = `<div class="vazio">NENHUM COMPROMISSO NA AGENDA FRIDAY</div>`;
    return;
  }
  const dias = agCache.dias;
  if (st.agendaDia >= dias.length) st.agendaDia = 0;
  const dAtual = dias[st.agendaDia] || dias[0];

  // Barra de dias horizontais
  const diasHtml = dias.map((d, idx) => {
    const sem = d.dia_semana ? esc(d.dia_semana.slice(0, 3).toUpperCase()) : "";
    const numD = d.data ? d.data.slice(8, 10) : "";
    const qtd = (d.itens || []).length;
    const ativo = idx === st.agendaDia ? "on" : "";
    return `<div class="agDia ${ativo}" data-agidx="${idx}"><span>${idx === 0 ? "HOJE" : idx === 1 ? "AMANHÃ" : sem}</span><b>${numD}</b><i>${qtd} itens</i></div>`;
  }).join("");
  $("#agDias").innerHTML = diasHtml;
  $$("#agDias .agDia").forEach((el) => {
    el.onclick = () => { vibrar(); st.agendaDia = parseInt(el.dataset.agidx || "0"); renderAgenda(); };
  });

  // Título e Nível
  const dStr = dAtual.data ? dAtual.data.split("-").reverse().join("/") : "HOJE";
  $("#agDataTit").textContent = (st.agendaDia === 0 ? "HOJE · " : "") + dStr;
  const nivKey = (dAtual.nivel || "livre").toLowerCase();
  const infoNiv = NIVEL_CORES[nivKey] || NIVEL_CORES.livre;
  const nb = $("#agNivelBadge");
  nb.textContent = "NÍVEL: " + infoNiv.t;
  nb.style.borderColor = infoNiv.b;
  nb.style.color = infoNiv.b;
  nb.style.background = infoNiv.bg;

  const itens = dAtual.itens || [];
  const feitos = itens.filter((x) => x.feito).length;
  $("#agStatsTxt").textContent = `${itens.length} compromissos · ${feitos} concluídos`;
  const pct = itens.length ? Math.round((feitos / itens.length) * 100) : 0;
  $("#agProgBar").style.width = pct + "%";
  $("#agLivreTxt").textContent = dAtual.livre_min ? `${Math.round(dAtual.livre_min / 60)}h livres` : "";

  // Próximos fora do dia escolhido: evento marcado p/ outro dia não some ("marcou mas não apareceu", 18/10/2026)
  const prox = [];
  dias.forEach((d, idx) => { if (idx > st.agendaDia) (d.itens || []).forEach((x) => { if (!x.feito) prox.push({ x, idx, d }); }); });
  const proxHtml = prox.length ? `<div class="agProx"><div class="agProxTit">PRÓXIMOS</div>` + prox.slice(0, 5).map((p) =>
    `<div class="agProxItem" data-agidx="${p.idx}"><b>${esc((p.d.dia_semana || "").slice(0, 3).toUpperCase())} ${esc(p.d.data ? p.d.data.slice(8, 10) + "/" + p.d.data.slice(5, 7) : "")}${p.x.hora ? " · " + esc(p.x.hora) : ""}</b> ${p.x.prioridade === 1 ? "[ALTA] " : ""}${esc(p.x.titulo || p.x.texto || "")}</div>`).join("") + `</div>` : "";
  const ligarProx = () => $$("#agLista .agProxItem").forEach((el) => {
    el.onclick = () => { vibrar(); st.agendaDia = parseInt(el.dataset.agidx || "0"); renderAgenda(); };
  });

  // Linha do tempo dos itens
  if (!itens.length) {
    $("#agLista").innerHTML = `<div class="vazio">DIA LIVRE · SEM COMPROMISSOS REGISTRADOS</div>` + proxHtml;
    ligarProx();
    return;
  }

  const PRIO_ROT = { 1: "ALTA", 2: "NORMAL", 3: "BAIXA" };   // igual ao PC (prom_ops._prio) e ao Agenda.java: 1 = alta
  const itemsHtml = itens.map((it) => {
    const clsPrio = it.prioridade === 1 ? "alta" : "";
    const clsFeito = it.feito ? "feito" : "";
    const cat = it.categoria || "geral";
    return `<div class="agItem ${clsPrio} ${clsFeito}" data-id="${esc(it.id)}">
      <div class="agItemTop">
        <span class="agHora">${esc(it.hora || "--:--")}</span>
        <span class="agCat">${esc(cat)}</span>
        <span class="agPrio">${PRIO_ROT[it.prioridade] || "NORMAL"}</span>
      </div>
      <div class="agTit">${esc(it.titulo || it.texto || "Sem título")}</div>
      ${it.notas ? `<div class="agNotas">${esc(it.notas)}</div>` : ""}
      <div class="agItemBtns">
        <button type="button" class="agBtn ok" data-agop="feito">${it.feito ? "REABRIR" : "CONCLUIR"}</button>
        <button type="button" class="agBtn lar" data-agop="prio">PRIORIDADE</button>
        <button type="button" class="agBtn err" data-agop="cancelar">EXCLUIR</button>
      </div>
    </div>`;
  }).join("");

  $("#agLista").innerHTML = itemsHtml + proxHtml;
  ligarProx();
  $$("#agLista .agItem").forEach((card) => {
    const id = card.dataset.id;
    card.querySelectorAll("[data-agop]").forEach((b) => {
      b.onclick = () => {
        vibrar();
        const op = b.dataset.agop;
        if (op === "feito") {
          const it = itens.find((x) => x.id === id);
          if (window.Nativo && Nativo.agendaMudar) Nativo.agendaMudar(id, "feito", String(!(it && it.feito)));
        } else if (op === "prio") {
          const it = itens.find((x) => x.id === id);
          const novaPrio = ((it ? it.prioridade : 2) % 3) + 1;
          if (window.Nativo && Nativo.agendaMudar) Nativo.agendaMudar(id, "prioridade", String(novaPrio));
        } else if (op === "cancelar") {
          if (window.Nativo && Nativo.agendaMudar) Nativo.agendaMudar(id, "removido", "true");
        }
        setTimeout(carregarAgenda, 200);
      };
    });
  });
}

$("#bAgNovoToggle").onclick = () => {
  const c = $("#agFormCard");
  c.hidden = !c.hidden;
  if (!c.hidden) {
    const hoje = new Date().toISOString().slice(0, 10);
    $("#agDataIn").value = hoje;
    $("#agTitIn").focus();
  }
};
$("#bAgCancelarForm").onclick = () => { $("#agFormCard").hidden = true; };
$("#bAgSalvar").onclick = () => {
  const tit = $("#agTitIn").value.trim();
  if (!tit) return toast("Informe o título do compromisso");
  const data = $("#agDataIn").value;
  const hora = $("#agHoraIn").value || "09:00";
  const dur = parseInt($("#agDurIn").value || "60");
  const cat = $("#agCatIn").value || "geral";
  const prio = parseInt($("#agPrioIn").value || "2");
  const notas = $("#agNotasIn").value.trim();
  vibrar(25);
  if (window.Nativo && Nativo.agendaNovo) {
    if (!data) return toast("Escolha a data");
    const quando = data.split("-").reverse().join("/") + " " + hora;
    const r = Nativo.agendaNovo(notas ? tit + " — " + notas : tit, quando, prio, dur);
    toast(r || "Compromisso salvo na Sexta-Feira");
  } else {
    toast("Salvo na agenda local");
  }
  $("#agTitIn").value = "";
  $("#agNotasIn").value = "";
  $("#agFormCard").hidden = true;
  setTimeout(carregarAgenda, 250);
};
$("#bAgSync").onclick = () => {
  vibrar(20);
  toast("Sincronizando com PC…");
  try { if (window.Nativo && Nativo.agendaSync) Nativo.agendaSync(); } catch {}
  setTimeout(carregarAgenda, 600);
};
$("#bAgFlut").onclick = () => {
  vibrar(20);
  try { if (window.Nativo && Nativo.agendaFlutuante) Nativo.agendaFlutuante(); } catch {}
};
aoMudarAba.push((aba) => { if (aba === "agenda") carregarAgenda(); });

// ============================================================================
// ========================= MODO DEV IDE AUTÔNOMA ============================
// ============================================================================
function appendDevLog(linha, cls = "plano") {
  const term = $("#devTerm");
  if (!term) return;
  const el = document.createElement("div");
  el.className = "dl " + cls;
  el.textContent = linha;
  term.appendChild(el);
  while (term.children.length > 250) term.firstChild.remove();
  term.scrollTop = term.scrollHeight;
}

function carregarDev() {
  let est = { estado: "pronto", tarefa: "", round: 0, maxRounds: 8, motor: "hibrido" };
  try {
    if (window.Nativo && Nativo.ideEstadoJson) {
      const j = JSON.parse(Nativo.ideEstadoJson());
      est = Object.assign(est, j);
    }
  } catch {}

  const pill = $("#devEstadoPill");
  pill.textContent = (est.estado || "PRONTA").toUpperCase();
  pill.classList.toggle("on", est.estado === "executando" || est.estado === "planejando" || est.estado === "codando");

  $("#devRoundTxt").textContent = `ROUND ${est.round || 0} / ${est.maxRounds || 8}`;
  const pct = Math.min(100, Math.round(((est.round || 0) / (est.maxRounds || 8)) * 100));
  $("#devProgBar").style.width = pct + "%";
  $("#devTarefaAtiva").textContent = est.tarefa ? esc(est.tarefa.slice(0, 40)) : "AGUARDANDO TAREFA";
  $("#devMotorTxt").textContent = st.devAlvo === "pc" ? "MOTOR PC" : (est.motor || "HÍBRIDO").toUpperCase();
}

function renderDevWs(m) {
  if (m.texto) appendDevLog(m.texto, m.classe || "plano");
  if (m.round !== undefined) $("#devRoundTxt").textContent = `ROUND ${m.round} / ${m.max || 8}`;
  if (m.estado) $("#devEstadoPill").textContent = m.estado.toUpperCase();
}

$("#bDevAlvoAuto").onclick = () => {
  st.devAlvo = "auto";
  $("#bDevAlvoAuto").classList.add("on");
  $("#bDevAlvoPc").classList.remove("on");
  toast("Modo Dev: Híbrido (celular + PC)");
  carregarDev();
};
$("#bDevAlvoPc").onclick = () => {
  st.devAlvo = "pc";
  $("#bDevAlvoPc").classList.add("on");
  $("#bDevAlvoAuto").classList.remove("on");
  toast("Modo Dev: Forçar execução no PC");
  carregarDev();
};

$$("[data-devpreset]").forEach((btn) => {
  btn.onclick = () => {
    vibrar();
    $("#devPrompt").value = btn.dataset.devpreset;
    $("#devPrompt").focus();
  };
});

$("#bDevIniciar").onclick = () => {
  const p = $("#devPrompt").value.trim();
  if (!p) return toast("Descreva o que deseja que a Friday desenvolva");
  vibrar(30);
  appendDevLog("[INICIANDO DEV] " + p, "cmd");
  toast("Iniciando Modo Dev autônomo…", 3000);

  if (st.devAlvo === "pc" || (!localOk() && st.online)) {
    enviar({ type: "ide", op: "iniciar", prompt: p });
  } else {
    try {
      if (window.Nativo && Nativo.ideIniciar) Nativo.ideIniciar(p);
      else if (window.Nativo && Nativo.local) Nativo.local("[modo dev] " + p);
    } catch (e) {
      appendDevLog("[ERRO] " + e.message, "erro");
    }
  }
  $("#devPrompt").value = "";
  setTimeout(carregarDev, 500);
};

$("#bDevPausar").onclick = () => {
  vibrar();
  toast("Pausando/retomando…");
  try {
    if (window.Nativo && Nativo.idePausar) Nativo.idePausar();
    if (st.online) enviar({ type: "ide", op: "pausar" });
  } catch {}
  setTimeout(carregarDev, 300);
};

$("#bDevParar").onclick = () => {
  vibrar(30);
  toast("Parando Modo Dev");
  appendDevLog("[PARADO PELO USUÁRIO]", "erro");
  try {
    if (window.Nativo && Nativo.ideParar) Nativo.ideParar();
    if (st.online) enviar({ type: "ide", op: "parar" });
  } catch {}
  setTimeout(carregarDev, 300);
};

$("#bDevFlut").onclick = () => {
  vibrar();
  try { if (window.Nativo && Nativo.ideFlutuante) Nativo.ideFlutuante(); } catch {}
};
$("#bDevTermux").onclick = () => {
  vibrar();
  try { if (window.Nativo && Nativo.devTerminal) Nativo.devTerminal(); } catch {}
};
aoMudarAba.push((aba) => { if (aba === "dev") carregarDev(); });

// ============================================================================
// ==================== BIOMETRIA DE VOZ E MODELOS ANDROID ====================
// ============================================================================
function carregarVozStatus() {
  let v = { amostras: 23, limiar: 0.54, ultimoScore: 0.0, estrito: true };
  try {
    if (window.Nativo && Nativo.vozStatusJson) v = Object.assign(v, JSON.parse(Nativo.vozStatusJson()));
  } catch {}
  $("#vozBioAmostras").textContent = v.amostras || "0";
  $("#vozBioLimiarVal").textContent = (v.limiar || 0.54).toFixed(2);
  $("#vozBioScore").textContent = v.ultimoScore > 0 ? v.ultimoScore.toFixed(2) : "--";
  $("#vozBioSlider").value = (v.limiar || 0.54).toFixed(2);
  $("#vozCont").textContent = `${v.amostras || 0}`;
}
$("#vozBioSlider").oninput = (e) => {
  const val = parseFloat(e.target.value);
  $("#vozBioLimiarVal").textContent = val.toFixed(2);
};
$("#vozBioSlider").onchange = (e) => {
  const val = parseFloat(e.target.value);
  vibrar();
  try { if (window.Nativo && Nativo.setLimiarVoz) Nativo.setLimiarVoz(val); } catch {}
  toast(`Limiar biométrico: ${val.toFixed(2)}`);
  carregarVozStatus();
};
$("#bVozGravar").onclick = () => {
  vibrar(25);
  toast("Fale uma frase de 5 a 10s…", 4000);
  try { if (window.Nativo && Nativo.cadastrarVoz) Nativo.cadastrarVoz(); } catch {}
  setTimeout(carregarVozStatus, 6000);
};
$("#bVozFuiEu").onclick = () => {
  vibrar(25);
  try {
    if (window.Nativo && Nativo.fuiEu) {
      Nativo.fuiEu();
      toast("Última fala adicionada ao perfil biométrico");
    }
  } catch {}
  setTimeout(carregarVozStatus, 500);
};

function carregarModelos() {
  let lista = [];
  try {
    if (window.Nativo && Nativo.catalogoModelos) lista = JSON.parse(Nativo.catalogoModelos());
  } catch {}
  if (!lista.length) {
    $("#listaModelos").innerHTML = `<div class="vazio">NENHUM MODELO ENCONTRADO</div>`;
    return;
  }
  const atual = nomeModelo();
  const html = lista.map((m) => {
    const ehAtivo = m.ativo || m.nome.toUpperCase().includes(atual);
    return `<div class="modCard ${ehAtivo ? "ativo" : ""}">
      <div class="mInfo">
        <b>${esc(m.nome)} ${m.recomendado ? "[RECOMENDADO]" : ""}</b>
        <small>${esc(m.desc || "")}</small>
        <div class="mMeta">${m.instalado ? "[INSTALADO]" : "PENDENTE"} · RAM: ${esc(m.ram || "2GB")} · TAM: ${esc(m.tamanho || "--")}</div>
      </div>
      <button type="button" class="bt ${ehAtivo ? "ok" : "lar"}" data-modid="${esc(m.id)}" style="min-height:36px;padding:4px 10px">${ehAtivo ? "ATIVO" : "USAR"}</button>
    </div>`;
  }).join("");
  $("#listaModelos").innerHTML = html;
  $$("#listaModelos [data-modid]").forEach((b) => {
    b.onclick = () => {
      vibrar(25);
      const mid = b.dataset.modid;
      toast("Alternando modelo para " + mid + "…", 3000);
      try { if (window.Nativo && Nativo.selecionarModelo) Nativo.selecionarModelo(mid); } catch {}
      setTimeout(() => { cerebroRender(); carregarModelos(); }, 1200);
    };
  });
}
aoMudarAba.push((aba) => {
  if (aba === "controles") {
    carregarVozStatus();
    carregarModelos();
  }
});

// ---------------- painel ----------------
function gauge(rot, v) {
  const n = Math.max(0, Math.min(100, num(v) ?? 0)), L = 188.5;
  return `<div class="g"><svg viewBox="0 0 100 100" class="gauge ${n > 85 ? "alto" : n > 65 ? "medio" : ""}">` +
    `<circle class="trilho" cx="50" cy="50" r="40" stroke-dasharray="${L} 999" transform="rotate(135 50 50)"/>` +
    `<circle class="valor" cx="50" cy="50" r="40" stroke-dasharray="${(n / 100 * L).toFixed(1)} 999" transform="rotate(135 50 50)"/>` +
    `<text x="50" y="57" text-anchor="middle">${num(v) === null ? "--" : Math.round(n) + "%"}</text></svg><span>${rot}</span></div>`;
}
function stats(m) {
  st.stats = m;
  $("#pGauges").innerHTML = gauge("CPU", m.cpu) + gauge("RAM", m.ram) + gauge("GPU", m.gpu) + gauge("VRAM", m.vram);
  $("#pTemp").textContent = num(m.temp) !== null ? Math.round(m.temp) + " °C" : "--";
  $("#pSisH").textContent = new Date().toLocaleTimeString("pt-BR", { hour: "2-digit", minute: "2-digit", second: "2-digit" });
  const pes = (m.pessoas || []).map((p) => `<span class="tag p">[PESSOA] ${esc(typeof p === "string" ? p : p.nome || JSON.stringify(p))}</span>`).join("");
  $("#pPessoas").innerHTML = pes || `<span class="vazio">NINGUÉM À VISTA</span>`;
  const obj = (m.objetos || []).slice(0, 16).map((o) => `<span class="tag">${esc(typeof o === "string" ? o : o.nome || o.label || JSON.stringify(o))}</span>`).join("");
  $("#pObjetos").innerHTML = obj;
  $("#pAlvo").textContent = m.alvo ? "ALVO: " + String(typeof m.alvo === "string" ? m.alvo : m.alvo.nome || "").toUpperCase() : "";
  if ("ptz_on" in m) {
    ptzDesconectada = !m.ptz_on;
    atualizarLayoutCams();
  }
  for (const [k, nome] of [["ptz_on", "ptz"], ["nat_on", "nativa"], ["usb_on", "porta"]])
    if (k in m && !m[k]) $$(`.cam[data-cam="${nome}"]`).forEach((e) => e.classList.remove("viva"));
}
const li = (b, s, i) => `<li><b>${esc(b)}</b><span>${esc(s)}</span>${i ? `<i>${esc(i)}</i>` : ""}</li>`;
const vazio = (t) => `<li><span class="vazio">${t}</span></li>`;
async function painelPuxar() {
  try {
    const r = await apiNova("/api/painel");
    if (r.status === 404) { $("#pClima").innerHTML = `<div class="vazio">REINICIE O DAEMON NO PC PARA LIBERAR O PAINEL</div>`; return; }
    if (!r.ok) return;
    const d = await r.json(), c = d.clima || {};
    const dias = (c.dias || []).slice(0, 4).map((x) => `<div>${esc(String(x.data || "").split("-").reverse().join("/"))}<b>${esc(x.min)}° / ${esc(x.max)}°</b></div>`).join("");
    $("#pClima").innerHTML = c.temp !== undefined ? `<div class="clima1"><span class="big">${esc(c.temp)}°</span><div><div class="d">${esc(c.desc)}</div>` +
      `<div class="c">${esc(String(c.local || c.cidade || "").toUpperCase())} · SENSAÇÃO ${esc(c.sensacao ?? "--")}° · UMIDADE ${esc(c.umidade ?? "--")}%</div></div></div>` +
      (dias ? `<div class="dias">${dias}</div>` : "") : `<div class="vazio">SEM DADOS DE CLIMA</div>`;
    $("#pAgenda").innerHTML = (d.agenda || []).map((x) => li(x.hora || x.quando || "", x.titulo || x.texto || "")).join("") || vazio("SEM COMPROMISSOS (TOQUE PARA ABRIR)");
    $("#pTarefas").innerHTML = (d.tarefas || []).map((x) => li("•", x.texto || x.titulo || "", String(x.estado || "").toUpperCase())).join("") || vazio("NENHUMA TAREFA ABERTA");
    $("#pRecente").innerHTML = (d.recente || []).map((x) => li(x.h || "", x.txt || "", String(x.tipo || "").toUpperCase())).join("") || vazio("SEM ATIVIDADE");
    const mem = d.memoria || {}, pt = Object.entries(mem.por_tipo || {}).sort((a, b) => b[1] - a[1]).slice(0, 8), mx = Math.max(1, ...pt.map((x) => x[1]));
    $("#pFatos").textContent = mem.fatos !== undefined ? mem.fatos + " FATOS" : "";
    $("#pMem").innerHTML = pt.map(([k, v]) => `<div><span>${esc(k.toUpperCase())}</span><s><i style="width:${v / mx * 100}%"></i></s><span>${esc(v)}</span></div>`).join("") || `<div class="vazio">—</div>`;
    const pr = (d.processos || []).slice(0, 6), pm = Math.max(100, ...pr.map((x) => num(x.cpu) || 0));
    $("#pProc").innerHTML = pr.map((x) => `<div><span>${esc(x.nome)}</span><s><i style="width:${(num(x.cpu) || 0) / pm * 100}%"></i></s><span>${esc(Math.round(num(x.cpu) || 0))}%</span></div>`).join("") || `<div class="vazio">—</div>`;
    $("#pDisco").textContent = d.disco || "--"; $("#pUp").textContent = d.uptime || "--"; $("#pRede").textContent = d.rede || "--";
  } catch {}
}
let painelLoop;
aoMudarAba.push((n) => { clearInterval(painelLoop); if (n === "painel") { painelPuxar(); painelLoop = setInterval(() => !document.hidden && painelPuxar(), 3000); } });

// ---------------- controles ----------------
const IC = {
  power: '<path d="M12 3v9M6.3 6.3a8 8 0 1 0 11.4 0"/>', voz: '<rect x="9" y="3" width="6" height="11" rx="3"/><path d="M5 11a7 7 0 0 0 14 0M12 18v3"/>',
  cam: '<path d="M3 8h4l2-3h6l2 3h4v11H3z"/><circle cx="12" cy="13" r="3.5"/>', jan: '<rect x="3" y="4" width="18" height="16"/><path d="M3 9h18M10 9v11"/>',
  cri: '<path d="M12 3l2.5 6 6.5.5-5 4 1.5 6.5L12 16l-5.5 4 1.5-6.5-5-4 6.5-.5z"/>', mao: '<path d="M8 13V5a1.5 1.5 0 0 1 3 0v6M11 11V4a1.5 1.5 0 0 1 3 0v7M14 11V6a1.5 1.5 0 0 1 3 0v8a6 6 0 0 1-6 6h-1a6 6 0 0 1-5-3l-2-4a1.5 1.5 0 0 1 2.5-1.5L8 13"/>',
  sil: '<path d="M4 9h4l5-4v14l-5-4H4zM17 9l4 6M21 9l-4 6"/>', pri: '<path d="M3 3l18 18M10.6 5.1A10 10 0 0 1 22 12a14 14 0 0 1-3 3.6M6.6 6.6A14 14 0 0 0 2 12s4 7 10 7a9 9 0 0 0 4.4-1.1"/>',
  sen: '<path d="M12 3l8 3v6c0 5-3.5 8-8 9-4.5-1-8-4-8-9V6z"/><circle cx="12" cy="11" r="2.5"/>', seg: '<rect x="5" y="11" width="14" height="10"/><path d="M8 11V7a4 4 0 0 1 8 0v4"/>',
  som: '<path d="M4 9h4l5-4v14l-5-4H4zM16 9a4 4 0 0 1 0 6M19 6a8 8 0 0 1 0 12"/>', ponte: '<rect x="7" y="2" width="10" height="20" rx="2"/><path d="M11 18h2"/>',
  cfg: '<circle cx="12" cy="12" r="3"/><path d="M12 2v3M12 19v3M2 12h3M19 12h3M4.9 4.9l2.1 2.1M17 17l2.1 2.1M4.9 19.1L7 17M17 7l2.1-2.1"/>',
};
const TG_PC = [
  ["friday", "power", "SEXTA-FEIRA", "Assistente ligada no PC", () => st.on, (v) => cmd({ type: "friday", on: v }), "lar"],
  ["voice", "voz", "ESCUTA DO PC", "Microfone do PC ouvindo você", () => st.voice, (v) => cmd({ type: "voice", on: v })],
  ["camera", "cam", "VISÃO DO PC", "Câmeras e gestos ligados", () => st.camera, (v) => cmd({ type: "camera", on: v })],
];
const TG_MODOS = [
  ["janela", "jan", "JANELAS POR GESTOS", "Mão aberta troca janela/workspace"], ["criacao", "cri", "CRIAÇÃO", "Modo de criação holográfica"],
  ["mouse", "mao", "MÃO LIVRE (MOUSE)", "Controla o cursor com a mão"], ["silencio", "sil", "SILÊNCIO", "Ela não fala em voz alta"],
  ["privacidade", "pri", "PRIVACIDADE", "Sem câmeras nem gravações"], ["sentinela", "sen", "SENTINELA", "PTZ vigia o quarto e avisa"],
  ["seguranca", "seg", "SEGURANÇA", "Bloqueio e alertas reforçados"],
];
const TG_CEL = [
  ["mic", "voz", "ESCUTA CONTÍNUA", "Celular ouve sem segurar o botão", () => st.micOn, (v) => micLigar(v)],
  ["som", "som", "VOZ DELA NO CELULAR", "Toca a fala da Sexta-Feira aqui", () => somNoCelular(), (v) => { ls.set("som", v ? "1" : "0"); renderControles(); }],
  ["celcam", "cam", "CÂMERA DO CELULAR", "Ela enxerga pelo celular", () => st.camOn, (v) => camLigar(v)],
];
function tgHTML(id, ic, tit, sub, cls = "") {
  return `<button type="button" class="tg ${cls}" data-tg="${id}"><span class="ic"><svg viewBox="0 0 24 24">${IC[ic]}</svg></span><span class="tx"><b>${tit}</b><small>${sub}</small></span><span class="sw"></span></button>`;
}
$("#tgsPC").innerHTML = TG_PC.map(([id, ic, t, s, , , c]) => tgHTML(id, ic, t, s, c)).join("");
$("#tgsModos").innerHTML = TG_MODOS.map(([id, ic, t, s]) => tgHTML("m_" + id, ic, t, s, "lar")).join("");
$("#tgsCel").innerHTML = TG_CEL.map(([id, ic, t, s]) => tgHTML(id, ic, t, s)).join("") +
  tgHTML("ponte", "ponte", "PONTE PC → CELULAR", "Acessibilidade: o PC acende e mexe aqui") + tgHTML("cfg", "cfg", "CONFIGURAR LINK", cfg.host);
function renderControles() {
  const set = (id, v) => { const e = $(`[data-tg="${id}"]`); if (!e) return; e.classList.toggle("on", !!v); e.classList.toggle("esp", v === null || v === undefined); };
  for (const [id, , , , g] of TG_PC) set(id, st.online ? g() : null);
  for (const [id] of TG_MODOS) set("m_" + id, st.online && id in st.modes ? st.modes[id] : null);
  for (const [id, , , , g] of TG_CEL) set(id, g());
  const n = nativo(); set("ponte", n ? n.ponteAtiva() : null);
  const tc = $("#tgCel"); if (tc) tc.classList.toggle("on", st.camOn);
}
document.addEventListener("click", (e) => {
  const b = e.target.closest("[data-tg]"); if (!b) return;
  const id = b.dataset.tg, on = !b.classList.contains("on"); vibrar();
  const pc = TG_PC.find((x) => x[0] === id); if (pc) return pc[5](on);
  if (id.startsWith("m_")) return cmd({ type: "mode", mode: id.slice(2), on });
  const ce = TG_CEL.find((x) => x[0] === id); if (ce) return ce[5](on);
  if (id === "ponte") return ponteChip();
  if (id === "cfg") return abrirSetup();
});
$("#bParar").onclick = () => { cmd({ type: "stop" }, "Parando tudo"); };
const ACOES = [
  ["[ CLIMA HUD ]", { t: "painel", op: "clima" }], ["[ AGENDA FRIDAY ]", { t: "painel", op: "agenda" }], ["[ TELEMETRIA ]", { t: "painel", op: "sistema" }],
  ["[ PLAY / PAUSA ]", { t: "sistema", op: "midia", valor: "play-pause" }], ["[ PRÓXIMA FAIXA ]", { t: "sistema", op: "midia", valor: "next" }], ["[ PRINT TELA ]", { t: "cli", op: "print" }],
  ["[ VOLUME − ]", { t: "sistema", op: "volume", valor: "down" }], ["[ VOLUME + ]", { t: "sistema", op: "volume", valor: "up" }], ["[ LIMPAR HUD ]", { t: "painel", op: "fechar" }],
];
for (const [t, a] of ACOES) {
  const b = document.createElement("button"); b.type = "button"; b.className = "bt"; b.textContent = t;
  b.onclick = () => {
    vibrar();
    if (a.t === "painel" && a.op === "agenda") irAba("agenda");
    enviar({ type: "acao", acao: a });
  };
  $("#acoes").appendChild(b);
}

// ---------------- ponte do PC -> celular ----------------
const nativo = () => (window.Nativo && typeof Nativo.configurar === "function") ? Nativo : null;
function ponteToken() { try { const n = nativo(); if (n && cfg.tok) n.configurar(cfg.tok); } catch {} }
function ponteChip() {
  const n = nativo(); if (!n) return toast("Só no app Android");
  ponteToken();
  if (n.ponteAtiva()) return toast("Ponte ativa: o PC pode acender, desbloquear e mexer no celular", 3500);
  if (!ls.get("ponteDica")) {
    ls.set("ponteDica", "1");
    toast("Se o Android bloquear: Info do app → ⋮ → Permitir configurações restritas. Depois ative em Acessibilidade.", 6000);
    return setTimeout(() => n.abrirInfoApp(), 1800);
  }
  toast("Ative “F.R.I.D.A.Y. · controle pelo PC” em Acessibilidade", 4000); setTimeout(() => n.abrirAcessibilidade(), 1200);
}

// ---------------- tela: prévia + VNC ----------------
let telaLoop, telaUrl = "";
aoMudarAba.push((n) => {
  clearInterval(telaLoop); if (n !== "tela") return;
  const atualiza = async () => {
    if (document.hidden || $("#vnc").classList.contains("open")) return;
    try { const b = await (await api("/api/tela?s=0.35")).blob(); const u = URL.createObjectURL(b); $("#telaImg").src = u; if (telaUrl) URL.revokeObjectURL(telaUrl); telaUrl = u;
      $("#telaH").textContent = new Date().toLocaleTimeString("pt-BR"); } catch {}
  };
  atualiza(); telaLoop = setInterval(atualiza, 1500);
});
let rfb;
function abrirVnc() {
  vibrar(); $("#vnc").classList.add("open");
  try {
    const RFB = (window.NoVNC && (NoVNC.default || NoVNC));
    rfb = new RFB($("#vncTela"), `ws://${cfg.host}/vnc?t=${encodeURIComponent(cfg.tok)}`, { wsProtocols: ["binary"] });
    rfb.scaleViewport = true; rfb.resizeSession = false; rfb.background = "#02070c";
    rfb.qualityLevel = 5; rfb.compressionLevel = 1;
    rfb.addEventListener("connect", () => toast("VNC conectado"));
    rfb.addEventListener("disconnect", (e) => toast(e.detail.clean ? "VNC encerrado" : "VNC indisponível (wayvnc instalado no PC?)", 3500));
  } catch (e) { toast("Falha no VNC: " + e.message); }
}
$("#bVnc").onclick = abrirVnc;
$("#telaImg").onclick = abrirVnc;
$("#vSair").onclick = () => { try { rfb && rfb.disconnect(); } catch {} $("#vnc").classList.remove("open"); };
new MutationObserver(() => { if (!$("#vnc").classList.contains("open") && rfb) { try { rfb.disconnect(); } catch {} rfb = null; } }).observe($("#vnc"), { attributes: true });
$("#vTeclado").onclick = () => {
  try { rfb && rfb.focus(); } catch {}
  const k = document.createElement("input"); k.style.cssText = "position:fixed;opacity:0;top:0"; document.body.appendChild(k); k.focus();
  k.oninput = () => { for (const ch of k.value) { const cp = ch.codePointAt(0); rfb && rfb.sendKey(cp < 256 ? cp : 0x01000000 + cp, null); } k.value = ""; };
  k.onkeydown = (e) => { const m = { Backspace: 0xff08, Enter: 0xff0d, Tab: 0xff09, Escape: 0xff1b }; if (m[e.key]) { rfb && rfb.sendKey(m[e.key], e.code); e.preventDefault(); } };
  k.onblur = () => k.remove();
};

// ---------------- painéis holográficos do daemon ----------------
const HOLO_TIT = { clima: "CLIMA", agenda: "AGENDA", sistema: "SISTEMA", midia: "MÍDIA", plano: "TAREFA" };
function holoCorpo(op, d) {
  if (op === "clima") return `<div class="clima1"><span class="big">${esc(d.temp ?? "--")}°</span><div><div class="d">${esc(d.desc)}</div><div class="c">${esc(String(d.cidade || "").toUpperCase())}</div></div></div>`;
  if (op === "agenda") return `<ul class="lst">${(d.itens || []).map((x) => li(x.quando, x.titulo)).join("") || vazio("SEM COMPROMISSOS")}</ul>`;
  if (op === "sistema") return `<div class="gs" style="grid-template-columns:repeat(3,1fr)">${gauge("CPU", d.cpu)}${gauge("RAM", d.ram)}${gauge("DISCO", d.disco)}</div>`;
  if (op === "midia") return `<div style="text-align:center;font-size:18px">${esc(d.titulo || "Nada tocando")}</div><div style="text-align:center;color:var(--cia)">${esc(d.artista)}</div><div class="vazio" style="text-align:center">${esc(String(d.status || "").toUpperCase())}</div>`;
  if (op === "plano") {
    const tot = Math.max(1, num(d.total) || 1), et = num(d.etapa) || 0, pct = Math.max(0, Math.min(100, (d.fim ? et : Math.max(0, et - 1)) / tot * 100)), ic = { ok: "[OK]", falhou: "[X]", pulado: ">>" };
    return `<div><b style="color:var(--lar)">${esc(et)}/${esc(d.total ?? 0)}</b> ${esc(d.objetivo)}</div><div class="pb"><i style="width:${pct}%"></i></div>` +
      (d.etapas || []).map(([o, e]) => `<div class="etapa ${esc(e)}"><i>${ic[e] || ""}</i><span>${esc(o)}</span></div>`).join("");
  }
  return null;
}
function holo(op, d) {
  const p = $("#holo"); clearTimeout(holo.t);
  if (op === "fechar") return p.classList.remove("open");
  const corpo = holoCorpo(op, d); if (corpo === null) return;
  const tit = op === "plano" ? "TAREFA · " + String(d.titulo || "").toUpperCase() : HOLO_TIT[op];
  p.innerHTML = `<h4>${esc(tit)}<small>TOQUE PARA FECHAR</small></h4>${corpo}`; p.classList.add("open");
  holo.t = setTimeout(() => p.classList.remove("open"), op === "plano" && !d.fim ? 6e5 : 15000);
}
$("#holo").onclick = () => $("#holo").classList.remove("open");

// ---------------- aprovações (WhatsApp, e-mail, sudo) ----------------
const aprov = { fila: [], min: false, editando: false, ocupado: false };
const ACAO_NOME = { "wa.send_chat": "WHATSAPP", "mail.send": "E-MAIL", "sudo.run": "COMANDO SUDO" };
async function aprovCarregar() {
  try { const r = await (await api("/api/aprovacoes")).json(); aprov.fila = (r.itens || []).slice().sort((a, b) => a.criado - b.criado); aprovRender(); } catch {}
}
function aprovReceber(it) {
  const i = aprov.fila.findIndex((x) => x.id === it.id), novo = i < 0;
  if (novo) aprov.fila.push(it); else aprov.fila[i] = it;
  if (novo) { aprov.min = false; vibrar([60, 40, 60]); }
  aprovRender(!novo && aprov.fila[0] && aprov.fila[0].id === it.id);
}
function aprovFim(id, estado, m) {
  const eraAtual = aprov.fila[0] && aprov.fila[0].id === id;
  if (!aprov.fila.some((x) => x.id === id)) return;
  aprov.fila = aprov.fila.filter((x) => x.id !== id);
  if (m) toast(m, 3000); else if (estado) toast(({ aprovada: "Aprovado", rejeitada: "Cancelado", falhou: "Falhou ao executar" })[estado] || estado);
  if (eraAtual) aprovFechar();
  aprovRender();
}
function aprovFechar() { aprov.editando = false; $("#aprEdit").hidden = true; $("#aprTexto").hidden = false; $("#aprAlt").textContent = "ALTERAR"; }
function aprovRender(alterado) {
  const c = $("#aprov"), bd = $("#aprBadge"), it = aprov.fila[0], n = aprov.fila.length;
  bd.textContent = n ? `[!] ${n}` : ""; bd.classList.toggle("on", !!n && aprov.min);
  if (!it || aprov.min) { c.classList.remove("open"); return; }
  if (c.dataset.id !== it.id) aprovFechar();
  c.dataset.id = it.id;
  $("#aprTit").textContent = "APROVAÇÃO · " + (ACAO_NOME[it.acao] || String(it.acao || "AÇÃO").toUpperCase());
  $("#aprFila").textContent = n > 1 ? `1 DE ${n}` : "";
  $("#aprAcao").textContent = it.resumo || it.acao || "";
  $("#aprDest").textContent = it.destino || "—";
  const tx = $("#aprTexto"); tx.textContent = it.texto || "";
  if (alterado) { tx.classList.remove("novo"); void tx.offsetWidth; tx.classList.add("novo"); }
  $("#aprAlt").hidden = !it.editavel;
  c.classList.add("open");
}
async function aprovDecidir(decisao) {
  const it = aprov.fila[0]; if (!it || aprov.ocupado) return;
  if (decisao === "aprovar" && aprov.editando) {
    const t = $("#aprEdit").value.trim();
    if (t && t !== (it.texto || "").trim()) return toast("Envie a alteração antes de aprovar", 3000);
    aprovFechar();
  }
  let texto;
  if (decisao === "alterar") {
    if (!aprov.editando) { aprov.editando = true; const e = $("#aprEdit"); e.value = it.texto || ""; e.hidden = false; $("#aprTexto").hidden = true; $("#aprAlt").textContent = "ENVIAR"; e.focus(); return; }
    texto = $("#aprEdit").value.trim(); if (!texto) return toast("Texto vazio");
  }
  aprov.ocupado = true; $$("#aprBtns button").forEach((b) => b.disabled = true); vibrar(25);
  try {
    const r = await (await api("/api/aprovacoes", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ id: it.id, decisao, texto }) })).json();
    if (!r.ok) { toast(r.msg || "Não foi possível", 3000); aprovCarregar(); }
    else if (decisao === "alterar") { aprovFechar(); if (r.item) aprovReceber(r.item); toast("Texto alterado — confira e aprove"); }
    else aprovFim(it.id, decisao === "aprovar" ? "aprovada" : "rejeitada", r.msg);
  } catch { toast("Falha ao falar com o PC"); }
  aprov.ocupado = false; $$("#aprBtns button").forEach((b) => b.disabled = false);
}
$("#aprOk").onclick = () => aprovDecidir("aprovar");
$("#aprNo").onclick = () => aprov.editando ? aprovFechar() : aprovDecidir("cancelar");
$("#aprAlt").onclick = () => aprovDecidir("alterar");
$("#aprMin").onclick = () => { aprov.min = true; aprovFechar(); aprovRender(); };
$("#aprBadge").onclick = () => { aprov.min = false; aprovRender(); };
new MutationObserver(() => { if (!$("#aprov").classList.contains("open") && aprov.fila.length && !aprov.min) { aprov.min = true; aprovRender(); } }).observe($("#aprov"), { attributes: true });

// ---------------- configuração ----------------
function bootFim() { const b = $("#boot"); if (b) { b.style.opacity = 0; setTimeout(() => b.remove(), 800); } }
function abrirSetup(motivo) { $("#cfHost").value = cfg.host; $("#cfTok").value = cfg.tok; $("#setup").classList.add("open"); if (motivo) toast(motivo); bootFim(); }
$("#cfOk").onclick = async () => {
  cfg.host = $("#cfHost").value.trim().replace(/^https?:\/\//, "").replace(/\/$/, ""); cfg.tok = $("#cfTok").value.trim();
  ls.set("host", cfg.host); ls.set("tok", cfg.tok); try { Nativo.configurarHost && Nativo.configurarHost(cfg.host); } catch {}
  try {
    const r = await (await fetch(http() + "/api/ping", { headers: { "X-Token": cfg.tok } })).json();
    if (!r.auth) return toast("Token incorreto");
    $("#setup").classList.remove("open"); toast("Conectado ao PC"); ponteToken(); conectar();
  } catch { toast("PC inacessível. Tailscale ou Wi-Fi conectado?"); }
};
(() => { const q = new URLSearchParams(location.search); if (q.get("t")) { cfg.tok = q.get("t"); ls.set("tok", cfg.tok); } if (q.get("host")) { cfg.host = q.get("host"); ls.set("host", cfg.host); } })();
document.addEventListener("visibilitychange", () => { if (!document.hidden && st.online) carregarStatus(); });

// ---------------- início ----------------
status(); ponteToken(); carregarVozStatus();
{
  const a0 = new URLSearchParams(location.search).get("aba");
  irAba(["conversa", "agenda", "dev", "cameras", "painel", "controles", "tela"].includes(a0) ? a0 : ls.get("aba", "conversa"));
}
if (cfg.tok) {
  conectar();
  setTimeout(() => { if (ls.get("mic", "1") === "1") micLigar(true); if (ls.get("celcam", "1") === "1") camLigar(true); }, 700);
} else {
  // Se estiver no navegador do próprio PC (localhost), busca o token localmente de forma transparente
  if (typeof window !== "undefined" && window.location && (window.location.hostname === "127.0.0.1" || window.location.hostname === "localhost")) {
    fetch("/api/local_token").then(r => r.json()).then(d => {
      if (d && d.token) {
        cfg.tok = d.token;
        ls.set("tok", d.token);
        conectar();
        bootFim();
      } else {
        abrirSetup();
      }
    }).catch(() => {
      if (localOk()) { bootFim(); status(); } else abrirSetup();
    });
  } else if (localOk()) {
    bootFim();
    status();
  } else {
    abrirSetup();
  }
}
setTimeout(bootFim, 2400);
