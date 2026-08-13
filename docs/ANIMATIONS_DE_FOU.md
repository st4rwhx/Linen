# Comment obtenir des animations de fou juste avec un prompt

Recherche complète, et la conclusion qui en sort. Ce document répond à une
question précise : **comment passer d'une phrase à une animation qui a l'air
capturée**, pour un jeu Roblox que tu vends.

La réponse courte, en une ligne : **on n'invente pas le mouvement, on le
choisit.** Et le tri est fait par la licence avant d'être fait par la qualité.

---

## 1. La génération de mouvement par IA existe vraiment

Ce n'est pas du marketing. L'état de l'art 2026 :

| Modèle | Ce que c'est |
| --- | --- |
| **MDM** (Motion Diffusion Model) | Le premier à poser le sujet, diffusion sur le mouvement |
| **MoMask** | Tokens de mouvement quantifiés en résidus + transformer masqué. Bat la diffusion en qualité et en fidélité au texte |
| **MoMask++ / SnapMoGen** (Snap, 2025) | État de l'art actuel, entraîné sur des textes **longs** — 48 mots en moyenne |
| **MoGeFlow, MoScale** (2026) | Suites, gains incrémentaux |

Deux choses que j'ai vérifiées et qui comptent :

- **MoMask tourne sur CPU.** Sa démo web est explicitement décrite comme
  tournant sans GPU. Pas besoin d'une carte graphique.
- **MoMask sort du BVH directement.** C'est exactement le format que
  `linen bvh` lit déjà. Le pont existe.

Et SnapMoGen répond précisément à ton besoin : 20 000 clips, 44 heures, 122 000
descriptions de 48 mots en moyenne — contre 12 mots pour l'ancien standard.
C'est fait pour les prompts détaillés, ceux que tu écris.

**Donc techniquement, prompt → animation de qualité, sur ton PC, sans GPU :
c'est possible aujourd'hui.**

---

## 2. Et c'est là que ça bloque : les licences

J'ai lu les licences plutôt que de supposer. Toutes.

| Ressource | Licence | Utilisable dans ton jeu ? |
| --- | --- | --- |
| **AMASS** | Recherche académique, non commercial | ❌ |
| **HumanML3D** | Dérivé d'AMASS, non commercial | ❌ |
| **SnapMoGen** | *Snap Inc. Non-Commercial License* | ❌ |
| **MoMask (code)** | MIT | ✅ le code — mais il ne sert à rien seul |
| **MoMask (poids)** | Entraînés sur HumanML3D | ❌ en pratique |

La licence Snap est sans ambiguïté :

> « The sample code and dataset in this repository are made available by Snap
> Inc. for **non-commercial, research purposes only**. Non-commercial means not
> intended for or directed towards commercial advantage or monetary
> compensation. »

Et AMASS renvoie vers `ps-licensing@tue.mpg.de` pour toute utilisation
commerciale.

**Traduction : toute la pile académique du text-to-motion est fermée pour un
jeu que tu vends.** Le modèle est gratuit, les poids sont téléchargeables, et
les utiliser pour ton jeu serait quand même une violation de licence. C'est le
genre de chose qui ne se voit pas avant qu'elle coûte cher.

> Les API payantes (DeepMotion SayMotion et compagnie) sont une autre voie :
> elles vendent justement des droits. Vérifie leurs CGU avant de t'engager, je
> n'ai pas trouvé de réponse claire publiquement.

---

## 3. Ce qui est réellement utilisable

Deux ressources, et elles sont énormes.

### CMU Graphics Lab Motion Capture Database

**2548 mouvements**, capturés en studio, et son propre README dit :

> « **Use this data!** This data is free for use in **research and commercial
> projects worldwide**. »

Trois choses que j'ai vérifiées en la téléchargeant :

1. **Elle est déjà en BVH** (conversion cgspeed / Bruce Hahne).
2. **Ses noms d'articulations sont ceux de Mixamo** — `Hips`, `LeftUpLeg`,
   `LeftLeg`, `LeftFoot`, `LeftArm`, `LeftForeArm`… donc `linen bvh
   --skeleton mixamo` la lit **sans une ligne de code en plus**. Testé.
