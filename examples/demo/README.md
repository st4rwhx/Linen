# Démos — à ouvrir dans un navigateur

Quatre pages. **Double-clique, ça joue.** Pas de serveur, pas d'installation,
pas de compte : chaque page contient son animation. Elles marchent hors-ligne.

| | |
| --- | --- |
| glisser · molette · maj+glisser | tourner · zoomer · déplacer |
| <kbd>espace</kbd> | lecture / pause |
| <kbd>←</kbd> <kbd>→</kbd> | image par image |
| clic sur la barre du bas | aller à un instant |
| **Face** · **Profil** · **Dessus** | vues fixes |

---

## `Cinematique_Disarm.html`

La cinématique complète de [`disarm.scene.json`](../disarm.scene.json) : deux
acteurs, le décor calculé, les cues en couloirs, tous les événements en repères
sous la barre, la courbe de tension derrière.

**Clique « 🎬 Caméra du réalisateur »** : la prise se joue à travers les plans
écrits dans la scène, avec leur focale et leur dérive. C'est le cadrage que tu
auras dans Studio.

Le personnage est en boîtes parce qu'un Block Rig en est. Avec un rig Blender :
`linen scene ... --skin ton_rig.blend` et la page gagne un sélecteur.

## `Posebook_marche.html` vs `Mocap_CMU_marche.html`

**La comparaison qui compte.** Les deux marchent. Regarde-les de **profil**,
vitesse **0,25×**, l'un après l'autre.

- `Posebook_marche.html` — composée à partir du vocabulaire de poses écrit à la
  main. Propre, lisible, et on voit que c'est dessiné.
- `Mocap_CMU_marche.html` — une vraie captation studio (CMU `02_01`), reciblée
  sur R15 sans une ligne de code en plus.

C'est tout l'écart entre « ça marche » et « ça a l'air vrai », et c'est pour ça
que `linen library` existe.

## `Mocap_CMU_enchainee.html`

Une phrase à trois temps → trois vraies captations, enchaînées :

```bash
linen prompt "il court vite puis il marche et il donne un coup de poing" \
     --library cmu.json -o build/phrase.rbxmx
```

Les raccords sont à **1,45 s** et **3,05 s**. Va les regarder image par image :
tu ne devrais pas les voir. Mesurés à 3,5 et 4,8 °/image, contre 3,4 °/image
pour le mouvement ordinaire de ces clips — un raccord au niveau du bruit de
fond.

Le raisonnement complet est dans
[`docs/ANIMATIONS_DE_FOU.md`](../../docs/ANIMATIONS_DE_FOU.md).

---

## Attribution

Les deux pages `Mocap_CMU_*` contiennent du mouvement de la **CMU Graphics Lab
Motion Capture Database**, qui demande cette mention :

> The data used in this project was obtained from mocap.cs.cmu.edu. The
> database was created with funding from NSF EIA-0196217.

Sa licence autorise explicitement l'usage commercial. Si tu sors un jeu avec,
mets cette ligne dans les crédits.
