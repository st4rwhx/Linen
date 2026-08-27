# Comment ils font les animations de fou — et où on se trompait

Recherche faite en août 2026 : NoCapMocap, l'état de l'art de la mocap depuis
vidéo, les licences, et ce que font vraiment les animateurs Roblox.

---

## 1. Ce que fait NoCapMocap

Deux entrées, une sortie.

| | |
| --- | --- |
| **Texte** | tu décris en anglais, il génère **quatre variantes**, tu prévisualises, tu appliques |
| **Vidéo** | tu filmes au téléphone, l'IA convertit en R15 — **markerless**, sans combinaison ni studio (beta) |
| **Sortie** | mouvement R15 natif, ou FBX pour Mixamo / Unity / Unreal / Blender |
| **Livraison** | un plugin Studio gratuit, **Motion Lab**, qui applique l'animation sur ton rig |
| **Modèle** | crédits, packs ou abonnement |

Regarde la structure : **un plugin Studio + un service qui génère + une
application directe sur le rig.** C'est exactement l'architecture qu'on a
reconstruite ici — relevé de place, génération, publication en `rbxassetid://`.
La différence n'est pas l'architecture. C'est **d'où vient le mouvement.**

## 2. Pourquoi leur mocap vidéo est bonne, et pourquoi on ne peut pas la copier

L'état de l'art pour « une vidéo au téléphone → mouvement 3D » s'appelle
**HMR** (human mesh recovery) : WHAM, TRAM, GVHMR, et en 2026 DanceHMR,
OnlineHMR, MoCapAnything. Ils combinent estimation du mouvement de caméra
(SLAM) et transformeurs vidéo, et ils sont **très bons**.

Ils reposent tous sur le même modèle de corps : **SMPL**, du Max Planck
Institute. Et sa licence dit :

> droit d'usage pour la **recherche non commerciale**, l'éducation non
> commerciale ou les projets artistiques non commerciaux. Tout autre usage,
> **en particulier commercial, est interdit** — y compris l'incorporation dans
> un produit commercial ou un service commercial.

Elle interdit même d'**entraîner** un modèle pour un usage commercial.

**C'est le vrai mur, et il n'est pas technique.** Le code est public, il marche,
et tu n'as pas le droit de t'en servir pour un jeu que tu vends. Un service
comme NoCapMocap peut payer une licence commerciale (le Max Planck en vend, via
Meshcapade) ; toi tout seul, non.

**Donc : cette technologie s'achète, elle ne se reconstruit pas.** Chercher à la
refaire dans Linen, c'était le mauvais combat depuis le début.

## 3. Ce qui fait vraiment une cinématique Roblox impressionnante

Trois choses différentes qu'on mélangeait, et une seule est de l'animation de
corps.

### a) La qualité du mouvement — se résout par la mocap
CMU, Mixamo, un service, ta propre vidéo. Personne n'anime un cycle de course à
la main en 2026.

### b) Le contact — se fait à la main, toujours
Qu'une main se ferme sur *ce col*, qu'un dos touche *ce mur*. Aucune capture de
bibliothèque ne le sait : une capture est **solo et générique**. Ça se règle
dans Moon Animator, image par image. Y compris chez les gros.

### c) La présentation — c'est la moitié de l'effet, et ce n'est pas de l'animation
C'est ce que tout le monde sous-estime. Ce que disent les guides d'animateurs
Roblox, mot pour mot :

- **La caméra fait le coup.** « Une bonne caméra peut rendre une attaque
  beaucoup plus puissante. » Et l'easing compte : `Sine`, `Cubic`, `Quint`,
  `OutQuad`, `InOutSine` — pas `Linear`. « Un rendu film hollywoodien plutôt
  qu'une caméra de surveillance. »
- **Sans son, c'est vide.** « Une cinématique sans son paraît vide. »
- **Les VFX** — particules, explosions, correction colorimétrique.

**Linen fait déjà (c).** Plans avec focale, fondu et dérive, coupes ancrées aux
temps, marqueurs de son à l'image près, feuille de spotting. C'est la partie où
on est *bons*.

---

## 4. Où on se trompait

On essayait de faire de Linen un **générateur de mouvement**. C'est son plus
mauvais métier : douze verbes dessinés à la main, contre 2548 captures studio
gratuites ou un service à quelques centimes le clip.

Le vrai métier de Linen, c'est l'**assemblage** — et là il n'a pas de
concurrent :

| Ce que Linen fait que personne d'autre ne fait | |
| --- | --- |
| Plusieurs acteurs sur **une** timeline | des cues ancrés les uns aux autres, retimables |
| Mise en scène **dans ta place réelle** | `linen survey` lit tes rigs et ton décor |
| Caméra, son, props, visages | ancrés aux temps, pas à l'horloge |
| Publication en masse | `rbxassetid://` sans ouvrir Studio, avec manifeste |
| R6 → R15 | vérifié à 10⁻⁶ |
| Mesure de la finition | patinage des pieds en studs, boucle par mesure |

Un service génère **un clip**. Il ne monte pas une scène à deux personnages
dans ton décor, avec la caméra qui coupe au bon moment.

## 5. Le changement qui débloque tout

**Une bibliothèque Linen indexe maintenant les animations Roblox finies.**

```bash
linen library build mes_animations/ -o mienne.json   # .rbxmx, .rbxm, .bvh, .dae
linen scene ma_scene.json --library mienne.json -o cinematique
```

Vérifié sur les animations converties de ton propre jeu :

```
bibliotheque: 17 captures
    0.00s  Rig   a   crouch move  [library:CrouchMove]
    0.80s  Rig   b   swim         [library:Swim]
```

