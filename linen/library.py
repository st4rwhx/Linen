"""A searchable library of real motion capture, and a prompt that picks from it.

This exists because of a hard limit in :mod:`linen.generate.offline`. That
planner composes from sixteen hand-built actions, which is enough to block a
scene and will never be enough to look captured. No amount of work on the pose
book changes that: a pose book is a person drawing keyframes, and a run cycle
drawn by hand does not look like a run cycle recorded off a runner.

So the way to "amazing animation from a prompt" is not to invent the motion. It
is to **own a library of real motion and let the prompt choose from it** — which
is, not coincidentally, what game studios actually do. Nobody generates motion
at runtime; they record thousands of clips and build a selection system on top.

The licensing is what decides which library, and it decides it sharply. The
academic text-to-motion stack — AMASS, HumanML3D, SnapMoGen — is uniformly
research-only, so a model trained on it cannot legally feed a game you sell.
The CMU Graphics Lab database says the opposite in its own README: *"Use this
data! This data is free for use in research and commercial projects
worldwide."* It is 2548 motions, it ships a plain-text index describing every
one of them, and its BVH joint names already match the Mixamo mapping Linen
reads. Mixamo itself is the other commercially-clear option.

What this module adds is the catalogue and the search. Two things go into
matching a prompt against a clip:

**What it is called.** The words in the description, matched in French and
English, with the same normalisation the offline planner uses.

**What it measurably does.** A description says "walk"; it does not say how
fast, whether the feet leave the ground, or whether it turns. Those come from
forward kinematics over the retargeted clip, and they are what separates six
clips all labelled "run" from each other. A prompt asking for something *slow*
should not be answered by the fastest clip that happens to share a word.
"""

from __future__ import annotations

import json
import math
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path

import numpy as np

from .generate.offline import normalize
from .rigs import get_rig
from .rigs.kinematics import place_rotations

#: Index files declare this so a stale catalogue is refused rather than
#: half-understood.
FORMAT_VERSION = 1

#: Suffixes worth trying to index.
MOTION_SUFFIXES = (".bvh",)


class LibraryError(ValueError):
    """A library that cannot be built or read, phrased for whoever built it."""


@dataclass
class Entry:
    """One clip in the catalogue."""

    #: Path relative to the index file, so a library stays movable.
    path: str
    name: str
    #: Free text: the line from a dataset index, or the filename made readable.
    description: str
    duration: float
    fps: float
    frames: int
    #: Measured, not declared. See :func:`_measure`.
    steps_per_second: float = 0.0
    #: Studs per second the feet travel, which reads as effort.
    foot_speed: float = 0.0
    #: How far the hands get in front of the chest, in body heights.
    reach: float = 0.0
    #: Degrees the body turns over the clip.
    turn: float = 0.0
    #: How far the hips rise and fall over the clip, in hip heights.
    bob: float = 0.0
    #: Hip heights travelled per second across the ground. Separates
    #: locomotion from anything performed on the spot.
    travel: float = 0.0
    #: True when both feet leave the ground together at some point.
    airborne: bool = False
    #: Words the search matches on, normalised.
    terms: list[str] = field(default_factory=list)

    @property
    def searchable(self) -> str:
        return " ".join(self.terms)


@dataclass
class Library:
    """A catalogue of clips, and the search over it."""

    root: Path
    entries: list[Entry] = field(default_factory=list)
    source: str = ""

    def to_dict(self) -> dict:
        return {
            "format": FORMAT_VERSION,
            "source": self.source,
            "entries": [asdict(entry) for entry in self.entries],
        }

    @classmethod
    def load(cls, path: str | Path) -> Library:
        path = Path(path)
        try:
            data = json.loads(path.read_text())
        except json.JSONDecodeError as exc:
            raise LibraryError(f"{path}: index illisible ({exc})") from None
        if data.get("format") != FORMAT_VERSION:
            raise LibraryError(
                f"{path}: index au format {data.get('format')!r}, attendu "
                f"{FORMAT_VERSION}. Reconstruis-le avec `linen library build`."
            )
        return cls(
            root=path.parent,
            source=data.get("source", ""),
            entries=[Entry(**entry) for entry in data.get("entries", [])],
        )

    def save(self, path: str | Path) -> Path:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self.to_dict(), indent=1, ensure_ascii=False) + "\n")
        return path

    def resolve(self, entry: Entry) -> Path:
        """Where the clip actually is.

        Paths are stored relative to the folder that was indexed, so a library
        moved wholesale still works. But the index is often written somewhere
        else entirely — ``-o build/lib.json`` pointing at a download folder —
        so the folder it was built from is the fallback.
        """
        beside = (self.root / entry.path).resolve()
        if beside.exists():
            return beside
        if self.source:
            from_source = (Path(self.source) / entry.path).resolve()
            if from_source.exists():
                return from_source
        raise LibraryError(
            f"{entry.name} est dans l'index mais introuvable sur le disque "
            f"({beside}). La bibliotheque a bouge : reconstruis l'index."
        )

    def search(self, prompt: str, *, limit: int = 5) -> list[tuple[float, Entry]]:
        """Best clips for ``prompt``, best first."""
        return search(self, prompt, limit=limit)


