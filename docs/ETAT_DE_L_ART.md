# Ce qui est caché, ce qui ne l'est pas, et ce que ça change

Recherche : forums Roblox, GitHub, articles, dumps d'API communautaires.

La demande était de chercher ce qui est gardé secret par de petits groupes et
qui aurait fuité. Réponse en deux temps, et les deux comptent.

---

## 1. D'abord, la mauvaise nouvelle sur les fuites

**Le code source propriétaire qui a réellement fuité ne t'est d'aucune
utilité.** Pas pour une raison morale — pour une raison pratique qui te
concerne directement :

Tu sors un jeu. Du code ou des assets issus d'une fuite dans un jeu publié,
c'est une violation de copyright caractérisée, et sur Roblox ça se termine par
un retrait du jeu et un bannissement du compte. Tu ne peux pas expédier ça.
Tout le travail au-dessus tombe avec.

Donc ce n'est pas une piste. Ce n'en est pas une même si personne ne regardait.

---

## 2. Et maintenant la bonne : **l'essentiel n'est pas caché**

C'est le renversement utile de cette recherche. Ce que tu imagines gardé par de
petits groupes discrets est en fait **publié, gratuit, et signé**.

- **Ubisoft La Forge** publie sa recherche en accès libre. Le motion matching,
  l'apprentissage de contrôleurs, le *learned motion matching* : articles,
  vidéos, et souvent **le code**.
