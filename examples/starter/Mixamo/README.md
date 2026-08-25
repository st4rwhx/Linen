# Mixamo → Roblox

De la vraie captation, reciblée. Une commande, pas de Blender.

```bash
linen bvh Walking.dae --units cm --motion loop --polish --moon --rig both \
     -o examples/starter/Mixamo/Walk.rbxmx
```

## Ce que ça a donné sur `Walking.dae`

Export Mixamo réel : 65 articulations, 30 images à 30 fps, 1 seconde de cycle.

| | R15 | R6 |
| --- | --- | --- |
| Glissement du pied posé, avant | 0,67 stud | 0,86 |
| **après finition** | **0,01 stud** | **0,55** |
| Arcs cassés détectés avant | `RightFoot` 150°, `RightHand` 175° | — |
| **après** | **aucun** | — |

Un pied R15 mesure 0,86 stud de long. **0,01 stud, c'est un quatre-vingtième de
pied** — il n'y a plus rien à voir.

Le R6 reste à 0,55 : une jambe R6 est une seule part rigide, sans genou, donc la
semelle n'atteint qu'une sphère. C'est la limite du rig, pas de la captation.

## Réglages de téléchargement Mixamo

| Champ | Valeur |
| --- | --- |
| Format | **`Collada (.dae)`** |
| Skin | `Without Skin` |
| Frames per Second | `30` |
| Keyframe Reduction | `none` |

`With Skin` marche aussi — le maillage est simplement ignoré — mais le fichier
pèse dix fois plus lourd pour rien.

## Sur la licence, à décider par toi

Mixamo est **gratuit pour un usage commercial illimité** : expédier ces
animations dans ton jeu est explicitement autorisé, sans royalties.

Ce que la licence interdit, c'est de **redistribuer les fichiers bruts** comme
un pack d'assets. Un `.rbxmx` reciblé reste la même animation, et ce dépôt est
sur GitHub.

Concrètement : **si ton dépôt est public**, mets ce dossier dans `.gitignore`
avant de le publier, ou passe le dépôt en privé. S'il est déjà privé, il n'y a
rien à faire. Ces fichiers sont ici parce que c'est le seul moyen que tu les
récupères — la décision t'appartient.

## Ce qui n'est pas vérifié

Les fichiers n'ont pas été joués dans Roblox Studio. Ce qui est vérifié : le
lecteur Collada contre treize fichiers écrits à la main plus ce vrai export
Mixamo, les mesures de finition ci-dessus, et la marche regardée image par image
dans `Walk.R15.html`.
