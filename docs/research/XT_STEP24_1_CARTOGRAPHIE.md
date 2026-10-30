# XT-WAVETABLE-LAB — Étape 24.1 : cartographie statique du format wavetable

Date : 30 octobre 2026. État : **revue statique de code confirmée ; instrumentation et validation audio à faire**.
Dépôt examiné : `dsp56300/gearmulator`, commit `7f9a9806b7b3326379a39a2008c6dc92519191df`.
Git du laboratoire : `vx-ghst/XT-WAVETABLE-LAB`, `main`, `d5ed656c818d3c3af78a700690225ac7ff43f170`.

## Couche 1 — Structures de données

- `xtTypes.h` : `using WaveData = std::array<int8_t, 128>;` et `using TableData = std::array<WaveId, 64>;`.
- `xtMidiTypes.h` : 506 waves ROM numérotées 0–505 ; 250 waves utilisateur numérotées 1000–1249 ; 128 tables numérotées 0–127, tables utilisateur 96–127 ; 64 positions/table, positions 61–63 réservées aux formes fixes. Des tables algorithmiques ne sont pas des données téléchargeables ordinaires.
- Une wave 8 bits ne doit pas être confondue avec une table de 64 références. Les 250 waves sont une réserve **partagée** entre les 32 tables utilisateur.

## Couche 2 — SysEx (source xtState.cpp / xtState.h)

- `WaveDump = 0x12` : **137 octets** au total : en-tête de 7 octets, charge de 128 octets, checksum 1, `F7` 1.
- `WaveCtlDump = 0x13` : **265 octets** au total : en-tête de 7 octets, 256 octets de références, checksum 1, `F7` 1.
- En-tête de dump : `F0 3E 0E 7F CMD HH LL` ; la valeur ID `7F` est celle utilisée par l'encodeur Xenia. Les index `HH` / `LL` correspondent aux 7 bits haut/bas d'un ID.
- Chaque wave contient en pratique **64 valeurs 8 bits** en deux nibbles, les 64 valeurs restantes étant reconstruites : `w[127-i] = -w[i]` pour `i=0..63`. Les données transmises subissent un XOR avec `0x80` pour récupérer des valeurs signées.
- Chaque position de table code un identifiant de wave sur **4 nibbles** ; 64 × 4 = 256 octets.
- Le checksum est la somme des octets à partir de l'offset 7 jusqu'au checksum exclu, ramenée à 7 bits (`& 0x7F`).
- Les chemins `WaveDumpP=0x19` / `WaveCtlDumpP=0x1A` sont **spécifiques à l'émulateur** : ne jamais les présenter comme des commandes matérielles XT.
- Vérifications à imposer dans notre futur parseur : taille exacte, préfixe/suffixe, fabricant/modèle, commande, index autorisé, bytes MIDI 7 bits, nibble 0..15, checksum, troncature, doublons, références orphelines.
- Cas limite : `-128` ne dispose pas d'un opposé `+128` représentable en `int8_t` ; introduire un test numérique avant de choisir une politique d'arrondi/saturation.

## Couche 3 — Editor et format WAV

- `xtWaveEditor.cpp::importWaveFile` n'importe que **64 ou 128 échantillons** PCM **8 bits mono** par wave, avec symétrie exacte si 128. Ce n'est pas un convertisseur automatique d'un sample WAV de plusieurs secondes.
- `xtWaveEditor.cpp::exportAsWav(TableId)` fabrique par interpolation logicielle des cycles pour un **export de table** ; ne pas confondre cette interpolation d'édition avec le comportement DSP d'origine.
- `weData.cpp::sendWaveToDevice / sendTableToDevice` appelle respectivement `State::createWaveData` et `State::createTableData`.

## Couche 4 — ROM / firmware et DSP

- `xtRomLoader.cpp` : ROM complète 256 KiB ou deux moitiés 128 KiB réassemblées ; une mise à jour MIDI OS seule n'est pas suffisante pour fournir les wavetables ROM.
- `xtHardware.cpp` : émulation MCU + DSP ; échantillonnage hôte déclaré à 40 kHz.
- `xtWavePreview.cpp` : injection directe dans la RAM Y du DSP à base `0x20000`, 64 waves/part, 256 mots de mémoire par wave, avec plusieurs résolutions successives. **Le calcul des résolutions réduites est explicitement approximatif** (moyenne par paires ; commentaire auteur : méthode matérielle inconnue).
- `xtTestConsole.cpp` contient un *bloc commenté* d'extraction de la RAM Y du DSP, avec base `0x20000`, décalage de `0x4000`/part et `256` mots/wave. C'est une piste d'instrumentation, **pas un test déjà exécuté**.
- `xtRomWaves.cpp` : les emplacements 452–505 de l'**image ROM en mémoire de l'émulateur** sont modifiables. Ne pas en inférer une écriture ROM possible sur l'instrument physique.
- Le cœur du comportement de synthèse est exécuté dans le firmware/DSP binaire, et n'est pas entièrement exprimé en C++ de Xenia.

