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

#: Seconds per beat when a prompt with several beats gives no duration.
DEFAULT_BEAT_SECONDS = 2.0

#: Imported here so ``--motion auto`` reads as one number in one place.
_LOOP_LIMIT = 5.0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="linen", description=__doc__)
    parser.add_argument("--version", action="version", version=f"linen {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    _add_retarget(sub)
    _add_bvh(sub)
    _add_prompt(sub)
    _add_synth(sub)
    _add_scene(sub)
    _add_library(sub)
    _add_convert(sub)
    _add_publish(sub)
    _add_survey(sub)
    sub.add_parser("providers", help="show which LLM providers are configured")
    _add_vocabulary(
        sub.add_parser("vocabulary", help="list the pose and cycle names a plan may use")
    )

    args = parser.parse_args(argv)
    _load_vocabularies(getattr(args, "vocabulary", None))

    handler = {
        "retarget": _cmd_retarget,
        "bvh": _cmd_bvh,
        "prompt": _cmd_prompt,
        "synth": _cmd_synth,
        "scene": _cmd_scene,
        "library": _cmd_library,
        "convert": _cmd_convert,
        "publish": _cmd_publish,
        "survey": _cmd_survey,
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
        "--no-viewer",
        action="store_true",
        help="skip the standalone .html 3D viewer written next to the .rbxmx",
    )
    parser.add_argument(
        "--polish",
        action="store_true",
        help=(
            "measure the clip against what an animator judges by eye — foot "
            "skate, broken arcs, joints bending backwards, frozen poses, "
            "twinning — and fix what can be fixed. Prints the numbers before "
            "and after"
        ),
    )
    parser.add_argument(
        "--desync",
        action="store_true",
        help=(
            "with --polish, also break genuine lockstep by shifting one limb "
            "half a gait cycle. Off by default: it assumes the clip is cyclic, "
            "and it is never applied to motion that is meant to be symmetric"
        ),
    )
    parser.add_argument(
        "--moon",
        action="store_true",
        help=(
            "also write a Moon Animator 2 save next to the .rbxmx, so the "
            "generated take can be finished by hand in the tool Roblox "
            "animators actually work in"
        ),
    )
    parser.add_argument(
        "--skin",
        type=Path,
        action="append",
        default=None,
        metavar="RIG.blend",
        help=(
            "dress the 3D viewer in a real rig instead of boxes. Takes a .blend "
            "saved without compression, holding one mesh object per Roblox part "
            "(Head, LeftUpperArm...). Repeatable; the viewer gets a rig picker. "
            "Proportions stay Linen's — only the shapes change."
        ),
    )
    parser.add_argument(
        "--motion",
        default="auto",
        choices=("auto", "in-place", "natural", "loop"),
        help=(
            "auto (default): root locked, and looping decided by measuring "
            "whether the wrap from last frame to first costs more than an "
            "ordinary frame; in-place: the same, never looped; natural: bake "
            "root translation, for cutscenes; loop: force the loop on. Root "
            "translation only exists on captured or imported clips."
        ),
    )


#: Extra pose vocabularies, by the name ``--vocabulary`` takes.
VOCABULARIES = ("military",)


def _add_vocabulary(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--vocabulary",
        action="append",
        default=None,
        choices=VOCABULARIES,
        help=(
            "load an extra pose vocabulary. Repeatable. Off by default and "
            "deliberately: registering one globally changed what every other "
            "prompt resolved to, which is not what asking for one style means"
        ),
    )


def _load_vocabularies(names: list[str] | None) -> None:
    for name in names or ():
        if name == "military":
            from .generate import military

            military.register()


def _add_convert(sub) -> None:
    parser = sub.add_parser(
        "convert",
        help="an existing R6 .rbxm animation -> R15",
        description=(
            "Move animations a game already has onto R15. Reads Roblox's binary "
            ".rbxm and rewrites the pose tree against the R15 rig, keeping every "
            "keyframe time, easing and non-body part exactly as it was."
        ),
    )
    parser.add_argument("files", type=Path, nargs="+", help=".rbxm files, or a folder")
    parser.add_argument(
        "-o", "--out", type=Path, required=True, help="folder to write the .rbxmx into"
    )


def _cmd_convert(args) -> int:
    from .convert import ConvertError, convert_file

    sources: list[Path] = []
    for entry in args.files:
        sources += sorted(entry.rglob("*.rbxm")) if entry.is_dir() else [entry]

    done, refused = 0, []
    for source in sources:
        try:
            report = convert_file(source, args.out / f"{source.stem}.rbxmx")
        except (ConvertError, ValueError) as exc:
            refused.append((source.name, str(exc)))
            continue
        done += 1
        print(f"  {report.line()}")

    print(f"{done} converties vers {args.out}")
    for name, why in refused:
        print(f"  refuse {name}: {why}", file=sys.stderr)
    return 0 if done else 1


def _add_survey(sub) -> None:
    parser = sub.add_parser(
        "survey",
        help="the Luau that reads your Studio place, so a scene can be staged in it",
        description=(
            "Writes a read-only Luau script. Run it in Studio's Command Bar and "
            "it prints your place as JSON: the rigs and whether each is R6 or "
            "R15, the named landmarks a camera can point at, and the sounds "
            "already there. Save that output and pass it to `linen scene "
            "--place`. Without it a cinematic is staged in a void — it plays, "
            "and every position in it is wrong for the game it was written for."
        ),
    )
    parser.add_argument(
        "-o", "--out", type=Path, default=Path("survey.luau"), help="where to write it"
    )
    parser.add_argument(
        "--print", action="store_true", dest="to_stdout",
        help="print the script instead, to paste straight into the Command Bar",
    )


def _cmd_survey(args) -> int:
    from .scene.place import SURVEY

    if args.to_stdout:
        print(SURVEY)
        return 0
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(SURVEY, encoding="utf-8")
    lines = len(SURVEY.splitlines())
    # Two different places, and typing the wrong thing in each is the mistake
    # everyone makes once: this command belongs in a terminal, and what Studio
    # wants is the Luau *inside* the file, not the command that wrote it.
    print(f"{args.out} ecrit — {lines} lignes de Luau.")
    print()
    print("  Ce qui va dans Studio, c'est le CONTENU de ce fichier, pas cette commande.")
    print("  La barre de commande de Studio ne parle que Luau.")
    print()
    print("  Le plus simple, ici dans le terminal :")
    print("      linen survey --print | clip        (Windows: copie dans le presse-papier)")
    print("      linen survey --print | pbcopy      (macOS)")
    print()
    print(f"  Ou ouvre {args.out} dans le Bloc-notes et copie tout.")
    print("  Puis dans Studio : View > Command Bar, colle, Entree.")
    print("  Copie enfin ce que l'Output affiche dans un fichier, et passe-le a :")
    print("      linen scene ... --place ce_fichier.json")
    return 0


def _add_publish(sub) -> None:
    parser = sub.add_parser(
        "publish",
        help="a .rbxmx animation -> a real rbxassetid:// on Roblox",
        description=(
            "Upload animations through Open Cloud and get the asset ids a running "
            "game needs, without opening Studio. The API key is read from "
            "$ROBLOX_API_KEY and is never accepted as an argument: arguments are "
            "readable by every process on the machine and are kept in shell "
            "history. Create a key at create.roblox.com/dashboard/credentials "
            "with the 'assets' permission, Read and Write."
        ),
    )
    parser.add_argument("files", type=Path, nargs="+", help=".rbxmx files, or a folder")
    parser.add_argument(
        "--creator",
        required=True,
        help="who owns the asset: 'user:ID' or 'group:ID'. A group needs the "
        "key's owner to hold that permission in the group.",
    )
    parser.add_argument(
        "--manifest",
        type=Path,
        help="JSON of filename -> asset id. Read before uploading, so a second "
        "run updates the same assets instead of making duplicates the game "
        "does not point at, and written after.",
    )
    parser.add_argument("--description", default="", help="asset description, on creation")
    parser.add_argument(
        "--asset-type",
        default="Animation",
        help="Roblox asset type. Animation is right for a KeyframeSequence; "
        "Model is right for a rig or a blockout. Default: Animation",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="say what would be uploaded, and check the key is readable, "
        "without sending anything",
    )


def _cmd_publish(args) -> int:
    from .cloud import (
        Creator,
        PublishError,
        api_key,
        load_manifest,
        publish,
        save_manifest,
    )

    creator = Creator.parse(args.creator)

    sources: list[Path] = []
    for entry in args.files:
        if not entry.exists():
            # Almost always the working directory rather than a typo: the paths
            # in the guide are relative to the project folder, and a terminal
            # opens in the home directory. Saying "no such file" alone sends
            # people looking for a missing file that is right where it belongs.
            print(
                f"error: {entry} n'existe pas depuis {Path.cwd()}.\n"
                f"  Les chemins sont relatifs au dossier courant. Va d'abord dans "
                f"le dossier du projet :\n"
                f"    cd chemin\\vers\\Linen\n"
                f"  puis relance la meme commande. Un chemin complet marche aussi.",
                file=sys.stderr,
            )
            return 1
        sources += sorted(entry.rglob("*.rbxmx")) if entry.is_dir() else [entry]
    if not sources:
        print(
            f"error: aucun .rbxmx dans {', '.join(str(f) for f in args.files)}",
            file=sys.stderr,
        )
        return 1

    known = load_manifest(args.manifest) if args.manifest else {}

    if args.dry_run:
        try:
            api_key()
        except PublishError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 1
        print(f"cle lue depuis l'environnement, proprietaire {creator}")
        for source in sources:
            existing = known.get(source.name)
            what = f"mise a jour de {existing}" if existing else "creation"
            print(f"  {source.name}: {what}")
        print(f"{len(sources)} fichiers, rien n'a ete envoye (--dry-run)")
        return 0

    done: dict[str, str] = dict(known)
    failed: list[tuple[str, str]] = []
    try:
        for source in sources:
            try:
                result = publish(
                    source,
                    creator,
                    description=args.description,
                    asset_id=known.get(source.name),
                    asset_type=args.asset_type,
                )
            except PublishError as exc:
                failed.append((source.name, str(exc)))
                continue
            done[source.name] = result.asset_id
            print(f"  {result.line()}")
            # Written after every single upload, not at the end. An asset that
            # exists and is not written down is worse than one that does not
            # exist: the next run cannot know, so it creates a second copy and
            # the game keeps pointing at the first. One interrupted batch must
            # cost the file it was on, not everything before it.
            if args.manifest:
                save_manifest(args.manifest, done, creator)
    except (KeyboardInterrupt, Exception):
        if args.manifest and done != known:
            save_manifest(args.manifest, done, creator)
            print(
                f"manifeste sauve dans {args.manifest} avant de s'arreter — "
                f"{len(done) - len(known)} identifiants gardes",
                file=sys.stderr,
            )
        raise

    if args.manifest and done != known:
        print(f"manifeste ecrit dans {args.manifest}")

    print(f"{len(done) - len(known)} publiees, {len(sources) - len(failed)} traitees")
    for name, why in failed:
        print(f"  echec {name}: {why}", file=sys.stderr)
    return 1 if failed else 0


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
        help="BVH or Collada capture -> Roblox animation",
        description=(
            "Retarget a humanoid capture — a Mixamo download, SayMotion, a "
            "locally run MoMask/MDM — onto a Roblox rig. Takes .bvh or .dae; "
            "Collada is the one Mixamo exports directly, so it needs no Blender."
        ),
    )
    parser.add_argument("file", type=Path, help="a .bvh or .dae file")
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
    _add_vocabulary(parser)
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
    parser.add_argument(
        "--name",
        default=None,
        help=(
            "animation name — what Studio shows in the Animation Editor and "
            "what the published asset is called. Defaults to the plan's name, "
            "or with --library to the sentence itself, which makes a poor one"
        ),
    )
    parser.add_argument(
        "--library",
        type=Path,
        default=None,
        help=(
            "pick real motion capture instead of composing poses. Takes an "
            "index built by `linen library build`. This is the route to motion "
            "that looks captured, because it was"
        ),
    )
    _add_common_output(parser)


