# -*- coding: utf-8 -*-
"""zzz H3 Transition Timing — un solo controllo in SECONDI per la transizione FL.

Il problema che risolve
-----------------------
In `FL MiniMax H3 Transition Prep` la durata non si imposta in secondi, e il
widget `length` NON e' la durata del bridge: e' la finestra totale. Dal suo
sorgente:

    generated_frames = frame_count - 2 * reference_frames

In piu' `length` deve stare sulla griglia H3 17k+5, e l'Assembler inserisce solo
i frame [reference_frames : length - reference_frames]. Quindi l'audio decodificato
(che copre TUTTA la finestra) va ritagliato esattamente su quella finestra, o
video e audio vanno fuori sincrono.

Questo nodo tiene insieme le tre cose: dai i secondi, lui calcola `length` e i due
tempi di taglio, che restano coerenti da soli quando cambi la durata.
"""

FPS = 24.0


def _snap_17k5(n, mode):
    """Porta n sulla griglia 17k+5 (5, 22, 39, 56, ...)."""
    if n <= 5:
        return 5
    k_low = (n - 5) // 17
    lo = 17 * k_low + 5
    hi = lo + 17 if lo < n else lo
    if mode == "giu":
        return lo
    if mode == "su":
        return hi if hi >= n else lo
    return lo if (n - lo) <= (hi - n) else hi   # vicino


def _mmss(seconds):
    """Formato accettato da AudioCrop: M:SS.mmm"""
    seconds = max(0.0, float(seconds))
    m = int(seconds // 60)
    s = seconds - m * 60
    return "%d:%06.3f" % (m, s)


class zzz_H3_TransitionTiming:
    ARROT = ["vicino", "su", "giu"]

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "secondi_transizione": ("FLOAT", {
                    "default": 4.0, "min": 0.2, "max": 60.0, "step": 0.1,
                    "tooltip": "Durata VOLUTA del bridge generato, in secondi. "
                               "E' la parte nuova che finisce fra le due clip, "
                               "non la finestra di campionamento."}),
                "reference_frames": ("INT", {
                    "default": 22, "min": 5, "max": 362, "step": 17,
                    "tooltip": "Deve combaciare con reference_frames del nodo "
                               "FL Transition Prep. Frame protetti per lato."}),
                "arrotondamento": (cls.ARROT, {
                    "default": "vicino",
                    "tooltip": "La griglia 17k+5 salta di 17 frame (0.71s), quindi "
                               "la durata esatta spesso non e' ottenibile."}),
                "fps": ("FLOAT", {"default": 24.0, "min": 1.0, "max": 120.0, "step": 0.1}),
            },
        }

    # crop_start/crop_end (STRING "M:SS.mmm") servono ai crop che vogliono testo,
    # ma ATTENZIONE: AudioCrop di audio-separation-nodes fa int() sui secondi e
    # rompe sui decimali. Con TrimAudioDuration usare invece start_secondi +
    # bridge_secondi_reali, che sono FLOAT e mantengono la precisione.
    RETURN_TYPES = ("INT", "FLOAT", "FLOAT", "STRING", "STRING", "INT", "INT",
                    "STRING")
    RETURN_NAMES = ("length", "start_secondi", "bridge_secondi_reali",
                    "crop_start", "crop_end", "reference_frames",
                    "bridge_frames", "report")
    FUNCTION = "run"
    CATEGORY = "zzz/h3"
    DESCRIPTION = ("Un solo controllo in secondi: calcola length sulla griglia "
                   "17k+5 e i tempi di taglio audio, coerenti fra loro.")

    def run(self, secondi_transizione, reference_frames, arrotondamento, fps):
        voluti = int(round(secondi_transizione * fps))
        grezzo = voluti + 2 * int(reference_frames)
        length = _snap_17k5(grezzo, arrotondamento)

        # la finestra deve contenere i frame protetti di entrambi i lati
        minimo = _snap_17k5(2 * int(reference_frames) + 5, "su")
        if length < minimo:
            length = minimo

        bridge = length - 2 * int(reference_frames)
        reali = bridge / fps
        start = reference_frames / fps
        end = (length - reference_frames) / fps

        note = []
        if bridge != voluti:
            note.append("richiesti %d frame (%.2fs), ottenuti %d (%.2fs): la griglia "
                        "17k+5 salta di 17 frame = %.2fs."
                        % (voluti, secondi_transizione, bridge, reali, 17 / fps))
        if bridge <= 0:
            note.append("ATTENZIONE: bridge <= 0. Alza i secondi o abbassa "
                        "reference_frames.")

        report = "\n".join(
            ["[zzz H3 Transition Timing]",
             "  length (-> FL Transition Prep)   %d" % length,
             "  reference_frames                 %d per lato" % reference_frames,
             "  bridge generato                  %d frame = %.2fs" % (bridge, reali),
             "  start_secondi (-> TrimAudioDuration) %.3f s" % start,
             "  duration      (-> TrimAudioDuration) %.3f s" % reali,
             "  frame finali = A + %d + B" % bridge]
            + ["  " + n for n in note])
        print(report)
        return (length, float(start), float(reali), _mmss(start), _mmss(end),
                int(reference_frames), bridge, report)


