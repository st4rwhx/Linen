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
    #: actor -> the generated facial performance, as FACS keys.
    faces: dict = field(default_factory=dict)
    #: Where each actor is, over time: (actor, start, stop, from, to). A Roblox
    #: animation is in place, so travelling across the scene is this, not the
    #: clip.
    moves: list = field(default_factory=list)
    #: Cues whose travel disagrees with what the capture's feet are doing.
    skates: list = field(default_factory=list)
    #: What each contact actually achieved, in studs. A reach that fell short
    #: is reported rather than absorbed: an arm has a fixed length.
    reaches: list = field(default_factory=list)

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
    reaches = _solve_contacts(scene, schedule, clips)
    from .face import build_faces

    total = max((entry.end for entry in schedule), default=0.0)
    faces = build_faces(scene, schedule, total)
    moves, skates = _plan_moves(scene, schedule, clips)
    return BuiltScene(
        scene=scene,
        clips=clips,
        schedule=schedule,
        markers=markers,
        director=director,
        reaches=reaches,
        faces=faces,
        moves=moves,
        skates=skates,
    )


#: How far a travel speed may disagree with what the feet are doing before it
#: is worth saying. Below this nobody sees it; above it, the character glides.
SKATE_TOLERANCE = 0.35


def _plan_moves(scene: Scene, schedule: list[ScheduledCue], clips):
    """Where every actor is over time, and where that fights the animation.

    A Roblox animation is in place by convention — the root is nailed — so a
    capture of someone walking forward plays as walking on the spot. Crossing
    the scene is the model moving, which is a separate thing and belongs to the
    script rather than the clip.

    The check that matters is speed. If a character is carried four studs in a
    second while its feet are stepping at one stud per second, it glides — the
    same footskate the polish pass measures inside a clip, one level up. It is
    reported in studs per second rather than corrected, because which of the
    two is wrong is the author's call: the distance, or the cue's length.
    """
    from ..rigs.kinematics import place_rotations

    moves, skates = [], []
    where = {actor.name: np.asarray(actor.position, dtype=float) for actor in scene.actors}

    for entry in sorted(schedule, key=lambda e: e.start):
        if entry.cue.move_to is None:
            continue
        actor = entry.cue.actor
        start = where[actor]
        target = entry.cue.move_to
        if isinstance(target, str):
            # Stop short of them, along the line between the two. A destination
            # that is a person is a relationship, and it stays true wherever
            # the stage ends up.
            them = where[target]
            offset = them - start
            offset[1] = 0.0
            distance = float(np.linalg.norm(offset))
            goal = (
                them - offset / distance * entry.cue.stop_at
                if distance > 1e-6
                else np.array(start, dtype=float)
            )
        else:
            goal = np.asarray(target, dtype=float)
        # A destination is a place on the floor. Walking does not change how
        # tall someone is, so the height is the actor's own — a written Y that
        # disagrees is almost always a copied coordinate, and honouring it
        # sends the character gliding through the air.
        goal[1] = start[1]
        span = max(entry.end - entry.start, 1e-3)
        travelled = float(np.linalg.norm(goal - start))
        moves.append((actor, entry.start, entry.end, tuple(start), tuple(goal)))
        where[actor] = goal

        clip = clips.get(actor)
        if clip is None or travelled < 1e-6:
            continue
        stepping = _foot_speed(clip, entry, place_rotations)
        carried = travelled / span
        if stepping > 1e-6 and abs(carried - stepping) / max(stepping, carried) > SKATE_TOLERANCE:
            skates.append((entry.cue.id, actor, carried, stepping))
    return moves, skates


def _foot_speed(clip, entry: ScheduledCue, place_rotations) -> float:
    """The speed the body is asking to travel at, from the foot on the ground.

    Under a nailed root a planted foot slides backwards at exactly the speed
    the character is moving forwards — that is the whole idea behind the
    footskate measurement this project already does inside a clip. So the
    speed is read from the *lowest* foot each frame, which is the one in
    contact, and taken as a median so a swing passing low does not set it.

    Averaging both feet instead gives a number that is half swing, and it
    comes out roughly the same whatever the clip is doing — a check that fires
    on everything, which is a check that says nothing.
    """
    feet = [p for p in clip.rig.animated_parts if p.endswith(("Foot", "Leg"))]
    low = max(round(entry.start * clip.fps), 0)
    high = min(round(entry.end * clip.fps), clip.frame_count - 1)
    if not feet or high - low < 3:
        return 0.0

    grounded = []
    for frame in range(low, high + 1):
        pose = {name: track[frame] for name, track in clip.rotations.items()}
        placed = place_rotations(clip.rig, pose)
        here = {part: placed[part][0] for part in feet}
        grounded.append(min(here, key=lambda part: here[part][1]))

    speeds = []
    for index in range(1, len(grounded)):
        if grounded[index] != grounded[index - 1]:
            continue  # the contact changed feet; that step is not a speed
        part = grounded[index]
        frame = low + index
        before = place_rotations(
            clip.rig, {n: track[frame - 1] for n, track in clip.rotations.items()}
        )[part][0]
        after = place_rotations(
            clip.rig, {n: track[frame] for n, track in clip.rotations.items()}
        )[part][0]
        speeds.append(float(np.linalg.norm((after - before)[[0, 2]])) * clip.fps)
    return float(np.median(speeds)) if speeds else 0.0


