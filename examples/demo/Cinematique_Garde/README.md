# `Garde` — une cinématique écrite pour une place réelle

Celle-ci n'est pas un exemple de démonstration : elle a été générée contre le
relevé d'une vraie place Studio (`Place1`, un rig R15 nommé `Rig` à
`(-15, 2.56, -3.5)`), pas contre un plateau vide.

```bash
linen survey --print | clip          # à coller dans la Command Bar de Studio
# ... copier la sortie dans place.json ...
linen scene examples/garde.scene.json --place place.json -o examples/demo/Cinematique_Garde
```

| Fichier | Ce que c'est |
| --- | --- |
| `Garde.html` | La prise entière. Ouvre-la, clique « 🎬 Caméra du réalisateur ». |
| `Garde_Rig.rbxmx` | L'animation, 22 images-clés, 5,6 s. À importer ou à publier. |
| `Garde.server.luau` | Le script : il place le rig **à sa position réelle** et coupe entre les deux plans. |

Quatre temps enchaînés — chacun démarre quand le précédent finit, donc retimer
l'un décale les suivants sans rien casser :

| | |
| --- | --- |
| 0,00 s | immobile, plan large |
| 1,60 s | regarde autour de lui, coupe sur le plan serré |
| 2,80 s | avance, retour au large |
| 4,60 s | s'arrête |

## Ce que le relevé a corrigé

**La position du rig.** Le relevé lisait `Model:GetPivot()`, alors que le script
de mise en place positionne un personnage par son `HumanoidRootPart`. Sur un rig
sorti du Rig Builder, le pivot est près du sol : la scène plaçait le personnage
**enterré de 2,3 studs**. Le contrôle de plateau l'a dit tout seul, et le relevé
lit maintenant la racine.

**Ce qui n'est pas un repère.** La place renvoyait `Baseplate` (2048 studs),
`Terrain`, `SpawnLocation`, un gizmo de plugin Moon Animator, et trois `Handle`
appartenant à l'outil que le rig tient. Aucun n'est un objet qu'on vise à la
caméra, et ils mangeaient la place des vrais. Filtrés — et un nom porté par
plusieurs objets est désormais signalé, parce que la caméra en cadrerait un au
hasard.
