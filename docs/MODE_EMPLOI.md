# Mode d'emploi

Installation, chaque commande, ce qu'elle fait vraiment, et où sont les limites.

---

## 1. Installer

Il faut **Python 3.11 ou plus**. C'est tout : la seule dépendance est NumPy.

```bash
# Vérifier Python
python --version          # doit afficher 3.11 ou plus

# Récupérer Linen
git clone https://github.com/st4rwhx/Linen
cd Linen

# Installer
python -m pip install .

# Vérifier
linen --version           # linen 0.1.0
linen --help
```

Sous Windows, si `linen` n'est pas reconnu après l'installation, utilise
`python -m pip install --user .` puis relance ton terminal, ou appelle-le par
son chemin complet.

> Pas de compte, pas de clé API, pas de GPU, pas de réseau. Tout ce qui suit
> marche hors-ligne sauf `--planner model`, qui est optionnel.

---

## 2. Les six commandes

```
linen prompt      texte              -> animation
linen synth       plan JSON          -> animation
linen bvh         .bvh               -> animation
linen retarget    capture FreeMoCap  -> animation
linen scene       scène JSON         -> cinématique complète
linen library     indexer de la mocap, et y piocher par prompt
linen vocabulary  ce que le planificateur sait faire
```

Chacune écrit un `.rbxmx` (à importer dans Studio) **et un `.html`**
(à double-cliquer, l'animation joue dans le navigateur).

---

## 3. `linen prompt` — texte vers animation

```bash
linen prompt "marche" -o build/Walk.rbxmx
```

Sortie : `build/Walk.rbxmx` + `build/Walk.html`. Ouvre le `.html` d'abord.

### Les options qui comptent

| Option | À quoi ça sert |
| --- | --- |
| `--duration 12` | N'importe quelle durée. **Pas de plafond** |
| `--fit cycle` | Comment atteindre la durée : `cycle` rallonge les cycles, `repeat` rejoue, `stretch` ralentit, `trim` coupe, `auto` choisit |
| `--rig R6` / `--rig both` | R15 par défaut ; `both` écrit un fichier par rig |
| `--motion loop` | Boucle sans couture (idle, marche, course) |
| `--motion natural` | Le personnage se déplace vraiment (cinématique) |
| `--planner offline` | Jamais de réseau. **Mets-le toujours** si tu n'as pas configuré de modèle |
| `--skin rig.blend` | Affiche ton rig Blender dans le `.html` au lieu des boîtes |
| `--seed 3` | Change les variations aléatoires |
| `--tolerance 0.3` | Moins de compression des keyframes, plus de fidélité |

### Ce que « prompt to animation » veut vraiment dire ici

**Il faut être précis, parce que c'est le point qui décide si Linen te sert ou
te déçoit.**

Linen n'est **pas** un modèle de diffusion de mouvement. Il ne va pas inventer
un mouvement qu'il n'a jamais vu. Ce qu'il fait, c'est **composer** : il lit ta
phrase, en tire un plan (quelle action, à quel rythme, de quel côté, combien de
temps), et synthétise ce plan à partir d'un vocabulaire de poses et de cycles
construits à la main.

```bash
linen vocabulary        # la liste exacte
```

Seize actions aujourd'hui : `idle`, `walk`, `run`, `wave`, `jump`, `crouch`,
`sit`, `punch`, `point`, `celebrate`, `back`, `flinch`, `talk`, `nod`,
`shake_head`, `t_pose`. Avec les modificateurs de vitesse, d'énergie, de côté
et de durée, ça fait beaucoup de variantes — mais **ça ne fait pas une pirouette
arrière**, parce que la pirouette arrière n'est pas dans le vocabulaire.

Conséquence pratique :

- **Ce que Linen fait très bien** : le blocking. Poser une scène entière, avec
  le bon timing, le bon découpage, la caméra, les sons, en quelques secondes,
  et pouvoir la retimer sans rien casser.
- **Ce qu'il ne fait pas** : de la mocap de qualité studio à partir d'une
  phrase. Personne ne le fait gratuitement et hors-ligne aujourd'hui.

Pour de la vraie qualité de mouvement, il y a mieux que le vocabulaire :
**`linen library`**, qui laisse le prompt piocher dans une bibliothèque de vraie
mocap au lieu de composer des poses.

```bash
linen library build ~/cmu/data -o cmu.json --descriptions ~/cmu/index.txt
linen prompt "coup de poing" --library cmu.json -o build/punch.rbxmx
```

La base CMU fait 2548 mouvements, dit dans son propre README qu'elle est libre
pour un usage commercial, et arrive avec ses descriptions. Le raisonnement
complet — et pourquoi la pile IA text-to-motion ne convient pas à un jeu qu'on
vend — est dans [`ANIMATIONS_DE_FOU.md`](ANIMATIONS_DE_FOU.md).

---

## 4. `linen bvh` — le chemin vers la vraie qualité

```bash
linen bvh danse.bvh --skeleton mixamo -o build/Dance.rbxmx
```

[Mixamo](https://www.mixamo.com) est gratuit, professionnel, et couvre des
milliers d'animations captées sur de vrais acteurs. **Mixamo n'exporte pas de
BVH** — seulement FBX et DAE — donc Blender sert de convertisseur. Le chemin
complet est dans [`MIXAMO.md`](MIXAMO.md).

Le reciblage ne garde que des **rotations**, donc il est indépendant des
proportions : une animation captée sur un acteur d'1m80 joue correctement sur
n'importe quel avatar Roblox.

C'est aussi la porte d'entrée pour les modèles de diffusion (MoMask, MDM,
SayMotion) : dès qu'un outil te sort du BVH, `linen bvh` prend le relais.

---

## 5. `linen scene` — la cinématique

C'est le cœur de l'outil.

```bash
linen scene examples/disarm.scene.json --planner offline -o build/
```

Une **scène** est un fichier JSON : un casting, une feuille de cues, et ce qui
se passe autour (objets, plans de caméra, expressions, répliques).

### Le point qui change tout : l'ancrage

Aucun cue n'est écrit à un temps absolu.

```json
{ "id": "disarm", "actor": "Hero", "after": "grab", "prompt": "coup de poing droite" },
{ "id": "flinch", "actor": "Thug", "with": "disarm", "offset": 0.20, "prompt": "encaisse" }
```

| Ancrage | Sens |
| --- | --- |
| `at` | Temps absolu. À réserver aux ouvertures |
| `after` | Démarre quand le cue nommé **finit** |
| `with` | Démarre quand le cue nommé **commence** |
| rien | Enchaîne le cue précédent du même acteur |
| `offset` | Décale, négatif accepté |

Rallonge l'approche du héros d'une seconde et **tout** suit : le désarmement, le
jet du pistolet, la coupe caméra, l'impact au mur, l'expression, la réplique.
C'est la différence entre une cinématique qu'on peut monter et une qu'on doit
refaire.

### Ce que la commande sort

```
build/
  Disarm_Hero.rbxmx        l'animation du héros, avec ses marqueurs d'événement
  Disarm_Thug.rbxmx        celle de l'autre
  Disarm.server.luau       le script Studio : mise en place, lecture, caméra, son
  Disarm_Blockout.rbxmx    le décor en blocs gris, aux bonnes positions
  Disarm.audio.json        les sons dont la scène a besoin — tu colles les IDs
  Disarm.html              le visualiseur 3D
```

Plus, dans le terminal, deux feuilles à lire :

- la **feuille de plateau** — où placer le mur, et pourquoi ;
- la **conduite son** — quels sons, à quelle frame, et quoi chercher.

### Les options

| Option | À quoi ça sert |
| --- | --- |
| `--planner offline` | Jamais de réseau |
| `--from-prompt "..."` | Écrit la scène depuis une description (**demande un LLM**) |
| `--save-scene duel.json` | Écrit le JSON pour le corriger à la main |
| `--skin rig.blend` | Ton rig Blender dans le visualiseur |
| `--audio mes_sons.json` | Un autre fichier de correspondance son |
| `--no-audio` | Pas de repérage sonore |
| `--no-viewer` | Pas de `.html` |
| `--folder` | Où le script Studio cherche les animations importées |

`--from-prompt` est le **seul** endroit de Linen qui exige vraiment un modèle de
langage : choisir un casting et décider quel beat s'accroche à quel autre, c'est
de la lecture d'intention. Un [Ollama](https://ollama.com) local le fait
gratuitement. Les cues eux-mêmes n'en ont pas besoin.

---

## 6. Le son : tu ne places rien à la main

Détaillé dans [`SON.md`](SON.md).

Linen regarde l'animation et **trouve tout seul** où les sons tombent : un poing
qui accélère puis freine contre un torse, c'est un impact, et la frame est une
mesure. Il en sort une conduite son avec des slots nommés, et tu colles les
identifiants **une fois** dans `<Scène>.audio.json` — ils survivent à toutes les
régénérations.

Trois slots (`footstep`, `jump_land`, `effort`) sont **déjà remplis** avec des
fichiers livrés dans le client Roblox : rien à uploader, rien à faire modérer.

Pour le reste : Toolbox → Creator Store → Audio, plus de 100 000 sons libres, et
la feuille te donne les mots-clés. Le dialogue, c'est toi (ElevenLabs).

---

## 7. Les expressions de visage

**Oui, c'est géré — avec une condition matérielle qu'il faut connaître.**

Un événement `face` dans une scène :

```json
{ "kind": "face", "cue": "settle", "offset": 0.10, "actor": "Hero",
  "expression": "smug", "hold": 3.0 }
```

Neuf expressions nommées : `neutral`, `smug`, `angry`, `afraid`, `surprised`,
`pain`, `determined`, `laughing`, `sad`. Le runtime les traduit en mélange de
**poses FACS**, pour qu'une scène reste lisible au lieu de lister des
coefficients.

### La condition : il faut une *dynamic head*

R15 s'arrête au cou. Une tête blocky classique **n'a pas de visage animable** —
elle a une texture. Pour une vraie expression il faut une
[**dynamic head**](https://create.roblox.com/docs/avatar/dynamic-heads) : un
`MeshPart` skinné, avec des os de visage, portant une instance `FaceControls`
qui expose [50 poses FACS](https://create.roblox.com/docs/art/characters/facial-animation/facs-poses-reference).

Trois façons d'en avoir une, de la plus simple à la plus longue :

1. **En prendre une toute faite.** Beaucoup de têtes du catalogue Roblox sont
   déjà dynamiques. C'est le chemin court, et c'est celui à prendre pour
   commencer.
2. **Acheter/récupérer un personnage complet** qui en embarque une.
3. **La fabriquer** — modélisation, os de visage, skinning, mapping FACS dans
   Blender. C'est un métier à part entière ; le guide Roblox est
   [Create basic dynamic heads](https://create.roblox.com/docs/art/characters/facial-animation/create-basic-heads).

**Sur une tête blocky, l'événement `face` est simplement ignoré, sans erreur.**
C'est voulu : la scène reste valide, tu ajoutes les têtes quand tu veux, rien
d'autre ne casse entre-temps.

> Un piège qui coûte cher : les noms de poses FACS sont assignés dans un
> `pcall`. Un nom mal orthographié **n'échoue pas**, il ne fait rien — et
> l'expression sort vide sur une tête qui la supporte pourtant. Quatre des neuf
> mélanges de Linen étaient faux comme ça (`NoseWrinkler` au lieu de
> `LeftNoseWrinkler`, `LipPressor` au lieu de `LipPresser`…). C'est corrigé, et
> un test vérifie maintenant chaque nom contre la liste officielle des 50.

---

## 8. Le visualiseur 3D

Chaque commande écrit un `.html`. Double-clique-le.

| | |
| --- | --- |
| Tourner / zoomer / déplacer | glisser · molette · maj+glisser |
| Lecture, image par image | <kbd>espace</kbd>, <kbd>←</kbd> <kbd>→</kbd> |
| Vues fixes | **Face**, **Profil**, **Dessus** |
| Aller à un instant | cliquer sur la timeline |
| Choisir le rig affiché | menu **rig** (avec `--skin`) |
| Jouer à travers tes plans | **Caméra du réalisateur** |
| Ouvrir sur un moment | `Disarm.html#t=2.03&cam=side` |

**Regarde toujours le `.html` avant d'importer quoi que ce soit.** C'est deux
secondes et ça répond à la seule question qui compte : *est-ce que ça ressemble
à ce que j'ai demandé.*

---

## 9. Recette complète : de zéro à une cinématique

```bash
# 1. Installer
git clone https://github.com/st4rwhx/Linen && cd Linen
python -m pip install .

# 2. Regarder ce qui existe déjà — rien à installer de plus
open examples/starter/R15/Walk.html

# 3. Générer la cinématique d'exemple
linen scene examples/disarm.scene.json --planner offline -o build/

# 4. La regarder, avec ton rig si tu en as un
linen scene examples/disarm.scene.json --planner offline -o build/ \
     --skin MonRig.blend
open build/Disarm.html

# 5. Corriger ce qui ne va pas dans examples/disarm.scene.json, relancer (3)

# 6. Coller les IDs audio dans build/Disarm.audio.json, relancer (3)

# 7. Dans Studio : importer les .rbxmx, déposer le blockout, lancer le script
```

Les étapes 3 à 6 sont une boucle de quelques secondes. **L'étape 7 est la seule
qui n'a jamais été testée.**

---

## 10. L'état réel

| | |
| --- | --- |
| Reciblage FreeMoCap / BVH / Mixamo | **Fait et testé** |
| Prompt → animation, hors-ligne, sans plafond de durée | **Fait et testé** |
| Scène multi-personnages, ancrage, retiming | **Fait et testé** |
| Feuille de plateau, blockout du décor | **Fait et testé** |
| Repérage son, courbe de tension, ambiances | **Fait et testé** |
| Visualiseur 3D, caméra du réalisateur, rigs Blender | **Fait, et il tourne** |
| Tout le Luau généré | **Compile** (compilateur officiel), **jamais exécuté** |
| Import dans Studio | **Jamais testé** |
| Modèle de mouvement génératif | **Non** — vocabulaire composé à la main |
| Décor généré | **Non, et ce n'est pas prévu** |

347 tests passent. Ça ne veut pas dire que ça marche dans Studio : ça veut dire
que ce qui est vérifiable ici est vérifié. Le reste attend l'étape 7.

---

## 11. Si quelque chose ne marche pas

| Symptôme | Cause probable |
| --- | --- |
| `linen: command not found` | Installation dans un autre Python. Essaie `python -m linen.cli` |
| `error: no provider configured` | Ajoute `--planner offline` |
| L'animation ne ressemble à rien dans le `.html` | Le vocabulaire n'a pas ce mouvement ; regarde `linen vocabulary` |
| Le `.html` rame | Rig lourd : passe le menu **rig** sur **Boîtes** |
| `.blend` refusé | Réenregistre-le sans compression (décoche « Compresser ») |
| L'import Studio est grisé | Rig R6 construit alors que le fichier est R15 |
| Le visage ne bouge pas | Tête blocky : il faut une *dynamic head* (section 7) |
| Un son ne part pas | Slot vide dans `<Scène>.audio.json` |
