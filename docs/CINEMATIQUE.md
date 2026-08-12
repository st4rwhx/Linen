# Comment on fait une cinématique AAA sur Roblox

> « Le mec attrape l'ennemi, le désarme, jette son arme au mur, plan sur le mur
> qui encaisse, la caméra revient, le héros sourit et dit *Hahaha, you couldn't
> even swing me!*, l'autre répond *Nooo* — avec expressions, VFX, son. »

Ce document répond à ça : ce que font vraiment les devs Roblox, quelles briques
du moteur ils utilisent, et où Linen s'insère.

---

## Comment les autres font

Il n'y a pas de « CutsceneService » sur Roblox. Une cinématique est assemblée à
la main à partir de six briques indépendantes, et c'est le **timing entre elles**
qui fait toute la difficulté.

| Brique | Mécanisme Roblox |
| --- | --- |
| Le mouvement des corps | `AnimationTrack` joué sur un `Animator` |
| La caméra | `Camera.CameraType = Scriptable`, puis on écrit `Camera.CFrame` |
| Les objets tenus | `Motor6D` ou `WeldConstraint` sur `RightHand`, détruit pour lâcher |
| Les effets | `ParticleEmitter:Emit(n)`, `Beam`, `Trail` |
| Le son | `Sound:Play()`, positionnel s'il est dans une `BasePart` |
| Les visages | `FaceControls` sur une *dynamic head* — 50 poses FACS |

**L'outil communautaire dominant est [Moon Animator](https://create.roblox.com/store/asset/4725618216)** :
un éditeur multi-pistes dans Studio où l'on anime plusieurs rigs *et* la caméra
sur une timeline commune. C'est avec ça que sont faites la quasi-totalité des
cinématiques Roblox que tu as vues. C'est excellent, et c'est **entièrement
manuel** : chaque pose, chaque coupe caméra, chaque frame est placée à la main.

C'est précisément ce que Linen automatise.

---

## Le mécanisme central : `KeyframeMarker`

Voici la brique que la plupart des tutoriels ratent, et sans laquelle rien ne
tombe juste.

Un `KeyframeMarker` est une instance qu'on accroche à une `Keyframe` dans une
animation. À la lecture, Roblox déclenche :

```lua
track:GetMarkerReachedSignal("linen_sound"):Connect(function(value)
    -- value est la chaîne portée par le marqueur
end)
```

**C'est frame-exact.** Le coup de feu part sur la frame où la main s'ouvre, pas
« à peu près au même moment ». Et le marqueur voyage *dans* l'animation : une
fois publiée, elle porte ses propres événements.

Linen écrit des `KeyframeSequence` — il écrit donc ces marqueurs. C'est la
colonne vertébrale de tout le reste.

---

## Ce que ça donne concrètement

Ton scénario, écrit tel quel dans
[`examples/disarm.scene.json`](../examples/disarm.scene.json) :

```json
{ "kind": "prop",   "cue": "disarm", "offset": 0.14, "actor": "Thug",
  "prop": "Pistol", "action": "throw", "impulse": [0, 9, -75] },
{ "kind": "camera", "cue": "disarm", "offset": 0.34, "shot": "wall" },
{ "kind": "vfx",    "cue": "disarm", "offset": 0.46, "effect": "WallImpact", "at_part": "Wall" },
{ "kind": "camera", "cue": "disarm", "offset": 0.90, "shot": "two_shot" },
{ "kind": "face",   "cue": "settle", "offset": 0.10, "actor": "Hero", "expression": "smug" },
{ "kind": "line",   "cue": "settle", "offset": 0.35, "actor": "Hero",
  "text": "Hahaha, you couldn't even swing me!" }
```

```
$ linen scene examples/disarm.scene.json --planner offline -o build/

Disarm: 2 actors, 7 cues, 4.72s
    0.00s  Hero  approach   marche
    1.80s  Hero  disarm     coup de poing droite tres rapide et explosif
    2.00s  Thug  flinch     encaisse
    2.78s  Thug  recoil     recule vite
  Disarm_Hero.rbxmx: R15, 40 keyframes, 4 marqueurs d'evenement
  Disarm_Thug.rbxmx: R15, 31 keyframes, 4 marqueurs d'evenement
  6 evenements sur l'horloge du realisateur (camera, effets de decor)
```

