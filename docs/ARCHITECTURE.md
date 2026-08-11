# Architecture

## Le pipeline

```
FreeMoCap (.npy)  ─┐
                   ├─> AnimationClip ─> réduction ─> .rbxmx (KeyframeSequence)
prompt ─> plan ────┘                 └─> .json (viewport three.js)
```

Deux sources, une représentation, deux sorties. `AnimationClip`
([`linen/clip.py`](../linen/clip.py)) est le pivot : `fps`, plus un tableau de
quaternions `(frames, 4)` par part, **locaux au parent et relatifs à la pose de
repos du rig**. C'est exactement ce que stocke un `Pose.CFrame` Roblox, donc
l'export est une transcription, pas une conversion.

| Module | Responsabilité |
| --- | --- |
| `linen/math3d.py` | Quaternions, matrices, bases orthonormées, easing des rotations |
| `linen/rigs/` | R15, R6 : topologie, axes, sources de landmarks |
| `linen/retarget/` | Landmarks → rotations articulaires |
| `linen/generate/` | Prompt → plan → clip |
| `linen/export/` | `.rbxmx` pour Studio, `.json` pour le viewport |

## Pourquoi on n'a jamais besoin des tailles de parts

Une animation Roblox ne stocke pas des orientations absolues : un `Pose.CFrame`
est une transformation appliquée *par-dessus* le repos du joint. Il ne faut donc
connaître que la **topologie** du rig, jamais sa géométrie. Trois conséquences,
toutes bonnes :

- une animation captée sur quelqu'un de n'importe quelle taille joue
  correctement sur n'importe quel avatar ;
- pas d'étape de calibration ;
- les tailles présentes dans `linen/rigs/` ne servent qu'au preview, et une
  erreur dedans ne peut pas corrompre un export.

## Les conventions, et pourquoi elles sont fragiles

C'est la partie où une erreur de signe produit un personnage aux genoux à
l'envers, alors autant l'écrire noir sur blanc.

**Espace Roblox** : main droite, `+Y` en haut, le personnage regarde vers `-Z`,
son propre côté droit est `+X`. three.js partage cette convention, d'où
l'absence de conversion vers le viewport.

**Pose de repos** : les deux rigs de stock reposent avec toutes les parts
alignées sur les axes — bras et jambes pendants. La rotation de repos de chaque
part est donc l'identité, et la rotation qu'on résout *est* la pose exportée.

**Axes d'une part** (`aim_axis`) : la direction, dans l'espace propre de la
part, vers laquelle l'os pointe. `-Y` pour un bras ou une jambe, `+Y` pour le
torse et la tête, `-Z` pour un pied. Il en découle, pour un membre :

| Rotation | Effet |
| --- | --- |
| `+X` | l'os part vers l'avant — flexion d'épaule, flexion de coude |
| `-X` | l'os part vers l'arrière — flexion de genou |
| signe de `Z` | abduction vers la droite du personnage |
| `Y` | torsion autour de l'os |

Le `t_pose` du posebook vaut `Z = -90°` sur le bras gauche et `+90°` sur le
droit ; le test `test_t_pose_matches_the_authored_t_pose` vérifie que le
reciblage d'une vraie T-pose retombe exactement dessus. C'est le garde-fou
contre une dérive entre les deux moitiés du projet.

**Le twist.** Viser un os avec un vecteur ne fixe que deux degrés de liberté sur
trois. Le troisième — la torsion autour de l'os — doit venir d'ailleurs, sinon
il dérive d'une frame à l'autre et les coudes se retournent. Chaque part déclare
donc un `roll_axis` (un axe *dans son espace propre*) et chaque source déclare
d'où vient sa direction *monde* :

- `LATERAL` — une paire de landmarks gauche/droite (épaules, hanches, oreilles) ;
- `CHAIN_PLANE` — la normale du plan passant par les trois landmarks de la
  charnière. Les deux os d'une même charnière citent **le même** triplet : la
  torsion d'un tibia vient du genou, pas de la direction des orteils ;
- `PARENT_BACK` / `PARENT_UP` — hérité du parent, pour les mains et les pieds
  dont les landmarks propres sont trop bruités.

Le solveur construit deux bases avec la même fonction — `(aim_axis, roll_axis)`
dans l'espace de la part, `(direction de l'os, indice de twist)` dans le monde —
et compose l'une avec l'inverse de l'autre. Les deux paires doivent décrire les
mêmes directions, sinon tous les membres sortent en miroir.

**Le cas dégénéré.** Quand l'indice de twist devient colinéaire à l'os — un bras
tendu le long de son propre axe de flexion — la torsion n'est tout simplement
pas dans la donnée. Le solveur bascule alors sur la rotation d'arc minimal
(*swing*) depuis le parent, qui n'invente aucun roll, plutôt que de laisser la
base tomber sur un axe monde arbitraire et sauter d'une frame à l'autre.

## Réduction de keyframes

Roblox interpole entre les poses, donc écrire chaque frame est du gaspillage :
dix secondes à 60 fps sur un R15 font ~9 000 poses. `linen/export/keyframes.py`
applique un Ramer–Douglas–Peucker adapté aux rotations : on suppose un slerp
droit entre les deux extrémités, on cherche la frame qui s'en écarte le plus, et
on coupe là si l'écart dépasse la tolérance. Les points de rebroussement sont
gardés par construction — c'est ce qui empêche de raboter le sommet d'un
mouvement rapide, contrairement à une décimation « une frame sur N ».

Corollaire testé : une rotation à vitesse constante *est* un slerp et se réduit
à deux keyframes exactement.

## Le plan de mouvement

[`schema.py`](../linen/generate/schema.py) définit la seule chose qu'un LLM
produit. C'est un **emploi du temps**, pas de la donnée de mouvement : des
segments sur une timeline, chacun tenant une pose ou un cycle, avec un easing et
une durée de fondu.

La validation est stricte et volontairement bavarde. Les modèles inventent des
noms de poses ; un repli silencieux sur le repos ressemblerait à un bug de
l'exporteur trois étages plus loin. À la place, le message d'erreur est renvoyé
au modèle pour une passe de réparation
([`choreographer.py`](../linen/generate/choreographer.py)), ce qui rattrape la
grande majorité des échecs sans changer de fournisseur.

`_coerce` est délibérément étroit : il complète un `fps` omis et déballe un plan
imbriqué sous une clé parasite. Rien d'autre. Une mauvaise pose ou une timeline
incohérente doit échouer, pour que le modèle l'apprenne.

## Étendre la banque de poses

Ajouter une entrée à `POSES` suffit : le schéma JSON, le prompt système et la
CLI la reprennent automatiquement. Les poses s'écrivent en degrés Euler XYZ, par
part, relatifs au repos, dans l'ordre de `CFrame.Angles(x, y, z)`.

N'écrire que le côté gauche et dériver le droit avec `mirror()` — la réflexion
échange les préfixes `Left`/`Right` et inverse les termes Y et Z. Deux poses
symétriques écrites à la main finissent toujours par diverger.

Le vrai chemin de montée en qualité n'est pas d'écrire plus de poses à la main :
c'est de capturer les extrêmes avec FreeMoCap, de les recibler, et d'extraire
les frames clés du clip obtenu. Les poses deviennent alors du mouvement humain
réel, et le LLM continue de ne faire que ce qu'il fait bien — les choisir et les
placer dans le temps.
