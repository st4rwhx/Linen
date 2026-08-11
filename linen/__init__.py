"""Linen — Roblox animation from FreeMoCap captures and from text prompts.

Two entry points share one representation:

* :func:`linen.retarget.solve_clip` maps a FreeMoCap recording onto an R15 or R6
  rig, which is where the high-fidelity motion comes from;
* :func:`linen.generate.synthesize` builds a clip from a motion plan, which is
  what a language model writes when there is no capture to work from.

Both produce an :class:`~linen.clip.AnimationClip`, and
:func:`linen.export.write_rbxmx` writes that as a ``KeyframeSequence`` Roblox
Studio can import.
"""

from __future__ import annotations

from .clip import AnimationClip
from .export import write_rbxmx
from .rigs import R6, R15, get_rig

__version__ = "0.1.0"

__all__ = ["R6", "R15", "AnimationClip", "__version__", "get_rig", "write_rbxmx"]
