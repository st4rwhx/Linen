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

## 6. Le choix, avec les chiffres

Relevé en août 2026, prix et licences vérifiés à la source.

| | Prix | Licence commerciale | Sortie | Ce que ça règle |
| --- | --- | --- | --- | --- |
| **CMU** | **gratuit** | oui, explicitement, y compris commercial | `.bvh` | 2548 mouvements réels. Le socle. |
| **NoCapMocap** | **9 $/mois** (50 crédits ≈ 50 s), 29 $ (250), 79 $ (1000). Packs à partir de 7 $ / 25 crédits | **oui — « you may use generated animation files in personal and commercial projects »**, et tu restes propriétaire | R15 natif + FBX | Texte → mouvement, et vidéo → mouvement (beta, 20 s max, une personne) |
| **Mixamo** | gratuit | oui, illimité ; interdiction de redistribuer les fichiers bruts | `.dae` | Combat, armes, morts stylisées |
| **Cascadeur** | **12 $/mois** indie (< 100 k$ de revenus/an) ; version gratuite non commerciale | oui sur les plans payants | **`.dae`**, FBX | **Le contact.** AutoPosing, AutoPhysics, ragdoll, inbetweening IA |
| **WHAM / TRAM / GVHMR** | gratuit | **NON** — SMPL interdit tout usage commercial | — | rien qu'on ait le droit d'utiliser |

**Le détail qui compte** : NoCapMocap facture **1 crédit par seconde générée** et rend
**quatre variantes** pour ce crédit. La scène `Contre` fait 7,45 s à deux acteurs,
soit ~15 s de mouvement — **le plan à 9 $ la couvre trois fois**, ratés compris.

Et Cascadeur exporte du **`.dae`**, que le lecteur Collada d'ici lit déjà. Une
pose corrigée à la main dans Cascadeur entre dans une bibliothèque Linen sans
conversion. *(Non testé de bout en bout : le format est standard, mais personne
ici n'a fait tourner Cascadeur.)*

### La recommandation

1. **CMU ce soir.** Gratuit, définitif, sans risque. C'est le plancher.
2. **NoCapMocap Starter, un mois, 9 $.** C'est le seul moyen de savoir si leur
   qualité vaut le coup, et ça coûte moins qu'une pizza. Tu restes propriétaire
   et l'usage commercial est écrit noir sur blanc.
3. **Cascadeur seulement si le contact te gêne encore.** C'est le seul outil de
   toute cette page qui attaque ce problème — et le contact, c'est justement
   toute ta scène de bagarre.

**Coût pour savoir : 9 $.** Pas un chantier de six mois.

## Ce qui reste un vrai chantier de code, si un jour on le veut

**Un solveur IK avec conscience des collisions.** C'est la seule chose de cette
page que personne ne vend et qu'aucune bibliothèque ne remplace : faire qu'un
geste générique atterrisse *sur* un autre personnage, à *sa* taille, contre *ce*
mur. C'est difficile — et c'est aussi la seule chose qui rendrait Linen
meilleur qu'un animateur qui bosse à la main, au lieu de simplement plus rapide.
