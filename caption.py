# -*- coding: utf-8 -*-
"""ZZZ Video Caption (Qwen3-VL): descrive da solo un video in una caption inglese, per Regenerate 2K IC (o altro).

Guarda N frame distribuiti sul video e scrive UN paragrafo: soggetti e aspetto, luogo, luce, camera e cosa succede in ordine.
Se `testo_manuale` non e' vuoto si usa quello (nessun modello). Risultato in CACHE per contenuto: rilanciare non ricalcola.
Usa models/LLM/Qwen-VL/Qwen3-VL-2B-Instruct (lo stesso del Ripple), caricato e scaricato subito per liberare la VRAM.
"""
import hashlib
import json
import logging
import os

import numpy as np
import torch

import folder_paths

_PROMPT = ("These are {n} frames taken in order from one short video clip. Write ONE paragraph (max 120 words) in English "
           "that describes the whole clip as a video caption: the main subject(s) and how they look (clothes, colours, "
           "accessories), the place, the lighting and time of day, the camera framing and movement, and what happens from the "
           "beginning to the end, in order. Plain visible facts only, no guesses about names or emotions. Output only the paragraph.")


def _model_dir():
    bases = folder_paths.get_folder_paths("LLM") if "LLM" in folder_paths.folder_names_and_paths else []
    for base in bases + [os.path.join(folder_paths.models_dir, "LLM")]:
        p = os.path.join(base, "Qwen-VL", "Qwen3-VL-2B-Instruct")
        if os.path.isdir(p):
            return p
    raise FileNotFoundError("ZZZ Video Caption: manca models/LLM/Qwen-VL/Qwen3-VL-2B-Instruct")


def _cache_file():
    return os.path.join(folder_paths.get_user_directory(), "zzz_video_caption_cache.json")


