# M3 — Registre canonique des sources et découvertes (2026-10-30)

**Objet :** mémoire documentaire persistante du projet `XT-WAVETABLE-LAB` avant publication M3. Ce registre complète, sans remplacer, `08_M3_5_SOURCE_AUDIT.md`, `10_M3_6_MANUAL_SOURCE_AUDIT.md` et `11_M3_6_RENDER_PROFILE_GUIDE.md`.

**État des preuves :** M1/M2 publiés au commit `8019745022637d835b21a2f13898bc417f1faf83` ; M3.1–M3.6 testés sur Windows (`Ran 449 tests`, `OK` fourni par l'utilisateur) mais **non publiés lors de la rédaction**. Ces résultats testent l'implémentation, **pas** sa fidélité sonore au XT réel.

## 1. Sources primaires et leur provenance

| ID | Source | Version / référence stable | Usage et limites |
|---|---|---|---|
| `WALDORF-FR-1998` | *Guide d'utilisation MicroWave II / MicroWave XT*, version française fournie par l'utilisateur | Révision annoncée 12 janvier 1998 ; PDF de **118 pages** ; `SHA-256: 1442d05d4d9c02be660f79f7cde90a42f5b016a3af978c059de9072b020a4f7e` | Manuel officiel d'utilisation ; n'est **pas** un inventaire du code du firmware OS 2.33 ; document privé **non joint au dépôt**. |
| `TALLENT-OS233` | [brandon-tallent/microwave-xt-extended-firmware](https://github.com/brandon-tallent/microwave-xt-extended-firmware) | Commit `fc02c58ded5ef2f8e4f853a8e4530326787fd0a6` | Assembleur d'extension pour OS 2.33 ; renseigne les branchements vers les fonctions d'origine, pas l'implémentation complète du firmware Waldorf. |
| `TALLENT-GUIDE` | [Guide Tallent, section Interpolation](https://brandon-tallent.github.io/microwave-xt-extended-firmware/manual.html#interp) | Page web courante consultée 2026-10-30 ; **non figée par commit** dans cette URL | Documentation de l'extension, à confronter au code épinglé. |
| `XENIA` | [dsp56300/gearmulator](https://github.com/dsp56300/gearmulator) | Commit `7f9a9806b7b3326379a39a2008c6dc92519191df` | Émulation et interfaces de l'XT ; le code C++ n'est pas la transcription complète de l'algorithme fermé Waldorf. |
| `XT-LAB-M1` | Code local / GitHub de ce projet | Réf. M2 publiée ci-dessus ; 2 dumps privés round-trip et 30 comparaisons à l'oracle C++ consignées dans l'historique M1 | Preuve de conformité au **périmètre des paquets testés** ; pas au rendu. |

### Fichiers Tallent à consulter en priorité

- [`src/features/morph/morph.asm`](https://github.com/brandon-tallent/microwave-xt-extended-firmware/blob/fc02c58ded5ef2f8e4f853a8e4530326787fd0a6/src/features/morph/morph.asm) : `morph_interp`, `morph_wave1_index`, `morph_wave2_index`, `morph_wave1_position`, `morph_word_blend`, `morph_edge_wave1/2`.
- [`src/features/morph/morph_constants.inc`](https://github.com/brandon-tallent/microwave-xt-extended-firmware/blob/fc02c58ded5ef2f8e4f853a8e4530326787fd0a6/src/features/morph/morph_constants.inc) : `INTERP_XT=0`, `INTERP_E352=1`, `INTERP_HONDA=2`, finesse de Startwave.
- [`src/hooks.asm`](https://github.com/brandon-tallent/microwave-xt-extended-firmware/blob/fc02c58ded5ef2f8e4f853a8e4530326787fd0a6/src/hooks.asm) : détournements d'adresses du firmware 2.33, insertion du traitement morph et effets sur le parcours OSC.
- [`src/stock_abi.inc`](https://github.com/brandon-tallent/microwave-xt-extended-firmware/blob/fc02c58ded5ef2f8e4f853a8e4530326787fd0a6/src/stock_abi.inc) : constantes et adresses identifiées du code stock. **Des noms d'adresses ne prouvent pas leur algorithme complet.**
- [`src/features/honda/honda.asm`](https://github.com/brandon-tallent/microwave-xt-extended-firmware/blob/fc02c58ded5ef2f8e4f853a8e4530326787fd0a6/src/features/honda/honda.asm) et [`honda_constants.inc`](https://github.com/brandon-tallent/microwave-xt-extended-firmware/blob/fc02c58ded5ef2f8e4f853a8e4530326787fd0a6/src/features/honda/honda_constants.inc) : traitement Aliasing Honda/Honda Raw, distinct du mode d'interpolation entre Waves.

### Fichiers Gearmulator/Xenia à consulter en priorité

- [`source/waldi/xt/xtLib/xtDSP.cpp`](https://github.com/dsp56300/gearmulator/blob/7f9a9806b7b3326379a39a2008c6dc92519191df/source/waldi/xt/xtLib/xtDSP.cpp) : émulation DSP et configuration du taux nominal de **40 kHz** ; ne dévoile pas toute la synthèse du firmware.
- [`xtWavePreview.cpp`](https://github.com/dsp56300/gearmulator/blob/7f9a9806b7b3326379a39a2008c6dc92519191df/source/waldi/xt/xtLib/xtWavePreview.cpp) : préparation des Waves et réduction 128+64+... ; commentaire reconnaissant ne pas connaître l'équivalence au matériel. **Ne pas utiliser comme oracle du DSP XT.**
- [`xtHardware.cpp`](https://github.com/dsp56300/gearmulator/blob/7f9a9806b7b3326379a39a2008c6dc92519191df/source/waldi/xt/xtLib/xtHardware.cpp), [`xtRomLoader.cpp`](https://github.com/dsp56300/gearmulator/blob/7f9a9806b7b3326379a39a2008c6dc92519191df/source/waldi/xt/xtLib/xtRomLoader.cpp) : interfaces matériels émulés et dépendance aux ROM privées.
- [`xtState.cpp`](https://github.com/dsp56300/gearmulator/blob/7f9a9806b7b3326379a39a2008c6dc92519191df/source/waldi/xt/xtLib/xtState.cpp), [`xtMidiTypes.h`](https://github.com/dsp56300/gearmulator/blob/7f9a9806b7b3326379a39a2008c6dc92519191df/source/waldi/xt/xtLib/xtMidiTypes.h) : formats SysEx/état et comparaisons M1 ; distinguer la commande de *preview* des dumps matériels.

## 2. Extraits et constatations du manuel fourni

| Pages du fichier PDF (numérotation 1-based) | Pages **imprimées** du manuel | Constat et prudence |
|---|---|---|
| 30 | 32 | Une Wavetable est une **table de pointeurs** ; quand des colonnes sont vides, des Waves intermédiaires sont calculées. |
| 31 | 33 | Deux oscillateurs sélectionnent des positions dans une table commune en firmware stock ; transitions timbrales modulables. L'extension Tallent peut changer ce partage. |
| 32 | 34 | Une Wave est un cycle ; la plupart des Waves sont conservées par demi-cycle, mais **des cycles complets sont également possibles**. Ne pas confondre cette capacité avec notre format de dump standard. |
| 33 | 35 | Positions 00 et 02 : 50/50 en 01 ; positions 02 et 05 : 2/3–1/3 en 03 et 1/3–2/3 en 04. Description de pondérations **d'amplitude** ; l'algorithme exact de génération et ses arrondis ne sont pas définis. |
| 45 | 46 | `Aliasing`, `TimeQuant`, `Accuracy`, `Clipping` sont des paramètres **distincts** ; l'interpolation/filtrage intra-Wave ne doit pas être assimilée à l'interpolation entre positions de table. |

*Remarque sur le document fourni :* la phrase « § 3.4 WDATA » figurait dans le texte accompagnant l'envoi, mais **n'est pas une référence localisée et vérifiée dans cet exemplaire du manuel utilisateur français**. Localiser le protocole technique WDATA séparé avant d'en faire une citation officielle. La phrase « interpolation spectrale » n'est pas une preuve de FFT ou d'interpolation spectrale à l'intérieur du DSP ; le manuel décrit ici des mélanges pondérés.

## 3. Quatre mécanismes différents — ne jamais les fusionner

| Niveau | Objet | Établi / à vérifier | Effet sur notre code |
|---|---|---|---|
| **Wave / transfert** | Demi-cycle de 64 valeurs 8 bits (et reconstruction à 128) dans le format de dump testé | **SOURCE DIRECTE + M1** pour ce format ; non-universalité de l'ensemble des Waves du XT étayée par le manuel | Codec M1/M2 conservé dans son périmètre. |
| **Construction sparse de table** | Calcul des formes aux positions **sans pointeur** | **SOURCE DIRECTE** (manuel, exemples de pondération), **DSP exact NON VÉRIFIÉ** | Jobs M2 à 61 positions explicites ; calcul sparse pas modélisé dans M3.6. |
| **Balayage de la table** | Mode stock 2.33 : positions entières ; Tallent E352/Honda : position fractionnaire | **SOURCE DIRECTE** pour bifurcation Tallent ; parité exacte de seuil/temps **NON VÉRIFIÉE** | `xt233-discrete-approx` = proxy ; `tallent-*-approx` = proxies. |
| **Lecture intra-Wave** | Interpolation de phase, réduction harmonique, aliasing, TimeQuant | **NON VÉRIFIÉ** précisément sur le stock ; Xenia peut servir d'oracle d'observation après vérification du firmware | Phase `linear` ou `nearest` est approximative ; `48000 Hz` est un paramètre de préécoute, `40000 Hz` le nominal dans Xenia. |

## 4. Mathématiques Waves : correct, MAIS pas « la formule officielle unique »

Pour le format **demi-cycle** couvert, le modèle de reconstruction est `W[64+n] = -W[63-n]` avec `n=0..63`. La symétrie en *entiers signés* exige un traitement particulier de **-128**, puisque `-(-128)` vaut +128 hors de l'intervalle int8 ; le code de round-trip M1 suit la convention **modulo 256**. Éviter `-128` dans une nouvelle synthèse musicale si une anti-symétrie entière stricte est recherchée.

La synthèse proposée `h[n] = Σ_k A_k sin(2πk(n+0.5)/128)` (première moitié, `n=0..63`) satisfait mathématiquement la réflexion antisymétrique pour tout harmonique `k` entier **si les deux demi-cycles sont reconstruits dans cette convention**. Cette équation est une **méthode possible**, pas une formule exclusive imposée par le manuel. Après normalisation/quantification ±127, l'écriture dans notre format SysEx inclut le codage en nibbles MIDI 7 bits, les en-têtes et le checksum ; les 64 octets d'exemple ne sont pas un paquet SysEx valide à eux seuls.

La conversion d'un **WAV arbitraire** peut perdre transitoires, contenu non périodique, phase et harmoniques. Le pipeline M2.4 projette vers sa représentation contrainte ; **aucune transparence sonore garantie**.

## 5. Conclusions pour les jalons et état scientifique

- **M1/M2 : conservés** pour format standard, prétraitement, projection et sécurité ; ne pas extrapoler le succès des tests à tout le format interne des ROM ou au DSP.
- **M3.1** : le défaut historique `table_interpolation=linear` est un **crossfade hypothétique**, non le mode stock 2.33. Maintenu pour préserver la reproductibilité des anciens jobs.
- **M3.2–M3.4** : A/B et batch restent comparables *dans le modèle utilisé* ; les métriques de cancellation à mi-crossfade sont **sans objet** pour le mode XT discret.
- **M3.5** : analyse RMS à phase alignée des sauts entre positions explicites ; ne prédit pas directement les clics audio et ne doit pas réorganiser les Waves sans accord humain.
- **M3.6** : profils explicitement nommés `legacy-linear-approx`, `xt233-discrete-approx`, `tallent-e352-approx`, `tallent-honda-approx`. Ce sont **des modèles**, non des captures ni des clones DSP.

### Questions ouvertes — conserver jusqu'à preuve expérimentale

1. Calcul exact et quantification des Waves intermédiaires pour tables *sparse* (et traitement des pointeurs particuliers / cycles complets).
2. Seuils de changement d'indice, contrôle de Startwave, position de Wave2, modulation, synchronisation et cadence de mise à jour sous OS 2.33.
3. Lecture intra-Wave exacte, tables de résolutions, limitation des harmoniques et interactions avec `Aliasing`, `TimeQuant`, `Accuracy`, `Clipping`.
4. Parité entre signaux rendus sous Xenia (ROM/version fixées), firmware Tallent 2.33 modifié et Microwave XT matériel ; clics au lancement de patchs.
5. Possibilités d'encodage/transfert des **cycles complets** non couvertes par le codec M1.
6. Vérification indépendante du protocole technique « WDATA § 3.4 » invoqué dans le texte transmis ; ne pas le considérer comme preuve localisée avant l'obtention de cette source.

## 6. Protocole de recherche pour M4 et les travaux futurs

1. Énoncer la question précise avant chaque expérience : `claim_id`, variante OS, réglages Sound, famille de Waves.
2. Lire **manuel + Tallent + Gearmulator**, consigner un chemin et **un commit exact par dépôt**, noter la portée de la source et toute contradiction.
3. Créer une hypothèse isolée **en la marquant comme telle** ; ne pas inventer des formules internes à partir de noms de fonctions.
4. Concevoir des cas synthétiques reproductibles : deux Waves identiques, opposées, changement de phase, table *sparse* et table à 61 références explicites, seuils de sélection, différentes hauteurs/`Aliasing`/`TimeQuant`.
5. Exécuter Xenia en lecture contrôlée, comparer PCM/FFT et rapports, consigner version de ROM et programme, paramètres et SHA des sorties **privées**.
6. Ne conclure à une compatibilité *hardware* qu'après une comparaison directe contrôlée si elle est nécessaire ; ne jamais envoyer un dump ni flasher le matériel par défaut.
7. Mettre à jour ce registre si une source ultérieure contredit une déduction précédente ; conserver la trace de la correction et les tests associés.

## 7. Confidentialité et traçabilité

- Le PDF utilisateur, les ROM, les binaires Waldorf, les SysEx privés et les WAV de test personnels **ne doivent pas entrer dans le dépôt ni dans ce ZIP**.
- Le SHA du manuel ci-dessus est un **identifiant de version documentaire**, pas une autorisation de redistribution.
- Une nouvelle conversation ne relit pas forcément automatiquement les anciens messages : fournir **le dépôt et ce registre** comme documents de référence pour reprendre le travail.
- Étendue de l'audit : revue **statique ciblée**, non démonstration d'exhaustivité ligne par ligne de toutes les versions des dépôts externes.
