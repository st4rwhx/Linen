# Démarrage — de zéro à une animation qui tourne dans ton jeu

Ce guide ne demande **aucune ligne de code** et aucune installation en dehors de
Roblox Studio. Les animations sont déjà générées et livrées dans le dépôt.

Compte 20 minutes pour les étapes 1 à 3. Fais-les **dans l'ordre** : chacune
vérifie quelque chose que la suivante suppose acquis.

---

## Étape 0 — récupérer les fichiers

Sur la page GitHub du dépôt, bouton vert **Code** → **Download ZIP**. Dézippe
quelque part de simple, par exemple sur ton Bureau.

Ce dont tu as besoin est dans `examples/starter/R15/` : sept fichiers `.rbxmx`.

| Fichier | Ce que c'est |
| --- | --- |
| `Idle.rbxmx` | Repos, en boucle, avec respiration |
| `Walk.rbxmx` | Marche, en boucle |
| `Run.rbxmx` | Course, en boucle |
| `Jump.rbxmx` | Impulsion du saut |
| `Fall.rbxmx` | Chute libre, en boucle |
| `Land.rbxmx` | Réception |
| `Sit.rbxmx` | Assis |

---

## Étape 1 — voir une animation jouer (5 min)

1. Ouvre Roblox Studio, crée une **Baseplate**.
2. Onglet **Avatar** → **Rig Builder** → **R15** → **Block Rig**. Un mannequin
   apparaît dans le monde.
3. Le mannequin étant sélectionné, onglet **Avatar** → **Animation Editor**.
4. Studio demande un nom pour l'animation. Mets `Test`, valide.
5. Dans la barre de l'éditeur, clique sur les **trois points `⋯`** (en haut à
   droite du panneau) → **Import** → **From File…**
6. Choisis `examples/starter/R15/Walk.rbxmx`.
7. Appuie sur **Play** dans l'éditeur d'animation.

### Ce que tu dois voir

Le mannequin marche sur place. Les bras se balancent en opposition aux jambes.

### Si ça ne marche pas

| Symptôme | Cause |
| --- | --- |
| L'import est grisé / refusé | Tu as construit un rig **R6**. Refais l'étape 2 en R15. |
| Le perso ne bouge pas du tout | L'import a échoué silencieusement — vérifie que tu as bien pris un fichier dans `R15/`. |
| Ça bouge mais c'est n'importe quoi | Note ce que tu vois et dis-le-moi. C'est exactement le retour qu'il me manque. |

**C'est le point de contrôle le plus important du projet.** Tant que cette étape
n'est pas passée, tout le reste est de la théorie. Ne va pas plus loin avant.

---

## Étape 2 — publier les animations (10 min)

Roblox ne peut pas jouer une animation depuis un fichier : il lui faut un
identifiant. Il faut donc publier chaque fichier une fois.

Pour **chacun** des sept fichiers, dans l'Animation Editor :

1. `⋯` → **Import** → **From File…** → le fichier.
2. `⋯` → **Publish to Roblox…**
3. Donne-lui le nom du fichier (`Walk`, `Idle`…), publie.
4. Studio affiche un **ID**. Note-le dans un carnet, en face du nom.

Tu dois finir avec une liste de sept lignes du genre :

```
Idle  = 1234567890
Walk  = 1234567891
Run   = 1234567892
Jump  = 1234567893
Fall  = 1234567894
Land  = 1234567895
Sit   = 1234567896
```

> **Piège classique.** Une animation ne se joue que si elle appartient au même
> compte (ou au même groupe) que le jeu. Si tu publies sur ton compte et que le
> jeu appartient à un groupe, elle ne chargera pas. Publie du bon côté dès le
> départ.

---

## Étape 3 — les mettre sur ton personnage (5 min)

Le personnage d'un joueur est animé par un script `Animate` que Roblox insère
automatiquement. On en prend une copie et on remplace les identifiants. **Aucune
ligne à écrire** : tout se fait dans le panneau Properties.

1. Vérifie que ton jeu est en R15 : **Home** → **Game Settings** → **Avatar** →
   **Rig Type** = `R15`.
2. Appuie sur **Play** (F5) pour lancer une partie de test.
3. Dans **Explorer**, déplie `Workspace` → ton pseudo. Tu y vois un script
   nommé **`Animate`**. Clic droit dessus → **Copy**.
4. Arrête la partie (**Shift+F5**).
5. Dans **Explorer**, déplie `StarterPlayer` → clic droit sur
   **`StarterCharacterScripts`** → **Paste Into**.
