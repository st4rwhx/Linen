# Moon Animator — finir à la main ce que le prompt commence

## D'abord la question que tu poses vraiment

> Est-ce qu'on peut refaire des animations de studio AAA à un milliard ?

Réponse honnête, en deux parties, parce qu'elles ne vont pas dans le même sens.

**Ce qui sépare une animation AAA d'une animation correcte n'est pas une
technologie que tu n'as pas.** Les trois quarts de ce qu'un gros studio met
dans une animation sont publiés et accessibles, et on en a déjà une partie :

| Ce que fait un studio AAA | Où on en est |
| --- | --- |
| Capturer des milliers de clips en studio | **On a l'équivalent** : CMU, 2548 captations, licence commerciale explicite |
| Choisir le bon clip au bon moment (motion matching) | **Fait** — `linen library` mesure et classe, la fenêtre est choisie dans la prise |
| Raccorder sans couture (inertialisation) | **Fait** — la formule d'Ubisoft La Forge, raccords mesurés à 3–5 °/image |
| Mouvement secondaire, pieds au sol, équilibre | **Écrit, typé strict, jamais joué dans Studio** — `runtime/` |
| Superposition, blend spaces, sync de phase | **Le moteur le fait** depuis juillet 2026 (Animation Graphs) |
| Son collé à l'image | **Fait** — `linen/scene/audio.py` |
| **Un animateur qui repasse dessus** | **Rien. Et c'est là qu'est tout l'écart.** |

**La dernière ligne est la vraie réponse.** Ce qui fait qu'une animation AAA se
remarque, ce n'est presque jamais l'algorithme. C'est qu'un humain a décidé que
le coup partait deux images plus tôt, que la tête restait accrochée à la cible
une demi-seconde de trop, que l'épaule montait avant le poing. Une captation
reciblée te donne un *timing juste* et une *intention absente*. C'est très
bien, et ce n'est pas fini.

Donc non : aucun prompt ne produira ça tout seul, et quiconque te dit le
contraire vend quelque chose. Mais l'écart n'est pas un mur — c'est du travail
d'animateur, et le travail d'animateur a besoin d'un endroit où se faire.

**Cet endroit, sur Roblox, c'est Moon Animator.** D'où ce qui suit.

---

## Ce que ça change concrètement

Avant, Linen écrivait du **définitif** : un `KeyframeSequence` s'importe dans
l'Animation Editor, se publie, se joue. On ne travaille pas dedans.

Maintenant `--moon` écrit en plus une **sauvegarde Moon Animator 2** : la même
animation, mais ouverte dans l'outil, avec une piste par articulation et des
images-clés qu'on peut attraper.

```bash
linen prompt "il court vite puis il donne un coup de poing" \
     --library cmu.json --moon -o build/combat.rbxmx
```

Tu obtiens `build/combat.moon.rbxmx` à côté du `.rbxmx` habituel.

### Le montage, une fois

1. Glisse `combat.moon.rbxmx` dans **ServerStorage** (n'importe où).
2. Un rig R15 dans le **Workspace** (Avatar → Rig Builder → R15).
3. Clic droit sur le script **`InstallerLinen`** → **Run Script**.
4. Ouvre **Moon Animator** → **Load** → ton animation est dans la liste.

Le script écrit dans `ServerStorage.MoonAnimator2Saves` et nulle part ailleurs.
Rien n'est envoyé sur le réseau. Il est lisible : va le lire avant de le lancer,
c'est ton jeu.

### Régler la densité d'images-clés

C'est le réglage qui compte pour travailler à la main :

```bash
--tolerance 1    # défaut : fidèle à la captation, timeline dense
--tolerance 4    # moins de clés, plus maniable, la captation reste lisible
--tolerance 8    # squelette de l'animation, à re-poser toi-même
```

Les clés sont réduites **par articulation**, pas par image : une tête qui ne
tourne pas porte deux clés, pas cinq cents. C'est ce qui rend la timeline
lisible là où il faut la lire.

---

## À essayer tout de suite

Deux sauvegardes sont livrées, prêtes à charger :

| Fichier | Ce que c'est |
| --- | --- |
| [`examples/demo/Posebook_marche.moon.rbxmx`](../examples/demo/Posebook_marche.moon.rbxmx) | La marche composée. **155 clés, 15 pistes** — commence par celle-là, elle est petite et propre. |
| [`examples/demo/Mocap_CMU_enchainee.moon.rbxmx`](../examples/demo/Mocap_CMU_enchainee.moon.rbxmx) | Les trois captations CMU enchaînées. **1339 clés** — de la vraie mocap, avec la densité que ça implique. |

---

## Comment le format a été trouvé

Le format de sauvegarde de Moon Animator n'est pas documenté. Il n'a pas eu
besoin d'être deviné pour autant : **Moonlite**, le lecteur runtime open-source
de MaximumADHD, le lit en entier, et ce writer est construit contre ce que ce
lecteur exige.

Une sauvegarde est un `StringValue` qui est deux choses à la fois :

- son `.Value` est du **JSON** — `Information` (`Length` en images, `Looped`,
  `FPS`) et `Items`, un par objet animé, avec le chemin vers lui ;
- ses **enfants** sont le mouvement, sous forme d'arbre d'Instances. Un dossier
  par item, nommé par son index dans `Items`. Un item de type rig contient un
  dossier `Rig` de dossiers `_joint`, chacun avec `_hier` (la chaîne des noms de
  parties), `default`, et `_keyframes`.

Le seul calcul qui compte : **Moon stocke le C1 *animé* de l'articulation**, pas
la transformation qu'applique une animation. Son lecteur retrouve
`Transform = c1:Inverse() * default`, donc l'installeur écrit
`c1 = default * Transform:Inverse()`. Se tromper de sens produit un rig
subtilement et systématiquement faux — le genre d'erreur qui survit à un coup
d'œil. Il y a un test qui vérifie l'aller-retour.

**Et c'est pour ça que la sauvegarde est construite par un script dans Studio
plutôt qu'écrite entièrement ici.** `default` est le vrai `Motor6D.C1` du vrai
rig, et Linen ne le connaît pas : sa propre géométrie est dérivée pour le
dessin et le dit franchement dans son code. Le lire sur le rig en place est
juste sur un R15 standard *et* sur un rig custom — ce qu'une table d'offsets
supposés ne serait pas.

---

## Ce qui n'est pas vérifié

**Rien de tout ça n'a tourné dans Roblox Studio.** Ce qui est vérifié ici :

- le Luau généré **compile et passe le typage strict** — compilateur Luau
  officiel, puis `luau-lsp` avec les définitions de l'API Roblox chargées ;
- la structure du `.rbxmx` et le contenu des deux scripts (18 tests) ;
- l'algèbre `c1 → Transform` en aller-retour sur des rotations aléatoires.

Ce qui ne l'est pas : que Moon Animator ouvre le résultat. Ça, seul Moon
Animator répond. C'est cinq minutes, et c'est le retour qui manque.

---

## Sources

- [Moonlite](https://github.com/MaximumADHD/Moonlite) — MaximumADHD, lecteur
  runtime open-source des sauvegardes Moon Animator. La référence du format.
- [Moon Animator 2 — documentation](https://zildjibian.github.io/moon-plus/)
- [Roblox DevForum — exporter des animations Moon Animator](https://devforum.roblox.com/t/want-to-export-object-animations-you-made-in-moon-animator-2-now-you-can/2515950)