3. **Elle est livrée avec un index texte** : `cmu-mocap-index-text.txt`, 2435
   lignes du genre `09_02<TAB>run` ou `01_03<TAB>playground - climb, hang,
   swing`. C'est-à-dire : **un jeu de données texte→mouvement, utilisable
   commercialement**. C'est exactement ce que la recherche prétend fournir et
   qu'elle ne peut pas te donner.

Attention à la nuance : AMASS *contient* CMU, mais repackagé sous licence
restrictive. La base CMU d'origine a sa propre licence permissive. C'est
l'originale qu'il faut prendre.

### Mixamo

Adobe, gratuit avec un compte, **libre de droits pour un usage commercial
illimité**, environ 2500 animations professionnelles. Tu peux les livrer dans
un jeu fini ; tu ne peux pas les revendre en pack. Adobe ne le maintient plus
activement, mais il fonctionne.

---

## 4. La méthode : ce que font les vrais studios

Point important qui recadre tout : **aucun studio AAA ne génère du mouvement.**
Ni Rockstar, ni Naughty Dog, ni Ubisoft. Ils enregistrent des milliers de clips
et construisent un **système de sélection** par-dessus.

C'est le **motion matching**, inauguré par Ubisoft sur *For Honor* et
aujourd'hui partout. Le principe : au lieu d'une machine à états qui choisit
une animation par son nom, on décrit des **contraintes** (trajectoire voulue,
vitesse, pose actuelle) et le système va chercher, dans toute la base, la frame
qui y répond le mieux. Les raccords se rattrapent par **inertialisation** — une
technique de *Gears of War 4* où l'on ne mélange pas deux animations mais où
l'on reporte la vitesse et l'accélération du moment de la transition, qu'on
laisse décroître :

```
offset(t) = e^(−y·t) · (x + (v + x·y)·t)
```

Autrement dit : la qualité AAA ne vient pas d'un générateur. Elle vient d'une
**bibliothèque** plus d'un **choix** plus des **raccords propres**.

C'est reproductible. Et ça n'a aucun problème de licence. **C'est fait** — voir
la section suivante.

### Les raccords, mesurés

Une phrase à trois temps, c'est trois clips, et les raccords sont tout le
problème : coupé net, le personnage se téléporte d'une pose à l'autre.

Mesuré sur de vraies captures CMU, coupées course → marche → coup de poing,
en degrés parcourus sur l'image la pire du raccord :

| | pic (°/image) | aire |
| --- | --- | --- |
| concaténation brute | 109,8 / 61,5 | 442 / 171 |
| inertialisation | 32,8 / 29,8 | 344 / 125 |
| **+ choix du point d'entrée** | **3,5 / 2,3** | **89 / 66** |

Le mouvement ordinaire dans ces clips fait environ **3,4 °/image**. La dernière
ligne est donc un raccord qu'on **ne peut pas voir**.

Et la leçon est dans l'écart entre les deux dernières lignes : le ressort compte
beaucoup moins que le fait de **ne pas couper sur une mauvaise pose**. C'est
exactement ce que dit le motion matching, et c'est la partie qu'on rate en le
résumant à « du blending intelligent » : il ne s'agit pas de mélanger mieux, il
s'agit de **ne pas avoir à mélanger**. On cherche dans le clip entrant l'image
qui ressemble déjà à la pose sortante, et on démarre là.

```bash
linen prompt "il court vite puis il marche et il donne un coup de poing" \
     --library cmu.json -o build/phrase.rbxmx
# 'il court vite'             -> 02_03: run/jog
# 'il marche'                 -> 02_01: walk
# 'il donne un coup de poing' -> 02_05: punch/strike
#   raccord a 1.45s : 3.5 deg/frame
#   raccord a 3.05s : 4.8 deg/frame
```

---

## 5. Ce que j'ai construit

`linen library` : Linen indexe une bibliothèque de mocap, et un prompt y pioche.

```bash
# 1. indexer (une fois)
linen library build ~/cmu/data -o cmu.json \
     --descriptions ~/cmu/cmu-mocap-index-text.txt

# 2. chercher
linen library search cmu.json "il court vite puis saute"

# 3. sortir l'animation Roblox
linen prompt "coup de poing" --library cmu.json -o build/punch.rbxmx
```

### Ce qui rend la recherche utile

