# Linen

Des animations Roblox **R15 / R6** à partir de FreeMoCap — et à partir d'un
prompt texte, sans coût d'API.

> **Rien à installer pour voir ce que ça donne :**
> **[`examples/demo/`](examples/demo/)** — quatre démos, chacune en paire : une
> page à double-cliquer, et le `.rbxmx` du même mouvement à importer dans
> Studio. La cinématique complète avec la caméra du réalisateur, et la
> comparaison vocabulaire de poses ↔ vraie mocap, côte à côte.
>
> **Tu débutes sur le projet ?** Commence par
> **[`docs/DEMARRAGE.md`](docs/DEMARRAGE.md)** : sept animations déjà générées,
> et un pas-à-pas dans Studio sans une ligne de code. 20 minutes.
>
> **Tu veux l'installer et t'en servir ?**
> **[`docs/MODE_EMPLOI.md`](docs/MODE_EMPLOI.md)** : l'installation, chaque
> commande, ce qu'elle fait vraiment, et où sont les limites.
>
> **Un jeu militaire ?**
> **[`examples/starter/Military/`](examples/starter/Military/)** — `Idle`,
> `Walk`, `Run`, `Jump`, `Fall`, `Land` en style militaire d'élite, R15 et R6,
> prêtes à importer. L'arme possède le haut du corps : c'est ça, le style.
>
> **Tu veux être meilleur qu'un animateur pro ?**
> **[`docs/FINITION.md`](docs/FINITION.md)** : `--polish` mesure le patinage
> des pieds en studs et le ramène à 0,05 — sur de la vraie mocap studio. Un
> animateur juge à l'œil ; un nombre ne s'arrête pas.
>
> **Comment font ceux qui sortent des animations de fou ?**
> **[`docs/COMMENT_ILS_FONT.md`](docs/COMMENT_ILS_FONT.md)** : NoCapMocap, la
> mocap depuis vidéo et son mur de licence, ce que font vraiment les animateurs
> Roblox — et pourquoi le métier de Linen est d'assembler, pas d'inventer.
>
> **Tes animations ont l'air dessinées ?**
> **[`docs/BIBLIOTHEQUE.md`](docs/BIBLIOTHEQUE.md)** : le vocabulaire de poses
> connaît douze verbes. CMU en a 2548, capturés en studio, gratuits y compris
> commercialement — vérifié de bout en bout, avec les commandes.
>
> **Tu veux une cinématique dans ton jeu à toi ?**
> **[`docs/CINEMATIQUE_DANS_TON_JEU.md`](docs/CINEMATIQUE_DANS_TON_JEU.md)** :
> relever ta place, écrire la scène, la générer calée sur tes vrais rigs, et la
> jouer en jeu réel avec des identifiants publiés.
>
> **Tu veux l'identifiant, pas le fichier ?**
> **[`docs/PUBLIER.md`](docs/PUBLIER.md)** : `linen publish` téléverse par Open
> Cloud et rend de vrais `rbxassetid://`, sous ton compte ou sous ton groupe,
> sans ouvrir Studio et sans jamais toucher à un cookie.
>
> **Tu veux finir l'animation à la main ?**
> **[`docs/MOON.md`](docs/MOON.md)** : `--moon` écrit une sauvegarde Moon
> Animator 2 à côté du `.rbxmx`, et la vraie réponse à « est-ce qu'on peut
> atteindre le niveau AAA ».
>
> **Tu veux des animations qui ont l'air capturées ?**
> **[`docs/ANIMATIONS_DE_FOU.md`](docs/ANIMATIONS_DE_FOU.md)** : pourquoi toute
> la pile IA text-to-motion est fermée pour un jeu qu'on vend, quelles
> bibliothèques sont réellement utilisables, et comment un prompt y pioche.
>
> **Ce que Roblox n'a pas documenté :**
> **[`docs/ETAT_DE_L_ART.md`](docs/ETAT_DE_L_ART.md)** — Animation Graphs,
> inertialisation native, synchronisation de phase, mocap depuis une vidéo :
> ce que le dump d'API révèle et que la doc ne dit pas.

