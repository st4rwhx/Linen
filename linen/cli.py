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
from .generate.providers import PROVIDERS, NoProviderConfigured, configured_providers
from .rigs import get_rig


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="linen", description=__doc__)
    parser.add_argument("--version", action="version", version=f"linen {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    _add_retarget(sub)
    _add_bvh(sub)
    _add_prompt(sub)
    _add_synth(sub)
    sub.add_parser("providers", help="show which LLM providers are configured")
    sub.add_parser("vocabulary", help="list the pose and cycle names a plan may use")

    args = parser.parse_args(argv)
    handler = {
        "retarget": _cmd_retarget,
        "bvh": _cmd_bvh,
        "prompt": _cmd_prompt,
        "synth": _cmd_synth,
        "providers": _cmd_providers,
        "vocabulary": _cmd_vocabulary,
    }[args.command]

    try:
        return handler(args)
    except (PlanError, NoProviderConfigured, ValueError, FileNotFoundError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


def _add_common_output(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("-o", "--out", type=Path, required=True, help="output .rbxmx path")
    parser.add_argument(
        "--rig", default="R15", help="target rig: R15 or R6 (default: R15)"
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
    parser.add_argument("--loop", action="store_true")
    parser.add_argument(
        "--root-motion",
        action="store_true",
        help="bake HumanoidRootPart translation; off by default so the Humanoid stays in control",
    )
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
    parser.add_argument("--loop", action="store_true")
    parser.add_argument("--root-motion", action="store_true")
    parser.add_argument("--smoothing", type=int, default=3)
    _add_common_output(parser)


def _add_prompt(sub) -> None:
    parser = sub.add_parser("prompt", help="text -> motion plan -> Roblox animation")
    parser.add_argument("text", help="what the animation should do")
    parser.add_argument("--fps", type=float, default=30.0)
    parser.add_argument("--seed", type=int, default=0)
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
    _add_common_output(parser)


# ---------------------------------------------------------------------------
def _cmd_retarget(args) -> int:
    from .retarget import SolveOptions, load_freemocap, solve_clip

    rig = get_rig(args.rig)
    track = load_freemocap(
        args.recording, fps=args.fps, units=args.units, convention=args.axes
    )
    clip = solve_clip(
        rig,
        track,
        SolveOptions(root_motion=args.root_motion, smoothing_frames=args.smoothing),
        name=args.name or args.recording.stem,
    )
    clip.loop = args.loop
    if args.loop:
        clip = clip.with_loop_seam()
    return _write(clip, args)


def _cmd_bvh(args) -> int:
    from .retarget import SolveOptions, solve_clip
    from .sources import load_bvh

    track = load_bvh(args.file, skeleton=args.skeleton, units=args.units, fps=args.fps)
    clip = solve_clip(
        get_rig(args.rig),
        track,
        SolveOptions(root_motion=args.root_motion, smoothing_frames=args.smoothing),
        name=args.name or args.file.stem,
    )
    clip.loop = args.loop
    if args.loop:
        clip = clip.with_loop_seam()
    return _write(clip, args)


def _cmd_prompt(args) -> int:
    from .generate import plan_from_prompt

    providers = None
    if args.provider:
        from .generate.providers import BY_NAME

        if args.provider not in BY_NAME:
            raise ValueError(
                f"unknown provider {args.provider!r}; "
                f"known: {', '.join(sorted(BY_NAME))}"
            )
        providers = (BY_NAME[args.provider],)

    plan, provider = plan_from_prompt(args.text, fps=args.fps, providers=providers)
    print(f"plan from {provider}: {len(plan.segments)} segments, {plan.duration:.2f}s")
    if plan.notes:
        print(f"  notes: {plan.notes}")
    if args.save_plan:
        args.save_plan.parent.mkdir(parents=True, exist_ok=True)
        args.save_plan.write_text(json.dumps(plan.to_dict(), indent=2))
        print(f"  plan -> {args.save_plan}")

    clip = synthesize(plan, get_rig(args.rig), seed=args.seed)
    return _write(clip, args)


def _cmd_synth(args) -> int:
    plan = MotionPlan.from_dict(json.loads(args.plan.read_text()))
    clip = synthesize(plan, get_rig(args.rig), seed=args.seed)
    return _write(clip, args)


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

    print("poses:")
    for name in sorted(POSES):
        print(f"  {name}")
    print("cycles:")
    for name, cycle in sorted(CYCLES.items()):
        print(f"  {name:<8} {cycle.default_rate} Hz, keys: {len(cycle.keys)}")
    return 0


def _write(clip: AnimationClip, args) -> int:
    frames = (
        list(range(clip.frame_count))
        if args.tolerance <= 0
        else reduce_keyframes(clip, angular_tolerance_deg=args.tolerance)
    )
    path = write_rbxmx(clip, args.out, frames=frames)
    print(
        f"{path}: {clip.rig.name}, {clip.frame_count} frames -> {len(frames)} keyframes, "
        f"{clip.duration:.2f}s"
    )
    if args.preview:
        from .export.preview import write_preview

        print(f"{write_preview(clip, args.preview)}: viewport clip")
    print("import into Studio with Animation Editor > ... > Import > From File")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