### Le point qui change tout : l'ancrage

Aucun événement n'est écrit à un temps absolu. Tout est **ancré sur un cue** :
`"cue": "disarm", "offset": 0.14`.

Rallonge l'approche du héros d'une seconde, et le désarmement, le jet du
pistolet, la coupe caméra, l'impact au mur, le retour caméra, l'expression et la
réplique **se décalent tous ensemble**. Dans Moon Animator, il faudrait tout
redéplacer à la main.

C'est la différence entre une cinématique qu'on peut **monter** et une qu'on doit
**refaire**.

### Où va chaque événement

- **Lié à un acteur** (son de sa main, son expression, sa réplique, le pistolet
  qu'il lâche) → devient un `KeyframeMarker` dans **son** animation. Il survit à
  la publication et reste accroché même si tu retimes le clip dans Studio.
- **Sans acteur** (coupe caméra, impact sur le mur) → n'a aucune animation à
  chevaucher, va sur l'**horloge du réalisateur** dans le script généré.

---

## Les visages

R15 s'arrête au cou. Pour une vraie expression il faut une **dynamic head** :
un `MeshPart` skinné portant une instance `FaceControls` avec
[50 poses FACS](https://create.roblox.com/docs/art/characters/facial-animation/facs-poses-reference).

Linen expose des **noms d'expression** (`smug`, `angry`, `afraid`, `pain`,
`determined`, `laughing`…) plutôt que des coefficients FACS, pour qu'une scène
reste lisible. Le runtime les traduit en mélange de poses.

Sur une tête blocky classique, l'événement `face` est simplement ignoré — sans
erreur. C'est voulu : la scène reste valide, tu ajoutes les têtes quand tu veux.

---

## Le son : tu ne places rien à la main

Détaillé dans [`docs/SON.md`](SON.md). Le résumé :

Linen fait la **spotting session** tout seul — le nom que le cinéma donne à la
séance où on marque chaque endroit qui a besoin d'un son. Il n'a pas besoin que
tu le lui dises, parce que l'image est déjà dans le fichier : les clips
contiennent la rotation de chaque partie sur chaque frame, donc la cinématique
directe donne la position des deux poings et des deux pieds sur chaque frame de
la prise.

Un poing qui accélère puis freine brutalement à 0,7 stud du torse d'en face,
c'est un coup qui touche — et la frame où ça arrive est une mesure, pas une
estimation. Une semelle qui atteint le bas de sa course près du sol, c'est un
pas.

Il en sort une **conduite son** : des slots nommés (`punch_impact`, `footstep`,
`tension_drone`, `heartbeat`…), les instants exacts où chacun se déclenche, une
description de ce qu'il faut, et les mots-clés pour le trouver dans le Creator
Store. Tu colles les identifiants **une fois** dans `<Scène>.audio.json` ; ils
survivent à toutes les régénérations suivantes.

Trois slots sont déjà remplis avec des fichiers **livrés dans le client Roblox**
(`rbxasset://sounds/…`) : rien à uploader, rien à faire modérer, la scène fait
du bruit immédiatement.

**Ce qui reste à toi :** trouver les sons. Linen ne peut pas inventer un asset
ID. Tes rendus ElevenLabs vont dans le slot `dialogue`, une piste par réplique,
listées dans l'ordre.

> Roblox modère les audios uploadés, et les sons de plus de 6 secondes sont
> restreints selon ton compte. Uploade tôt, ne découvre pas ça la veille.

---

## Le décor : où le placer ? Ça se calcule.

Générer un décor depuis un prompt, non. Mais **savoir où il doit être**, oui —
et ce n'est pas une estimation, c'est une résolution.

Le pistolet quitte une main à un instant connu, avec une impulsion connue.
L'effet d'impact dit à quel instant il arrive. La gravité Roblox vaut
**196,2 studs/s²**. Deux temps connus et une gravité connue ne laissent qu'une
inconnue : la position. `linen scene` l'intègre et sort une **feuille de
plateau** :

```
Plateau — Disarm

objet           type      position (studs)          pourquoi
Wall            cible     (0.7, 2.1, -16.0)         Pistol lancé à 1.94s, impact à 2.26s (0.32s de vol)
Floor           sol       (0.0, -0.5, -2.0)         2 acteurs + 4 studs de marge

À fournir toi-même (la scène les nomme, elle ne peut pas les créer) :
  ReplicatedStorage.Props.Pistol         modèle de l'accessoire Pistol
  WallImpact                             ParticleEmitter ou effet nommé
```

Et un **blockout** : un `.rbxmx` de blocs gris, nommés et placés correctement,
que tu déposes dans Studio. La scène joue immédiatement ; tu remplaces ensuite
chaque bloc par du vrai décor, sans rien retoucher au timing.

### Ce que ça a déjà attrapé

En écrivant l'exemple, j'avais mis une impulsion de `[0, 9, -75]`. La feuille de
plateau a répondu : **mur à 232 studs de distance et 16 de haut**. C'était une
balle, pas un pistolet lancé. Corrigé avant d'ouvrir Studio une seule fois.

Puis elle a signalé que mes deux acteurs étaient **enterrés jusqu'à la taille** :
la position d'un personnage Roblox est celle de sa *racine*, qui se trouve à
hauteur de hanche (2,44 studs sur un R15). Placé à `y=0` sur un sol à `y=0`, il
a la moitié du corps sous terre.

Aucun des deux n'était visible dans le fichier de scène. Les deux auraient coûté
une session de débogage dans Studio.

---

## L'état réel, sans enrobage

| | État |
| --- | --- |
| Cast, cues ancrés, timing | **Fait et testé** |
| Une animation par acteur, sans dérive | **Fait et testé** |
| Marqueurs d'événements frame-exacts dans le `.rbxmx` | **Fait et testé** |
| Format de scène : props, plans, son, VFX, visages, répliques | **Fait et testé** |
| Feuille de plateau + blockout du décor | **Fait et testé** |
| Repérage son : impacts, pas, chutes, objets, répliques | **Fait et testé** |
| Courbe de tension, nappes, tremblement, filtre | **Fait et testé** |
| Écrire la scène depuis un prompt (LLM) | **Fait**, non exécuté faute de modèle ici |
| Script Studio : mise en place + lecture synchrone | **Fait**, jamais exécuté |
| Script Studio : caméra, props, VFX, visages, répliques | **Fait**, jamais exécuté |
| Script Studio : bus audio, sons repérés, ambiance | **Fait**, jamais exécuté |
| Visualiseur 3D interactif, avec caméra du réalisateur | **Fait**, et il tourne |
| Afficher un vrai rig Blender à la place des boîtes | **Fait**, et il tourne |
| Décor généré | **Non, et ce n'est pas prévu** |

Rien de ce qui touche à Studio n'a encore **tourné** une seule fois. C'est le
risque numéro un du projet.

Le visualiseur, lui, tourne : `<Scène>.html` s'ouvre dans un navigateur et joue
la prise. Il ne remplace pas Studio — il n'a ni la physique, ni les vraies
proportions d'avatar, ni les visages — mais il répond à la question que rien
d'autre ici ne posait : *est-ce que ça ressemble à ce qu'on a demandé*. Il a
déjà attrapé le plan `wall` de l'exemple, qui cadrait un mur gris et rien
d'autre.

Un cran a néanmoins été gagné : tout le Luau généré passe maintenant par le
**compilateur Luau officiel** et par `luau-analyze` en mode strict. Les scripts
de scène compilent et ne produisent aucune erreur de type autre que les globales
Roblox, qui n'existent pas hors de Studio. Ça a immédiatement attrapé deux vrais
défauts : une scène sans props ou sans plans émettait des tables vides non
typées, que Luau refuse d'itérer en mode strict ; et chaque bloc de rig généré
dans `RigLimits.luau` était rouge parce que `kind` s'inférait en `string` au lieu
de l'union `"ball" | "hinge" | "fixed"`.

« Ça compile » n'est pas « ça marche ». Mais « ça ne compile pas » aurait été
découvert au pire moment.

> Les modules de `runtime/` (ragdoll, équilibre, appuis, inertie) compilent aussi,
> mais `luau-analyze` y signale une quarantaine d'erreurs de type restantes. La
> majorité vient de l'absence des types Roblox hors Studio — l'arithmétique
> `Vector3` devient `unknown` — mais pas toutes. Elles sont antérieures à cette
> passe et pas encore triées.
