# Linen

Des animations Roblox **R15 / R6** à partir de FreeMoCap — et à partir d'un
prompt texte, sans coût d'API.

```bash
# une capture FreeMoCap -> un fichier importable dans Studio
linen retarget mediapipe_body_3d_xyz.npy --fps 30 -o wave.rbxmx

# un prompt -> un plan -> la même sortie
linen prompt "un salut amical, puis le personnage repart au pas" -o hello.rbxmx
```

---

## Est-ce que c'est possible ? Oui — mais pas de la façon dont ça se raconte

La question posée était : *brancher FreeMoCap sur des rigs Roblox, et générer
des animations depuis un prompt, gratuitement, sans sacrifier la qualité.*
Trois morceaux, trois réponses différentes, et il vaut mieux les séparer tout de
suite parce qu'ils n'ont pas du tout le même niveau de difficulté.

**1. Le rig R15/R6 dans le viewport FreeMoCap — oui, franchement facile.**
FreeMoCap v2 rend déjà son viewport avec three.js et `@react-three/fiber`. Le
rig est un composant React de plus dans la scène. C'est fait, c'est dans
[`viewport/`](viewport/).

**2. Capture FreeMoCap → animation Roblox — oui, et c'est là qu'est la qualité.**
C'est le chemin solide. Du vrai mouvement humain, capté, reciblé sur le rig :
le poids, le timing, les micro-décalages, tout ce qui fait qu'une animation
« sent » juste, sont déjà dans la donnée. Aucun modèle génératif ne rivalise
aujourd'hui avec une captation propre. C'est aussi la partie la plus technique
et elle est faite : voir [`linen/retarget/`](linen/retarget/).

**3. Prompt → animation — la technologie existe et elle est bonne. Elle n'est
simplement ni gratuite ni faite avec un LLM.**

Il faut distinguer deux choses que le mot « IA » confond.

