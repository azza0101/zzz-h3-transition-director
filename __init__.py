# -*- coding: utf-8 -*-
from .director import NODE_CLASS_MAPPINGS as _M1, NODE_DISPLAY_NAME_MAPPINGS as _D1
from .caption import NODE_CLASS_MAPPINGS as _M2, NODE_DISPLAY_NAME_MAPPINGS as _D2
from .timing import NODE_CLASS_MAPPINGS as _M3, NODE_DISPLAY_NAME_MAPPINGS as _D3  # DURATA TRANSIZIONE (prima pacchetto separato zzz_h3_transition_timing)
from . import routes  # noqa: F401  (registra le rotte della GUI)

NODE_CLASS_MAPPINGS = {**_M1, **_M2, **_M3}
NODE_DISPLAY_NAME_MAPPINGS = {**_D1, **_D2, **_D3}
WEB_DIRECTORY = "./js"
__all__ = ["NODE_CLASS_MAPPINGS", "NODE_DISPLAY_NAME_MAPPINGS", "WEB_DIRECTORY"]
