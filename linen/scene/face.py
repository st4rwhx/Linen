"""Faces, generated rather than captured.

Studio can turn a webcam into facial keyframes, and for someone acting their
own scene that is the best tool there is. It is the wrong tool here: it puts a
person back in the loop for every beat, and the point of this pipeline is that
the scene is written and comes out finished.

So the face is built from what the scene already says. An expression is a set
of FACS poses with weights, eased in and out rather than switched on. A spoken
line drives the jaw and lips from its own text, syllable by syllable. And
underneath both, a face that never blinks reads as a corpse, so it blinks.

Everything here targets `FaceControls`, which is a documented class with fifty
named properties between 0 and 1. It is driven per frame from the scene's
client script — not written into the animation file, because how a
`KeyframeSequence` stores facial tracks is not documented anywhere this could
be checked against, and guessing a file format is how you ship something that
imports and does nothing.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

#: Roblox's FACS poses, verbatim from the avatar reference. The seventeen a
#: head must have to be published are marked, because a scene that only uses
#: those works on every dynamic head in the catalogue.
REQUIRED: frozenset[str] = frozenset(
    {
        "LeftEyeClosed", "RightEyeClosed", "EyesLookDown",
        "JawDrop", "Pucker", "LeftLipCornerPuller", "RightLipCornerPuller",
        "ChinRaiser", "ChinRaiserUpperLip",
        "LeftLowerLipDepressor", "RightLowerLipDepressor",
        "LeftCheekRaiser", "RightCheekRaiser",
        "LeftInnerBrowRaiser", "RightInnerBrowRaiser",
        "LeftLipCornerDown", "RightLipCornerDown",
    }
)

OPTIONAL: frozenset[str] = frozenset(
    {
        "EyesLookLeft", "EyesLookRight", "EyesLookUp",
        "LeftEyeUpperLidRaiser", "RightEyeUpperLidRaiser",
        "LeftLipStretcher", "RightLipStretcher",
        "LeftUpperLipRaiser", "RightUpperLipRaiser",
        "LipsTogether", "FlatPucker", "Funneler", "LowerLipSuck", "UpperLipSuck",
        "LipPresser", "MouthLeft", "MouthRight",
        "LeftCheekPuff", "RightCheekPuff", "LeftDimpler", "RightDimpler",
        "JawLeft", "JawRight",
        "Corrugator", "LeftBrowLowerer", "RightBrowLowerer",
        "LeftOuterBrowRaiser", "RightOuterBrowRaiser",
        "LeftNoseWrinkler", "RightNoseWrinkler",
        "TongueDown", "TongueOut", "TongueUp",
    }
)

CONTROLS: frozenset[str] = REQUIRED | OPTIONAL

#: What each named expression is, in FACS. Built from the required seventeen
#: wherever the shape allows, so an expression works on any published head;
#: where a feeling genuinely needs a brow lowerer, it says so and degrades to
#: nothing on a head that lacks one rather than looking wrong.
EXPRESSIONS: dict[str, dict[str, float]] = {
    "neutral": {},
    "smug": {
        "LeftLipCornerPuller": 0.55, "RightLipCornerPuller": 0.15,
        "LeftDimpler": 0.4, "LeftEyeUpperLidRaiser": 0.15,
        "RightBrowLowerer": 0.25,
    },
    "angry": {
        "Corrugator": 0.8, "LeftBrowLowerer": 0.75, "RightBrowLowerer": 0.75,
        "LeftNoseWrinkler": 0.4, "RightNoseWrinkler": 0.4,
        "LipPresser": 0.6, "JawDrop": 0.15,
        "LeftEyeUpperLidRaiser": 0.35, "RightEyeUpperLidRaiser": 0.35,
    },
    "afraid": {
        "LeftInnerBrowRaiser": 0.85, "RightInnerBrowRaiser": 0.85,
        "LeftOuterBrowRaiser": 0.5, "RightOuterBrowRaiser": 0.5,
        "LeftEyeUpperLidRaiser": 0.7, "RightEyeUpperLidRaiser": 0.7,
        "JawDrop": 0.35, "LeftLipStretcher": 0.5, "RightLipStretcher": 0.5,
    },
    "surprised": {
        "LeftInnerBrowRaiser": 0.9, "RightInnerBrowRaiser": 0.9,
        "LeftOuterBrowRaiser": 0.8, "RightOuterBrowRaiser": 0.8,
        "LeftEyeUpperLidRaiser": 0.8, "RightEyeUpperLidRaiser": 0.8,
        "JawDrop": 0.6,
    },
    "pain": {
        "LeftEyeClosed": 0.8, "RightEyeClosed": 0.8,
        "Corrugator": 0.7, "LeftNoseWrinkler": 0.6, "RightNoseWrinkler": 0.6,
        "LeftLipStretcher": 0.7, "RightLipStretcher": 0.7,
        "ChinRaiser": 0.4, "JawDrop": 0.3,
    },
    "determined": {
        "LeftBrowLowerer": 0.5, "RightBrowLowerer": 0.5,
        "LipPresser": 0.7, "ChinRaiser": 0.35,
        "LeftEyeUpperLidRaiser": 0.2, "RightEyeUpperLidRaiser": 0.2,
    },
    "laughing": {
        "LeftLipCornerPuller": 0.9, "RightLipCornerPuller": 0.9,
        "LeftCheekRaiser": 0.8, "RightCheekRaiser": 0.8,
        "LeftEyeClosed": 0.5, "RightEyeClosed": 0.5, "JawDrop": 0.45,
    },
    "sad": {
        "LeftInnerBrowRaiser": 0.7, "RightInnerBrowRaiser": 0.7,
        "LeftLipCornerDown": 0.7, "RightLipCornerDown": 0.7,
        "ChinRaiser": 0.3, "EyesLookDown": 0.4,
    },
}

#: Mouth shapes for speech. Not phonemes — six visemes is what animation has
#: used since Disney, because at twenty-four frames a second nobody sees more.
VISEMES: dict[str, dict[str, float]] = {
    # open: a, â
    "A": {"JawDrop": 0.65, "LeftLowerLipDepressor": 0.3, "RightLowerLipDepressor": 0.3},
    # wide: i, é, è
    "E": {"JawDrop": 0.2, "LeftLipStretcher": 0.6, "RightLipStretcher": 0.6},
    # rounded: o, u, ou
    "O": {"JawDrop": 0.4, "Pucker": 0.7, "Funneler": 0.4},
    # closed: p, b, m
    "M": {"LipsTogether": 0.9, "LipPresser": 0.5},
    # teeth: f, v
    "F": {"UpperLipSuck": 0.4, "LowerLipSuck": 0.5, "JawDrop": 0.12},
    # neutral consonant
    "C": {"JawDrop": 0.22, "LeftLipStretcher": 0.2, "RightLipStretcher": 0.2},
}

_VOWELS = {
    "a": "A", "à": "A", "â": "A",
    "e": "E", "é": "E", "è": "E", "ê": "E", "i": "E", "î": "E", "y": "E",
    "o": "O", "ô": "O", "u": "O", "û": "O", "ù": "O",
}
_CLOSED = set("pbm")
_TEETH = set("fv")

#: Seconds a mouth shape is held. Faster than this and the jaw buzzes; slower
#: and the character mumbles behind its own line.
SYLLABLE_SECONDS = 0.11

#: A face that never blinks reads as a corpse. Roughly every four seconds,
#: offset per actor so a cast does not blink in unison.
BLINK_EVERY = 4.0
BLINK_SECONDS = 0.12


@dataclass
class Key:
    """One FACS control at one instant."""

    at: float
    control: str
    value: float


@dataclass
class FaceTrack:
    """Everything one actor's face does, as keys to be eased between."""

    actor: str
    keys: list[Key] = field(default_factory=list)

    def add(self, at: float, poses: dict[str, float], *, ease: float = 0.12) -> None:
        """Move to `poses` over `ease` seconds, and hold there.

        Every control the previous expression used but this one does not is
        driven back to zero, otherwise a raised brow from three beats ago is
        still raised under a smile.
        """
        held = {key.control for key in self.keys}
        for control in sorted(held | set(poses)):
            value = float(poses.get(control, 0.0))
            self.keys.append(Key(max(at - ease, 0.0), control, _last(self.keys, control, at)))
            self.keys.append(Key(at, control, value))

    def controls(self) -> set[str]:
        return {key.control for key in self.keys}


