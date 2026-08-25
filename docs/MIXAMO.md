# Des animations mocap gratuites, sans caméra

FreeMoCap triangule : il lui faut au moins deux caméras. Avec une seule caméra
ou un téléphone, ce chemin est fermé — mais il n'est pas le seul.

[Mixamo](https://www.mixamo.com) est gratuit avec un compte Adobe et propose des
centaines d'animations issues de vraie capture de mouvement, retravaillées par
des animateurs professionnels. C'est le meilleur saut de qualité disponible sans
matériel.

## Le chemin, sans Blender

**Mixamo n'exporte pas de BVH** — seulement FBX et Collada (`.dae`). Le chemin
passait donc par Blender. Plus maintenant : `linen bvh` lit le Collada
directement, choisi d'après le suffixe du fichier.

```
Mixamo  --.dae-->  linen bvh  -->  .rbxmx  -->  Studio
```

**1. Télécharger.** Sur Mixamo, choisis l'animation, bouton **Download** :

| Champ | Mets ça | Pourquoi |
| --- | --- | --- |
| Format | **`Collada (.dae)`** | Le FBX encode des courbes par canal, qu'il faut réinterpréter — ordre de rotation, pré-rotation, mode temporel. Le Collada de Mixamo cuit **une matrice 4×4 par os et par image** : il n'y a plus rien à interpréter |
| Skin | **`Without Skin`** | On ne veut que le mouvement, pas le personnage |
| Frames per Second | **`30`** | La cadence de Roblox |
| Keyframe Reduction | **`none`** | Linen réduit lui-même, et en mesurant |

**2. Une commande.**

```bash
linen bvh Walking.dae --units cm --polish --moon --rig both -o Walk.rbxmx
```

**3. Import Studio** — Animation Editor → `⋯` → **Import** → **From File…**

### Pourquoi le Collada et pas le FBX

Un import mocap subtilement faux donne un squelette qui a l'air *presque* juste,
et presque juste est le pire des ratés : il passe la relecture et se voit en jeu.
Le FBX offre trois occasions de se tromper que le Collada n'offre pas du tout.

Le lecteur est dans [`linen/sources/collada.py`](../linen/sources/collada.py),
vérifié par onze tests contre des fichiers écrits à la main — dont un squelette
Mixamo complet de 21 os passé de bout en bout par la vraie commande.

Les repères que Mixamo n'a pas — talons, oreilles — sont reconstruits, et le
lacet de la tête suit le buste. C'est la seule perte connue de ce chemin.

## Si tu passes par un rig R15 Blender

Les rigs R15 communautaires pour Blender — comme
[celui-ci](https://devforum.roblox.com/t/r15-rig-for-blender-40-fkik-switching/3606878),
avec bascule FK/IK — nomment leurs os de déformation **exactement** comme les
parties Roblox : `LeftUpperArm`, `LowerTorso`, `LeftFoot`…

Linen sait lire ce nommage directement :

```bash
linen bvh anim.bvh --skeleton r15 -o Anim.rbxmx
```

Passer `--skeleton mixamo` sur un tel fichier **échoue franchement** en nommant
les repères manquants, plutôt que de résoudre à moitié et de produire un
personnage qui n'anime que le haut du corps.

## Quand Linen ne sert à rien, et il faut le dire

Si tu animes **à la main** dans Blender sur un rig R15, ou si tu retargettes du
Mixamo sur ce rig, l'addon
[Blender Rig Exporter / Animation Importer](https://devforum.roblox.com/t/blender-rig-exporteranimation-importer/34729)
envoie l'animation directement dans Studio. C'est plus court que de passer par
Linen, et c'est le bon outil pour ce travail.

Linen sert ailleurs : générer depuis un prompt, produire des jeux d'animations
en lot, monter des cinématiques multi-personnages, et la couche runtime.
