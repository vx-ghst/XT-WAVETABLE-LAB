# État vérifié du laboratoire — 2026-10-30

## Référence Git et architecture

- Dépôt public : `vx-ghst/XT-WAVETABLE-LAB`, branche `main`.
- Dernier commit public vérifié : `8dd121e4bac482ec56ae09441530a454db0adcb6` (`feat(m1): implement validated XT SysEx codec and dump inspector`). Commit précédent d'architecture : `591495653370712ae192715cd4bd5abf73dcf135`. Commit initial : `d5ed656`.
- Arborescence canonique publiée : code sous `src/xtwavetable/`, tests sous `tests/`, scripts sous `scripts/audit/`, documentation publique sous `docs/`.
- M1 est publié et la synchronisation `main...origin/main` a été confirmée dans le journal de push. Le code M2 est présent localement, encore **non suivi** par Git selon `git status --short` du 30 octobre 2026 ; aucun commit ni push M2 n'est confirmé.
- `private/`, `reports/`, `runs/`, `upstream/`, `build/`, `.vscode/` et `test-plugins/` restent hors du dépôt public.

## M0 — Base de recherche et environnement (validé sur le périmètre audité)

- Gearmulator / Xenia verrouillé au commit `7f9a9806b7b3326379a39a2008c6dc92519191df` ; Tallent Edition référencé au commit `fc02c58ded5ef2f8e4f853a8e4530326787fd0a6`.
- Builds Xenia VST3 Release et Debug réussis sur Windows 11 avec MSVC ; chargement et signal audio observés dans Ableton Live 12.
- Débogage `cppvsdbg`, breakpoints et inspection de `xtDevice.cpp::sendLeds` validés.
- Audit statique Gearmulator 24.1 exécuté sous Windows : **19/19 PASS**, commit attendu identique au commit observé, working tree upstream propre. Il s'agit d'un audit de sources, non d'une certification de fidélité sonore.
- Deux Dump Everything privés précédemment comparés en lecture seule : 667 messages chacun, 64 messages modifiés et 603 identiques.
- Les firmwares, ROMs, dumps et fichiers personnels ne sont pas publiés.

## M1 — Modèle Wave/Table, codec SysEx et inspection des dumps

**Statut : VALIDÉ TECHNIQUEMENT ET PUBLIÉ (commit `8dd121e`).**

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

## Publication M1 — clôturée

- Publication GitHub vérifiée : `8dd121e4bac482ec56ae09441530a454db0adcb6` sur `main` ; 17 fichiers dans le commit (15 ajouts de code/tests/scripts et 2 documents modifiés).
- Aucune ROM, firmware ou dump personnel ne figure dans les chemins publiés du commit M1.

## M2 — MVP déterministe WAV → XT → SysEx (candidat à publication)

**Statut : M2.1 à M2.8 VALIDÉS LOCALEMENT sur le périmètre exécuté ; documentation et publication Git M2 à finaliser.**

| Sous-étape | Fonctionnalité développée | État observé |
|---|---|---|
| M2.1 | WAV mono/stéréo : PCM 16/24/32, Float 32, fréquences natives dont 44,1 / 48 / 96 kHz | PASS |
| M2.2 | Crop, downmix explicite, retrait DC, normalisation Peak optionnelle | PASS |
| M2.3 | F0 estimée, périodicité, centroïde et flux spectraux (heuristiques) | PASS |
| M2.4 | Extraction de cycles candidats et projection vers la géométrie Wave XT | PASS |
| M2.5 | Sélection uniforme/diversité, dédoublonnage, 8/16/32/61 Waves | PASS |
| M2.6 | Snapshot complet, Wave/Table IDs explicitement autorisés, export SysEx hors ligne | PASS |
| M2.7 | Pipeline déterministe intégrant WAV, modèles, analyse, sélection et export | PASS |
| M2.8 | CLI `convert`/`verify`, artefacts privés sous `runs/`, double conversion et contrôle d'intégrité | PASS sur le périmètre testé |

### Preuve Windows du 30 octobre 2026

