# État vérifié du laboratoire — 2026-10-30

## Confirmé dans les journaux transmis

- Git principal : `vx-ghst/XT-WAVETABLE-LAB`, dépôt public, branche `main`, commit initial `d5ed656`.
- Gearmulator : checkout sur `7f9a9806b7b3`, build Release et Debug Xenia VST3 Windows x64 réussis.
- Xenia Release et Debug chargés dans Ableton Live 12 et signaux audio observés.
- Profil de debug C++ `cppvsdbg`, breakpoints et inspection de `xtDevice.cpp::sendLeds` réussis.
- Audit statique étape 24.1 : JSON fourni annonce 19 contrôles PASS / 19 (lecture des sources uniquement).
- Script de comparaison de deux dumps SysEx revalidé hors ligne avec données privées : 667 messages/dump, 64 changements, 603 messages identiques. **Aucun test sur le matériel physique.**

## Non confirmé ou non disponible

- Aucun moteur propre WAV -> wavetable n'apparaît dans le ZIP fourni ; `project/` est vide dans cette archive.
- Aucune implémentation publique de codec XT ni suite de tests unitaires détectée.
- `XT_STEP24_1_AUDIT_V12.ps1`, cité dans la documentation historique, est absent du ZIP fourni : préserver l'audit JSON, mais signaler l'absence de son script reproductible dans l'archive.
- Aucune certification sonore Xenia vs matériel physique.
- Fonctionnement de Tallent Edition dans l'émulateur non démontré ici.
- Licence du code original non choisie.

## Étape suivante

**M1 : modèles Wave/Table + codec SysEx standard XT + validations strictes + tests round-trip avec fixtures entièrement synthétiques.** Ne pas commencer l'intégration hardware ni le flash.
