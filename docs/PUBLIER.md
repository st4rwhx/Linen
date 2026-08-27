# Publier une animation sans ouvrir Studio

Tout le reste du projet s'arrête à un fichier. Un jeu qui tourne ne joue pas un
fichier, il joue un `rbxassetid://`. Obtenir ce numéro voulait dire ouvrir
l'éditeur d'animation et cliquer **Publish**, une fois par animation, à la main.

C'est fini :

```bash
export ROBLOX_API_KEY="..."          # une seule fois, dans ton shell
linen publish examples/starter/R15_converties --creator group:TON_GROUPE \
      --manifest publish.json
```

```
  Run.rbxmx: rbxassetid://2205400862 (cree, revision 1)
  Swim.rbxmx: rbxassetid://2205400863 (cree, revision 1)
```

---

## La clé, en trois minutes

1. [create.roblox.com/dashboard/credentials](https://create.roblox.com/dashboard/credentials)
   → **API Keys** → **Create API Key**.
2. **Access Permissions** → ajoute **`assets`**, avec **Read** *et* **Write**.
3. Si tu publies sous un groupe, choisis le groupe dans le sélecteur de
   propriétaire. La clé doit appartenir à quelqu'un qui a ce droit dans le
   groupe — l'API le vérifie, pas Linen.
4. **Security** → laisse la liste d'IP vide, ou mets la tienne. Si tu la
   remplis et que ton IP change, tu récupères un **403** : c'est ça, pas la
   permission.
5. Copie la clé **maintenant** ; elle ne se réaffiche pas.

```bash
export ROBLOX_API_KEY="ta-cle"       # à mettre dans ~/.zshrc ou ~/.bashrc
```

> **La clé ne se passe jamais en argument.** `linen publish --api-key ...`
> n'existe pas et n'existera pas. Un argument est lisible par n'importe quel
> processus de la machine (`ps`), et il reste écrit dans l'historique du shell.
> Une clé qui passe par là doit être révoquée, et personne ne s'en rend compte.

---

## Le manifeste, et pourquoi il n'est pas optionnel

`--manifest publish.json` écrit la correspondance `fichier → asset id`.

Sans lui, la **deuxième** exécution ne met pas à jour tes animations : elle en
crée des copies. Et c'est le pire des trois résultats possibles, parce qu'il
**réussit** — il affiche des identifiants tout neufs, auxquels rien dans ton jeu
ne pointe. Avec le manifeste, la deuxième exécution fait un `PATCH` sur le même
asset : tous les `Animation` déjà câblés dans ton jeu suivent tout seuls.

Commite `publish.json`. Ce n'est pas un secret, c'est la carte de ton jeu.

---

## Ce que ça donne

```bash
linen publish dossier/ --creator user:TON_ID --dry-run   # rien n'est envoyé
linen publish Run.rbxmx --creator group:123456           # une seule
linen publish examples/demo/Cinematique_Disarm --creator group:123456 \
      --manifest cinematique.json                        # toute une scène
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

## Le point qui reste ouvert

Roblox prévient qu'un `.rbxm`/`.rbxmx` **écrit ailleurs que par Studio** peut ne
pas se téléverser ou ne pas fonctionner correctement, parce que Studio fait un
traitement supplémentaire à l'enregistrement. Nos fichiers sont générés.

Les tests couvrent tout ce qui est vérifiable sans compte : la forme du
formulaire à deux champs, l'en-tête qui porte la clé, l'attente de l'opération,
la mise à jour au lieu du doublon, et le fait qu'une erreur ne recrache jamais
la clé. Ils **ne peuvent pas** couvrir la seule question qui reste : est-ce que
Roblox accepte un `.rbxmx` de Linen.

Ça se tranche avec un fichier et dix minutes :

```bash
linen publish examples/starter/R15_converties/Run.rbxmx --creator user:TON_ID
```

Puis dans Studio, un `Animation` avec l'id rendu, joué sur un rig R15. Si ça
bouge, le chemin **prompt → animation → asset publié** est complet et il n'y a
plus jamais de clic. Si ça refuse en 400, le repli est d'importer le fichier
dans Studio et de le réenregistrer une fois — et on saura que c'est le
traitement de Studio qui manque, pas notre écriture.

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
