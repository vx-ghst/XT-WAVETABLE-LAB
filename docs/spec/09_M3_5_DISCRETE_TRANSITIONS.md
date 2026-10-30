# M3.5 — Planification optionnelle des transitions **discrètes** XT 2.33

## Emploi

M3.5 s'insère **en lecture seule après** `select_wave_plan()` M2.5, **avant** tout export M2.6, et n'écrit pas sur disque. Le modèle traite les **60 frontières des 61 positions utilisateurs** et exclut les positions 61, 62, 63 réservées. Il ne faut pas le confondre avec le crossfade linéaire par défaut de M3.1.

```python
from xtwavetable.optimizer.stock_transitions import analyze_stock_transitions

# 'plan' est un WaveSelection déjà construit par select_wave_plan(...).
report = analyze_stock_transitions(plan)  # audit seulement, ordre conservé
optional = analyze_stock_transitions(plan, allow_reordering=True, max_passes=12)
print(optional.numerically_improved, optional.chronology_changed)
print(optional.source_total_aligned_rms, optional.proposal_total_aligned_rms)
# optional.report_json : JSON canonique en mémoire, aucune écriture automatique.
# optional.proposed_order est une permutation d'indices dans plan.selected.
# Aucun export n'utilise automatiquement optional.proposed_position_indices.
```

**Ne pas activer le réordonnancement par défaut.** Le 2-opt fixe le tout premier et le dernier candidat et propose des inversions de séquences intermédiaires si, et seulement si, le total des RMS « Wave au même angle de phase » diminue. Les Waves originales et les durées de maintien de chaque position restent inchangées, **mais la chronologie artistique des timbres peut être modifiée**. Les métriques ne sont pas des probabilités de clics ni des jugements d'écoute.

### Convention de distance

Pour les 128 points de chaque Wave canonique : `RMS(A-B)/128`, borne de 0 à 1,9921875 ; le `peak` correspond à `max(|A-B|)/128`. Cela représente l'écart **à phase identique** lors d'une sélection brutale. Le résultat dépend du contenu brut des Waves, pas du pitch, du filtre, de l'aliasing ou du DSP ; il ne reproduit pas une forme d'onde XT enregistrée.

### Sécurité et tests

- Rentrées : `WaveSelection` M2.5, 1 à 61 Waves, mapping non décroissant sur 61 positions, chaque index utilisé.
- Aucune édition de `plan`, des Wave, des fichiers sources, du firmware, des dumps et aucun transfert SysEx/MIDI.
- `allow_reordering=False` par défaut ; aucune « nouvelle wavetable » n'est matérialisée sur disque ; références 61–63 non lues/modifiées.
- Empreintes SHA-256 des demi-Waves dans le rapport, sans chemins privés ni audio personnel.
- 23 tests nouveaux pour monotonie du coût, déterminisme, garde-fous, inversion opt-in, tableaux 1/2/3/61 Waves, contrôle des bornes, absence de crossfade implicite.

**État :** tests de la suite complète sur un environnement isolé : `Ran 426 tests`, `OK`. La certification Windows et la publication GitHub restent séparées et nécessitent les logs utilisateur.

Pour les preuves détaillées Tallent/Gearmulator et les correctifs M3.1–3.4 à planifier, lire [`08_M3_5_SOURCE_AUDIT.md`](08_M3_5_SOURCE_AUDIT.md).