def _add_synth(sub) -> None:
    parser = sub.add_parser("synth", help="motion plan JSON -> Roblox animation, no network")
    parser.add_argument("plan", type=Path, help="a motion plan written by hand or by `prompt`")
    _add_vocabulary(parser)
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
    parser.add_argument(
        "--place",
        type=Path,
        default=None,
        help=(
            "the output of `linen survey`, run in your Studio place. Actors "
            "whose names match a rig there are moved onto the real rig, at its "
            "real position and facing, and a shot aimed at something the place "
            "does not have is reported before you run anything."
        ),
    )
    parser.add_argument(
        "--library",
        type=Path,
        default=None,
        help=(
            "a `linen library build` index. A cue whose words match a real "
            "capture is played by that capture instead of by the pose "
            "vocabulary — which knows a dozen verbs and draws them. For a "
            "grapple, a shove or a throw, that is the difference between a "
            "scene that reads and one that does not."
        ),
    )
    parser.add_argument(
        "--animations",
        type=Path,
        default=None,
        help=(
            "a `linen publish --manifest` file. With it the generated script "
            "plays published rbxassetid:// animations, so the scene runs in a "
            "live game; without it, it registers the KeyframeSequences, which "
            "only works inside Studio."
        ),
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
        "--audio",
        type=Path,
        default=None,
        help=(
            "slot -> audio id mapping (default: <out>/<scene>.audio.json). Linen "
            "spots the scene, writes every sound it needs into this file, and "
            "keeps whatever ids you have already pasted in."
        ),
    )
    parser.add_argument(
        "--no-audio",
        action="store_true",
        help="skip spotting entirely: no derived impacts, footsteps or ambience",
    )
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
    parser.add_argument(
        "--no-viewer",
        action="store_true",
        help="skip the standalone <Scene>.html 3D viewer",
    )
    parser.add_argument(
        "--skin",
        type=Path,
        action="append",
        default=None,
        metavar="RIG.blend",
        help=(
            "dress the 3D viewer in a real rig instead of boxes. Takes a .blend "
            "saved without compression, holding one mesh object per Roblox part "
            "(Head, LeftUpperArm...). Repeatable; the viewer gets a rig picker. "
            "Proportions stay Linen's — only the shapes change."
        ),
    )



