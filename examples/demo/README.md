# Démos — regarder d'abord, importer ensuite

Chaque démo est **une paire** :

- le `.html` s'ouvre dans ton navigateur, **double-clique, ça joue**. Pas de
  serveur, pas d'installation, pas de compte : la page contient l'animation ;
- le `.rbxmx` du même nom est le **même mouvement**, prêt à importer dans Roblox
  Studio (Animation Editor → `⋯` → **Import** → **From File…**).

Regarde la page avant d'importer. C'est la seule étape qui te dit si un fichier
vaut la peine d'être publié — et si le rig bouge autrement dans Studio, c'est
l'import qui a raté, pas l'animation : tu viens de la voir jouer correctement.

> Ce n'est pas une promesse en l'air : `tests/test_examples.py` compare, pose
> par pose et image-clé par image-clé, ce que porte chaque page et ce que porte
> le `.rbxmx` à côté. Sur les douze paires livrées, l'écart maximum est de
> **0,07°** — c'est l'arrondi des deux formats de texte, rien d'autre.

| | |
| --- | --- |
| glisser · molette · maj+glisser | tourner · zoomer · déplacer |
| <kbd>espace</kbd> | lecture / pause |
| <kbd>←</kbd> <kbd>→</kbd> | image par image |
| clic sur la barre du bas | aller à un instant |
| **Face** · **Profil** · **Dessus** | vues fixes |

---

## Comment récupérer ces fichiers

Sur GitHub, **cliquer sur un `.html` ne l'ouvre pas** — GitHub affiche le code
source. Deux façons de vraiment les avoir sur ton disque :

- **Tout d'un coup** — sur la page d'accueil du dépôt, bouton vert **Code** →
  **Download ZIP**. C'est ce qu'il faut faire la première fois : tu obtiens
  aussi `examples/starter/` et `runtime/`.
