# Commencer ici — RiskIQ Intelligence 0.1.0

## Ce que contient cette archive

Un **nouveau dépôt autonome exécutable**, avec une interface web, un moteur actuariel Python, une boucle persistante de six agents métier outillés, une validation par un autre compte, une cotation interne versionnée et un suivi lié. Il ne remplace pas encore toutes les fonctions de ton application d’origine, dont les répertoires sources complets n’ont pas été fournis.

Périmètre opérationnel : **une garantie sélectionnée et le renouvellement**, sur des jeux bornés. Le LLM est facultatif et en lecture seule ; l’orchestrateur et les calculs sont déterministes. Les adaptateurs data sont codés mais doivent être testés avec tes comptes réels. Aucune production publique n’a été déployée.

## Lancer sur ton ordinateur

Extraire l’archive ; ouvrir PowerShell **dans le dossier contenant `docker-compose.yml`**. Démarrer Docker Desktop. Avec Python installé :

```powershell
py scripts/configure.py
docker compose up --build -d
```

Sans Python hôte, le script PowerShell équivalent est `./scripts/configure.ps1`, à exécuter uniquement si autorisé par la politique de ton poste ; ne pas contourner cette politique. L’image Docker doit encore être construite et recettée sur ton environnement.

Ouvrir `http://127.0.0.1:8080`. L’espace est `demo`. Le fichier `.local-credentials.txt`, généré sur ton ordinateur, contient les deux comptes. **Ne jamais le partager ou le commiter.**

Une alternative Python sans Docker est décrite dans `README.md` ; c’est le moteur Python qui a été exécuté pendant la recette fournie.

## Démontrer la boucle

Données → générer 5 000 polices synthétiques → lancer une revue → attendre les six étapes → se connecter avec le compte approbateur → approuver → revenir au compte administrateur → publier en interne → tester un devis → Suivi & feedback → créer de nouvelles observations synthétiques → mesurer → lancer une revue liée.

## Déposer dans GitHub

Créer un **nouveau dépôt privé vide**, sans README initial. Depuis le dossier décompressé :

```powershell
git init -b main
git add .
git status
```

Vérifier l’absence de `.env`, `.local-credentials.txt`, `sources.local.json`, `var/`, clés et données réelles dans les fichiers ajoutés, puis :

```powershell
git commit -m "Initial RiskIQ Intelligence reference release"
git remote add origin https://github.com/TON-COMPTE/riskiq-intelligence.git
git push -u origin main
```

Remplacer `TON-COMPTE`. Voir `docs/INSTALLATION_GITHUB.md` pour l’authentification Git, la CI et les instructions détaillées. **GitHub Pages n’exécute pas cette application Python** : GitHub conserve le code, l’hébergement de l’application est un sujet distinct.

## Documents importants

- `docs/ARCHITECTURE.md` : séparation noyau/agents/plateformes.
- `docs/AUDIT_TRACEABILITY.md` : lien avec les constats de Claude, sans fausse déclaration de correction de l’ancien code.
- `docs/INTEGRATION_PLATFORMS.md` : connecteurs, secrets, limites et recette réelle.
- `docs/QA_REPORT.md` et `qa/` : preuves, 71 tests réussis, packaging, captures et limites du test navigateur.
- `docs/SECURITY_AND_OPERATIONS.md` : utilisateurs, sauvegarde, restauration et limites avant exposition.
- `docs/ROADMAP.md` : étapes restant à réaliser pour la vision complète.
