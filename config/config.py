#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
@Time    : 2026-03-12
@Author  : Levi Fang 000592
@File    : config.py
@Desc    : Configuration manager to load YAML configuration
"""
import os
import sys
import yaml
from typing import Any

sys.path.append(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from utils.transform_namespace_util import dict_to_namespace

ENV_RUN = os.environ.get("ENV_RUN", "LOCAL")


def _substitute_env_vars(obj: Any) -> Any:
    """Recursively substitute environment variables in config"""
    if isinstance(obj, dict):
        return {k: _substitute_env_vars(v) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [_substitute_env_vars(v) for v in obj]
    elif isinstance(obj, str) and obj.startswith('${') and obj.endswith('}'):
        env_var = obj[2:-1]
        return os.getenv(env_var, obj)
    else:
        return obj


# Load config
with open(
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.yaml"),
    'r', encoding='utf-8'
) as fp:
    CONFIG = yaml.load(fp, yaml.SafeLoader)

CONFIG = CONFIG[ENV_RUN]
CONFIG = _substitute_env_vars(CONFIG)
CONFIG = dict_to_namespace(CONFIG)

# Set OpenAI API key if available
api_key = getattr(getattr(CONFIG, 'LLM_CONFIG', None), 'API_KEY', '')
if api_key and not api_key.startswith('${'):
    os.environ["OPENAI_API_KEY"] = api_key