```bash
# un prompt -> une animation. Aucune clé, aucun GPU, aucun réseau.
linen prompt "salue de la main gauche puis marche" --planner offline --rig both -o hello.rbxmx
#   -> hello.R15.rbxmx  +  hello.R6.rbxmx

# une capture FreeMoCap -> un fichier importable dans Studio
linen retarget mediapipe_body_3d_xyz.npy --fps 30 --rig R6 -o wave.rbxmx
```

`--rig` vaut `R15`, `R6` ou `both` sur **toutes** les commandes : le choix du
rig appartient à l'utilisateur, jamais à l'outil.

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

**Ce que Linen fait de tout ça.** Trois chemins, du plus lourd au plus léger,
tous aboutissant à du R15/R6 :

- **Il ingère leur sortie.** `linen bvh` prend un BVH — export SayMotion, MoMask
  ou MDM lancé en local, téléchargement Mixamo — et le recible sur R15/R6 avec
  le même solveur, les mêmes conventions et le même exporteur que la voie
  FreeMoCap. Un test vérifie que les deux chemins donnent la même chose sur la
  même pose. Linen est le tuyau, pas un concurrent du modèle.
- **Il parle à un LLM local.** Ollama, llama.cpp ou LM Studio sur ta machine :
  aucune clé, aucun quota, rien ne sort. C'est le premier fournisseur de la
  chaîne, et il tombe en une poignée de secondes si rien n'écoute.
- **Et il a un planificateur qui ne demande rien du tout** — ni clé, ni GPU, ni
  réseau, ni téléchargement. C'est `--planner offline`, et c'est ce qui rend la
  phrase « prompt to animation, local et gratuit » vraie sans astérisque.

Dans les deux derniers cas le principe est le même : **le planificateur dirige,
il n'anime pas.** Il produit un *plan* — quelle pose à quel instant, avec quel
easing, quelle énergie — et un synthétiseur déterministe fait le reste. La
qualité vient de trois choses toutes gratuites et sous notre contrôle :

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

### Sur le « photoréalisme »

Un mot à clarifier, parce qu'il recouvre deux choses très différentes.

**Le rendu** n'est pas de notre ressort. Un personnage Roblox est un assemblage
de blocs, et c'est le moteur de Roblox qui l'éclaire et l'affiche. Aucune
animation ne rendra un R15 photoréaliste : ce n'est pas ce que la plateforme
dessine.

**Le mouvement**, lui, peut absolument atteindre le réalisme — et c'est
probablement ce que tu veux dire. Mais il n'existe que deux sources de réalisme
de mouvement, et ni l'une ni l'autre n'est un vocabulaire de poses :

1. **de la vraie captation** — `linen retarget` sur tes propres prises
   FreeMoCap. C'est le plafond de qualité, et il est gratuit ;
2. **un modèle entraîné sur de la captation** — `linen bvh` sur une sortie
   SayMotion, ou sur MoMask/MDM lancés en local.

Le planificateur hors-ligne, lui, ne sera jamais réaliste : il interpole entre
des poses écrites à la main. Il est propre, lisible et instantané, ce qui en
fait un excellent outil de **prévisualisation** — on monte la cinématique, on
valide le timing, puis on remplace cue par cue par de la captation. C'est
exactement le workflow d'un studio : previs d'abord, mocap ensuite.

### En résumé

| Source | Qualité | Coût | Réseau | Quand |
| --- | --- | --- | --- | --- |
| `linen retarget` — capture FreeMoCap | La meilleure | Gratuit | Non | Tu peux filmer le mouvement |
| `linen bvh` — SayMotion, MoMask/MDM local | Très bonne | Crédits, ou gratuit en local | Selon | Tu ne peux pas filmer |
| `linen prompt` — LLM local (Ollama) | Correcte, plans variés | Gratuit | Non | Tu as un LLM installé |
| `linen prompt --planner offline` | Correcte, déterministe | Gratuit | **Jamais** | Rien d'installé du tout |

Toutes écrivent du R15, du R6, ou les deux.

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
| `--motion` | `in-place` (défaut), `natural` (racine cuite), `loop`. Voir plus bas. |
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

**Sans rien installer** — le planificateur hors-ligne :

