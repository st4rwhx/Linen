"""Multi-character scenes: several rigs sharing one timeline."""

from __future__ import annotations

from .build import CUE_BLEND, BuiltScene, ScheduledCue, build_scene
from .director import build_director_prompt, scene_from_prompt
from .luau import scene_script, write_scene_script
from .staging import GRAVITY, Placement, SetPlan, blockout, plan_set
from .schema import Actor, Cue, Scene, SceneError, json_schema

__all__ = [
    "CUE_BLEND",
    "GRAVITY",
    "Actor",
    "BuiltScene",
    "Cue",
    "Scene",
    "SceneError",
    "Placement",
    "ScheduledCue",
    "SetPlan",
    "blockout",
    "plan_set",
    "build_director_prompt",
    "build_scene",
    "json_schema",
    "scene_from_prompt",
    "scene_script",
    "write_scene_script",
]
