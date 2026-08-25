# Être meilleur qu'un animateur pro — la partie qui est vraie

Un animateur juge à l'œil. Il regarde un pied posé, et il s'arrête quand ça a
l'air immobile.

**Un nombre ne s'arrête pas.** Personne qui travaille à la main ne sait que son
pied glisse de 1,34 stud par appui, parce que personne qui travaille à la main
ne *peut* le savoir. C'est là, et seulement là, qu'on passe devant : pas en
étant plus malin, en mesurant.

```bash
linen prompt "il marche" --library cmu.json --polish -o marche.rbxmx
```

```
finition — R15
  avant appuis  5 — glissement max 1,11 studs, moyen 1,01
  apres appuis  5 — glissement max 0,05 studs, moyen 0,03
```

## Les chiffres, sur de la vraie captation studio

Ce n'est pas mesuré sur des clips fabriqués pour bien se comporter. C'est la
base CMU — de la mocap professionnelle, reciblée sur R15 :

| Prise | Appuis | Glissement max | Moyen | |
| --- | --- | --- | --- | --- |
| marche (`02_01`) | 7 | 1,34 → **0,07** stud | 1,08 → **0,05** | −96 % |
| course (`02_03`) | 4 | 0,82 → **0,10** | 0,74 → **0,07** | −90 % |
| sauts (`01_01`) | 29 | 1,45 → **0,40** | 0,98 → **0,09** | −90 % |
| coups (`02_05`) | 6 | 1,43 → **0,95** | 0,94 → **0,23** | −75 % |
| navigation (`09_12`) | 27 | 2,48 → **0,64** | 1,60 → **0,10** | −94 % |

Un pied R15 fait 0,86 stud de long. Un glissement de 0,05 stud, c'est **un
dix-septième de pied** — invisible. 1,6 stud, c'est presque deux longueurs de
pied par appui, et ça, ça se voit.

**Regarde-le :**
[`examples/demo/Appuis_avant_apres.html`](../examples/demo/Appuis_avant_apres.html)
— la même marche deux fois, côte à côte, de profil. Bleu : avant. Orange :
après.

---

## Ce qui est mesuré, et ce qui est corrigé

Cinq défauts, tous des signatures connues d'animation amateur. **Les cinq sont
maintenant corrigés**, chacun avec sa précaution.

| Défaut | Mesure | Correction |
| --- | --- | --- |
| **Patinage des pieds** | studs par appui | IK analytique à deux os (R15) ou visée de la jambe (R6) |
| **Arcs cassés** | degrés de virage sur une fenêtre de 40 ms | remplacement de l'image isolée fautive |
| **Poses figées** | images où la pose est *identique* | *moving hold* : la pose dépasse un peu et revient |
| **Articulations à l'envers** | images où un genou passe derrière la ligne hanche-cheville | rapporté (c'est le solveur amont qu'il faut corriger, pas le clip) |
| **Symétrie parasite** | corrélation du balancement signé | décalage d'une demi-foulée — **sur demande seulement** |

```bash
linen prompt "..." --library cmu.json --polish            # les quatre corrections sûres
linen prompt "..." --library cmu.json --polish --desync   # + le décalage de symétrie
```

L'ordre n'est pas arbitraire : régler un maintien déplace des membres, lisser un
arc les déplace encore, donc **la pose des pieds passe en dernier**. Sinon les
deux passages précédents la défont en silence.

### Les poses figées

Une pose qui s'arrête *exactement* lit comme un arrêt sur image. Le correctif
d'animateur s'appelle un *moving hold* : la pose porte un peu au-delà de son
point d'arrêt et revient.

C'est donc un **settle**, pas du bruit. La direction vient du mouvement qui
entre dans le maintien, l'amplitude de sa vitesse, et les deux sont plafonnées
dur : un degré ou deux, c'est un corps qui respire ; cinq, c'est une nouvelle
action. Seules les parties qui bougeaient en héritent, au prorata.

Et les deux images aux bords du maintien sont rendues **intactes** : ce sont
celles de l'animation, et un settle qui ne les rend pas telles quelles crée une
discontinuité à l'endroit même qu'il devait adoucir.