# -- building -----------------------------------------------------------------


def build_library(
    folder: str | Path,
    *,
    descriptions: dict[str, str] | None = None,
    skeleton: str = "mixamo",
    units: str = "cm",
    rig: str = "R15",
    on_progress=None,
) -> Library:
    """Index every motion file under ``folder``.

    Each clip is retargeted once, purely to measure it. That is the expensive
    part and the reason this is a build step rather than something the search
    does live.
    """
    folder = Path(folder)
    if not folder.is_dir():
        raise LibraryError(f"{folder} n'est pas un dossier")

    files = sorted(
        path
        for suffix in MOTION_SUFFIXES
        for path in folder.rglob(f"*{suffix}")
    )
    if not files:
        raise LibraryError(
            f"{folder} ne contient aucun fichier {'/'.join(MOTION_SUFFIXES)}. "
            f"Télécharge une bibliothèque de mocap dedans d'abord."
        )

    library = Library(root=folder, source=str(folder))
    for index, path in enumerate(files):
        if on_progress is not None:
            on_progress(index, len(files), path)
        try:
            entry = _index_one(
                path, folder, descriptions or {}, skeleton=skeleton, units=units, rig=rig
            )
        except (ValueError, KeyError, OSError) as exc:
            # One malformed file in a 2500-clip download must not sink the
            # whole build; it is reported and skipped.
            if on_progress is not None:
                on_progress(index, len(files), path, error=str(exc))
            continue
        library.entries.append(entry)

    if not library.entries:
        raise LibraryError(
            f"aucun des {len(files)} fichiers de {folder} n'a pu être lu — "
            f"vérifie --skeleton et --units"
        )
    return library


def _index_one(
    path: Path,
    root: Path,
    descriptions: dict[str, str],
    *,
    skeleton: str,
    units: str,
    rig: str,
) -> Entry:
    from .retarget import SolveOptions, solve_clip
    from .sources import load_bvh

    track = load_bvh(path, skeleton=skeleton, units=units)
    clip = solve_clip(get_rig(rig), track, SolveOptions())

    description = descriptions.get(path.stem, "") or _readable(path.stem)
    entry = Entry(
        path=str(path.relative_to(root)),
        name=path.stem,
        description=description,
        duration=round(clip.duration, 3),
        fps=round(clip.fps, 3),
        frames=clip.frame_count,
    )
    _measure(entry, clip)
    _measure_world(entry, track)
    entry.terms = _terms(entry)
    return entry


@dataclass
class _World:
    """Per-frame ground truth from the capture, before the root is locked.

    Held as arrays rather than folded straight into an :class:`Entry` so the
    same pass can answer both questions: what the whole take does, and what any
    stretch of it does. Scoring a window by re-deriving it from scratch is
    quadratic in the number of windows, and a CMU take has hundreds.
    """

    #: Frames per second of the capture these came from.
    fps: float
    #: The subject's own hip height, the unit everything else is divided by.
    scale: float
    #: Hip height per frame.
    hips: np.ndarray
    #: The lower of the two ankles, per frame.
    lower: np.ndarray
    #: Hip centre on the ground plane, per frame.
    centre: np.ndarray

    def __len__(self) -> int:
        return len(self.hips)


