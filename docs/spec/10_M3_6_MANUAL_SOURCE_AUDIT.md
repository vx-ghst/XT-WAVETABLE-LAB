# M3.6 — audit différentiel des sources : manuel Waldorf, Tallent, Xenia

Date : 2026-10-30. Statut : **lecture statique + tests de logiciel, PAS une certification du DSP**.

## Hiérarchie des sources

1. **Manuel Waldorf utilisateur français** : *Guide d'utilisation MicroWave II / MicroWave XT*, révision 12/01/1998, exemplaire fourni par l'utilisateur ; **PDF pages 30 à 34** (pages imprimées 32 à 36), et **PDF page 45** (imprimée 46). Le fichier source n'est **pas redistribué**.
2. **Tallent**, dépôt `brandon-tallent/microwave-xt-extended-firmware`, commit épinglé `fc02c58ded5ef2f8e4f853a8e4530326787fd0a6`, fichiers `src/features/morph/morph.asm`, `morph_constants.inc`, `src/hooks.asm`, et [manuel en ligne](https://brandon-tallent.github.io/microwave-xt-extended-firmware/manual.html#interp).
3. **Gearmulator/Xenia**, dépôt `dsp56300/gearmulator`, commit épinglé `7f9a9806b7b3326379a39a2008c6dc92519191df`, `source/waldi/xt/xtLib/xtDSP.cpp`, `xtWavePreview.cpp`, `xtRomLoader.cpp`, `xtState.cpp`, `xtMidiTypes.h`.

### Découverte majeure : DEUX étapes de table, pas une

- **Construction des 61 positions éditables** : le manuel (PDF pp. 30, 32–33) précise que certains pointeurs de table sont **absents** et que le synthétiseur génère des formes intermédiaires. Exemple officiel : entrées à 00 et 02, interpolation **50/50** en position 01 ; entrées à 02 et 05, **2/3–1/3** et **1/3–2/3** en 03/04. C'est un *pré-remplissage* de positions discrètes, non un fondu audio continu pendant une modulation fractionnaire.
- **Balayage d'une table** : le firmware 2.33 d'origine sélectionne des **positions entières** ; la Tallent Edition ajoute des positions fractionnaires avec interpolation entre Waves pour les modes `E352` et `Honda`.
- **Conséquence** : « XT ne fait aucun type d'interpolation » est FAUX. « XT 2.33 ne fait pas de crossfade fractionnaire continu entre positions à chaque lecture » est étayé par le code Tallent. « Le modèle M3.1 nearest reproduit exactement toutes les positions, toutes les règles de génération des entrées vides et les seuils temporels du XT » est NON DÉMONTRÉ.
- **Implémentation de nos jobs M2** : ils utilisent 61 références explicites aux Waves du bundle ; nos profils M3.6 ne simulent **pas** la génération interne de positions de table *sparse* dont les pointeurs sont omis. Elles ne doivent pas être appelées « interpolation spectrale exacte » : le manuel explique des mélanges d'amplitudes entre Waves, mais ne décrit pas un calcul spectral DSP exact.

### Wave, symétrie et type de stockage

- La formule `W[64+n] = -W[63-n]` (n = 0..63) décrit la représentation **half-cycle** du dump standard reconnu par notre codec ; elle équivaut à `W[127-n] = -W[n]`.
- **Cas -128 :** une négation sur 8 bits se fait **modulo 256**. Notre `Wave.from_half_cycle()` le préserve pour garantir des round-trips exacts. Pour une génération musicale classique, éviter le -128 en quantifiant par ±127 afin d'obtenir une anti-symétrie en entiers sans dépassement.
- Le manuel utilisateur, **PDF page 32 (imprimée 34)**, précise qu'en plus de la plupart des Waves demi-cycle, le Microwave II/XT peut aussi stocker des **cycles complets**. Cette capacité n'est **pas** prise en charge par notre `codec_xt/sysex.py` limité à la commande de dump Wave standard `0x12` de 64 échantillons. **NE PAS** étendre la formule half-cycle à tous les types d'ondes présents dans le synthétiseur.
- **Écriture MIDI :** les 64 octets quantifiés XOR `0x80` de l'exemple théorique sont **128 nibbles MIDI** dans notre paquet SysEx standard : un WaveDump complet a **137 octets**, pas un paquet MIDI de 64 octets. Validé par le code et les tests M1; ne pas reprendre tel quel le tableau `encoded` de l'exemple comme un message SysEx complet.

### Formule additive (mathématique / proposition, pas une formule obligatoire du manuel)

L'expression fournie par l'utilisateur est une **méthode de synthèse valide**, pas l'unique méthode officielle de fabrication d'une Wave :

`h[n] = Σ_k A_k * sin(2πk(n+0.5)/128)`, `n=0..63`.

Le demi-échantillon permet la réflexion inverse `h[127-n] = -h[n]` pour **tous les harmoniques k entiers**, y compris les pairs, lorsque les 128 échantillons sont calculés avec cette expression. Normalisation puis arrondi ±127, enfin reconstruction avec `Wave.from_half_cycle` et encodage `encode_wave_dump`.

Ceci **ne résout pas** par magie la réduction d'un WAV arbitraire à un seul cycle. Les opérations existantes M2.4 (extraction, projection sur la symétrie) peuvent perdre de l'information : phase, composantes non stationnaires, bruit, transitoires, largeur d'impulsion et harmoniques.

### Interpolation intracycle, aliasing et TimeQuant

- Le manuel (PDF page 45, imprimée 46) distingue `Aliasing`, `TimeQuant`, `Accuracy` et `Clipping` ; l'interpolation/limitation d'harmoniques mentionnée dans `TimeQuant` ne doit pas être confondue avec **l'interpolation entre positions de table**.
- Gearmulator `xtDSP.cpp` : le DSP est émulé ; le rendu nominal configuré est **40 kHz**, mais le code C++ périphérique ne décrit pas l'algorithme DSP Waldorf en entier.
- Gearmulator `xtWavePreview.cpp` : réduction successive simplifiée des résolutions; commentaire de l'auteur indiquant qu'il ignore si c'est ainsi que le matériel le fait. Ce code n'est **PAS** une preuve de la décimation ou de l'interpolation exacte du hardware.
- Tallent `morph.asm` : profils de comportement différents `XT`, `E352` et `Honda`. Pour M3.6, nous proposons des **proxies** maths, pas une égalité bit-à-bit aux sorties audio de l'extension.

## Revue des anciennes fonctions (écarts et actions)

| Composant | Verdict M3.6 | Décision |
|---|---|---|
| M1 Wave/Table codec | **périmètre validé uniquement pour les paquets standards compatibles** | Conserver. Étudier ultérieurement le stockage de cycles complets et les autres formats. |
| M2.4 cycle et symétrie | **conforme à la contrainte du format choisi** | Conserver, garder explicites les pertes de projection. |
| M2.5 placement 61 Waves | **politique logiciel, non interpolation native des pointeurs vides** | Conserver, éviter d'attribuer une interpolation spectrale hardware. |
| M3.1 crossfade `linear` implicite | **source d'ambiguïté** | Profils nommés ajoutés, ancien défaut intact pour reproductibilité, avertissement dans CLI. |
| M3.2 diagnostic de cancellation | **inapplicable au stock discret** | Pour un profil nommé XT, utiliser `null` et `false`, validation anti-altération. |
| M3.3/3.4 CLI et rapports | **anciens résultats à préserver** | `--render-profile` optionnel ajouté : omission = sortie ancienne inchangée + avertissement, sélection = nouvelles métadonnées vérifiées. |
| M3.5 transition stock | **proxy RMS sur positions explicites** | Conserver. Pas de modification des exports / ordre sans approbation. |

## Non-certifications restantes

Les seuils exacts d'arrondi 2.33 ; la génération binaire de positions sparse ; le support complet de Waves 128-échantillons indépendantes ; le pitch et le bandlimiting ; les effets `Aliasing` / `TimeQuant` ; le comportement de l'enveloppe/modulation ; les clics au changement de Patch ; la parité Xenia/Tallent/matériel. **Ne pas déclarer validé sans test externe reproduisible.**

L'ordre de recherche prioritaire est **manuel Waldorf → Tallent et Gearmulator/Xenia, code/commits épinglés → hypothèses explicitement marquées → expérience Xenia → mesure sur XT réel**.
