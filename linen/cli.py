"""Command line entry point: ``linen <command>``."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import __version__
from .clip import AnimationClip
from .export import reduce_keyframes, write_rbxmx
from .generate import MotionPlan, PlanError, synthesize
from .generate.providers import (
    PROVIDERS,
    NoProviderConfigured,
    ProviderError,
    configured_providers,
)
from .rigs import get_rig


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="linen", description=__doc__)
    parser.add_argument("--version", action="version", version=f"linen {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    _add_retarget(sub)
    _add_bvh(sub)
    _add_prompt(sub)
    _add_synth(sub)
    _add_scene(sub)
    sub.add_parser("providers", help="show which LLM providers are configured")
    sub.add_parser("vocabulary", help="list the pose and cycle names a plan may use")

    args = parser.parse_args(argv)
    handler = {
        "retarget": _cmd_retarget,
        "bvh": _cmd_bvh,
        "prompt": _cmd_prompt,
        "synth": _cmd_synth,
        "scene": _cmd_scene,
        "providers": _cmd_providers,
        "vocabulary": _cmd_vocabulary,
    }[args.command]

    try:
        return handler(args)
    except (
        PlanError,
        NoProviderConfigured,
        ProviderError,
        ValueError,
        FileNotFoundError,
    ) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


def _add_common_output(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("-o", "--out", type=Path, required=True, help="output .rbxmx path")
    parser.add_argument(
        "--rig",
        default="R15",
        help=(
            "target rig: R15, R6, or 'both' to write one file per rig "
            "(suffixed .R15.rbxmx / .R6.rbxmx). Default: R15"
        ),
    )
    parser.add_argument(
        "--tolerance",
        type=float,
        default=1.0,
        help="keyframe reduction tolerance in degrees; 0 keeps every frame",
    )
    parser.add_argument(
        "--preview",
        type=Path,
        default=None,
        help="also write a dense JSON clip for the viewport component",
    )
    parser.add_argument(
        "--motion",
        default="in-place",
        choices=("in-place", "natural", "loop"),
        help=(
            "in-place: root locked, the Humanoid keeps driving position "
            "(default); natural: bake root translation, for cutscenes; "
            "loop: root locked with a seamless seam. Root translation only "
            "exists on captured or imported clips."
        ),
    )


def _add_duration(parser: argparse.ArgumentParser) -> None:
    """Duration controls, for the commands that compose rather than record."""
    from .generate.timing import DURATION_PRESETS, STRATEGIES

    presets = ", ".join(f"{p:g}" for p in DURATION_PRESETS if p is not None)
    parser.add_argument(
        "--duration",
        default="auto",
        help=(
            f"target length in seconds — any value, no cap. 'auto' keeps the "
            f"sequence's natural length. Common choices: {presets}"
        ),
    )
    parser.add_argument(
        "--fit",
        default="auto",
        choices=STRATEGIES,
        help=(
            "how to reach --duration. auto: lengthen cycles if the plan has "
            "any, else replay the sequence, else scale. cycle/repeat/stretch/"
            "trim force one of those."
        ),
    )


def _add_retarget(sub) -> None:
    parser = sub.add_parser("retarget", help="FreeMoCap recording -> Roblox animation")
    parser.add_argument("recording", type=Path, help="mediapipe_body_3d_xyz.npy or .csv")
    parser.add_argument("--fps", type=float, required=True, help="capture frame rate")
    parser.add_argument("--units", default="mm", choices=("mm", "cm", "m"))
    parser.add_argument(
        "--axes",
        default="z_up",
        choices=("z_up", "y_up", "mediapipe_world"),
        help="source coordinate convention (default: z_up, what FreeMoCap writes)",
    )
    parser.add_argument("--name", default=None, help="animation name (default: file stem)")
    parser.add_argument("--smoothing", type=int, default=5, help="smoothing window in frames")
    _add_common_output(parser)


def _add_bvh(sub) -> None:
    parser = sub.add_parser(
        "bvh",
        help="BVH from any text-to-motion tool -> Roblox animation",
        description=(
            "Retarget a humanoid BVH — SayMotion, a locally run MoMask/MDM, a "
            "Mixamo download — onto a Roblox rig."
        ),
    )
    parser.add_argument("file", type=Path, help="a .bvh file")
    parser.add_argument("--skeleton", default="mixamo", help="source naming convention")
    parser.add_argument("--units", default="cm", choices=("mm", "cm", "m"))
    parser.add_argument(
        "--fps", type=float, default=None, help="override the file's frame time"
    )
    parser.add_argument("--name", default=None)
    parser.add_argument("--smoothing", type=int, default=3)
    _add_common_output(parser)


def _add_prompt(sub) -> None:
    parser = sub.add_parser("prompt", help="text -> motion plan -> Roblox animation")
    parser.add_argument("text", help="what the animation should do")
    parser.add_argument("--fps", type=float, default=30.0)
    parser.add_argument("--seed", type=int, default=0)
    _add_duration(parser)
    parser.add_argument(
        "--planner",
        default="auto",
        choices=("auto", "model", "offline"),
        help=(
            "auto: a language model if one answers, otherwise the offline "
            "planner; model: fail rather than fall back; offline: never touch "
            "the network (default: auto)"
        ),
    )
    parser.add_argument(
        "--provider",
        default=None,
        help="force one provider by name instead of trying the whole chain",
    )
    parser.add_argument(
        "--save-plan", type=Path, default=None, help="also write the plan as JSON"
    )
    _add_common_output(parser)


def _add_synth(sub) -> None:
    parser = sub.add_parser("synth", help="motion plan JSON -> Roblox animation, no network")
    parser.add_argument("plan", type=Path, help="a motion plan written by hand or by `prompt`")
    parser.add_argument("--seed", type=int, default=0)
    _add_duration(parser)
    _add_common_output(parser)


def _add_scene(sub) -> None:
    parser = sub.add_parser(
        "scene",
        help="a cast of rigs on one timeline -> a cinematic",
        description=(
            "Build a multi-character scene: one animation per actor covering "
            "the whole take, plus a Studio script that stages the rigs and "
            "plays them in sync."
        ),
    )
    parser.add_argument(
        "file", type=Path, nargs="?", help="a scene JSON file (omit with --from-prompt)"
    )
    parser.add_argument(
        "--from-prompt",
        default=None,
        help=(
            "write the scene from a description instead of reading a file. "
            "Needs a language model — choosing a cast and anchoring a cue "
            "sheet is the one part keyword matching cannot do. A local Ollama "
            "covers it for free."
        ),
    )
    parser.add_argument(
        "--save-scene", type=Path, default=None, help="also write the scene JSON"
    )
    parser.add_argument("--fps", type=float, default=30.0)
    parser.add_argument(
        "-o",
        "--out",
        type=Path,
        required=True,
        help="output directory for the per-actor .rbxmx files and the script",
    )
    parser.add_argument(
        "--planner",
        default="auto",
        choices=("auto", "model", "offline"),
        help="how each cue's prompt is planned (default: auto)",
    )
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument(
        "--tolerance", type=float, default=1.0, help="keyframe reduction, in degrees"
    )
    parser.add_argument(
        "--folder",
        default="ServerStorage.LinenAnimations",
        help="where the generated script looks for the imported KeyframeSequences",
    )
    parser.add_argument(
        "--preview", action="store_true", help="also write viewport JSON per actor"
    )


# ---------------------------------------------------------------------------
def _target_rigs(args) -> list:
    """The rigs to write. ``--rig both`` covers R15 and R6 in one run."""
    if args.rig.lower() == "both":
        return [get_rig("R15"), get_rig("R6")]
    return [get_rig(args.rig)]


def _solve_all(args, track, name: str) -> list:
    from .retarget import SolveOptions, solve_clip

    options = SolveOptions(
        root_motion=args.motion == "natural", smoothing_frames=args.smoothing
    )
    loop = args.motion == "loop"
    clips = []
    for rig in _target_rigs(args):
        clip = solve_clip(rig, track, options, name=name)
        clip.loop = loop
        clips.append(clip.with_loop_seam() if loop else clip)
    return clips


def _cmd_retarget(args) -> int:
    from .retarget import load_freemocap

    track = load_freemocap(
        args.recording, fps=args.fps, units=args.units, convention=args.axes
    )
    return _write(_solve_all(args, track, args.name or args.recording.stem), args)


def _cmd_bvh(args) -> int:
    from .sources import load_bvh

    track = load_bvh(args.file, skeleton=args.skeleton, units=args.units, fps=args.fps)
    return _write(_solve_all(args, track, args.name or args.file.stem), args)


def _cmd_prompt(args) -> int:
    from .generate.choreographer import plan_for_prompt

    providers = None
    if args.provider:
        from .generate.providers import BY_NAME

        if args.provider not in BY_NAME:
            raise ValueError(
                f"unknown provider {args.provider!r}; "
                f"known: {', '.join(sorted(BY_NAME))}"
            )
        providers = (BY_NAME[args.provider],)

    plan, source = plan_for_prompt(
        args.text, fps=args.fps, planner=args.planner, providers=providers
    )
    print(f"plan from {source}: {len(plan.segments)} segments, {plan.duration:.2f}s")
    if plan.notes:
        print(f"  notes: {plan.notes}")
    if args.save_plan:
        args.save_plan.parent.mkdir(parents=True, exist_ok=True)
        args.save_plan.write_text(json.dumps(plan.to_dict(), indent=2))
        print(f"  plan -> {args.save_plan}")

    return _write(_synthesize_all(plan, args), args)


def _cmd_synth(args) -> int:
    plan = MotionPlan.from_dict(json.loads(args.plan.read_text()))
    return _write(_synthesize_all(plan, args), args)


def _synthesize_all(plan: MotionPlan, args) -> list:
    from .generate.timing import fit_duration

    plan = fit_duration(plan, _duration(args.duration), strategy=args.fit)
    if args.motion == "loop":
        plan.loop = True

    natural = f"{plan.duration:.2f}s"
    if args.duration != "auto":
        print(f"  fitted to {natural}: {plan.notes.rsplit('Fitted', 1)[-1].strip()}")
    return [synthesize(plan, rig, seed=args.seed) for rig in _target_rigs(args)]


def _duration(value: str) -> float | None:
    if value.strip().lower() in ("auto", "natural", ""):
        return None
    try:
        return float(value)
    except ValueError:
        raise ValueError(
            f"--duration expects seconds or 'auto', got {value!r}"
        ) from None


def _cmd_scene(args) -> int:
    from .scene import Scene, build_scene, scene_from_prompt, write_scene_script

    if (args.file is None) == (args.from_prompt is None):
        raise ValueError("pass either a scene file or --from-prompt, not both or neither")

    if args.from_prompt is not None:
        scene, provider = scene_from_prompt(args.from_prompt, fps=args.fps)
        print(f"scene from {provider}")
    else:
        scene = Scene.from_dict(json.loads(args.file.read_text()))

    if args.save_scene:
        args.save_scene.parent.mkdir(parents=True, exist_ok=True)
        args.save_scene.write_text(json.dumps(scene.to_dict(), indent=2))
        print(f"{args.save_scene}: scene")

    built = build_scene(scene, planner=args.planner, seed=args.seed)

    print(
        f"{scene.name}: {len(scene.actors)} actors, {len(built.schedule)} cues, "
        f"{built.duration:.2f}s"
    )
    for entry in built.schedule:
        what = entry.cue.prompt or entry.plan.name
        print(
            f"  {entry.start:6.2f}s  {entry.cue.actor:<10} {entry.cue.id:<14} "
            f"{what[:42]}  [{entry.source}]"
        )

    args.out.mkdir(parents=True, exist_ok=True)
    for actor_name, clip in built.clips.items():
        path = args.out / f"{scene.name}_{actor_name}.rbxmx"
        frames = (
            list(range(clip.frame_count))
            if args.tolerance <= 0
            else reduce_keyframes(clip, angular_tolerance_deg=args.tolerance)
        )
        write_rbxmx(clip, path, frames=frames)
        print(f"{path}: {clip.rig.name}, {len(frames)} keyframes")
        if args.preview:
            from .export.preview import write_preview

            write_preview(clip, args.out / f"{scene.name}_{actor_name}.json")

    script = write_scene_script(
        built, args.out / f"{scene.name}.server.luau", folder=args.folder
    )
    print(f"{script}: staging and playback script")
    print(f"import the .rbxmx files into {args.folder}, then run the script in Studio")
    return 0


def _cmd_providers(_args) -> int:
    ready = {p.name for p in configured_providers()}
    for provider in PROVIDERS:
        mark = "ok " if provider.name in ready else "-- "
        print(f"{mark} {provider.name:<11} {provider.env_key:<21} {provider.model}")
        print(f"     {provider.notes}")
    if not ready:
        print("\nNo key set. `linen synth` still works on a hand-written plan.")
    return 0


def _cmd_vocabulary(_args) -> int:
    from .generate import CYCLES, POSES
    from .generate.offline import ACTIONS

    print("poses (what a plan may schedule):")
    for name in sorted(POSES):
        print(f"  {name}")
    print("\ncycles:")
    for name, cycle in sorted(CYCLES.items()):
        print(f"  {name:<12} {cycle.default_rate} Hz, {len(cycle.keys)} keys")
    print("\noffline planner actions (words it recognises in a prompt):")
    for action in ACTIONS:
        flags = "".join(
            (" sided" if action.sided else "", " loopable" if action.loopable else "")
        )
        print(f"  {action.name:<12} {', '.join(action.keywords)}{flags}")
    return 0


def _write(clips: list[AnimationClip], args) -> int:
    for clip in clips:
        out = _suffixed(args.out, clip.rig.name, len(clips) > 1)
        frames = (
            list(range(clip.frame_count))
            if args.tolerance <= 0
            else reduce_keyframes(clip, angular_tolerance_deg=args.tolerance)
        )
        path = write_rbxmx(clip, out, frames=frames)
        print(
            f"{path}: {clip.rig.name}, {clip.frame_count} frames -> "
            f"{len(frames)} keyframes, {clip.duration:.2f}s"
        )
        if args.preview:
            from .export.preview import write_preview

            preview = _suffixed(args.preview, clip.rig.name, len(clips) > 1)
            print(f"{write_preview(clip, preview)}: viewport clip")

    print("import into Studio with Animation Editor > ... > Import > From File")
    return 0


def _suffixed(path: Path, rig: str, multiple: bool) -> Path:
    """``take.rbxmx`` becomes ``take.R15.rbxmx`` when writing more than one rig."""
    return path.with_suffix(f".{rig}{path.suffix}") if multiple else path


if __name__ == "__main__":
    raise SystemExit(main())
