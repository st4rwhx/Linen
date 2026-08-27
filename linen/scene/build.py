"""Resolve a scene into one clip per actor.

Each actor comes out with a single animation spanning the whole scene rather
than one per cue. That is deliberate: a cinematic that plays as N tracks
started at N different moments drifts, and debugging the drift is miserable.
One track per actor, all started together at t=0, cannot drift.
"""

from __future__ import annotations

import itertools
from dataclasses import dataclass, field

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

#: Whether a capture answers a cue at all is `library.search`'s decision, not a
#: threshold here. It scores against the corpus, so the same words score
#: differently in a library of eleven clips and one of two thousand — an
#: absolute floor would refuse real matches in a small library and admit poor
#: ones in a large one. Measured on a real eleven-clip index: genuine matches
#: came back at 0.44 to 1.35, and "shove", "xyzzy quux" and "mange une pomme"
#: came back with nothing at all. `linen prompt --library` takes the top hit
#: the same way, so the same words give the same clip in both commands.


@dataclass
class ScheduledCue:
    cue: Cue
    plan: MotionPlan
    start: float
    end: float
    source: str
    #: When the cue was answered by a real capture rather than by the pose
    #: vocabulary: the file to retarget. Held as a path rather than a clip
    #: because the rig is not known until splicing — two actors may play the
    #: same beat on different rigs.
    capture: str | None = None


@dataclass
class BuiltScene:
    scene: Scene
    #: actor name -> the clip covering the whole scene.
    clips: dict[str, AnimationClip]
    schedule: list[ScheduledCue]
    #: actor -> frame -> KeyframeMarkers, for the events that ride an animation.
    markers: dict[str, dict[int, list[tuple[str, str]]]] = field(default_factory=dict)
    #: Events with no actor — camera cuts, world effects — on the director's
    #: clock, in seconds.
    director: list[tuple[float, object]] = field(default_factory=list)

    @property
    def duration(self) -> float:
        return max((entry.end for entry in self.schedule), default=0.0)


def build_scene(
    scene: Scene, *, planner: str = "auto", seed: int = 0, library=None
) -> BuiltScene:
    """Plan, schedule and synthesise every cue in ``scene``.

    With a ``library``, a cue whose words match a real capture is answered by
    that capture instead of by the pose vocabulary. The vocabulary knows a
    dozen verbs and draws them; a library knows what a body actually does. For
    anything the vocabulary has no word for — a grapple, a shove, a throw — it
    is the difference between a scene that reads and one that does not.
    """
    scene.validate()

    planned = _plan_cues(scene, planner, library)
    schedule = _schedule(scene, planned)
    clips = _splice(scene, schedule, seed)
    markers, director = _place_events(scene, schedule)
    return BuiltScene(
        scene=scene,
        clips=clips,
        schedule=schedule,
        markers=markers,
        director=director,
    )


def _place_events(scene: Scene, schedule: list[ScheduledCue]):
    """Turn cue-anchored events into frame markers and director-clock entries.

    An event on an actor becomes a KeyframeMarker inside that actor's
    animation, so it survives publishing and stays attached if the clip is
    retimed in Studio. An event with no actor has no animation to ride and goes
    on the director's clock instead.
    """
    starts = {entry.cue.id: entry.start for entry in schedule}
    markers: dict[str, dict[int, list[tuple[str, str]]]] = {}
    director: list[tuple[float, object]] = []

    for event in scene.events:
        when = starts[event.cue] + event.offset
        if when < 0:
            raise SceneError(
                f"{event.kind} event on cue {event.cue!r} fires at {when:.2f}s, "
                f"before the scene begins"
            )
        if event.actor is None:
            director.append((round(when, 4), event))
            continue

        frame = round(when * scene.fps)
        clip_frames = max(round(max(e.end for e in schedule) * scene.fps) + 1, 1)
        if not 0 <= frame < clip_frames:
            raise SceneError(
                f"{event.kind} event on cue {event.cue!r} fires at {when:.2f}s, "
                f"past the end of the scene"
            )
        by_frame = markers.setdefault(event.actor, {})
        by_frame.setdefault(frame, []).append((event.marker_name, event.marker_value()))

    director.sort(key=lambda pair: pair[0])
    return markers, director


