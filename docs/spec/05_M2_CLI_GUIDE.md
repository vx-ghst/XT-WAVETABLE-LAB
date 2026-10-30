# M2.8 — Interface CLI hors ligne et audit de reproductibilité

**Statut (30 octobre 2026) : validation Windows effectuée ; publication Git M2 en attente.** Suite complète : `Ran 250 tests`, `OK`, soit **250 PASS, 0 SKIP, 0 FAIL, 0 ERROR**. La création de liens symboliques était initialement bloquée par Windows (`WinError 1314`), donnant quatre SKIP historiques. Après activation du mode développeur et contrôle de création sans administrateur, les quatre tests de sécurité symlink ont réussi isolément, puis dans la suite complète. Aucun résultat de qualité perceptive ou de parité matérielle n’en découle.

Depuis la racine du dépôt, avec `PYTHONPATH=src`, utiliser :

```text
python -m xtwavetable.cli.convert convert --help
python -m xtwavetable.cli.convert verify --help
```

Le sous-programme `convert` exige un fichier WAV sous `private/`, un dump
Everything complet sous `private/` (250 user Waves + 32 user Tables), un
`--job` nouveau, une liste d'IDs RAM `--wave-ids`, une liste identique
`--approve-wave-ids`, un `--table-id` et le commutateur
`--authorize-table-replacement`. Les références connues depuis d'autres
Tables bloquent la conversion par défaut ; l'option
`--acknowledge-cross-table-references` autorise leur prise en compte **pour
l'export hors ligne seulement**. Les autres types de messages (Singles,
Multis, Global), certains formats spéciaux et les dépendances de presets
restent non validés. Un emplacement non référencé n'est jamais réputé libre.

Exemple **fictif**, à adapter aux fichiers privés locaux :

```powershell
$env:PYTHONPATH = "$PWD\src"
python -m xtwavetable.cli.convert convert `
  --wav 'private/audio/sample-sources/exemple.wav' `
  --snapshot 'private/dumps/xt-original/sauvegarde.syx' `
  --job 'demo_synthetic_01' `
  --pitch-hz 220 `
  --candidate-count 8 --requested-waves 8 --shortfall reuse `
  --wave-ids 1200,1201,1202,1203,1204,1205,1206,1207 `
  --approve-wave-ids 1200,1201,1202,1203,1204,1205,1206,1207 `
  --table-id 96 --authorize-table-replacement
```

Ces IDs illustrent la syntaxe, **pas des emplacements conseillés**. La
commande ci-dessus remplacerait leurs contenus dans un artefact SysEx
hors ligne ; **ne jamais envoyer cet artefact au synthétiseur**.

La sortie est créée seulement dans un dossier inédit `runs/<job>/` :

```text
xt_candidate.syx   # SysEx standard des Waves et de la Table
xt_candidate.json  # manifeste M2.6
xt_pipeline.json   # manifeste M2.7
xt_audit.json      # hashes et résultat de deux conversions identiques
```

Chaque conversion complète est effectuée deux fois indépendamment et les
octets du SysEx et des deux manifestes sont comparés avant écriture.
Reproduire le même job nécessite un **autre nom de dossier**, sans modifier
les artefacts existants. La commande :

```text
python -m xtwavetable.cli.convert verify --job demo_synthetic_01
```

contrôle les hashes, l'accord des manifestes, l'identité des IDs et la
validité de la structure SysEx des fichiers conservés. Elle **ne relance
pas** la conversion depuis le WAV : le test de reproductibilité est celui
effectué pendant `convert`.

### Interdictions et limites

- Aucun MIDI, upload XT, programmation EPROM, firmware ou accès réseau.
- Aucun nouveau fichier privé ou rapport de job ne doit être ajouté à Git.
- `private/` et `runs/` doivent être des répertoires réels, ignorés par Git.
- Pas d'allocation automatique ou de classement « RAM libre ».
- Fichiers WAV limités à 64 Mio (lecteur M2.1) ; snapshot limité à 16 Mio.
- Qualité perceptive, rendu de l'interpolation XT et fidélité hardware non
  certifiés : M3 et M4 restent nécessaires.
- Les tests automatisés n'utilisent que des WAV/dumps synthétiques temporaires.