def _last(keys: list[Key], control: str, before: float) -> float:
    value = 0.0
    for key in keys:
        if key.control == control and key.at <= before:
            value = key.value
    return value


def visemes(text: str) -> list[str]:
    """A line of dialogue as a run of mouth shapes.

    Derived from the letters rather than from audio: the audio does not exist
    yet when the scene is built, and `AudioTextToSpeech` will read the same
    text. Approximate on purpose — a mouth that opens on vowels and closes on
    m/b/p is the whole of what reads on screen.
    """
    shapes: list[str] = []
    for word in re.findall(r"[^\W\d_]+", text.lower(), flags=re.UNICODE):
        letters = list(word)
        while letters:
            letter = letters.pop(0)
            if letter in _VOWELS:
                shapes.append(_VOWELS[letter])
                # A run of vowels is one shape held, not three flutters.
                while letters and letters[0] in _VOWELS:
                    letters.pop(0)
            elif letter in _CLOSED:
                shapes.append("M")
            elif letter in _TEETH:
                shapes.append("F")
            else:
                shapes.append("C")
        shapes.append("M")  # the mouth closes between words
    return shapes


def speak(track: FaceTrack, at: float, text: str) -> float:
    """Drive the mouth through a line. Returns when it finishes."""
    when = at
    for shape in visemes(text):
        track.add(when, VISEMES[shape], ease=SYLLABLE_SECONDS * 0.6)
        when += SYLLABLE_SECONDS
    track.add(when, {}, ease=0.15)
    return when


