"""A 3D viewer for a clip or a whole scene, as one self-contained HTML file.

Everything else in this project is checked by asking whether the numbers agree
with each other. This asks the only question that finally settles it: *does it
look like the thing it claims to be*. Until you can watch a take, every layer
added on top is unverified work stacked on unverified work.

It is one file with the data baked into it. No server, no build step, no
network — double-click and it plays, which matters because the alternative
is a thing you never actually open.

The renderer is deliberately small: a Roblox character *is* a stack of boxes,
so drawing it is projecting eight corners per part and filling the faces back
to front. That is the same painter's algorithm ``tools/render_frames.py``
already uses for contact sheets, and it needs no library, which is what keeps
the page self-contained.

Two things it shows that a plain animation preview cannot:

**The director's camera.** A scene's shots are real camera setups with a
position, a subject and a field of view. Playing the take through them is the
framing you will get in Studio, so a cut that lands on the back of someone's
head is visible here rather than after an import.

**The soundtrack, on the timeline.** Every spotted impact, footstep and line is
a tick under the scrub bar, with the tension curve behind it. You can see the
punch land on the frame the fist stops.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np

from ..clip import AnimationClip
from ..rigs import get_rig
from .preview import rig_to_dict


def standing_height(rig) -> float:
    """How far a rig's root sits above the ground when standing, in studs.

    A Roblox character's position is its *root*, at hip height. Drawing a clip
    with the root on the grid buries the legs, which looks like a bug in the
    animation rather than in the viewer.
    """
    from ..rigs.kinematics import place_rotations

    rest = place_rotations(rig, {})
    return float(
        -min(pos[1] - rig.part(name).size[1] / 2.0 for name, (pos, _) in rest.items())
    )


def clip_payload(
    clip: AnimationClip, *, name: str | None = None, skins: list[dict] | None = None
) -> dict[str, Any]:
    """One clip, viewable on its own."""
    return {
        "skins": skins or [],
        "name": name or clip.name or "Clip",
        "fps": clip.fps,
        "duration": (clip.frame_count - 1) / clip.fps if clip.fps else 0.0,
        "frameCount": clip.frame_count,
        "rigs": {clip.rig.name: rig_to_dict(clip.rig)},
        "actors": [
            {
                "name": name or clip.name or "Clip",
                "rig": clip.rig.name,
                # Stood on the grid rather than sunk through it: the root is at
                # hip height, exactly as Studio will place the character.
                "position": [0.0, standing_height(clip.rig), 0.0],
                "yaw": 0.0,
                "rotations": _rotations(clip),
                "root": None
                if clip.root_positions is None
                else [round(float(v), 4) for v in np.asarray(clip.root_positions).reshape(-1)],
            }
        ],
        "set": [],
        "shots": [],
        "cues": [],
        "events": [],
        "tension": [],
    }


def scene_payload(
    built, *, sheet=None, set_plan=None, skins: list[dict] | None = None
) -> dict[str, Any]:
    """A whole cinematic: cast, staging, set, shots, cues and soundtrack."""
    scene = built.scene
    rigs = {}
    actors = []

    for actor in scene.actors:
        clip = built.clips.get(actor.name)
        if clip is None:
            continue
        rig = get_rig(actor.rig)
        rigs.setdefault(rig.name, rig_to_dict(rig))
        actors.append(
            {
                "name": actor.name,
                "rig": rig.name,
                "position": [float(v) for v in actor.position],
                "yaw": _yaw_degrees(scene, actor),
                "rotations": _rotations(clip),
                "root": None,
            }
        )

    return {
        "skins": skins or [],
        "name": scene.name,
        "fps": scene.fps,
        "duration": built.duration,
        "frameCount": max((c.frame_count for c in built.clips.values()), default=1),
        "rigs": rigs,
        "actors": actors,
        "set": _set_pieces(set_plan),
        "shots": [
            {
                "id": shot.id,
                "position": [float(v) for v in shot.position],
                "lookAt": shot.look_at,
                "fov": shot.fov,
                "blend": shot.blend,
                "drift": [float(v) for v in shot.drift],
            }
            for shot in scene.shots
        ],
        "cues": [
            {
                "id": entry.cue.id,
                "actor": entry.cue.actor,
                "start": round(entry.start, 4),
                "stop": round(entry.end, 4),
                "what": (entry.cue.prompt or entry.plan.name)[:60],
            }
            for entry in built.schedule
        ],
        "events": _events(built, sheet),
        "tension": [[round(t, 3), v] for t, v in (sheet.tension if sheet else [])],
    }


def _rotations(clip: AnimationClip) -> dict[str, list[float]]:
    """Flat xyzw per part, frame-major — the form the page indexes directly."""
    return {
        part: [round(float(v), 5) for v in track.reshape(-1)]
        for part, track in clip.rotations.items()
    }


def _yaw_degrees(scene, actor) -> float:
    """The heading the Studio script will give this actor, in degrees.

    Kept in step with the player's staging on purpose: a viewer that faces
    people differently from the runtime shows a scene nobody will ever get.
    """
    if isinstance(actor.facing, (int, float)):
        return float(actor.facing)
    if isinstance(actor.facing, str):
        other = next((a for a in scene.actors if a.name == actor.facing), None)
        if other is not None:
            dx = other.position[0] - actor.position[0]
            dz = other.position[2] - actor.position[2]
            if abs(dx) > 1e-6 or abs(dz) > 1e-6:
                return float(np.degrees(np.arctan2(dx, -dz)))
    return 0.0


def _set_pieces(set_plan) -> list[dict[str, Any]]:
    if set_plan is None:
        return []
    return [
        {
            "name": p.name,
            "kind": p.kind,
            "position": [float(v) for v in p.position],
            "size": [float(v) for v in p.size],
            "reason": p.reason,
        }
        for p in set_plan.placements
    ]


#: How each event kind is drawn on the timeline. Sound is split out from the
#: authored kinds because there are far more of them and they read as texture.
LANES: dict[str, str] = {
    "camera": "#e8b84b",
    "line": "#7fd1e8",
    "face": "#c99ae8",
    "prop": "#8fd98f",
    "vfx": "#e88f6a",
    "sound": "#9aa4b2",
    "spot": "#9aa4b2",
    # Contact is solved into the animation rather than fired at playback, so it
    # is the one lane where the marker shows where a correction was made rather
    # than where something happens.
    "contact": "#e86a8f",
}


def _events(built, sheet) -> list[dict[str, Any]]:
    """Everything that fires, authored or spotted, on one timeline."""
    events: list[dict[str, Any]] = []
    starts = {entry.cue.id: entry.start for entry in built.schedule}

    for event in built.scene.events:
        when = starts[event.cue] + event.offset
        events.append(
            {
                "t": round(when, 4),
                "kind": event.kind,
                "actor": event.actor,
                "label": _label(event),
            }
        )

    for slot in sheet.slots if sheet else []:
        for hit in slot.hits:
            events.append(
                {
                    "t": round(hit.time, 4),
                    "kind": "spot",
                    "actor": hit.actor,
                    "label": f"{slot.name} ({hit.intensity:.2f})",
                    "why": hit.why,
                }
            )

    events.sort(key=lambda e: e["t"])
    return events


def _label(event) -> str:
    if event.kind == "camera":
        return f"plan {event.shot}"
    if event.kind == "line":
        return f"« {(event.text or '')[:38]} »"
    if event.kind == "face":
        return str(event.expression)
    if event.kind == "prop":
        return f"{event.prop} {event.action}"
    if event.kind == "vfx":
        return f"{event.effect} sur {event.at_part or 'la scène'}"
    return str(event.asset or event.kind)


def viewer_html(payload: dict[str, Any]) -> str:
    """The page, with ``payload`` baked in."""
    data = json.dumps(payload, separators=(",", ":"), ensure_ascii=False)
    return (
        _PAGE.replace("__TITLE__", _escape(payload.get("name", "Linen")))
        .replace("__LANES__", json.dumps(LANES))
        # A literal </script> inside the payload would end the block early.
        .replace("__DATA__", data.replace("</", "<\\/"))
    )


def write_viewer(payload: dict[str, Any], path: str | Path) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(viewer_html(payload), encoding="utf-8")
    return path


def _escape(text: str) -> str:
    return (
        text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    )


_PAGE = r"""<!doctype html>
<html lang="fr">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>__TITLE__ — Linen</title>
<style>
  :root {
    --bg: #14161a; --panel: #1c1f25; --line: #2a2f37;
    --ink: #e6e9ee; --dim: #8b93a1; --accent: #6ea8fe;
  }
  * { box-sizing: border-box; }
  html, body { height: 100%; margin: 0; }
  body {
    background: var(--bg); color: var(--ink);
    font: 13px/1.5 ui-sans-serif, system-ui, -apple-system, "Segoe UI", sans-serif;
    display: flex; flex-direction: column; overflow: hidden;
  }
  header {
    display: flex; align-items: baseline; gap: 12px;
    padding: 10px 14px; border-bottom: 1px solid var(--line);
  }
  header h1 { font-size: 14px; margin: 0; font-weight: 600; }
  header .meta { color: var(--dim); font-size: 12px; }
  main { flex: 1; position: relative; min-height: 0; }
  canvas#stage { display: block; width: 100%; height: 100%; cursor: grab; }
  canvas#stage:active { cursor: grabbing; }
  #hud {
    position: absolute; top: 10px; left: 12px; pointer-events: none;
    font-variant-numeric: tabular-nums; color: var(--dim); font-size: 12px;
  }
  #fired {
    position: absolute; top: 10px; right: 12px; pointer-events: none;
    text-align: right; font-size: 12px; max-width: 40%;
  }
  #fired div { opacity: 0.9; }
  #legend {
    position: absolute; bottom: 10px; left: 12px; pointer-events: none;
    color: var(--dim); font-size: 11px;
  }
  footer { border-top: 1px solid var(--line); background: var(--panel); }
  .bar { display: flex; align-items: center; gap: 10px; padding: 8px 14px; flex-wrap: wrap; }
  button, select {
    background: #262b33; color: var(--ink); border: 1px solid var(--line);
    border-radius: 6px; padding: 5px 10px; font: inherit; cursor: pointer;
  }
  button:hover, select:hover { border-color: #3d444f; }
  button.on { background: var(--accent); color: #0d1117; border-color: var(--accent); }
  label { color: var(--dim); display: inline-flex; align-items: center; gap: 6px; }
  #time { font-variant-numeric: tabular-nums; color: var(--dim); min-width: 128px; }
  canvas#timeline { display: block; width: 100%; height: 92px; cursor: pointer; }
  kbd {
    background: #262b33; border: 1px solid var(--line); border-bottom-width: 2px;
    border-radius: 4px; padding: 0 4px; font: 11px ui-monospace, monospace;
  }
</style>
</head>
<body>
<header>
  <h1>__TITLE__</h1>
  <span class="meta" id="summary"></span>
</header>

<main>
  <canvas id="stage"></canvas>
  <div id="hud"></div>
  <div id="fired"></div>
  <div id="legend">
    glisser : tourner &nbsp;·&nbsp; molette : zoom &nbsp;·&nbsp; maj+glisser : déplacer
    &nbsp;·&nbsp; <kbd>espace</kbd> lecture &nbsp;·&nbsp; <kbd>←</kbd><kbd>→</kbd> frame
  </div>
</main>

<footer>
  <canvas id="timeline"></canvas>
  <div class="bar">
    <button id="play">▶ Lecture</button>
    <button id="loop" class="on">↻ Boucle</button>
    <span id="time"></span>
    <label>vitesse
      <select id="speed">
        <option value="0.1">0,1×</option>
        <option value="0.25">0,25×</option>
        <option value="0.5">0,5×</option>
        <option value="1" selected>1×</option>
        <option value="2">2×</option>
      </select>
    </label>
    <label id="skinpick" hidden>rig
      <select id="skin"></select>
    </label>
    <button id="director">🎬 Caméra du réalisateur</button>
    <button id="showset" class="on">Décor</button>
    <button id="showgrid" class="on">Grille</button>
    <button id="front">Face</button>
    <button id="side">Profil</button>
    <button id="top">Dessus</button>
  </div>
</footer>

<script>
const DATA = __DATA__;

/* ---------------------------------------------------------------- maths -- */
const IDENT = [1,0,0, 0,1,0, 0,0,1];

function matMul(a, b) {
  const o = new Array(9);
  for (let r = 0; r < 3; r++) for (let c = 0; c < 3; c++) {
    o[r*3+c] = a[r*3]*b[c] + a[r*3+1]*b[3+c] + a[r*3+2]*b[6+c];
  }
  return o;
}
function matVec(m, v) {
  return [
    m[0]*v[0] + m[1]*v[1] + m[2]*v[2],
    m[3]*v[0] + m[4]*v[1] + m[5]*v[2],
    m[6]*v[0] + m[7]*v[1] + m[8]*v[2],
  ];
}
function add(a, b) { return [a[0]+b[0], a[1]+b[1], a[2]+b[2]]; }
function sub(a, b) { return [a[0]-b[0], a[1]-b[1], a[2]-b[2]]; }
function scale(a, k) { return [a[0]*k, a[1]*k, a[2]*k]; }
function dot(a, b) { return a[0]*b[0] + a[1]*b[1] + a[2]*b[2]; }
function cross(a, b) {
  return [a[1]*b[2]-a[2]*b[1], a[2]*b[0]-a[0]*b[2], a[0]*b[1]-a[1]*b[0]];
}
function norm(a) {
  const n = Math.hypot(a[0], a[1], a[2]) || 1;
  return [a[0]/n, a[1]/n, a[2]/n];
}
// Quaternion xyzw to a rotation matrix, matching linen.math3d.quat_to_mat.
function quatToMat(x, y, z, w) {
  const xx = x*x, yy = y*y, zz = z*z;
  const xy = x*y, xz = x*z, yz = y*z, wx = w*x, wy = w*y, wz = w*z;
  return [
    1-2*(yy+zz),   2*(xy-wz),   2*(xz+wy),
      2*(xy+wz), 1-2*(xx+zz),   2*(yz-wx),
      2*(xz-wy),   2*(yz+wx), 1-2*(xx+yy),
  ];
}
function yawMat(deg) {
  const a = deg * Math.PI / 180, c = Math.cos(a), s = Math.sin(a);
  // Turns the rig's -Z forward onto the heading the Studio script gives it.
  return [c, 0, s, 0, 1, 0, -s, 0, c];
}

/* ------------------------------------------------- forward kinematics ---- */
// The same chain the exporter and the Studio player walk: a joint frame at the
// pivot that the pose rotates, then the part's centre offset inside it.
function poseAt(rig, actor, frame) {
  const placed = {};
  for (const part of rig.parts) {
    const track = actor.rotations[part.name];
    let local = IDENT;
    if (track) {
      const i = frame * 4;
      local = quatToMat(track[i], track[i+1], track[i+2], track[i+3]);
    }
    if (part.parent === null) {
      let root = [0, 0, 0];
      if (actor.root) root = [actor.root[frame*3], actor.root[frame*3+1], actor.root[frame*3+2]];
      placed[part.name] = { p: root, r: local };
      continue;
    }
    const parent = placed[part.parent];
    const joint = add(parent.p, matVec(parent.r, part.pivot));
    const r = matMul(parent.r, local);
    placed[part.name] = { p: add(joint, matVec(r, part.offsetFromPivot)), r: r };
  }
  return placed;
}

/* ------------------------------------------------------------ geometry -- */
const CORNERS = [
  [-.5,-.5,-.5], [.5,-.5,-.5], [.5,.5,-.5], [-.5,.5,-.5],
  [-.5,-.5,.5], [.5,-.5,.5], [.5,.5,.5], [-.5,.5,.5],
];
const FACES = [
  [0,1,2,3], [5,4,7,6], [4,0,3,7], [1,5,6,2], [3,2,6,7], [4,5,1,0],
];
const LIGHT = norm([0.4, 0.85, 0.45]);

const PALETTE = [
  [110, 168, 254], [232, 143, 106], [143, 217, 143],
  [201, 154, 232], [232, 184, 75], [127, 209, 232],
];

/* -------------------------------------------------------------- camera -- */
const cam = { yaw: 0.55, pitch: 0.22, dist: 16, target: [0, 3, -2], fov: 45 };

function orbitEye() {
  const cp = Math.cos(cam.pitch), sp = Math.sin(cam.pitch);
  return add(cam.target, [
    cam.dist * cp * Math.sin(cam.yaw),
    cam.dist * sp,
    cam.dist * cp * Math.cos(cam.yaw),
  ]);
}

function basis(eye, target) {
  const f = norm(sub(target, eye));
  let r = cross(f, [0, 1, 0]);
  if (Math.hypot(r[0], r[1], r[2]) < 1e-6) r = [1, 0, 0];
  r = norm(r);
  return { f: f, r: r, u: cross(r, f) };
}

/* --------------------------------------------------------------- state -- */
const stage = document.getElementById('stage');
const ctx = stage.getContext('2d');
const timeline = document.getElementById('timeline');
const tctx = timeline.getContext('2d');

const state = {
  time: 0, playing: false, loop: true, speed: 1,
  director: false, showSet: true, showGrid: true,
  //: Index into DATA.skins, or -1 for the plain boxes a Block Rig really is.
  skin: DATA.skins.length ? 0 : -1,
};
const frames = Math.max(DATA.frameCount, 1);
const duration = DATA.duration || (frames - 1) / (DATA.fps || 30);

document.getElementById('summary').textContent =
  `${DATA.actors.length} acteur(s) · ${duration.toFixed(2)} s · ${DATA.fps} fps` +
  (DATA.cues.length ? ` · ${DATA.cues.length} cues` : '') +
  (DATA.events.length ? ` · ${DATA.events.length} événements` : '');

// Frame the cast on load, so nothing opens off-screen.
(function frameCast() {
  if (!DATA.actors.length) return;
  let lo = [1e9, 1e9, 1e9], hi = [-1e9, -1e9, -1e9];
  for (const a of DATA.actors) for (let i = 0; i < 3; i++) {
    lo[i] = Math.min(lo[i], a.position[i]); hi[i] = Math.max(hi[i], a.position[i]);
  }
  cam.target = [(lo[0]+hi[0])/2, (lo[1]+hi[1])/2 + 1, (lo[2]+hi[2])/2];
  const span = Math.max(hi[0]-lo[0], hi[2]-lo[2], 4);
  cam.dist = span + 12;
})();

/* -------------------------------------------------------------- render -- */
function resize() {
  const dpr = window.devicePixelRatio || 1;
  for (const [c, h] of [[stage, stage.clientHeight], [timeline, timeline.clientHeight]]) {
    c.width = Math.max(c.clientWidth * dpr, 1);
    c.height = Math.max(h * dpr, 1);
  }
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  tctx.setTransform(dpr, 0, 0, dpr, 0, 0);
}
window.addEventListener('resize', () => { resize(); draw(); });

function activeShot(t) {
  if (!DATA.shots.length) return null;
  let current = null;
  for (const e of DATA.events) {
    if (e.kind !== 'camera' || e.t > t) continue;
    const shot = DATA.shots.find(s => e.label === 'plan ' + s.id);
    if (shot) current = { shot: shot, at: e.t };
  }
  return current || { shot: DATA.shots[0], at: 0 };
}

function subjectPosition(name, placed) {
  const actor = DATA.actors.find(a => a.name === name);
  if (actor) {
    const p = placed[actor.name];
    const head = p && (p['Head'] || p['UpperTorso'] || p['Torso']);
    if (head) return worldOf(actor, head.p);
    return [actor.position[0], actor.position[1] + 1.5, actor.position[2]];
  }
  const piece = DATA.set.find(s => s.name === name);
  if (piece) return piece.position;
  return cam.target;
}

function worldOf(actor, local) {
  return add(actor.position, matVec(yawMat(actor.yaw), local));
}

function draw() {
  const w = stage.clientWidth, h = stage.clientHeight;
  ctx.clearRect(0, 0, w, h);
  ctx.fillStyle = '#14161a';
  ctx.fillRect(0, 0, w, h);

  const frame = Math.min(Math.round(state.time * DATA.fps), frames - 1);
  const placed = {};
  for (const actor of DATA.actors) {
    placed[actor.name] = poseAt(DATA.rigs[actor.rig], actor, frame);
  }

  let eye, target, fov = cam.fov;
  if (state.director && DATA.shots.length) {
    const cut = activeShot(state.time);
    eye = cut.shot.position.slice();
    const drift = cut.shot.drift || [0, 0, 0];
    // Every shot drifts, exactly as the Studio player tweens it.
    const k = Math.min((state.time - cut.at) / 4, 1);
    eye = add(eye, scale(drift, k));
    target = subjectPosition(cut.shot.lookAt, placed);
    fov = cut.shot.fov;
  } else {
    eye = orbitEye();
    target = cam.target;
  }

  const b = basis(eye, target);
  const focal = (h / 2) / Math.tan(fov * Math.PI / 360);
  const quads = [];

  function project(p) {
    const d = sub(p, eye);
    const z = dot(d, b.f);
    if (z < 0.2) return null;
    return { x: w/2 + dot(d, b.r) * focal / z, y: h/2 - dot(d, b.u) * focal / z, z: z };
  }

  // The floor is painted in its own pass, before everything else. Sorting it
  // with the rest by centroid depth puts its near edge in front of the actors
  // standing on it — a big quad's centroid can be nearer than a small object
  // genuinely in front of it. Nothing is ever under the ground, so this is
  // correct by construction rather than a fudge.
  const ground = [];

  function box(centre, rot, size, rgb, alpha, into) {
    const bucket = into || quads;
    const world = CORNERS.map(c =>
      add(centre, matVec(rot, [c[0]*size[0], c[1]*size[1], c[2]*size[2]])));
    const screen = world.map(project);
    for (const face of FACES) {
      const pts = face.map(i => screen[i]);
      if (pts.some(p => p === null)) continue;
      const a = world[face[0]], bb = world[face[1]], cc = world[face[2]];
      const n = norm(cross(sub(bb, a), sub(cc, bb)));
      // Back-face cull, so interior faces never paint over the silhouette.
      if (dot(n, sub(a, eye)) > 0) continue;
      const shade = 0.42 + 0.58 * Math.max(dot(n, LIGHT), 0);
      bucket.push({
        pts: pts,
        depth: (pts[0].z + pts[1].z + pts[2].z + pts[3].z) / 4,
        fill: `rgba(${Math.round(rgb[0]*shade)},${Math.round(rgb[1]*shade)},` +
              `${Math.round(rgb[2]*shade)},${alpha})`,
      });
    }
  }

  if (state.showSet) {
    for (const piece of DATA.set) {
      const floor = piece.kind === 'sol';
      box(piece.position, IDENT, piece.size, [92, 98, 110], 0.9, floor ? ground : quads);
    }
  }
  ground.sort((p, q) => q.depth - p.depth);
  paint(ground);

  if (state.showGrid) drawGrid(project);

  // A skin replaces a part's box with real geometry. Its vertices are already
  // in that part's local space, scaled into that part's box, so it rides the
  // exact same transform the box does and cannot come apart at the joints.
  function skinned(centre, rot, geometry, rgb) {
    const verts = geometry.vertices, tris = geometry.triangles;
    const world = new Array(verts.length / 3);
    for (let i = 0; i < world.length; i++) {
      world[i] = add(centre, matVec(rot, [verts[i*3], verts[i*3+1], verts[i*3+2]]));
    }
    const screen = world.map(project);
    for (let t = 0; t < tris.length; t += 3) {
      const a = screen[tris[t]], b2 = screen[tris[t+1]], c2 = screen[tris[t+2]];
      if (!a || !b2 || !c2) continue;
      const wa = world[tris[t]], wb = world[tris[t+1]], wc = world[tris[t+2]];
      const n = norm(cross(sub(wb, wa), sub(wc, wb)));
      if (dot(n, sub(wa, eye)) > 0) continue;
      const shade = 0.42 + 0.58 * Math.max(dot(n, LIGHT), 0);
      quads.push({
        pts: [a, b2, c2],
        depth: (a.z + b2.z + c2.z) / 3,
        fill: `rgb(${Math.round(rgb[0]*shade)},${Math.round(rgb[1]*shade)},` +
              `${Math.round(rgb[2]*shade)})`,
      });
    }
  }

  const skin = DATA.skins[state.skin] || null;

  DATA.actors.forEach((actor, index) => {
    const rgb = PALETTE[index % PALETTE.length];
    const rig = DATA.rigs[actor.rig];
    const yaw = yawMat(actor.yaw);
    for (const part of rig.parts) {
      if (part.parent === null) continue;  // HumanoidRootPart is invisible in game
      const local = placed[actor.name][part.name];
      const centre = add(actor.position, matVec(yaw, local.p));
      const rot = matMul(yaw, local.r);
      const geometry = skin && skin.rig === actor.rig ? skin.parts[part.name] : null;
      if (geometry) skinned(centre, rot, geometry, rgb);
      else box(centre, rot, part.size, rgb, 1);
    }
  });

  quads.sort((p, q) => q.depth - p.depth);
  paint(quads);

  // Name every actor and every set piece, so the view matches the build sheet.
  ctx.font = '12px ui-sans-serif, system-ui, sans-serif';
  ctx.textAlign = 'center';
  DATA.actors.forEach((actor, index) => {
    const p = placed[actor.name]['Head'] || placed[actor.name]['Torso'];
    if (!p) return;
    const s = project(add(worldOf(actor, p.p), [0, 1.2, 0]));
    if (!s) return;
    const rgb = PALETTE[index % PALETTE.length];
    ctx.fillStyle = `rgb(${rgb[0]},${rgb[1]},${rgb[2]})`;
    ctx.fillText(actor.name, s.x, s.y);
  });
  if (state.showSet) {
    ctx.fillStyle = '#8b93a1';
    for (const piece of DATA.set) {
      const s = project(add(piece.position, [0, piece.size[1] / 2 + 0.6, 0]));
      if (s) ctx.fillText(piece.name, s.x, s.y);
    }
  }
  ctx.textAlign = 'left';

  drawHud(frame);
  drawTimeline();
}

function paint(quads) {
  for (const quad of quads) {
    ctx.beginPath();
    ctx.moveTo(quad.pts[0].x, quad.pts[0].y);
    for (let i = 1; i < quad.pts.length; i++) ctx.lineTo(quad.pts[i].x, quad.pts[i].y);
    ctx.closePath();
    ctx.fillStyle = quad.fill;
    ctx.fill();
  }
}

function drawGrid(project) {
  const y = groundLevel();
  const half = 20, step = 4;
  ctx.strokeStyle = 'rgba(120,132,150,0.18)';
  ctx.lineWidth = 1;
  ctx.beginPath();
  for (let i = -half; i <= half; i += step) {
    for (const seg of [
      [[i, y, -half], [i, y, half]],
      [[-half, y, i], [half, y, i]],
    ]) {
      const a = project(seg[0]), b = project(seg[1]);
      if (!a || !b) continue;
      ctx.moveTo(a.x, a.y); ctx.lineTo(b.x, b.y);
    }
  }
  ctx.stroke();
}

function groundLevel() {
  const floor = DATA.set.find(s => s.kind === 'sol');
  if (floor) return floor.position[1] + floor.size[1] / 2;
  return 0;
}

function drawHud(frame) {
  const hud = document.getElementById('hud');
  const cut = state.director ? activeShot(state.time) : null;
  hud.innerHTML =
    `frame ${frame} / ${frames - 1} &nbsp; ${state.time.toFixed(2)} s` +
    (cut ? `<br>plan « ${cut.shot.id} » · ${cut.shot.fov}° · vise ${cut.shot.lookAt}` : '') +
    (DATA.tension.length ? `<br>tension ${tensionAt(state.time).toFixed(2)}` : '');

  // Anything that fired in the last third of a second, newest first.
  const recent = DATA.events
    .filter(e => e.t <= state.time && state.time - e.t < 0.35)
    .slice(-6).reverse();
  document.getElementById('fired').innerHTML = recent.map(e => {
    const fade = 1 - (state.time - e.t) / 0.35;
    const colour = LANE_COLOURS[e.kind] || '#9aa4b2';
    const who = e.actor ? `${e.actor} · ` : '';
    return `<div style="color:${colour};opacity:${(0.35 + 0.65*fade).toFixed(2)}">` +
           `${who}${escapeHtml(e.label)}</div>`;
  }).join('');
}

const LANE_COLOURS = __LANES__;

function escapeHtml(s) {
  return String(s).replace(/[&<>]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;'}[c]));
}

function tensionAt(t) {
  const curve = DATA.tension;
  if (!curve.length) return 0;
  if (t <= curve[0][0]) return curve[0][1];
  for (let i = 0; i < curve.length - 1; i++) {
    if (t < curve[i+1][0]) {
      const span = curve[i+1][0] - curve[i][0] || 1;
      const k = (t - curve[i][0]) / span;
      return curve[i][1] + (curve[i+1][1] - curve[i][1]) * k;
    }
  }
  return curve[curve.length - 1][1];
}

/* ------------------------------------------------------------ timeline -- */
function drawTimeline() {
  const w = timeline.clientWidth, h = timeline.clientHeight;
  tctx.clearRect(0, 0, w, h);
  const pad = 14;
  const span = Math.max(duration, 0.001);
  const x = t => pad + (w - 2*pad) * (t / span);

  // Tension behind everything: the shape of the scene at a glance.
  if (DATA.tension.length) {
    tctx.beginPath();
    tctx.moveTo(x(0), h - 4);
    for (const [t, v] of DATA.tension) tctx.lineTo(x(t), h - 4 - v * (h - 30));
    tctx.lineTo(x(span), h - 4);
    tctx.closePath();
    tctx.fillStyle = 'rgba(110,168,254,0.13)';
    tctx.fill();
  }

  // One lane per actor, showing what they are doing.
  const actors = DATA.actors.map(a => a.name);
  const laneH = 13;
  actors.forEach((name, i) => {
    const y = 8 + i * (laneH + 3);
    tctx.fillStyle = 'rgba(255,255,255,0.04)';
    tctx.fillRect(pad, y, w - 2*pad, laneH);
    const rgb = PALETTE[i % PALETTE.length];
    for (const cue of DATA.cues.filter(c => c.actor === name)) {
      tctx.fillStyle = `rgba(${rgb[0]},${rgb[1]},${rgb[2]},0.42)`;
      tctx.fillRect(x(cue.start), y, Math.max(x(cue.stop) - x(cue.start), 2), laneH);
      tctx.fillStyle = '#e6e9ee';
      tctx.font = '10px ui-sans-serif, system-ui, sans-serif';
      tctx.save();
      tctx.beginPath();
      tctx.rect(x(cue.start) + 3, y, Math.max(x(cue.stop) - x(cue.start) - 6, 0), laneH);
      tctx.clip();
      tctx.fillText(cue.what, x(cue.start) + 4, y + 10);
      tctx.restore();
    }
  });

  // Event ticks, tall for authored beats and short for spotted sound.
  const base = h - 4;
  for (const e of DATA.events) {
    const tall = e.kind !== 'spot' && e.kind !== 'sound';
    tctx.strokeStyle = LANE_COLOURS[e.kind] || '#9aa4b2';
    tctx.globalAlpha = tall ? 0.95 : 0.55;
    tctx.lineWidth = tall ? 2 : 1;
    tctx.beginPath();
    tctx.moveTo(x(e.t), base);
    tctx.lineTo(x(e.t), base - (tall ? 22 : 11));
    tctx.stroke();
  }
  tctx.globalAlpha = 1;

  tctx.strokeStyle = '#ffffff';
  tctx.lineWidth = 1.5;
  tctx.beginPath();
  tctx.moveTo(x(state.time), 2);
  tctx.lineTo(x(state.time), h - 2);
  tctx.stroke();

  document.getElementById('time').textContent =
    `${state.time.toFixed(2)} / ${span.toFixed(2)} s`;
}

function seekFromEvent(ev) {
  const rect = timeline.getBoundingClientRect();
  const pad = 14;
  const k = (ev.clientX - rect.left - pad) / Math.max(rect.width - 2*pad, 1);
  state.time = Math.min(Math.max(k, 0), 1) * duration;
  draw();
}
timeline.addEventListener('pointerdown', ev => {
  timeline.setPointerCapture(ev.pointerId);
  seekFromEvent(ev);
  timeline.onpointermove = seekFromEvent;
});
timeline.addEventListener('pointerup', ev => {
  timeline.onpointermove = null;
  timeline.releasePointerCapture(ev.pointerId);
});

/* -------------------------------------------------------------- input -- */
let drag = null;
stage.addEventListener('pointerdown', ev => {
  drag = { x: ev.clientX, y: ev.clientY, pan: ev.shiftKey || ev.button === 2 };
  stage.setPointerCapture(ev.pointerId);
});
stage.addEventListener('pointermove', ev => {
  if (!drag) return;
  const dx = ev.clientX - drag.x, dy = ev.clientY - drag.y;
  drag.x = ev.clientX; drag.y = ev.clientY;
  if (drag.pan) {
    const b = basis(orbitEye(), cam.target);
    const k = cam.dist / 600;
    cam.target = add(cam.target, add(scale(b.r, -dx * k), scale(b.u, dy * k)));
  } else {
    cam.yaw -= dx * 0.008;
    cam.pitch = Math.max(-1.45, Math.min(1.45, cam.pitch + dy * 0.006));
  }
  draw();
});
stage.addEventListener('pointerup', ev => {
  drag = null;
  stage.releasePointerCapture(ev.pointerId);
});
stage.addEventListener('contextmenu', ev => ev.preventDefault());
stage.addEventListener('wheel', ev => {
  ev.preventDefault();
  cam.dist = Math.max(2, Math.min(120, cam.dist * (1 + Math.sign(ev.deltaY) * 0.12)));
  draw();
}, { passive: false });

function toggle(id, key, after) {
  const el = document.getElementById(id);
  el.addEventListener('click', () => {
    state[key] = !state[key];
    el.classList.toggle('on', state[key]);
    if (after) after();
    draw();
  });
}
toggle('loop', 'loop');
toggle('director', 'director');
toggle('showset', 'showSet');
toggle('showgrid', 'showGrid');

// The rig picker only appears when there is a choice to make.
(function skinPicker() {
  if (!DATA.skins.length) return;
  const pick = document.getElementById('skinpick');
  const select = document.getElementById('skin');
  pick.hidden = false;
  DATA.skins.forEach((s, i) => {
    const option = document.createElement('option');
    option.value = String(i);
    option.textContent = s.name;
    select.appendChild(option);
  });
  const boxes = document.createElement('option');
  boxes.value = '-1';
  boxes.textContent = 'Boîtes (Block Rig)';
  select.appendChild(boxes);
  select.value = String(state.skin);
  select.addEventListener('change', ev => {
    state.skin = parseInt(ev.target.value, 10);
    draw();
  });
})();

document.getElementById('play').addEventListener('click', togglePlay);
document.getElementById('speed').addEventListener('change', ev => {
  state.speed = parseFloat(ev.target.value);
});
for (const [id, yaw, pitch] of [['front', 0, 0.1], ['side', Math.PI/2, 0.1], ['top', 0, 1.35]]) {
  document.getElementById(id).addEventListener('click', () => {
    cam.yaw = yaw; cam.pitch = pitch; state.director = false;
    document.getElementById('director').classList.remove('on');
    draw();
  });
}

function togglePlay() {
  state.playing = !state.playing;
  document.getElementById('play').textContent = state.playing ? '❚❚ Pause' : '▶ Lecture';
  document.getElementById('play').classList.toggle('on', state.playing);
  if (state.playing) { last = performance.now(); requestAnimationFrame(tick); }
}

window.addEventListener('keydown', ev => {
  if (ev.code === 'Space') { ev.preventDefault(); togglePlay(); }
  else if (ev.code === 'ArrowLeft') {
    state.time = Math.max(0, state.time - 1 / DATA.fps); draw();
  } else if (ev.code === 'ArrowRight') {
    state.time = Math.min(duration, state.time + 1 / DATA.fps); draw();
  } else if (ev.code === 'Home') { state.time = 0; draw(); }
});

let last = performance.now();
function tick(now) {
  if (!state.playing) return;
  state.time += (now - last) / 1000 * state.speed;
  last = now;
  if (state.time > duration) {
    if (state.loop) state.time = 0;
    else { state.time = duration; togglePlay(); }
  }
  draw();
  requestAnimationFrame(tick);
}

/* --------------------------------------------------------- deep links -- */
// #t=2.03&cam=front&director=1 opens on a moment. Useful for pointing someone
// at the exact frame an impact lands, and for screenshotting one.
(function openAt() {
  const q = new URLSearchParams(location.hash.slice(1));
  if (q.has('t')) state.time = Math.min(Math.max(parseFloat(q.get('t')) || 0, 0), duration);
  if (q.get('director') === '1' && DATA.shots.length) {
    state.director = true;
    document.getElementById('director').classList.add('on');
  }
  const views = { front: [0, 0.1], side: [Math.PI/2, 0.1], top: [0, 1.35], back: [Math.PI, 0.1] };
  const view = views[q.get('cam')];
  if (view) { cam.yaw = view[0]; cam.pitch = view[1]; }
  if (q.has('dist')) cam.dist = parseFloat(q.get('dist')) || cam.dist;
})();

resize();
draw();
</script>
</body>
</html>
"""