```bash
linen prompt "saute deux fois puis célèbre" --planner offline -o jump.rbxmx
```

Il reconnaît des mots-clés en français et en anglais et assemble un plan à
partir de *beat sheets* écrites à la main : anticipation, action, settle, avec
des durées contrastées. Il ne comprend pas une phrase, il y **reconnaît des
mots** — et il le dit dans ses `notes` quand il ne reconnaît rien.

| Il connaît | Exemples de mots |
| --- | --- |
| actions | salut/wave, marche/walk, cours/run, saute/jump, accroupi/crouch, assis/sit, poing/punch, pointe/point, célèbre/cheer, idle |
| côté | gauche/left, droite/right |
| vitesse | vite, très rapide, lentement, doucement |
| énergie | explosif, puissant, fatigué, mou |
| répétition | deux fois, trois fois, twice |
| boucle | en boucle, loop (refusée si un saut traîne dans la séquence) |
| enchaînement | puis, ensuite, et, then, virgules |

`linen vocabulary` liste tout, y compris les mots-clés exacts.

#### Durée : n'importe laquelle, sans plafond

```bash
linen prompt "marche" --planner offline --duration 60 -o walk.rbxmx   # 60 s
linen prompt "marche" --planner offline --duration 90 -o walk.rbxmx   # 90 s aussi
```

Les services hébergés s'arrêtent à 10 secondes parce qu'un modèle de diffusion
ne peut produire que ce que sa fenêtre d'entraînement contenait. Ici la durée
est un problème de **mise en page**, pas de modèle : un plan est un emploi du
temps sur un vocabulaire de poses. Il n'y a donc pas de plafond — juste un
garde-fou à 600 s contre les fautes de frappe.

Ce qui compte alors, ce n'est pas *si* on peut allonger, c'est **comment**.
Étirer un coup de poing de 2 s à 60 s donne un ralenti, pas un coup de poing
plus long. `--fit` choisit :

| `--fit` | Effet |
| --- | --- |
| `auto` (défaut) | Lit le plan : cycle présent → il tourne plus longtemps ; sinon la séquence rejoue ; sinon le timing est mis à l'échelle |
| `cycle` | Le temps en plus va aux cycles, **à cadence inchangée** — 60 s de marche, pas un pas géant |
| `repeat` | La séquence rejoue jusqu'à remplir, avec un fondu aux raccords |
| `stretch` | Tout est mis à l'échelle. Ralenti assumé |
| `trim` | Coupe net à la cible, ou tient la dernière pose |

`--duration auto` (défaut) garde la longueur naturelle de la séquence.
Valeurs suggérées pour une UI : 3, 5, 10, 15, 30, 60 — exportées dans
`viewport/rigs.generated.ts` (`DURATION_PRESETS`) pour ne pas diverger du CLI.

Pour une boucle, un clip **court** vaut mieux qu'un long : 2,2 s de marche en
`--motion loop` rejouées par Roblox pèsent 200 ko là où 60 s en pèsent 5 Mo,
pour un résultat identique à l'écran.

#### Racine et boucle

`--motion` sur toutes les commandes :

| Valeur | Effet |
| --- | --- |
| `in-place` (défaut) | Racine verrouillée. C'est le `Humanoid` qui pilote la position — le bon choix pour un personnage jouable |
| `natural` | Translation de la racine cuite dans le fichier. Pour une cinématique |
| `loop` | Racine verrouillée + raccord de boucle sans à-coup |

**Avec un LLM local** — plans plus variés, toujours zéro coût et zéro réseau
sortant :

```bash
ollama serve && ollama pull llama3.1        # une fois
linen prompt "esquive à droite, contre-attaque, retour en garde" -o dodge.rbxmx
```

Linen essaie `http://localhost:11434/v1` d'abord (surchargeable par
`LINEN_LOCAL_BASE_URL`, donc LM Studio et llama.cpp marchent aussi), puis les
API distantes si une clé est présente, puis retombe sur le planificateur
hors-ligne. `--planner model` refuse ce repli et échoue franchement à la place.

**Avec une API distante** — `export GEMINI_API_KEY=...`, et `linen providers`
liste ce qui est configuré.

Le plan sauvegardé est un JSON court, relisible et modifiable à la main :