def _tc(seconds):
    """Formato dei timecode del prompt FL: MM:SS.mmm"""
    seconds = max(0.0, float(seconds))
    m = int(seconds // 60)
    return "%02d:%06.3f" % (m, seconds - m * 60)


class zzz_H3_TransitionScript:
    """Copione della transizione: scrivi le AZIONI come percentuale del bridge, i timecode assoluti li calcola lui.

    Il bridge reale dipende dalla griglia 17k+5 (29, 46, 63, 80... frame): se i tempi del prompt sono scritti a mano vanno
    risistemati ogni volta che cambi i secondi, e se sono sfasati il modello non arriva in tempo alla posa di B (scatto al
    raccordo). Qui t = (reference_frames + frazione * bridge_frames) / fps, sempre allineato al bridge vero.
    """
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "bridge_frames": ("INT", {"forceInput": True, "tooltip": "Dal nodo Transition Timing (bridge_frames)."}),
            "reference_frames": ("INT", {"forceInput": True, "tooltip": "Dal nodo Transition Timing (reference_frames)."}),
            "fps": ("FLOAT", {"default": 24.0, "min": 1.0, "max": 120.0, "step": 0.1}),
            "scena": ("STRING", {"multiline": True, "default":
                      "One single continuous shot, no cut. The man stays fully visible in the frame at all times."}),
            "azioni": ("STRING", {"multiline": True, "default":
                       "0% | the man turns away from the camera\n20% | the green fabric backdrop collapses onto the floor\n"
                       "55% | he runs and jumps toward the train\n85% | he grabs the handrail and hangs onto the train",
                       "tooltip": "Una azione per riga: 'percentuale | testo'. La percentuale e' la posizione NEL BRIDGE "
                                  "(0 = inizio del bridge, 100 = inizio di B)."}),
            "finale": ("STRING", {"multiline": True, "default":
                       "he stays in exactly the same pose and position he has at the start of the next shot",
                       "tooltip": "Frase finale: viene scritta con il timecode in cui parte B."}),
        }}

    RETURN_TYPES = ("STRING", "STRING", "FLOAT")
    RETURN_NAMES = ("transition_description", "report", "b_start_secondi")
    FUNCTION = "run"
    CATEGORY = "zzz/h3"
    DESCRIPTION = "Costruisce il prompt della transizione con i timecode calcolati dal bridge reale (azioni in % del bridge)."

    def run(self, bridge_frames, reference_frames, fps, scena, azioni, finale):
        bridge = max(1, int(bridge_frames))
        fps = float(fps)
        t0 = int(reference_frames) / fps
        t_b = (int(reference_frames) + bridge) / fps
        parts = [scena.strip()]
        rows = []
        for raw in str(azioni).splitlines():
            raw = raw.strip()
            if not raw or "|" not in raw:
                continue
            pc, txt = raw.split("|", 1)
            try:
                fr = float(pc.strip().rstrip("%")) / 100.0
            except ValueError:
                continue
            fr = min(1.0, max(0.0, fr))
            rows.append((t0 + fr * bridge / fps, txt.strip()))
        rows.sort()
        for t, txt in rows:
            parts.append("At %s %s." % (_tc(t), txt.rstrip(".")))
        if finale.strip():
            parts.append("From %s %s, until the next shot starts at %s." % (
                _tc(max(t0, t_b - 0.2 * bridge / fps)), finale.strip().rstrip("."), _tc(t_b)))
        text = " ".join(parts)
        rep = ("[zzz H3 Transition Script] bridge %d frame = %.2fs, da %s a %s (B parte a %s)\n" % (
            bridge, bridge / fps, _tc(t0), _tc(t_b), _tc(t_b))
            + "\n".join("  %s  %s" % (_tc(t), x) for t, x in rows))
        print(rep)
        return (text, rep, float(t_b))


NODE_CLASS_MAPPINGS = {"zzz_H3_TransitionTiming": zzz_H3_TransitionTiming,
                      "zzz_H3_TransitionScript": zzz_H3_TransitionScript}
NODE_DISPLAY_NAME_MAPPINGS = {
    "zzz_H3_TransitionTiming": "ZZZ H3 Transition Timing (secondi)",
    "zzz_H3_TransitionScript": "ZZZ H3 Transition Script (tempi automatici)",
}