def _world_series(track) -> _World | None:
    """Facts that only exist before the root is locked.

    The export is rotation-only, so a retargeted clip has a pelvis nailed in
    place — which means a run in it never leaves the ground, and its head never
    rises. Flight and bob are real, they are just not in that clip; they are in
    the capture it came from.

    Every number here is divided by the subject's own hip height, because a
    capture's units are frequently not what its file claims. These CMU files
    put the hips at 0.16 of whatever unit the loader produced. Ratios survive
    that; absolutes do not.
    """
    names = {name: index for index, name in enumerate(track.names)}
    if not {"left_ankle", "right_ankle", "left_hip", "right_hip"} <= set(names):
        return None

    positions = np.asarray(track.positions, dtype=float)
    hips = np.nanmean(
        positions[:, [names["left_hip"], names["right_hip"]], 1], axis=1
    )
    ankles = positions[:, [names["left_ankle"], names["right_ankle"]], 1]
    if not np.isfinite(hips).any() or not np.isfinite(ankles).any():
        return None

    scale = float(np.nanmedian(hips))
    if not np.isfinite(scale) or abs(scale) < 1e-6:
        return None

    ground_plane = positions[:, [names["left_hip"], names["right_hip"]], :][:, :, [0, 2]]
    return _World(
        fps=float(getattr(track, "fps", 0.0)) or 30.0,
        scale=abs(scale),
        hips=hips,
        lower=np.nanmin(ankles, axis=1),
        centre=np.nanmean(ground_plane, axis=1),
    )


def _fill_world(entry: Entry, world: _World, lo: int = 0, hi: int | None = None) -> None:
    """Write the world-space measurements of ``world[lo:hi]`` onto an entry.

    The ground reference stays the whole take's, not the window's: a window
    that happens to sit entirely in the air is airborne, and asking it to
    supply its own floor would say the opposite.
    """
    hi = len(world) if hi is None else hi
    hips = world.hips[lo:hi]
    lower = world.lower[lo:hi]
    centre = world.centre[lo:hi]
    if len(hips) < 2:
        return

    ground = float(np.nanpercentile(world.lower, 5))
    lift = 0.08 * world.scale
    # ``frames - 1`` intervals, not ``frames``: the same span the clip reports
    # as its duration, so a full-take window measures identically to the index.
    seconds = max((hi - lo - 1) / world.fps, 1e-6)

    entry.airborne = bool(int(np.nansum(lower - ground > lift)) > 2)
    entry.bob = round(float(np.nanmax(hips) - np.nanmin(hips)) / world.scale, 3)
    travelled = float(np.nansum(np.linalg.norm(np.diff(centre, axis=0), axis=1)))
    entry.travel = round(travelled / world.scale / seconds, 3)


def _measure_world(entry: Entry, track) -> None:
    world = _world_series(track)
    if world is not None:
        _fill_world(entry, world)


def _readable(stem: str) -> str:
    """``Standing_Melee_Attack_Horizontal`` -> a sentence a search can read."""
    words = re.split(r"[_\-.]+|(?<=[a-z])(?=[A-Z])", stem)
    return " ".join(word for word in words if word and not word.isdigit())


#: Sampling stride for measurement. Captures run at 120 fps, and nothing here
#: needs that resolution — this keeps a 2500-clip build to minutes, not hours.
MEASURE_STRIDE = 4


@dataclass
class _Posed:
    """Per-sample geometry from forward kinematics, sampled at the stride."""

    #: Samples per second — the clip's rate divided by the stride.
    rate: float
    #: Standing height of the rig, the unit reach is divided by.
    height: float
    #: Bottom of each sole, per sample.
    soles: dict[str, np.ndarray]
    #: Furthest either hand gets in front of the chest, per sample.
    reaches: np.ndarray
    #: Where the chest points, per sample.
    facings: np.ndarray

    def __len__(self) -> int:
        return len(self.facings)


