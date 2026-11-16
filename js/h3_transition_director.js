// ZZZ H3 Transition Director — GUI a timeline (stile Director Rambla).
// Due clip (A, B) spostabili/rifilabili: sovrapposte = transizione sovrapposta, lontane = ponte generato, attaccate = taglio.
// Ancore (immagini guida) e segmenti di prompt sulla timeline. Tutto finisce nel widget nascosto `timeline_data`.
import { app } from "../../scripts/app.js";
import { api } from "../../scripts/api.js";

const NODE = "zzz_H3_TransitionDirector";
const FPS = 24;
const MIN_PROMPT = 12;           // frame (0.5 s): sotto questa durata H3 non rispetta il segmento
const L = { ruler: 26, clip: 66, anchor: 30, prompt: 42, label: 74, pad: 6, grip: 10 };
const thumbCache = new Map();   // "nome|frame" -> Image
const COL = { A: "#3d7fd9", B: "#d9773d", sovrapposta: "rgba(255,170,40,0.30)", ponte: "rgba(80,170,255,0.30)",
  taglio: "rgba(190,110,255,0.30)", ctx: "rgba(255,255,255,0.10)", head: "#ff4d4d", prompt: "#3f8f5f", anchor: "#ffd166" };
const MODE_TXT = { sovrapposta: "SOVRAPPOSTA — la parte sovrapposta viene rigenerata", ponte: "PONTE — il buco viene generato",
  taglio: "TAGLIO — raccordo a cavallo del taglio (durata A + B)" };

const clamp = (v, a, b) => Math.min(b, Math.max(a, v));
const fmt = (f) => { const s = f / FPS; const m = Math.floor(s / 60); return `${m}:${(s - m * 60).toFixed(2).padStart(5, "0")}`; };
const uid = () => Math.random().toString(36).slice(2, 9);
const W = (n, name) => (n.widgets || []).find((w) => w.name === name);
function show(w) { if (!w || !w._zzzHid) return; w.hidden = false; delete w.computeSize; if (w.element) w.element.style.display = ""; w.type = w._zzzType; w._zzzHid = false; }
function softHide(w) { if (!w || w._zzzHid) return; w._zzzType = w.type; w._zzzHid = true; hide(w); }
const ALWAYS_HIDDEN = ["video_a", "video_b", "sfuma_A_dentro", "sfuma_A_fuori", "sfuma_B_dentro", "sfuma_B_fuori", "curva_sfumatura", "oltre_limite_H3"];
const hideAlways = (node) => { for (const k of ALWAYS_HIDDEN) softHide(W(node, k)); node.setDirtyCanvas?.(true, true); };
const AUTO_OFF = ["scena", "finale", "overall_soundscape", "non_diegetic_music"];
function syncAuto(node) {
  const on = !!W(node, "automatico")?.value;
  for (const k of AUTO_OFF) on ? softHide(W(node, k)) : show(W(node, k));
  const idea = W(node, "idea_transizione");
  if (idea) { idea.label = "GLOBAL PROMPT"; if (idea.element) idea.element.placeholder = "GLOBAL PROMPT — l'idea della transizione in una riga (correzioni comprese)"; }
  on ? show(idea) : softHide(idea);
  node.setDirtyCanvas?.(true, true);
}
function hide(w) { if (!w) return; w.hidden = true; w.computeSize = () => [0, -4]; if (w.element) w.element.style.display = "none"; w.type = "converted-widget"; }
const viewUrl = (img) => { const i = img.lastIndexOf("/"); const sub = i >= 0 ? img.slice(0, i) : "", fn = i >= 0 ? img.slice(i + 1) : img;
  return api.apiURL(`/view?filename=${encodeURIComponent(fn)}&subfolder=${encodeURIComponent(sub)}&type=input`); };

function css() {
  if (document.getElementById("zzz-h3td-css")) return;
  const s = document.createElement("style"); s.id = "zzz-h3td-css";
  s.textContent = `
  .h3td{display:flex;flex-direction:column;gap:6px;background:#15171b;border:1px solid #2b2f36;border-radius:8px;padding:8px;color:#d8dde6;font:12px/1.3 system-ui,sans-serif;box-sizing:border-box;height:100%}
  .h3td .bar{display:flex;flex-wrap:wrap;gap:5px;align-items:center}
  .h3td button{background:#262b33;color:#e6ebf2;border:1px solid #3a414c;border-radius:5px;padding:4px 9px;cursor:pointer;font:600 12px system-ui}
  .h3td button:hover{background:#323946}.h3td button.a{border-color:${COL.A}}.h3td button.b{border-color:${COL.B}}
  .h3td button.k{border-color:${COL.anchor}}.h3td button.p{border-color:${COL.prompt}}
  .h3td .mon{position:relative;display:flex;gap:6px;justify-content:center;background:#000;border-radius:6px;height:190px;overflow:hidden}
  .h3td .mon video,.h3td .mon img.anc{height:100%;max-width:100%;object-fit:contain}
  .h3td .mon .tag{position:absolute;left:8px;top:6px;background:rgba(0,0,0,.65);padding:2px 7px;border-radius:4px;font-weight:700}
  .h3td .mon .tc{position:absolute;right:8px;top:6px;background:rgba(0,0,0,.65);padding:2px 7px;border-radius:4px;font-family:monospace}
  .h3td canvas{width:100%;display:block;border-radius:6px;background:#1b1e24;cursor:default}
  .h3td .info{min-height:30px;padding:4px 8px;border-radius:5px;background:#1f232a;white-space:pre-wrap}
  .h3td .info.err{background:#4a1d1d;color:#ffd0d0}
  .h3td .ed{position:absolute;z-index:20;background:#1f232a;border:1px solid ${COL.prompt};border-radius:6px;padding:6px;display:flex;flex-direction:column;gap:4px}
  .h3td .ed textarea{width:420px;height:90px;background:#111;color:#eee;border:1px solid #333;border-radius:4px;font:12px system-ui}
  .h3td .ldr{display:flex;gap:8px}
  .h3td .ldc{flex:1;min-width:0;display:flex;gap:8px;background:#1a1d23;border:1px solid #2b2f36;border-left:4px solid #888;border-radius:8px;padding:6px}
  .h3td .ldc.a{border-left-color:${COL.A}}.h3td .ldc.b{border-left-color:${COL.B}}
  .h3td .ldi{height:84px;width:150px;object-fit:cover;border-radius:5px;background:#000;flex:none}
  .h3td .ldb{display:flex;flex-direction:column;gap:4px;min-width:0;flex:1;justify-content:center}
  .h3td .ldt{font-weight:700;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
  .h3td .ldm{opacity:.7;font-size:11px}
  .h3td .ldr2{display:flex;gap:5px}.h3td .ldr2 select{flex:1;min-width:0;background:#111;color:#ddd;border:1px solid #333;border-radius:4px;font:11px system-ui}
  .h3td .hint{opacity:.6;font-size:11px}
  .h3td .menu{position:absolute;z-index:30;background:#20242b;border:1px solid #3a414c;border-radius:6px;padding:4px;min-width:220px;max-height:320px;overflow:auto;box-shadow:0 6px 20px rgba(0,0,0,.5)}
  .h3td .menu div{padding:5px 9px;border-radius:4px;cursor:pointer;white-space:nowrap}
  .h3td .menu div:hover{background:#334}.h3td .menu .sep{height:1px;background:#3a414c;margin:3px 0;padding:0;cursor:default}
  .h3td .menu .ttl{opacity:.6;cursor:default;font-weight:700}.h3td .menu .ttl:hover{background:none}
  .h3td textarea.inl{position:absolute;z-index:25;background:#0f1a13;color:#eaffef;border:2px solid #5fd08f;border-radius:5px;font:12px/1.35 system-ui;padding:4px 6px;resize:none;box-sizing:border-box}`;
  document.head.appendChild(s);
}

