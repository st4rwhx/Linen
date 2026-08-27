# Passer du gribouillage aux vraies animations

## Le diagnostic, sans enrobage

Linen a **deux moitiés**, et elles ne sont pas au même niveau.

**La tuyauterie est solide.** Le reciblage, la correction du patinage des pieds
(1,34 stud → 0,07 sur de la vraie mocap), la détection de boucle par mesure, la
conversion R6→R15 vérifiée à 10⁻⁶, la publication en `rbxassetid://`, le
minutage d'une scène à plusieurs acteurs, la caméra, les accessoires, les
marqueurs image-exacte. Tout ça marche et est testé.

**Le stock de mouvement est minuscule.** Douze verbes dessinés à la main :
marcher, courir, frapper, encaisser, reculer, s'accroupir, sauter, s'asseoir,
saluer, pointer, célébrer, tituber. C'est tout. Il n'y a **aucune ligne** dans
ce dépôt qui sache à quoi ressemble une empoignade, un plaquage, un lancer de
couteau ou un corps qui glisse le long d'un mur.

C'est la seule raison pour laquelle une cinématique sort décevante. Pas le
minutage, pas la caméra, pas l'export. **Le stock.**

Et c'est une bonne nouvelle : changer le stock ne demande de réécrire aucune
des deux moitiés. Tout ce qui est en aval — polish, boucle, publication,
scènes — en profite gratuitement.

---

## 1. CMU : 2548 captures, une soirée de téléchargement

**C'est le saut le plus grand, et le moins cher.** La base de la Carnegie
Mellon Graphics Lab, capturée en studio, dont le README dit :

> « **Use this data!** This data is free for use in **research and commercial
> projects worldwide**. »

Elle est déjà en BVH, ses noms d'articulations sont ceux de Mixamo — donc Linen
la lit sans une ligne de code en plus — et elle est livrée avec un **index
texte** qui décrit chaque capture en anglais. C'est-à-dire : un jeu de données
**texte → mouvement**, utilisable commercialement. Exactement ce que les modèles
de recherche promettent et n'ont pas le droit de te donner.

### Vérifié de bout en bout

```bash
mkdir cmu && cd cmu

# Les captures. 16 archives de ~33 Mo pour la série complete (sujets 01 a 94).
# Commence par une seule pour voir : 98 captures, ~33 Mo.
curl -O https://codewelt.com/dl/cmuconvert/cmuconvert-mb2-01-09.zip
unzip cmuconvert-mb2-01-09.zip -d bvh

# L'index de descriptions. L'original a bouge ; ce miroir repond.
curl -o index.txt https://raw.githubusercontent.com/una-dinosauria/cmu-mocap/master/cmu-mocap-index-text.txt

cd ..
linen library build cmu/bvh -o cmu.json --descriptions cmu/index.txt
```

Sur ce seul lot, en français, contre des descriptions en anglais :

| Ce que tu écris | Ce qu'il trouve | Score |
| --- | --- | --- |
| `coup de poing` | `02_05` — punch/strike | 3,13 |
| `il court` | `02_03` — run/jog | 3,12 |
| `il saute` | `02_04` — jump, balance | 2,28 |
| `il danse` | `05_02` — dance, expressive arms, pirouette | 0,57 |

Et le résultat :

```bash
linen prompt "coup de poing" --library cmu.json -o Punch.rbxmx
```

```
'coup de poing' -> 02_05: punch/strike  [15,4s]  score 3.13
  02_05: fenetre 12.00-14.01s sur 15.4s
Punch.rbxmx: R15, 241 frames -> 166 keyframes, 2.00s
```

**166 images-clés sur deux secondes**, avec le report d'appui, l'épaule qui
part avant le bras, le retour en garde. Le `punch` dessiné, c'était deux poses.

