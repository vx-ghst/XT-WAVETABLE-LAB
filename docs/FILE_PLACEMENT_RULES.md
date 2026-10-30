# Règles obligatoires pour toute nouvelle contribution

**Toujours choisir l'emplacement à partir de la fonction du fichier, jamais au hasard.**

| Ce que tu crées | Où ? | GitHub public ? |
|---|---|---|
| Parser/encodeur SysEx, types XT | `src/xtwavetable/codec_xt/`, `model/` | Oui |
| Lecture WAV, DSP, algorithmes de sélection | `src/xtwavetable/audio/`, `analysis/`, `converter/`, `optimizer/` | Oui |
| CLI | `src/xtwavetable/cli/` | Oui |
| Intégration Xenia (code original) | `adapters/xenia/` | Oui, après revue de licence |
| Modification nécessaire de Gearmulator | patch texte sous `patches/gearmulator/` + explication | Oui après revue GPL ; ne pas faire de modifications permanentes non suivies dans `upstream/` |
| Tests déterministes | `tests/unit/` | Oui |
| Tests facultatifs sur matériel / ROM | `tests/integration/` + fichiers d'entrée dans `private/` | Tests oui, données non |
| Scripts d'inspection génériques | `scripts/audit/` | Oui |
| Architecture, spécifications, ADR, résultat de recherche sans donnée privée | `docs/` | Oui |
| Comparaison de dumps réels, manifeste de firmware personnel, état matériel détaillé | `private/docs/` | Non |
| Dumps Everything | `private/dumps/xt-original/` | Non |
| Firmware/EPROM et update officiel | `private/firmware/stock-v233/` | Non |
| WAV sources et prises audio XT | `private/audio/` | Non |
| Résultats de calcul, exports SYX/WAV, rapports de jobs | `runs/<run_id>/` | Non |
| Inventaire local, audit machine, logs | `reports/` | Non |
| Compilations CMake/Ninja et symboles PDB | `build/`, sorties upstream, `test-plugins/` | Non |
| Copie historique de bootstrap | `private/old_package/` | Non |

## Contrat d'une session de travail

1. Lire `docs/ARCHITECTURE.md`, `docs/STATUS.md`, `docs/UPSTREAM_LOCK.md` et les documents métier pertinents.
2. Annoncer avant codage les fichiers exacts à créer/modifier et les tests associés.
3. Implémenter sous `src/`, `adapters/` ou `scripts/` uniquement ; tests sous `tests/`.
4. Exécuter tests locaux avec données synthétiques ; classifier PASS, FAIL, SKIP, BLOCKED sans les confondre.
5. Produire les résultats sous `runs/` et les audits de machine sous `reports/`.
6. Vérifier `git diff --cached --name-only` avant chaque commit ; contrôler la présence de données privées ou de chemins locaux.
7. Ne jamais changer de révision upstream sans enregistrer la décision et ses implications.
8. Un nouveau script ne doit jamais être enregistré dans `private/docs/` : la documentation explique ; le code exécutable est dans `scripts/` ou `src/`.

## Anti-patterns à refuser

- `project/project/src/...`, `private/docs/mon_script_final_v17.py`, `reports/codec_definitif.cpp`, `upstream/gearmulator/source/.../mon_converter_original.cpp` sans patch/fork, scripts PowerShell isolés à la racine, copie de ROM dans `tests/fixtures/`.
- Écraser un fichier existant ou régénérer un projet complet sans audit différentiel.
- Mettre en ligne des JSON de `reports/` contenant des chemins Windows, des identifiants matériels ou des empreintes de fichiers privés.
