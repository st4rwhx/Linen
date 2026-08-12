# Euphoria sur Roblox : ce qui est atteignable, et ce qui ne l'est pas

## Le changement de nature

Tout ce que Linen faisait jusqu'ici est **hors-ligne** : du Python qui écrit des
fichiers `.rbxmx`, une fois, sur ta machine. Euphoria est **runtime** : il
tourne à chaque frame dans le moteur, et rien n'y est pré-calculé.

Ce sont donc deux programmes différents. Ce module vit dans
[`runtime/`](../runtime/), en Luau, et **s'embarque dans ta place Roblox**. Il
ne produit pas de fichiers ; il modifie un personnage pendant qu'il bouge.

Le seul lien entre les deux moitiés : les limites articulaires sont définies en
Python ([`limits.py`](../linen/rigs/limits.py)), testées là-bas, et **générées**
en Luau. Le rig physique ne peut donc pas diverger du rig d'animation.

> **Non exécuté.** Je n'ai pas de moteur Roblox ici. Les modules Luau sont
> écrits et relus, pas testés. La couche de données, elle, l'est (225 tests).
> Prévois une passe de mise au point en Studio.

## Ce que Roblox fournit, et ce qu'il ne fournit pas

La bonne nouvelle d'abord, parce qu'elle a changé récemment :

| Besoin d'Euphoria | Primitive Roblox | État |
| --- | --- | --- |
| IK runtime sur une chaîne | **`IKControl`** — natif, avec `Weight`, `Priority`, `Pole`, `SmoothTime` | Excellent |
| Limites articulaires | `BallSocketConstraint` (cône + twist), `HingeConstraint` (1 axe) | Bon |
| Ressort/amortisseur angulaire | `AlignOrientation` (`Responsiveness`, `MaxTorque`) | Correct |
| Impulsion à un point | `ApplyImpulseAtPosition` | Bon |
| Bascule animation ↔ physique | `Motor6D.Enabled`, `HumanoidStateType.Physics` | Correct |
| Couches haut/bas du corps | Priorités `AnimationTrack` + `AdjustWeight` | Correct |

`IKControl` est la vraie nouveauté : il y a encore peu, il fallait écrire son
propre solveur two-bone. Le module 3 de ton cahier des charges est donc
largement résolu par le moteur.

## Les quatre modules demandés

### Module 1 — Ragdoll actif → [`Ragdoll.luau`](../runtime/Ragdoll.luau)

Fait. Deux points qui séparent une vraie implémentation d'une naïve :

**Les coudes et les genoux sont des charnières, pas des cônes.** Un
`BallSocketConstraint` sur un coude le laisse plier latéralement, et à la
première impulsion il le fera. `HingeConstraint` avec `LowerAngle`/`UpperAngle`
est la primitive correcte, et les données encodent le *type* de contrainte par
articulation, pas seulement ses angles.

**Le drive.** Un `AlignOrientation` par articulation tire l'enfant vers
l'orientation que l'animation aurait produite — cible recalculée chaque frame
depuis `Motor6D.Transform`. C'est ça, « le personnage essaie encore ». La force
du drive est le curseur animé ↔ mou : à 1 le corps encaisse et se redresse, à 0
il s'effondre.

**Le ragdoll partiel** — ce que tu appelles « désactiver partiellement les
animations » — se fait en ne nommant que certaines articulations : une balle
dans l'épaule fait céder le haut du corps pendant que les jambes continuent de
marcher, parce qu'on ne prévient jamais les jambes.

### Module 2 — IK et adaptation au sol → [`FootPlanting.luau`](../runtime/FootPlanting.luau)

Fait, via `IKControl`. Le détail qui compte : **le bassin descend avant que les
pieds soient résolus.** Deux passes. Résoudre les pieds puis baisser les hanches
les décolle immédiatement du sol — c'est l'erreur classique.

Un raycast par pied, la semelle posée sur la normale de la surface, et le
`Weight` de l'IK qui retombe à zéro en l'air. Les pentes au-delà de 50° sont des
murs, pas des sols : on n'y colle pas le pied.

**R15 seulement.** Une jambe R6 est un bloc rigide sans cheville — elle ne peut
pas à la fois atteindre le sol et poser sa semelle à plat. Le module le dit et
refuse, plutôt que de marcher à moitié.

### Module 3 — Inertie et poids → [`Momentum.luau`](../runtime/Momentum.luau)

Fait. Le buste s'incline **contre** l'accélération : en avant quand on
accélère, en arrière quand on freine, penché dans le virage. Tout est lu sur la
vélocité réelle de l'assemblage, jamais sur l'animation en cours — c'est ce qui
le garde juste pendant les transitions, précisément là où le blending lâche.

Appliqué en **multipliant** les `Motor6D.Transform` que l'Animator vient
d'écrire, depuis `PreRender`. Ça se superpose au lieu de se battre.

