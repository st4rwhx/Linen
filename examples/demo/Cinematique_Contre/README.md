# `Contre` — la bagarre, et ce qui lui manque encore

Le Hero se fait plaquer au mur et frapper, il contre, plaque l'Enemy à son
tour, lui prend son couteau et le lance.

**22 temps, 7,45 s, deux acteurs.** La feuille de temps est dans
[`examples/contre.scene.json`](../../contre.scene.json), en JSON lisible : un
temps par ligne, avec son instant et sa durée.

| Ce qui est en place | |
| --- | --- |
| Le minutage | chaque réaction est posée contre le coup qui la cause — la tête part 0,13 s après le poing, le couteau quitte la main 0,18 s après le lancer, la tête de l'Enemy part 0,22 s après ça |
| La caméra | 8 coupes sur 5 plans, du large au gros plan sur le couteau, avec dérive et fondus |
| Le couteau | `release` sur l'Enemy, `attach` sur le Hero, `throw` avec impulsion — trois événements à 40 ms d'écart |
| Les visages | colère, douleur, détermination, surprise, en FACS |
| Les marqueurs | 4 par acteur, dans l'animation elle-même, donc ils survivent à la publication |

## Ce qui ne va pas encore, et pourquoi

**Le mouvement.** Regarde la pellicule : l'Enemy marche, lève les bras, reste
debout. Ce n'est pas une empoignade, ce n'est pas un plaquage, et personne ne
glisse le long d'un mur.

La raison n'est pas un réglage. Le vocabulaire de poses connaît **douze
verbes** — marcher, courir, frapper, encaisser, reculer, s'accroupir… Il n'a
aucun mot pour *attraper*, *pousser contre un mur*, *retourner un bras*,
*lancer* ou *glisser au sol*. Demandé, il répond avec le plus proche qu'il
connaisse, et ça se voit.

**Ce qui manque n'est pas du code, ce sont des captures.** Le squelette de la
scène — minutage, caméra, accessoires, visages — est juste. C'est le mouvement
qui doit venir d'ailleurs.

```bash
# 1. des vraies captures dans un dossier (Mixamo exporte du .dae directement)
linen library build mes_captures/ -o combat.json

# 2. la meme scene, jouee par elles
linen scene examples/contre.scene.json --library combat.json \
     --place place.json --animations publish.json -o cinematique
```

Un temps que la bibliothèque sait répondre est joué par la capture ; les autres
restent dessinés. La sortie le dit pour chacun : `[library:<clip>]` ou
`[offline]`.

Les clips Mixamo qui répondent exactement à cette scène : **Grab**,
*Pushing*, *Shove Reaction*, *Body Jab*, *Head Hit*, *Stunned*,
*Take Weapon*, *Throw Object*, *Falling Back Death*. Mixamo est gratuit pour un
usage commercial illimité.

## Ce qu'aucune capture ne réglera

**Le contact.** Que la main se ferme *sur le col*, que le dos touche *le mur*,
que le couteau entre *dans la tête* — ça demande un solveur IK avec collision
sur deux rigs de proportions inconnues, et Linen ne l'a pas. Tu auras la mise
en scène et le minutage, qui font l'essentiel de ce qui se lit. Les derniers
centimètres se règlent à la main, dans l'éditeur ou dans Moon Animator
(`--moon`).
