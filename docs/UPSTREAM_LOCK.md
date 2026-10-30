# Références tierces verrouillées — état documentaire

Ces valeurs sont celles de l'audit fourni le 30 octobre 2026. **Ne pas substituer automatiquement les branches distantes actuelles.**

| Dépendance | Dépôt officiel | Révision documentée |
|---|---|---|
| Gearmulator / Xenia | https://github.com/dsp56300/gearmulator | `7f9a9806b7b3326379a39a2008c6dc92519191df` |
| Tallent Edition | https://github.com/brandon-tallent/microwave-xt-extended-firmware | `fc02c58ded5ef2f8e4f853a8e4530326787fd0a6` |

La référence Gearmulator a été confirmée dans `reports/upstream_inventory.json` et `reports/XT_STEP24_1_STATIC_AUDIT_*.json` fournis. Les deux clones sont situés sous `upstream/`, hors dépôt Git principal.

## Sources Gearmulator prioritaires

- [`xtTypes.h`](https://github.com/dsp56300/gearmulator/blob/7f9a9806b7b3326379a39a2008c6dc92519191df/source/waldi/xt/xtLib/xtTypes.h)
- [`xtMidiTypes.h`](https://github.com/dsp56300/gearmulator/blob/7f9a9806b7b3326379a39a2008c6dc92519191df/source/waldi/xt/xtLib/xtMidiTypes.h)
- [`xtState.cpp`](https://github.com/dsp56300/gearmulator/blob/7f9a9806b7b3326379a39a2008c6dc92519191df/source/waldi/xt/xtLib/xtState.cpp)
- [`xtWaveEditor.cpp`](https://github.com/dsp56300/gearmulator/blob/7f9a9806b7b3326379a39a2008c6dc92519191df/source/waldi/xt/xtJucePlugin/xtWaveEditor.cpp)
- [`xtRomLoader.cpp`](https://github.com/dsp56300/gearmulator/blob/7f9a9806b7b3326379a39a2008c6dc92519191df/source/waldi/xt/xtLib/xtRomLoader.cpp)
- [`xtWavePreview.cpp`](https://github.com/dsp56300/gearmulator/blob/7f9a9806b7b3326379a39a2008c6dc92519191df/source/waldi/xt/xtLib/xtWavePreview.cpp)

Ces liens permettent à la conversation de consulter le code source tiers public **sans le dupliquer dans `vx-ghst/XT-WAVETABLE-LAB`**. Préserver les avis de licence de chaque projet.
