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

## Ce qui est mesuré

`--polish` mesure quatre choses, qui sont quatre signatures connues d'animation
amateur.

**Le patinage des pieds.** En studs, par appui. Voir plus bas pour la
subtilité, parce qu'elle est réelle.

**Les articulations qui plient à l'envers.** Un genou qui passe derrière la
ligne hanche-cheville, un coude qui passe devant. Pas « un membre tendu » — un
membre tendu est normal, c'est la position de repos de tout le monde.

**Les poses figées.** Un maintien *parfaitement* immobile lit comme un arrêt
sur image. Les animateurs appellent le correctif un *moving hold*.

**La symétrie parasite.** Les deux côtés du corps qui font la même chose au
même instant, ce qui est la chose la plus mécanique qu'un corps puisse faire.
En opposition, c'est une marche ; en phase, c'est une machine.

## Ce qui est corrigé

**Les appuis, exactement**, avec l'IK analytique de *Footskate Cleanup for
Motion Capture Editing* (Kovar, Schreiner et Gleicher, SIGGRAPH SCA 2002). Leur
fonction de fondu `a(t) = 2t³ − 3t² + 1` — l'unique cubique qui vaut 1 en 0, 0
en 1 et qui est plate aux deux bouts — est reprise telle quelle : c'est elle
qui empêche la correction de claquer à la sortie de l'appui.

Deux écarts au papier, tous les deux subis, tous les deux dits là où ils
mordent :

- Le papier peut **déplacer la racine** quand la cible est hors de portée. Un
  clip Linen exporté sur place a le bassin cloué — c'est ce qui en fait une
  animation Roblox et pas une cinématique — donc une cible hors de portée est
  ramenée à jambe tendue, et le reste est **rapporté**, pas absorbé en silence.
- Le papier **étire** un membre en dernier recours. Une part Roblox a une taille
  fixe : cette option n'existe pas ici.

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

## Ce qui est mesuré mais pas encore corrigé

Dit franchement, parce que c'est la suite :

- **Les poses figées** — détectées, pas encore animées. Le correctif est une
  dérive lente ajoutée au maintien.
- **La symétrie parasite** — détectée, pas encore décalée. Le correctif est un
  décalage de phase de quelques images sur un côté.
- **Les arcs** — pas encore mesurés. Une extrémité qui trace une trajectoire à
  angles au lieu d'un arc est le tell classique.
- **R6** — mesuré, pas résolu. Une jambe R6 est une seule part rigide : pas de
  genou, donc rien pour résoudre.

## Ce qui n'est pas vérifié

Les corrections sont vérifiées **numériquement** (16 tests, dont des clips
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