- **Daniel Holden** (Ubisoft) tient [theorangeduck.com](https://theorangeduck.com)
  et y donne les formules et les implémentations complètes — inertialisation,
  dead blending, ressorts. La formule que Linen utilise vient de là.
- **La GDC** met ses conférences techniques en ligne. « Inertialization:
  High-Performance Animation Transitions in *Gears of War* » est une conférence
  publique.
- **Unreal Engine** est *source-available*. Le système d'animation d'un moteur
  AAA est lisible.

Le vrai obstacle n'est pas l'accès. C'est que **c'est illisible sans contexte,
et personne ne le traduit**. Ce qui ressemble à un secret est presque toujours
un article de 2018 que personne n'a relié à ton problème.

---

## 3. La chose la plus proche d'une fuite — et elle est légitime

**Le dump d'API Roblox.**

Roblox publie une documentation. Il expose aussi, dans son client, une surface
d'API bien plus large que ce que la documentation décrit, et la communauté en
maintient un miroir mis à jour à chaque version (le *Roblox-Client-Tracker*).

Ce n'est pas une fuite : c'est ce que le client déclare lui-même. Mais ça
montre ce que Roblox construit **avant** que ce soit documenté, et ça vient de
nous apprendre plus que toute la documentation officielle.

Voilà ce qu'il contient et qui nous concerne.

### 3.1 Animation Graphs — sorti de beta le 15 juillet 2026

C'est l'AnimGraph d'Unreal, en natif, et c'est **récent**.

| Nœud | Ce que ça fait |
| --- | --- |
| `Blend1D` / `Blend2D` | Blend spaces — mélange marche/course selon la vitesse |
| `Select` / `PrioritySelect` | Machines à états |
| `Over` / `Add` / `Subtract` | Superposition, poses additives |
| `Mask` | Par articulation — saluer du haut du corps en marchant |
| `Sequence` / `RandomSequence` | Enchaînements, variantes pondérées |
| `Speed` | Vitesse de lecture |

Piloté depuis Luau par **`AnimationTrack:SetParameter("WalkSpeed", 16)`**, et
**les paramètres se répliquent tout seuls**. C'est exactement le RTPC dont on
parlait pour le son, appliqué au mouvement.

### 3.2 Trois choses dans le dump que la doc ne dit pas

**`Enum.AnimationNodeTransitionType` = `CrossFade`, `InertialBlend`,
`DeadBlend`.**

Le moteur fait **l'inertialisation nativement**. Exactement ce que j'ai
implémenté en Python la semaine dernière. Ça ne rend pas notre version inutile
— la nôtre travaille hors-ligne, sur le fichier, avant l'export — mais ça veut
dire qu'au *runtime* on n'a pas à la réécrire : il y a un nœud pour ça.

**`Enum.AnimationNodePhaseSync` = `Synced` / `Unsynced`.**

Le mélange **synchronisé en phase**. C'est le détail qui fait qu'un fondu
marche→course ne fait pas patiner les pieds : les deux cycles sont alignés sur
leur phase avant d'être mélangés. C'est une technique AAA classique, et elle
est là, dans une enum non documentée.

**`AnimationFromVideoCreatorService`.**

```
Function AnimationFromVideoCreatorService:FullProcess(videoFilePath, progressCallback)
Function AnimationFromVideoCreatorStudioService:ImportVideoWithPrompt()
```

**Roblox construit de la mocap depuis une vidéo, dans le client.** Verrouillé
`{🔒RobloxScript}` — seuls les scripts internes de Studio peuvent l'appeler —
donc soit c'est une fonctionnalité Studio déjà là, soit elle arrive.

Ça te concerne directement : tu as un téléphone. En attendant, des plugins
tiers font déjà exactement ça (Motion Lab de NoCapMocap, DeepMotion Animate 3D)
avec import R15 en un clic.

### 3.3 Le vrai gatekeep, et il est technique

Peut-on **générer** un Animation Graph depuis Linen, comme on génère un
`KeyframeSequence` ?

La structure dit oui :

```
Class AnimationGraphDefinition : AnimationClip     <- même famille que KeyframeSequence
Class AnimationNodeDefinition : Instance
    Property AnimationNodeDefinition.NodeType: Enum.AnimationNodeType
    Property AnimationNodeDefinition.InputPinData: BinaryString [Hidden] [NotScriptable]
    Property AnimationNodeDefinition.NodeId: string {🔒RobloxScript}
    Function AnimationNodeDefinition:AddInputPin(pin) {🔒RobloxScript}
```

Et la réalité dit non, pour l'instant : **les connexions entre nœuds sont dans
`InputPinData`, un `BinaryString` caché, non scriptable, de format non
documenté**, et toutes les fonctions qui le manipulent sont réservées aux
scripts Roblox.

Voilà le seul vrai verrou de toute cette recherche. Il est franc : ce n'est pas
un secret gardé, c'est une API pas encore ouverte. Elle s'ouvrira probablement
— le reste de la classe est public.

---

## 4. Ce que ça change pour nous

| Trouvaille | Effet |
| --- | --- |
| Animation Graphs en natif | Les modules `runtime/` (locomotion, superposition) ont un équivalent moteur, répliqué et performant |
| `InertialBlend` natif | Notre inertialisation reste utile hors-ligne ; au runtime, ne pas la réécrire |
| `PhaseSync` | La solution au patinage des pieds en mélange marche/course existe |
| `InputPinData` verrouillé | Générer un graphe depuis Linen : **pas possible aujourd'hui** |
| Vidéo → animation | Ton téléphone devient une source de mocap, via plugin tiers dès maintenant |
| `CurveAnimation` | Un second format d'animation à côté de `KeyframeSequence` — à évaluer |
| `KeyframeSequenceProvider` | **Non déprécié** — ce que le lecteur de scène utilise reste valide |

---

## 5. Ce qu'il faut retenir

La question était : que gardent-ils pour eux ?

La réponse honnête, après avoir cherché : **presque rien.** Ubisoft publie,
Epic ouvre son code, la GDC diffuse, Roblox déclare son API. Ce qui manque
n'est pas l'information, c'est quelqu'un pour la relier à ton problème
précis — et c'est exactement le travail qu'on fait ici.

Le seul vrai verrou trouvé est une API Roblox pas encore ouverte, et attendre
son ouverture coûte moins cher que de la contourner.