- `python -m unittest discover -s tests -t . -v` : **250 tests exécutés ; 250 PASS, 0 SKIP, 0 FAIL, 0 ERROR**, sortie `Ran 250 tests in 15.549s` puis `OK`.
- Les **quatre scénarios de liens symboliques** (`test_job_symlink_guard`, `test_nested_symlink_inside_private_rejected`, `test_symlink_escape_rejected`, `test_symlink_runs_rejected`) ont d'abord été classés SKIP en raison de `WinError 1314` (droits Windows insuffisants). Après activation du mode développeur, la création de symlinks sans administrateur a été vérifiée `[PASS]`, puis ces **4 tests ont réussi individuellement (4/4 PASS)** et lors de la **suite complète (250/250 PASS)**. La sortie complète a été fournie par l’utilisateur le 30 octobre 2026. Ces 4 SKIP restent un résultat historique antérieur, et non l'état final.
- `python -m xtwavetable.cli.convert convert --help` : options de la CLI affichées ; cette vérification ne crée pas de job.
- `git status --short` : modules M2 non suivis (`src/xtwavetable/audio/`, `analysis/`, `converter/`, `optimizer/`, `export/`, `cli/`), tests nouveaux et `docs/spec/05_M2_CLI_GUIDE.md`. Aucune publication M2 observée.
- Les vérifications de reproductibilité dans les tests portent sur des **fixtures synthétiques**. Aucun essai de qualité musicale avec des échantillons utilisateur, aucun rendu par interpolation XT et aucune validation sur synthétiseur physique.

### Limites et garde-fous M2

- Les 250 Waves et 32 Tables utilisateur du snapshot sont vérifiées ; les commandes Single/Multi/Global et certaines dépendances spéciales ne sont pas sémantiquement certifiées.
- Un slot non référencé n'est jamais considéré comme libre. Toute destination RAM et tout remplacement sont explicitement autorisés **pour la fabrication d'un artefact offline seulement**.
- La CLI ne comporte aucun accès matériel, flash, ni émission MIDI ; générer un `.syx` ne vaut jamais permission de l'envoyer au XT.
- L'analyse de hauteur et les critères de diversité/projection ne prouvent pas la fidélité perceptive. Les transitions entre Waves et l'interpolation XT restent à tester en M3/M4.
- Fichiers WAV limités à 64 Mio et sauvegardes SysEx à 16 Mio par l'interface M2.8 actuelle ; pas de streaming de très gros fichiers.
- Les rapports produits sous `runs/` contiennent des empreintes de données privées : **ne pas les publier**.

### Dernières actions avant publication M2

1. Vérifier la liste exacte des **23 nouveaux fichiers M2** et les quatre documents actualisés, puis inspecter le diff indexé complet.
2. Archiver le journal Windows du **250/250 PASS, 0 SKIP** ainsi que le contrôle ciblé des 4 symlinks ; ne pas confondre cet acquis de sécurité avec une validation matérielle ou perceptive.
3. Lors de la publication, enregistrer le nouveau SHA Git ; ne pas déclarer M2 publié avant `git push` confirmé.

## Non confirmé ou hors du jalon courant

- Le moteur WAV → XT hors ligne est développé et validé sur fixtures synthétiques ; **qualité sonore perceptive et rendu d’interpolation non validés** (M3/M4).
- Rendu Xenia Stock automatisé et reproductible : **M4 non commencé**.
- Démarrage et compatibilité de Tallent Edition dans Xenia : **non démontrés** (M5).
- Comparaison sonore ou numérique avec le Waldorf XT physique : **non certifiée** (M7 optionnel).
- Licence du code original du laboratoire : **non choisie**.
- Le script historique `XT_STEP24_1_AUDIT_V12.ps1` était absent du ZIP de migration examiné ; le résultat 19/19 repose sur la sortie locale et le rapport JSON fournis, et non sur une réexécution depuis ce ZIP.

## Étape suivante

**Finaliser la revue documentaire/sécurité et la publication Git de M2**, après la suite Windows 250/250 PASS sans SKIP. Ensuite ouvrir **M3 — préécoute approximative, simulation de transitions/interpolation et batch QA** selon `docs/spec/03_ROADMAP.md`. Ne pas démarrer le flash, la GUI, ni Tallent Edition pendant cette clôture.