```bash
linen synth dodge.plan.json -o dodge.rbxmx   # aucun réseau
```

C'est le mode de travail recommandé : le LLM propose, vous ajustez le timing
dans le JSON, vous resynthétisez. `linen vocabulary` liste les poses et cycles
disponibles.

### Le visualiseur 3D

Chaque commande écrit un `.html` à côté de son `.rbxmx`. **Double-clique-le** :
il s'ouvre dans le navigateur et l'animation joue.

Pas de serveur, pas de CDN, pas de compte — la page contient les données. Elle
marche hors-ligne et s'envoie par mail.

```bash
linen prompt "coup de poing droite tres rapide" -o build/punch.rbxmx
# build/punch.rbxmx  +  build/punch.html
```

| | |
| --- | --- |
| Tourner / zoomer / déplacer | glisser · molette · maj+glisser |
| Lecture, image par image | <kbd>espace</kbd>, <kbd>←</kbd> <kbd>→</kbd> |
| Vues fixes | **Face**, **Profil**, **Dessus** |
| Aller à un instant | cliquer sur la timeline |
| Ouvrir sur un moment précis | `punch.html#t=2.03&cam=side` |

Sur une scène, la page porte en plus la **caméra du réalisateur** — elle joue la
prise à travers tes plans, avec leur focale et leur dérive, donc un plan qui
tombe sur la nuque de quelqu'un se voit ici et pas après un import — le décor
calculé, les cues par acteur en couloirs, tous les événements en repères sous la
barre, et la courbe de tension derrière.

Regarde la prise avant d'importer quoi que ce soit. C'est la seule vérification
qui coûte deux secondes et qui répond à la vraie question : *est-ce que ça
ressemble à ce que j'ai demandé.*

#### Choisir le rig affiché

Par défaut c'est des boîtes — parce qu'un Block Rig *est* des boîtes. Mais ça
ressemble à une hitbox, et une hitbox en dit moins qu'un vrai personnage. Donne
un rig Blender et la page l'affiche à la place :

```bash
linen scene examples/disarm.scene.json -o build/ --skin MrXen0_R15RIG_v1.2.blend
# MrXen0_R15RIG_v1.2.blend: habillage R15 — 15 parties, 2390 triangles
```

Le `.blend` est lu directement, sans Blender : un `.blend` est un vidage
auto-descriptif de la mémoire de Blender, et un de ses blocs contient la
définition de toutes ses structures. Il faut **un objet maillage par partie
Roblox**, nommé exactement comme Roblox les nomme (`Head`, `LeftUpperArm`…) —
ce que font déjà les rigs R15 qui circulent. `--skin` est répétable, et la page
gagne un sélecteur *rig* pour passer de l'un à l'autre, boîtes comprises.

> Enregistre depuis Blender **sans compression** (`Fichier > Enregistrer sous`,
> décoche « Compresser ») : Blender compresse en Zstandard, que Python ne sait
> pas relire ici. Le message d'erreur te le redira.

**Le squelette reste celui de Linen.** Chaque maillage est recentré et mis à
l'échelle de la boîte de sa partie, mesurée sur le ClassicMannequin de Roblox.
Les articulations tombent donc exactement là où le solveur les met, quelles que
soient les proportions du rig prêté — un habillage change ce que tu regardes,
jamais ce qui est exporté. C'est la même raison qui fait que l'export ne
contient que des rotations : une animation, ce sont des angles, donc elle joue
correctement sur n'importe quel avatar.

> Le composant React pour FreeMoCap est séparé, dans
> [`viewport/README.md`](viewport/README.md) : deux fichiers à déposer dans
> `freemocap-ui`, un `<RobloxRig rig="R15" clip={clip} />` dans la scène.

### Cinématiques multi-personnages

```bash
linen scene examples/confrontation.scene.json --planner offline -o build/
```

Sortie : **une animation par acteur** couvrant toute la prise, plus un script
Luau qui place les rigs et lance tout en synchro.

Une scène, c'est un casting et une feuille de cues. Ce qui la rend utilisable,
c'est que chaque cue peut s'**ancrer sur une autre** plutôt que sur l'horloge :

