"""Text-driven animation: prompt -> motion plan -> clip."""

from __future__ import annotations

from .choreographer import build_system_prompt, plan_from_prompt
from .posebook import CYCLES, POSES, cycle_names, pose_names, resolve_pose
from .providers import (
    PROVIDERS,
    NoProviderConfigured,
    Provider,
    ProviderError,
    complete_json,
    configured_providers,
)
from .schema import Layer, MotionPlan, PlanError, Segment, json_schema
from .synth import synthesize

__all__ = [
    "CYCLES",
    "POSES",
    "PROVIDERS",
    "Layer",
    "MotionPlan",
    "NoProviderConfigured",
    "PlanError",
    "Provider",
    "ProviderError",
    "Segment",
    "build_system_prompt",
    "complete_json",
    "configured_providers",
    "cycle_names",
    "json_schema",
    "plan_from_prompt",
    "pose_names",
    "resolve_pose",
    "synthesize",
]