def blinks(duration: float, offset: float) -> list[tuple[float, dict[str, float]]]:
    """When to blink over a scene, staggered so a cast does not blink together."""
    out = []
    when = offset % BLINK_EVERY
    while when < duration:
        out.append((when, {"LeftEyeClosed": 1.0, "RightEyeClosed": 1.0}))
        out.append((when + BLINK_SECONDS, {}))
        when += BLINK_EVERY
    return out


def build_faces(scene, schedule, duration: float) -> dict[str, FaceTrack]:
    """Every actor's facial performance, from what the scene already says.

    Expressions come from `face` events, mouths from `line` events, and blinks
    from the fact that faces blink. Nothing here is captured and nothing needs
    a person: a written scene comes out with a performance on it.
    """
    starts = {entry.cue.id: entry.start for entry in schedule}
    tracks: dict[str, FaceTrack] = {}

    def track_for(actor: str) -> FaceTrack:
        return tracks.setdefault(actor, FaceTrack(actor=actor))

    timed = sorted(
        (
            (starts[event.cue] + event.offset, event)
            for event in scene.events
            if event.kind in ("face", "line") and event.actor
        ),
        key=lambda pair: pair[0],
    )
    for when, event in timed:
        track = track_for(event.actor)
        if event.kind == "face":
            track.add(when, EXPRESSIONS.get(event.expression or "neutral", {}))
        else:
            speak(track, when, event.text or "")

    # Blinks last, so an expression that closes the eyes is not fought over by
    # a blink landing on the same frame.
    for index, actor in enumerate(scene.actors):
        track = track_for(actor.name)
        for when, poses in blinks(duration, index * 1.3):
            if not any(abs(key.at - when) < 0.2 for key in track.keys if "EyeClosed" in key.control):
                track.add(when, {**_held(track, when), **poses}, ease=0.05)
    return {name: track for name, track in tracks.items() if track.keys}


def _held(track: FaceTrack, when: float) -> dict[str, float]:
    """What the face is already doing, so a blink adds to it instead of
    replacing it."""
    return {
        control: _last(track.keys, control, when)
        for control in track.controls()
        if "EyeClosed" not in control
    }
