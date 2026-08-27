# Faire une cinématique dans **ton** jeu

Deux endroits, deux langages. C'est la seule chose à ne pas confondre.

| Où | Ce qui s'y tape |
| --- | --- |
| **`cmd`** (le terminal Windows) | les commandes `linen ...` |
| **Barre de commande de Studio** | du **Luau**, et rien d'autre |

Taper `linen survey` dans la barre de commande de Studio donne
`Incomplete statement: expected assignment or a function call` : Studio essaie
de lire ça comme du Luau, et ce n'en est pas.

---

## 1. Relever ta place

**Dans `cmd`**, depuis le dossier du projet :

```
linen survey --print | clip
```

Le script est maintenant dans ton presse-papier. (Sans `| clip` :
`linen survey -o survey.luau` écrit un fichier, et tu l'ouvres dans le
Bloc-notes pour le copier.)

**Dans Studio** : **View → Command Bar**, colle, **Entrée**.

L'Output affiche ta place entre deux marqueurs :

```
--LINEN-PLACE-BEGIN--
{"place":"...","rigs":[...],"landmarks":[...],"sounds":[...]}
--LINEN-PLACE-END--
```

Copie tout ça — **avec les horodatages de Studio, ils sont gérés** — et
enregistre-le dans `place.json` à côté du projet.

> Le script **lit** et n'écrit rien. Un test vérifie qu'il ne contient ni
> `Destroy`, ni `Instance.new`, ni `.Parent =`, ni `Clone`.
>
> Il n'utilise que des commentaires `--[[ ]]`, jamais `--`. Si la barre de
> commande aplatit le collage sur une seule ligne, un commentaire `--` avalerait
> tout le reste du script et tu n'aurais **aucune sortie, sans erreur**. Un test
> tient cette propriété.

## 2. Écrire la scène

Tu me décris la cinématique en français, avec le détail que tu veux : qui fait
quoi, dans quel ordre, ce que la caméra regarde, ce qu'on entend. J'écris le
`scene.json`.

Ce qu'une scène sait exprimer :

| | |
| --- | --- |
| **Cues ancrés les uns aux autres** | « l'encaissement part 0,2 s après le poing » — et ça reste vrai quand on retime le poing |
| **Plans caméra** | position, cible, focale, fondu, dérive lente |
| **Props** | attachés à une main, lâchés, jetés |
| **Son** | par `KeyframeMarker`, donc à l'image près |
| **Visage** | `FaceControls`, 50 poses FACS, sur une dynamic head |
| **VFX** | `ParticleEmitter:Emit`, faisceaux, traînées |
| **Dialogue** | répliques placées sur la timeline |

## 3. Générer, calé sur ton décor

```
linen scene ma_scene.json --place place.json --animations publish.json -o cinematique
```

- `--place` pose chaque acteur sur **le rig qui existe vraiment**, à sa vraie
  position et sa vraie orientation, et signale ce qui ne colle pas : un acteur
  sans rig, un plan qui vise un objet absent, et surtout un rig que la scène
  croit R15 alors qu'il est R6 — auquel cas c'est la place qui gagne, parce
  qu'une animation R15 sur un corps R6 s'importe et **ne bouge pas**.
- `--animations` met tes vrais `rbxassetid://` dans le script, donc la scène
  joue **en jeu réel**. Sans ça, le script enregistre les `KeyframeSequence`,
  ce qui ne marche que dans Studio.

Ouvre le `.html` produit : c'est la prise entière, avec la caméra du
réalisateur. Regarde avant de toucher à Studio.

## 4. Publier et monter

```
linen publish cinematique --creator user:TON_ID --manifest cinematique.json
linen scene ma_scene.json --place place.json --animations cinematique.json -o cinematique
```

La première fois crée les assets ; la deuxième régénère le script avec les
identifiants dedans. Ensuite, tu régénères une animation → `linen publish` la
**met à jour** au même identifiant → le jeu joue la nouvelle version sans que
tu touches à un seul `Animation`.

L'ordre de montage dans Studio est en tête du `.server.luau` généré.

---

## Ce que ça ne fait pas

**Le contact n'est pas résolu.** Le poing part au bon moment, dans la bonne
direction, et l'autre encaisse à la bonne image — mais qu'il **touche** la
mâchoire à deux centimètres près demande un solveur IK avec collision, et Linen
ne l'a pas. Tu as la mise en scène et le timing ; les derniers centimètres sont
un ajustement à la main, dans l'éditeur d'animation ou dans Moon Animator
(`--moon`).

---

## Et sans copier-coller ?

Le relevé passe par toi parce que je tourne dans le cloud et ne vois pas ta
machine. Pour supprimer l'aller-retour : **Claude Code installé sur ton PC** +
le [serveur MCP Studio officiel de Roblox](https://github.com/Roblox/studio-rust-mcp-server).
Son outil `run_code` exécute le relevé et me rend la sortie directement, et la
même chose vaut pour l'installation dans la place.

Le copier-coller marche aujourd'hui et te dit déjà si le résultat vaut le coup
d'installer le reste.