def _add_library(sub) -> None:
    parser = sub.add_parser(
        "library",
        help="index a mocap library, then let a prompt pick from it",
        description=(
            "Real motion capture beats a hand-built pose book, and no amount of "
            "work on the pose book changes that. Point this at a folder of BVH "
            "and it measures every clip, so a prompt can choose one. CMU's "
            "database is 2548 motions, ships descriptions, and its own README "
            "says the data is free for commercial projects."
        ),
    )
    action = parser.add_subparsers(dest="action", required=True)

    build = action.add_parser("build", help="index a folder of .bvh")
    build.add_argument("folder", type=Path)
    build.add_argument("-o", "--out", type=Path, required=True, help="index JSON to write")
    build.add_argument(
        "--descriptions",
        type=Path,
        default=None,
        help=(
            "a 'name<TAB>description' index, e.g. CMU's cmu-mocap-index-text.txt. "
            "Without it, filenames are used"
        ),
    )
    build.add_argument("--skeleton", default="mixamo")
    build.add_argument("--units", default="cm", choices=("mm", "cm", "m"))

    find = action.add_parser("search", help="what does this prompt match?")
    find.add_argument("index", type=Path)
    find.add_argument("text")
    find.add_argument("--limit", type=int, default=8)


def _cmd_library(args) -> int:
    from .library import Library, build_library, describe, read_descriptions

    if args.action == "build":
        descriptions = read_descriptions(args.descriptions) if args.descriptions else None

        def progress(index, total, path, error=None):
            if error:
                print(f"  skipped {path.name}: {error}", file=sys.stderr)
            elif index % 25 == 0:
                print(f"  {index}/{total}...", file=sys.stderr)

        library = build_library(
            args.folder,
            descriptions=descriptions,
            skeleton=args.skeleton,
            units=args.units,
            on_progress=progress,
        )
        if library.warning:
            print(f"attention: {library.warning}", file=sys.stderr)
        path = library.save(args.out)
        print(f"{path}: {len(library.entries)} clips indexes")
        return 0

    library = Library.load(args.index)
    hits = library.search(args.text, limit=args.limit)
    if not hits:
        print(f"aucun clip ne correspond a {args.text!r} dans {len(library.entries)} clips")
        return 1
    for score, entry in hits:
        print(f"{score:6.2f}  {entry.name:14} {entry.description[:46]:48} {describe(entry)}")
    return 0

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
    # `auto` decides per clip below, once there is a clip to measure.
    loop = args.motion == "loop"
    clips = []
    for rig in _target_rigs(args):
        clip = solve_clip(rig, track, options, name=name)
        wants_loop = loop
        if args.motion == "auto":
            from .polish import loop_seam

            ratio = loop_seam(clip)
            wants_loop = ratio <= _LOOP_LIMIT
            print(
                f"  boucle: raccord a {ratio:.1f}x une image ordinaire — "
                f"{'bouclee' if wants_loop else 'jouee une fois'}"
            )
        clip.loop = wants_loop
        clips.append(clip.with_loop_seam() if wants_loop else clip)
    return clips


