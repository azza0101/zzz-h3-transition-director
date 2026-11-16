# -*- coding: utf-8 -*-
"""ZZZ H3 Transition Director — due clip su una timeline, H3 genera il raccordo.

Timeline a 24 fps (quelli di H3). Clip A e B sono barre spostabili/rifilabili:
- B si SOVRAPPONE ad A  -> la zona sovrapposta viene rigenerata (A che diventa B), il tempo e' quello della timeline;
- B e' LONTANA da A     -> il buco viene generato da zero (ponte);
- B attaccata ad A      -> raccordo "a taglio": la zona minima si allarga a cavallo del taglio, durata = A + B.
Ancore = immagini guida a un frame della timeline. Prompt = segmenti sulla timeline ("From .. to .., testo").
La griglia temporale di H3 (contesto, lunghezza 17k+5, bordi dei token) e' risolta qui, mai a mano.
"""
import functools
import json
import math
import os
import re
import shutil
import subprocess

import numpy as np
import torch

import comfy.nested_tensor
import folder_paths
from comfy.ldm.minimax.model import FRAME_PER_TOKEN
from comfy_extras import nodes_minimax_h3 as h3

_OWNER = "ZZZ H3 Transition Director"
VERSION = "v2.19"  # alzare a ogni modifica del nodo e annotare qui sotto
# v2.0  base: timeline A/B, ancore, prompt a segmenti, audio originale in dissolvenza nell'Assemble
# v2.1  2026-11-16  numero di versione nel titolo e nel report; audio solo dal Director (niente loader esterni)
# v2.2  2026-11-16  prompt AUTOMATICO opzionale: caption di A e B (Qwen3-VL) + una riga 'idea_transizione'; audio automatico
# v2.3  2026-11-16  uscita agli fps ORIGINALI di A (ricampionamento temporale dei 24 fps di H3), opzione fps_uscita
# v2.4  2026-11-16  oltre_limite_H3 sempre acceso (default True); GUI: snap on/off al posto dei bottoni sovrapponi/attacca/stacca; sfuma_* e curva nascosti
# v2.5  2026-11-16  GUI: loader video grafici (anteprima, dati, Load video) al posto dei combo; campo 'GLOBAL PROMPT'
# v2.6  2026-11-16  GUI: cursore/mouse corretti con lo zoom del canvas (coordinate del puntatore scalate, come nel Dialogue)
# v2.7  2026-11-16  GUI: bottone 'Ancora dal frame' rinominato 'FRAME RIFERIMENTO TRANSIZIONE'
# v2.8  2026-11-16  le ancore seguono il clip: salvano clip (a/b) + frame sorgente e il frame di timeline si ricalcola da pos/in
# v2.9  2026-11-16  ANCORA B AUTOMATICA (contesto di B): il frame di B subito dopo la zona, calcolato dal Director, peso 0.15 -> 1; le ancore manuali restano a parte
# v2.10 2026-11-16  prompt automatico: MAI tagli se non chiesti (testo 'unico piano sequenza'), tratti della zona senza segmento riempiti con 'l'azione continua senza stacchi'
# v2.11 2026-11-16  prompt automatico: frase di RITMO COSTANTE (niente slow motion / rampa di velocita' / recupero), per evitare l'accelerazione nella zona generata
# v2.12 2026-11-16  UNIVERSALE: zona automatica (96 fr + gap, max 124), segmenti legati alla zona (si ridistribuiscono), STADI AUTOMATICI a frazioni per i segmenti >= 1 s ('->' = stadi propri), sfuma B 8
# v2.13 2026-11-16  transition_zone automatica: short / medium / large (campo in coda: non sposta i valori salvati)
# v2.14 2026-11-16  video VERTICALI: la rotazione nei metadati (es. FX3/telefono, 90 gradi) scambia larghezza e altezza, la tela esce verticale
# v2.15 2026-11-16  transition_zone: short 24 / medium 64 / large 96 frame + buco, e mai oltre il 70% di A+B (clip corte)
# v2.16 2026-11-16  tetto per livello (short 35% / medium 55% / large 80% di A+B): con clip corte i livelli restano diversi
# v2.17 2026-11-16  UNIVERSALE per scene/soggetti diversi: niente piu' 'same subject/same place'; se la zona non ha segmenti nasce da sola una transizione a stadi (GLOBAL PROMPT tradotto in inglese, o generica A -> B)
# v2.18 2026-11-16  location diverse: frase SPAZIO CONTINUO (i due luoghi sono un unico ambiente collegato, la camera ci passa attraverso, niente flash/sfocatura)
# v2.19 2026-11-16  SPACE_JOIN rivisto: il luogo nuovo entra SOLO dal lato verso cui gira la camera, gli sfondi non si fondono sul posto (niente dissolvenza dietro il soggetto), alla fine solo il contenuto di B
FPS = h3.FPS  # 24: la timeline lavora nei frame del modello
_NOWIN = getattr(subprocess, "CREATE_NO_WINDOW", 0)
VIDEO_EXT = (".mp4", ".mov", ".mkv", ".webm", ".avi", ".m4v")


def _ffmpeg():
    return shutil.which("ffmpeg") or "ffmpeg"


def _ffprobe():
    return shutil.which("ffprobe") or "ffprobe"


def list_videos():
    d = folder_paths.get_input_directory()
    out = []
    for root, _, files in os.walk(d):
        for f in files:
            if f.lower().endswith(VIDEO_EXT):
                out.append(os.path.relpath(os.path.join(root, f), d).replace("\\", "/"))
    return sorted(out) or ["(nessun video in input)"]


