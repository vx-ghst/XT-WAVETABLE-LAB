# XT-WAVETABLE-LAB — M3.5 : audit des hypothèses contre Tallent et Xenia

**Date du contrôle : 2026-10-30.** Ce document contrôle les affirmations scientifiques, **pas** la validité intégrale du comportement physique. Suite synthétique locale après ajout de M3.5 : **426 tests PASS**, aucun SKIP/FAIL. Résultat Windows à confirmer. Les 403 anciens tests PASS sur Windows restent un acquis fonctionnel mais ne prouvent pas la fidélité au DSP.

## Règle prioritaire de recherche (pour tous les prochains jalons)

Avant d'ajouter tout modèle/paramètre supposé « XT », **lire les portions concernées** de **(1) Tallent Extended Firmware** et **(2) Gearmulator/Xenia**, avec références aux fichiers et commit exact. Puis distinguer **PROUVÉ DANS LE CODE**, **INFÉRÉ**, **MODÈLE APPROXIMATIF**, **À TESTER PAR XENIA**, **À VÉRIFIER SUR MATÉRIEL**. Les deux dépôts sont des sources primaires de travaux indépendants, **pas** des spécifications officielles exhaustives de Waldorf. Les éventuelles images de firmware restent privées ; pas de ROM/binaire propriétaire dans Git ou les livrables.

### Références étudiées (révisions épinglées)

