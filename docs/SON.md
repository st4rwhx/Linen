# Le son : comment un studio place les bruitages, et comment Linen le fait

> « Pour éviter de gérer les sons frame par frame il faut un truc intelligent :
> vu qu'on sait qu'ils se battent, à chaque coup qui rentre en contact avec les
> mains, ce son se lance. Et la cinématique nous dit : voilà les variables dont
> j'ai besoin, insère l'id des coups de poing ici, celui des sauts là, et pour
> l'ambiance il me faut quelque chose de tendu, un drone, un tremblement qui
> fait sentir qu'on est mal en point. »

C'est exactement ce que fait un département son. Ce document dit comment, et ce
que Linen en reprend.

---

## Comment ça se passe vraiment, chez eux

### 1. La *spotting session*

Avant qu'un seul son soit posé, le réalisateur et le monteur son regardent le
film ensemble et marquent chaque endroit où la bande-son doit faire quelque
chose. Le résultat s'appelle une **feuille de repérage** (*spotting sheet*), et
chaque ligne porte une catégorie :

| Code | Ce que c'est |
| --- | --- |
| **DX** | dialogue |
| **FX** | effets (impacts, armes, verre) |
| **FOL** | foley (pas, tissu, objets manipulés) |
| **BG** | fonds, ambiances de lieu |
| **MUS** | musique |

Personne ne compte des frames à la main. **C'est l'image qui dit où vont les
repères.** Le monteur son regarde, et marque.

### 2. Les sons ne sont pas déclenchés par du code, mais par l'animation

Dans Unreal ou Unity avec Wwise ou FMOD, un pas ne se joue pas parce qu'un
script a mesuré une vitesse. Il se joue parce que l'animation contient une
**notify** — un repère nommé, posé sur la frame exacte où le talon touche. Les
studios vont jusqu'à séparer talon et pointe sur deux repères différents.

Roblox a exactement le même mécanisme, et c'est celui que Linen utilise déjà
pour tout le reste : le **`KeyframeMarker`**.

```lua
track:GetMarkerReachedSignal("linen_spot"):Connect(function(value)
    -- "punch_impact|0.580|RightHand"
end)
```

Frame-exact, et il voyage *dans* l'animation : une fois publiée, elle porte ses
propres pas et ses propres impacts.

### 3. Un seul chiffre pilote toute la bande-son

Les middlewares appellent ça un **RTPC** (*real-time parameter control*) : une
valeur continue que le jeu met à jour et dont dépendent volumes, filtres et
couches musicales.

RDR2 en est l'exemple le plus connu. Woody Jackson a enregistré une dizaine de
**stems** — des couches d'orchestre bouclées de quatre à cinq minutes, dans le
même tempo et la même tonalité pour qu'elles s'empilent sans se battre. Un
système interne surnommé le **« Gunfight Conductor »** décide en direct
lesquelles jouent et à quel niveau. Il n'y a pas de « musique de combat » : il y
a une intensité, et une partition qui y répond.

C'est ce qui distingue une bande-son qui *accompagne* d'une bande-son qui
*commente*.

### 4. Jamais deux fois le même son au même niveau

Rejouer le même échantillon à volume constant est le défaut le plus
reconnaissable de l'audio de jeu amateur — l'« effet agrafeuse ». Chaque
déclenchement varie en volume et en hauteur.

---

## Ce que Linen en fait

Linen fait la spotting session tout seul, parce que l'image est déjà dans le
fichier.

Les clips contiennent la rotation de chaque partie sur chaque frame. La
cinématique directe donne donc la position dans le monde des deux poings, des
deux pieds et de la tête, sur chaque frame de la prise. À partir de là :

| Ce qu'on cherche | Comment on le mesure |
| --- | --- |
| Un coup qui part | le membre dépasse 28 studs/s |
| Où il touche | la frame de freinage maximal après le pic |
| S'il touche | distance de surface au corps d'en face, sur *cette* frame |
| Un pas | la semelle atteint le bas de sa course près du sol |
| Une réception | même chose, mais en descendant vite |
| Une chute | la tête descend loin et s'arrête |
| Un objet lancé | la feuille de plateau connaît déjà sa durée de vol |
| Une réplique | elle est écrite dans la scène |

