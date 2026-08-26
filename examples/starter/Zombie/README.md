# Zombies — 11 animations, boucle décidée par la mesure

Depuis `Scary Zombie Pack.rar`. R15 et R6, `.rbxmx` + `.html` à côté.

## La boucle, sans avoir à y penser

Tu demandais comment éviter que certaines animations s'arrêtent et pas d'autres.
Le test est mesurable : **le raccord de la dernière image vers la première doit
coûter autant qu'une image ordinaire de ce clip.**

Exprimé en rapport, pas en degrés, parce que l'échelle est celle du clip : une
course bouge de 60° par image et un idle de 1°, donc un seuil fixe en degrés
déclarerait la course cassée et l'idle parfait quoi qu'ils fassent.

| Animation | Raccord | Verdict |
| --- | --- | --- |
| `zombie_neck_bite` | 0,2× | bouclée |
| `zombie_scream` | 0,3× | bouclée |
| `zombie_idle` | 0,5× | bouclée |
| `zombie_crawl` | 0,6× | bouclée |
| `zombie_run` | 0,9× | bouclée |
| `zombie_attack` | 1,7× | bouclée |
| `running_crawl` | 1,8× | bouclée |
| `zombie_walk` | 2,2× | bouclée |
| `zombie_biting_2` | 2,8× | bouclée |
| **`zombie_death`** | **13,7×** | **jouée une fois** |
| **`zombie_dying`** | **13,5×** | **jouée une fois** |

Rien ne tombe entre 2,8 et 13,5 : le seuil est posé dans le trou, pas réglé à la
main. Les deux seules qui ne bouclent pas sont celles qui finissent au sol —
exactement les deux qu'on ne veut pas voir se remettre debout d'un coup.

C'est `--motion auto`, et c'est le **défaut** maintenant. Le rapport est imprimé
à chaque conversion, donc tu peux forcer avec `--motion loop` ou `--motion
in-place` si tu n'es pas d'accord.

> « Bouclable » n'est pas « doit boucler ». `zombie_attack` revient à sa pose de
> départ, donc la boucler ne fait pas de saut — mais dans ton jeu tu la joueras
> une fois, avec `:Play()`. Ce que la mesure garantit, c'est qu'aucune de ces
> animations ne **claque** au raccord.

## Ce qui a foiré

`zombie biting.dae` ne sort pas de l'archive : le RAR est tronqué dessus (262 Ko
extraits sur 436 Ko annoncés). Ce n'est pas la conversion, c'est le `.rar`.
`zombie_biting_2` couvre le même mouvement.

## Pourquoi les R6 ne ressemblaient pas à la page

**R6 ne mesure pas ses rotations dans les axes de la part.** Roblox compose une
articulation en `parent * C0 * Transform * C1:Inverse()`. R15 construit chaque
articulation alignée sur les axes, donc son `Transform` **est** la rotation
locale et s'écrit tel quel. R6 construit ses épaules et ses hanches **tournées
d'un quart de tour autour de Y**, et sa nuque et sa racine tournées autour de la
diagonale Y/Z.

Résultat : sur R6, une jambe qui part **en avant** est stockée comme une
rotation autour du **Z** de la pose, pas de son X. L'exportateur écrivait la
rotation locale directement — le fichier s'importe, il se joue, et le pas part
**de côté**. C'est exactement l'écart que tu as vu entre la page et Studio :
la page, elle, compose les rotations locales, donc elle était juste.

Ça se lit dans les animations que Roblox a écrites lui-même : sur les cycles de
course et d'accroupissement de ton propre jeu, les jambes sont à **0,85-0,99 de
Z**, alors que le torse — dont l'articulation est tournée autrement — est sur X.

Corrigé pour l'export `.rbxmx` **et** pour les sauvegardes Moon, avec cinq tests
et un test de bout en bout qui compare la page et le fichier **à travers** le
repère de l'articulation. Tous les `.R6.rbxmx` de ce dossier ont été régénérés.

> Les `.R15.rbxmx` n'ont jamais été touchés par ce bug : sur R15 la
> transformation est l'identité. C'est pour ça que le `Walk.rbxmx` R15 que tu as
> testé en premier marchait.

## Deux choses trouvées sur tes fichiers

**Le drapeau de boucle se perdait.** `plant_feet` reconstruisait le clip sans
reporter `loop` ni `priority`. Un cycle de marche exporté avec Loop à `false`
s'arrête net à chaque foulée dans Studio, et rien dans l'animation n'a l'air
faux — c'est pour ça qu'il a fallu que quelqu'un la joue pour le voir. Corrigé,
avec un test.

**Un `.dae` Mixamo est un ZIP.** Chacun de tes fichiers est une archive dont
l'unique entrée est le vrai XML. Le lecteur les déballe tout seul maintenant.

## Licence

Ce pack vient de Mixamo (squelette `mixamorig`, 65 os). Gratuit pour un usage
commercial illimité, mais **redistribution des fichiers bruts interdite**. Si ce
dépôt est public, mets ce dossier dans `.gitignore` avant publication.
