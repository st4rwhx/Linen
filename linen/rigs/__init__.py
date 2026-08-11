"""Roblox rig definitions."""

from __future__ import annotations

from .definition import BoneSource, Part, RigDefinition, Roll
from .r6 import R6
from .r15 import R15

RIGS: dict[str, RigDefinition] = {"R15": R15, "R6": R6}


def get_rig(name: str) -> RigDefinition:
    try:
        return RIGS[name.upper()]
    except KeyError:
        raise ValueError(f"unknown rig {name!r}; known rigs: {', '.join(sorted(RIGS))}") from None


__all__ = ["R6", "R15", "RIGS", "BoneSource", "Part", "RigDefinition", "Roll", "get_rig"]
