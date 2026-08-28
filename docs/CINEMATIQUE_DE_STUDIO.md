# Une vraie cinématique de studio, brique par brique

Recherche faite en août 2026 sur ce que les gros font réellement dans Roblox
Studio — caméra, visages, voix — et ce que Linen sait en faire.

---

## 1. La caméra : la moitié de l'effet, et elle est **cliente**

**Le fait qui casse tout et que personne ne dit assez fort :** la caméra
n'existe que chez le client. `workspace.CurrentCamera` vaut `nil` sur un
serveur. Un script serveur qui pilote la caméra place les corps, joue les
animations, **et ne montre rien à personne** — sans la moindre erreur.

C'était le cas de ce que Linen générait jusqu'ici. Le fichier s'appelle
maintenant `<Scene>.client.luau`, il va dans **StarterPlayer →
StarterPlayerScripts**, et il refuse de tourner ailleurs en le disant.

### Les trois mouvements qui font une cinématique

Ce que disent les guides d'animateurs Roblox, et ce que Linen écrit :

| | Ce que ça donne | Dans la scène |
| --- | --- | --- |
| **`static`** | plan fixe, avec une dérive lente — un plan parfaitement immobile se lit comme une capture d'écran, pas comme une caméra | `"kind": "static"`, `drift` |
| **`orbit`** | la caméra tourne autour du sujet. C'est *le* plan de révélation, celui que tout le monde appelle « cinématique » | `"kind": "orbit"`, `orbit_speed` en °/s |
| **`follow`** | décalage fixe par rapport au sujet : un personnage qui se déplace reste cadré pareil | `"kind": "follow"`, `follow_offset`, `follow_lag` |

```json
{ "id": "reveal", "position": [7, 4.5, 4], "look_at": "Hero",
  "kind": "orbit", "orbit_speed": 22, "fov": 55, "blend": 0.4 }
```

**Pourquoi ça tourne dans `BindToRenderStep` et pas en `TweenService`.** Une
orbite et un suivi dépendent de **où le sujet est maintenant**. Un tween vers un
`CFrame` figé ne peut pas suivre quelqu'un qui bouge — et dans une bagarre,
personne ne reste en place. Le plan est donc recalculé à chaque image, à
`Enum.RenderPriority.Camera`.

**Deux amortissements, et ce ne sont pas la même chose.**

- `blend` est la coupe : la durée que met la caméra pour aller au nouveau plan,
  lissée en `t²(3−2t)` pour qu'un changement de plan voyage au lieu de claquer.
- `follow_lag` est la main de l'opérateur. Une caméra soudée à son sujet se lit
  comme rigide ; un peu de retard, c'est ce qui la fait paraître *tenue*.

Et l'easing compte plus qu'on ne croit. Les guides le disent mot pour mot :
`Sine`, `Cubic`, `Quint`, `OutQuad`, `InOutSine` — jamais `Linear`. « Un rendu
film hollywoodien plutôt qu'une caméra de surveillance. »

> La boucle est **détachée** à la fin (`UnbindFromRenderStep`) et le
> `CameraType` rendu. Un render step qui survit à la scène garde la caméra en
> otage et le joueur ne peut plus bouger.

---

## 2. Les visages : générés, pas captés

Une **dynamic head** porte un objet `FaceControls` : **50 propriétés nommées**,
chacune entre 0 et 1, tirées du Facial Action Coding System. Plusieurs se
combinent dans la même image pour faire une expression complexe. 17 sont
obligatoires pour publier une tête sur la Marketplace.

Studio sait transformer une **webcam** en images-clés faciales (*Face Capture*,
en beta dans l'éditeur d'animation). C'est excellent — et **hors sujet ici** :
ça remet un humain dans la boucle à chaque plan, alors que tout l'intérêt de
cette chaîne est qu'une scène écrite sorte finie.

**Donc le visage est construit à partir de ce que la scène dit déjà.**

| D'où ça vient | Ce que ça donne |
| --- | --- |
| un événement `face` | l'expression, en poses FACS pondérées, **fondue** en entrée et en sortie |
| un événement `line` | la mâchoire et les lèvres traversent les **syllabes du texte** |
| rien du tout | ça **cligne des yeux**, décalé par acteur |

**Une expression est une courbe, pas un interrupteur.** Un visage posé sur une
expression et laissé là se lit comme un masque. Et chaque contrôle que
l'expression précédente utilisait est **ramené à zéro** — sinon un sourcil levé
il y a trois temps est encore levé sous un sourire, et le visage s'accumule
lentement en grimace.

**Le lip-sync vient du texte, pas de l'audio.** Il n'y a pas encore d'audio
quand la scène est construite, et `AudioTextToSpeech` lira exactement le même
texte. Six visèmes — ouvert, large, arrondi, fermé, dents, consonne — parce que
c'est ce que l'animation utilise depuis Disney : à 24 images par seconde
personne n'en voit davantage.

> Pourquoi piloté image par image et pas écrit dans le `.rbxmx` : **la façon
> dont un `KeyframeSequence` stocke des pistes faciales n'est documentée nulle
> part** où on puisse la vérifier. Deviner un format de fichier, c'est livrer
> quelque chose qui s'importe et ne fait rien. `FaceControls` est une classe
> documentée ; on écrit dedans.

## 3. La voix : native, sans rien enregistrer

`AudioTextToSpeech` est une **classe Roblox** en beta : du dialogue parlé, sans
clip pré-enregistré et **sans service tiers**. Une réplique de la scène devient
une voix, câblée à un `AudioEmitter` sur la tête du personnage — donc
positionnelle, elle vient d'où il est.

Et la bouche bouge déjà sur **le même texte**. Rien à synchroniser à la main :
les deux sont générés de la même phrase.

Si la classe est désactivée sur ta place, la réplique reste affichée à l'écran
et le script le dit, au lieu de jouer un silence.

## 4. Ce qu'aucune des trois briques ne donne, et que Linen fait

Un service génère **un clip d'une personne seule**. Un plugin de caméra bouge la
caméra. Un éditeur de visage pose une expression. **Aucun des trois ne sait que
cette main doit se fermer sur ce col.**

C'est ce que résout `contact` : l'IK deux-os pointée sur un bras, contre la
position réelle de l'autre corps, image par image, et ce qui ne peut pas être
atteint est **rapporté en studs** au lieu d'être caché.

```
Hero.RightHand -> Enemy.UpperTorso [3.78-4.28s] atteint
Enemy.RightHand -> Hero.Head       [2.37-2.49s] a 0.85 stud pres
```

---

## Le montage complet d'une cinématique

| Brique | Qui la fournit | Où c'est dans Linen |
| --- | --- | --- |
| Mouvement des corps | CMU / Mixamo / ta vidéo | `linen library build`, `--library` |
| **Contact entre personnages** | **Linen** | événement `contact` |
| Minutage entre acteurs | Linen | cues ancrés les uns aux autres |
| Caméra fixe / orbite / suivi | Linen | `kind` sur un plan |
| Coupes au bon instant | Linen | événements `camera` ancrés aux cues |
| Visages | Roblox (FACS, Face Capture) | événement `face` |
| Voix | Roblox (`AudioTextToSpeech`) | événement `sound` |
| Son à l'image près | Linen | `KeyframeMarker` dans le clip |
| VFX | Roblox (`ParticleEmitter`) | événement `vfx` |
| Publication | Linen | `linen publish` |

Rien là-dedans ne se loue. Tout est soit dans Roblox, soit gratuit et
téléchargeable, soit dans ce dépôt.
