# Rapport de recette — RiskIQ Intelligence 0.1.0

Date : 10 octobre 2026. Périmètre : **nouveau dépôt de référence**, pas l’application Next.js/FastAPI auditée par Claude. Données : synthétiques uniquement.

## Résultats effectivement obtenus

**71 tests pytest réussis** dans l’environnement local de livraison. Sorties brutes : `qa/pytest.txt` et `qa/junit.xml`. Python 3.13.5 ; dépendances directement requises figées dans `pyproject.toml`. Les versions exactes de l’environnement et le contrôle de packaging sont conservés dans `qa/`.

Domaines testés : cohérence nombre/charge/exposition, CSV français et défauts de grain, transformations réelles, séparation train/validation/test, sévérité pondérée par nombre, parité du scorer JSON, noms avec `_`, variables entières, modalités inconnues et manquantes, scénario inchangé, normalisation de l’optimiseur, contraintes, Gini avec ex aequo, PSI hors plage, HT/taxe/TTC, sessions/CSRF/Origin/Host, droits et isolation entre tenants, idempotence/reprise/annulation, refus d’auto-approbation, publication interne/quote/retrait, observations et revue liée, chaîne d’audit, rotation des mots de passe/révocation, sauvegarde/restauration, contrats de connecteurs.

**Packaging vérifié :** roue Python construite, installée dans un répertoire temporaire sans téléchargement de dépendances, ressources statiques présentes, candidat headless généré sur 5 000 polices et scoring de ces 5 000 lignes avec `python -S` (bibliothèque standard seule). Les bibliothèques scientifiques déjà installées servent à l’entraînement, pas au scorer exporté. Preuves : `qa/package-build.txt` et `qa/package-results.json`.

Les commandes `node --check riskiq/static/app.js` et `python -m compileall -q riskiq scripts examples` ont réussi. Ce frontend est JavaScript et n’utilise pas TypeScript ; ces contrôles ne corrigent pas le frontend historique.

## Parcours d’interface réellement exécuté

Chromium avec Playwright, application et API Python réelles, base temporaire : connexion ; génération de 5 000 polices synthétiques ; exécution des six étapes de revue ; approbation avec un autre compte ; publication dans l’API de cotation interne ; devis calculé ; nouvel instantané d’observation ; A/E et dérive ; deuxième revue reliée à la première ; copilot déterministe ; écran audit et utilisateurs. Aucune erreur JavaScript `pageerror` observée. Résultat structuré : `qa/browser-results.json`, captures : `qa/screenshots/`.

**Limite importante de la recette navigateur :** le navigateur de l’environnement de livraison ne peut pas joindre directement le serveur local. La recette a utilisé un pont Python vers le vrai serveur HTTP, avec de vraies réponses API, sessions, calculs et artefacts. Le HTML/CSS/JavaScript de l’interface a été chargé par le harness. Ce n’est donc pas une preuve du transport navigateur direct, de l’application effective de la CSP, de TLS ou du comportement réel des cookies dans un hébergement public. La CI fournie exécute le même parcours **sans ce pont**, mais elle n’a pas encore été lancée dans le GitHub du propriétaire.

## Connecteurs

Databricks, Snowflake, Foundry : réponses HTTP de contrats simulées (polling, pagination, refus, troncature). BigQuery : SDK simulé. PostgreSQL : validation des paramètres, pas de serveur source réel. Ces tests contrôlent le comportement de notre adaptateur ; **ils ne prouvent pas la connexion à un compte cloud, ni les droits, ni la compatibilité de tous les types métier**. La déclaration UI `configured_not_live_verified` est volontaire.

## Non exécuté / non démontré

Construction et lancement Docker (Docker indisponible ici) ; installation Windows native ; tests GitHub Actions du propriétaire ; serveur PostgreSQL réel ; appels BigQuery/Databricks/Snowflake/Foundry réels ; fournisseur LLM réel ; pentest/SAST/DAST/SCA en réseau ; test de charge multi-utilisateur ; disponibilité/PRA en infrastructure réelle ; données de portefeuille client ; exécution distribuée/native marketplace ; validation réglementaire/fiscale ; parité fonctionnelle avec toutes les fonctions de l’ancien studio.

Un audit de dépendances réseau est fourni dans la CI mais n’a pas été exécuté ici. Les versions installées ne sont pas qualifiées de « sans vulnérabilité » sur la seule base de tests fonctionnels.

## Rejouer

```bash
pip install '.[test]'
OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 python -m pytest --junitxml=qa/junit.xml
node --check riskiq/static/app.js
python -m playwright install chromium
python scripts/browser_smoke.py
```

Sous PowerShell, définir séparément `$env:OPENBLAS_NUM_THREADS='1'` et `$env:OMP_NUM_THREADS='1'`. Le dernier test doit réussir en HTTP direct sur le poste/CI cible. Le mode `RISKIQ_QA_BRIDGE=1` est réservé à ce harness contraint et ne doit pas servir à masquer un échec réseau en production.

## Interprétation

Les tests prouvent les comportements précis couverts par les fixtures. Ils ne prouvent ni une supériorité marché, ni l’absence de défaut, ni l’exactitude statistique universelle. Les seuils de calibration, l’élasticité hypothétique et les limites de variation doivent être validés sur le portefeuille et l’usage retenus.
