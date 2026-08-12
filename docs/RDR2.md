# RDR2 vs Linen : la comparaison honnête

> Question posée : « est-ce qu'on imite parfaitement les animations réalistes de
> RDR2, mais sur Roblox ? »
>
> **Non.** On en attrape une partie — la partie la moins chère et la plus
> visible. Ce document dit laquelle, et surtout *pourquoi* le reste est loin.

## Comment RDR2 fonctionne réellement

Le piège, c'est de croire qu'« Euphoria = le réalisme de RDR2 ». C'est faux, et
c'est la chose la plus importante de ce document. Le jeu empile **trois
systèmes** dont Euphoria n'est que le troisième.

### Couche 1 — une bibliothèque d'animations colossale

C'est de là que vient l'essentiel du réalisme. Du mouvement humain capté par
motion capture, retravaillé par des animateurs, en quantité : RDR2 embarque
[environ dix fois le volume d'animations de GTA V](https://www.gameslearningsociety.org/wiki/did-red-dead-redemption-use-motion-capture/),
et Rockstar a capté simultanément corps, visage et voix des acteurs.

Chaque variation a son clip : marcher, marcher blessé, marcher en portant,
marcher dans la neige, marcher en pente, se retourner sur place à 90°, à 180°,
freiner depuis la course, freiner depuis le sprint. **Rien de tout ça n'est
procédural.** C'est de l'authoring, à une échelle industrielle.

### Couche 2 — le graphe de mélange (RAGE / MoVE)

Un arbre d'états qui choisit et mélange ces clips selon la vitesse, la
direction, la pente, l'état du personnage, ce qu'il tient. C'est de
l'ingénierie classique, mais sur une bibliothèque de cette taille elle devient
le vrai travail.

### Couche 3 — Euphoria, seulement pour les réactions

[Euphoria](https://en.wikipedia.org/wiki/Euphoria_(software)) est du *Dynamic
Motion Synthesis* : une simulation biomécanique avec muscles et système nerveux
simplifié, développée par NaturalMotion et intégrée dans RAGE. Elle ne pilote
pas la marche. Elle prend la main quand le corps subit quelque chose.

Et son ampleur se mesure : l'interface publique côté GTA V expose
[~90 comportements nommés](https://nitanmarcel.github.io/shvdn-docs.github.io/class_g_t_a_1_1_natural_motion_1_1_euphoria.html),
chacun réglable. Un échantillon, pour donner l'échelle :

| Comportement | Ce qu'il fait |
| --- | --- |
| `catchFall` | Tend les bras pour amortir la chute |
| `staggerFall` | Titube plusieurs pas avant de tomber |
| `bodyBalance` | Rattrapage d'équilibre actif |
| `armsWindmill` | Moulinets de bras pour ne pas basculer |
| `shotInGuts`, `shotFallToKnees`, `shotShockSpin` | Réactions **par zone touchée** |
| `configureShotInjuredArm` | Le personnage **protège** son bras blessé ensuite |
| `grab` | Se rattrape à un rebord, un objet |
| `rollDownStairs` | Descente d'escalier en roulé-boulé |
| `teeter` | Vacille au bord d'un précipice |
| `configureSelfAvoidance` | Les membres évitent de traverser le corps |
| `setMuscleStiffness` | Tonus musculaire, réglable |
| `bodyFoetal`, `bodyWrithe`, `onFire`, `electrocute`, `buoyancy` | … et ainsi de suite |

Nous en avons l'équivalent d'environ **cinq**.

### Le coût, que personne ne mentionne

RDR2 a un temps de réponse aux commandes
[nettement supérieur à ses pairs](https://www.resetera.com/threads/ea-motives-dan-lowe-compares-the-input-response-times-of-rdr2-with-uncharted-assassins-creed-etc.80420/),
et c'est un **choix** : Rockstar privilégie l'engagement dans l'animation à la
réactivité. Dan Lowe, animateur technique chez EA Motive, fait remarquer que ce
n'était pas obligatoire — la bonne façon d'obtenir du mouvement lourd sans
latence est de mettre **l'anticipation dans l'animation**, pas un délai sur les
commandes.

Ça compte énormément pour toi : ce compromis passe dans un western solo
contemplatif. Sur Roblox, où les joueurs attendent une réponse immédiate, copier
la latence de RDR2 rendrait ton jeu injouable. **Copie son poids, pas son
délai** — et c'est exactement ce que fait l'easing `anticipate` du
planificateur hors-ligne.

## Comment Linen fonctionne

Deux programmes qui ne tournent jamais en même temps.

### A. Hors-ligne — Python, sur ta machine, une fois

```
FreeMoCap (.npy) ──┐
BVH externe ───────┼─> LandmarkTrack ─> solveur ─┐
                   │                             ├─> AnimationClip ─┬─> .rbxmx
prompt ─┬─ LLM ────┴──> MotionPlan ─> synthèse ──┘                  └─> .json
        └─ hors-ligne ┘
```

Trois sources d'entrée, une représentation au milieu, deux sorties.

**Le solveur** est le morceau technique. Il consomme des *points nommés* — pas
un tracker particulier — donc une capture FreeMoCap et un BVH de MoMask passent
par exactement le même code. Il calcule des **rotations seulement**, donc il est
indépendant de la taille du sujet : quelqu'un d'1,55 m et quelqu'un d'1,95 m
pilotent le même rig sans calibration.

**Le planificateur** ne génère jamais de mouvement. Il produit un *emploi du
temps* — quelle pose à quel instant, quel easing — et un synthétiseur
déterministe interpole entre des poses écrites à la main.

### B. Runtime — Luau, dans ta place, à chaque frame

```
1. Locomotion   mélange les allures par vitesse       (PreSimulation)
2. l'Animator écrit la pose
3. Secondary    drag, ondes d'impact, regard          (PreRender)
4. Momentum     incline la colonne par-dessus         (PreRender)
5. FootPlanting résout les jambes au sol              (PreRender, après)
6. la physique avance, le drive du ragdoll tourne     (PreSimulation)
7. Balance      lit où le corps a atterri             (PostSimulation)
```

### Le pont entre les deux

Les limites articulaires et les foulées sont définies **en Python**, testées
là-bas, puis **générées** en Luau. Un test échoue si le fichier généré dérive.
C'est ce qui garantit que le rig physique ne peut pas contredire le rig
d'animation.

## Là où on est réellement proche

| Fonction | RDR2 | Linen | Verdict |
| --- | --- | --- | --- |
| Pieds ancrés sur le relief | Oui | Oui (`IKControl`) | **Comparable** |
| Absence de patinage | Oui | Oui (cadence calée sur la foulée) | **Comparable** |
| Inertie, inclinaison en virage | Oui | Oui | **Proche** |
| Overlapping / follow-through | Oui, animé à la main | Oui, procédural | **Proche** |
| Perte d'équilibre progressive | Oui | Oui (marge en studs) | **Proche** |
| Onde de réaction à l'impact | Oui | Oui, procédurale | **Proche en lecture, pas en variété** |

Sur ces six lignes, un joueur ne saurait probablement pas dire lequel est
lequel — sur un plan fixe et sans regarder le rendu.

## Là où on n'y est pas

| Fonction | RDR2 | Linen |
| --- | --- | --- |
| Bibliothèque d'animations | Des milliers de clips mocap | ~30 poses écrites à la main |
| Comportements de réaction | ~90, réglés individuellement | ~5 |
| Réaction par zone touchée | Ventre, tête, jambe, bras… | Une onde générique |
| Blessure persistante | Le perso protège son bras | Rien |
| Rattrapage (rebord, objet) | `grab` | Rien |
| Auto-évitement des membres | `configureSelfAvoidance` | Rien |
| Tonus musculaire | Modèle musculaire | `AlignOrientation`, analogue grossier |
| Colonne vertébrale | Plusieurs vertèbres | **Une** (`Waist`) |
| Multijoueur | Sans objet (solo) | Le vrai mur |

## Ce qui fermerait le plus l'écart

Contre-intuitif, mais c'est ce que dit la structure de RDR2 : **le gain n'est
pas dans plus de code runtime.**

L'essentiel de son réalisme vient de la **couche 1** — de la vraie captation, en
quantité. Or c'est précisément ce que Linen sait déjà ingérer, et c'est gratuit.

1. **Filme tes propres poses clés avec FreeMoCap** et verse-les dans la banque.
   Chaque pose remplacée par du mouvement humain réel améliore *toutes* les
   animations générées, la previs comme le jeu. C'est le meilleur rapport
   effort/résultat du projet, et de loin.
2. **Élargis le vocabulaire de réaction** — touché au ventre, à la tête, à la
   jambe. Cinq comportements de plus valent mieux qu'un solveur de plus.
3. **Des poses de freinage**, pour l'arrêt depuis la course. C'est de
   l'animation, pas de la procédure, et c'est l'un des détails les plus
   reconnaissables de RDR2.
4. **Traite la propriété réseau tôt.** C'est le problème qu'Euphoria n'a jamais
   eu, et celui qui te coûtera le plus de temps.

## Le verdict

Tu es en train de construire l'un des meilleurs systèmes de mouvement de
personnage sur Roblox. Ce n'est pas RDR2, et l'écart ne se comble pas par du
code : il se comble par **du contenu capté**, exactement ce que la première
moitié de ce projet a été construite pour produire.

Les deux moitiés se rejoignent là. C'était le plan depuis le début.
