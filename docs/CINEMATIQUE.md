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

## Le son, et ElevenLabs

Ton idée est bonne, avec une nuance importante.

**Ce qui marche :** tu génères le dialogue et les bruitages sur ElevenLabs, tu
les uploades sur Roblox, tu récupères les `rbxassetid://`, et tu les mets dans
le champ `asset` de l'événement. Le timing est géré par l'ancrage — tu n'as
jamais à compter des frames.

**Ce qui ne marche pas :** laisser Linen « choisir » un son. Le planificateur ne
peut pas inventer un asset ID. Le bon partage est :

- **toi** : tu génères et uploades les sons, tu notes les IDs ;
- **le modèle** : il place les événements sonores aux bons instants et te dit
  *quel type* de son il attend à chaque endroit (`notes`) ;
- **Linen** : il garantit que ça tombe à la frame près.

> Roblox modère les audios uploadés, et les sons de plus de 6 secondes sont
> restreints selon ton compte. Uploade tôt, ne découvre pas ça la veille.

---

## Le décor

C'est la partie que Linen ne fait **pas**, et il ne faut pas se raconter
d'histoires : générer un décor Roblox depuis un prompt, ce n'est pas le même
problème que générer du mouvement.

Ce que Linen fait : il **nomme** ce dont la scène a besoin. `at_part: "Wall"`,
`source: "ReplicatedStorage.Props.Pistol"`, `effect: "WallImpact"`. Le script
généré cherche ces objets et **dit lesquels manquent** au lieu d'échouer en
silence.

Tu construis le décor une fois dans Studio ; la scène s'y branche par nom.

---

## L'état réel, sans enrobage

| | État |
| --- | --- |
| Cast, cues ancrés, timing | **Fait et testé** |
| Une animation par acteur, sans dérive | **Fait et testé** |
| Marqueurs d'événements frame-exacts dans le `.rbxmx` | **Fait et testé** |
| Format de scène : props, plans, son, VFX, visages, répliques | **Fait et testé** |
| Écrire la scène depuis un prompt (LLM) | **Fait**, non exécuté faute de modèle ici |
| Script Studio : mise en place + lecture synchrone | **Fait**, jamais exécuté |
| Script Studio : caméra, props, VFX, visages, répliques | **Pas encore** — c'est la prochaine étape |
| Visualiseur 3D interactif | **Pas encore** |
| Décor généré | **Non, et ce n'est pas prévu** |

Rien de ce qui touche à Studio n'a encore tourné une seule fois. C'est le risque
numéro un du projet, et il grossit à chaque brique ajoutée.