**Les mots, en français et en anglais.** Toutes les bibliothèques utilisables
sont étiquetées en anglais ; tes prompts sont en français. Sans table de
synonymes, `marche` ne trouve aucun des 506 clips décrits `walk` — la recherche
rend zéro résultat en étant assise sur exactement ce qu'on lui demande. La table
part des mots-clés bilingues du planificateur hors-ligne, puis couvre le
vocabulaire réellement présent dans l'index CMU.

**Et ce que le clip *fait*, mesuré.** Une description dit « walk ». Elle ne dit
pas à quelle vitesse, ni si les pieds décollent, ni si ça tourne. Linen
retargette chaque clip une fois et le mesure :

| Mesuré | Ce que ça vaut |
| --- | --- |
| `travel` | Hauteurs de hanche parcourues par seconde |
| `steps_per_second` | Cadence, par le bas de course de la semelle |
| `airborne` | Les deux pieds quittent le sol ensemble |
| `bob` | Montée/descente du bassin |
| `reach` | Jusqu'où la main passe devant le torse |
| `turn` | Degrés tournés sur la durée |

Ce qui donne, sur les vraies données CMU :

```
02_01  walk           travel=1.37  air=0
02_03  run/jog        travel=3.01  air=1
09_02  run            travel=3.90  air=1
02_07  swordplay      travel=0.16  air=0
02_10  wash self      travel=0.16  air=0
```

**Le contrôle qui valide tout ça** : marcher à 1,37 hauteur de hanche/s et
courir à 3,9, pour une hanche à 0,9 m, ça fait 1,2 m/s et 3,5 m/s. Ce sont les
chiffres de la biomécanique humaine. La mesure mesure la bonne chose.

C'est ce qui permet à « marche **lentement** » de ne pas répondre par le clip le
plus rapide qui partage un mot.

### Deux corrections que les vraies données ont imposées

**Le décollage ne se mesure pas sur le clip exporté.** L'export ne contient que
des rotations, donc la hanche y est clouée : dans le clip, une course ne quitte
jamais le sol. Mesuré là, *toutes* les courses CMU sortaient « jamais en
l'air », et toutes les prises longues sortaient « toujours en l'air ». Le vol
est réel, il est juste dans la capture d'origine, pas dans le clip. Mesuré
depuis la capture, c'est juste.

**Les unités des fichiers mentent.** Les BVH CMU placent les hanches à 0,16 de
je-ne-sais-quelle unité. Tout est donc divisé par la hauteur de hanche du sujet
lui-même. Les ratios survivent ; les valeurs absolues non.

---

## 6. Où on en est, honnêtement

| | |
| --- | --- |
| Lire du BVH CMU / Mixamo → animation Roblox | **Fait et testé** |
| Indexer une bibliothèque et la mesurer | **Fait et testé** |
| Prompt FR → vrai clip mocap → `.rbxmx` + `.html` | **Fait et testé** |
| Le prompt compose plusieurs clips à la suite | **Fait et testé** |
| Raccords par inertialisation + choix du point d'entrée | **Fait et testé** |
| Découper une prise longue au bon endroit | **Pas encore** — `--duration` coupe au début |
| Modèle génératif embarqué | **Non**, et la licence l'interdit pour ton jeu |

Ce qui manque le plus :

**Le découpage.** Les prises CMU durent parfois 40 secondes et contiennent
plusieurs actions. Trouver *quelle* portion répond au prompt est un autre
problème que trouver la prise ; `--duration` coupe au début.

---

## 7. Ce que tu as à faire, toi

```bash
# La bibliothèque, une fois (≈ 1 Go)
git clone https://github.com/una-dinosauria/cmu-mocap
linen library build cmu-mocap/data -o cmu.json \
     --descriptions cmu-mocap/cmu-mocap-index-text.txt
```

Puis tu prompt. Et tu ouvres le `.html` pour vérifier avant d'importer.

Mixamo demande de télécharger à la main et de convertir en BVH via Blender
(voir [`MIXAMO.md`](MIXAMO.md)) — plus de friction, mais un catalogue mieux
rangé et déjà nettoyé. CMU est plus brut et immédiatement disponible.

> Si tu publies un jeu utilisant CMU, leur README demande une mention :
> « The data used in this project was obtained from mocap.cs.cmu.edu. The
> database was created with funding from NSF EIA-0196217. » C'est gratuit, ça
> coûte une ligne dans les crédits.