def _posed_series(clip) -> _Posed | None:
    """Run forward kinematics once and keep what the measurements need."""
    rig = clip.rig
    frames = list(range(0, clip.frame_count, MEASURE_STRIDE))
    if len(frames) < 2:
        return None

    soles: dict[str, list[np.ndarray]] = {}
    reaches: list[float] = []
    facings: list[np.ndarray] = []

    sole_parts = ("LeftFoot", "RightFoot")
    core = "UpperTorso" if "UpperTorso" in {p.name for p in rig.parts} else "Torso"

    for frame in frames:
        placed = place_rotations(
            rig, {part: track[frame] for part, track in clip.rotations.items()}
        )
        for part in sole_parts:
            if part not in placed:
                continue
            position, rotation = placed[part]
            half = rig.part(part).size[1] / 2.0
            soles.setdefault(part, []).append(
                position + rotation @ np.array([0.0, -half, 0.0])
            )
        if core not in placed:
            continue
        chest, chest_rotation = placed[core]
        facing = chest_rotation @ np.array([0.0, 0.0, -1.0])
        facings.append(facing)
        hands = [
            float((placed[hand][0] - chest) @ facing)
            for hand in ("LeftHand", "RightHand")
            if hand in placed
        ]
        reaches.append(max(hands) if hands else 0.0)

    if not facings:
        return None
    return _Posed(
        rate=clip.fps / MEASURE_STRIDE,
        height=_standing_height(rig),
        soles={part: np.array(values) for part, values in soles.items()},
        reaches=np.array(reaches),
        facings=np.array(facings),
    )


def _fill_posed(entry: Entry, posed: _Posed, lo: int = 0, hi: int | None = None) -> None:
    """Write the forward-kinematics measurements of ``posed[lo:hi]``."""
    hi = len(posed) if hi is None else hi
    if hi - lo < 2:
        return
    seconds = max((hi - lo - 1) / posed.rate, 1e-6)

    if posed.soles:
        # The ground reference is the *stance* level, not the lowest point the
        # clip ever reaches. Taking the minimum over a forty-second take puts
        # the floor under a crouch, after which both feet read as airborne for
        # the whole clip and every take is a jump. The median of the per-frame
        # lower sole is where the character actually stands. It is taken over
        # the whole take even when measuring a window, for the same reason: a
        # window is not entitled to its own idea of where the floor is.
        lower = np.minimum.reduce([values[:, 1] for values in posed.soles.values()])
        stance = float(np.median(lower))
        lift = 0.07 * posed.height  # studs a sole must clear to be off the floor

        steps = 0
        speeds = []
        for values in posed.soles.values():
            span = values[lo:hi]
            speeds.append(
                float(np.linalg.norm(np.diff(span, axis=0), axis=1).mean() * posed.rate)
            )
            steps += len(_touchdowns(span[:, 1] - stance, plant=lift, clearance=lift))

        entry.steps_per_second = round(steps / seconds, 3)
        entry.foot_speed = round(float(np.mean(speeds)), 3)

    span = posed.reaches[lo:hi]
    if len(span):
        entry.reach = round(float(span.max()) / posed.height, 3)
    facings = posed.facings[lo:hi]
    if len(facings) > 1:
        cosine = float(np.clip(np.dot(facings[0], facings[-1]), -1.0, 1.0))
        entry.turn = round(float(np.degrees(math.acos(cosine))), 1)


def _measure(entry: Entry, clip) -> None:
    """What the clip actually does, from forward kinematics.

    Descriptions lie by omission: six CMU clips are all called "run" and they
    are not the same run. These numbers are what tells them apart, and what
    lets "cours lentement" avoid the fastest one.
    """
    posed = _posed_series(clip)
    if posed is not None:
        _fill_posed(entry, posed)


def _standing_height(rig) -> float:
    rest = place_rotations(rig, {})
    top = max(pos[1] + rig.part(name).size[1] / 2.0 for name, (pos, _) in rest.items())
    low = min(pos[1] - rig.part(name).size[1] / 2.0 for name, (pos, _) in rest.items())
    return float(max(top - low, 1.0))


def _touchdowns(height: np.ndarray, plant: float = 0.12, clearance: float = 0.12) -> list[int]:
    """Same gait test the sound spotter uses: the bottom of the sole's travel."""
    frames: list[int] = []
    peak = float(height[0]) if len(height) else 0.0
    for frame in range(1, len(height) - 1):
        peak = max(peak, float(height[frame]))
        low = height[frame] <= height[frame - 1] and height[frame] < height[frame + 1]
        if not low or height[frame] > plant or peak - float(height[frame]) < clearance:
            continue
        frames.append(frame)
        peak = float(height[frame])
    return frames