class TransitionDirector {
  constructor(node) {
    this.node = node; this.data = { a: {}, b: {}, anchors: [], prompts: [] };
    this.info = { a: null, b: null }; this.plan = null; this.err = null;
    this.head = 0; this.view = { start: -10, scale: 4 }; this.sel = null; this.drag = null; this.playing = false;
    this.build(); this.load();
    // se timeline_data o i video cambiano da fuori (workflow caricato, modifica via API) la GUI si riallinea
    this._last = W(node, "timeline_data")?.value;
    this._names = [W(node, "video_a")?.value, W(node, "video_b")?.value].join("|");
    setInterval(() => {
      if (!this.root.isConnected || this.drag) return;
      const v = W(node, "timeline_data")?.value, n = [W(node, "video_a")?.value, W(node, "video_b")?.value].join("|");
      if (n !== this._names) { this._names = n; this.refreshInfo(true); }
      if (v !== this._last) { this._last = v; this.load(); }
    }, 800);
  }

  // ---------- DOM ----------
  build() {
    css();
    const root = this.root = document.createElement("div"); root.className = "h3td"; root.style.position = "relative";
    const bar = document.createElement("div"); bar.className = "bar";
    const btn = (txt, cls, fn, title) => { const b = document.createElement("button"); b.textContent = txt; if (cls) b.className = cls; b.title = title || ""; b.onclick = (e) => { e.stopPropagation(); fn(); }; bar.appendChild(b); return b; };
    this.playBtn = btn("▶ Play", "", () => this.togglePlay(), "Riproduce la timeline (barra spaziatrice)");
    btn("◆ FRAME RIFERIMENTO TRANSIZIONE", "k", () => this.anchorFromFrame(), "Usa il frame sotto il cursore come immagine di riferimento (ancora) della transizione");
    btn("🖼 Ancora da file", "k", () => this.anchorFromFile(), "Carica un'immagine guida al punto del cursore");
    btn("✎ + Prompt", "p", () => this.addPrompt(), "Aggiunge un segmento di prompt al cursore (min 0,5 s)");
    btn("✂ Dividi al cursore", "", () => this.splitAtHead(), "Un video solo: lo divide al cursore in A e B (stesso file) con 1 s di spazio. Poi rifila le parti e spostale: si rigenera solo il raccordo");
    this.snapBtn = btn("", "", () => { this.data.snap_enabled = this.data.snap_enabled === false; this.updateSnap(); this.save(); }, "Aggancia i bordi delle clip quando sono vicini (B attaccata ad A = taglio). Sovrapposta o lontana: il modo si calcola da solo");
    this.updateSnap();
    btn("⤢ Adatta", "", () => this.fit(), "Adatta lo zoom alla timeline");
    root.appendChild(bar);

    const ld = document.createElement("div"); ld.className = "ldr"; this.ldr = {};
    for (const k of ["a", "b"]) {
      const wn = k === "a" ? "video_a" : "video_b";
      const card = document.createElement("div"); card.className = "ldc " + k;
      const img = document.createElement("img"); img.className = "ldi";
      const body = document.createElement("div"); body.className = "ldb";
      const ttl = document.createElement("div"); ttl.className = "ldt";
      const meta = document.createElement("div"); meta.className = "ldm";
      const row = document.createElement("div"); row.className = "ldr2";
      const b1 = document.createElement("button"); b1.className = k; b1.textContent = "📂 Load video"; b1.title = `Carica dal PC il video ${k.toUpperCase()}`;
      b1.onclick = (e) => { e.stopPropagation(); this.pickVideo(wn); };
      const bx = document.createElement("button"); bx.textContent = "✕"; bx.title = `Togli il video ${k.toUpperCase()}`;
      bx.onclick = (e) => { e.stopPropagation(); this.clearVideo(wn); };
      row.append(b1, bx); body.append(ttl, meta, row); card.append(img, body); ld.appendChild(card);
      this.ldr[k] = { img, ttl, meta, key: null };
    }
    root.appendChild(ld);
    api.fetchApi("/zzz_h3td/videos").then((r) => r.json()).then((v) => { this._vids = v; this.updateLoaders(true); }).catch(() => {});

    const mon = this.mon = document.createElement("div"); mon.className = "mon";
    this.vA = document.createElement("video"); this.vB = document.createElement("video");
    for (const v of [this.vA, this.vB]) { v.muted = true; v.preload = "auto"; v.playsInline = true; mon.appendChild(v); }
    this.ancImg = document.createElement("img"); this.ancImg.className = "anc"; this.ancImg.style.display = "none"; mon.appendChild(this.ancImg);
    this.tag = document.createElement("div"); this.tag.className = "tag"; mon.appendChild(this.tag);
    this.tc = document.createElement("div"); this.tc.className = "tc"; mon.appendChild(this.tc);
    root.appendChild(mon);

    const cv = this.cv = document.createElement("canvas"); root.appendChild(cv);
    this.infoEl = document.createElement("div"); this.infoEl.className = "info"; root.appendChild(this.infoEl);
    const hint = document.createElement("div"); hint.className = "hint";
    hint.textContent = "Clip: trascina per spostare, maniglie ai bordi per rifilare, tasto destro = sostituisci video · trascina un video dal PC sulla traccia A o B · " +
      "Prompt: doppio clic per scrivere direttamente nel blocco (Invio conferma, Shift+Invio a capo), trascina per spostare, maniglie bianche per allungare/accorciare, doppio clic sulla riga vuota = nuovo prompt · " +
      "clic sul righello = cursore · rotella = zoom · Shift+rotella = scorri · Canc = elimina";
    root.appendChild(hint);

    cv.addEventListener("pointerdown", (e) => { this.closeMenu(); if (e.button === 2) return; this.down(e); });
    cv.addEventListener("pointermove", (e) => this.move(e));
    cv.addEventListener("pointerup", (e) => this.up(e));
    cv.addEventListener("dblclick", (e) => this.dbl(e));
    cv.addEventListener("contextmenu", (e) => { e.preventDefault(); e.stopPropagation(); this.context(e); });
    cv.addEventListener("dragover", (e) => { e.preventDefault(); e.stopPropagation(); });
    cv.addEventListener("drop", (e) => { e.preventDefault(); e.stopPropagation(); this.dropFile(e); });
    cv.addEventListener("wheel", (e) => { e.preventDefault(); e.stopPropagation(); this.wheel(e); }, { passive: false });
    root.tabIndex = 0;
    root.addEventListener("keydown", (e) => {
      if (e.target.tagName === "TEXTAREA") return;
      if (e.key === " ") { e.preventDefault(); this.togglePlay(); }
      if ((e.key === "Delete" || e.key === "Backspace") && this.sel) { e.preventDefault(); this.remove(this.sel.kind, this.sel.item); }
      if (e.key === "ArrowLeft") { this.setHead(this.head - (e.shiftKey ? 10 : 1)); }
      if (e.key === "ArrowRight") { this.setHead(this.head + (e.shiftKey ? 10 : 1)); }
    });
    new ResizeObserver(() => this.draw()).observe(root);
  }