def _cmd_retarget(args) -> int:
    from .retarget import load_freemocap

    track = load_freemocap(
        args.recording, fps=args.fps, units=args.units, convention=args.axes
    )
    return _write(_solve_all(args, track, args.name or args.recording.stem), args)


def _cmd_bvh(args) -> int:
    from .sources import load_bvh, load_collada

    # Chosen by suffix rather than by a flag: the file already says which it is,
    # and asking twice is a way to get told the wrong thing.
    read = load_collada if args.file.suffix.lower() == ".dae" else load_bvh
    track = read(args.file, skeleton=args.skeleton, units=args.units, fps=args.fps)
    return _write(_solve_all(args, track, args.name or args.file.stem), args)


def _cmd_prompt(args) -> int:
    from .generate.choreographer import plan_for_prompt

    if args.library is not None:
        return _prompt_from_library(args)

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

    clips = _synthesize_all(plan, args)
    if args.name:
        for clip in clips:
            clip.name = args.name
    return _write(clips, args)


def _prompt_from_library(args) -> int:
    """Answer a prompt with real capture rather than composed poses.

    A sentence with several beats becomes several clips, joined so the seam
    does not show. "Il court, il s'arrete, il frappe" is three retrievals.
    """
    from .generate.offline import _split_clauses
    from .library import Library, best_window, describe
    from .retarget import SolveOptions, solve_clip
    from .sources import load_bvh
    from .transitions import chain, seam_error

    library = Library.load(args.library)
    clauses = _split_clauses(args.text) or [args.text]

    chosen = []
    for clause in clauses:
        hits = library.search(clause, limit=4)
        if not hits:
            print(f"  (rien pour {clause!r}, ignore)", file=sys.stderr)
            continue
        score, entry = hits[0]
        print(f"{clause!r} -> {entry.name}: {entry.description}  "
              f"[{describe(entry)}]  score {score:.2f}")
        for other_score, other in hits[1:3]:
            print(f"     sinon: {other.name:12} {other.description[:40]:42} {other_score:.2f}")
        chosen.append((clause, entry))

    if not chosen:
        raise ValueError(
            f"aucun des {len(library.entries)} clips ne correspond a "
            f"{args.text!r}. Essaie `linen library search` pour voir ce que la "
            f"bibliotheque contient."
        )

    # Each beat gets an equal share of the asked-for length, so a three-part
    # sentence does not come back as forty seconds of the first take.
    target = _duration(args.duration)
    share = target / len(chosen) if target else DEFAULT_BEAT_SECONDS

    written = []
    for rig in _target_rigs(args):
        pieces = []
        for clause, entry in chosen:
            track = load_bvh(library.resolve(entry), skeleton="mixamo", units="cm")
            clip = solve_clip(
                rig,
                track,
                # `prompt` has no --smoothing of its own; capture needs a little.
                SolveOptions(root_motion=args.motion == "natural", smoothing_frames=3),
            )
            clip.name = entry.name
            # What the previous piece ended on: a window that answers the beat
            # but enters it mid-stride makes a seam nothing downstream can hide.
            follows = (
                {part: rotations[-1] for part, rotations in pieces[-1].rotations.items()}
                if pieces
                else None
            )
            lo, hi = best_window(clip, track, clause, share, follows=follows)
            if hi - lo < clip.frame_count:
                print(
                    f"  {entry.name}: fenetre {lo / clip.fps:.2f}-{hi / clip.fps:.2f}s "
                    f"sur {clip.duration:.1f}s"
                )
            pieces.append(_window(clip, lo, hi))

        joined = chain(pieces, name=args.name or args.text[:40])
        for seam in joined.metadata.get("seams", []):
            worst = max(seam_error(joined, seam + k) for k in range(8))
            print(f"  raccord a {seam / joined.fps:.2f}s : {worst:.1f} deg/frame")
        written.append(joined)
    return _write(written, args)