# -- descriptions -------------------------------------------------------------

#: ``09_02\trun, kick`` — the shape of CMU's index, and of anything sane.
_INDEX_LINE = re.compile(r"^\s*(?P<key>[\w.\-]+)\s*[\t:|]\s*(?P<text>\S.*?)\s*$")


def read_descriptions(path: str | Path) -> dict[str, str]:
    """Clip name to description, from a dataset's own index file.

    CMU ships ``cmu-mocap-index-text.txt``, which is what makes that database a
    text-to-motion corpus rather than 2548 anonymous files.
    """
    path = Path(path)
    out: dict[str, str] = {}
    for line in path.read_text(errors="replace").splitlines():
        match = _INDEX_LINE.match(line)
        if match and not line.lstrip().startswith("#"):
            out[match.group("key")] = match.group("text")
    if not out:
        raise LibraryError(
            f"{path} ne contient aucune ligne « nom<TAB>description ». "
            f"Attendu par exemple : 09_02\\trun"
        )
    return out


# -- searching ----------------------------------------------------------------

#: Prompt words that describe *how*, mapped onto measured properties rather
#: than onto description text. This is the half a keyword search cannot do.
FAST_WORDS = ("vite", "rapide", "rapidement", "fast", "quick", "sprint", "cours", "court", "run")
SLOW_WORDS = ("lent", "lentement", "doucement", "slow", "slowly", "calme", "tranquille")
BIG_WORDS = ("saut", "saute", "jump", "leap", "bond", "explosif", "violent", "puissant")
STILL_WORDS = ("immobile", "statique", "attend", "idle", "still", "stand", "wait", "repos")
REACH_WORDS = ("frappe", "coup", "poing", "punch", "attrape", "grab", "pousse", "push", "tend", "pointe", "point", "reach")
TURN_WORDS = ("tourne", "demi-tour", "turn", "pivot", "rotate", "spin")

#: Groups of words that mean the same motion, across French and English.
#:
#: This is the piece without which the whole idea fails in practice. Every
#: commercially usable library is labelled in English — CMU's index is 2435
#: lines of it — and the prompts are French. Without this, "marche" matches
#: none of the 506 clips described as "walk", and the search returns nothing
#: while sitting on exactly what was asked for.
#:
#: The first sixteen groups are the offline planner's own keyword sets, so the
#: two vocabularies cannot drift apart. The rest were read off the words that
#: actually occur in CMU's descriptions rather than invented.
EXTRA_SYNONYMS: tuple[tuple[str, ...], ...] = (
    ("grimpe", "grimper", "escalade", "climb", "climbing"),
    ("danse", "danser", "dance", "dancing", "salsa"),
    ("epee", "sabre", "sword", "swordplay", "fencing"),
    ("lave", "laver", "nettoie", "wash", "clean", "scrub"),
    ("coup de pied", "pied", "kick", "kicking"),
    ("tourne", "pivote", "demi-tour", "turn", "turning", "rotate", "spin"),
    ("balance", "balancer", "swing", "swinging"),
    ("ramasse", "ramasser", "prend", "pick", "pickup", "scoop", "grab"),
    ("porte", "porter", "souleve", "carry", "lift", "lifting"),
    ("pousse", "pousser", "push", "shove"),
    ("tire", "tirer", "pull", "drag"),
    ("lance", "lancer", "jette", "throw", "toss", "pitch"),
    ("attrape", "attraper", "catch", "catching"),
    ("rampe", "ramper", "crawl", "crawling"),
    ("boite", "boxe", "box", "boxing", "punching"),
    ("nage", "nager", "swim", "swimming"),
    ("monte", "monter", "gravit", "up", "upstairs", "ascend"),
    ("descend", "descendre", "down", "downstairs", "descend"),
    ("cote", "lateral", "sideways", "sidestep", "side"),
    ("arriere", "recule", "reculer", "backward", "backwards", "back", "retreat"),
    ("avant", "devant", "forward", "ahead"),
    ("trebuche", "titube", "stumble", "trip", "stagger"),
    ("tombe", "tomber", "chute", "fall", "falling", "collapse"),
    ("leve", "lever", "debout", "stand", "standing", "rise", "get up"),
    ("bras", "arm", "arms"),
    ("main", "hand", "hands"),
    ("jambe", "leg", "legs"),
    ("tete", "head"),
    ("basket", "basketball", "ball", "dribble"),
    ("football", "soccer"),
    ("terrain", "sol", "ground", "terrain", "floor"),
    ("obstacle", "boite", "box", "obstacle"),
    ("escaliers", "marches", "stairs", "steps"),
    ("etire", "etirer", "stretch", "stretching"),
    ("assis", "chaise", "tabouret", "sit", "sitting", "stool", "chair"),
    ("boit", "boire", "drink", "drinking"),
    ("mange", "manger", "eat", "eating"),
    ("salue", "salut", "wave", "waving", "greet"),
    ("regarde", "look", "looking", "watch"),
    ("court", "cours", "courir", "run", "running", "jog", "jogging", "sprint"),
    ("marche", "marcher", "walk", "walking", "stroll", "step"),
    ("saute", "sauter", "jump", "jumping", "hop", "leap", "bound"),
)