6. Déplie le `Animate` que tu viens de coller. Tu trouves des dossiers `idle`,
   `walk`, `run`, `jump`, `fall`, `sit`…
7. Déplie `walk` → clique sur **`WalkAnim`**. Dans **Properties**, remplace
   **`AnimationId`** par `rbxassetid://` suivi de ton numéro.
   Exemple : `rbxassetid://1234567891`.
8. Recommence pour `run` → `RunAnim`, `jump` → `JumpAnim`, `fall` → `FallAnim`,
   `sit` → `SitAnim`.
   Pour `idle`, il y a **deux** entrées (`Animation1` et `Animation2`) : mets le
   même ID dans les deux pour commencer.

### Ce que tu dois voir

Lance une partie. Ton personnage utilise **tes** animations : il respire à
l'arrêt, marche et court avec tes cycles.

### Si ça ne marche pas

| Symptôme | Cause |
| --- | --- |
| Le perso reste en T-pose ou en animation Roblox | L'ID est faux, ou l'animation n'appartient pas au bon compte/groupe. |
| Ça marche en solo mais pas en ligne | Presque toujours le problème de propriété du groupe. |
| Le perso glisse en marchant | Normal pour l'instant — c'est ce que règle le module `Locomotion`, plus tard. |

---

## Étape 4 — le module qui change le plus (optionnel, 10 min)

`Secondary` fait traîner chaque articulation derrière son parent. C'est ce qui
fait qu'une animation ordinaire se met à ressembler à du travail d'animateur.
C'est aussi **le module le moins risqué** : il ne touche à aucune physique, donc
au pire il ne fait rien de visible.

1. Dans **Explorer**, clic droit sur **`ReplicatedStorage`** → **Insert Object**
   → **Folder**. Renomme-le `Linen`.
2. Ouvre le dossier `runtime/` du ZIP dans ton explorateur de fichiers.
   Glisse-dépose ces fichiers dans Studio, dans le dossier `Linen` :
   `init.luau`, `RigLimits.luau`, `MotionData.luau`, `Secondary.luau`,
   `FootPlanting.luau`, `Momentum.luau`, `Balance.luau`, `Ragdoll.luau`,
   `Locomotion.luau`.
   Renomme `init` en `Linen` si Studio ne le fait pas tout seul.
3. Clic droit sur **`StarterPlayer` → `StarterCharacterScripts`** →
   **Insert Object** → **LocalScript**.
4. Efface son contenu et colle **exactement** ceci :

```lua
local ReplicatedStorage = game:GetService("ReplicatedStorage")
local Linen = require(ReplicatedStorage.Linen)

local character = script.Parent
character:WaitForChild("Humanoid")

-- Uniquement le module de mouvement secondaire pour l'instant : pas de
-- physique, donc rien qui puisse faire tomber le personnage.
Linen.attach(character, {
    secondary = true,
    footPlanting = false,
    momentum = false,
    balance = false,
})
```

5. Lance une partie et marche.

### Ce que tu dois voir

Une différence **subtile mais nette** : les mains et les avant-bras arrivent
légèrement en retard sur les bras. Le corps a l'air moins mécanique.

### Si ça ne marche pas

Ouvre la fenêtre **Output** (`View` → `Output`) et envoie-moi le texte en rouge.
C'est du code qui n'a **jamais été exécuté** — s'il y a une erreur, c'est normal
et c'est réparable en une passe.

---

## Ce qu'on fait après

Dans l'ordre de ce qui rapporte le plus :

1. **`Locomotion`** — supprime le patinage des pieds et mélange marche/course
   selon la vitesse réelle. C'est le défaut le plus visible qui reste après
   l'étape 3.
2. **`FootPlanting`** — les pieds épousent le relief. À faire seulement si ton
   jeu a des pentes ou des escaliers.
3. **De vraies animations mocap.** Tu n'as qu'une caméra, donc FreeMoCap n'est
   pas pour toi tout de suite. [Mixamo](https://www.mixamo.com) est gratuit et
   professionnel — mais **il n'exporte pas de BVH**, seulement du FBX et du
   DAE, donc Blender sert de convertisseur. Le chemin complet est décrit dans
   [`MIXAMO.md`](MIXAMO.md).
4. **`Ragdoll`** en dernier. C'est le plus spectaculaire et le plus risqué : il
   touche à la physique, donc à la réplication réseau.