```json
{ "id": "hit",   "actor": "Alice", "after": "approche", "prompt": "coup de poing droite" },
{ "id": "recul", "actor": "Bob",   "with": "hit", "offset": 0.25, "prompt": "encaisse" }
```

| Ancrage | Sens |
| --- | --- |
| `at` | Temps absolu. À réserver aux ouvertures |
| `after` | Démarre quand le cue nommé **finit**. Une conséquence |
| `with` | Démarre quand le cue nommé **commence**. Deux choses en même temps |
| rien | Enchaîne le cue précédent du même acteur |
| `offset` | Décale l'ancrage, négatif accepté (anticiper le coup) |

Rallonge l'approche d'Alice et le recul de Bob suit tout seul. C'est ce qui
rend une cinématique retimeable au lieu d'être à refaire.

Chaque acteur a **son propre rig** : Alice en R15, Bob en R6 dans la même scène,
sans rien de particulier à faire.

Le script généré utilise `KeyframeSequenceProvider:RegisterKeyframeSequence`,
qui donne un ID d'animation temporaire — donc **la scène se teste sans rien
uploader**. Ces IDs ne marchent qu'en Studio ; on publie normalement une fois
la scène figée.

#### Écrire la scène depuis un prompt

```bash
linen scene --from-prompt "Alice arrive, pointe Bob du doigt, le frappe ; Bob encaisse et recule" \
  -o build/ --save-scene duel.json --planner offline
```

C'est le **seul** endroit de Linen qui exige vraiment un modèle de langage :
choisir un casting, une mise en place et surtout décider quel beat s'accroche à
quel autre, c'est de la lecture d'intention. Le matching de mots-clés n'en est
pas capable, et prétendre le contraire produirait du n'importe quoi confiant.

En revanche les cues eux-mêmes n'en ont pas besoin : `--planner offline` les
anime sans réseau. Un Ollama local couvre la mise en scène gratuitement, le
hors-ligne couvre l'animation — l'ensemble reste local.

`--save-scene` écrit le JSON, qui se relit et se corrige à la main. C'est le
mode de travail recommandé : le modèle propose le découpage, tu ajustes les
`offset`, tu reconstruis.

#### Le son : repéré, pas placé à la main

Détaillé dans [`docs/SON.md`](docs/SON.md).

Tu n'écris aucun événement sonore. Les clips contiennent la rotation de chaque
partie sur chaque frame, donc la cinématique directe donne la position des deux
poings et des deux pieds sur chaque frame de la prise — et un poing qui
accélère puis freine brutalement contre le torse d'en face, **c'est** un coup
qui touche. La frame est une mesure, pas une estimation.

`linen scene` sort donc une **conduite son**, comme il sort déjà une feuille de
plateau :

```
slot            cat    n  quand                       il te faut
punch_impact    FX     1  2.03s                       Impact d'un poing sur un corps — sourd, court, avec du grave
footstep        FOL    7  0.20, 0.50, 0.80...s        Un pas...
dialogue        DX     2  2.67, 4.42s                 1. Hahaha, you couldn't even swing me!; 2. Nooo...
tension_drone   MUS    -  1.11-4.72s (nappe)          Nappe grave et tenue, qui monte quand ça chauffe
heartbeat       MUS    -  0.00-4.72s (nappe)          Battement de cœur — Thug encaisse plus qu'il ne donne

Tension (0-1) :   ▁▂▃▄▄▄▄▄▄▄▄▄▄▄▄▃▃▃▃▃▃▃▃    pic à 0.62
```

Personne n'a écrit que Thug était mal en point : chaque coup qui touche
enregistre qui il touche, et le cœur va à celui qui encaisse plus qu'il ne
donne.

Tu colles les identifiants **une fois** dans `<Scène>.audio.json` ; ils
survivent à toutes les régénérations. Trois slots (`footstep`, `jump_land`,
`effort`) sont déjà remplis avec des fichiers **livrés dans le client Roblox** —
rien à uploader, rien à faire modérer.

La courbe de tension est écrite dans le script et lue en direct : elle gonfle le
drone, ouvre la profondeur du `TremoloSoundEffect` — le tremblement — et fait
tomber les aigus quand ça monte.

