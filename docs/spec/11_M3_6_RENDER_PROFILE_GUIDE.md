# M3.6 — profils nommés de rendu approximatif, sans changement rétroactif

## Exemples CLI

Préécoute A/B **positions discrètes XT 2.33, approximate-only** :

```powershell
python -m xtwavetable.cli.preview_ab compare --job QA_XT233 --source-a JOB_A --source-b JOB_B --render-profile xt233-discrete-approx
```

Préécoute A/B **Tallent E352, approximate-only** :

```powershell
python -m xtwavetable.cli.preview_ab compare --job QA_E352 --source-a JOB_A --source-b JOB_B --render-profile tallent-e352-approx
```

Préécoute par lot **Tallent Honda, approximate-only** :

```powershell
python -m xtwavetable.cli.preview_batch batch --job QA_HONDA --sources JOB_A JOB_B --render-profile tallent-honda-approx
```

Ces commandes n'agissent pas sur le hardware, ne lisent que les jobs M2 déjà vérifiés, et refusent d'écraser un dossier `runs/<job>` existant.

## Profils

| Identifiant | Axe table | Axe phase | Statut |
|---|---|---|---|
| `legacy-linear-approx` | crossfade linéaire | linéaire | historique M3.1, NON stock 2.33 |
| `xt233-discrete-approx` | `nearest` (seuils approximatifs) | linéaire | sélecteur discret proxy, NON DSP certifié |
| `tallent-e352-approx` | crossfade linéaire | linéaire | proxy E352, NON bit-exact |
| `tallent-honda-approx` | crossfade linéaire | nearest | proxy Honda, NON bit-exact |

L'absence de `--render-profile` **reproduit le comportement M3.1–M3.4 d'origine sans changer les WAV/JSON**, avec un avertissement CLI. Les anciens fichiers de préécoute ne sont jamais modifiés automatiquement. Lorsqu'un profil nommé est passé, le rapport de vérification contient `render_profile` et la paire `render_settings` correspondante. Les options individuelles `--table-interpolation` / `--phase-interpolation` ne peuvent pas contredire le profil.

Le profil XT discret écrit `crossfade_midpoint_rms_ratio=null`, `possible_midpoint_cancellation=false`, `possible_cancellation_positions=[]`, car **il n'existe pas de crossfade continu fractionnaire** dans le mode stock modélisé. Les métriques RMS de changements de Waves restent mesurées comme proxy, pas comme certitude de clic audible.

**Limites :** les 61 Waves sont déjà présentes dans les jobs M2. Le calcul interne des formes intermédiaires pour les **positions de table vides** (manuel Waldorf pp. 32–35) n'est pas simulé. De même, pas d'aliasing Waldorf exact, pas de resampling/filtre natif, pas d'accurate `TimeQuant`, ni de parité Xenia. Le signal est un mono synthétique de test, à fréquence de sortie configurable (48 kHz par défaut, sans prétendre imiter les 40 kHz internes de Xenia).

## Sécurité / intégrité

- Nouveaux profils = opt-in; absence de profil = compatible historique mais avertissement.
- Les noms de profil, déclarations de fidélité et réglages sont vérifiés lors de la vérification du rapport. Les hachages assurent l'intégrité des fichiers *dans le job*, non l'authenticité cryptographique d'un tiers.
- Aucune ROM, aucun firmware et aucun dump utilisateur ne sont inclus dans ce livrable.
- Valider la suite complète `python -m unittest discover -s tests -t . -v` avant toute publication M3.