## Décisions pour le convertisseur

1. Format d'échange canonique : **Waldorf standard**, indépendamment du profil de préécoute.
2. Deux profils de rendu : OS 2.33 (*premier*) ; Tallent Edition (*ultérieur*, uniquement après validation de chargement dans Xenia).
3. Écrire un parseur/validateur **strict** ; ne pas utiliser directement des `parse*` Xenia comme preuves de validité complète (ils ne vérifient pas systématiquement les checksums).
4. Gérer le budget global de 250 waves, les références partagées, la sélection des emplacements et l'analyse non destructive des dumps.
5. Ne pas envoyer de MIDI/SysEx au synthétiseur physique ; aucun flash ; aucun push de ROM, `.syx` ou audio privé.

## Étape 24.2 proposée — à valider localement

- Audit statique historique : les scripts `XT_STEP24_1_AUDIT.ps1` et `XT_STEP24_1_AUDIT_V12.ps1` ne sont pas fournis dans le depot actuel. Le rapport existant reste conserve localement dans `reports/`. Ne pas declarer ce controle reproductible avant restauration et validation du script.
- Inspecter le JSON ; seules les sources sont lues ; aucune ROM ou donnée privée n'est ouverte.
- Après les contrôles PASS, développer des tests de **round-trip** sans accès matériel : `wave -> sysex -> wave`, `table -> sysex -> table`, y compris données corrompues et valeurs extrêmes ; **aucun rendu audio** à ce jalon.

## Références de code, revision immuable

- [xtTypes.h](https://github.com/dsp56300/gearmulator/blob/7f9a9806b7b3326379a39a2008c6dc92519191df/source/waldi/xt/xtLib/xtTypes.h#L20-L24)
- [xtMidiTypes.h](https://github.com/dsp56300/gearmulator/blob/7f9a9806b7b3326379a39a2008c6dc92519191df/source/waldi/xt/xtLib/xtMidiTypes.h#L211-L277)
- [xtState.cpp](https://github.com/dsp56300/gearmulator/blob/7f9a9806b7b3326379a39a2008c6dc92519191df/source/waldi/xt/xtLib/xtState.cpp#L975-L1196)
- [xtState.h](https://github.com/dsp56300/gearmulator/blob/7f9a9806b7b3326379a39a2008c6dc92519191df/source/waldi/xt/xtLib/xtState.h#L60-L74)
- [xtWaveEditor.cpp](https://github.com/dsp56300/gearmulator/blob/7f9a9806b7b3326379a39a2008c6dc92519191df/source/waldi/xt/xtJucePlugin/xtWaveEditor.cpp#L731-L806)
- [weData.cpp](https://github.com/dsp56300/gearmulator/blob/7f9a9806b7b3326379a39a2008c6dc92519191df/source/waldi/xt/xtJucePlugin/weData.cpp#L229-L250)
- [xtRomLoader.cpp](https://github.com/dsp56300/gearmulator/blob/7f9a9806b7b3326379a39a2008c6dc92519191df/source/waldi/xt/xtLib/xtRomLoader.cpp#L15-L113)
- [xtRomWaves.cpp](https://github.com/dsp56300/gearmulator/blob/7f9a9806b7b3326379a39a2008c6dc92519191df/source/waldi/xt/xtLib/xtRomWaves.cpp#L9-L90)
- [xtWavePreview.cpp](https://github.com/dsp56300/gearmulator/blob/7f9a9806b7b3326379a39a2008c6dc92519191df/source/waldi/xt/xtLib/xtWavePreview.cpp#L8-L82)
- [xtTestConsole.cpp](https://github.com/dsp56300/gearmulator/blob/7f9a9806b7b3326379a39a2008c6dc92519191df/source/waldi/xt/xtTestConsole/xtTestConsole.cpp#L93-L122)
- [xtState.cpp — refresh table](https://github.com/dsp56300/gearmulator/blob/7f9a9806b7b3326379a39a2008c6dc92519191df/source/waldi/xt/xtLib/xtState.cpp#L805-L894)

Cet audit est **une carte statique du code et des formats**. L'implémentation et le comportement dynamique des algorithmes DSP restent à caractériser avant toute affirmation de fidélité sonore exacte.