def _actor_yaw(scene: Scene, actor) -> float:
    """Which way an actor faces, as degrees, however the scene said it.

    `facing` may name another actor, which is a relationship rather than an
    angle — it stays true when either of them moves, and it has to be resolved
    against the staging before any contact can be solved in world space.
    """
    if isinstance(actor.facing, (int, float)):
        return float(actor.facing)
    if isinstance(actor.facing, str):
        other = scene.actor(actor.facing)
        offset = np.asarray(other.position, dtype=float) - np.asarray(
            actor.position, dtype=float
        )
        if float(np.linalg.norm(offset[[0, 2]])) > 1e-6:
            return float(np.degrees(np.arctan2(offset[0], offset[2])))
    return 0.0


def _solve_contacts(scene: Scene, schedule: list[ScheduledCue], clips) -> list:
    """Bend the reaching arm so the hand arrives, for every contact event.

    This runs after splicing because it needs the finished animation: where a
    hand already is decides how far it has to travel, and both bodies have to
    be placed before either can be aimed at the other.
    """
    from .contact import BLEND_SECONDS, Reach, base_frame, solve_reach

    contacts = [event for event in scene.events if event.kind == "contact"]
    if not contacts:
        return []

    starts = {entry.cue.id: entry.start for entry in schedule}
    bases = {
        actor.name: base_frame(actor.position, _actor_yaw(scene, actor))
        for actor in scene.actors
    }
    blend = max(round(BLEND_SECONDS * scene.fps), 1)
    reaches = []

    for event in contacts:
        clip = clips.get(event.actor)
        if clip is None:
            continue
        begin = starts[event.cue] + event.offset
        frames = range(
            max(round(begin * scene.fps), 0),
            min(round((begin + event.hold) * scene.fps) + 1, clip.frame_count),
        )
        if not frames:
            continue

        targets = _contact_targets(scene, clips, bases, event, frames)
        if targets is None:
            continue

        fixed, shortfall = solve_reach(
            clip, bases[event.actor], event.limb, targets, blend_frames=blend
        )
        clips[event.actor] = fixed
        reaches.append(
            Reach(
                actor=event.actor,
                limb=event.limb,
                target=f"{event.target_actor or 'decor'}.{event.target_part}",
                start=begin,
                stop=begin + event.hold,
                shortfall=shortfall,
            )
        )
    return reaches


def _contact_targets(scene: Scene, clips, bases, event, frames):
    """Where the hand has to be, per frame, in world studs.

    A target on another actor moves with them, so it is read per frame from
    that actor's own animation. A target in the place stands still, and the
    scene has no geometry for it, so it is refused rather than guessed at.
    """
    from .contact import world_point

    if event.target_actor is None:
        # Reaching for scenery would need the place's geometry, which a scene
        # built without `--place` does not have. Saying so beats putting the
        # hand at the origin.
        raise SceneError(
            f"contact on cue {event.cue!r} reaches for {event.target_part!r} with no "
            f"'target_actor'. Reaching for something in the place is not solved yet; "
            f"name the character being touched instead."
        )

    other = clips.get(event.target_actor)
    if other is None:
        return None
    if event.target_part not in other.rig._by_name:
        raise SceneError(
            f"contact on cue {event.cue!r} reaches for {event.target_actor}."
            f"{event.target_part!r}, which is not a part of a {other.rig.name} rig"
        )

    base = bases[event.target_actor]
    return {
        frame: world_point(other, min(frame, other.frame_count - 1), event.target_part, base)
        for frame in frames
    }


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
        if event.kind == "contact":
            # Solved into the animation, not fired at playback. A marker for it
            # would tell the runtime to do something that has already been done.
            continue
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
    from pathlib import Path

    from ..library import best_window
    from ..retarget import SolveOptions, solve_clip
    from ..sources import ROBLOX_SUFFIXES, load_motion

    if Path(entry.capture).suffix.lower() in ROBLOX_SUFFIXES:
        # A finished Roblox animation — from a service, from Studio, keyed by
        # hand. It is already on a rig, so it is used as it is; there is no
        # capture behind it for `best_window` to read, and trimming it would
        # cut somebody's finished work in half.
        from ..sources.keyframes import read_keyframe_sequence

        clip = read_keyframe_sequence(entry.capture, fps=fps)
        if clip.rig.name != rig.name:
            raise SceneError(
                f"{Path(entry.capture).name} is a {clip.rig.name} animation and "
                f"{entry.cue.actor} is on {rig.name}. Convert it first: "
                f"`linen convert` moves an R6 animation onto R15."
            )
        clip.name = entry.plan.name
        return clip

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
