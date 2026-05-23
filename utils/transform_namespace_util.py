# -*- encoding: utf-8 -*-
"""
@Time      :    2026-03-17 19:58:25
@Author    :    Levi Fang 000592
@File      :    transform_namespace_util.py
@Desc      :    
"""

import os
import sys
from types import SimpleNamespace
from typing import Any
sys.path.append(os.path.abspath(os.path.dirname(__file__)))
sys.path.append(os.path.dirname(os.path.abspath(os.path.dirname(__file__))))

def dict_to_namespace(d: Any) -> SimpleNamespace:
    """
    Recursively converting a dictionary to SimpleNamespace

    :param d: config data
    :return: config namespace
    """
    if isinstance(d, dict):
        return SimpleNamespace(**{k: dict_to_namespace(v) for k, v in d.items()})
    elif isinstance(d, list):
        return [dict_to_namespace(v) for v in d]
    else:
        return d