def _window(clip: AnimationClip, lo: int, hi: int) -> AnimationClip:
    """One stretch of a capture, as a clip of its own.

    Which stretch is :func:`linen.library.best_window`'s decision. This only
    does the cutting.
    """
    if lo <= 0 and hi >= clip.frame_count:
        return clip
    cut = AnimationClip(
        rig=clip.rig,
        fps=clip.fps,
        rotations={part: track[lo:hi].copy() for part, track in clip.rotations.items()},
        name=clip.name,
        metadata=dict(clip.metadata),
        loop=clip.loop,
        priority=clip.priority,
    )
    if clip.root_positions is not None:
        cut.root_positions = clip.root_positions[lo:hi].copy()
    return cut


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

    if args.place:
        from .scene.place import read_place, stage_in

        place = read_place(args.place)
        print(f"place: {place.line()}")
        for note in stage_in(scene, place):
            print(f"  {note}")

    if args.save_scene:
        args.save_scene.parent.mkdir(parents=True, exist_ok=True)
        args.save_scene.write_text(json.dumps(scene.to_dict(), indent=2))
        print(f"{args.save_scene}: scene")

    library = None
    if args.library:
        from .library import Library

        library = Library.load(args.library)
        print(f"bibliotheque: {len(library.entries)} captures")

    built = build_scene(scene, planner=args.planner, seed=args.seed, library=library)

    # Spotting comes before the clips are written, because it adds markers to
    # them: a derived footstep rides the animation exactly like an authored
    # event does, and is frame-exact for the same reason.
    from .scene import apply_spotting, read_mapping, spot_scene, write_mapping

    audio_path = args.audio or (args.out / f"{scene.name}.audio.json")
    mapping = {} if args.no_audio else read_mapping(audio_path)
    sheet = None
    if not args.no_audio:
        sheet = spot_scene(built, mapping=mapping)
        apply_spotting(built, sheet)

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
        markers = built.markers.get(actor_name, {})
        write_rbxmx(clip, path, frames=frames, markers=markers)
        events = sum(len(v) for v in markers.values())
        suffix = f", {events} marqueurs d'evenement" if events else ""
        print(f"{path}: {clip.rig.name}, {len(frames)} keyframes{suffix}")
        if args.preview:
            from .export.preview import write_preview

            write_preview(clip, args.out / f"{scene.name}_{actor_name}.json")

    if built.moves:
        print(f"  {len(built.moves)} deplacements d'acteur")
    for cue_id, actor, carried, stepping in built.skates:
        print(
            f"    {cue_id}: {actor} est porte a {carried:.1f} studs/s mais ses "
            f"pieds en font {stepping:.1f} — il glisse. Change la distance ou "
            f"la duree du cue.",
            file=sys.stderr,
        )

    if built.reaches:
        print(f"  {len(built.reaches)} contacts resolus dans l'animation :")
        for reach in built.reaches:
            print(f"    {reach.line()}")

    if built.director:
        print(f"  {len(built.director)} evenements sur l'horloge du realisateur "
              f"(camera, effets de decor)")

    animations: dict[str, str] = {}
    if args.animations:
        from .cloud import load_manifest

        published = load_manifest(args.animations)
        for actor_name in built.clips:
            asset = published.get(f"{scene.name}_{actor_name}.rbxmx")
            if asset:
                animations[actor_name] = f"rbxassetid://{asset}"
        absent = [a for a in built.clips if a not in animations]
        print(
            f"  {len(animations)}/{len(built.clips)} animations publiees"
            + (f" — a publier : {', '.join(absent)}" if absent else "")
        )

    script = write_scene_script(
        built,
        args.out / f"{scene.name}.client.luau",
        folder=args.folder,
        sheet=sheet,
        mapping=mapping,
        animations=animations,
    )
    print(f"{script}: staging and playback script")

    from .scene import blockout, plan_set

    set_plan = plan_set(built)
    blockout_path = args.out / f"{scene.name}_Blockout.rbxmx"
    blockout_path.write_text(blockout(set_plan))
    print(f"{blockout_path}: blockout du decor (placeholders gris, positions calculees)")

    if not args.no_viewer:
        from .export import scene_payload, write_viewer

        viewer = write_viewer(
            scene_payload(
                built, sheet=sheet, set_plan=set_plan, skins=_skins(args, None, len(scene.actors))
            ),
            args.out / f"{scene.name}.html",
        )
        print(f"{viewer}: visualiseur 3D — ouvre-le, c'est la scene entiere")

    print()
    print(set_plan.sheet())

    if sheet is not None:
        written = write_mapping(sheet, audio_path)
        filled = sum(1 for slot in sheet.used() if mapping.get(slot.name) or slot.default)
        print()
        print(sheet.sheet())
        print()
        print(f"{written}: {filled}/{len(sheet.used())} slots remplis — "
              f"colle les identifiants manquants, puis relance la meme commande")

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


