# État vérifié du laboratoire — 2026-10-30

## Référence Git et architecture

- Dépôt public : `vx-ghst/XT-WAVETABLE-LAB`, branche `main`.
- Dernier commit public **vérifié avant le commit M1** : `591495653370712ae192715cd4bd5abf73dcf135` (`docs: establish canonical project architecture and audits`). Le commit initial est `d5ed656`.
- Arborescence canonique publiée : code sous `src/xtwavetable/`, tests sous `tests/`, scripts sous `scripts/audit/`, documentation publique sous `docs/`.
- Les **15 nouveaux fichiers M1** de code, tests et scripts sont présents localement et ajoutés à l'index Git (`A`), d'après la sortie `git status --short` transmise. `git diff --cached --check` ne signale pas d'erreur. **Aucun commit ni push M1 n'a encore été confirmé.**
- `private/`, `reports/`, `runs/`, `upstream/`, `build/`, `.vscode/` et `test-plugins/` restent hors du dépôt public.

## M0 — Base de recherche et environnement (validé sur le périmètre audité)

- Gearmulator / Xenia verrouillé au commit `7f9a9806b7b3326379a39a2008c6dc92519191df` ; Tallent Edition référencé au commit `fc02c58ded5ef2f8e4f853a8e4530326787fd0a6`.
- Builds Xenia VST3 Release et Debug réussis sur Windows 11 avec MSVC ; chargement et signal audio observés dans Ableton Live 12.
- Débogage `cppvsdbg`, breakpoints et inspection de `xtDevice.cpp::sendLeds` validés.
- Audit statique Gearmulator 24.1 exécuté sous Windows : **19/19 PASS**, commit attendu identique au commit observé, working tree upstream propre. Il s'agit d'un audit de sources, non d'une certification de fidélité sonore.
- Deux Dump Everything privés précédemment comparés en lecture seule : 667 messages chacun, 64 messages modifiés et 603 identiques.
- Les firmwares, ROMs, dumps et fichiers personnels ne sont pas publiés.

## M1 — Modèle Wave/Table, codec SysEx et inspection des dumps

**Statut : VALIDÉ TECHNIQUEMENT EN LOCAL — PUBLICATION GIT À FINALISER.**

### Implémentations locales validées

- Modèles `Wave` et `Table` : `src/xtwavetable/model/`.
- Codec SysEx standard XT, commandes `WaveDump` (`0x12`) et `WaveCtlDump` (`0x13`) : `src/xtwavetable/codec_xt/`.
- Inspecteur read-only : `scripts/audit/xt_codec_inventory.py`.
- Comparaison avec l'encodeur C++ verrouillé : `scripts/audit/xt_cpp_encoder_compare.py`.
- Tests déterministes : `tests/unit/` et `tests/integration/`.

### Preuves d'exécution sur Windows 11

| Vérification | Résultat | Périmètre |
|---|---:|---|
| Suite Python `unittest` | **48/48 PASS** | Modèles, codec, corruption, cas limites, inspecteur, tests préparatoires C++ |
| Dump Everything — 31 juillet 2026 | **282/282** round-trips identiques | 250 waves et 32 tables |
| Dump Everything — 4 août 2026 | **282/282** round-trips identiques | 250 waves et 32 tables |
| Complétude waves/tables utilisateur | **PASS** sur les deux dumps | Aucune wave/table utilisateur manquante |
| Confrontation avec les fonctions C++ Gearmulator | **30/30 PASS**, 0 différence | Vecteurs synthétiques ; MSVC `cl` |
| Écriture sur le XT, flash ou transfert MIDI | **Aucune** | Traitement exclusivement hors ligne |

Les rapports JSON restent sous `reports/` et ne doivent pas être ajoutés à Git. Les dumps d'origine restent sous `private/`.

### Limites et précautions

- Les **385 autres messages** de chaque dump (256 Singles, 128 Multis, 1 Global) sont dénombrés, mais ne sont pas certifiés sémantiquement par l'inspecteur M1.
- Les positions de table 61–63, les sentinelles et autres références particulières sont préservées lors du round-trip ; elles ne doivent pas être converties arbitrairement en références ordinaires.
- Les waves utilisateur non référencées ne sont **pas nécessairement libres ni écrasables**.
- Les 30 vecteurs C++ confirment l'identité binaire sur le corpus testé, pas une équivalence universelle ni une validation matérielle.
- Les essais Xenia réalisés précédemment ne constituent pas la validation M4 d'un moteur de rendu automatisé, et aucun résultat de fidélité sonore Xenia vs XT physique n'est certifié.

## Publication M1 — Actions restantes

1. Vérifier le **diff indexé complet**, les chemins, les licences et l'absence de données privées.
2. Ajouter les corrections de `docs/ARCHITECTURE.md` et `docs/STATUS.md` aux 15 nouveaux fichiers M1.
3. Relancer les 48 tests si le code change avant commit ; vérifier `git diff --cached --check`, `git diff --cached --name-only` et `git diff --cached`.
4. Créer puis pousser le commit M1 seulement après revue. Mettre à jour le présent statut avec le SHA réellement publié lors d'une révision ultérieure.

## Non confirmé ou hors du jalon courant

- Aucun moteur métier WAV → wavetable n'est encore implémenté ou validé : **M2 non commencé**.
- Rendu Xenia Stock automatisé et reproductible : **M4 non commencé**.
- Démarrage et compatibilité de Tallent Edition dans Xenia : **non démontrés** (M5).
- Comparaison sonore ou numérique avec le Waldorf XT physique : **non certifiée** (M7 optionnel).
- Licence du code original du laboratoire : **non choisie**.
- Le script historique `XT_STEP24_1_AUDIT_V12.ps1` était absent du ZIP de migration examiné ; le résultat 19/19 repose sur la sortie locale et le rapport JSON fournis, et non sur une réexécution depuis ce ZIP.

## Étape suivante

**Clôturer la publication Git de M1**, puis ouvrir **M2 — convertisseur WAV → XT déterministe** conformément à `docs/spec/03_ROADMAP.md`. Ne pas démarrer l'intégration hardware, le flash, la GUI ou Tallent Edition pendant cette clôture.
