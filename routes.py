# -*- coding: utf-8 -*-
"""Rotte della GUI del Transition Director (frame in unita' timeline = 24 fps)."""
import asyncio
import hashlib
import os
import subprocess
import time

import folder_paths
from aiohttp import web

from . import director as D

try:
    from server import PromptServer
except Exception:  # pragma: no cover
    PromptServer = None


def _thumb(name, frame, h):
    path, info = D.probe(name)
    t = max(0.0, min(info["duration"] - 0.5 / D.FPS, frame / D.FPS))
    cmd = [D._ffmpeg(), "-v", "error", "-ss", "%.6f" % t, "-i", path, "-map", "0:v:0", "-vf", "scale=-2:%d" % h,
           "-frames:v", "1", "-f", "image2pipe", "-vcodec", "mjpeg", "-q:v", "4", "-"]
    r = subprocess.run(cmd, capture_output=True, creationflags=D._NOWIN, timeout=60)
    if r.returncode != 0 or not r.stdout:
        raise RuntimeError(r.stderr.decode("utf8", "ignore")[-300:])
    return r.stdout


def _grab(name, frame):
    path, info = D.probe(name)
    t = max(0.0, min(info["duration"] - 0.5 / D.FPS, frame / D.FPS))
    sub = "zzz_h3td_ancore"
    d = os.path.join(folder_paths.get_input_directory(), sub)
    os.makedirs(d, exist_ok=True)
    base = os.path.splitext(os.path.basename(name))[0]
    fn = "%s_f%d_%s.png" % (base, int(frame), hashlib.sha1(str(time.time()).encode()).hexdigest()[:6])
    out = os.path.join(d, fn)
    cmd = [D._ffmpeg(), "-v", "error", "-y", "-ss", "%.6f" % t, "-i", path, "-map", "0:v:0", "-frames:v", "1", out]
    r = subprocess.run(cmd, capture_output=True, creationflags=D._NOWIN, timeout=60)
    if r.returncode != 0 or not os.path.isfile(out):
        raise RuntimeError(r.stderr.decode("utf8", "ignore")[-300:])
    return sub + "/" + fn


def _solve(body):
    pa, ia = D.probe(body["video_a"])
    pb, ib = D.probe(body["video_b"])
    tl = D.parse_timeline(body.get("timeline") or "{}")
    res = {"a": {"tl_frames": ia["tl_frames"], "fps": ia["fps"], "w": ia["width"], "h": ia["height"]},
           "b": {"tl_frames": ib["tl_frames"], "fps": ib["fps"], "w": ib["width"], "h": ib["height"]}}
    try:
        p = D.solve_auto(tl, ia["tl_frames"], ib["tl_frames"], int(body.get("contesto", 22)), int(body.get("zona_minima", 24)),
                         bool(body.get("zona_automatica", True)), str(body.get("transition_zone", "medium")))
        res["plan"] = D.summary(p)
    except Exception as e:
        res["error"] = str(e)
    return res


if PromptServer is not None:
    R = PromptServer.instance.routes

    @R.get("/zzz_h3td/videos")
    async def _videos(request):
        return web.json_response(D.list_videos())

    @R.get("/zzz_h3td/info")
    async def _info(request):
        try:
            _, info = D.probe(request.query.get("name", ""))
        except Exception as e:
            return web.json_response({"error": str(e)}, status=404)
        return web.json_response(info)

    @R.get("/zzz_h3td/thumb")
    async def _thumb_r(request):
        q = request.query
        loop = asyncio.get_running_loop()
        try:
            data = await loop.run_in_executor(None, _thumb, q.get("name", ""), int(float(q.get("frame", 0))), int(q.get("h", 90)))
        except Exception as e:
            return web.Response(status=500, text=str(e))
        return web.Response(body=data, content_type="image/jpeg", headers={"Cache-Control": "max-age=3600"})

    @R.post("/zzz_h3td/grab")
    async def _grab_r(request):
        body = await request.json()
        loop = asyncio.get_running_loop()
        try:
            name = await loop.run_in_executor(None, _grab, body.get("name", ""), int(body.get("frame", 0)))
        except Exception as e:
            return web.json_response({"error": str(e)}, status=500)
        return web.json_response({"image": name})

    @R.post("/zzz_h3td/solve")
    async def _solve_r(request):
        body = await request.json()
        loop = asyncio.get_running_loop()
        try:
            res = await loop.run_in_executor(None, _solve, body)
        except Exception as e:
            return web.json_response({"error": str(e)})
        return web.json_response(res)