@functools.lru_cache(maxsize=64)
def _probe_cached(path, mtime):
    r = subprocess.run([_ffprobe(), "-v", "error", "-show_entries",
                        "stream=codec_type,r_frame_rate,avg_frame_rate,nb_frames,duration,width,height:stream_tags=rotate:stream_side_data=rotation:format=duration",
                        "-of", "json", path], capture_output=True, text=True, creationflags=_NOWIN, timeout=60)
    j = json.loads(r.stdout or "{}")
    v = next((s for s in j.get("streams", []) if s.get("codec_type") == "video"), {})
    has_audio = any(s.get("codec_type") == "audio" for s in j.get("streams", []))

    def fr(x):
        try:
            a, b = str(x).split("/")
            return float(a) / float(b) if float(b) else 0.0
        except Exception:
            return 0.0
    fps = fr(v.get("avg_frame_rate")) or fr(v.get("r_frame_rate")) or 24.0
    dur = float(v.get("duration") or (j.get("format") or {}).get("duration") or 0)
    frames = int(v["nb_frames"]) if str(v.get("nb_frames", "")).isdigit() else int(round(dur * fps))
    if not dur:
        dur = frames / fps
    # video verticali (telefono, FX3 ruotata): i pixel sono orizzontali ma c'e' una rotazione di 90 gradi nei metadati.
    # ffmpeg ruota gia' i frame quando li legge: qui larghezza e altezza vanno scambiate, o la tela esce orizzontale.
    rot = 0
    try:
        rot = int(float((v.get("tags") or {}).get("rotate") or 0))
    except Exception:
        pass
    for sd in v.get("side_data_list") or []:
        if "rotation" in sd:
            try:
                rot = int(float(sd["rotation"]))
            except Exception:
                pass
    w_, h_ = int(v.get("width") or 0), int(v.get("height") or 0)
    if abs(rot) % 180 == 90:
        w_, h_ = h_, w_
    return {"fps": fps, "frames": frames, "duration": dur, "width": w_,
            "height": h_, "rotation": rot, "has_audio": has_audio,
            "tl_frames": int(math.floor(dur * FPS + 1e-6))}


def probe(name):
    path = folder_paths.get_annotated_filepath(name)
    if not os.path.isfile(path):
        raise ValueError("%s: video non trovato: %s" % (_OWNER, name))
    return path, _probe_cached(path, os.path.getmtime(path))


def read_frames(path, start, count, W, H, crop="center"):
    """count frame a 24 fps da `start` (frame timeline della clip), ridimensionati W x H. -> tensor [N,H,W,3] float."""
    if count <= 0:
        return torch.zeros((0, H, W, 3))
    if crop == "center":
        vf = "fps=%d,scale=%d:%d:force_original_aspect_ratio=increase:flags=lanczos,crop=%d:%d" % (FPS, W, H, W, H)
    else:
        vf = "fps=%d,scale=%d:%d:flags=lanczos" % (FPS, W, H)
    t = max(0.0, start / FPS)
    cmd = [_ffmpeg(), "-v", "error", "-ss", "%.6f" % t, "-i", path, "-map", "0:v:0", "-vf", vf,
           "-frames:v", str(count), "-f", "rawvideo", "-pix_fmt", "rgb24", "-"]
    r = subprocess.run(cmd, capture_output=True, creationflags=_NOWIN)
    if r.returncode != 0:
        raise RuntimeError("%s: ffmpeg fallito su %s: %s" % (_OWNER, path, r.stderr.decode("utf8", "ignore")[-400:]))
    arr = np.frombuffer(r.stdout, np.uint8)
    n = arr.size // (W * H * 3)
    arr = arr[: n * W * H * 3].reshape(n, H, W, 3)
    out = torch.from_numpy(arr.copy()).float() / 255.0
    if n < count:  # fine file: ripete l'ultimo frame (la GUI non dovrebbe permetterlo)
        pad = out[-1:].expand(count - n, -1, -1, -1) if n else torch.zeros((count, H, W, 3))
        out = torch.cat((out, pad), 0)
    return out


