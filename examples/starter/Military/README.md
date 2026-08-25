# Militaire d'élite — six animations, prêtes à importer

`Idle`, `Walk`, `Run`, `Jump`, `Fall`, `Land`. En **R15** et en **R6**.

```
Walk.R15.rbxmx        à importer dans Studio
Walk.R15.html         à double-cliquer d'abord — c'est ce que Studio doit donner
Walk.R15.moon.rbxmx   la même, ouvrable dans Moon Animator pour la retoucher
```

> `Land` n'était pas demandée. Elle est là parce qu'une `Fall` sans `Land` a
> l'air cassée en jeu : le personnage tombe et se remet debout d'un coup.

---

## Ce qui en fait un militaire et pas quelqu'un qui marche

**L'arme possède le haut du corps.** C'est la seule chose qui compte vraiment,
et c'est ce qu'un spectateur lit en premier — avant la longueur de foulée,
avant l'inclinaison. Les bras d'un civil balancent librement et compensent les
jambes. Ceux d'un soldat forment un triangle fermé autour d'un fusil, et ils y
restent pendant que tout le reste travaille.

Mesuré : le bras balance **quatre fois moins** que dans la marche civile du
vocabulaire de base.

Le reste est ce que ce triangle fermé coûte au corps :

- **Les genoux ne se verrouillent jamais.** Un genou tendu envoie le choc dans
  la colonne et dans la visée. C'est ce qui rend la marche délibérée plutôt que
  lente.
- **La tête garde sa ligne.** Le buste tourne, les bras en prennent la moitié —
  l'arme traîne légèrement derrière le corps, comme une masse tenue à bout de
  bras — et la tête prend l'opposé. Les yeux sont pointés et le restent.
- **La foulée est courte et rase.** Un grand pas engage le poids sur un pied
  qui n'est pas encore posé.

> Le porté était d'abord **complètement** figé : les bras mesuraient 0,0° sur un
> cycle entier. C'est exactement la signature que le passage de finition appelle
> une pose figée, et ça se lit comme un mannequin qu'on fait glisser sur le sol.
> Il faut que le corps travaille dessous.

---

## Montage dans Studio (5 min)

1. **Ouvre `Walk.R15.html`** dans ton navigateur. C'est le mouvement exact que
   le fichier contient. Si Studio donne autre chose, c'est l'import qui a raté.
2. Studio → **Baseplate** → onglet **Avatar** → **Rig Builder** → **R15** →
   **Block Rig**.
3. Mannequin sélectionné → **Avatar** → **Animation Editor** → nomme-la, valide.
4. `⋯` → **Import** → **From File…** → `Walk.R15.rbxmx` → **Play**.
5. `⋯` → **Publish to Roblox…**, note l'ID.

Puis les six IDs dans le script `Animate` : `walk/WalkAnim`, `run/RunAnim`,
`jump/JumpAnim`, `fall/FallAnim`, `idle/Animation1` et `Animation2`. Le pas à
pas complet est dans [`docs/DEMARRAGE.md`](../../../docs/DEMARRAGE.md), étape 4.

> **En R6**, prends les fichiers `.R6.rbxmx` et mets `Rig Type = R6` dans
> **Game Settings → Avatar**. Un rig R6 a une jambe d'une seule pièce, donc pas
> de genou : le style tient, la finesse des appuis non.

---

## Les refaire, ou les changer

```bash
linen synth examples/military/Walk.plan.json \
     --vocabulary military --motion loop --polish --moon --rig both \
     -o examples/starter/Military/Walk.rbxmx
```

Les six plans sont dans [`examples/military/`](../../military/), en JSON
lisible. Change une durée, un `rate`, un easing, relance la commande.

Les poses sont dans [`linen/generate/military.py`](../../../linen/generate/military.py) :
`LOW_READY`, `HIGH_READY`, `TUCKED` pour le porté, et les jambes en dessous. Ce
sont des angles d'Euler en degrés, un par articulation — c'est là que le style
se règle.

`--vocabulary military` est **obligatoire** et volontairement pas automatique :
chargé partout, il changeait ce que des prompts sans rapport allaient chercher.

---

## Ce que la finition a mesuré dessus

| | Avant | Après |
| --- | --- | --- |
| `Walk` R6, glissement moyen | 0,94 stud | **0,48** |
| `Run` R6 | 1,49 | **0,83** |
| `Jump` R15 | 1,15 | **0,50** |
| `Fall` R15 | 0,68 | **0,29** |
| `Land` R15 | 0,07 | **0,00** |
| `Idle`, pose figée 90 images | oui | **corrigée** |

Sur `Walk` et `Run` en R15, la pose des pieds a été **écartée** : un cycle
composé n'a pas de vrai appui — le vocabulaire de poses ne tient jamais un pied
immobile — donc ce que le détecteur y trouve est un balancement qui passe bas.
La correction rendait la marche trois fois pire, et la garde l'a refusée. C'est
le comportement voulu : un passage qui promet une amélioration doit être
incapable de livrer l'inverse.

## Ce qui n'est pas vérifié

Rien de tout ça n'a tourné dans Roblox Studio. Ce qui est vérifié : les six
plans construisent sur les deux rigs sans une valeur non finie, le style tient
en mesure (15 tests), et les pages `.html` ont été regardées, image par image.
