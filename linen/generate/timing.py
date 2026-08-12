"""Fit a plan to a requested duration.

The hosted generators cap a clip at ten seconds because a motion diffusion
model can only produce as much as its training window held.  Nothing here has
that constraint: a plan is a schedule over a pose vocabulary, so length is a
layout problem, not a model problem.  Ask for ninety seconds of walking and you
get ninety seconds of walking.

Which is exactly why the *strategy* matters. Stretching a two-second punch to
sixty produces slow motion, not a longer punch, and that is almost never what
someone asking for a minute of animation meant.  So the default reads the plan:
a walk cycle gets longer by cycling more, a one-shot action gets longer by
happening again, and only a plan with neither gets its timing scaled.
"""

from __future__ import annotations

from dataclasses import replace

from .posebook import CYCLES
from .schema import MotionPlan, PlanError, Segment

#: Sensible choices for a duration control. ``None`` means "whatever the
#: sequence naturally lasts", which is the right default.
DURATION_PRESETS: tuple[float | None, ...] = (None, 3.0, 5.0, 10.0, 15.0, 30.0, 60.0)

STRATEGIES = ("auto", "cycle", "repeat", "stretch", "trim")

MIN_DURATION = 0.1

#: Mirrors the range :class:`~linen.generate.schema.Segment` validates, so a bad
#: fit is reported in terms of the fit rather than as a schema violation.
MIN_RATE, MAX_RATE = 0.05, 12.0


def fit_duration(
    plan: MotionPlan, target: float | None, *, strategy: str = "auto"
) -> MotionPlan:
    """Return ``plan`` laid out to last ``target`` seconds.

    ``target`` of ``None`` leaves the plan alone.
    """
    if strategy not in STRATEGIES:
        raise PlanError(
            f"unknown fit strategy {strategy!r}; expected one of {', '.join(STRATEGIES)}"
        )
    if target is None:
        return plan
    if target < MIN_DURATION:
        raise PlanError(f"duration {target}s is below the {MIN_DURATION}s minimum")

    natural = plan.duration
    if natural <= 0:
        raise PlanError("cannot fit a plan of zero length")
    if abs(target - natural) < 1e-6:
        return plan

    chosen = strategy
    if chosen == "auto":
        if _cycle_segments(plan) and target > natural:
            chosen = "cycle"
        elif target > natural:
            chosen = "repeat"
        else:
            chosen = "stretch"

    fitted = {
        "cycle": _fit_by_cycling,
        "repeat": _fit_by_repeating,
        "stretch": _fit_by_stretching,
        "trim": _fit_by_trimming,
    }[chosen](plan, target)

    fitted.notes = _note(plan.notes, chosen, natural, target)
    fitted.validate()
    return fitted


def _cycle_segments(plan: MotionPlan) -> list[Segment]:
    return [segment for segment in plan.segments if segment.cycle is not None]


def _clone(plan: MotionPlan, segments: list[Segment]) -> MotionPlan:
    return MotionPlan(
        name=plan.name,
        segments=segments,
        fps=plan.fps,
        loop=plan.loop,
        priority=plan.priority,
        layers=[replace(layer) for layer in plan.layers],
        energy=plan.energy,
        notes=plan.notes,
    )


def _fit_by_cycling(plan: MotionPlan, target: float) -> MotionPlan:
    """Give the extra time to the cycles, at their existing cadence.

    The cadence is the point: a walk that fills a minute should be a minute of
    walking at the same speed, not one very slow step.  Everything that is not
    a cycle — the settle at the end of a wave, say — keeps the timing it was
    written with.
    """
    cycles = _cycle_segments(plan)
    if not cycles:
        return _fit_by_stretching(plan, target)

    extra = target - plan.duration
    total_cycle_time = sum(segment.end - segment.start for segment in cycles)
    if total_cycle_time <= 0:
        return _fit_by_stretching(plan, target)

    segments: list[Segment] = []
    cursor = 0.0
    for segment in plan.segments:
        length = segment.end - segment.start
        if segment.cycle is not None:
            length += extra * (length / total_cycle_time)
        segments.append(
            replace(segment, start=round(cursor, 4), end=round(cursor + length, 4))
        )
        cursor += length
    return _clone(plan, segments)


def _fit_by_repeating(plan: MotionPlan, target: float) -> MotionPlan:
    """Play the sequence again until the time is filled, trimming the last pass."""
    natural = plan.duration
    segments: list[Segment] = []
    offset = 0.0

    while offset < target - 1e-6:
        for segment in plan.segments:
            start = segment.start + offset
            if start >= target - 1e-6:
                break
            end = min(segment.end + offset, target)
            if end - start < 1e-6:
                continue
            segments.append(
                replace(
                    segment,
                    start=round(start, 4),
                    end=round(end, 4),
                    # The seam between passes needs a blend; the very first
                    # segment of the plan had none because nothing preceded it.
                    blend_in=segment.blend_in or (0.12 if offset > 0 else 0.0),
                )
            )
        offset += natural

    return _clone(plan, segments)


def _fit_by_stretching(plan: MotionPlan, target: float) -> MotionPlan:
    """Scale every beat, and slow cycles to match so cadence tracks the scale."""
    factor = target / plan.duration
    segments = []
    for segment in plan.segments:
        rate = segment.rate
        if segment.cycle is not None:
            base = rate if rate is not None else CYCLES[segment.cycle].default_rate
            rate = round(base / factor, 4)
            if not MIN_RATE <= rate <= MAX_RATE:
                # Stretching a gait this far means one step every several
                # seconds, which is not a slower walk, it is a broken one.
                raise PlanError(
                    f"stretching {segment.cycle!r} to {target:.1f}s puts its cadence "
                    f"at {rate}Hz, outside {MIN_RATE}-{MAX_RATE}Hz. To make the "
                    f"animation longer without slowing it down, use --fit cycle."
                )
        segments.append(
            replace(
                segment,
                start=round(segment.start * factor, 4),
                end=round(segment.end * factor, 4),
                blend_in=round(segment.blend_in * factor, 4),
                rate=rate,
            )
        )
    return _clone(plan, segments)


def _fit_by_trimming(plan: MotionPlan, target: float) -> MotionPlan:
    """Cut at the target, or hold the final segment out to it."""
    segments = []
    for segment in plan.segments:
        if segment.start >= target - 1e-6:
            break
        segments.append(replace(segment, end=round(min(segment.end, target), 4)))

    if not segments:
        segments = [replace(plan.segments[0], start=0.0, end=round(target, 4))]
    elif segments[-1].end < target:
        segments[-1] = replace(segments[-1], end=round(target, 4))
    return _clone(plan, segments)


def _note(existing: str, strategy: str, natural: float, target: float) -> str:
    how = {
        "cycle": "cycles extended",
        "repeat": "sequence repeated",
        "stretch": "timing scaled",
        "trim": "trimmed",
    }[strategy]
    fitted = f"Fitted {natural:.2f}s -> {target:.2f}s ({how})."
    return f"{existing} {fitted}".strip() if existing else fitted