  // ---------- dati ----------
  load() {
    const w = W(this.node, "timeline_data");
    try { const d = JSON.parse(w?.value || "{}"); if (d && d.a) this.data = Object.assign({ a: {}, b: {}, anchors: [], prompts: [] }, d); } catch (e) { /* vuoto */ }
    this.updateSnap();
    this.inferAnchors();
    this.refreshInfo(true);
  }
  syncAnchors() {   // le ancore legate a un clip (clip + src) seguono il clip quando si sposta o si rifila
    for (const an of this.data.anchors || []) {
      const c = an.clip ? this.data[an.clip] : null;
      if (c && an.src != null && c.pos != null && c.in != null) an.frame = c.pos + (an.src - c.in);
    }
  }
  inferAnchors() {   // ancore vecchie: clip e frame sorgente dal nome file <video>_f<frame>_<hash>.png
    for (const an of this.data.anchors || []) {
      if (an.clip && an.src != null) continue;
      const m = /^(.*)_f(\d+)_[0-9a-fA-F]{6}\.png$/.exec(String(an.image || "").split("/").pop());
      if (!m) continue;
      for (const k of ["a", "b"]) { const v = String(this.vname(k === "a" ? "video_a" : "video_b") || "").split("/").pop().replace(/\.[^.]+$/, ""); if (v === m[1]) { an.clip = k; an.src = Number(m[2]); break; } }
    }
  }
  save() {
    this.syncAnchors();
    const w = W(this.node, "timeline_data"); const s = JSON.stringify(this.data);
    if (w && w.value !== s) { w.value = s; this._last = s; this.node.setDirtyCanvas?.(true, true); }
    clearTimeout(this._st); this._st = setTimeout(() => this.solve(), 220);
    this.draw();
  }
  vname(k) { return W(this.node, k)?.value; }
  async refreshInfo(keep, keepPos) {
    for (const [k, w] of [["a", "video_a"], ["b", "video_b"]]) {
      const name = this.vname(w);
      if (!name || name.startsWith("(")) { this.info[k] = null; continue; }
      if (this.info[k]?.name === name) continue;
      try {
        const r = await api.fetchApi(`/zzz_h3td/info?name=${encodeURIComponent(name)}`); const j = await r.json();
        if (j.error) throw new Error(j.error);
        this.info[k] = { ...j, name };
        const v = k === "a" ? this.vA : this.vB;
        v.src = api.apiURL(`/zzz/video_proxy?filename=${encodeURIComponent(name)}`);
        const c = this.data[k], n = j.tl_frames;
        if (!keep || c.out == null || c.out > n) { c.in = 0; c.out = n; }
        if (c.pos == null || (!keep && !keepPos)) c.pos = k === "a" ? 0 : Math.max(0, (this.data.a.out - this.data.a.in || n) - 31);
      } catch (e) { this.info[k] = null; this.err = `${w}: ${e.message}`; }
    }
    this.save(); this.fit();
  }
  len(k) { const c = this.data[k]; return (c.out ?? 0) - (c.in ?? 0); }
  span(k) { const c = this.data[k]; return [c.pos ?? 0, (c.pos ?? 0) + this.len(k)]; }
  total() { const [, ea] = this.span("a"), [, eb] = this.span("b"); return Math.max(ea, eb, 1); }