def _skins(args, rig, actors: int = 1) -> list:
    """Load every --skin, reporting what each one covers.

    A skin that only matches some parts is still worth showing: the rest fall
    back to boxes, and the gap is named rather than silently drawn.
    """
    paths = getattr(args, "skin", None)
    if not paths:
        return []
    from .export.skin import TRIANGLE_BUDGET, load_skin

    # The budget is per frame for the whole cast, so a crowd scene gets
    # simpler geometry rather than a slower page.
    budget = max(TRIANGLE_BUDGET // max(actors, 1), 400)
    rigs = [rig.name] if rig is not None else ["R15", "R6"]
    skins = []
    for path in paths:
        for name in rigs:
            try:
                skin = load_skin(path, rig=name, budget=budget)
            except ValueError as exc:
                if name == rigs[-1]:
                    print(f"warning: {exc}", file=sys.stderr)
                continue
            covered = len(skin["parts"])
            gap = f", {len(skin['missing'])} en boîtes" if skin["missing"] else ""
            print(
                f"{path}: habillage {name} — {covered} parties, "
                f"{skin['triangles']} triangles{gap}"
            )
            skins.append(skin)
            break
    return skins


def _write(clips: list[AnimationClip], args) -> int:
    if getattr(args, "polish", False):
        clips = [_polished(clip, args) for clip in clips]

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

        if getattr(args, "moon", False):
            from .export.moon import write_moon

            save = write_moon(
                clip,
                out.with_suffix(".moon.rbxmx"),
                angular_tolerance_deg=max(args.tolerance, 0.0) or 1.0,
            )
            print(f"{save}: sauvegarde Moon Animator — glisse-la dans ServerStorage")

        if not args.no_viewer:
            from .export import clip_payload, write_viewer

            page = write_viewer(
                clip_payload(clip, skins=_skins(args, clip.rig)),
                out.with_suffix(".html"),
            )
            print(f"{page}: visualiseur 3D — ouvre-le avant d'importer quoi que ce soit")

    print("import into Studio with Animation Editor > ... > Import > From File")
    return 0


def _polished(clip: AnimationClip, args) -> AnimationClip:
    """Run the finishing pass, and print what changed rather than claiming it."""
    from .polish import polish

    fixed, before, after = polish(clip, allow_desync=getattr(args, "desync", False))
    print(f"finition — {clip.rig.name}")
    for line in before.lines()[1:]:
        print(f"  avant {line.strip()}")
    if fixed is clip:
        print("  (rien a corriger)")
        return clip
    for line in after.lines()[1:]:
        print(f"  apres {line.strip()}")
    return fixed


def _suffixed(path: Path, rig: str, multiple: bool) -> Path:
    """``take.rbxmx`` becomes ``take.R15.rbxmx`` when writing more than one rig."""
    return path.with_suffix(f".{rig}{path.suffix}") if multiple else path


if __name__ == "__main__":
    raise SystemExit(main())
