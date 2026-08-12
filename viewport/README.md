# Viewport — le rig Roblox dans FreeMoCap

FreeMoCap v2 rend son viewport avec **three.js + @react-three/fiber** (voir
`freemocap-ui/package.json` : `three`, `@react-three/fiber`, `@react-three/drei`).
Le rig s'ajoute donc comme un composant React ordinaire, sans toucher au moteur
de rendu.

## Fichiers

| Fichier | Rôle |
| --- | --- |
| `rigs.generated.ts` | Géométrie R15 / R6 **et** les contrôles de génération. **Généré** — ne pas éditer à la main. |
| `RobloxRig.tsx` | Le composant R3F. |

Le module généré exporte aussi de quoi construire la barre de contrôles :

```ts
import { DURATION_PRESETS, FIT_STRATEGIES, MOTION_MODES } from "./rigs.generated";
// DURATION_PRESETS -> [null, 3, 5, 10, 15, 30, 60]   (null = durée naturelle)
// FIT_STRATEGIES   -> ["auto", "cycle", "repeat", "stretch", "trim"]
// MOTION_MODES     -> in-place / natural / loop, avec libellé et explication
```

Ces valeurs viennent des mêmes constantes que le CLI. Un sélecteur de durée
codé en dur dans le frontend finirait par proposer autre chose que ce que le
planificateur accepte — et les presets ne sont que des suggestions : le champ
accepte n'importe quelle valeur, il n'y a pas de plafond à 10 s.

Régénérer la géométrie après toute modification des rigs Python :

```bash
python -m linen.export.preview viewport/rigs.generated.ts
```

C'est généré volontairement : un rig dessiné dans le viewport qui diverge de
celui qu'écrit l'exporteur donnerait un aperçu qui ment sur le fichier envoyé à
Studio.

## Intégration

Copier les deux fichiers dans `freemocap-ui/src/components/roblox/`, puis les
monter dans la scène existante :

```tsx
import { RobloxRig } from "./components/roblox/RobloxRig";

<Canvas camera={{ position: [0, 3, 12], fov: 45 }}>
  <ambientLight intensity={0.6} />
  <directionalLight position={[5, 10, 5]} castShadow />
  <RobloxRig rig={rigName} clip={clip} playing />
  <OrbitControls />
</Canvas>
```

`rigName` vaut `"R15"` ou `"R6"` — un simple toggle dans le panneau
« Viewport settings » suffit à basculer de l'un à l'autre.

## Alimenter le rig

Trois modes, du plus simple au plus vivant :

1. **Un clip** — `linen retarget ... --preview clip.json` écrit un JSON dense
   (une pose par frame) que `RobloxRig` lit tel quel via la prop `clip`.
2. **Une frame imposée** — passer `frame={n}` pour synchroniser le rig avec le
   scrub bar de la timeline plutôt que de le laisser jouer tout seul.
3. **Du direct** — la prop `pose` prend un dictionnaire
   `{ nomDeLaPart: [x, y, z, w] }` et court-circuite le clip. C'est le chemin à
   brancher sur le websocket de FreeMoCap pour voir le personnage Roblox bouger
   pendant l'enregistrement.

Roblox et three.js partagent la même convention (main droite, Y vers le haut),
donc les quaternions s'appliquent sans conversion d'axes.

## Ce que le preview n'est pas

Les tailles de parts sont celles du rig « Build Rig » de Studio, arrondies.
Elles ne servent qu'à l'affichage : l'animation exportée ne contient que des
rotations, elle est donc indépendante des proportions de l'avatar. Un avatar
custom aux bras plus longs jouera le même fichier correctement même si le
preview, lui, montre des proportions standard.
