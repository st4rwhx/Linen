# Publier une animation sans ouvrir Studio

Tout le reste du projet s'arrête à un fichier. Un jeu qui tourne ne joue pas un
fichier, il joue un `rbxassetid://`. Obtenir ce numéro voulait dire ouvrir
l'éditeur d'animation et cliquer **Publish**, une fois par animation, à la main.

C'est fini. Voilà exactement quoi taper, de zéro, sous Windows.

---

## 1. Python

Il en faut **3.11 ou plus**. Dans `cmd` :

```
py --version
```

Si ça répond `Python 3.11.x` ou mieux, passe à l'étape 2. Sinon, installe-le
depuis [python.org/downloads](https://www.python.org/downloads/) et **coche
« Add python.exe to PATH »** sur le premier écran de l'installeur. C'est la case
que tout le monde rate, et sans elle rien de ce qui suit ne marche.

## 2. Récupérer le projet

> **Attention** : la branche par défaut du dépôt (`main`) est **vide**. Tout le
> code est sur `claude/freemocap-roblox-animations-b5nhwl`. Si tu cliques
> « Download ZIP » depuis la page d'accueil de GitHub, tu télécharges un dossier
> sans rien dedans.

**Avec Git**, si tu l'as :

```
cd %USERPROFILE%\Desktop
git clone -b claude/freemocap-roblox-animations-b5nhwl https://github.com/st4rwhx/Linen
cd Linen
```

**Sans Git** : télécharge
[le ZIP de la branche](https://github.com/st4rwhx/Linen/archive/refs/heads/claude/freemocap-roblox-animations-b5nhwl.zip),
clic droit → **Extraire tout**, puis dans `cmd` va dans le dossier extrait :

```
cd %USERPROFILE%\Desktop\Linen-claude-freemocap-roblox-animations-b5nhwl
```

Pour vérifier que tu es au bon endroit, `dir` doit montrer `pyproject.toml` et
un dossier `linen`.

## 3. Installer

```
py -m pip install .
```

Puis vérifie :

```
linen --version
```

Si ça affiche `linen 0.1.0`, c'est bon, et la commande marche **depuis
n'importe quel dossier**. Si Windows répond que `linen` n'est pas reconnu,
utilise `py -m linen.cli` à la place de `linen` partout dans la suite — c'est
strictement équivalent.

## 4. Créer la clé Roblox

1. [create.roblox.com/dashboard/credentials](https://create.roblox.com/dashboard/credentials)
   → **API Keys** → **Create API Key**.
2. Donne-lui un nom (`linen`, par exemple).
3. **Access Permissions** → **Add API System** → choisis **`assets`**, puis coche
   **Read** *et* **Write**.
4. Si tu publies sous un groupe, choisis le groupe dans le sélecteur de
   propriétaire. La clé doit appartenir à quelqu'un qui a ce droit dans le
   groupe — c'est l'API qui le vérifie, pas Linen.
5. **Security** → laisse la liste d'IP vide, ou mets la tienne. Si tu la
   remplis et que ton IP change, tu récupères un **403** : c'est ça, pas la
   permission.
6. **Save & Generate Key**, puis copie la clé **tout de suite** — elle ne se
   réaffiche jamais.

> **La clé ne se passe jamais en argument.** `linen publish --api-key ...`
> n'existe pas et n'existera pas : un argument est lisible par n'importe quel
> processus de la machine et reste écrit dans l'historique du terminal. Une clé
> qui passe par là doit être révoquée, et personne ne s'en aperçoit.

## 5. Donner la clé au terminal

**Dans la même fenêtre `cmd`** que celle où tu vas publier :

```
set ROBLOX_API_KEY=colle-ta-cle-ici
```

Trois pièges, tous les trois classiques sous Windows :

- **Pas de guillemets.** `set ROBLOX_API_KEY="abc"` met *littéralement*
  `"abc"`, guillemets compris, et Roblox répondra 401.
- **Pas d'espace autour du `=`.**
- **Ça ne dure que dans cette fenêtre.** Si tu fermes `cmd`, refais le `set`.
  Pour que ça tienne, `setx ROBLOX_API_KEY colle-ta-cle-ici` une fois — mais
  `setx` ne s'applique qu'aux fenêtres **ouvertes après**, donc ouvre-en une
  nouvelle ensuite.

Vérifie que la variable est bien là :

```
echo %ROBLOX_API_KEY%
```

Elle doit réafficher ta clé, sans guillemets autour.

> **PowerShell** au lieu de `cmd` : `$env:ROBLOX_API_KEY = "ta-cle"` — là les
> guillemets sont normaux.
>
> **macOS / Linux** : `export ROBLOX_API_KEY="ta-cle"`.

## 6. Publier

```
linen publish examples\starter\R15_converties\Run.rbxmx --creator user:TON_ID
```

```
  Run.rbxmx: rbxassetid://2205400862 (cree, revision 1)
```

**Ton `TON_ID`** est le nombre dans l'URL de ton profil :
`roblox.com/users/`**`12345678`**`/profile`. Pour un groupe, le nombre dans
`roblox.com/groups/`**`12345678`**`/nom` et tu écris `--creator group:12345678`.

Avant de tout envoyer, tu peux toujours répéter sans rien envoyer :

```
linen publish examples\starter\R15_converties --creator user:TON_ID --dry-run
```

---

## Le manifeste, et pourquoi il n'est pas optionnel

`--manifest publish.json` écrit la correspondance `fichier → asset id`.

Sans lui, la **deuxième** exécution ne met pas à jour tes animations : elle en
crée des copies. Et c'est le pire des trois résultats possibles, parce qu'il
**réussit** — il affiche des identifiants tout neufs, auxquels rien dans ton jeu
ne pointe. Avec le manifeste, la deuxième exécution fait un `PATCH` sur le même
asset : tous les `Animation` déjà câblés dans ton jeu suivent tout seuls.

Il est réécrit **après chaque fichier**, pas à la fin. Un asset qui existe et
qui n'est pas noté est pire qu'un asset qui n'existe pas : la fois suivante ne
peut pas le savoir, donc elle en crée un deuxième et le jeu continue de pointer
sur le premier. Une coupure de réseau doit coûter **le fichier en cours**, pas
tout ce qui précède. Si le programme s'arrête quand même, il sauve le manifeste
avant de partir et te le dit.

Commite `publish.json`. Ce n'est pas un secret, c'est la carte de ton jeu.

---

## Ce que ça donne

```
rem une seule animation
linen publish examples\starter\R15_converties\Run.rbxmx --creator user:TON_ID

rem tout un dossier, sous ton groupe, en gardant la carte des identifiants
linen publish examples\starter\R15_converties --creator group:123456 --manifest publish.json

rem une cinematique entiere
linen publish examples\demo\Cinematique_Disarm --creator group:123456 --manifest cinematique.json

rem verifier sans rien envoyer
linen publish examples\starter\R15_converties --creator user:TON_ID --dry-run
```

| Option | À quoi ça sert |
| --- | --- |
| `--creator user:ID` / `group:ID` | qui possède l'asset. L'id est le nombre dans l'URL de ton profil ou de ton groupe |
| `--manifest FICHIER` | créer la première fois, mettre à jour ensuite |
| `--dry-run` | vérifier la clé et ce qui partirait, sans rien envoyer |
| `--asset-type` | `Animation` par défaut. `Model` pour un rig ou un décor |

---

## Quand ça refuse

| | Ce que ça veut dire |
| --- | --- |
| **401** | la clé est rejetée — tu as peut-être copié son *nom* et pas la clé |
| **403** | la clé est valide mais pas autorisée : permission `assets` manquante, droit manquant dans le groupe, ou ton IP n'est pas dans la liste de la clé |
| **400** | Roblox a refusé le fichier ou la requête (voir juste en dessous) |
| **413** | plus de 20 Mo — c'est la limite par appel |
| **429** | trop d'envois d'affilée, attends un peu |

Le message d'erreur le dit en clair, et **la clé en est retirée** avant d'être
affichée.

---

## Est-ce que Roblox accepte un fichier écrit par Linen ? Oui

C'était la seule question que les tests ne pouvaient pas trancher. Roblox
prévient qu'un `.rbxm`/`.rbxmx` **écrit ailleurs que par Studio** peut ne pas
se téléverser ou ne pas fonctionner, parce que Studio fait un traitement
supplémentaire à l'enregistrement — et nos fichiers sont générés de bout en
bout, jamais passés par Studio.

**Réglé le 27 août 2026.** Un `.rbxmx` produit par Linen, téléversé par
`linen publish`, est devenu l'asset **`121632245238820`** : il apparaît dans
l'inventaire d'animations de Studio et il **joue correctement** sur un rig.

Donc le chemin est complet, et il n'a plus de clic dedans :

```
prompt / .dae / .rbxm R6   →   linen   →   .rbxmx   →   rbxassetid://
```

Ce qui reste vrai malgré tout : un fichier peut être refusé pour ce qu'il
contient, pas pour d'où il vient. Un **400** reste possible sur un fichier
particulier, et le repli est alors de l'importer dans Studio et de le
réenregistrer une fois.

---

## Pourquoi une clé et pas le cookie

Les outils qui demandent de coller ton `.ROBLOSECURITY` ont été écrits **avant**
que l'API Assets accepte les animations. Ils ne sont pas plus puissants, ils
sont plus vieux — et publier sous un groupe, qui était leur dernier argument,
marche très bien avec une clé.

- Une clé est **limitée** à `assets` et se révoque en un clic. Le cookie n'est
  pas limité : il fait tout ce que tu peux faire connecté, y compris ton solde
  Robux, tes Limiteds et ton adresse mail.
- Le cookie s'invalide dès que tu te déconnectes quelque part. D'où le rituel du
  « recolle ton cookie », qui t'apprend à le balader en clair.
- C'est le trafic automatisé **avec cookie** sur les endpoints web qui fait
  signaler les comptes. La clé est le chemin prévu pour ça.
