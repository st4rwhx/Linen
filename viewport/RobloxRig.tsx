/**
 * An R15 or R6 Roblox rig for the FreeMoCap viewport.
 *
 * FreeMoCap's UI already renders with three.js through @react-three/fiber, so
 * this drops in beside the existing skeleton view rather than replacing it —
 * the point is to see the capture on the body it is going to ship on, while it
 * is being captured.
 *
 * The rig geometry comes from `rigs.generated.ts`, which is written by
 * `python -m linen.export.preview`. Editing the parts here instead would let
 * the preview drift away from what the exporter actually writes.
 *
 * Roblox and three.js agree on handedness and on Y being up, so quaternions
 * from a clip apply directly with no axis conversion.
 */

import { useFrame } from "@react-three/fiber";
import { useLayoutEffect, useMemo, useRef } from "react";
import * as THREE from "three";

import { RIGS, type RigDefinition, type RigPart } from "./rigs.generated";

/** A clip as written by `linen.export.preview.write_preview`. */
export interface PreviewClip {
  name: string;
  rig: string;
  fps: number;
  frameCount: number;
  loop: boolean;
  /** Part name -> flat xyzw quaternions, four numbers per frame. */
  rotations: Record<string, number[]>;
  /** Flat xyz triples in studs, or null when root motion was not baked. */
  rootPositions: number[] | null;
}

export interface RobloxRigProps {
  rig?: keyof typeof RIGS;
  clip?: PreviewClip | null;
  /** Advance the clip automatically. Ignore with a controlled `frame`. */
  playing?: boolean;
  /** Pin to one frame, e.g. from a scrub bar. Overrides `playing`. */
  frame?: number;
  /** Live pose, part name -> xyzw. Takes priority over `clip`; use for a
   *  streaming solve where there is no clip yet. */
  pose?: Record<string, [number, number, number, number]>;
  color?: string;
  accentColor?: string;
  /** Draw the HumanoidRootPart, which is invisible on a real character. */
  showRoot?: boolean;
  onFrameChange?: (frame: number) => void;
}

const LIMB_PATTERN = /Arm|Leg|Hand|Foot/;

export function RobloxRig({
  rig = "R15",
  clip = null,
  playing = true,
  frame,
  pose,
  color = "#d8d8d8",
  accentColor = "#4b9cd3",
  showRoot = false,
  onFrameChange,
}: RobloxRigProps) {
  const definition = RIGS[rig];
  if (!definition) {
    throw new Error(`unknown rig "${rig}"; known rigs: ${Object.keys(RIGS).join(", ")}`);
  }

  const joints = useRef(new Map<string, THREE.Group>());
  const rootGroup = useRef<THREE.Group>(null);
  const elapsed = useRef(0);
  const lastFrame = useRef(-1);

  // A clip carrying a different rig's parts would silently animate nothing,
  // which reads as "the exporter is broken" rather than "wrong rig selected".
  const mismatched = clip !== null && clip.rig !== rig;

  useLayoutEffect(() => {
    elapsed.current = 0;
    lastFrame.current = -1;
  }, [clip, rig]);

  useFrame((_state, delta) => {
    if (pose) {
      applyPose(joints.current, pose);
      return;
    }
    if (!clip || mismatched || clip.frameCount === 0) return;

    let index: number;
    if (frame !== undefined) {
      index = clamp(Math.round(frame), 0, clip.frameCount - 1);
    } else {
      if (playing) elapsed.current += delta;
      const raw = Math.floor(elapsed.current * clip.fps);
      index = clip.loop
        ? ((raw % clip.frameCount) + clip.frameCount) % clip.frameCount
        : clamp(raw, 0, clip.frameCount - 1);
    }

    if (index === lastFrame.current) return;
    lastFrame.current = index;

    for (const [part, values] of Object.entries(clip.rotations)) {
      const group = joints.current.get(part);
      if (!group) continue;
      const at = index * 4;
      group.quaternion.set(values[at], values[at + 1], values[at + 2], values[at + 3]);
    }

    if (clip.rootPositions && rootGroup.current) {
      const at = index * 3;
      rootGroup.current.position.set(
        clip.rootPositions[at],
        clip.rootPositions[at + 1],
        clip.rootPositions[at + 2],
      );
    }

    onFrameChange?.(index);
  });

  const tree = useMemo(() => buildTree(definition), [definition]);

  return (
    <group ref={rootGroup} name={`${rig}-rig`}>
      {tree.map((node) => (
        <RigNode
          key={node.part.name}
          node={node}
          joints={joints}
          color={color}
          accentColor={accentColor}
          showRoot={showRoot}
        />
      ))}
    </group>
  );
}

interface Node {
  part: RigPart;
  children: Node[];
}

function buildTree(definition: RigDefinition): Node[] {
  const nodes = new Map<string, Node>(
    definition.parts.map((part) => [part.name, { part, children: [] }]),
  );
  const roots: Node[] = [];
  for (const part of definition.parts) {
    const node = nodes.get(part.name)!;
    if (part.parent === null) roots.push(node);
    else nodes.get(part.parent)!.children.push(node);
  }
  return roots;
}

function RigNode({
  node,
  joints,
  color,
  accentColor,
  showRoot,
}: {
  node: Node;
  joints: React.MutableRefObject<Map<string, THREE.Group>>;
  color: string;
  accentColor: string;
  showRoot: boolean;
}) {
  const { part } = node;
  const isRoot = part.parent === null;
  const visible = !isRoot || showRoot;

  return (
    // Outer group is the joint frame — poses rotate about the joint, not about
    // the part's centre, which is what keeps a bent elbow attached to the arm.
    <group
      position={part.pivot}
      ref={(group) => {
        if (group) joints.current.set(part.name, group);
        else joints.current.delete(part.name);
      }}
    >
      <group position={part.offsetFromPivot}>
        {visible && (
          <mesh castShadow receiveShadow>
            <boxGeometry args={part.size} />
            <meshStandardMaterial
              color={LIMB_PATTERN.test(part.name) ? accentColor : color}
              roughness={0.65}
              metalness={0.05}
              transparent={isRoot}
              opacity={isRoot ? 0.25 : 1}
            />
          </mesh>
        )}
        {node.children.map((child) => (
          <RigNode
            key={child.part.name}
            node={child}
            joints={joints}
            color={color}
            accentColor={accentColor}
            showRoot={showRoot}
          />
        ))}
      </group>
    </group>
  );
}

function applyPose(
  joints: Map<string, THREE.Group>,
  pose: Record<string, [number, number, number, number]>,
) {
  for (const [part, q] of Object.entries(pose)) {
    joints.get(part)?.quaternion.set(q[0], q[1], q[2], q[3]);
  }
}

function clamp(value: number, low: number, high: number): number {
  return Math.min(Math.max(value, low), high);
}