  async solve() {
    const a = this.vname("video_a"), b = this.vname("video_b");
    if (!this.info.a || !this.info.b) { this.plan = null; this.err = "Carica le clip A e B"; this.updInfo(); return; }
    try {
      const r = await api.fetchApi("/zzz_h3td/solve", { method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ video_a: a, video_b: b, timeline: JSON.stringify(this.data), contesto: W(this.node, "contesto")?.value ?? 22, zona_minima: W(this.node, "zona_minima")?.value ?? 24, zona_automatica: W(this.node, "zona_automatica")?.value !== false, transition_zone: W(this.node, "transition_zone")?.value || "medium" }) });
      const j = await r.json();
      this.plan = j.plan || null; this.err = j.error || null;
      // segmenti legati alla zona: se la zona cambia (clip spostate/rifilate) i prompt si ridistribuiscono in proporzione
      const p = this.plan;
      if (p && W(this.node, "zona_automatica")?.value !== false) {
        const z = this.data.zone;
        if (Array.isArray(z) && z.length === 2 && (z[0] !== p.z0 || z[1] !== p.z1) && z[1] > z[0]) {
          const k = (p.z1 - p.z0) / (z[1] - z[0]);
          for (const pr of this.data.prompts || []) { pr.start = Math.round(p.z0 + (pr.start - z[0]) * k); pr.end = Math.round(p.z0 + (pr.end - z[0]) * k); }
          this.data.zone = [p.z0, p.z1]; this.save(); return;
        }
        if (!Array.isArray(z)) { this.data.zone = [p.z0, p.z1]; const w = W(this.node, "timeline_data"); const s = JSON.stringify(this.data); if (w && w.value !== s) { w.value = s; this._last = s; } }
      }
    } catch (e) { this.plan = null; this.err = e.message; }
    this.updInfo(); this.draw();
  }
  updInfo() {
    const el = this.infoEl;
    if (this.err || !this.plan) { el.className = "info err"; el.textContent = this.err || "…"; return; }
    const p = this.plan, z = p.z1 - p.z0, tot = p.t1 - p.t0;
    el.className = "info";
    el.textContent = `${MODE_TXT[p.mode]}\nzona ${p.z0}–${p.z1} (${z} frame, ${(z / FPS).toFixed(2)} s) · contesto A ${p.ca} / B ${p.cb} · ` +
      `finestra H3 ${p.w0}–${p.w1} (${p.L} frame) · video finale ${tot} frame = ${(tot / FPS).toFixed(2)} s` +
      (p.warn?.length ? `\n⚠ ${p.warn.join(" · ")}` : "");
  }

  // ---------- geometria ----------
  rows() {
    const lanes = this.promptLanes();
    let y = L.ruler; const r = {};
    r.b = [y, L.clip]; y += L.clip + 2; r.a = [y, L.clip]; y += L.clip + 6;
    r.anchor = [y, L.anchor]; y += L.anchor + 4;
    r.prompt = [y, L.prompt * Math.max(1, lanes.n)]; y += L.prompt * Math.max(1, lanes.n) + L.pad;
    r.h = y; r.lanes = lanes; return r;
  }
  promptLanes() {
    const ps = [...this.data.prompts].sort((p, q) => p.start - q.start), ends = [], lane = new Map();
    for (const p of ps) { let i = ends.findIndex((e) => e <= p.start); if (i < 0) { i = ends.length; ends.push(0); } ends[i] = p.end; lane.set(p.id, i); }
    return { n: ends.length, lane };
  }
  x(f) { return L.label + (f - this.view.start) * this.view.scale; }
  f(x) { return Math.round((x - L.label) / this.view.scale + this.view.start); }
  fit() {
    const w = this.cv.clientWidth || 800, tot = this.total();
    this.view.scale = Math.max(0.5, (w - L.label - 20) / (tot + 20)); this.view.start = -10; this.draw();
  }

  // ---------- disegno ----------
  updateLoaders(force) {
    if (!this.ldr) return;
    for (const k of ["a", "b"]) {
      const L_ = this.ldr[k], name = this.vname(k === "a" ? "video_a" : "video_b"), inf = this.info[k], c = this.data[k] || {};
      const key = [name, inf?.tl_frames, c.in, this._vids?.length].join("|");
      if (!force && L_.key === key) continue; L_.key = key;
      const ok = name && !String(name).startsWith("(");
      L_.ttl.textContent = ok ? `CLIP ${k.toUpperCase()} · ${name}` : `CLIP ${k.toUpperCase()} · nessun video`;
      L_.meta.textContent = inf ? `${(inf.tl_frames / FPS).toFixed(2)} s · ${Number(inf.fps).toFixed(2)} fps · ${inf.width}×${inf.height} · ${inf.has_audio ? "con audio" : "senza audio"}` : (ok ? "lettura…" : "premi Load video");
      if (ok) L_.img.src = api.apiURL(`/zzz_h3td/thumb?name=${encodeURIComponent(name)}&frame=${c.in ?? 0}&h=168`); else L_.img.removeAttribute("src");
    }
  }
  draw() {
    this.updateLoaders();
    const cv = this.cv, R = this.rows(), dpr = window.devicePixelRatio || 1, w = cv.clientWidth || 800;
    cv.style.height = R.h + "px"; cv.width = w * dpr; cv.height = R.h * dpr;
    const g = cv.getContext("2d"); g.setTransform(dpr, 0, 0, dpr, 0, 0); g.clearRect(0, 0, w, R.h);
    g.font = "11px system-ui"; g.textBaseline = "middle";
    // etichette
    g.fillStyle = "#11141a"; g.fillRect(0, 0, L.label, R.h);
    const lab = (t, [y, h], c) => { g.fillStyle = c || "#9aa4b2"; g.fillText(t, 8, y + h / 2); };
    lab("B", R.b, COL.B); lab("A", R.a, COL.A); lab("ANCORE", R.anchor, COL.anchor); lab("PROMPT", R.prompt, "#7fd1a0");
    g.save(); g.beginPath(); g.rect(L.label, 0, w - L.label, R.h); g.clip();
    // righello
    const step = [1, 2, 6, 12, 24, 48, 120, 240].find((s) => s * this.view.scale >= 46) || 480;
    g.fillStyle = "#9aa4b2";
    for (let f = Math.ceil(this.view.start / step) * step; this.x(f) < w; f += step) {
      const x = this.x(f); g.fillRect(x, L.ruler - 8, 1, 8); g.fillText(f % 24 === 0 ? fmt(f) : String(f), x + 3, 9);
    }
    // clip: barra con i fotogrammi del video, maniglie ai bordi; traccia vuota = invito a caricare
    for (const k of ["a", "b"]) {
      const [y, h] = R[k], C = COL[k.toUpperCase()];
      if (!this.info[k]) {
        g.strokeStyle = C; g.setLineDash([6, 4]); g.strokeRect(L.label + 8, y + 4, w - L.label - 16, h - 8); g.setLineDash([]);
        g.fillStyle = C; g.font = "600 12px system-ui";
        g.fillText(`＋ Clic qui o trascina un video per caricare la clip ${k.toUpperCase()}`, L.label + 20, y + h / 2); g.font = "11px system-ui"; continue;
      }
      const [s, e] = this.span(k), x0 = this.x(s), x1 = this.x(e), sel = this.sel?.kind === "clip" && this.sel.item === k;
      g.fillStyle = "#000"; g.fillRect(x0, y + 2, x1 - x0, h - 4);
      this.drawThumbs(g, k, x0, x1, y + 2, h - 4);
      g.fillStyle = C; g.globalAlpha = 0.28; g.fillRect(x0, y + 2, x1 - x0, h - 4); g.globalAlpha = 1;
      g.strokeStyle = sel ? "#fff" : C; g.lineWidth = sel ? 2 : 1.5; g.strokeRect(x0 + 0.5, y + 2.5, x1 - x0 - 1, h - 5); g.lineWidth = 1;
      for (const xe of [x0, x1 - L.grip]) { g.fillStyle = C; g.fillRect(xe, y + 2, L.grip, h - 4); g.fillStyle = "rgba(255,255,255,.8)"; g.fillRect(xe + L.grip / 2 - 1, y + h / 2 - 9, 2, 18); }
      const label = `${k.toUpperCase()} · ${this.info[k].name.split("/").pop()} · da f${this.data[k].in} · ${this.len(k)} f (${(this.len(k) / FPS).toFixed(2)} s)`;
      g.font = "600 11px system-ui"; const tw = g.measureText(label).width;
      g.fillStyle = "rgba(0,0,0,.65)"; g.fillRect(x0 + L.grip + 2, y + 5, tw + 10, 16);
      g.fillStyle = "#fff"; g.fillText(label, x0 + L.grip + 7, y + 13); g.font = "11px system-ui";
    }
    // zona e finestra (sopra le clip, trasparente)
    const p = this.plan;
    if (p) {
      const top = R.b[0], bot = R.a[0] + R.a[1];
      g.fillStyle = COL.ctx; g.fillRect(this.x(p.w0), top, this.x(p.w1) - this.x(p.w0), R.h - top);
      g.fillStyle = COL[p.mode]; g.fillRect(this.x(p.z0), top, this.x(p.z1) - this.x(p.z0), R.h - top);
      g.strokeStyle = "rgba(255,255,255,.7)"; g.setLineDash([4, 3]);
      for (const f of [p.w0, p.w1]) { g.beginPath(); g.moveTo(this.x(f), top); g.lineTo(this.x(f), bot); g.stroke(); }
      g.strokeStyle = "#ffbf5e"; g.setLineDash([]);
      for (const f of [p.z0, p.z1]) { g.beginPath(); g.moveTo(this.x(f), top); g.lineTo(this.x(f), R.h); g.stroke(); }
      g.font = "700 11px system-ui"; const t = p.mode === "ponte" ? "GENERATO" : "RIGENERATO", tw = g.measureText(t).width;
      g.fillStyle = "rgba(0,0,0,.7)"; g.fillRect(this.x(p.z0) + 3, bot - 18, tw + 8, 15);
      g.fillStyle = "#ffbf5e"; g.fillText(t, this.x(p.z0) + 7, bot - 10); g.font = "11px system-ui";
    }
    // ancora B automatica (contesto di B): non si modifica, la calcola il Director
    if (this.plan && this.plan.z1 != null && W(this.node, "ancora_B_automatica")?.value !== false && this.info.b) {
      const fa = this.plan.z1 - 1, x = this.x(fa), [y, h] = R.anchor, cb = this.data.b;
      g.strokeStyle = COL.B; g.lineWidth = 2; g.beginPath(); g.moveTo(x, y + 4); g.lineTo(x + 8, y + h / 2); g.lineTo(x, y + h - 4); g.lineTo(x - 8, y + h / 2); g.closePath(); g.stroke(); g.lineWidth = 1;
      g.fillStyle = "#e9b48f"; g.fillText(`auto · contesto B f${(cb.in ?? 0) + (this.plan.z1 - (cb.pos ?? 0))} · peso 0.15→1`, x + 10, y + h / 2);
    }
    // ancore
    for (const an of this.data.anchors) {
      const x = this.x(an.frame), [y, h] = R.anchor, s = this.sel?.item === an;
      g.fillStyle = s ? "#fff" : COL.anchor; g.beginPath(); g.moveTo(x, y + 4); g.lineTo(x + 8, y + h / 2); g.lineTo(x, y + h - 4); g.lineTo(x - 8, y + h / 2); g.closePath(); g.fill();
      g.strokeStyle = "rgba(255,209,102,.35)"; g.beginPath(); g.moveTo(x, R.b[0]); g.lineTo(x, y); g.stroke();
      g.fillStyle = "#ddd"; g.fillText(`f${an.frame}${an.clip ? ` (${an.clip.toUpperCase()} f${an.src})` : ""} · peso ${this.wTxt(an)}`, x + 10, y + h / 2);
      const ws = an.peso_prima ?? an.peso ?? 1, wp = an.peso ?? 1;
      if (ws !== wp && this.plan) {   // rampa del peso dalla finestra al frame dell'ancora
        g.strokeStyle = "rgba(255,209,102,.8)"; g.beginPath();
        const yy = (v) => y + h - 3 - Math.min(1, v) * (h - 8);
        g.moveTo(this.x(this.plan.w0), yy(ws)); g.lineTo(x, yy(wp)); g.stroke();
      }
    }
    // prompt
    for (const pr of this.data.prompts) {
      if (this._editing === pr) continue;
      const ln = R.lanes.lane.get(pr.id) || 0, y = R.prompt[0] + ln * L.prompt, x0 = this.x(pr.start), x1 = this.x(pr.end), s = this.sel?.item === pr;
      const bh = L.prompt - 6, bw = Math.max(4, x1 - x0);
      g.fillStyle = s ? "#4fb37a" : COL.prompt; g.beginPath(); g.roundRect ? g.roundRect(x0, y + 3, bw, bh, 5) : g.rect(x0, y + 3, bw, bh); g.fill();
      if (s) { g.strokeStyle = "#fff"; g.lineWidth = 2; g.stroke(); g.lineWidth = 1; }
      for (const xe of [x0, x1 - L.grip]) { g.fillStyle = "rgba(0,0,0,.35)"; g.fillRect(xe, y + 3, L.grip, bh); g.fillStyle = "#fff"; g.fillRect(xe + L.grip / 2 - 1, y + 3 + bh / 2 - 8, 2, 16); }
      g.save(); g.beginPath(); g.rect(x0 + L.grip + 2, y, Math.max(0, bw - 2 * L.grip - 4), L.prompt); g.clip();
      g.fillStyle = pr.text ? "#fff" : "rgba(255,255,255,.6)"; g.textBaseline = "top";
      const lines = this.wrap(g, pr.text || "doppio clic per scrivere", bw - 2 * L.grip - 8, 2);
      lines.forEach((t, i) => g.fillText(t, x0 + L.grip + 4, y + 7 + i * 14)); g.textBaseline = "middle"; g.restore();
    }
    // cursore
    const hx = this.x(this.head); g.fillStyle = COL.head; g.fillRect(hx - 1, 0, 2, R.h);
    g.beginPath(); g.moveTo(hx - 6, 0); g.lineTo(hx + 6, 0); g.lineTo(hx, 8); g.fill();
    g.restore();
    this.updMonitor();
  }

  // ---------- monitor ----------
  clipAt(t) {
    const p = this.plan, [sa, ea] = this.span("a"), [sb, eb] = this.span("b");
    const inA = this.info.a && t >= sa && t < ea, inB = this.info.b && t >= sb && t < eb;
    const z = p && t >= p.z0 && t < p.z1;
    if (z) return { k: inA && (!inB || t < (p.z0 + p.z1) / 2) ? "a" : inB ? "b" : null, zone: true };
    if (p && t >= p.z1 && inB) return { k: "b" };
    if (inA) return { k: "a" }; if (inB) return { k: "b" }; return { k: null };
  }
  srcFrame(k, t) { const c = this.data[k]; return c.in + (t - c.pos); }
  updMonitor() {
    const t = this.head, c = this.clipAt(t);
    this.tc.textContent = `${fmt(t)} · f${t}`;
    const an = this.sel?.kind === "anchor" ? this.sel.item : null;
    this.ancImg.style.display = an?.image ? "" : "none"; if (an?.image) this.ancImg.src = viewUrl(an.image);
    for (const k of ["a", "b"]) {
      const v = k === "a" ? this.vA : this.vB;
      v.style.display = c.k === k ? "" : "none";
      if (c.k === k && !this.playing && this.info[k]) { const s = this.srcFrame(k, t) / FPS + 0.5 / FPS; if (Math.abs(v.currentTime - s) > 0.02) v.currentTime = Math.max(0, s); }
    }
    this.tag.textContent = c.zone ? (this.plan.mode === "ponte" ? "ZONA GENERATA (vuota ora)" : `ZONA RIGENERATA · sorgente ${c.k?.toUpperCase()}`) : c.k ? `CLIP ${c.k.toUpperCase()}` : "—";
    this.tag.style.color = c.zone ? "#ffbf5e" : c.k === "a" ? "#8fb8ff" : "#ffb38a";
  }
  setHead(f) { this.head = clamp(Math.round(f), Math.min(0, this.data.a.pos ?? 0), this.total()); this.draw(); }
  togglePlay() {
    this.playing = !this.playing; this.playBtn.textContent = this.playing ? "⏸ Pausa" : "▶ Play";
    if (!this.playing) { this.vA.pause(); this.vB.pause(); this.draw(); return; }
    if (this.head >= this.total() - 1) this.head = 0;
    let last = performance.now(), acc = 0, cur = null;
    const tick = (now) => {
      if (!this.playing) return;
      acc += (now - last) / 1000 * FPS; last = now;
      if (acc >= 1) { const n = Math.floor(acc); acc -= n; this.head += n; }
      if (this.head >= this.total()) { this.togglePlay(); return; }
      const c = this.clipAt(this.head);
      if (c.k !== cur) { for (const v of [this.vA, this.vB]) v.pause(); cur = c.k;
        if (c.k) { const v = c.k === "a" ? this.vA : this.vB; v.currentTime = this.srcFrame(c.k, this.head) / FPS; v.play().catch(() => {}); } }
      this.draw(); requestAnimationFrame(tick);
    };
    requestAnimationFrame(tick);
  }

  // ---------- interazione ----------
  pointer(e) {   // il canvas puo' essere scalato (zoom del grafo): px schermo -> px CSS del canvas
    const r = this.cv.getBoundingClientRect();
    return { x: (e.clientX - r.left) * this.cv.clientWidth / (r.width || 1), y: (e.clientY - r.top) * this.cv.clientHeight / (r.height || 1) };
  }
  hit(e) {
    const { x, y } = this.pointer(e), R = this.rows();
    const inRow = ([ry, rh]) => y >= ry && y < ry + rh;
    if (y < L.ruler) return { kind: "ruler", x, y };
    for (const an of this.data.anchors) if (inRow(R.anchor) && Math.abs(this.x(an.frame) - x) <= 9) return { kind: "anchor", item: an, x, y };
    for (const pr of this.data.prompts) {
      const ln = R.lanes.lane.get(pr.id) || 0, ry = R.prompt[0] + ln * L.prompt;
      if (y >= ry && y < ry + L.prompt) { const x0 = this.x(pr.start), x1 = this.x(pr.end), g = Math.min(L.grip + 2, (x1 - x0) / 3);
        if (x >= x0 - 3 && x <= x1 + 3) return { kind: "prompt", item: pr, edge: x - x0 < g ? "l" : x1 - x < g ? "r" : null, x, y }; }
    }
    if (inRow(R.prompt)) return { kind: "promptRow", x, y };
    for (const k of ["b", "a"]) {
      if (!inRow(R[k])) continue;
      if (!this.info[k]) return { kind: "emptyTrack", item: k, x, y };
      const [s, e2] = this.span(k), x0 = this.x(s), x1 = this.x(e2), g = Math.min(L.grip + 2, (x1 - x0) / 3);
      if (x >= x0 - 3 && x <= x1 + 3) return { kind: "clip", item: k, edge: x - x0 < g ? "l" : x1 - x < g ? "r" : null, x, y };
      return { kind: "track", item: k, x, y };
    }
    return { kind: "empty", x, y };
  }
  down(e) {
    this.root.focus(); const h = this.hit(e);
    if (h.kind === "emptyTrack") { this.pickVideo(h.item === "a" ? "video_a" : "video_b"); return; }
    this.cv.setPointerCapture(e.pointerId);
    if (["ruler", "empty", "track", "promptRow"].includes(h.kind)) { this.sel = null; this.drag = { kind: "head" }; this.setHead(this.f(h.x)); return; }
    this.sel = { kind: h.kind, item: h.item };
    const f0 = this.f(h.x);
    if (h.kind === "clip") { const c = this.data[h.item]; this.drag = { kind: "clip", k: h.item, edge: h.edge, f0, c0: { ...c } }; }
    else if (h.kind === "anchor") { this.drag = { kind: "anchor", item: h.item, f0, v0: h.item.frame }; this.setHead(h.item.frame); }
    else if (h.kind === "prompt") this.drag = { kind: "prompt", item: h.item, edge: h.edge, f0, s0: h.item.start, e0: h.item.end };
    this.draw();
  }
  updateSnap() { if (this.snapBtn) this.snapBtn.textContent = `Snap: ${this.data.snap_enabled === false ? "OFF" : "ON"}`; }
  snap(f, k) {   // calamita sui bordi dell'altra clip e sul cursore
    if (this.data.snap_enabled === false) return f;
    const o = k === "a" ? "b" : "a", tgt = [...(this.info[o] ? this.span(o) : []), this.head], tol = 6 / this.view.scale;
    for (const t of tgt) if (Math.abs(f - t) <= tol) return t; return f;
  }
  move(e) {
    const h = this.drag;
    if (!h) { const t = this.hit(e); this.cv.style.cursor = t.edge ? "ew-resize" : (t.kind === "clip" || t.kind === "prompt" || t.kind === "anchor") ? "grab" : "default"; return; }
    const f = this.f(this.pointer(e).x), d = f - h.f0;
    if (h.kind === "head") { this.setHead(f); return; }
    if (h.kind === "clip") {
      const c = this.data[h.k], c0 = h.c0, n = this.info[h.k].tl_frames;
      if (!h.edge) { let pos = c0.pos + d; const e2 = pos + (c0.out - c0.in); const sp = this.snap(pos, h.k), se = this.snap(e2, h.k);
        if (sp !== pos) pos = sp; else if (se !== e2) pos = se - (c0.out - c0.in); c.pos = pos; }
      else if (h.edge === "l") { const nin = clamp(c0.in + d, 0, c0.out - 5); c.in = nin; c.pos = c0.pos + (nin - c0.in); }
      else { const target = this.snap(c0.pos + (c0.out - c0.in) + d, h.k); c.out = clamp(c0.in + (target - c0.pos), c0.in + 5, n); }
      if (h.k === "b" && c.pos < (this.data.a.pos || 0)) c.pos = this.data.a.pos || 0;
      this.save(); return;
    }
    if (h.kind === "anchor") { const an = h.item; an.frame = Math.max(0, h.v0 + d); this.head = an.frame; if (an.clip && this.data[an.clip]) an.src = this.srcFrame(an.clip, an.frame); this.save(); return; }
    if (h.kind === "prompt") {
      const it = h.item;
      if (!h.edge) { it.start = Math.max(0, h.s0 + d); it.end = it.start + (h.e0 - h.s0); }
      else if (h.edge === "l") it.start = clamp(h.s0 + d, 0, h.e0 - MIN_PROMPT);
      else it.end = Math.max(h.s0 + MIN_PROMPT, h.e0 + d);
      this.save();
    }
  }
  up(e) {
    if (this.drag?.kind === "clip") this.normalize();
    this.drag = null; try { this.cv.releasePointerCapture(e.pointerId); } catch (_) { /* */ }
    this.save();
  }
  normalize() {   // la timeline parte sempre da 0 con l'inizio di A
    const d = this.data.a.pos || 0; if (!d) return;
    for (const k of ["a", "b"]) this.data[k].pos -= d;
    for (const an of this.data.anchors) an.frame -= d;
    for (const pr of this.data.prompts) { pr.start -= d; pr.end -= d; }
    this.head -= d;
  }
  wheel(e) {
    if (e.shiftKey) { this.view.start += (e.deltaY > 0 ? 1 : -1) * 40 / this.view.scale; this.draw(); return; }
    const px = this.pointer(e).x, fx = this.f(px);
    this.view.scale = clamp(this.view.scale * (e.deltaY > 0 ? 0.85 : 1.18), 0.3, 40);
    this.view.start = fx - (px - L.label) / this.view.scale; this.draw();
  }
  dbl(e) {
    const h = this.hit(e);
    if (h.kind === "prompt") this.editPrompt(h.item);
    else if (h.kind === "promptRow") this.addPrompt(this.f(h.x));
  }

  // ---------- menu tasto destro ----------
  closeMenu() { this.root.querySelector(".menu")?.remove(); }
  menu(e, items) {
    this.closeMenu();
    const m = document.createElement("div"); m.className = "menu";
    const rr = this.root.getBoundingClientRect(), sc = this.root.clientWidth / (rr.width || 1);
    m.style.left = Math.min((e.clientX - rr.left) * sc, this.root.clientWidth - 240) + "px"; m.style.top = ((e.clientY - rr.top) * sc) + "px";
    for (const it of items) {
      const d = document.createElement("div");
      if (it === "-") d.className = "sep"; else if (it.title) { d.className = "ttl"; d.textContent = it.title; }
      else { d.textContent = it.label; d.onclick = (ev) => { ev.stopPropagation(); this.closeMenu(); it.fn(); }; }
      m.appendChild(d);
    }
    m.addEventListener("pointerdown", (ev) => ev.stopPropagation());
    this.root.appendChild(m);
    setTimeout(() => document.addEventListener("pointerdown", () => this.closeMenu(), { once: true }), 0);
  }
  async context(e) {
    const h = this.hit(e);
    if (h.kind === "clip" || h.kind === "emptyTrack" || h.kind === "track") {
      const k = h.item, wn = k === "a" ? "video_a" : "video_b", K = k.toUpperCase();
      let vids = [];
      try { vids = await (await api.fetchApi("/zzz_h3td/videos")).json(); } catch (_) { /* */ }
      const items = [{ title: `CLIP ${K}${this.info[k] ? " · " + this.info[k].name : ""}` },
        { label: "🔁 Sostituisci con un file dal PC…", fn: () => this.pickVideo(wn, true) }];
      if (this.vname(wn) && !String(this.vname(wn)).startsWith("(")) items.push({ label: "🗑 Elimina video " + K, fn: () => this.clearVideo(wn) });
      if (this.info[k]) {
        items.push({ label: "↔ Usa tutta la durata del video", fn: () => { const c = this.data[k]; c.pos -= c.in; c.in = 0; c.out = this.info[k].tl_frames; this.save(); } });
        items.push({ label: "⇤ Inizio clip al cursore (IN)", fn: () => { const c = this.data[k], d = this.head - c.pos; if (d > 0 && d < this.len(k) - 5) { c.in += d; c.pos += d; this.save(); } } });
        items.push({ label: "⇥ Fine clip al cursore (OUT)", fn: () => { const c = this.data[k], d = this.head - c.pos; if (d > 5 && d < this.len(k)) { c.out = c.in + d; this.save(); } } });
      }
      this.menu(e, items); return;
    }
    if (h.kind === "prompt") {
      const p = h.item; this.sel = { kind: "prompt", item: p }; this.draw();
      this.menu(e, [{ title: `PROMPT ${fmt(p.start)} → ${fmt(p.end)}` },
        { label: "✎ Modifica testo", fn: () => this.editPrompt(p) },
        { label: "⧉ Duplica dopo", fn: () => { const q = { ...p, id: uid(), start: p.end, end: p.end + (p.end - p.start) }; this.data.prompts.push(q); this.save(); } },
        { label: "⇤ Inizia al cursore", fn: () => { if (this.head < p.end - MIN_PROMPT) { p.start = this.head; this.save(); } } },
        { label: "⇥ Finisci al cursore", fn: () => { if (this.head > p.start + MIN_PROMPT) { p.end = this.head; this.save(); } } },
        "-", { label: "🗑 Elimina", fn: () => this.remove("prompt", p) }]);
      return;
    }
    if (h.kind === "promptRow") { const f = this.f(h.x); this.menu(e, [{ label: "✎ Nuovo prompt qui", fn: () => this.addPrompt(f) }]); return; }
    if (h.kind === "anchor") {
      const a = h.item; this.sel = { kind: "anchor", item: a }; this.draw();
      const setW = (ws, wp) => { a.peso_prima = ws; a.peso = wp; this.save(); };
      this.menu(e, [{ title: `ANCORA f${a.frame} · peso ${this.wTxt(a)}` },
        { title: "Peso (serve il nodo Anchor Attention sul modello):" },
        { label: "● Guida piena: 1 sempre", fn: () => setW(1, 1) },
        { label: "◐ Presenza leggera da subito: 0.05 → 1 al suo frame", fn: () => setW(0.05, 1) },
        { label: "◔ Bassa bassa: 0.05 → 0.3", fn: () => setW(0.05, 0.3) },
        { label: "○ Solo riferimento debole: 0.1 sempre", fn: () => setW(0.1, 0.1) },
        { label: "✎ Personalizza…", fn: () => { const r = window.prompt("Peso all'inizio della finestra → peso al frame dell'ancora (es. 0.05 1)", `${a.peso_prima ?? 1} ${a.peso ?? 1}`);
            if (!r) return; const [x, y] = r.replace(",", ".").split(/[\s;→>-]+/).map(Number); if (!isNaN(x)) setW(clamp(x, 0, 8), clamp(isNaN(y) ? x : y, 0, 8)); } },
        "-", { label: "🖼 Sostituisci immagine…", fn: async () => { const f = await this.pickFile("image/*"); if (f) { a.image = await this.upload(f); this.save(); } } },
        { label: "🗑 Elimina", fn: () => this.remove("anchor", a) }]);
    }
  }
  async dropFile(e) {
    const f = e.dataTransfer?.files?.[0]; if (!f) return;
    const h = this.hit(e);
    if (f.type.startsWith("image/")) { const name = await this.upload(f); const an = { id: uid(), frame: this.f(h.x), image: name }; this.data.anchors.push(an); this.save(); return; }
    const k = h.item === "a" || h.item === "b" ? h.item : (this.info.a ? "b" : "a");
    const name = await this.upload(f); this.setVideo(k === "a" ? "video_a" : "video_b", name, true);
  }
  async splitAtHead() {   // un video unico -> A (prima del cursore) e B (dopo), stesso file; il resto lo decide la timeline
    if (!this.info.a) { this.err = "Carica prima il video su A, poi metti il cursore dove vuoi dividerlo."; this.updInfo(); return; }
    const a = this.data.a, [pa, ea] = this.span("a"), h = this.head;
    const ctx = W(this.node, "contesto")?.value ?? 13, m = Math.max(5, Math.min(ctx, 13));
    if (h <= pa + m || h >= ea - m) { this.err = `Metti il cursore dentro la clip A, ad almeno ${m} frame dai bordi.`; this.updInfo(); return; }
    const cut = this.srcFrame("a", h), name = this.vname("video_a"), w = W(this.node, "video_b"); if (!w) return;
    const vals = w.options?.values;
    if (Array.isArray(vals) && !vals.includes(name)) { try { vals.push(name); } catch (_) { /* */ } }
    w.value = name;
    if (w.value !== name) { try { await app.refreshComboInNodes?.(); } catch (_) { /* */ } w.value = name; }
    if (w.value !== name) { this.err = "Non riesco a impostare B: premi F5 e riprova."; this.updInfo(); return; }
    const out = a.out;
    this.data.a = { in: a.in, out: cut, pos: pa };
    this.data.b = { in: cut, out, pos: h + 24 };   // 1 s di spazio: si rifila e si sposta a mano
    this.info.b = null; this._names = [name, name].join("|");
    this.err = null; this.refreshInfo(true, true); this.node.setDirtyCanvas?.(true, true);
  }
  clearVideo(wname) {   // toglie il video dalla traccia (il nodo restera' da completare prima del run)
    const w = W(this.node, wname); if (!w) return;
    const k = wname === "video_a" ? "a" : "b";
    w.value = ""; this.info[k] = null; this.data[k] = {};
    (k === "a" ? this.vA : this.vB).removeAttribute("src");
    this._names = [this.vname("video_a"), this.vname("video_b")].join("|");
    this.plan = null; this.save(); this.updateLoaders(true);
  }
  async setVideo(wname, name, keepPos) {
    const w = W(this.node, wname); if (!w || !name) return;
    // il combo puo' avere un elenco non estendibile (frontend nuovo): se il valore non "prende", si ricarica l'elenco dal server
    const vals = w.options?.values;
    if (Array.isArray(vals) && !vals.includes(name)) { try { vals.push(name); } catch (_) { /* */ } }
    w.value = name;
    if (w.value !== name) { try { await app.refreshComboInNodes?.(); } catch (_) { /* */ } w.value = name; }
    if (w.value !== name) { this.err = `Non riesco a impostare il video "${name}" sul nodo: premi F5 e riprova.`; this.updInfo(); return; } this._names = [this.vname("video_a"), this.vname("video_b")].join("|");
    const k = wname === "video_a" ? "a" : "b"; this.info[k] = null; this.data[k].in = null; this.data[k].out = null;
    this.refreshInfo(true, keepPos);
  }

  // ---------- disegno: fotogrammi e testo ----------
  drawThumbs(g, k, x0, x1, y, h) {
    const name = this.info[k]?.name; if (!name) return;
    const tw = h * 16 / 9, c = this.data[k], step = Math.max(1, Math.round(tw / this.view.scale / 6) * 6);
    const visL = Math.max(x0, L.label), visR = Math.min(x1, this.cv.clientWidth);
    g.save(); g.beginPath(); g.rect(x0, y, x1 - x0, h); g.clip();
    for (let x = x0; x < x1; x += tw) {
      if (x + tw < visL || x > visR) continue;
      const fr = Math.round((c.in + (x - x0) / this.view.scale) / step) * step, key = `${name}|${fr}`;
      let im = thumbCache.get(key);
      if (!im) { im = new Image(); im.onload = () => { clearTimeout(this._td); this._td = setTimeout(() => this.draw(), 60); };
        im.src = api.apiURL(`/zzz_h3td/thumb?name=${encodeURIComponent(name)}&frame=${fr}&h=72`); thumbCache.set(key, im); }
      if (im.complete && im.naturalWidth) g.drawImage(im, x, y, tw, h);
    }
    g.restore();
  }
  wTxt(a) { const ws = a.peso_prima ?? a.peso ?? 1, wp = a.peso ?? 1; return ws === wp ? `${wp}` : `${ws}→${wp}`; }
  wrap(g, text, maxW, maxLines) {
    const words = String(text).split(/\s+/), out = []; let cur = "";
    for (const wd of words) {
      const t = cur ? cur + " " + wd : wd;
      if (g.measureText(t).width <= maxW || !cur) cur = t; else { out.push(cur); cur = wd; if (out.length >= maxLines) break; }
    }
    if (out.length < maxLines && cur) out.push(cur);
    if (out.length === maxLines && words.join(" ").length > out.join(" ").length) out[maxLines - 1] = out[maxLines - 1].replace(/.{0,2}$/, "…");
    return out;
  }
  remove(kind, item) {
    if (kind === "anchor") this.data.anchors = this.data.anchors.filter((a) => a !== item);
    if (kind === "prompt") this.data.prompts = this.data.prompts.filter((p) => p !== item);
    this.sel = null; this.save();
  }

  // ---------- azioni ----------
  preset(mode) {
    if (!this.info.a || !this.info.b) return;
    const [, ea] = this.span("a");
    this.data.b.pos = mode === "sovrapposta" ? ea - 31 : mode === "taglio" ? ea : ea + 48;
    this.save(); this.fit();
  }
  addPrompt(at) {
    const s = at ?? this.head, p = { id: uid(), start: s, end: s + 24, text: "" };
    this.data.prompts.push(p); this.sel = { kind: "prompt", item: p }; this.save(); this.editPrompt(p);
  }
  editPrompt(p) {   // il testo si scrive DENTRO il blocco della timeline
    this.root.querySelector("textarea.inl")?.remove();
    const R = this.rows(), ln = R.lanes.lane.get(p.id) || 0;
    const cr = this.cv.getBoundingClientRect(), rr = this.root.getBoundingClientRect(), sc = this.root.clientWidth / (rr.width || 1);
    const x0 = Math.max(L.label, this.x(p.start)), x1 = Math.min(this.cv.clientWidth, this.x(p.end));
    const ta = document.createElement("textarea"); ta.className = "inl"; ta.value = p.text || "";
    ta.placeholder = "cosa succede in questo tratto…";
    const w = Math.max(320, x1 - x0);
    ta.style.left = Math.min((cr.left - rr.left) * sc + x0, this.root.clientWidth - w - 10) + "px";
    ta.style.top = ((cr.top - rr.top) * sc + R.prompt[0] + ln * L.prompt + 2) + "px";
    ta.style.width = w + "px"; ta.style.height = "86px";
    this._editing = p; this.draw();
    let done = false;
    const finish = (keep) => { if (done) return; done = true; if (keep) p.text = ta.value.trim(); this._editing = null; ta.remove(); this.save(); };
    ta.addEventListener("keydown", (e) => { e.stopPropagation();
      if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); finish(true); }
      if (e.key === "Escape") finish(false); });
    ta.addEventListener("blur", () => finish(true));
    ta.addEventListener("pointerdown", (e) => e.stopPropagation());
    this.root.appendChild(ta); setTimeout(() => { ta.focus(); ta.setSelectionRange(ta.value.length, ta.value.length); }, 0);
  }
  async anchorFromFrame() {
    const c = this.clipAt(this.head); if (!c.k) return;
    const name = this.vname(c.k === "a" ? "video_a" : "video_b");
    const r = await api.fetchApi("/zzz_h3td/grab", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ name, frame: this.srcFrame(c.k, this.head) }) });
    const j = await r.json(); if (j.error) { this.err = j.error; this.updInfo(); return; }
    const an = { id: uid(), frame: this.head, image: j.image, clip: c.k, src: this.srcFrame(c.k, this.head) }; this.data.anchors.push(an); this.sel = { kind: "anchor", item: an }; this.save();
  }
  async upload(file) {
    const fd = new FormData(); fd.append("image", file); fd.append("type", "input"); fd.append("overwrite", "true");
    const r = await api.fetchApi("/upload/image", { method: "POST", body: fd });
    if (!r.ok) {   // ComfyUI rifiuta i file oltre --max-upload-size (default 100 MB)
      const mb = (file.size / 1048576).toFixed(0);
      this.err = r.status === 413 ? `"${file.name}" (${mb} MB) supera il limite di upload di ComfyUI (100 MB di default). ` +
        "Avvia ComfyUI con --max-upload-size 4096 (nel .bat di avvio) per caricare video grandi."
        : `Upload fallito (${r.status}) per "${file.name}"`;
      this.updInfo(); throw new Error(this.err);
    }
    const j = await r.json();
    return j.subfolder ? `${j.subfolder}/${j.name}` : j.name;
  }
  pickFile(accept) { return new Promise((res) => { const i = document.createElement("input"); i.type = "file"; i.accept = accept; i.onchange = () => res(i.files[0] || null); i.click(); }); }
  async anchorFromFile() {
    const f = await this.pickFile("image/*"); if (!f) return;
    const name = await this.upload(f); const an = { id: uid(), frame: this.head, image: name };
    this.data.anchors.push(an); this.sel = { kind: "anchor", item: an }; this.save();
  }
  async pickVideo(wname, keepPos) {
    const f = await this.pickFile("video/*,.mov,.mkv,.mp4,.webm"); if (!f) return;
    const name = await this.upload(f); this.setVideo(wname, name, !!keepPos);
  }
}