> Le seuil de détection est volontairement minuscule (0,25 °/s sur tout le rig).
> Un maintien *lent* est ce qu'un maintien doit être ; le défaut, c'est
> l'**image répétée**. De la vraie captation ne descend jamais là-dessous, parce
> qu'un vrai corps ne peut pas. Les poses de synthèse, elles, sont à zéro pile.

### Les arcs

Une extrémité doit décrire une courbe. L'angle se mesure sur une **fenêtre de
40 ms**, pas d'une image à la suivante — première version, et à 120 Hz elle
comparait des déplacements de six millièmes de stud, où la direction n'est plus
que de l'arrondi : toutes les prises ressortaient pleines d'arcs cassés.

Seuls les angles **isolés** sont corrigés, et cette restriction est toute la
conception. Une main qui change brutalement de direction n'est pas un défaut,
c'est un coup qui porte, et l'adoucir serait du vandalisme. Le défaut, c'est une
image qui contredit ses deux voisines — la signature d'une erreur de reciblage.
Les angles au bord d'un appui sont exclus d'office : la pose du talon et le
décollement de l'orteil sont les deux instants d'un pas où le pied inverse
volontairement.

Le résultat est chirurgical : sur `09_12`, **3 images-parties touchées sur
28 785**. Sur une marche et un enchaînement de coups propres, **aucune**.

### La symétrie

Un saut à deux pieds a les deux jambes qui font exactement la même chose au même
instant. **Ce n'est pas un défaut à corriger, c'est ce qu'est un saut.**

Donc la mesure regarde d'abord la démarche : les appuis alternent-ils, ou les
deux pieds travaillent-ils ensemble ? Sur `01_01` (sauts en avant), le rapport
dit « mouvement symétrique — normal » et `--desync` **refuse de toucher au
clip**. Sur une marche, il ne se déclenche pas non plus, parce qu'une marche est
déjà en opposition.

Et `--desync` reste en option, pour deux raisons qui sont les mêmes : il suppose
le clip cyclique — décaler une piste l'enroule, donc une prise qui n'était pas
une boucle gagne une couture à l'image zéro — et une demi-foulée est le seul
décalage qui veuille dire quelque chose, donc il exige une période mesurée et
refuse plutôt que de deviner.

### R6

Une jambe R6 est **une seule part rigide** : pas de genou, donc la semelle
atteint une **sphère**, pas un volume. Une cible ailleurs ne peut pas être
atteinte, et prétendre le contraire reviendrait à étirer une part.

La jambe est donc **visée** : tournée pour que la semelle tombe sur le point de
la sphère le plus proche de sa cible.

| Prise | R6, glissement moyen |
| --- | --- |
| marche `02_01` | 1,84 → **0,05** stud |
| navigation `09_12` | 1,85 → **0,03** |
| course `02_03` | 1,62 → 1,21 |

La course résiste, et c'est la limite honnête d'un membre rigide : en course la
jambe est trop pliée pour qu'une part droite atteigne la cible. C'est rapporté,
pas caché.

---

## La subtilité qui a failli tout casser

Sur une animation Roblox **le bassin est cloué**. Donc un pied correctement
planté **ne reste pas immobile** dans l'espace du rig : il recule exactement à
la vitesse à laquelle le personnage avance, et le moteur annule ce recul en
déplaçant le personnage.

Exiger un pied immobile aurait donc « corrigé » une marche parfaite en
moonwalk.

Le patinage, c'est **l'écart à cette droite**, pas sa longueur. Et la vitesse de
la droite se mesure sur les appuis eux-mêmes, par la médiane : le patinage,
c'est les pieds qui ne sont pas d'accord sur la vitesse du sol, donc le
consensus est exactement ce vers quoi il faut ramener les dissidents.

---

## Trois bugs que les nombres seuls n'auraient pas vus

Ils comptent parce qu'ils disent pourquoi il faut *à la fois* des mesures et
des tests. Les trois faisaient baisser un chiffre.

