# XT-WAVETABLE-LAB — règles de recherche et d'ingénierie

> Instructions de travail destinées aux assistants techniques qui lisent le dépôt.
> Elles ne remplacent pas les décisions explicites de l'utilisateur ni les tests.

## Ordre de preuve AVANT l'implémentation

Pour toute affirmation ou hypothèse qui concerne le **fonctionnement interne du Waldorf Microwave II / XT / XTk**, procéder dans cet ordre :

1. Lire les passages pertinents du **manuel Waldorf** et identifier clairement la révision du manuel (le manuel français de 1998 n'est pas en soi une spécification exhaustive du firmware 2.33).
2. Examiner **les deux dépôts**, pas seulement l'un :
   - `brandon-tallent/microwave-xt-extended-firmware` (source assembleur Tallent et manuel de l'extension) ;
   - `dsp56300/gearmulator` (`source/waldi/xt`, implémentation Xenia et interfaces d'émulation CPU/DSP).
3. Consigner **les chemins, les URL et le SHA complet des commits consultés**, ainsi que la portion de code utile.
4. Marquer chaque assertion selon : `SOURCE_DIRECTE`, `DEDUCTION`, `APPROXIMATION_IMPLEMENTEE`, `NON_VERIFIE`, `CONTREDIT` ; ne jamais confondre un test logiciel PASS avec une validation du DSP réel.
5. Seulement si les sources ne suffisent pas, formuler un protocole d'essai reproductible sous **Xenia** avec firmware précisément identifié ; réserver les essais physiques pour les inconnues persistantes.

Référence canonique : [`docs/spec/12_M3_SOURCE_REGISTRY.md`](docs/spec/12_M3_SOURCE_REGISTRY.md). Audits historiques : [`docs/spec/08_M3_5_SOURCE_AUDIT.md`](docs/spec/08_M3_5_SOURCE_AUDIT.md) et [`docs/spec/10_M3_6_MANUAL_SOURCE_AUDIT.md`](docs/spec/10_M3_6_MANUAL_SOURCE_AUDIT.md).

## Invariants XT-WAVETABLE-LAB

- Séparer **(A) représentation et format des Waves**, **(B) calcul des positions vides de la Wavetable**, **(C) sélection discrète ou balayage fractionnaire des positions**, et **(D) lecture intra-Wave, harmoniques et aliasing**.
- Le profil stock `xt233-discrete-approx` **n'est pas** une émulation bit-identique. Les profils `tallent-e352-approx` et `tallent-honda-approx` restent des modèles.
- Le manuel indique des **cycles entiers possibles** : la demi-Wave de 64 échantillons ne doit pas être décrite comme le seul format imaginable. Notre encodeur M1/M2 reste volontairement limité au **WaveDump SysEx standard validé**.
- Ne jamais substituer la décimation simplifiée de `xtWavePreview.cpp` au DSP physique : le code avertit que l'équivalence au matériel est inconnue.
- Préserver la reproductibilité des jobs existants ; pas de changement silencieux de valeurs par défaut ni de manifestes ; chaque changement de comportement requiert de nouveaux tests.
- **Aucun MIDI matériel**, aucun flash, aucune écriture sur le XT sans autorisation explicite et protocole de sauvegarde. Les données utilisateur, ROM propriétaires, mises à jour officielles et dumps restent privés ; ne pas les publier.
- Ne pas modifier l'ordre artistique des Waves automatiquement : tout réordonnancement est *opt-in*, diagnostiqué et soumis à validation humaine.

## Chaque nouveau jalon doit produire

- Un mini-registre `assertion -> source + commit + fichier -> conclusion + incertitudes` ;
- une revue différentielle des hypothèses héritées ;
- des tests positifs, négatifs et de non-régression ;
- un état séparé `tests locaux`, `tests Windows utilisateur`, `publié Git` et `équivalence Xenia/hardware` ;
- un contrôle de périmètre Git avant tout commit et push.

**Source de vérité documentaire** : les fichiers versionnés dans ce dépôt. L'assistant d'une autre conversation doit relire ces fichiers ; une mémoire conversationnelle ne garantit pas à elle seule la conservation de tous les détails techniques.