Ce que ça veut dire : **tout devient une brique de scène.**

- Un clip acheté à NoCapMocap → appliqué sur un rig → exporté → indexé.
- Un Mixamo importé dans Studio et réenregistré.
- Un plan que tu as animé toi-même dans Moon Animator.
- Tes 17 animations de jeu existantes.
- CMU, Mixamo en `.dae` direct.

Linen n'a plus besoin d'être bon pour **inventer** le mouvement. Il doit être
bon pour l'**arranger**, et il l'est.

---

## Le plan, dans l'ordre

| | Ce que ça coûte | Ce que ça change |
| --- | --- | --- |
| **1.** CMU, une soirée de `curl` | 0 € | 12 verbes dessinés → 2548 mouvements réels ([`BIBLIOTHEQUE.md`](BIBLIOTHEQUE.md)) |
| **2.** Tester NoCapMocap sur **un** clip de bagarre | quelques crédits | tu sais en dix minutes si ça vaut le coup, sans rien reconstruire |
| **3.** Indexer tout dans une bibliothèque | une commande | tes scènes piochent dedans automatiquement |
| **4.** Ta propre vidéo | deux caméras | le geste exact que personne n'a capturé |
| **5.** Contact et derniers centimètres | à la main | `--moon`, et c'est ce que font les gros aussi |

**Ce qu'il ne faut pas faire** : réimplémenter WHAM ou SMPL. C'est illégal pour
un jeu commercial, et ça ne réglerait ni le contact ni la présentation.

---

## 6. Le choix : ne dépendre de personne

Ce que j'avais écrit ici — « teste NoCapMocap pour 9 $ » — mélangeait deux
choses qui n'ont rien à voir.

**Se procurer du mouvement n'est pas une dépendance.** CMU, c'est 2548 captures
que tu **télécharges et que tu possèdes**, gratuites y compris commercialement,
qui ne peuvent plus t'être retirées. Mixamo pareil. Un abonnement, si.

Et j'avais tort sur un point de fait : j'ai écrit que la mocap depuis vidéo
« s'achète, elle ne se reconstruit pas ». **C'est vrai seulement de la branche
SMPL.** MediaPipe est en **Apache 2.0**, utilisable commercialement sans
restriction, il sort des points 3D — et Linen le lit déjà, c'est le chemin
FreeMoCap d'origine. MMPose est aussi en Apache 2.0. Il y a donc une route
vidéo → mouvement qui est **libre, auto-hébergeable et à nous**. Elle est moins
précise que WHAM. Elle est légale, et elle ne s'arrête pas si quelqu'un ferme
boutique.

| | Possédé ? | Prix | Ce que ça règle |
| --- | --- | --- | --- |
| **CMU** | oui, pour toujours | 0 € | 2548 mouvements réels |
| **Mixamo** | oui, les fichiers sont à toi | 0 € | combat, armes |
| **Ta vidéo → MediaPipe** | oui, tout le code est à nous | 0 € | le geste exact que personne n'a capturé |
| **Contact solvé par Linen** | oui, c'est notre code | 0 € | **ce que personne ne vend** |
| Service par abonnement | non | 9-79 $/mois | rien qu'on ne puisse faire autrement |

## 7. Ce qui rend Linen meilleur qu'eux — et c'est fait

Un service génère **un clip d'une personne seule**. C'est structurellement
incapable de savoir que *cette* main doit se fermer sur *ce* col, d'un
personnage de *cette* taille, debout *là*. L'information n'est dans aucun clip,
à aucun prix.

Elle est dans la **scène** : Linen sait où sont les deux corps, comment ils
regardent, et où est chaque articulation à chaque image. Il ne manquait que la
dernière étape — plier le bras pour que la main arrive.

`linen scene` la fait maintenant :

```json
{ "kind": "contact", "actor": "Hero", "cue": "plaque", "offset": 0.05,
  "limb": "RightHand", "target_actor": "Enemy", "target_part": "UpperTorso",
  "hold": 0.5 }
```

```
8 contacts resolus dans l'animation :
  Hero.LeftHand  -> Enemy.RightLowerArm [3.23-3.68s] atteint
  Hero.RightHand -> Enemy.UpperTorso    [3.78-4.28s] atteint
  Enemy.RightHand -> Hero.Head          [2.37-2.49s] a 0.85 stud pres
```

C'est la même IK deux-os analytique que la pose des pieds, pointée sur un bras :
plier le coude pour mettre le poignet à la bonne distance, puis orienter le bras
entier. Le coude plie dans le plan que la pose indique déjà, pas dans un plan
décrété — un coude à l'envers se voit immédiatement.

**Et ce qui ne peut pas être atteint est mesuré, pas caché.** Un bras Roblox a
une longueur fixe ; l'étirer n'est pas une option. Alors la main va aussi loin
qu'elle peut et le manque est rapporté **en studs**, comme le patinage des pieds
et la boucle. « À 0,85 stud près » te dit de rapprocher les acteurs ou de viser
plus bas. Un service, lui, te rend un clip qui a l'air bien et rate la cible en
silence.

## Ce qui reste un vrai chantier de code, si un jour on le veut

**Un solveur IK avec conscience des collisions.** C'est la seule chose de cette
page que personne ne vend et qu'aucune bibliothèque ne remplace : faire qu'un
geste générique atterrisse *sur* un autre personnage, à *sa* taille, contre *ce*
mur. C'est difficile — et c'est aussi la seule chose qui rendrait Linen
meilleur qu'un animateur qui bosse à la main, au lieu de simplement plus rapide.