#: Words too common to carry meaning in a motion library.
STOPWORDS = frozenset({
    "de", "du", "des", "le", "la", "les", "un", "une", "et", "au", "aux",
    "en", "il", "elle", "se", "sa", "son", "ses", "dans", "sur", "avec",
    "pour", "par", "the", "an", "and", "of", "to", "in", "on", "with",
    "his", "her", "he", "she", "it", "then", "puis", "ensuite",
})

#: How much of the final score the measured shape may swing. The text match
#: is the base; this only re-ranks clips that already matched the words.
SHAPE_WEIGHT = 0.6


def _tokens(text: str) -> list[str]:
    return [
        word
        for word in re.findall(r"[a-z0-9]+", normalize(text))
        if len(word) > 1 and word not in STOPWORDS
    ]


def _terms(entry: Entry) -> list[str]:
    """What the search matches against: the description plus the file's name."""
    words = _tokens(f"{entry.description} {_readable(entry.name)}")
    seen: list[str] = []
    for word in words:
        if word not in seen:
            seen.append(word)
    return seen


def _synonym_index() -> dict[str, frozenset[str]]:
    """Word to every word that means the same motion."""
    from .generate.offline import ACTIONS

    groups = [tuple(_tokens(" ".join(action.keywords))) for action in ACTIONS]
    groups += [tuple(_tokens(" ".join(group))) for group in EXTRA_SYNONYMS]

    index: dict[str, set[str]] = {}
    for group in groups:
        for word in group:
            index.setdefault(word, set()).update(group)
    return {word: frozenset(others) for word, others in index.items()}


SYNONYMS = _synonym_index()

#: A synonym hit counts for less than the word the library actually uses, so
#: an exact match still wins when both are present.
SYNONYM_WEIGHT = 0.8

#: A prefix hit ("danse" against "dancing") counts for less again.
PREFIX_WEIGHT = 0.35

#: Terms a description may carry before length normalisation starts biting.
#: Around the length of a focused label: "run", "jump, balance", "punch/strike".
LENGTH_PIVOT = 4


