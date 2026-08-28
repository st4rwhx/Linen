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

## 2. Les visages : `FaceControls`, 50 poses FACS

Une **dynamic head** est un `MeshPart` skinné qui porte un objet `FaceControls`.
Roblox définit **50 poses FACS** de base ; 17 sont obligatoires pour publier une
tête sur la Marketplace. Plusieurs poses se combinent dans une même image pour
faire une expression complexe.

Trois façons de les animer, toutes dans Studio :

1. **À la main** — une valeur FACS par piste, entre 0 et 1 dans l'éditeur
   d'animation, et ces valeurs vont directement dans `FaceControls`.
2. **Face Animation Editor** — des curseurs pour composer une expression et la
   poser sur la timeline.
3. **Face Capture** — *et c'est la trouvaille* : Roblox lit ta webcam et en fait
   des images-clés pour une dynamic head. C'est en beta **dans l'éditeur
   d'animation**, c'est gratuit, et ça ne demande aucun service.

Convention : l'image 0 est le visage neutre, les poses commencent à l'image 1,
une seule pose FACS unique par image.

**Ce que Linen fait :** un événement `face` pose une expression au bon instant,
par marqueur, ancrée à un temps de la scène. C'est un palier, pas une courbe —
suffisant pour « il passe en colère ici », plus grossier qu'une vraie captation.

**Le mélange qui donne le meilleur résultat :** Linen place *quand* l'expression
change, Face Capture fournit *à quoi elle ressemble*.

---

## 3. La voix

| | |
| --- | --- |
| **`AudioTextToSpeech`** | classe **native Roblox**, en beta : du dialogue parlé en temps réel, sans clip pré-enregistré et **sans service tiers** |
| **`AudioPlayer` + `AudioEmitter`** | la nouvelle API audio. `AudioPlayer` charge et joue, `AudioEmitter` est un haut-parleur virtuel dans l'espace 3D |
| **2D** | musique, interface, et **voix off de cinématique** — pas d'émetteur, pas d'atténuation |
| **3D** | une réplique qui vient de la bouche d'un personnage : `AudioEmitter` sur sa tête |

Le lip-sync automatique depuis l'audio n'est pas encore une fonction livrée ;
c'est un sujet ouvert sur le forum. En attendant, les poses FACS de mâchoire
posées sur les syllabes font le travail.

**Ce que Linen fait :** chaque son est un `KeyframeMarker` **dans l'animation**,
donc à l'image près et solidaire du clip — si tu retimes le clip dans Studio, le
son suit. La feuille de spotting (`<Scene>.audio.json`) liste chaque son dont la
scène a besoin, avec sa description ; tu colles un `rbxassetid://` en face.

---

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
