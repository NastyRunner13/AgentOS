"""Shared HTTP adapter helpers."""

from __future__ import annotations

import os
from typing import Callable, Optional

import httpx

OnToken = Optional[Callable[[str], None]]


def _secret(pcfg: dict) -> str | None:
    env = pcfg.get("api_key_env")
    if not env:
        return None
    key = os.environ.get(env)
    if not key:
        raise RuntimeError(f"missing env {env} — set it in .env")
    return key


def _timeout(pcfg: dict) -> httpx.Timeout:
    seconds = float(pcfg.get("timeout_seconds", 120))
    return httpx.Timeout(seconds, connect=10.0)