Pour les autres archives, remplace `01-09` par `10-14`, `15-19`, … jusqu'à
`86-94` sur [codewelt.com/cmumocap](https://codewelt.com/cmumocap). Prends la
série **`mb2`** — c'est celle qui est testée ici.

> Attention à une nuance : **AMASS contient CMU mais repackagé sous licence
> restrictive.** C'est la base CMU d'origine qu'il faut, pas AMASS.

### Le crédit, obligatoire

Si tu sors un jeu avec, mets cette ligne dans les crédits :

> The data used in this project was obtained from mocap.cs.cmu.edu. The
> database was created with funding from NSF EIA-0196217.

---

## 2. Mixamo : le complément, pas la base

CMU est de la captation universitaire de 2003 : marcher, courir, sauter,
danser, du sport, quelques bagarres. Ce qu'elle n'a **pas** : le maniement
d'armes, les empoignades chorégraphiées, les morts stylisées, les animations de
jeu vidéo.

C'est là que Mixamo sert — et **pas** comme bibliothèque principale, parce que
c'est un clip à la fois, à la main.

1. [mixamo.com](https://www.mixamo.com), compte Adobe gratuit.
2. Cherche le mouvement, choisis-le.
3. **Download** → Format **Collada (.dae)** → **Without Skin** → 30 fps.
4. Mets le fichier dans le même dossier que le reste, relance
   `linen library build`.

Gratuit pour un **usage commercial illimité**. Seule interdiction :
redistribuer les fichiers bruts. Les mettre dans ton jeu, oui ; les republier
sur GitHub, non.

Pour la scène [`Contre`](../examples/contre.scene.json) : *Grab*, *Pushing*,
*Shove Reaction*, *Body Jab*, *Head Hit*, *Stunned*, *Take Weapon*,
*Throw Object*, *Falling Back Death*. Neuf clips, dix minutes.

---

## 3. Ta propre mocap : la seule réponse à « je veux exactement ça »

Aucune bibliothèque n'aura *ton* geste précis. Et c'est **la raison d'être
originelle de ce projet** : Linen est né pour brancher FreeMoCap sur des rigs
Roblox.

**Deux webcams ou deux téléphones**, [FreeMoCap](https://freemocap.org)
(gratuit, open source), toi et un ami qui jouent la scène, et :

```bash
linen retarget ma_capture/mediapipe_body_3d_xyz.npy --fps 30 --polish -o Prise.rbxmx
```

C'est la seule route qui te donne l'empoignade exacte que tu as en tête, jouée
par de vrais corps. Coût : deux caméras et un après-midi.

---

## 4. Le plafond, qu'il faut connaître

**Le contact n'est pas résolu, et aucune bibliothèque ne le résoudra.**

Une capture de bibliothèque est **solo et générique**. Elle sait à quoi
ressemble un corps qui pousse. Elle ne sait pas que ta main doit se fermer sur
*ce col-là*, que ce dos doit toucher *ce mur-là* à *cette* distance, ni que ce
couteau doit entrer dans *cette* tête.

Combler ça demande un **solveur IK avec conscience des collisions** sur deux
rigs de proportions inconnues. Ce n'est pas un réglage, c'est un vrai chantier
d'ingénierie, et Linen ne l'a pas.

**Ce que tu as en attendant, et qui suffit dans 90 % des cas** : la mise en
scène et le minutage justes, avec du vrai mouvement dessus. Les derniers
centimètres se règlent à la main — `--moon` écrit une sauvegarde Moon
Animator 2, une piste par articulation, et tu attrapes trois images-clés.

**C'est aussi comme ça que font les vrais studios.** Personne ne génère une
cinématique AAA depuis du texte. Ils partent d'une mocap et ils polissent à la
main. La seule différence, c'est que le premier jet leur coûte un studio de
captation, et à toi une commande.

---

## L'ordre dans lequel faire les choses

| | Effort | Ce que ça change |
| --- | --- | --- |
| **1. CMU** | une soirée de téléchargement | 12 verbes dessinés → **2548 mouvements réels**. Le plus gros saut du projet. |
| **2. Mixamo** | 10 min par scène | Le combat et les armes que CMU n'a pas. |
| **3. `--polish`** | une option | Les appuis arrêtent de glisser. Déjà là. |
| **4. Ta mocap** | deux caméras, un après-midi | Le geste exact que personne n'a capturé. |
| **5. Moon Animator** | à la main | Le contact, les derniers centimètres. |

Rien là-dedans n'est un chantier de code. **Le retard de Linen n'est pas
technique, il est documentaire** — et ça se rattrape avec un `curl`.