def read_audio(path, start, count, sr=48000):
    """audio stereo dei `count` frame timeline da `start`. -> tensor [2, samples] (zeri se il file non ha audio)."""
    n = int(round(count / FPS * sr))
    cmd = [_ffmpeg(), "-v", "error", "-ss", "%.6f" % (start / FPS), "-i", path, "-t", "%.6f" % (count / FPS),
           "-vn", "-f", "f32le", "-ac", "2", "-ar", str(sr), "-"]
    r = subprocess.run(cmd, capture_output=True, creationflags=_NOWIN)
    a = np.frombuffer(r.stdout, np.float32) if r.returncode == 0 else np.zeros(0, np.float32)
    a = a[: (a.size // 2) * 2].reshape(-1, 2).T
    out = torch.zeros((2, n))
    m = min(n, a.shape[1])
    if m:
        out[:, :m] = torch.from_numpy(a[:, :m].copy())
    return out


# ------------------------------------------------------------------ griglia H3
@functools.lru_cache(maxsize=4096)
def _edges(frame_count):
    t = h3.video_latent_t(frame_count)
    e = [0]
    for k in range(t):
        e.append(e[-1] + FRAME_PER_TOKEN[k % len(FRAME_PER_TOKEN)])
    return tuple(e)


def _clip_len(n):
    if n < 5:
        return 1
    while n % 17 != 5:
        n -= 1
    return n


def parse_timeline(data):
    try:
        tl = json.loads(data) if isinstance(data, str) and data.strip() else {}
    except Exception:
        tl = {}
    tl.setdefault("a", {})
    tl.setdefault("b", {})
    tl.setdefault("anchors", [])
    tl.setdefault("prompts", [])
    return tl


def clip_span(c, total):
    i = int(max(0, min(total, c.get("in", 0))))
    o = int(max(i + 1, min(total, c.get("out", total))))
    return i, o, int(c.get("pos", 0))


def solve(tl, la_total, lb_total, ctx=22, min_zone=24):
    """Calcola modo, zona e finestra latente. Tutto in frame timeline (24 fps)."""
    a_in, a_out, pa = clip_span(tl["a"], la_total)
    b_in, b_out, pb = clip_span(tl["b"], lb_total)
    la, lb = a_out - a_in, b_out - b_in
    endA, endB = pa + la, pb + lb
    warn = []
    if pb < pa:
        raise ValueError("%s: la clip B deve stare dopo l'inizio di A (sposta B a destra)." % _OWNER)
    if endB <= endA:
        raise ValueError("%s: la clip B finisce prima di A: B deve continuare dopo la fine di A." % _OWNER)
    if pb < endA:
        mode, z0, z1 = "sovrapposta", pb, endA
    elif pb > endA:
        mode, z0, z1 = "ponte", endA, pb
    else:
        mode, z0, z1 = "taglio", endA, endA
    if z1 - z0 < min_zone:  # zona troppo corta: si allarga a cavallo, senza spostare nulla
        extra = min_zone - (z1 - z0)
        z0 -= extra // 2
        z1 += extra - extra // 2
        if mode != "ponte":
            warn.append("zona allargata a %d frame (minimo) a cavallo del raccordo" % min_zone)
    hasA = lambda t: pa <= t < endA
    hasB = lambda t: pb <= t < endB
    best = None
    G = z1 - z0
    for dG in range(-6, 7):
        g = G + dG
        if g < 5:
            continue
        nz0 = z1 - g          # il bordo B (z1) resta dov'e': si sposta l'inizio della zona
        if mode == "ponte" and nz0 > endA:
            continue          # buco senza contenuto: non permesso
        if nz0 < pa + 1:
            continue
        for ca in range(5, ctx + 18):   # >= 5: le guide di contesto non devono mai sembrare ancore da 1 frame
            if nz0 - ca < pa:
                break
            for cb in range(5, ctx + 18):
                if z1 + cb > endB:
                    break
                L = ca + g + cb
                if L % 17 != 5:
                    continue
                e = _edges(L)
                if ca not in e or (L - cb) not in e:
                    continue
                cost = abs(dG) * 3 + abs(ca - ctx) + abs(cb - ctx) + abs(ca - cb) * 0.3
                if best is None or cost < best[0]:
                    best = (cost, nz0, ca, cb, L)
    if best is None:
        raise ValueError("%s: nessuna griglia valida — servono almeno ~%d frame di A prima della zona e di B dopo. "
                         "Allunga le clip o riduci il contesto." % (_OWNER, max(5, ctx // 2)))
    _, z0, ca, cb, L = best
    w0 = z0 - ca
    return dict(mode=mode, z0=z0, z1=z1, ca=ca, cb=cb, L=L, w0=w0, w1=w0 + L, pa=pa, pb=pb, endA=endA, endB=endB,
                a_in=a_in, b_in=b_in, la=la, lb=lb, t0=pa, t1=max(endA, endB), warn=warn,
                mid=(z0 + z1) / 2.0, hasA=None, hasB=None)


ZONE_AUTO_BASE, ZONE_AUTO_MAX = 96, 124
ZONE_LEVELS = {"short": (24, 64), "medium": (64, 100), "large": (96, 131)}
ZONE_CAP = {"short": 0.35, "medium": 0.55, "large": 0.8}   # quota massima di A + B: con clip corte i tre livelli restano diversi   # (base, massimo) in frame a 24 fps


def solve_auto(tl, la_total, lb_total, ctx=22, min_zone=24, auto=True, level="medium"):
    """zona automatica: almeno 96 frame + il buco tra A e B (max 124 = vicino al limite della finestra H3).
    Se la griglia non ci sta (clip corte) scende a passi fino al minimo dell'utente."""
    if not auto:
        return solve(tl, la_total, lb_total, ctx, min_zone)
    a_in, a_out, pa = clip_span(tl["a"], la_total)
    b_in, b_out, pb = clip_span(tl["b"], lb_total)
    gap = max(0, pb - (pa + a_out - a_in))
    base_, max_ = ZONE_LEVELS.get(str(level), ZONE_LEVELS["medium"])
    want = min(max_, base_ + gap)
    # la zona non deve mangiarsi le clip: al massimo il 70% della durata di A + B (clip corte = zona corta)
    want = min(want, max(gap + 12, int(ZONE_CAP.get(str(level), 0.55) * ((a_out - a_in) + (b_out - b_in) + gap))))
    want = max(int(min_zone), want)
    err = None
    for z in range(want, int(min_zone) - 1, -4):
        try:
            p = solve(tl, la_total, lb_total, ctx, z)
            if z != want:
                p["warn"].append("zona automatica ridotta a %d frame (clip corte)" % z)
            return p
        except ValueError as e:
            err = e
    if err is None:
        return solve(tl, la_total, lb_total, ctx, min_zone)
    raise err


def _remap_to_zone(tl, p):
    """segmenti legati alla zona: se la zona salvata (tl['zone']) e' diversa da quella calcolata, li riporta in proporzione."""
    z = tl.get("zone")
    if not (isinstance(z, (list, tuple)) and len(z) == 2):
        return
    oz0, oz1 = float(z[0]), float(z[1])
    nz0, nz1 = float(p["z0"]), float(p["z1"])
    if (oz0, oz1) == (nz0, nz1) or oz1 <= oz0:
        return
    k = (nz1 - nz0) / (oz1 - oz0)
    for s in tl.get("prompts", []):
        s["start"] = int(round(nz0 + (float(s.get("start", 0)) - oz0) * k))
        s["end"] = int(round(nz0 + (float(s.get("end", 0)) - oz0) * k))


_FR = {2: ["about half"], 3: ["about one third", "about two thirds"], 4: ["about one quarter", "about half", "about three quarters"]}


def expand_stages(prompts):
    """STADI AUTOMATICI: un segmento lungo (>= 24 frame = 1 s) diventa 2-4 stadi uguali con l'avanzamento scritto
    (un quarto, meta', tre quarti, completato): H3 segue il ritmo scritto invece di fare tutto in un attimo.
    Testo con '->' = stadi scritti dall'utente, distribuiti in parti uguali. "stadi": false nel segmento = lascialo intero."""
    out = []
    for s in prompts:
        t = str(s.get("text", "")).strip().rstrip(".")
        a, b = int(s.get("start", 0)), int(s.get("end", 0))
        if not t or b <= a:
            continue
        if "->" in t:
            parts = [x.strip() for x in t.split("->") if x.strip()]
            n = len(parts)
            for i, x in enumerate(parts):
                out.append({"start": a + (b - a) * i // n, "end": a + (b - a) * (i + 1) // n, "text": x})
            continue
        if b - a < 24 or s.get("stadi") is False:
            out.append({"start": a, "end": b, "text": t})
            continue
        n = max(2, min(4, (b - a) // 12))
        for i in range(n):
            if i < n - 1:
                x = "%s; this change progresses evenly and is %s complete at this point, the rest is still to come" % (t, _FR[n][i])
            else:
                x = "%s; this change is now complete, its final state is fully reached and holds steady" % t
            out.append({"start": a + (b - a) * i // n, "end": a + (b - a) * (i + 1) // n, "text": x})
    return out


def _ramp(i, n, shape):
    x = (i + 1) / (n + 1)
    if shape == "smooth":
        x = x * x * (3 - 2 * x)
    return x


def build_mask(p, real, fa_in, fa_out, fb_in, fb_out, shape):
    """maschera per token (1 = genera). `real[i]` = il frame latente i ha contenuto vero nel controllo."""
    e = _edges(p["L"])
    T = len(e) - 1
    tok_s, tok_e = e.index(p["ca"]), e.index(p["L"] - p["cb"])
    tok_real = [all(real[f] for f in range(e[t], e[t + 1])) for t in range(T)]
    m = [0.0] * T
    for t in range(tok_s, tok_e):
        m[t] = 1.0

    def cover(start_tok, n_frames, step, stop):
        out, cov, t = [], 0, start_tok
        while cov < n_frames and stop(t):
            out.append(t)
            cov += e[t + 1] - e[t]
            t += step
        return out
    a_out = cover(tok_s - 1, fa_out, -1, lambda t: t >= 1)
    a_in = cover(tok_s, fa_in, +1, lambda t: t < tok_e and tok_real[t])
    b_in = cover(tok_e - 1, fb_in, -1, lambda t: t >= tok_s and tok_real[t])
    b_out = cover(tok_e, fb_out, +1, lambda t: t < T - 1)
    zone_tok = tok_e - tok_s
    while len(a_in) + len(b_in) > max(0, zone_tok - 1):
        if len(a_in) >= len(b_in) and a_in:
            a_in.pop()
        elif b_in:
            b_in.pop()
    seq = list(reversed(a_out)) + a_in
    for i, t in enumerate(seq):
        m[t] = _ramp(i, len(seq), shape)
    seq = list(reversed(b_in)) + b_out
    for i, t in enumerate(seq):
        v = 1.0 - _ramp(i, len(seq), shape)
        m[t] = min(m[t], v) if t < tok_e else v
    nz = [t for t in range(T) if m[t] > 0]
    return m, e[nz[0]], e[nz[-1] + 1]


def _tc(seconds):
    seconds = max(0.0, float(seconds))
    mm = int(seconds // 60)
    return "%02d:%06.3f" % (mm, seconds - mm * 60)


def _anchor_frame(an, p, va, vb):
    """frame di timeline dell'ancora. Se l'ancora e' legata a un clip (clip + src = frame sorgente) segue il clip quando si sposta o si rifila;
    le ancore vecchie (solo frame) si riconoscono dal nome file `<video>_f<frame>_<hash>.png`."""
    clip, src = an.get("clip"), an.get("src")
    if clip not in ("a", "b") or src is None:
        clip, src = None, None
        m = re.match(r"^(.*)_f(\d+)_[0-9a-fA-F]{6}\.png$", os.path.basename(str(an.get("image") or "")))
        if m:
            for k, v in (("a", va), ("b", vb)):
                if os.path.splitext(os.path.basename(str(v)))[0] == m.group(1):
                    clip, src = k, int(m.group(2))
                    break
    if clip in ("a", "b") and src is not None:
        pos, inn = (p["pa"], p["a_in"]) if clip == "a" else (p["pb"], p["b_in"])
        return int(pos + int(src) - inn)
    return int(an.get("frame", -1))


def build_description(tl, p, scena, finale, fill=None, stadi=True):
    rows = []
    for s in (expand_stages(tl.get("prompts", [])) if stadi else tl.get("prompts", [])):
        txt = str(s.get("text", "")).strip().rstrip(".")
        if not txt:
            continue
        a, b = int(s.get("start", 0)), int(s.get("end", 0))
        a, b = max(a, p["w0"]), min(b, p["w1"])
        if b <= a:
            continue
        rows.append(((a - p["w0"]) / FPS, (b - p["w0"]) / FPS, txt))
    rows.sort()
    if fill:   # tratti della zona generata senza segmento: l'azione continua, niente tagli
        z0s, z1s = (p["z0"] - p["w0"]) / FPS, (p["z1"] - p["w0"]) / FPS
        cur, extra = z0s, []
        for t0, t1, _ in rows:
            if t0 - cur >= 0.5:
                extra.append((cur, t0, fill))
            cur = max(cur, t1)
        if z1s - cur >= 0.5:
            extra.append((cur, z1s, fill))
        rows = sorted(rows + extra)
    parts = [scena.strip()] if scena.strip() else []
    for t0, t1, txt in rows:
        parts.append("From %s to %s, %s." % (_tc(t0), _tc(t1), txt))
    if finale.strip():
        parts.append("%s, flowing straight into the next shot at %s with no jump." % (
            finale.strip().rstrip("."), _tc((p["z1"] - p["w0"]) / FPS)))
    return " ".join(parts), rows


_CUT_WORDS = re.compile(r"\b(cut|hard cut|jump cut|taglio|stacco|stacchi)\b", re.I)
NO_CUT = ("This is ONE single uninterrupted take filmed by one camera: there is no cut, no jump cut, no scene change, no fade and no change "
          "of angle anywhere; the subject and the camera move continuously and smoothly through the whole shot, including the gap between the two clips.")
FILL = ("the transition keeps progressing smoothly and continuously in the same single uninterrupted shot, "
        "with continuous camera movement and no cut")


PACE = ("All motion happens at natural real-time speed, constant from the first to the last frame: no slow motion, no speed ramp, "
        "no time remapping, no acceleration to catch up; every movement keeps a steady, natural pace.")


SPACE_JOIN = ("If the two shots are in different places, they are neighbouring parts of one connected building or environment: "
              "the camera physically turns or moves from the first place toward the next one, and the new place enters the frame only "
              "from the side the camera is turning toward, while the first place leaves the frame on the opposite side; "
              "each background stays solid and real while it is in view, never morphing, fading or blending in place, "
              "and at the end only the content of the next shot is in the frame, exactly as in the next shot.")


def auto_texts(A, B, idea, a_audio, b_audio):
    """prompt automatico: descrive A e l'inizio di B con il captioner locale (in cache) + una riga di idea."""
    from .caption import zzz_VideoCaption
    cap = zzz_VideoCaption().run
    cap_a = cap(A, 4, "")[0]
    cap_b = cap(B[:max(8, min(len(B), 48))], 3, "")[0]
    cuts_ok = bool(_CUT_WORDS.search(idea or ""))   # un taglio c'e' solo se l'utente lo scrive espressamente
    scena = ("" if cuts_ok else NO_CUT + " " + SPACE_JOIN + " ") + PACE + " The shot starts like this: %s" % cap_a.strip()
    idea_en = _to_english(idea)
    if idea_en:
        scena += " The transition: %s" % idea_en.rstrip(".")
    finale = "The shot ends exactly in the framing of the next shot, which looks like this: %s" % cap_b.strip().rstrip(".")
    if not cuts_ok:
        finale += ", reached by continuous motion with no cut"
    if a_audio:
        sound = ("The original voice and sound of the first shot continue without any interruption, change in level or change "
                 "in tone; the ambience of the next shot fades in smoothly under it.")
    else:
        sound = "Natural production sound continues without interruption."
    # transizione di default (nessun segmento sulla zona): l'idea dell'utente, oppure "la scena di A diventa quella di B"
    trans = idea_en or ("the scene of the first shot progressively transforms into the scene of the next shot, %s"
                        % cap_b.strip().split(". ")[0].rstrip("."))
    return scena, finale, sound, (None if cuts_ok else FILL), trans


def _to_english(text):
    """GLOBAL PROMPT in qualunque lingua -> inglese (H3 e' addestrato in inglese). Qwen3-VL-2B locale, in cache."""
    t = (text or "").strip()
    if not t:
        return ""
    try:
        from .caption import translate_en
        return translate_en(t)
    except Exception as e:
        print("[%s] traduzione non riuscita, uso il testo originale: %s" % (_OWNER, e))
        return t


def _prompt(L, description, soundscape, music):
    return (
        "How the reference pictures align with the target video — Picture 1 (from Shot 1) aligns "
        f"with the 0.00-second mark of the target video; Picture 2 (from Shot 1) aligns with the {L / FPS:.2f}-second mark of the target video.\n\n"
        f"integrated_multimodal_description: {description.strip()}\n\n"
        f"overall_soundscape: {soundscape.strip() or 'N/A'}\n\n"
        f"non_diegetic_music: {music.strip() or 'N/A'}"
    )


def canvas_size(w, h, megapixel, oltre=False):
    cap = 4.0e6 if oltre else h3.MAX_PIXELS   # oltre il limite ufficiale H3 (768x1344): sperimentale
    mp = min(float(megapixel), cap / 1e6) if megapixel > 0 else min(w * h, cap) / 1e6
    W = max(32, int(round(math.sqrt(mp * 1e6 * w / h) / 32)) * 32)
    H = max(32, int(round(math.sqrt(mp * 1e6 * h / w) / 32)) * 32)
    while W * H > cap:
        if W >= H:
            W -= 32
        else:
            H -= 32
    return W, H


def summary(p):
    return {k: p[k] for k in ("mode", "z0", "z1", "ca", "cb", "L", "w0", "w1", "t0", "t1", "warn")}


class zzz_H3_TransitionDirector:
    @classmethod
    def INPUT_TYPES(cls):
        vids = list_videos()
        return {
            "required": {
                "clip": ("CLIP",),
                "vae": ("VAE",),
                "video_a": (vids, {"tooltip": "Clip A (prima). Si carica dal pulsante nella timeline."}),
                "video_b": (vids, {"tooltip": "Clip B (dopo)."}),
                "megapixel": ("FLOAT", {"default": 0.4, "min": 0.05, "max": 4.0, "step": 0.05,
                                        "tooltip": "Risoluzione di lavoro. Oltre 1.03 MP solo con 'oltre_limite_H3' acceso."}),
                "contesto": ("INT", {"default": 22, "min": 1, "max": 120,
                                     "tooltip": "Frame veri che H3 vede prima e dopo la zona (si aggancia alla griglia)."}),
                "zona_minima": ("INT", {"default": 24, "min": 5, "max": 240,
                                        "tooltip": "Se la zona (sovrapposizione o buco) e' piu' corta, si allarga a cavallo del raccordo."}),
                "sfuma_A_dentro": ("INT", {"default": 8, "min": 0, "max": 120}),
                "sfuma_A_fuori": ("INT", {"default": 0, "min": 0, "max": 120}),
                "sfuma_B_dentro": ("INT", {"default": 8, "min": 0, "max": 120}),
                "sfuma_B_fuori": ("INT", {"default": 8, "min": 0, "max": 120}),
                "curva_sfumatura": (["smooth", "lineare"],),
                "scena": ("STRING", {"multiline": True, "default":
                                     "One single continuous shot, no cut. The subject stays fully visible in the frame at all times."}),
                "finale": ("STRING", {"multiline": True, "default":
                                      "He arrives exactly in the pose, position and framing of the next shot"}),
                "overall_soundscape": ("STRING", {"multiline": True, "default": "Natural production sound continues without interruption."}),
                "non_diegetic_music": ("STRING", {"default": "N/A"}),
                "crop": (["center", "stretch"],),
                "timeline_data": ("STRING", {"default": "{}", "multiline": True}),
            },
            "optional": {
                "automatico": ("BOOLEAN", {"default": False,
                               "tooltip": "Prompt AUTOMATICO: descrive A e B da solo (Qwen3-VL, in cache) e scrive il raccordo e l'audio. "
                                          "Si scrive solo 'idea_transizione' (facoltativa) e i segmenti della timeline."}),
                "idea_transizione": ("STRING", {"default": "", "multiline": True,
                                                "tooltip": "Una riga: cosa succede nella transizione, correzioni comprese. Solo con 'automatico'."}),
                "zona_automatica": ("BOOLEAN", {"default": True,
                                   "tooltip": "La zona generata si allunga da sola con la distanza tra A e B (96 frame + buco, max 124). "
                                              "zona_minima resta il minimo. I segmenti di prompt la seguono in proporzione."}),
                "stadi_automatici": ("BOOLEAN", {"default": True,
                                     "tooltip": "I segmenti lunghi (>= 1 s) diventano stadi con l'avanzamento scritto (un quarto, meta', tre quarti, completato). "
                                                "Con '->' nel testo si scrivono gli stadi a mano."}),
                "ancora_B_automatica": ("BOOLEAN", {"default": True,
                                       "tooltip": "Contesto di B automatico: il frame di B subito dopo la zona generata viene dato a H3 come ancora, "
                                                  "con peso basso (0.15) che sale a 1. Si ricalcola da solo. Le ancore della timeline sono a parte."}),
                "oltre_limite_H3": ("BOOLEAN", {"default": True,
                                                "tooltip": "SPERIMENTALE: permette di superare la tela ufficiale di H3 (768x1344 = 1.03 MP). "
                                                           "Fuori dall'addestramento: rischio di ripetizioni/incoerenze, tempi e VRAM molto piu' alti."}),
                "transition_zone": (["medium", "short", "large"], {"default": "medium",
                                    "tooltip": "Quanta parte generare con la zona automatica: short (~1 s + buco), medium (~2.7 s + buco), large (~4 s + buco, fino al limite di H3); tetto 35/55/80% della durata di A+B."}),
            },
        }

    RETURN_TYPES = ("CONDITIONING", "LATENT", "ZZZ_H3_TD_PLAN", "STRING", "STRING", "STRING")
    RETURN_NAMES = ("positive", "latent", "plan", "prompt", "report", "spec_pesi_ancore")
    FUNCTION = "run"
    CATEGORY = "zzz/h3"
    DESCRIPTION = ("Timeline stile Director con due clip: sovrapposte = transizione sovrapposta, lontane = ponte generato, "
                   "attaccate = raccordo a taglio. Ancore e prompt a segmenti sulla timeline.")

    @classmethod
    def VALIDATE_INPUTS(cls, video_a=None, video_b=None, **kw):
        return True

    def run(self, clip, vae, video_a, video_b, megapixel, contesto, zona_minima, sfuma_A_dentro, sfuma_A_fuori,
            sfuma_B_dentro, sfuma_B_fuori, curva_sfumatura, scena, finale, overall_soundscape, non_diegetic_music,
            crop, timeline_data, oltre_limite_H3=False, automatico=False, idea_transizione='', ancora_B_automatica=True, zona_automatica=True, stadi_automatici=True, transition_zone="medium"):
        tl = parse_timeline(timeline_data)
        path_a, ia = probe(video_a)
        path_b, ib = probe(video_b)
        p = solve_auto(tl, ia["tl_frames"], ib["tl_frames"], int(contesto), int(zona_minima), bool(zona_automatica), str(transition_zone))
        if zona_automatica:
            _remap_to_zone(tl, p)
        W, H = canvas_size(ia["width"] or 832, ia["height"] or 480, megapixel, bool(oltre_limite_H3))
        if W * H > h3.MAX_PIXELS:
            p["warn"].append("SPERIMENTALE: %dx%d = %.2f MP oltre la tela ufficiale H3 (1.03 MP)" % (W, H, W * H / 1e6))
        A = read_frames(path_a, p["a_in"], p["la"], W, H, crop)
        B = read_frames(path_b, p["b_in"], p["lb"], W, H, crop)

        # controllo (pixel) della finestra latente
        L, w0 = p["L"], p["w0"]
        gray = torch.full((H, W, 3), 0.5)
        frames, real = [], []
        for i in range(L):
            t = w0 + i
            inA = p["pa"] <= t < p["endA"]
            inB = p["pb"] <= t < p["endB"]
            if t < p["z0"]:
                use = "A"
            elif t >= p["z1"]:
                use = "B"
            elif inA and inB:
                use = "A" if t < p["mid"] else "B"
            else:
                use = "A" if inA else ("B" if inB else None)
            if use == "A" and inA:
                frames.append(A[t - p["pa"]]); real.append(True)
            elif use == "B" and inB:
                frames.append(B[t - p["pb"]]); real.append(True)
            else:
                frames.append(gray); real.append(False)
        control = torch.stack(frames, 0)

        fill = None
        if automatico:
            scena, finale, overall_soundscape, fill, trans = auto_texts(A, B, idea_transizione, ia["has_audio"], ib["has_audio"])
            # nessun segmento sulla zona: la transizione stessa diventa un segmento (a stadi) su tutta la zona
            covered = sum(max(0, min(int(s.get("end", 0)), p["z1"]) - max(int(s.get("start", 0)), p["z0"])) for s in tl.get("prompts", []))
            if covered < 0.5 * (p["z1"] - p["z0"]):
                tl["prompts"] = list(tl.get("prompts", [])) + [{"start": p["z0"], "end": p["z1"], "text": trans}]
            non_diegetic_music = "N/A"
        description, rows = build_description(tl, p, scena, finale, fill, bool(stadi_automatici))
        prompt = _prompt(L, description, overall_soundscape, non_diegetic_music)
        positive, latent = h3.MiniMaxH3ImageToVideo.execute(clip, vae, prompt, W, H, L).args
        video_latent = vae.encode(control)
        empty_video, audio_lat = latent["samples"].unbind()
        if video_latent.shape != empty_video.shape:
            raise ValueError("%s: VAE %s, atteso %s" % (_OWNER, tuple(video_latent.shape), tuple(empty_video.shape)))
        m, g0, g1 = build_mask(p, real, int(sfuma_A_dentro), int(sfuma_A_fuori), int(sfuma_B_dentro), int(sfuma_B_fuori),
                               curva_sfumatura)
        vmask = torch.zeros_like(video_latent)
        for t, v in enumerate(m):
            vmask[:, :, t].fill_(v)
        out = latent.copy()
        out["samples"] = comfy.nested_tensor.NestedTensor((video_latent, audio_lat))
        out["noise_mask"] = comfy.nested_tensor.NestedTensor((vmask, torch.ones_like(audio_lat)))

        # guide: contesto vero di A e di B + ancore della timeline
        ca, cb = p["ca"], p["cb"]
        ga, gb = _clip_len(ca), _clip_len(cb)
        positive = h3.MiniMaxH3AddGuide.execute(positive, latent, ca - ga, vae=vae, image=control[ca - ga:ca]).args[0]
        positive = h3.MiniMaxH3AddGuide.execute(positive, latent, L - cb, vae=vae, image=control[L - cb:L - cb + gb]).args[0]
        # ancore in ordine di frame; per ognuna una curva di peso (spec per zzz_H3AnchorTimelineAttention):
        # peso_prima dall'inizio della finestra, sale fino a peso al frame dell'ancora, poi resta costante.
        used_anchors, spec = [], []
        for an in sorted(tl.get("anchors", []), key=lambda a: _anchor_frame(a, p, video_a, video_b)):
            fr = _anchor_frame(an, p, video_a, video_b)
            f = fr - w0
            img = an.get("image")
            if not img or not (0 <= f < L):
                if img:
                    p["warn"].append("ancora al frame %s fuori dalla finestra generata: ignorata" % fr)
                continue
            ipath = folder_paths.get_annotated_filepath(img)
            if not os.path.isfile(ipath):
                p["warn"].append("immagine ancora non trovata: %s" % img)
                continue
            from PIL import Image, ImageOps
            im = ImageOps.exif_transpose(Image.open(ipath)).convert("RGB")
            t_img = torch.from_numpy(np.asarray(im).astype(np.float32) / 255.0)[None]
            positive = h3.MiniMaxH3AddGuide.execute(positive, latent, f, vae=vae, image=t_img).args[0]
            wp = float(an.get("peso", 1.0))
            ws = float(an.get("peso_prima", wp))
            spec.append({"frame": f, "pts": [[0, ws], [max(1, f), wp]]})
            used_anchors.append((fr, img, ws, wp))
        if ancora_B_automatica:   # contesto di B: il primo frame di B dopo la zona, peso basso che sale (come nella config approvata)
            fa, ib_ = p["z1"] - 1, p["z1"] - p["pb"]
            if p["pb"] <= p["z1"] < p["endB"] and 0 <= fa - w0 < L and 0 <= ib_ < len(B):
                positive = h3.MiniMaxH3AddGuide.execute(positive, latent, fa - w0, vae=vae, image=B[ib_:ib_ + 1]).args[0]
                spec.append({"frame": fa - w0, "pts": [[0, 0.15], [max(1, fa - w0), 1.0]]})
                used_anchors.append((fa, "B f%d (automatica)" % (p["b_in"] + ib_), 0.15, 1.0))
            else:
                p["warn"].append("ancora B automatica: nessun frame di B dopo la zona, saltata")

        # frame veri della timeline intera (per l'assembler) e audio a dissolvenza
        T0, T1 = p["t0"], p["t1"]
        real_tl = torch.empty((T1 - T0, H, W, 3))
        for t in range(T0, T1):
            if t < p["z0"] and p["pa"] <= t < p["endA"]:
                real_tl[t - T0] = A[t - p["pa"]]
            elif p["pb"] <= t < p["endB"]:
                real_tl[t - T0] = B[t - p["pb"]]
            elif p["pa"] <= t < p["endA"]:
                real_tl[t - T0] = A[t - p["pa"]]
            else:
                real_tl[t - T0] = gray
        sr = 48000
        aud_a = read_audio(path_a, p["a_in"], p["la"], sr) if ia["has_audio"] else None
        aud_b = read_audio(path_b, p["b_in"], p["lb"], sr) if ib["has_audio"] else None
        n = int(round((T1 - T0) / FPS * sr))
        mix = torch.zeros((2, n))
        tt = (torch.arange(n) / sr) * FPS + T0  # frame timeline di ogni campione
        z0, z1 = float(p["z0"]), float(p["z1"])
        x = ((tt - z0) / max(z1 - z0, 1.0)).clamp(0, 1)
        if aud_a is not None:
            s0 = int(round((p["pa"] - T0) / FPS * sr))
            seg = torch.zeros((2, n)); k = min(aud_a.shape[1], n - s0); seg[:, s0:s0 + k] = aud_a[:, :k]
            mix += seg * (1 - x)
        if aud_b is not None:
            s0 = int(round((p["pb"] - T0) / FPS * sr))
            seg = torch.zeros((2, n)); k = min(aud_b.shape[1], n - s0); seg[:, s0:s0 + k] = aud_b[:, :k]
            mix += seg * x
        audio = {"waveform": mix[None], "sample_rate": sr}

        plan = dict(type="zzz_h3_td", L=L, W=W, H=H, g0=g0, g1=g1, w0=w0, T0=T0, real=real_tl, audio=audio, src_fps=float(ia["fps"]),
                    z0=p["z0"], z1=p["z1"], mode=p["mode"])
        rep = [
            "[%s %s] modo %s · %dx%d · latent %d frame (%d token)" % (_OWNER, VERSION, p["mode"].upper(), W, H, L, len(m)),
            "  timeline: A %d-%d · B %d-%d · zona %d-%d (%d frame, %.2fs) · uscita %d frame = %.2fs" % (
                p["pa"], p["endA"], p["pb"], p["endB"], p["z0"], p["z1"], p["z1"] - p["z0"], (p["z1"] - p["z0"]) / FPS,
                T1 - T0, (T1 - T0) / FPS),
            "  contesto A %d · contesto B %d · finestra %d-%d · ricalcolati %d-%d" % (ca, cb, w0, w0 + L, w0 + g0, w0 + g1 - 1),
            "  maschera: " + " ".join("%.2f" % v for v in m),
            "  ancore usate: %s" % (", ".join("f%s (peso %.2f -> %.2f)" % (f, ws, wp) for f, _, ws, wp in used_anchors) or "nessuna"),
        ] + ["  prompt %s-%s  %s" % (_tc(a), _tc(b), t) for a, b, t in rows] + ["  ! " + w for w in p["warn"]]
        if automatico:
            rep.append("  PROMPT AUTOMATICO:\n" + prompt)
        report = "\n".join(rep)
        print(report)
        return (positive, out, plan, prompt, report, json.dumps(spec))


def resample_fps(images, dst):
    """riporta i frame a 24 fps (griglia H3) agli fps `dst`: stessa durata in secondi, interpolazione temporale lineare.
    |dst-24| <= 1 -> frame piu' vicino (un frame ripetuto/saltato ogni tanto, niente sfocatura da miscela)."""
    n = int(images.shape[0])
    dst = float(dst)
    if n < 2 or abs(dst - FPS) < 1e-3:
        return images
    m = max(1, int(round(n * dst / FPS)))
    pos = torch.arange(m, dtype=torch.float64) * (FPS / dst)
    pos = pos.clamp(0, n - 1)
    if abs(dst - FPS) <= 1.0:
        return images[pos.round().long()]
    i0 = pos.floor().long().clamp(0, n - 1)
    i1 = (i0 + 1).clamp(max=n - 1)
    w = (pos - i0.to(pos.dtype)).to(images.dtype).view(-1, 1, 1, 1)
    return images[i0] * (1 - w) + images[i1] * w


class zzz_H3_TransitionDirectorAssemble:
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"plan": ("ZZZ_H3_TD_PLAN",), "decoded": ("IMAGE",)},
                "optional": {"audio_generato": ("AUDIO", {"tooltip": "Audio decodificato da H3: se collegato riempie il PONTE (buco)."}),
                             "fps_uscita": (["originale (fps di A)", "24 (H3)"], {"default": "originale (fps di A)",
                                            "tooltip": "Originale: il video esce agli fps del clip A (H3 genera a 24 e viene ricampionato nel tempo)."})}}

    RETURN_TYPES = ("IMAGE", "AUDIO", "IMAGE", "FLOAT")
    RETURN_NAMES = ("images", "audio", "solo_finestra", "fps")
    FUNCTION = "run"
    CATEGORY = "zzz/h3"
    DESCRIPTION = "Rimonta la timeline: frame veri + parte generata da H3, audio originale in dissolvenza nella zona."

    def run(self, plan, decoded, audio_generato=None, fps_uscita="originale (fps di A)"):
        if not isinstance(plan, dict) or plan.get("type") != "zzz_h3_td":
            raise ValueError("Assemble: serve il plan di ZZZ H3 Transition Director")
        L = plan["L"]
        if decoded.shape[0] < L or tuple(decoded.shape[1:3]) != (plan["H"], plan["W"]):
            raise ValueError("Assemble: decode con forma %s, atteso %d x %dx%d" % (tuple(decoded.shape), L, plan["H"], plan["W"]))
        real = plan["real"].to(decoded.device, decoded.dtype)
        off = plan["w0"] - plan["T0"]
        g0, g1 = plan["g0"], plan["g1"]
        images = real.clone()
        images[off + g0: off + g1] = decoded[g0:g1]
        audio = plan["audio"]
        if audio_generato is not None and plan["mode"] == "ponte":
            sr = audio["sample_rate"]
            w = audio_generato["waveform"]
            if audio_generato["sample_rate"] != sr:
                import torchaudio
                w = torchaudio.functional.resample(w, audio_generato["sample_rate"], sr)
            w = w[0]
            if w.shape[0] == 1:
                w = w.expand(2, -1)
            mix = audio["waveform"][0].clone()
            a = int(round((plan["z0"] - plan["T0"]) / FPS * sr))
            b = int(round((plan["z1"] - plan["T0"]) / FPS * sr))
            ga = int(round((plan["z0"] - plan["w0"]) / FPS * sr))
            k = max(0, min(b - a, w.shape[1] - ga))
            mix[:, a:a + k] = w[:2, ga:ga + k].to(mix.dtype)
            audio = {"waveform": mix[None], "sample_rate": sr}
        out_fps = float(FPS)
        if str(fps_uscita).startswith("originale"):
            out_fps = float(plan.get("src_fps") or FPS)
            if 1.0 <= out_fps <= 240.0 and abs(out_fps - FPS) > 1e-3:
                images = resample_fps(images, out_fps)
                print("[%s %s] uscita ricampionata da %d a %.3f fps (%d -> %d frame)" % (
                    _OWNER, VERSION, FPS, out_fps, plan["real"].shape[0], images.shape[0]))
            else:
                out_fps = float(FPS)
        return (images, audio, decoded[:L], out_fps)


NODE_CLASS_MAPPINGS = {
    "zzz_H3_TransitionDirector": zzz_H3_TransitionDirector,
    "zzz_H3_TransitionDirectorAssemble": zzz_H3_TransitionDirectorAssemble,
}
NODE_DISPLAY_NAME_MAPPINGS = {
    "zzz_H3_TransitionDirector": "ZZZ H3 Transition Director (timeline) " + VERSION,
    "zzz_H3_TransitionDirectorAssemble": "ZZZ H3 Transition Director Assemble " + VERSION,
}