- Tallent, `fc02c58ded5ef2f8e4f853a8e4530326787fd0a6` : [`src/features/morph/morph.asm`](https://github.com/brandon-tallent/microwave-xt-extended-firmware/blob/fc02c58ded5ef2f8e4f853a8e4530326787fd0a6/src/features/morph/morph.asm), [`src/features/morph/morph_constants.inc`](https://github.com/brandon-tallent/microwave-xt-extended-firmware/blob/fc02c58ded5ef2f8e4f853a8e4530326787fd0a6/src/features/morph/morph_constants.inc), [`src/hooks.asm`](https://github.com/brandon-tallent/microwave-xt-extended-firmware/blob/fc02c58ded5ef2f8e4f853a8e4530326787fd0a6/src/hooks.asm), [`src/stock_abi.inc`](https://github.com/brandon-tallent/microwave-xt-extended-firmware/blob/fc02c58ded5ef2f8e4f853a8e4530326787fd0a6/src/stock_abi.inc) ; [manuel — interpolation](https://brandon-tallent.github.io/microwave-xt-extended-firmware/manual.html#interp).
- Gearmulator/Xenia, `7f9a9806b7b3326379a39a2008c6dc92519191df` : [`source/waldi/xt/xtLib/xtDSP.cpp`](https://github.com/dsp56300/gearmulator/blob/7f9a9806b7b3326379a39a2008c6dc92519191df/source/waldi/xt/xtLib/xtDSP.cpp), [`xtWavePreview.cpp`](https://github.com/dsp56300/gearmulator/blob/7f9a9806b7b3326379a39a2008c6dc92519191df/source/waldi/xt/xtLib/xtWavePreview.cpp), [`xtHardware.cpp`](https://github.com/dsp56300/gearmulator/blob/7f9a9806b7b3326379a39a2008c6dc92519191df/source/waldi/xt/xtLib/xtHardware.cpp), [`xtRomLoader.cpp`](https://github.com/dsp56300/gearmulator/blob/7f9a9806b7b3326379a39a2008c6dc92519191df/source/waldi/xt/xtLib/xtRomLoader.cpp).
- Les travaux M1 avaient déjà comparé le format de dump à `xtState.cpp` / `xtMidiTypes.h` de Gearmulator. Les deux dumps utilisateurs privés ont été validés en aller-retour au jalon M1 ; ils ne sont **pas** réutilisés pour ce jalon.

## Constats établis

1. **XT stock 2.33, axe TABLE : discrétisation.** Tallent `morph_wave1_index` utilise le chemin `morph_interp` « XT » et arrondit un indice ; `morph_edge_wave1` et `morph_edge_wave2` ont d'autres chemins pour les modes additionnels. Le manuel explicite le passage d'une Wave entière à l'autre. **NE PAS** appeler un crossfade linéaire « interpolation native XT 2.33 ».
2. **Tallent E352/Honda : nouvelles formes de mélange de positions fractionnaires** (`morph_wave1_position`, `morph_word_blend`) ; E352 interpole aussi dans la phase, Honda utilise des pas. L'implémentation exacte sur DSP ne peut pas être reconstituée de la seule partie 68k présentée.
3. **AXE PHASE / antialiasing : toujours non certifié.** Xenia exécute le firmware et les DSP émulés ; `xtDSP.cpp` définit un rendu autour de **40 000 échantillons/s**, mais le C++ périphérique ne contient pas la formule complète interne Waldorf. `xtWavePreview.cpp` prépare une pyramide 128+64+... et reconnaît explicitement utiliser une réduction simplifiée, sans savoir si elle reproduit celle du matériel. Ne pas présenter son moyennage par deux comme l'algorithme Waldorf vérifié.
4. **Quantification exacte du choix Wave : encore à mesurer.** Notre `math.floor(position + 0.5)` dans M3.1 `nearest` est une approximation plausible ; le firmware incorpore Startwave, indices internes, enveloppe, modulation, limites, temporisation et arrondis en arithmétique entière. Pas de parité au seuil 0,5 démontrée.
5. **L'aliasing dépend du pitch, de l'interpolation intra-Wave et des réglages Quality/Aliasing.** Tout résultat M3 à 48 kHz, sans filtre ni corrections, reste un outil mathématique de comparaison et **non** une référence audio hardware.

## Audit rétroactif par domaine (lecture statique des sources XT-WAVETABLE-LAB)

| Domaine | État | Justification / mesure corrective |
|---|---|---|
| M1 — Wave/Table codec SysEx, IDs, reserved 61..63, checksum, aller-retour | **CONSERVÉ, périmètre DATA** | Correspondances M1 validées avec code C++ et dumps. La découverte sur le rendu n'invalide pas l'encodage. Ne pas extrapoler la fidélité audio depuis les roundtrips. |
| M2.1 — décodeur WAV | **CONSERVÉ, méthode générique** | Opération WAV/RIFF indépendante de l'émulation XT. |
| M2.2 — prétraitement (canal, DC, normalisation) | **CONSERVÉ, transformation choisie** | Prétraitement logiciel explicite ; pas l'algorithme du XT. |
| M2.3 — analyse f0/spectre | **CONSERVÉ, heuristique** | Estimation hors firmware ; les résultats ne certifient pas la reconstruction timbrale. |
| M2.4 — extraction d'un cycle et projection antisymétrique | **CONSERVÉ, perte signalée** | Projection contrainte par la Wave transmise ; recherche de phase/échantillonnage ne prétend pas copier le DSP. Vérifier perceptuellement les pertes plus tard. |
| M2.5 — uniform/diversity, mapping chronologique 61 positions | **CONSERVÉ, politique artistique à revoir en M3.5** | La diversité temporelle ne garantit pas la douceur des **sauts discrets** XT ; le nouveau diagnostic mesure ces sauts. |
| M2.6 — sauvegarde, autorisations et SysEx | **CONSERVÉ, sécurité** | Écrit sur disque sous autorisation, aucun transfert matériel. Vérification des slots et du dump préalable indépendante de l'interpolation. |
| M2.7 — pipeline, M2.8 — CLI et vérification | **CONSERVÉS, fonctionnels** | Pas de préécoute intégrée au processus de conversion, pas de promesse de parité XT. |
| M3.1 — oscillator crossfade, `table_interpolation='linear'` par défaut | **À RECARDER — ÉCART MAJEUR de profil** | Bonne approximation *alternative*, mais NON STOCK 2.33. `nearest` se rapproche de la sélection entière, sans certifier les seuils ni le DSP. **Ne pas changer silencieusement les defaults existants** ; futur correctif CLI devra exiger/afficher un `render_profile` explicite. |
| M3.1 — `phase_interpolation='linear'` | **NON CALIBRÉ** | Même avec table `nearest`, phase et antialiasing hardware ne sont pas reproduits. 48 kHz par défaut au lieu de 40 kHz internes sous Xenia. |
| M3.2 — transitions RMS entre deux Waves | **CONSERVÉ, PROXY** | Différence à phase alignée, utile pour un saut discret mais non équivalente à un clic réellement entendu. |
| M3.2 — `crossfade_midpoint_rms_ratio` | **À RECARDER — PROFIL CROSSFADE UNIQUEMENT** | Ne représente pas un événement existant lors du saut **XT stock**. Ne pas l'utiliser pour classer les transitions du 2.33. |
| M3.3 — CLI AB, M3.4 — CLI batch | **FONCTIONNEL MAIS DEFAULTS À EXPLICITER** | Héritent du moteur M3.1 et du `linear` par défaut ; résultats de M3.3/4 comparables *dans* ce modèle, pas à la référence XT stock. Prochaine évolution : profil explicite + métadonnées de preuve. |
| M3.5 — `stock_transitions.py` | **NOUVEAU, SOURCE-DERIVED SUR AXE TABLE UNIQUEMENT** | Analyse des sauts entre Waves à phase alignée. Réordonnancement 2-opt strictement opt-in, indices extrêmes préservés, source et SysEx intacts. Classement musical inexistant. |

## Écarts prioritaires et critères de fermeture

- **P0 — empêcher une confusion de profils** : M3.5 emploie `XT233_DISCRETE_POSITION_SWITCH_APPROX_PHASE_UNVERIFIED`. M3.1–3.4 restent `APPROX` et explicitement non stock lorsqu'en mode `linear`. À corriger dans les prochains points d'entrée CLI/documentation : nom de profil obligatoire, et test anti-régression ciblé.
- **P1 — calibration XT stock sous Xenia** : mêmes Waves, Sound neutralisé (sans FX, filtre si possible neutralisé), paramètres de modulation contrôlés, balayage lent des 61 positions ; comparaisons PCM/FFT et trajectoires d'indices aux seuils. Version firmware du rendu vérifiée. Ne rien générer en transgressant la licence Waldorf.
- **P1 — phase et décimation** : comparer plusieurs pitchs et Quality/Aliasing. `xtWavePreview.cpp` n'est pas l'oracle hardware.
- **P1 — validation du reordonnancement** : l'algorithme M3.5 ne peut réduire qu'une métrique de coût numérique, **au prix possible de l'intention timbrale dans l'ordre original**. Un responsable humain doit écouter et approuver avant toute modification réelle.
- **P2 — Tallent Edition** : ajouter séparément les profils E352 et Honda après tests ; il faut différencier interpolation entre les 61 positions et lecture de chacun des 128 échantillons.

## Ce que cet audit ne certifie pas

Ni le rendu « identique au XT », ni les transitoires réels, ni les clics de patchs au démarrage, ni le spectre antialiasé, ni l'équivalence du firmware modifié. Aucun de ces points ne sera déclaré PASS sans référence reproduisible et trace Xenia/matériel. Cette revue est **statique et différentielle**, pas un contrôle formel exhaustif de chaque ligne de code C++ ou assembleur des dépôts tiers.
