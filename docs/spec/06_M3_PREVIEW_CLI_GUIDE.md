# M3.3 — Préécoute A/B des candidats M2 validés (hors ligne)

## Périmètre

La CLI M3.3 charge deux jobs **M2.8 déjà produits** et déjà stockés sous `runs/<nom>/`. Elle vérifie les quatre artefacts du job (`xt_candidate.syx`, `xt_candidate.json`, `xt_pipeline.json`, `xt_audit.json`), reconstruit les références Wave/Table, contrôle leur cohérence, puis utilise le moteur M3.1 et le comparateur M3.2 **approximatifs** pour produire deux WAV A/B et un JSON de diagnostic.

Aucune lecture de données privées brutes, aucun MIDI, aucun firmware, aucune modification d'un synthétiseur. Les jobs sources ne sont jamais modifiés. Le nouveau résultat exige un nom de job inexistant et reste dans `runs/` (exclu de Git).

## Commandes

```powershell
cd "D:\DEV\XT-WAVETABLE-LAB"
$env:PYTHONPATH = "$PWD\src"
python -m xtwavetable.cli.preview_ab compare --help
python -m xtwavetable.cli.preview_ab verify --help
```

Deux jobs M2.8 distincts, **créés préalablement**, par exemple `TEST_M2_A` et `TEST_M2_B`, doivent exister dans `runs/`. Ne pas exécuter cet exemple sans eux :

```powershell
python -m xtwavetable.cli.preview_ab compare `
  --job TEST_M3_AB_01 `
  --source-a TEST_M2_A `
  --source-b TEST_M2_B `
  --sample-rate 48000 `
  --frequency-hz 220 `
  --duration-seconds 1 `
  --start-position 0 `
  --end-position 60 `
  --table-interpolation linear `
  --phase-interpolation linear
```

Sortie :

- `runs/TEST_M3_AB_01/preview_A.wav`
- `runs/TEST_M3_AB_01/preview_B.wav`
- `runs/TEST_M3_AB_01/preview_AB_report.json`

Vérification sans écriture :

```powershell
python -m xtwavetable.cli.preview_ab verify --job TEST_M3_AB_01
```

## Garde-fous / limites

- Les deux candidats doivent déclarer le **même hash de sauvegarde XT**, pas forcément le même WAV source. Les sources sont des exports M2.8 vérifiés, pas des SysEx isolés non audités.
- La CLI relance la comparaison deux fois et exige l'identité des fichiers WAV et JSON avant d'écrire. Aucune écriture en cas d'échec de chargement ou de calcul.
- Les noms de jobs ne contiennent que des caractères ASCII simples. Les liens symboliques de jobs et d'artefacts sont refusés.
- `verify` est un contrôle d'intégrité par hash **non authentifié**, et non une garantie d'origine ou une signature cryptographique.
- Le rapport de transitions contient des heuristiques sans calibration perceptive. Aucun « gagnant » automatique.
- Interpolation **approximative** (crossfade M3.1) ; la fidélité au DSP du Microwave XT n'est pas démontrée. Validation Xenia stock en M4 et hardware optionnel en M7.
- Aucune opération MIDI, USB, SysEx vers un appareil, firmware ou flash n'est implémentée.
- Les tests n'utilisent que des fixtures générées et synthétiques. Les WAV personnels seront demandés pour des essais musicaux ultérieurs.
