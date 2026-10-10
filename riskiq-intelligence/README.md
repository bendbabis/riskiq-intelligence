# RiskIQ Intelligence Studio

**Version 0.1.0 — nouveau dépôt exécutable pour un pilote privé.**

Une boucle d’intelligence tarifaire gouvernée, sans dépendance obligatoire à Databricks, Snowflake, Palantir, GCP ou à un LLM. Le moteur de calcul est séparé de l’interface, du stockage et des adaptateurs.

> Ce dépôt ne remplace pas à périmètre égal l’ancien RiskIQ Studio : les sources complètes de son backend/frontend n’ont pas été fournies. Il s’agit d’une nouvelle implémentation ciblée, construite à partir des exigences et du rapport « Audit RiskIQ Studio », daté du 10 octobre 2026. **Ne pas fusionner aveuglément ce dépôt avec le projet existant.**

## Ce qui fonctionne dans cette version

Connexion locale, quatre rôles, isolation logique par tenant, création/suspension de membres, sessions serveur, protection CSRF, limites de connexion et d’import. Import CSV français avec séparateur/décimale/encodage explicites, instantanés persistés, filtres structurés et renommages réels.

Six agents métier **déterministes et outillés**, coordonnés par un workflow SQL persistant : contrôle qualité, diagnostic, modèles Poisson × Gamma et Tweedie, contrôles sur échantillon test réservé, optimisation de renouvellement, constitution d’un dossier de décision. Reprise après incident par bail et points de contrôle ; chaque étape et ses artefacts sont enregistrés atomiquement.

Approbation par un compte différent de l’auteur, publication dans une API interne de cotation sandbox, devis réel, retrait d’une version, export JSON avec scorer Python portable, suivi A/E monétaire et dérive sur un nouvel instantané, ouverture d’une revue de feedback liée à la précédente. L’assistant explique les preuves ; son option LLM est désactivée par défaut et ne publie jamais de prix.

## Périmètre à ne pas confondre avec un produit enterprise complet

Une garantie sélectionnée par revue, tarification de renouvellement avec prime précédente HT. Régularisation **L2 seulement**, pas de lasso ni arbres. Pas de moteur réglementaire français validé, pas de taxes légales embarquées, pas d’IBNR automatique ni d’estimation causale de l’élasticité. L’orchestration n’est pas un système multi-LLM autonome. Les adaptateurs cloud sont implémentés mais **non recettés sur des comptes réels** ; ils font des extractions bornées, pas un entraînement distribué natif ou un accès zéro copie.

Maximum par import : **100 000 lignes, 150 colonnes, 15 MiB**, et 20 variables de modélisation. SQLite est destiné à une installation locale mono-instance ; PostgreSQL est prévu par SQLAlchemy mais doit être recetté en environnement cible. L’application n’est pas certifiée et ne doit pas être exposée à des données de clients réels sur Internet sans revue de sécurité et actuarielle indépendante.

## Démarrage local — Windows, avec Docker Desktop

Prérequis : Docker Desktop démarré et Python disponible pour générer les secrets (ou utiliser `scripts/configure.ps1`, après revue et selon la politique de votre poste).

Depuis le dossier contenant ce README :

```powershell
py scripts/configure.py
docker compose up --build -d
```

Ouvrir **http://127.0.0.1:8080**. Lire les identifiants dans `.local-credentials.txt` : espace `demo`, compte `admin@riskiq.local`, compte `approver@riskiq.local`. Les deux mots de passe sont **générés sur votre poste**, aucun mot de passe opérationnel n’est livré dans l’archive.

```powershell
docker compose logs --tail=100 app
docker compose stop
# Redémarrer sans perdre les données
docker compose up -d
```

**Ne pas utiliser `docker compose down -v` : cela supprimerait le volume de données.** Les mises à jour du code exigent une sauvegarde et une reconstruction de l’image ; ne jamais supprimer le volume pour une simple mise à jour.

## Alternative sans Docker — Python

