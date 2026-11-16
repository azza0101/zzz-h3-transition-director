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


def _caption(pil_frames):
    import comfy.model_management as mm
    from transformers import AutoProcessor, AutoModelForImageTextToText
    dev = mm.get_torch_device()
    mm.free_memory(6.0 * 1024 ** 3, dev)
    path = _model_dir()
    proc = AutoProcessor.from_pretrained(path)
    model = AutoModelForImageTextToText.from_pretrained(path, dtype=torch.bfloat16, device_map=str(dev), attn_implementation="sdpa")
    try:
        content = [{"type": "image", "image": im} for im in pil_frames]
        content.append({"type": "text", "text": _PROMPT.format(n=len(pil_frames))})
        inp = proc.apply_chat_template([{"role": "user", "content": content}], tokenize=True, add_generation_prompt=True,
                                       return_dict=True, return_tensors="pt").to(model.device)
        with torch.inference_mode():
            out = model.generate(**inp, max_new_tokens=220, do_sample=False)
        return proc.batch_decode(out[:, inp["input_ids"].shape[1]:], skip_special_tokens=True)[0].strip()
    finally:
        del model, proc
        mm.soft_empty_cache()
        torch.cuda.empty_cache()


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