```
$ linen scene examples/disarm.scene.json --planner offline -o build/

Conduite son — Disarm

slot            cat    n  quand                       il te faut
punch_impact    FX     1  2.03s                       Impact d'un poing sur un corps — sourd, court, avec du grave
footstep        FOL    7  0.20, 0.50, 0.80...s        Un pas...
jump_land       FOL    1  3.43s                       Réception au sol après un saut ou une chute
effort          DX     1  1.95s                       Souffle ou grognement d'effort
prop_throw      FX     1  1.94s                       Objet qui quitte la main et fend l'air
prop_impact     FX     1  2.26s                       L'objet arrive sur le décor
dialogue        DX     2  2.67, 4.42s                 1. Hahaha, you couldn't even swing me!; 2. Nooo...
ambient_bed     BG     -  0.00-4.72s (nappe)          Le fond permanent du lieu
tension_drone   MUS    -  1.11-4.72s (nappe)          Nappe grave et tenue, qui monte quand ça chauffe
riser           MUS    1  1.33s                       Montée juste avant le point culminant
sting           MUS    1  2.73s                       Frappe musicale sur le pic
heartbeat       MUS    -  0.00-4.72s (nappe)          Battement de cœur — Thug encaisse plus qu'il ne donne

Tension (0-1, échantillonnée) :
                  ▁▂▃▄▄▄▄▄▄▄▄▄▄▄▄▃▃▃▃▃▃▃▃
  pic à 0.62
```

Personne n'a écrit que Thug était mal en point. Chaque coup qui touche
enregistre **qui** il touche ; le battement de cœur va à celui qui encaisse plus
qu'il ne donne. Si tu inverses le combat, le cœur change de camp tout seul.

### Le fichier que tu remplis

Une seule chose ne peut pas être devinée : quel fichier audio jouer. Elle
revient dans `Disarm.audio.json` :

```json
{
  "sounds": {
    "punch_impact": "",
    "footstep": "rbxasset://sounds/action_footsteps_plastic.mp3",
    "effort": "rbxasset://sounds/uuhhh.mp3",
    "tension_drone": "",
    "heartbeat": ""
  }
}
```

Tu colles les identifiants une fois. **Les valeurs déjà remplies survivent à
toutes les régénérations suivantes** — allonge une cue, ajoute un plan, refais
la scène : le fichier garde tes ids et n'ajoute que les nouveaux slots.

### Ce que Roblox te donne déjà gratuitement

Les slots marqués `rbxasset://` ne sont pas des assets publiés : ce sont des
fichiers **à l'intérieur du client Roblox**. Rien à uploader, rien à faire
modérer, aucune condition de compte, et personne ne peut les retirer.

| Slot | Fichier |
| --- | --- |
| `footstep` | `rbxasset://sounds/action_footsteps_plastic.mp3` |
| `jump_land` | `rbxasset://sounds/action_jump_land.mp3` |
| `effort` | `rbxasset://sounds/uuhhh.mp3` |

Pour le reste, le Creator Store contient **plus de 100 000 sons professionnels
libres d'usage** (Toolbox → Creator Store → Audio). La feuille te donne les
mots-clés de recherche pour chacun.

Et le dialogue reste à toi : c'est là que vont tes rendus ElevenLabs, une piste
par réplique, listées dans l'ordre.

### La courbe de tension

Chaque impact chauffe la scène, et ça refroidit tout seul entre deux. La somme
passe par une saturation douce — un enchaînement reste plus tendu qu'un coup
isolé, sans jamais coller au plafond. Un plan coupé chauffe un peu aussi : le
montage crée de la tension même en silence.

Cette courbe est écrite dans le script généré, et le runtime la lit en direct :