def _cache():
    try:
        with open(_cache_file(), encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _caption(pil_frames, prompt=None, max_new_tokens=220):
    import comfy.model_management as mm
    from transformers import AutoProcessor, AutoModelForImageTextToText
    dev = mm.get_torch_device()
    mm.free_memory(6.0 * 1024 ** 3, dev)
    path = _model_dir()
    proc = AutoProcessor.from_pretrained(path)
    model = AutoModelForImageTextToText.from_pretrained(path, dtype=torch.bfloat16, device_map=str(dev), attn_implementation="sdpa")
    try:
        content = [{"type": "image", "image": im} for im in pil_frames]
        content.append({"type": "text", "text": (prompt or _PROMPT).format(n=len(pil_frames))})
        inp = proc.apply_chat_template([{"role": "user", "content": content}], tokenize=True, add_generation_prompt=True,
                                       return_dict=True, return_tensors="pt").to(model.device)
        with torch.inference_mode():
            out = model.generate(**inp, max_new_tokens=max_new_tokens, do_sample=False)
        return proc.batch_decode(out[:, inp["input_ids"].shape[1]:], skip_special_tokens=True)[0].strip()
    finally:
        del model, proc
        mm.soft_empty_cache()
        torch.cuda.empty_cache()


def translate_en(text):
    """traduce una riga in inglese con lo stesso Qwen3-VL-2B (solo testo), in cache. Se e' gia' inglese la restituisce uguale."""
    t = (text or "").strip()
    if not t:
        return ""
    key = "tr1|%s" % hashlib.sha1(t.encode("utf-8")).hexdigest()
    c = _cache()
    if key in c:
        return c[key]
    import comfy.model_management as mm
    from transformers import AutoProcessor, AutoModelForImageTextToText
    dev = mm.get_torch_device()
    mm.free_memory(6.0 * 1024 ** 3, dev)
    path = _model_dir()
    proc = AutoProcessor.from_pretrained(path)
    model = AutoModelForImageTextToText.from_pretrained(path, dtype=torch.bfloat16, device_map=str(dev), attn_implementation="sdpa")
    try:
        msg = [{"role": "user", "content": [{"type": "text", "text":
               "Translate this film/camera direction into clear, natural English as a director would write it "
               "(for example 'movimento unico' = 'one single continuous movement', 'stacco' = 'cut'). "
               "If it is already English, repeat it unchanged. Keep every detail, add nothing. Output only the translation.\n\n" + t}]}]
        inp = proc.apply_chat_template(msg, tokenize=True, add_generation_prompt=True, return_dict=True, return_tensors="pt").to(model.device)
        with torch.inference_mode():
            out = model.generate(**inp, max_new_tokens=200, do_sample=False)
        res = proc.batch_decode(out[:, inp["input_ids"].shape[1]:], skip_special_tokens=True)[0].strip() or t
    finally:
        del model, proc
        mm.soft_empty_cache()
        torch.cuda.empty_cache()
    c[key] = res
    try:
        with open(_cache_file(), "w", encoding="utf-8") as f:
            json.dump(c, f, ensure_ascii=False, indent=1)
    except Exception:
        pass
    print("[zzz translate] %s -> %s" % (t, res))
    return res


_SCENE_PROMPT = ("These are {n} frames from one short video shot. Write ONE paragraph (max 90 words) in English describing ONLY "
                 "what is visible: the people and how they look (clothes, hair, accessories), the place and its objects, the light and "
                 "the colours. Do NOT describe camera movement, zoom, framing changes or actions over time. Output only the paragraph.")
_SHOT_PROMPT = ("Look at this video frame and answer with exactly one of these shot sizes and nothing else: "
                "extreme close-up, close-up, medium close-up, medium shot, medium wide shot, wide shot.")


def _pil_from(images, n):
    from PIL import Image
    k = int(images.shape[0])
    idx = sorted({int(round(i)) for i in np.linspace(0, k - 1, max(1, int(n)))})
    out = []
    for i in idx:
        im = Image.fromarray((images[i, ..., :3].clamp(0, 1).cpu().numpy() * 255).astype(np.uint8))
        im.thumbnail((640, 640))
        out.append(im)
    return out


def _cached(key_prefix, pil, prompt, max_new_tokens):
    h = hashlib.sha1()
    for im in pil:
        h.update(im.tobytes())
    key = "%s|%s" % (key_prefix, h.hexdigest())
    c = _cache()
    if key in c:
        return c[key]
    txt = _caption(pil, prompt, max_new_tokens).strip()
    c[key] = txt
    try:
        with open(_cache_file(), "w", encoding="utf-8") as f:
            json.dump(c, f, ensure_ascii=False, indent=1)
    except Exception:
        pass
    print("[zzz VideoCaption %s] %s" % (key_prefix, txt))
    return txt


def scene_caption(images, n=4):
    """descrizione SOLO di aspetto/luogo/luce (niente camera ne' azioni: il movimento lo misura il Director)."""
    return _cached("scene1", _pil_from(images, n), _SCENE_PROMPT, 180)


def shot_size(image):
    """dimensione dell'inquadratura di un frame: close-up / medium shot / wide shot ..."""
    t = _cached("shot1", _pil_from(image, 1), _SHOT_PROMPT, 8).lower().strip(" .")
    for k in ("extreme close-up", "medium close-up", "close-up", "medium wide shot", "medium shot", "wide shot"):
        if k in t:
            return k
    return t[:30]


class zzz_VideoCaption:
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "images": ("IMAGE", {"tooltip": "Frame del video (es. uscita images di Get Video Components o del Prepare Draft)."}),
            "frame_da_guardare": ("INT", {"default": 6, "min": 1, "max": 16,
                                          "tooltip": "Quanti frame, distribuiti su tutto il video, guarda il modello."}),
            "testo_manuale": ("STRING", {"multiline": True, "default": "",
                                         "tooltip": "Se scrivi qualcosa qui viene usato questo e il modello non parte."}),
        }}

    RETURN_TYPES = ("STRING",)
    RETURN_NAMES = ("caption",)
    FUNCTION = "run"
    CATEGORY = "zzz/h3"
    DESCRIPTION = "Caption automatica di un video con Qwen3-VL-2B (locale, in cache). Testo manuale = override."

    def run(self, images, frame_da_guardare, testo_manuale):
        if str(testo_manuale).strip():
            return (str(testo_manuale).strip(),)
        n = int(images.shape[0])
        idx = sorted({int(round(i)) for i in np.linspace(0, n - 1, int(frame_da_guardare))})
        from PIL import Image
        pil = []
        for i in idx:
            a = (images[i, ..., :3].clamp(0, 1).cpu().numpy() * 255).astype(np.uint8)
            im = Image.fromarray(a)
            im.thumbnail((640, 640))
            pil.append(im)
        h = hashlib.sha1()
        for im in pil:
            h.update(im.tobytes())
        key = "v1|%s" % h.hexdigest()
        c = _cache()
        if key in c:
            logging.info("[zzz VideoCaption] da cache: %s", c[key][:120])
            return (c[key],)
        txt = _caption(pil)
        c[key] = txt
        try:
            with open(_cache_file(), "w", encoding="utf-8") as f:
                json.dump(c, f, ensure_ascii=False, indent=1)
        except Exception as e:
            logging.warning("[zzz VideoCaption] cache non salvata: %s", e)
        logging.info("[zzz VideoCaption] %s", txt)
        print("[zzz VideoCaption] " + txt)
        return (txt,)


NODE_CLASS_MAPPINGS = {"zzz_VideoCaption": zzz_VideoCaption}
NODE_DISPLAY_NAME_MAPPINGS = {"zzz_VideoCaption": "ZZZ Video Caption (Qwen3-VL, automatica)"}
