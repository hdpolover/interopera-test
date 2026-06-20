"""Config loader: deep-merge base.yaml + firm.yaml → FirmConfig pydantic model."""
from __future__ import annotations

import hashlib
import json
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict


class NonIgConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    include_fallen_angels: bool  # required, no default


class GREConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    group_key: Literal["issuer", "parent_issuer"]  # required, no default


class ConcentrationConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    gre: GREConfig


class OutputConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    utilization_format: Literal["percent_1dp", "truncated_bps"]  # required, no default


class FirmConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    firm_id: str
    non_ig: NonIgConfig
    concentration: ConcentrationConfig
    output: OutputConfig


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    """Deep-merge override into base. Override values take precedence."""
    result = dict(base)
    for key, value in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = value
    return result


def merge_configs(base: dict, override: dict) -> dict:
    """Return a new dict with override applied on top of base."""
    return _deep_merge(base, override)


def load_config(base_yaml: str, firm_yaml: str) -> FirmConfig:
    """Load and merge base + firm YAML, validate with pydantic."""
    with open(base_yaml) as f:
        base = yaml.safe_load(f) or {}
    with open(firm_yaml) as f:
        firm = yaml.safe_load(f) or {}
    merged = _deep_merge(base, firm)
    return FirmConfig(**merged)


def effective_config_hash(config: FirmConfig) -> str:
    """SHA-256 of the config's JSON representation (sorted keys)."""
    serialized = json.dumps(config.model_dump(), sort_keys=True)
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()
