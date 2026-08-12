# Architecture

## Le pipeline

```
FreeMoCap (.npy) ──┐
BVH externe ───────┼─> LandmarkTrack ─> solveur ─┐
                   │                             ├─> AnimationClip ─┬─> .rbxmx
prompt ─┬─ LLM ────┴──> MotionPlan ─> synthèse ──┘   (R15 et/ou R6) └─> .json
        └─ offline ──┘
```

Trois sources, une représentation, deux sorties. `AnimationClip`
([`linen/clip.py`](../linen/clip.py)) est le pivot : `fps`, plus un tableau de
quaternions `(frames, 4)` par part, **locaux au parent et relatifs à la pose de
repos du rig**. C'est exactement ce que stocke un `Pose.CFrame` Roblox, donc
l'export est une transcription, pas une conversion.

| Module | Responsabilité |
| --- | --- |
| `linen/math3d.py` | Quaternions, matrices, bases orthonormées, easing des rotations |
| `linen/rigs/` | R15, R6 : topologie, axes, sources de landmarks |
| `linen/retarget/` | Landmarks → rotations articulaires |
| `linen/sources/` | BVH et squelettes étrangers → landmarks |
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

## Pourquoi le solveur travaille sur des positions nommées

Le reciblage ne consomme jamais un tracker, il consomme des **points nommés**.
C'est ce qui permet à un BVH venu d'ailleurs de devenir une entrée valide avec
un simple mapping de noms ([`sources/skeletons.py`](../linen/sources/skeletons.py))
et de traverser exactement le même solveur, les mêmes conventions et le même
exporteur qu'une captation FreeMoCap. Le test
`test_bvh_and_freemocap_paths_agree_on_the_same_pose` verrouille cette
équivalence.

Conséquence directe : le BVH est parsé pour ses **positions**, pas pour ses
rotations. Un BVH exprime ses rotations contre son propre repos et son propre
ordre de canaux ; les consommer directement lierait le solveur aux conventions
de chaque exporteur. On fait donc la cinématique directe et on jette les
rotations — sauf pour reconstruire les oreilles, faute de mieux.

L'ordre des canaux, lui, est respecté et pas supposé. Un BVH liste presque
toujours `ZXY` ; l'appliquer comme `XYZ` produit une pose plausible mais fausse,
que rien en aval ne rattrape. `test_channel_order_is_honoured` couvre ce piège.

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

## Le planificateur hors-ligne

[`offline.py`](../linen/generate/offline.py) produit le même `MotionPlan` sans
modèle du tout. C'est du **matching de mots-clés**, dit tel quel dans le module :
il ne comprend pas une phrase, il y reconnaît des mots.

Ce qu'il a en revanche, c'est la partie qu'un LLM rate le plus souvent : le
**timing**. Chaque action est une *beat sheet* écrite à la main — anticipation,
action, settle, avec des durées volontairement contrastées. Un saut, par
exemple, ne s'écrit pas « pose accroupie puis pose en l'air » : c'est un
`crouch` court en `anticipate`, un décollage de 0,10 s, un apex qui *tient*
0,34 s, une réception brève et un `overshoot` de retour. C'est ça qui fait le
poids, et ça ne dépend d'aucun modèle.

Trois invariants sont testés parce qu'ils cassent silencieusement :

- toute pose et tout cycle cité par une action existe vraiment dans la banque,
  **des deux côtés** pour les actions latéralisées ;
- une action qui propose un choix gauche/droite doit templater *tous* ses beats
  — un salut dont le cycle est câblé à droite ignorerait « de la main gauche »
  sans rien signaler (bug réel, attrapé par ce test) ;
- une boucle n'est proposée que si toutes les actions de la séquence sont
  bouclables : boucler un saut renverrait le personnage en l'air d'un coup.

Quand rien n'est reconnu, il produit un idle **et l'écrit dans `notes`**, avec
la liste de ce qu'il sait faire. Un repli silencieux passerait pour un bug.

## Choisir le rig

`--rig` accepte `R15`, `R6` ou `both` sur toutes les commandes. Le cas `both`
résout, synthétise et exporte une fois par rig, et suffixe les fichiers
(`take.R15.rbxmx`, `take.R6.rbxmx`). Rien n'est partagé entre les deux passes :
le solveur R6 lit ses propres `BoneSource`, et l'adaptation des poses vers R6
(`R6_FROM_R15` dans [`synth.py`](../linen/generate/synth.py)) **laisse tomber**
les coudes et les genoux plutôt que de replier leur flexion dans l'épaule ou la
hanche — R6 n'a pas ces articulations, et les simuler lit plus mal que de ne
rien faire.

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
