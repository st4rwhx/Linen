"""Multi-character scenes: several rigs sharing one timeline."""

from __future__ import annotations

from .audio import (
    CATALOGUE,
    Ambience,
    Hit,
    SoundSlot,
    SpottingSheet,
    apply_spotting,
    read_mapping,
    spot_scene,
    write_mapping,
)
from .build import CUE_BLEND, BuiltScene, ScheduledCue, build_scene
from .director import build_director_prompt, scene_from_prompt
from .luau import scene_script, write_scene_script
from .schema import Actor, Cue, Scene, SceneError, json_schema
from .staging import GRAVITY, Placement, SetPlan, blockout, plan_set

__all__ = [
    "CATALOGUE",
    "CUE_BLEND",
    "GRAVITY",
    "Actor",
    "Ambience",
    "BuiltScene",
    "Cue",
    "Hit",
    "Placement",
    "Scene",
    "SceneError",
    "ScheduledCue",
    "SetPlan",
    "SoundSlot",
    "SpottingSheet",
    "apply_spotting",
    "blockout",
    "build_director_prompt",
    "build_scene",
    "json_schema",
    "plan_set",
    "read_mapping",
    "scene_from_prompt",
    "scene_script",
    "spot_scene",
    "write_mapping",
    "write_scene_script",
]