- le **volume du drone** la suit, donc il gonfle en entrant dans l'échange ;
- le `TremoloSoundEffect` du bus musique ouvre sa **profondeur** avec elle —
  c'est le tremblement, une instabilité qu'on sent plus qu'on ne l'entend ;
- l'`EqualizerSoundEffect` du bus effets **coupe les aigus et pousse les
  graves** quand ça monte : le monde se referme.

Le drone démarre une seconde *avant* le premier coup. Arriver avec le coup, ça
l'annonce ; arriver avant, ça le rend inévitable.

### Deux bus, et pas un son qui sorte deux fois pareil

Tout passe par un `SoundGroup` `LinenSFX` ou `LinenMusic`. Chaque déclenchement
porte une intensité, tirée de la vitesse de la frappe, qui module le volume et
la hauteur avec un peu de jitter. Deux coups de poing identiques ne sonnent pas
identiques.

---

## Les erreurs que cette couche a déjà attrapées

Elles ont toutes été de vraies erreurs pendant l'écriture, et chacune a un test.

**Onze coups de poing dans une promenade.** La vitesse seule ne suffit pas : un
saut, un salut et une célébration lancent tous un membre à plus de 50 studs/s.
Ce qui les sépare, c'est la **direction** — un coup finit *devant*. Mesurée sur
les seize actions du planificateur et les deux rigs : coup de poing et
désignation finissent à 2,0-2,3 studs devant le torse, le salut à 0,9, le saut à
0,2, l'encaissement à −1,3, derrière.

**Un bras est aussi long baissé que tendu.** La première version testait
l'*allongement* du bras depuis le torse, ce qui ne bouge presque pas quand on
frappe droit devant. C'est la portée vers l'avant qui compte.

**Le son du coup arrivait à la fin du geste.** Placé là où le membre s'arrête
complètement, il tombait deux dixièmes trop tard — le poing était déjà revenu.
L'impact, c'est le **freinage le plus fort après le pic**, pas le repos.

**R6 était muet.** Une partie R6, c'est tout le bras : son centre est à un stud
des phalanges. Mesuré au centre, un coup R6 rate toujours et un pied R6 ne
touche jamais le sol. Tout se mesure maintenant à l'extrémité de la partie —
le poing, la semelle.

**Les pieds ne s'arrêtaient jamais.** Chercher un pied *immobile* ne trouve rien
ici : les clips n'ont pas de translation de racine, donc le personnage marche
sur place et le pied posé glisse vers l'arrière à 3 studs/s, comme sur un tapis.
Le contact se trouve comme en analyse de la marche : au **bas de la course
verticale** de la semelle. Résultat : 1,8 pas/s en marche, 3,2 en course, 0 à
l'arrêt.

**La courbe de tension restait collée à 1,00.** Additionner les à-coups sature
après trois impacts et la courbe devient plate, ce qui revient à ne pas en
avoir.

**La même seconde dramatique était soulignée deux fois.** Deux *stings* à trois
dixièmes d'intervalle, c'est un seul moment compté deux fois.

**Un coup touchait parce que la victime passait là deux secondes plus tard.** La
distance se compare sur *la même* frame.

**Un pied replié sur un saut passait tous les tests.** Un membre qui vient de
toucher le sol ne portait pas un coup.

---

## Ce qui reste à toi

- **Trouver et uploader les sons.** Linen dit lesquels, quand, et avec quels
  mots-clés les chercher. Il ne peut pas inventer un identifiant.
- **Rapprocher les acteurs si rien ne touche.** La feuille le dit quand ça
  arrive : *« 1 coup détecté mais aucun ne touche : les acteurs sont trop loin
  l'un de l'autre »*. Un coup de poing porte à peu près 2 studs.
- **Vérifier dans Studio.** Rien de tout ça n'a encore tourné une seule fois.

> Roblox modère les audios uploadés, et les sons de plus de six secondes sont
> restreints selon ton compte. Uploade tôt.
