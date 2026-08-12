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
> écrits et relus, pas testés. La couche de données, elle, l'est (240 tests).
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

## Comment s'en approcher quand même

Le plafond est réel, mais il porte sur *l'articulation*. Or l'essentiel de ce
qui rend un personnage Rockstar vivant n'est pas de l'articulation — c'est du
**timing entre articulations**, et ça ne coûte rien. Cinq leviers, du plus
rentable au moins.

### 1. Le drag — le meilleur rapport qualité/effort de tout le projet

[`Secondary.luau`](../runtime/Secondary.luau) fait traîner chaque articulation
derrière son parent. La main arrive après l'avant-bras, qui arrive après le
bras. C'est le principe d'animation de l'**overlapping action**, celui qui
sépare une animation faite à la main d'une interpolation — et l'appliquer
procéduralement fait qu'un clip banal se met à ressembler à du travail
d'animateur.

Ça marche sur **n'importe quel R15**, y compris l'avatar d'un joueur, sans
aucun os supplémentaire. Si tu ne dois retenir qu'une chose de ce document,
c'est celle-là.

### 2. Les ondes d'impact — la signature Euphoria, sans physique

Un coup ne déplace pas tout le corps d'un coup : la perturbation **part du
point de contact et voyage** vers l'extérieur, arrivant plus tard et plus
faible à chaque articulation. C'est ça qu'on reconnaît dans RDR2.

`Secondary:impact()` le fait de façon purement procédurale — donc ça fonctionne
aussi sur un personnage que tu ne veux **pas** passer en ragdoll, et ça arrive
sur la même frame au lieu d'attendre que la physique se stabilise. L'axe de
rotation est perpendiculaire à la poussée : un coup de face fait tanguer, un
coup de côté fait rouler. Prendre l'axe de la poussée elle-même ferait pivoter
le personnage autour de l'axe du coup, ce qui n'arrive jamais à un corps.

### 3. Le regard

Les personnages Euphoria regardent ce qui les menace, et **la tête précède le
corps**. `Secondary:lookAt()` répartit la rotation entre la tête et le buste,
avec des butées — une tête qui continue de tourner au-delà de sa limite est
l'artefact « cou de hibou » classique. Rien n'achète autant d'intelligence
perçue par ligne de code.

### 4. Le patinage : ce n'est pas un problème d'animation

C'est de l'arithmétique. Un cycle de marche parcourt une distance précise par
tour — et si la vitesse du personnage n'est pas celle-là, les pieds **doivent**
glisser, quelle que soit la qualité du clip.

Linen calcule cette distance **par cinématique directe sur les poses**
([`stride.py`](../linen/generate/stride.py)) plutôt que de la déclarer à la
main : élargis une pose de contact et la foulée suit toute seule. Le chiffre
part dans `MotionData.luau`, et [`Locomotion.luau`](../runtime/Locomotion.luau)
joue le clip à `vitesse_réelle / vitesse_naturelle`.

| Cycle | Foulée | Vitesse naturelle |
| --- | --- | --- |
| `walk` | 7,77 studs | 7,0 studs/s |
| `run` | 11,88 studs | 19,0 studs/s |

Le même module mélange idle/marche/course par **poids continus fonction de la
vitesse** — pas de machine à états, donc pas de transition à déclencher ni dans
laquelle rester coincé.

### 5. Et si tu contrôles le modèle : des vraies vertèbres

Pour les PNJ, tu n'es pas obligé de rester sur R15. Roblox supporte les
personnages **skinnés avec des instances `Bone`**, `IKControl` accepte les
`Bone` comme cibles, et — le point important — **une animation R15 peut piloter
un personnage à os supplémentaires** tant que les os correspondants sont
orientés comme les Motor6D d'origine.

Donc : un PNJ avec trois vertèbres au lieu d'une, qui rejoue tes animations
R15 existantes, avec la torsion de colonne ajoutée procéduralement par-dessus.
C'est le seul chemin qui lève réellement le plafond — mais il ne s'applique pas
aux avatars des joueurs, qui arrivent en R15 standard.

## L'objectif réaliste

Avec ces six modules, tu es **très largement au-dessus du Roblox standard** —
pieds ancrés sur le relief, zéro patinage, réactions aux impacts qui se
propagent, regard qui suit, perte d'équilibre progressive, inertie visible.
Ça place ton jeu dans le haut du panier de la plateforme.

Et il faut voir d'où vient le gain : les modules physiques (ragdoll, équilibre)
coûtent cher et servent aux moments forts, alors que le **drag, les ondes
d'impact et le regard sont presque gratuits et tournent en permanence**. C'est
ce deuxième groupe qui fait le plus pour l'impression générale.

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