- **Un seul fichier** — ouvre-le sur GitHub, puis bouton **Download raw file**
  (l'icône ⤓ en haut à droite du fichier). Sur les gros `.rbxmx`, GitHub dit
  « this file is too big to display » et ne montre que ce bouton : c'est normal
  et c'est le bon.

---

## Les paires

### `Posebook_marche` vs `Mocap_CMU_marche`

**La comparaison qui compte.** Les deux marchent. Regarde-les de **profil**,
vitesse **0,25×**, l'une après l'autre.

| Fichiers | Ce que c'est |
| --- | --- |
| `Posebook_marche.html` + `.rbxmx` | Composée à partir du vocabulaire de poses écrit à la main. Propre, lisible, et on voit que c'est dessiné. |
| `Mocap_CMU_marche.html` + `.rbxmx` | Une vraie captation studio (CMU `02_01`), reciblée sur R15 sans une ligne de code en plus. |

C'est tout l'écart entre « ça marche » et « ça a l'air vrai », et c'est pour ça
que `linen library` existe.

```bash
linen prompt "il marche" --duration 3 --planner offline --name Posebook_Marche \
     -o examples/demo/Posebook_marche.rbxmx
```

### `Mocap_CMU_enchainee`

Une phrase à trois temps → trois vraies captations, enchaînées :

```bash
linen prompt "il court vite puis il marche et il donne un coup de poing" \
     --library cmu.json --name CMU_Enchainee \
     -o examples/demo/Mocap_CMU_enchainee.rbxmx
```

Les raccords sont à **1,45 s** et **3,46 s**. Va les regarder image par image :
tu ne devrais pas les voir. Mesurés à 3,4 et 5,1 °/image, contre 3,4 °/image
pour le mouvement ordinaire de ces clips — un raccord au niveau du bruit de
fond.

Les trois prises font 1,4 s, 2,9 s et **15,4 s**. Ce ne sont pas leurs deux
premières secondes qui sont reprises, mais la fenêtre que Linen a choisie dans
chacune : celle qui répond au temps de la phrase *et* qui enchaîne le mieux sur
ce qui précède.

Le raisonnement complet est dans
[`docs/ANIMATIONS_DE_FOU.md`](../../docs/ANIMATIONS_DE_FOU.md).

> C'est un fichier de 7,3 Mo : 544 images-clés à 120 Hz, la cadence de la
> captation d'origine. L'import dans Studio prend quelques secondes.

### `Appuis_avant_apres.html` — ce que la finition change

La même marche CMU deux fois, côte à côte, de profil. **Bleu : avant. Orange :
après `--polish`.** Regarde les pieds au ralenti (0,25×), vue **Profil** ou
**Dessus**.

Le glissement du pied posé passe de **1,34 stud à 0,07** — un pied R15 fait
0,86 stud de long, donc de deux longueurs de pied par appui à un dix-septième.
Le raisonnement et les chiffres sur cinq prises sont dans
[`docs/FINITION.md`](../../docs/FINITION.md).

### Les `.moon.rbxmx` — la même animation, mais modifiable

À côté de deux des démos il y a un fichier `.moon.rbxmx`. C'est la **même
animation en sauvegarde Moon Animator 2** : une piste par articulation, des
images-clés qu'on peut attraper et déplacer.

| Fichier | Ce que c'est |
| --- | --- |
| `Posebook_marche.moon.rbxmx` | 155 clés, 15 pistes. **Commence par celle-là** : petite et propre. |
| `Mocap_CMU_enchainee.moon.rbxmx` | 1339 clés. De la vraie mocap, avec la densité que ça implique. |

Glisse le fichier dans **ServerStorage**, mets un rig R15 dans le Workspace,
clic droit sur le script `InstallerLinen` → **Run Script**, puis Moon Animator →
**Load**. Le détail est dans [`docs/MOON.md`](../../docs/MOON.md).

### `Cinematique_Disarm/` — la scène complète

Six fichiers, parce qu'une cinématique n'est pas une animation : c'est un
casting, une caméra et une bande son.

| Fichier | Ce que c'est |
| --- | --- |
| `Disarm.html` | La prise entière : deux acteurs, le décor calculé, les cues en couloirs, tous les événements en repères sous la barre, la courbe de tension derrière. |
| `Disarm_Hero.rbxmx` | L'animation du héros, toute la prise (4,72 s). À importer. |
| `Disarm_Thug.rbxmx` | Celle de l'autre, sur la même timeline. À importer. |
| `Disarm_Blockout.rbxmx` | Le décor en boîtes — glisse-le dans `Workspace`, il se place tout seul. |
| `Disarm.server.luau` | Le script qui pose les rigs, joue les deux animations en sync, coupe les plans caméra et déclenche les sons. |
| `Disarm.audio.json` | La feuille de spotting : un slot par catégorie de son, avec la description de ce qu'il te faut. Colle un `rbxassetid://` en face, régénère, c'est câblé. |

**Dans la page, clique « 🎬 Caméra du réalisateur »** : la prise se joue à
travers les plans écrits dans la scène, avec leur focale et leur dérive. C'est
le cadrage que tu auras dans Studio.

```bash
linen scene examples/disarm.scene.json -o examples/demo/Cinematique_Disarm
```

L'ordre de montage dans Studio est en tête de `Disarm.server.luau`, et le détail
des sons dans [`docs/SON.md`](../../docs/SON.md).

---

> Le personnage est en boîtes parce qu'un Block Rig en est. Si tu as un rig R15
> pour Blender, `linen scene ... --skin ton_rig.blend` l'affiche à la place, et
> la page gagne un sélecteur pour basculer entre les deux.

> Tu cherches les sept animations de base — `Idle`, `Walk`, `Run`, `Jump`,
> `Fall`, `Land`, `Sit` ? Elles ne sont pas ici mais dans
> **[`examples/starter/R15/`](../starter/R15/)**, en paires `.html` + `.rbxmx`
> elles aussi. C'est de là que part [`docs/DEMARRAGE.md`](../../docs/DEMARRAGE.md).

---

## Attribution

Les deux paires `Mocap_CMU_*` contiennent du mouvement de la **CMU Graphics Lab
Motion Capture Database**, qui demande cette mention :

> The data used in this project was obtained from mocap.cs.cmu.edu. The
> database was created with funding from NSF EIA-0196217.

Sa licence autorise explicitement l'usage commercial. Si tu sors un jeu avec,
mets cette ligne dans les crédits.