Python **3.11 à 3.13** est déclaré compatible. Les tests livrés ont été exécutés sous **Python 3.13.5 / Linux** ; Windows, Docker et Python 3.11 doivent être validés sur votre poste/CI.

```powershell
py -3.13 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[test]"
.\.venv\Scripts\python.exe scripts/configure.py
.\.venv\Scripts\python.exe -m riskiq.cli serve
```

macOS / Linux :

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -e '.[test]'
.venv/bin/python scripts/configure.py
.venv/bin/python -m riskiq.cli serve
```

Les dépendances sont téléchargées à l’installation. Une fois installée, la boucle autonome s’exécute sans Internet. Une installation entièrement hors ligne nécessite un miroir de paquets ou une image préconstruite ; il n’est pas fourni.

## Première démonstration

1. Avec le compte administrateur : **Données → Données synthétiques → Générer**, puis **Lancer une revue**. Les paramètres par défaut sont adaptés au jeu synthétique.
2. Suivre **Boucle intelligente** jusqu’à « À valider ». Examiner le test réservé, la calibration, les hypothèses et le scénario. Se déconnecter.
3. Avec le compte approbateur : ouvrir la même revue, **Examiner et approuver**, écrire un motif. Se déconnecter.
4. Revenir avec l’administrateur : **Publier en interne**, puis **Déploiements → Tester un devis**.
5. Dans **Suivi & feedback**, générer les observations synthétiques, les sélectionner, confirmer leur maturité pour la démonstration et mesurer. **Ouvrir une revue liée** referme la boucle.

Deux comptes ne garantissent pas deux personnes : en utilisation réelle, attribuer les comptes à des personnes distinctes et contrôler leur identité.

## Ajouter le dépôt à GitHub

Voir **[INSTALLATION_GITHUB.md](docs/INSTALLATION_GITHUB.md)**. Créer de préférence un nouveau dépôt **privé** ; ne pas écraser l’ancien projet.

```bash
git init -b main
git add .
git status
git commit -m "Initial RiskIQ Intelligence reference release"
git remote add origin https://github.com/TON-COMPTE/riskiq-intelligence.git
git push -u origin main
```

Remplacer `TON-COMPTE`, créer le dépôt distant vide et s’authentifier auprès de GitHub auparavant. Vérifier que `.env`, `.local-credentials.txt`, `var/`, les clés et les portefeuilles ne figurent pas dans les fichiers ajoutés. **GitHub Pages ne peut pas exécuter ce backend Python** : GitHub héberge le code, l’application nécessite un serveur.

## Tests et preuves

```bash
python -m pytest
node --check riskiq/static/app.js
python -m playwright install chromium
python scripts/browser_smoke.py
```

Voir **[QA_REPORT.md](docs/QA_REPORT.md)** pour le périmètre exact et les limites de transport de la recette réalisée ici. `qa/pytest.txt`, `qa/junit.xml` et `qa/browser-results.json` sont des résultats effectivement obtenus, pas des statuts saisis manuellement.

Les workflows GitHub Actions fournis lancent les tests, un contrôle de syntaxe JavaScript, une recette navigateur et un audit de dépendances. Un workflow manuel distinct peut construire/publier une image dans GHCR ; il ne déploie pas un site Internet.

## Documentation

- [Architecture et boucle](docs/ARCHITECTURE.md)
- [Intégration aux plateformes](docs/INTEGRATION_PLATFORMS.md)
- [Installation et GitHub](docs/INSTALLATION_GITHUB.md)
- [Correspondance avec l’audit Claude](docs/AUDIT_TRACEABILITY.md)
- [Sécurité, administration, sauvegarde](docs/SECURITY_AND_OPERATIONS.md)
- [Recette et limites](docs/QA_REPORT.md)
- [Feuille de route enterprise](docs/ROADMAP.md)

Le logo est celui fourni par le propriétaire. Les droits de redistribution et la licence commerciale du produit doivent être définis par le propriétaire avant diffusion. Aucune licence open source n’est attribuée à sa marque.