def _plan_cues(scene: Scene, planner: str, library=None) -> dict[str, tuple]:
    """Every cue gets its plan first, because scheduling needs its length."""
    planned: dict[str, tuple] = {}
    for cue in scene.cues:
        capture = None
        if cue.plan is not None:
            plan, source = MotionPlan.from_dict(dict(cue.plan)), "inline"
        elif library is not None and cue.prompt and (hit := _from_library(library, cue)):
            plan, source, capture = hit
        else:
            plan, source = plan_for_prompt(cue.prompt or "", fps=scene.fps, planner=planner)
        plan = fit_duration(plan, cue.duration, strategy=cue.fit)
        plan.fps = scene.fps
        plan.loop = plan.loop or cue.loop
        planned[cue.id] = (plan, source, capture)
    return planned


def _from_library(library, cue: Cue):
    """The best capture for this cue's words, if the library has one.

    A miss is not a failure: a scene mixes beats the library covers with beats
    it does not, and the vocabulary still answers the rest. Silently swapping
    in a poor match would be worse than drawing the beat.
    """
    from ..generate.schema import MotionPlan, Segment

    hits = library.search(cue.prompt or "", limit=1)
    if not hits:
        return None
    _score, entry = hits[0]
    # The plan exists only to carry a length into scheduling — nothing is ever
    # synthesised from it, because the capture replaces it at splice time. It
    # still has to be a valid plan, so it holds one resting segment; if the
    # capture ever failed to load, a still actor is a better answer than a
    # crash halfway through a scene.
    length = cue.duration or entry.duration
    plan = MotionPlan(
        name=entry.name,
        segments=[Segment(start=0.0, end=max(length, 0.05), pose="rest")],
        notes=f"capture {entry.name}: {entry.description}",
    )
    return plan, f"library:{entry.name}", str(library.resolve(entry))


def _schedule(scene: Scene, planned: dict[str, tuple]) -> list[ScheduledCue]:
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
            capture=planned[cue.id][2],
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
        for previous, current in itertools.pairwise(entries):
            if current.start < previous.end - 1e-6:
                raise SceneError(
                    f"{actor} is double-booked: {previous.cue.id!r} runs to "
                    f"{previous.end:.2f}s but {current.cue.id!r} starts at "
                    f"{current.start:.2f}s. Push it later with 'offset', or use "
                    f"'after' instead of 'at'."
                )


def _splice(scene: Scene, schedule: list[ScheduledCue], seed: int) -> dict[str, AnimationClip]:
    total = max((entry.end for entry in schedule), default=0.0)
    frames = max(round(total * scene.fps) + 1, 1)
    blend_frames = max(round(CUE_BLEND * scene.fps), 1)

    clips: dict[str, AnimationClip] = {}
    for actor in scene.actors:
        rig = get_rig(actor.rig)
        tracks = {
            part: np.tile(IDENTITY_QUAT, (frames, 1)) for part in rig.animated_parts
        }

        for entry in (e for e in schedule if e.cue.actor == actor.name):
            cue_clip = (
                _capture_clip(entry, rig, scene.fps)
                if entry.capture
                else synthesize(entry.plan, rig, seed=seed)
            )
            offset = round(entry.start * scene.fps)
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


def _capture_clip(entry: ScheduledCue, rig, fps: float) -> AnimationClip:
    """Retarget the capture answering this cue, windowed to the cue's length.

    Retargeting happens here rather than at planning time because it needs the
    rig, and the same beat may be played by an R15 hero and an R6 thug.

    Which stretch of the take to use is `best_window`'s decision, the same one
    `linen prompt --library` makes: a fifteen-second take rarely wants its
    first two seconds, it wants the two seconds that answer the beat.
    """
    from ..library import best_window
    from ..retarget import SolveOptions, solve_clip
    from ..sources import load_motion

    track = load_motion(entry.capture, skeleton="mixamo", units="cm")
    clip = solve_clip(rig, track, SolveOptions(root_motion=False, smoothing_frames=3))
    clip.name = entry.plan.name

    wanted = (entry.end - entry.start) or clip.duration
    lo, hi = best_window(clip, track, entry.cue.prompt or "", wanted)
    if lo <= 0 and hi >= clip.frame_count:
        return clip
    return AnimationClip(
        rig=clip.rig,
        fps=clip.fps,
        rotations={part: track_[lo:hi] for part, track_ in clip.rotations.items()},
        name=clip.name,
        metadata=dict(clip.metadata),
        loop=clip.loop,
        priority=clip.priority,
    )


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