**1. Le fondu était à l'intérieur de l'appui.** Les images qu'un appui a le plus
besoin de voir corrigées sont sa première et sa dernière — là où le pied arrive
et repart. Fondre là laissait le patinage visible intact et corrigeait le milieu
que personne ne regardait. Le papier fond **à l'extérieur** ; dans l'appui la
contrainte est exacte.

**2. Les seuils étaient en images, pas en secondes.** Trois images, c'est un
vrai seuil à 30 fps et un vingt-cinquième de pas à 120 fps, la cadence de CMU.
Résultat : le fondu de sortie d'une correction était relu comme un nouvel appui
de quatre images, et le maximum sautait.

**3. L'axe du genou était relu à chaque image.** Un genou qui passe par la
position tendue en plein appui n'a plus de direction lisible, et l'axe basculait
d'un côté à l'autre : **38° d'écart sur une seule image**. Tous les chiffres du
rapport appelaient ça un succès. C'est un test synthétique qui l'a attrapé — pas
la mocap réelle, qui avait déjà assez de bruit pour le masquer. L'axe est
maintenant fixé une fois par appui, lu sur l'image où le genou est le plus plié.

Et une erreur de conception, dans la mesure elle-même : la symétrie était
d'abord comparée sur la **vitesse** angulaire. Dans une marche saine les deux
bras atteignent leur vitesse maximale au même instant, en passant au milieu de
leur balancement — une marche correcte notait 0,93 et ressortait comme le pire
défaut du clip. Comparée sur l'angle **signé**, une marche en opposition note 0
et seul le vrai lockstep note 1.

---

## Ce que la recherche a donné, et ce qui est utilisable

La question posée était : que font les studios que nous ne faisons pas ? La
réponse tient en une ligne de licence.

| Piste | Verdict |
| --- | --- |
| **DeepPhase / AI4Animation** (Starke, SIGGRAPH 2022, *Best Paper*) — variétés de phase apprises, l'état de l'art de la locomotion | **Inutilisable tel quel.** Le dépôt dit : *"only for research or education purposes, and not freely available for commercial use"*, et sa mocap est en CC BY-NC 4.0 |
| **Footskate Cleanup** (Kovar & al., 2002) — IK analytique | **Utilisable.** Papier académique, algorithme, implémenté ici sur des données CMU à licence commerciale |
| **UnderPressure** (Mourot & al., 2022) — contacts et forces de réaction au sol par réseau | Piste sérieuse pour la détection des appuis ; à évaluer côté licence |
| **Motion matching / inertialisation** (Ubisoft La Forge, Holden) | **Déjà dans Linen** |

Le point important : **un algorithme publié n'est pas un jeu de poids
entraîné.** On ne peut pas prendre le modèle de DeepPhase. On peut lire le
papier de 2002 et l'implémenter sur de la donnée qui, elle, autorise le
commercial. C'est exactement ce qui a été fait.

---

## Ce qui reste

Un seul défaut est mesuré sans être corrigé : **les articulations qui plient à
l'envers**. C'est délibéré. Un genou à l'envers n'est pas un défaut du clip,
c'est un défaut du solveur qui l'a produit — le rattraper après coup masquerait
la cause. Le rapport le signale pour qu'on aille le corriger en amont.

## Ce qui n'est pas vérifié

Les corrections sont vérifiées **numériquement** (31 tests, dont des clips
synthétiques où le glissement est connu d'avance par géométrie) et
**visuellement** dans le visualiseur. Elles n'ont pas été jouées dans Roblox
Studio.

---

## Sources

- Kovar, Schreiner, Gleicher — [*Footskate Cleanup for Motion Capture
  Editing*](https://graphics.cs.wisc.edu/Papers/2002/KSG02/cleanup.pdf), SCA 2002
- Starke, Mason, Komura — [*DeepPhase: Periodic Autoencoders for Learning Motion
  Phase Manifolds*](https://dl.acm.org/doi/10.1145/3528223.3530178), SIGGRAPH 2022
- [AI4Animation](https://github.com/sebastianstarke/AI4Animation) — le code, et
  sa licence non commerciale
- Mourot & al. — [*UnderPressure*](https://github.com/InterDigitalInc/UnderPressure),
  SCA 2022