def search(library: Library, prompt: str, *, limit: int = 5) -> list[tuple[float, Entry]]:
    """Score every entry against ``prompt`` and return the best."""
    wanted = _tokens(prompt)
    if not wanted:
        return []

    # Inverse document frequency, so "walk" in a library of walks counts for
    # less than "cartwheel". Without it a generic word drowns a specific one.
    total = max(len(library.entries), 1)
    document_count: dict[str, int] = {}
    for entry in library.entries:
        for term in set(entry.terms):
            document_count[term] = document_count.get(term, 0) + 1

    def weight(term: str) -> float:
        return math.log(1 + total / (1 + document_count.get(term, 0)))

    shape = _shape_target(prompt)
    scored: list[tuple[float, Entry]] = []
    for entry in library.entries:
        terms = set(entry.terms)
        text = 0.0
        for word in wanted:
            if word in terms:
                text += weight(word)
                continue
            alternates = SYNONYMS.get(word, frozenset()) & terms
            if alternates:
                text += SYNONYM_WEIGHT * max(weight(term) for term in alternates)
                continue
            if len(word) >= 4:
                text += PREFIX_WEIGHT * max(
                    (weight(term) for term in terms if term.startswith(word[:4])),
                    default=0.0,
                )
        text /= len(wanted)
        # Length normalisation, as retrieval has done since BM25: a clip
        # described in twenty words that mentions a jump once is a worse answer
        # than one described as "jump, balance". Without this, CMU's long
        # playground takes beat every focused clip they happen to contain.
        text *= LENGTH_PIVOT / (LENGTH_PIVOT + max(len(terms) - LENGTH_PIVOT, 0))

        # Shape modulates the text score; it never replaces it. Added instead,
        # a prompt whose words match nothing still ranked every clip in the
        # library by its adverbs alone — "coup de poing" came back with
        # playground climbs, confidently.
        if text <= 0:
            continue
        score = text * (1.0 - SHAPE_WEIGHT + SHAPE_WEIGHT * _shape_score(entry, shape))
        scored.append((round(score, 4), entry))

    scored.sort(key=lambda pair: (-pair[0], pair[1].name))
    return scored[:limit]


#: Hip heights per second. Measured across CMU: standing work sits under 0.3,
#: a walk lands near 1.4, a jog near 3.0, a sprint near 4.0. Those are the same
#: numbers biomechanics gives for a 0.9 m hip — 1.3 m/s walking, 3.5 m/s
#: running — which is the check that says this is measuring the right thing.
WALKING_PACE = 1.4
RUNNING_PACE = 3.0
STANDING_PACE = 0.35


@dataclass
class _Shape:
    """What the adverbs in a prompt ask of the motion itself."""

    #: Preferred ground speed, in hip heights per second.
    pace: float | None = None
    reach: float | None = None
    airborne: bool | None = None
    turn: bool | None = None


def _shape_target(prompt: str) -> _Shape:
    words = set(_tokens(prompt))
    shape = _Shape()

    if words & set(FAST_WORDS):
        shape.pace = RUNNING_PACE
    if words & set(SLOW_WORDS):
        shape.pace = WALKING_PACE * 0.7
    if words & set(STILL_WORDS):
        shape.pace = 0.0
    if words & set(BIG_WORDS):
        shape.airborne = True
    if words & set(REACH_WORDS):
        shape.reach = 0.25
    if words & set(TURN_WORDS):
        shape.turn = True
    return shape


def _shape_score(entry: Entry, shape: _Shape) -> float:
    """0..1, how well a clip's measurements answer the prompt's adverbs."""
    checks: list[float] = []
    if shape.pace is not None:
        # Judged on a log scale: the gap between standing and walking matters
        # as much as the gap between walking and sprinting, and it is a much
        # smaller number.
        wanted = math.log1p(max(shape.pace, 0.0) / STANDING_PACE)
        got = math.log1p(max(entry.travel, 0.0) / STANDING_PACE)
        checks.append(float(np.clip(1.0 - abs(wanted - got) / 1.6, 0.0, 1.0)))
    if shape.airborne is not None:
        checks.append(1.0 if entry.airborne == shape.airborne else 0.0)
    if shape.reach is not None:
        checks.append(float(np.clip(entry.reach / max(shape.reach, 1e-6), 0.0, 1.0)))
    if shape.turn is not None:
        checks.append(float(np.clip(entry.turn / 90.0, 0.0, 1.0)))
    return float(np.mean(checks)) if checks else 0.0


#: How far apart candidate windows start, in seconds. Fine enough to land on
#: the right beat of a take, coarse enough that a forty-second capture is a
#: few hundred candidates rather than a few thousand.
WINDOW_STEP = 0.25

#: Weight of the prompt's adverbs against plain activity when placing a
#: window. Activity never disappears entirely: a stretch that matches the
#: adverbs while the actor stands around resetting between takes is not the
#: answer to anything.
WINDOW_SHAPE_WEIGHT = 0.7

#: Weight of the join against everything else, when the window has something
#: to follow. Placing a window purely on content picks the right beat and then
#: enters it mid-stride: measured on CMU, choosing the walk window with no
#: regard for what preceded it turned a 3.5 deg/frame seam into 35. The join
#: has to be part of the choice, not a repair applied afterwards.
WINDOW_JOIN_WEIGHT = 0.4


