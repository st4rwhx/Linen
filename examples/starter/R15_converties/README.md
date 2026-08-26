# Tes animations, converties en R15

Noms d'origine conservés. Un seul dossier, uniquement du `.rbxmx` R15.

```bash
linen convert dossier_avec_les_rbxm/ -o examples/starter/R15_converties
```

## Ce qui est passé : 17 sur 57

| Animation | Images-clés | Boucle | Conserve |
| --- | --- | --- | --- |
| `At ease` | 5 | non | |
| `Automatic Save` | 4 | oui | |
| `Bandage self` | 287 | oui | `Handle` |
| `CrouchIdleNoHead` | 1 | oui | |
| `CrouchMove` | 7 | oui | |
| `Imported Animation Clip` | 60 | oui | |
| `ProneIdle` | 1 | non | |
| `ProneMoveNoHead` | 5 | oui | |
| `Run` | 17 | oui | |
| `Swim` | 73 | oui | |
| `Swim Idle` | 80 | oui | |
| `Test` | 11 | oui | |
| `Untitled Animation Clip` | 1 | non | |
| `equip` | 50 | non | `Handle` |
| `hit1` | 67 | non | `Handle`, `Katana` |
| `hit2` | 42 | non | `Handle` |
| `in seat 1` | 1 | non | |

**La conversion est exacte.** Vérifié cellule par cellule sur les **4097 poses** :
écart maximum **5×10⁻⁷** sur une case de matrice, soit l'arrondi d'écriture à six
décimales. Aucune approximation dans le chemin.

Chaque temps d'image-clé, chaque easing, et chaque partie qui n'est pas du corps
— `Handle`, `Katana` — traversent **intacts**.

## Ce qu'une conversion R6 → R15 ne peut pas faire

**Inventer un coude.** Un bras R6 est **une seule part rigide** de l'épaule au
bout des doigts. R15 le coupe en trois : bras, avant-bras, main. L'angle entre
eux **n'existe pas** dans un fichier R6.

Donc les bras et les jambes converties sortent **droits**. C'est fidèle — c'est
exactement la pose R6 — et ça paraîtra plus raide qu'une animation R15 native,
parce que c'en est une R6 posée sur un corps qui a des articulations dont elle
n'a jamais entendu parler.

**Et le point de préhension se déplace.** Sur R6 un Tool se soude à `Right Arm`,
dont le bout est à 2 studs de l'épaule. Sur R15 il se soude à `RightHand`, à
environ 2,4 studs le long d'un bras tendu. Il faudra rattraper cet écart dans le
`C0` de ta soudure.

## Les 40 autres, et pourquoi

**20 sont des animations de viewmodel.** Leur arbre de poses est enraciné sur
`AnimBase` — une part de ton arme — avec les bras accrochés au fusil plutôt qu'à
un torse. Ce ne sont pas des animations de personnage. **Aucun rig R15 n'a cette
hiérarchie**, et renommer les parties produirait un fichier qui s'importe et ne
fait rien. Elles sont refusées plutôt que cassées en silence.

**9 sont des `CurveAnimation`** — le format à courbes de Roblox
(`EulerRotationCurve`, `FloatCurve`) au lieu de `Keyframe`/`Pose`. C'est un
lecteur différent, pas un mapping différent. Faisable, mais c'est un autre
chantier.

**11 ne sortent pas du `.rar`.** L'archive utilise une méthode de compression
RAR5 que ni `unar` ni `7z` ne décompressent ici — même erreur que sur le pack
zombie. **Renvoie-les en `.zip`** et elles passeront.

| | |
| --- | --- |
| `AoT Salute Animation` | `Chambre` |
| `Changer` | `Glock-17_Bouclier_Préparation faible` |
| `Glock-17_Shield_BoltRelease` | `Glock-17_Shield_Idle` |
| `KeyframeSequence` | `Sprint` |
| `Walk - V2` | `asd _CHANNELS_` |
| `set` | |

## Ce qui n'est pas vérifié

Aucun de ces fichiers n'a été importé dans Roblox Studio. Ce qui est vérifié :
le décodage binaire contre **5989 CFrames** — toutes orthonormales à 2,4×10⁻⁶
près, donc de vraies matrices de rotation — l'exactitude de la conversion sur
4097 poses, et la hiérarchie de sortie contre le rig R15 lui-même.