**Les modèles de diffusion de mouvement — ça marche, pour de vrai.**
[DeepMotion SayMotion](https://www.deepmotion.com/saymotion) et
[NoCapMocap](https://www.nocapmocap.com/roblox) font exactement ce que tu
décris, et NoCapMocap vise précisément Roblox R15, avec un plugin Studio
gratuit pour l'import en un clic. Leur API publique est documentée
([openapi.json](https://www.nocapmocap.com/openapi.json)) et le paramètre
`cfgScale` de leur endpoint `/api/generate` est une échelle de *classifier-free
guidance* : c'est la signature d'un **modèle de diffusion**, entraîné sur une
bibliothèque de mocap. Pas un LLM.

**Un LLM de chat, lui, ne génère pas de mouvement.** Demander à Gemini,
DeepSeek, Kimi ou Grok des angles articulaires image par image donne du bruit :
ces modèles n'ont pas de représentation interne du mouvement humain, et une
animation à 30 fps sur 15 articulations, c'est ~5 400 nombres corrélés par
seconde à sortir en tokens. Ça ne marche pas, quel que soit le modèle, gratuit
ou payant.

Donc la contrainte réelle n'est pas technique, elle est économique. Les deux
services ci-dessus fonctionnent au **crédit**, avec un plafond de **10 secondes
par génération**. Le « gratuit » du cahier des charges ne tombe pas là.

Il tombe ici : **les mêmes modèles de diffusion existent en open source et
tournent en local** — [MoMask](https://github.com/EricGuo5513/momask-codes),
MDM, et la génération suivante. Même famille de technologie, zéro crédit, zéro
plafond. C'est ça, la vraie réponse à « prompt → animation, gratuit, sans
sacrifier la qualité ».

**Ce que Linen fait de tout ça.** Deux choses, et pas de concurrence frontale :

- **Il ingère leur sortie.** `linen bvh` prend un BVH — export SayMotion, MoMask
  ou MDM lancé en local, téléchargement Mixamo — et le recible sur R15/R6 avec
  le même solveur, les mêmes conventions et le même exporteur que la voie
  FreeMoCap. Un test vérifie que les deux chemins donnent la même chose sur la
  même pose. Linen est le tuyau, pas un concurrent du modèle.
- **Il fournit une voie 100 % hors ligne**, pour quand il n'y a ni crédit ni
  GPU : **le LLM dirige, il n'anime pas.** Le modèle reçoit un vocabulaire de
  poses et de cycles et renvoie un *plan* — quelle pose à quel instant, avec
  quel easing, quelle énergie. Un synthétiseur déterministe fait le reste.

Sur cette seconde voie, la qualité vient de trois choses toutes gratuites et
sous notre contrôle :

- **les poses clés**, écrites à la main une fois pour toutes
  ([`posebook.py`](linen/generate/posebook.py)) — ou capturées avec FreeMoCap,
  ce qui est le vrai chemin de montée en qualité ;
- **le timing**, où le LLM est réellement bon : anticipation, hold, settle,
  contraste des durées — c'est un problème de planification, pas de calcul ;
- **les easings avec dépassement** (`anticipate`, `overshoot`), qui sont
  littéralement les principes d'animation Disney appliqués aux transitions.

Résultat honnête : on obtient des animations propres, lisibles, qui tiennent
sans problème dans un jeu Roblox. C'est en dessous d'un modèle de diffusion
dédié sur du mouvement complexe — un modèle entraîné sur des milliers d'heures
de mocap trouve des transitions qu'aucun vocabulaire écrit à la main ne
contient. En revanche c'est déterministe, illimité, relisible et modifiable, ce
qu'aucun des deux services n'offre.

**Sur le « gratuit » des clés LLM.** Ce sont des *free tiers*, pas de
l'illimité. Gemini est le plus généreux (palier gratuit permanent, sans carte).
Le reste tourne entre quotas journaliers et crédits promotionnels. Linen essaie
les fournisseurs en chaîne et passe au suivant sur un refus. Et comme le LLM ne
produit qu'un plan JSON de quelques centaines d'octets, une animation coûte *un*
appel : même un quota gratuit serré tient largement. La synthèse, elle, est
locale et gratuite pour de bon — `linen synth` sur un plan écrit à la main ne
touche jamais le réseau.

### En résumé, trois sources pour la même sortie

| Source | Qualité | Coût | Quand |
| --- | --- | --- | --- |
| `linen retarget` — capture FreeMoCap | La meilleure | Gratuit | Tu peux filmer le mouvement |
| `linen bvh` — SayMotion, NoCapMocap, MoMask/MDM local | Très bonne | Crédits, ou gratuit en local | Tu ne peux pas filmer |
| `linen prompt` / `linen synth` — plan + poses | Correcte, déterministe | Gratuit | Ni caméra, ni crédit, ni GPU |

---

## Installation

```bash
uv venv && uv pip install -e ".[dev]"
```

Seule dépendance d'exécution : `numpy`. Les appels HTTP passent par la
bibliothèque standard.

## Utilisation

### Recibler une capture FreeMoCap

```bash
linen retarget recording/output_data/mediapipe_body_3d_xyz.npy \
  --fps 30 --rig R15 -o take.rbxmx --preview take.json
```

| Option | À quoi ça sert |
| --- | --- |
| `--axes` | Convention de la capture : `z_up` (défaut, ce qu'écrit FreeMoCap), `y_up`, `mediapipe_world` |
| `--units` | `mm` (défaut), `cm`, `m` |
| `--root-motion` | Cuit la translation du `HumanoidRootPart`. Désactivé par défaut : sur un personnage vivant, c'est le `Humanoid` qui pilote la position, et une racine cuite se bat avec lui. À activer pour une cinématique. |
| `--smoothing` | Fenêtre de lissage en frames (défaut 5) |
| `--tolerance` | Réduction de keyframes, en degrés. `0` garde toutes les frames. |

Le recalage est **uniquement rotationnel**, donc indépendant de la taille du
sujet : quelqu'un de 1,55 m et quelqu'un de 1,95 m pilotent le même rig sans
calibration.

### Ingérer un BVH généré ailleurs

```bash
linen bvh saymotion_export.bvh --units cm --rig R15 -o dance.rbxmx
```

Marche avec tout squelette humanoïde nommé à la Mixamo — ce qui couvre les
exports SayMotion, les sorties MoMask / MDM converties depuis HumanML3D, et les
téléchargements Mixamo. `--skeleton` accepte `mixamo`, `smpl`, `humanml3d`,
`fbx` (alias du même mapping).

Deux repères que MediaPipe fournit et qu'un squelette d'animation n'a pas sont
reconstruits : les **talons** (sous la cheville, à la hauteur des orteils) et les
**oreilles** (de part et d'autre de la tête, à partir de l'os du cou). Le lacet
de la tête est perdu au passage et suit le buste — c'est la seule perte connue
de ce chemin, et elle est testée comme telle.

L'orientation du squelette source n'a pas d'importance : chaque rotation étant
résolue relativement à son parent, un personnage qui regarde `+Z` donne les
mêmes rotations locales qu'un qui regarde `-Z`. Seul le root motion cuit le
remarque.

### Générer depuis un prompt

```bash
export GEMINI_API_KEY=...
linen prompt "esquive à droite, contre-attaque, retour en garde" \
  -o dodge.rbxmx --save-plan dodge.plan.json
```

`linen providers` liste les fournisseurs et lesquels sont configurés.

Le plan sauvegardé est un JSON court, relisible et modifiable à la main :

```bash
linen synth dodge.plan.json -o dodge.rbxmx   # aucun réseau
```

C'est le mode de travail recommandé : le LLM propose, vous ajustez le timing
dans le JSON, vous resynthétisez. `linen vocabulary` liste les poses et cycles
disponibles.

### Le viewport

Voir [`viewport/README.md`](viewport/README.md) : deux fichiers à déposer dans
`freemocap-ui`, un `<RobloxRig rig="R15" clip={clip} />` dans la scène.

## Importer dans Roblox

La sortie est un `KeyframeSequence` en `.rbxmx`.

1. Studio → **Animation Editor**, rig sélectionné ;
2. menu **⋯** → **Import** → **From File…** → le `.rbxmx` ;
3. **Publish to Roblox** pour obtenir l'asset ID.

À propos de l'Open Cloud : l'API Assets accepte bien les uploads d'animations,
mais la documentation Roblox précise qu'un `.rbxm`/`.rbxmx` **édité hors de
Studio peut être refusé**. L'import Studio est donc le chemin supporté ; l'Open
Cloud est une commodité qui peut marcher ou non selon le fichier. Linen n'essaie
pas de faire croire l'inverse.

## Tests

```bash
pytest
```

Le test qui compte le plus est
`test_rest_pose_solves_to_identity_on_every_joint` : une silhouette debout en
pose de repos doit se recibler en rotation identité sur chaque articulation. Si
une convention d'axe dérive quelque part dans la chaîne, il tombe.

## Ce qui n'est pas là

- **Doigts et visage.** FreeMoCap capte les mains et le visage, R15 s'arrête au
  poignet. Rien à recibler.
- **Verrouillage des appuis (foot IK).** L'export étant rotationnel, Roblox gère
  la position ; un léger patinage reste possible sur une locomotion rapide.
- **Le modèle de diffusion lui-même.** Linen consomme du BVH, il n'en génère
  pas. Lancer MoMask ou MDM en local reste à ta charge (poids + PyTorch) ; une
  fois le BVH écrit, `linen bvh` prend le relais. Emballer ça dans une commande
  `linen generate --local` serait la suite logique.
- **Un client pour les API payantes.** Rien n'empêche d'appeler
  `/api/generate` de NoCapMocap ou l'API SayMotion depuis un script et de passer
  le résultat à `linen bvh` — mais ça demande un compte et des crédits, donc ce
  n'est pas câblé dans l'outil.

## Licence

AGPL-3.0-or-later, pour rester compatible avec FreeMoCap qui est lui-même sous
AGPL-3.0. Toute distribution d'une version modifiée doit en publier les sources.
