# Des animations mocap gratuites, sans caméra

FreeMoCap triangule : il lui faut au moins deux caméras. Avec une seule caméra
ou un téléphone, ce chemin est fermé — mais il n'est pas le seul.

[Mixamo](https://www.mixamo.com) est gratuit avec un compte Adobe et propose des
centaines d'animations issues de vraie capture de mouvement, retravaillées par
des animateurs professionnels. C'est le meilleur saut de qualité disponible sans
matériel.

## Le point que je n'avais pas vérifié

**Mixamo n'exporte pas de BVH.** Seulement FBX et Collada (DAE). Or `linen bvh`
lit du BVH. Il manque donc une conversion, et j'avais présenté ce chemin comme
direct alors qu'il ne l'est pas.

Blender est le convertisseur, et il est gratuit.

## Le chemin complet

```
Mixamo  --FBX-->  Blender  --BVH-->  linen bvh  -->  .rbxmx  -->  Studio
```

1. Sur Mixamo, choisis une animation. **Download** → format **FBX**, et
   **Without Skin** : on ne veut que le mouvement, pas le personnage.
2. Dans Blender : `File > Import > FBX`.
3. `File > Export > Motion Capture (.bvh)`.
4. ```bash
   linen bvh danse.bvh --skeleton mixamo --units cm -o Danse.rbxmx
   ```

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
