# M3.4 — Comparaison par lots (moteur de préécoute APPROXIMATIF)

## Objectif

Comparer de **2 à 6 exports M2.8 déjà vérifiés**, issus du **même Dump Everything XT** (même empreinte du dump). Les WAV sources peuvent différer. La méthode garde les mêmes paramètres de lecture pour chaque candidat et mesure toutes les paires : N(N−1)/2 comparaisons, sans note perceptive ni gagnant automatique.

La CLI ne lit **aucun WAV original ni dump brut** : elle charge uniquement les quatre artefacts de chaque job M2.8 existant sous `runs/`. Elle vérifie leur intégrité via M3.3 avant de les soumettre au moteur M3.1. Une seconde exécution indépendante doit produire des résultats binaires identiques avant tout export. Une opération réussie n'autorise jamais l'envoi au synthétiseur.

## Exemples (ne lancer qu'après création de jobs M2.8 réels)

```powershell
cd "D:\DEV\XT-WAVETABLE-LAB"
$env:PYTHONPATH = "$PWD\src"
python -m xtwavetable.cli.preview_batch batch --help
python -m xtwavetable.cli.preview_batch verify --help
```

Exemple avec trois jobs existants `TEST_M2_A`, `TEST_M2_B`, `TEST_M2_C` :

```powershell
python -m xtwavetable.cli.preview_batch batch `
  --job TEST_M3_BATCH_01 `
  --sources TEST_M2_A TEST_M2_B TEST_M2_C `
  --sample-rate 48000 `
  --frequency-hz 220 `
  --duration-seconds 1 `
  --table-interpolation linear `
  --phase-interpolation linear
```

Sorties sous **un nouveau** `runs/TEST_M3_BATCH_01/` :

- `preview_C01.wav`, `preview_C02.wav`, `preview_C03.wav` (PCM16 mono) ; chaque `Cnn` correspond à l'ordre de `--sources` ;
- `batch_report.json` (60 transitions par candidat, RMS/peak, empreintes et toutes les comparaisons numériques) ;
- `batch_audit.json` (contrôles d'intégrité des fichiers et statut « UNSIGNED_INTEGRITY_ONLY »).

Vérification en lecture seule :

```powershell
python -m xtwavetable.cli.preview_batch verify --job TEST_M3_BATCH_01
```

## Périmètre et limitations

- Le rendu est l'approximation **M3.1**, non la modélisation certifiée du DSP Waldorf. Les indicateurs de transitions M3.2 restent **heuristiques non calibrées**.
- Les comparaisons n'établissent **aucun classement musical** ; les égalités PCM16 peuvent différer des égalités en float64, explicitement identifiées dans le rapport.
- 2..6 candidats, **100 000 frames maximum par candidat**. Le dépassement est rejeté, pas tronqué automatiquement.
- Les noms des jobs doivent respecter la syntaxe ASCII stricte. Les symlinks vers des jobs ou artefacts sont rejetés. Jamais de réécriture d'un job existant ; sources et fichiers privés inchangés.
- Les rapports utilisent des **SHA-256 non authentifiés**, pas des signatures d'origine. Les identifiants des jobs sources ne sont pas inscrits dans les rapports ; seuls les labels `C01` etc. identifient leur ordre.
- Le dossier `runs/` reste ignoré par Git. Aucune communication MIDI, aucun accès USB, ROM, firmware ou transfert/flash matériel.
- Les tests ne contiennent que des WAV et des dumps **synthétiques** ; les essais musicaux nécessiteront des samples réels ultérieurement.