#### Ce que la scène ne fait pas

**Le contact résolu.** Faire atterrir une main sur l'épaule de l'autre, pour
deux rigs de proportions inconnues, demande un solveur IK avec conscience des
collisions. Les cues donnent la mise en place et le timing — ce qui représente
l'essentiel de ce qui *se lit* comme une interaction à l'écran — mais les
derniers centimètres se règlent à la main dans l'Animation Editor. Le repérage
son le dit quand la mise en place ne suffit pas : *« 1 coup détecté mais aucun
ne touche : les acteurs sont trop loin l'un de l'autre »*.

**Trouver les sons.** Linen dit lesquels il faut, quand ils tombent et avec
quels mots-clés les chercher dans le Creator Store. Il ne peut pas inventer un
asset ID.

## Le runtime : mouvement organique en jeu (style Euphoria)

Tout ce qui précède est **hors-ligne** — du Python qui écrit des fichiers.
[`runtime/`](runtime/) est autre chose : du **Luau qui s'embarque dans ta place**
et modifie les personnages pendant qu'ils bougent.

| Module | Ce qu'il fait |
| --- | --- |
| [`Ragdoll`](runtime/Ragdoll.luau) | Ragdoll **actif** : le corps continue d'essayer de tenir sa pose pendant que la physique agit dessus. Coudes et genoux en `HingeConstraint`, pas en cône |
| [`FootPlanting`](runtime/FootPlanting.luau) | Pieds ancrés sur le relief via `IKControl` natif, bassin abaissé avant résolution |
| [`Balance`](runtime/Balance.luau) | Centre de masse projeté dans le polygone de sustentation, marge en studs |
| [`Momentum`](runtime/Momentum.luau) | Le buste s'incline contre l'accélération, lu sur la vélocité réelle |
| [`Secondary`](runtime/Secondary.luau) | **Drag** entre articulations, **ondes d'impact** qui se propagent, regard, tremblement |
| [`Locomotion`](runtime/Locomotion.luau) | Mélange piloté par la vitesse, cadence calée sur la foulée — **fin du patinage** |

Les limites articulaires sont définies et testées **en Python**, puis générées
en Luau — le rig physique ne peut pas diverger du rig d'animation. Un test
vérifie qu'aucune pose de la banque ne demande quelque chose que les contraintes
interdisent (il a attrapé un salut qui pliait le coude latéralement).

Le plus rentable n'est pas la physique mais le **drag** : faire traîner chaque
articulation derrière son parent (overlapping action) fait qu'un clip banal se
met à ressembler à du travail d'animateur — sur n'importe quel R15, sans un seul
os supplémentaire. Et le patinage n'est pas un problème d'animation mais
d'arithmétique : Linen calcule la foulée de chaque cycle **par cinématique
directe sur les poses**, et le runtime joue le clip à `vitesse_réelle /
vitesse_naturelle`.

**Objectif réaliste, dit franchement :** tu passes très largement au-dessus du
Roblox standard. Tu n'auras pas la parité RDR2 — R15 a quinze blocs et **une
seule articulation de colonne**, là où Euphoria en anime plusieurs, et aucun
solveur ne crée des os manquants. Le vrai mur d'ingénierie n'est d'ailleurs pas
là : c'est la **propriété réseau** en multijoueur, un problème qu'Euphoria n'a
jamais eu puisque RDR2 est solo.

Le détail complet — ce qui est fait, ce qui est possible, ce qui ne l'est pas et
pourquoi — est dans [`docs/EUPHORIA.md`](docs/EUPHORIA.md), et la comparaison
point par point avec RDR2 dans [`docs/RDR2.md`](docs/RDR2.md).

> Les modules Luau sont **écrits et relus, pas exécutés** : je n'ai pas de
> moteur Roblox ici. Prévois une passe de mise au point en Studio.

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

Le second est `test_only_actual_thrusts_are_heard_as_strikes` : il passe les
seize actions du planificateur, sur les deux rigs, dans le repérage son et
exige zéro faux positif. C'est lui qui a fixé chaque seuil du détecteur de
coups — et il attrape immédiatement une pose retouchée qui se met à ressembler
à un coup de poing.

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
