# XT-WAVETABLE-LAB — Architecture canonique du dépôt

**Statut : architecture canonique publiée.** La migration contrôlée et la publication de l'architecture sur GitHub ont été réalisées au commit `591495653370712ae192715cd4bd5abf73dcf135` (30 octobre 2026). Le dépôt principal se trouve à `D:\DEV\XT-WAVETABLE-LAB` ; **il n'existe pas de second dépôt Git dans `project/`**.

## Principe directeur

Un dépôt racine unique pour le **code original du laboratoire**, sa documentation publique et ses tests synthétiques. Des dossiers frères exclus de Git pour les dépendances tierces, les données privées et les artefacts d'exécution. **Ne pas utiliser `project/` comme second dépôt racine.** `project/` était vide dans le ZIP audité lors de la migration ; ne supprimer un éventuel répertoire local qu'après vérification de son contenu sur le PC.

```text
D:\DEV\XT-WAVETABLE-LAB\                      # RACINE GIT (origin: vx-ghst/XT-WAVETABLE-LAB)
  .git/                                        # Métadonnées Git : JAMAIS à copier ou publier
  .gitignore                                   # Exclusions (déjà en place)
  README.md                                    # Porte d'entrée unique (déjà publié)
  docs/                                        # PUBLIC : ADR, architecture, spécification, recherche non sensible
    ARCHITECTURE.md
    FILE_PLACEMENT_RULES.md
    UPSTREAM_LOCK.md
    STATUS.md
    spec/
    research/
  src/xtwavetable/                             # PUBLIC : seul code applicatif original du laboratoire
    model/                                     # Wave, Table, IDs, contraintes : types neutres
    codec_xt/                                  # Parsing, sérialisation, checksum SysEx + validateur
    audio/                                     # Entrée WAV, découpe, mixdown et prétraitement
    analysis/                                  # Fréquence, périodicité, segmentation
    converter/                                 # Extraction / resynthèse de cycles candidats
    optimizer/                                 # Sélection, phase, ressources XT, mapping des slots
    preview/                                   # Préécoute approximative, interfaces d'adaptateurs
    export/                                    # Production des exports après validation
    projectio/                                 # Manifestes, provenance, configurations
    cli/                                       # Interface en ligne de commande
  adapters/xenia/                              # PUBLIC : intégration out-of-process si nécessaire
  patches/gearmulator/                         # PUBLIC : patchs texte révisés si besoin, PAS de ROM
  scripts/audit/                               # PUBLIC : outils de contrôle sans données embarquées
  tests/unit/                                  # PUBLIC : tests sur fixtures synthétiques
  tests/integration/                           # PUBLIC : tests qui SKIP si ressources privées absentes
  upstream/gearmulator/                        # EXCLU : clone Git tiers, commit verrouillé
  upstream/tallent-edition/                    # EXCLU : clone firmware modifié tiers
  private/                                     # EXCLU : actifs utilisateurs, firmware, dumps, métadonnées privées
    firmware/stock-v233/
    firmware/tallent-local/
    dumps/xt-original/
    audio/reference-hardware/
    audio/sample-sources/
    hardware/
    docs/                                      # Rapports personnels, manifestes firmwares, comparaisons de dumps
    old_package/                               # Archives historiques, hors parcours actif
  build/                                       # EXCLU : génération Ninja, objets, caches CMake
  test-plugins/                                # EXCLU : VST3 Debug et Release pour Ableton
  runs/                                        # EXCLU : WAV, SYX, jobs et résultats exécutés
  reports/                                     # EXCLU : JSON, inventaires locaux et résultats bruts
  .vscode/                                     # EXCLU : chemins locaux et configurations debugger
```

Les dossiers logiques `src/xtwavetable/*` décrivent les responsabilités. Ne créer physiquement un sous-dossier que lorsqu'un vrai module ou test y est ajouté : une arborescence vide n'est pas du code.

**État M1 au 30 octobre 2026 :** `src/xtwavetable/model/` et `src/xtwavetable/codec_xt/` sont implémentés et validés localement. Les outils complémentaires sont sous `scripts/audit/`, leurs tests sous `tests/`. Leur première publication GitHub est en préparation et ne doit pas être considérée comme effectuée avant un nouveau commit et son push. Les autres modules métier restent des responsabilités cibles, non des implémentations annoncées.

## Architecture logicielle, indépendamment de l'hébergement Git

```text
WAV d'entrée (private/audio) -> audio -> analysis -> converter -> optimizer
                                                     |
                                                   model
                                                     |
                                                  codec_xt
                                                     |
                                     export SYX + manifest dans runs/<id>/
                                                     |
                           preview approximatif | adapter Xenia | matériel (bloqué)
```

- Le **modèle XT** est une API neutre, sans dépendance au firmware.
- Le **codec XT** opère sur des structures canonisées et s'exécute sans Xenia ni données privées.
- `preview/` décrit un contrat ; il ne remplace jamais le codec.
- `adapters/xenia/` dialogue avec un exécutable externe ou une interface documentée. Ne pas mélanger les interfaces Ableton/VST3 et l'algorithme de conversion.
- Le clone `upstream/gearmulator/` est une **référence tierce verrouillée**, non un lieu où accumuler notre code original. Les changements nécessaires sont exprimés comme patchs suivis ou dans un fork documenté.
- `private/` est un réservoir de données en lecture seule lors des premières phases. Ne jamais modifier les fichiers source ; écrire les dérivés dans `runs/`.

## Limites et garde-fous

- Les projets Xenia Release et Debug compilés restent dans les sorties CMake tierces et `test-plugins/` : **jamais dans `src/` ou sur GitHub**.
- Ne pas publier de `.bin`, `.mid`, `.syx`, `.wav`, `.vst3`, `.pdb`, `.zip` privés, ni de document contenant des données musicales personnelles.
- Les fixtures publiques doivent être entièrement synthétiques ou autorisées.
- Le téléchargement et le flash du hardware sont hors du périmètre courant.
- Une licence publique du code propre reste à décider ; ne pas copier des parties GPL de Gearmulator dans une licence incompatible.

## Archives historiques et risque de confusion

Des documents bootstrap historiques de `private/old_package/*v0.2.zip` décrivent `project/` comme une racine Git. **C'est une architecture antérieure à l'initialisation du Git réel.** Pour ce projet, seule l'architecture racine décrite ici est canonique. Ne pas lancer `CREATE_WORKSPACE.ps1` de l'ancien package comme une migration.