def best_window(
    clip,
    track,
    prompt: str,
    seconds: float,
    *,
    follows: dict | None = None,
) -> tuple[int, int]:
    """Which stretch of a long take answers ``prompt``. Frame indices, half-open.

    A CMU take runs twenty to forty seconds and contains several actions, plus
    the actor walking into place at the top and standing around at the end.
    Handing back the opening — which is what a plain trim does — reliably
    returns the least interesting part of the file, and for a take that opens
    on a calibration pose it returns nothing at all.

    So every candidate window is measured with the same code that measured the
    whole take, and scored the same way search scores a clip: how well its
    numbers answer the adverbs in the prompt. When the prompt carries no
    adverbs there is nothing to match, and the fallback is simply the busiest
    stretch — which still beats the opening.

    ``follows`` is the pose this window will be joined onto, when it is not the
    first in a sequence. Two windows can answer a prompt equally well and be
    worlds apart as a continuation of what came before, so where it is known,
    it counts.
    """
    frames = clip.frame_count
    want = max(round(seconds * clip.fps) + 1, 2)
    if want >= frames:
        return 0, frames

    posed = _posed_series(clip)
    world = _world_series(track)
    if posed is None:
        return 0, want

    shape = _shape_target(prompt)
    has_shape = any(
        getattr(shape, field_name) is not None
        for field_name in ("pace", "reach", "airborne", "turn")
    )

    step = max(round(WINDOW_STEP * clip.fps), 1)
    starts = list(range(0, frames - want + 1, step))

    joins = _join_quality(clip, starts, follows)

    scored: list[tuple[float, float, float, int]] = []
    for index, start in enumerate(starts):
        probe = Entry(path="", name="", description="", duration=seconds,
                      fps=clip.fps, frames=want)
        _fill_posed(probe, posed, start // MEASURE_STRIDE, (start + want) // MEASURE_STRIDE)
        if world is not None:
            _fill_world(probe, world, start, start + want)
        scored.append(
            (
                _shape_score(probe, shape) if has_shape else 0.0,
                probe.foot_speed,
                joins[index],
                start,
            )
        )

    busiest = max((activity for _, activity, _, _ in scored), default=0.0) or 1.0

    def rank(candidate: tuple[float, float, float, int]) -> float:
        shape_score, activity, join, _ = candidate
        normalised = min(activity / busiest, 1.0)
        content = (
            WINDOW_SHAPE_WEIGHT * shape_score + (1.0 - WINDOW_SHAPE_WEIGHT) * normalised
            if has_shape
            else normalised
        )
        if not follows:
            return content
        return (1.0 - WINDOW_JOIN_WEIGHT) * content + WINDOW_JOIN_WEIGHT * join

    start = max(scored, key=rank)[3]
    return start, start + want


def _join_quality(clip, starts: list[int], follows: dict | None) -> list[float]:
    """0..1 per candidate start: how well it continues the pose before it.

    Relative rather than absolute — the best available start scores 1 and the
    worst 0 — because what matters is which of *these* windows joins best, not
    how the number compares against some other take.
    """
    if not follows:
        return [0.0] * len(starts)

    from .transitions import pose_distance

    distances = [
        pose_distance(follows, {part: track[start] for part, track in clip.rotations.items()})
        for start in starts
    ]
    worst, best = max(distances), min(distances)
    if worst - best < 1e-9:
        return [1.0] * len(starts)
    return [float((worst - value) / (worst - best)) for value in distances]


def describe(entry: Entry) -> str:
    """One line for the search results, saying what was measured."""
    bits = [f"{entry.duration:.1f}s"]
    if entry.steps_per_second:
        bits.append(f"{entry.steps_per_second:.1f} pas/s")
    if entry.foot_speed:
        bits.append(f"pieds {entry.foot_speed:.0f} studs/s")
    if entry.airborne:
        bits.append("décolle")
    if entry.turn >= 45:
        bits.append(f"tourne {entry.turn:.0f}°")
    if entry.reach >= 0.3:
        bits.append(f"allonge {entry.reach:.2f}")
    return ", ".join(bits)
