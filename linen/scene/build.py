"""Resolve a scene into one clip per actor.

Each actor comes out with a single animation spanning the whole scene rather
than one per cue. That is deliberate: a cinematic that plays as N tracks
started at N different moments drifts, and debugging the drift is miserable.
One track per actor, all started together at t=0, cannot drift.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from ..clip import IDENTITY_QUAT, AnimationClip
from ..generate.choreographer import plan_for_prompt
from ..generate.schema import MotionPlan
from ..generate.synth import synthesize
from ..generate.timing import fit_duration
from ..math3d import quat_slerp, unroll_quaternions
from ..rigs import get_rig
from .schema import Cue, Scene, SceneError

#: Seconds spent easing from whatever an actor was holding into a new cue.
CUE_BLEND = 0.12


@dataclass
class ScheduledCue:
    cue: Cue
    plan: MotionPlan
    start: float
    end: float
    source: str


@dataclass
class BuiltScene:
    scene: Scene
    #: actor name -> the clip covering the whole scene.
    clips: dict[str, AnimationClip]
    schedule: list[ScheduledCue]

    @property
    def duration(self) -> float:
        return max((entry.end for entry in self.schedule), default=0.0)


def build_scene(
    scene: Scene, *, planner: str = "auto", seed: int = 0
) -> BuiltScene:
    """Plan, schedule and synthesise every cue in ``scene``."""
    scene.validate()

    planned = _plan_cues(scene, planner)
    schedule = _schedule(scene, planned)
    clips = _splice(scene, schedule, seed)
    return BuiltScene(scene=scene, clips=clips, schedule=schedule)


def _plan_cues(scene: Scene, planner: str) -> dict[str, tuple[MotionPlan, str]]:
    """Every cue gets its plan first, because scheduling needs its length."""
    planned: dict[str, tuple[MotionPlan, str]] = {}
    for cue in scene.cues:
        if cue.plan is not None:
            plan, source = MotionPlan.from_dict(dict(cue.plan)), "inline"
        else:
            plan, source = plan_for_prompt(cue.prompt or "", fps=scene.fps, planner=planner)
        plan = fit_duration(plan, cue.duration, strategy=cue.fit)
        plan.fps = scene.fps
        plan.loop = plan.loop or cue.loop
        planned[cue.id] = (plan, source)
    return planned


def _schedule(
    scene: Scene, planned: dict[str, tuple[MotionPlan, str]]
) -> list[ScheduledCue]:
    """Turn anchors into absolute times, then check nobody is double-booked."""
    starts: dict[str, float] = {}
    by_id = {cue.id: cue for cue in scene.cues}

    def resolve(cue_id: str, chain: tuple[str, ...] = ()) -> float:
        if cue_id in starts:
            return starts[cue_id]
        if cue_id in chain:
            loop = " -> ".join((*chain[chain.index(cue_id) :], cue_id))
            raise SceneError(f"cues wait on each other in a loop: {loop}")

        cue = by_id[cue_id]
        if cue.after is not None:
            anchor = resolve(cue.after, (*chain, cue_id))
            base = anchor + planned[cue.after][0].duration
        elif cue.with_ is not None:
            base = resolve(cue.with_, (*chain, cue_id))
        elif cue.at is not None:
            base = cue.at
        else:
            # No anchor: follow whatever this actor was already doing, which is
            # what someone listing cues in order almost always means.
            previous = [
                other
                for other in scene.cues_for(cue.actor)
                if scene.cues.index(other) < scene.cues.index(cue)
            ]
            if previous:
                last = previous[-1]
                base = resolve(last.id, (*chain, cue_id)) + planned[last.id][0].duration
            else:
                base = 0.0

        start = base + cue.offset
        if start < 0:
            raise SceneError(
                f"cue {cue_id!r} starts at {start:.2f}s; an offset of "
                f"{cue.offset:+.2f}s pushed it before the scene begins"
            )
        starts[cue_id] = start
        return start

    schedule = [
        ScheduledCue(
            cue=cue,
            plan=planned[cue.id][0],
            start=resolve(cue.id),
            end=resolve(cue.id) + planned[cue.id][0].duration,
            source=planned[cue.id][1],
        )
        for cue in scene.cues
    ]
    schedule.sort(key=lambda entry: (entry.start, entry.cue.id))

    _reject_overlaps(schedule)
    total = max((entry.end for entry in schedule), default=0.0)
    from .schema import MAX_SCENE_SECONDS

    if total > MAX_SCENE_SECONDS:
        raise SceneError(
            f"the scene runs {total:.1f}s; keep it under {MAX_SCENE_SECONDS:.0f}s"
        )
    return schedule


def _reject_overlaps(schedule: list[ScheduledCue]) -> None:
    """One actor cannot play two cues at once.

    Silently letting the later cue win would look like the earlier one was
    dropped for no reason, so this names both and the overlap.
    """
    by_actor: dict[str, list[ScheduledCue]] = {}
    for entry in schedule:
        by_actor.setdefault(entry.cue.actor, []).append(entry)

    for actor, entries in by_actor.items():
        for previous, current in zip(entries, entries[1:]):
            if current.start < previous.end - 1e-6:
                raise SceneError(
                    f"{actor} is double-booked: {previous.cue.id!r} runs to "
                    f"{previous.end:.2f}s but {current.cue.id!r} starts at "
                    f"{current.start:.2f}s. Push it later with 'offset', or use "
                    f"'after' instead of 'at'."
                )


def _splice(scene: Scene, schedule: list[ScheduledCue], seed: int) -> dict[str, AnimationClip]:
    total = max((entry.end for entry in schedule), default=0.0)
    frames = max(int(round(total * scene.fps)) + 1, 1)
    blend_frames = max(int(round(CUE_BLEND * scene.fps)), 1)

    clips: dict[str, AnimationClip] = {}
    for actor in scene.actors:
        rig = get_rig(actor.rig)
        tracks = {
            part: np.tile(IDENTITY_QUAT, (frames, 1)) for part in rig.animated_parts
        }

        for entry in (e for e in schedule if e.cue.actor == actor.name):
            cue_clip = synthesize(entry.plan, rig, seed=seed)
            offset = int(round(entry.start * scene.fps))
            length = min(cue_clip.frame_count, frames - offset)
            if length <= 0:
                continue

            for part, track in tracks.items():
                incoming = cue_clip.rotations[part][:length]
                _blend_in(track, incoming, offset, blend_frames)
                track[offset : offset + length] = incoming
                # Hold the cue's final pose until something else takes over,
                # rather than snapping back to rest between beats.
                track[offset + length :] = incoming[-1]

        clips[actor.name] = AnimationClip(
            rig=rig,
            fps=scene.fps,
            rotations=tracks,
            name=f"{scene.name}_{actor.name}",
            metadata={"source": "scene", "scene": scene.name, "actor": actor.name},
        )
    return clips


def _blend_in(
    track: np.ndarray, incoming: np.ndarray, offset: int, blend_frames: int
) -> None:
    """Ease the frames just before a cue into its opening pose."""
    start = max(offset - blend_frames, 0)
    if offset <= start:
        return
    weights = np.linspace(0.0, 1.0, offset - start + 1)[1:]
    held = unroll_quaternions(track[start:offset])
    target = np.tile(incoming[0], (offset - start, 1))
    track[start:offset] = quat_slerp(held, target, weights)
