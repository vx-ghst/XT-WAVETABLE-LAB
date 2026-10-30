# Politique de publication

Le dépôt est public. Avant chaque `git add` ou `git push` :

1. Publier seulement `src/`, `tests/`, `scripts/`, `docs/` et les fichiers de configuration **relus**.
2. Conserver tous les dumps SysEx, ROM/firmware, samples et captures matérielles dans `private/`.
3. Ne pas publier `reports/`, `runs/`, `build/`, `test-plugins/`, `.git/`, ni le clone `upstream/`.
4. Vérifier qu'un script documente des chemins relatifs et qu'il ne contient ni données utilisateur ni secret.
5. Contrôler `git diff --cached --name-only` et `git diff --cached` AVANT de committer.
6. Les hashes de fichiers privés ne sont pas leurs contenus, mais leurs noms et métadonnées peuvent fournir des informations : les rapports personnels restent privés.
7. Ne jamais supposer qu'un `.gitignore` suffit à retirer un fichier déjà suivi : `git add -f` peut le contourner. Si une donnée sensible est commitée, interrompre la publication et gérer l'historique avant de pousser.

Les configurations VS Code de cette machine contiennent des chemins absolus `D:\DEV\...` et `C:\ProgramData\Ableton\...`. Elles sont conservées localement ; une version d'exemple portable pourra être publiée ultérieurement.