Ce qui manque : les **petits pas de freinage** que tu décris. Ça, c'est de
l'animation, pas de la procédure — il faut des poses de freinage dans la banque
et une transition pilotée par la décélération. Faisable, pas fait.

### Module 4 — Balance procédurale → [`Balance.luau`](../runtime/Balance.luau)

Fait, avec exactement le test que tu décris : projection du centre de masse dans
le polygone de sustentation. Pour un bipède ce polygone est mince — en gros le
segment entre les deux pieds, élargi de la longueur des semelles — donc c'est
traité comme une capsule autour de ce segment. Quelques produits scalaires par
frame au lieu d'un calcul d'enveloppe convexe, et c'est précis là où ça compte,
c'est-à-dire latéralement.

La sortie n'est pas un booléen mais une **marge en studs**. Branchée sur la
force du drive du ragdoll, le personnage **s'affaisse** en perdant l'équilibre
au lieu de basculer d'animé à mou en une frame.

Le centre de masse est pondéré par les masses réelles, pas pris au
`HumanoidRootPart` : un personnage bras tendus a son centre de masse bien en
avant de ses hanches, et c'est exactement cette différence qui décide s'il
tombe.

## Ce que tu ne rattraperas pas, et pourquoi

Je préfère te le dire nettement plutôt que te laisser le découvrir dans six mois.

**1. La résolution du rig — c'est le vrai plafond.**
R15 a **15 parties et une seule articulation de colonne** (`Waist`). Euphoria
anime une colonne vertébrale articulée sur plusieurs vertèbres, des clavicules,
un cou à deux segments. Une grande partie de ce qui rend une réaction RDR2
lisible — la façon dont le torse se tord en spirale sous un impact — a
littéralement besoin d'articulations que R15 n'a pas. Aucun solveur ne crée des
os manquants. Tu peux contourner avec un personnage custom (`Bone` + mesh
skinné, l'avatar Roblox le permet), mais alors tu quittes R15/R6 et tu perds la
compatibilité avec les avatars des joueurs.

**2. Pas de modèle musculaire.**
Euphoria simule des muscles et un système nerveux simplifié : les articulations
ont un tonus, une fatigue, des temps de réaction. Roblox te donne des corps
rigides et des contraintes. `AlignOrientation` est un analogue grossier du tonus
musculaire — assez pour « il essaie encore », pas pour « il protège sa blessure ».

**3. Le multijoueur — le vrai mur d'ingénierie.**
RDR2 est solo. Euphoria n'a jamais eu à répliquer. Sur Roblox, les parties d'un
ragdoll appartiennent à un client, et cette propriété réseau est *le* problème :
laissée au joueur, la simulation est fluide pour lui et exploitable par lui ;
mise au serveur, elle est autoritaire mais latente pour tout le monde. Le module
expose `setNetworkOwner` et documente le choix, mais **il n'y a pas de bonne
réponse universelle** — c'est un arbitrage par type de personnage. C'est ici que
tu passeras le plus de temps, pas dans les contraintes.

**4. Le budget.**
RDR2 fait tourner Euphoria sur une poignée de personnages à la fois. Vingt
ragdolls actifs simultanés sur Roblox, avec un `AlignOrientation` par
articulation, coûtera très cher. Prévois un budget : les N plus proches en
ragdoll actif, les autres en ragdoll passif ou en animation.

## L'objectif réaliste

Avec ces quatre modules, tu es **très largement au-dessus du Roblox standard** —
pieds ancrés sur le relief, réactions aux impacts localisées, perte d'équilibre
progressive, inertie visible. Ça place ton jeu dans le haut du panier de la
plateforme.

Tu n'auras pas la parité RDR2, et la raison principale n'est ni ton code ni le
moteur : c'est qu'un R15 a quinze blocs et une articulation de colonne. Viser
« le meilleur mouvement de personnage sur Roblox » est atteignable. Viser
« Euphoria » ne l'est pas tant que tu restes sur R15/R6.

## Installation

```bash
python -m linen.export.luau runtime/RigLimits.luau   # après toute modif des limites
```

Copier `runtime/` dans `ReplicatedStorage.Linen`, puis :

```lua
local Linen = require(ReplicatedStorage.Linen)
local body = Linen.attach(character)

body:hit(character.RightUpperArm, direction * 900, hitPosition, {
    "RightShoulder", "RightElbow", "Waist", "Neck",
})
```

L'ordre par frame, qui n'est pas devinable :

1. l'Animator écrit la pose ;
2. `Momentum` incline la colonne par-dessus (`PreRender`) ;
3. `FootPlanting` résout les jambes au sol (`PreRender`, après) ;
4. la physique avance, le drive du ragdoll tourne (`PreSimulation`) ;
5. `Balance` lit où le corps a atterri (`PostSimulation`).

Inverser 2 et 3 est l'erreur classique : incliner après avoir posé les pieds
les redécolle.