app.registerExtension({
  name: "zzz.H3TransitionDirector",
  async beforeRegisterNodeDef(nodeType, nodeData) {
    if (nodeData.name !== NODE) return;
    const onCreated = nodeType.prototype.onNodeCreated;
    nodeType.prototype.onNodeCreated = function () {
      const r = onCreated?.apply(this, arguments);
      const node = this;
      hide(W(node, "timeline_data"));
      hideAlways(node);
      { const w = W(node, "automatico"); if (w) { const cb = w.callback; w.callback = function () { const rr = cb?.apply(this, arguments); syncAuto(node); return rr; }; } }
      setTimeout(() => syncAuto(node), 0);
      const gui = new TransitionDirector(node);
      node._h3td = gui;
      node.addDOMWidget("h3td_timeline", "h3td", gui.root, { serialize: false, getMinHeight: () => 800, getHeight: () => 800 });
      for (const k of ["video_a", "video_b"]) { const w = W(node, k); if (!w) continue; const cb = w.callback;
        // cambio video: rilegge durata e anteprima; IN/OUT/posizione restano se sono ancora validi per il nuovo file
        w.callback = function () { const rr = cb?.apply(this, arguments); gui.info[k === "video_a" ? "a" : "b"] = null; gui._names = [W(node, "video_a")?.value, W(node, "video_b")?.value].join("|"); gui.refreshInfo(true); return rr; }; }
      for (const k of ["contesto", "zona_minima", "transition_zone", "zona_automatica"]) { const w = W(node, k); if (!w) continue; const cb = w.callback;
        w.callback = function () { const rr = cb?.apply(this, arguments); gui.solve(); return rr; }; }
      node.setSize([Math.max(node.size[0], 980), Math.max(node.size[1], 1220)]);
      return r;
    };
    const onConfigure = nodeType.prototype.onConfigure;
    nodeType.prototype.onConfigure = function () {
      const r = onConfigure?.apply(this, arguments);
      setTimeout(() => {
        syncAuto(this);
        hideAlways(this);
        this._h3td?.load();   // dati salvati nel workflow
        // un workflow salvato con il nodo stretto ricarica quella larghezza: la timeline ha bisogno di spazio
        if (this.size[0] < 960 || this.size[1] < 1100) this.setSize([Math.max(this.size[0], 980), Math.max(this.size[1], 1220)]);
        this.setDirtyCanvas?.(true, true);
      }, 0);
      return r;
    };
  },
});
