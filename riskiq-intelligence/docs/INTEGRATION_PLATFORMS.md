# Intégration simple, sans dépendance imposée

## Ce qui est livré et ce qui ne l’est pas

| Cible | Adaptateur livré | Preuve locale | Ce qu’il reste à recetter |
|---|---|---|---|
| Autonome | CSV, SQLite, moteur Python, API | Tests fonctionnels/API et parcours d’interface | Windows, image Docker, postes du client |
| Databricks | SQL Statement Execution API, lecture bornée, polling et chunks | Contrats HTTP simulés, succès/échec/troncature | OAuth/service principal, warehouse, Unity Catalog, réseau, types, consommation |
| Snowflake | SQL API, polling et partitions, token OAuth référencé serveur | Contrats HTTP simulés | Authentification réelle, rôles, warehouse, types, quotas |
| Palantir | Foundry API v2 `readTable`, CSV | Contrat HTTP simulé | RID, branche, droits/markings, snapshots et limites du tenant |
| GCP / BigQuery | SDK BigQuery, ADC, plafond de bytes facturés | Contrat SDK simulé | Workload identity, projet, dataset, localisation, quotas |
| PostgreSQL source | Transaction `READ ONLY`, table autorisée, timeout | Validation des identifiants, non testée sur serveur réel | Driver, droits SQL, TLS et réseau |
| PostgreSQL métadonnées | SQLAlchemy, même modèle de persistance | Code fourni, pas de serveur PostgreSQL disponible ici | Transactions concurrentes, sauvegarde, migrations et restauration |

**Ces adaptateurs ne sont pas des maquettes d’interface** : ils effectuent de vraies requêtes quand ils sont configurés. Mais les tests avec réponses simulées ne prouvent ni la connexion ni la conformité à toutes les variantes des comptes clients. L’interface ne les affiche pas comme « connectés » sans lecture réelle.

## Configuration opérateur unique

Copier `examples/sources.example.json` vers **sources.local.json**. Ce fichier n’est pas destiné à Git. Chaque source contient : fournisseur, tenant autorisé, tables explicitement autorisées, paramètres non secrets et **nom de variable d’environnement** contenant le credential.

```dotenv
RISKIQ_SOURCES_FILE=/app/sources.local.json
RISKIQ_SOURCE_DATABRICKS_TOKEN=SECRET_COTE_SERVEUR
RISKIQ_SOURCE_SNOWFLAKE_TOKEN=SECRET_COTE_SERVEUR
RISKIQ_SOURCE_FOUNDRY_TOKEN=SECRET_COTE_SERVEUR
```

Sous Docker, monter `sources.local.json` en lecture seule dans `/app/sources.local.json` via un fichier compose d’override ; ne pas le copier dans l’image. Les secrets doivent provenir du gestionnaire de secrets du client ou de l’environnement du processus. La UI ne reçoit ni token ni chaîne de connexion.

Le client sélectionne une source/table autorisée et déclenche l’import. Le serveur exécute une lecture, contrôle les limites et crée un instantané avec provenance/empreinte. **Ces lectures peuvent être facturées par la plateforme.** Elles ne sont jamais déclenchées par le LLM. Le compte de service doit être en lecture seule et limité aux données convenues ; un `LIMIT` ne garantit pas, à lui seul, un faible coût de scan.

Limites : 100 000 lignes / 15 MiB par import, pas de streaming distribué, pas de copie intégrale silencieuse si le résultat est tronqué. Les données sont extraites et stockées dans la base applicative : ne pas utiliser ce mode si la politique client interdit l’extraction. Déployer alors le noyau dans son périmètre de calcul ou préparer une vue matérialisée autorisée.

## Bibliothèques optionnelles

```bash
pip install '.[postgres]'  # métadonnées/source PostgreSQL
pip install '.[gcp]'       # BigQuery avec Application Default Credentials
```

Le Dockerfile accepte `--build-arg INSTALL_EXTRAS=postgres,gcp` pour installer ces options. Aucun de ces SDK n’est nécessaire au mode local CSV/SQLite. BigQuery utilise ADC : préférer une identité de workload gérée plutôt qu’un fichier de clé distribué. La région, les droits et les éventuels transferts doivent être validés par le client.

## Exécuter le noyau près des données

`riskiq.cli.analyse_frame(dataframe, specification)` produit un candidat tarifaire et ses preuves sans démarrer de serveur ni ouvrir la base de l’application. Exemple local :

```bash
python -m riskiq.cli analyse --input portefeuille.csv --out local-output
python examples/score_export.py local-output/tariff.json portefeuille.csv local-output/scored.csv
```

Les sorties portent le statut **unapproved_headless_candidate**. Le mode headless n’hérite pas magiquement du workflow d’approbation web : il faut raccorder les résultats à la gouvernance cible avant utilisation opérationnelle. `examples/headless_platform_job.py` illustre l’appel du noyau à partir d’un DataFrame ; ce n’est pas un connecteur certifié d’exécution native.

Pour un scorer indépendant des bibliothèques scientifiques, copier `riskiq/core/scoring.py` à côté de `examples/score_export.py`, sous le nom `scoring.py`. Le bundle JSON contient modèle et transformations. Aucun `pickle`, `eval` ni appel cloud n’est nécessaire au scoring.

## Databricks : deux niveaux distincts

**Aujourd’hui :** lire un portefeuille via le SQL Statement Execution API, sous les droits du compte de service. Le handler traite explicitement les états FAILED, PENDING, RUNNING, les chunks et la troncature. Les réponses HTTP 200 ne sont pas toutes des succès SQL.

**Étape suivante :** installer le package dans un Job Python/Notebook client et exécuter le noyau sur un extrait préparé et autorisé ; ensuite industrialiser le pushdown, Unity Catalog/MLflow, les identités et les artefacts. Un export `.toPandas()` reste borné en mémoire, il ne devient pas distribué par le seul fait de tourner sur Databricks. Une application native Databricks Apps demande un packaging et une recette distincts.

## Snowflake

**Aujourd’hui :** SQL API pour extraire une table autorisée ; polling asynchrone et récupération des partitions. Les noms de tables sont validés et explicitement quotés.

**Étape suivante :** évaluer Snowpark Python ou Snowpark Container Services pour le calcul proche des données, avec compute pools, réseau, image, secrets, restrictions de paquets et gouvernance du client. Aucun package Snowflake Native App/Marketplace n’est livré ou déclaré prêt.

## Palantir

**Aujourd’hui :** lecture d’un Dataset Foundry via REST v2 `readTable`, avec RID et branche. Cela ne constitue ni une intégration aux objets/actions de l’Ontology ni une application AIP native. Les views ne sont pas acceptées par cet endpoint selon la documentation citée.

**Étape suivante :** mapper contrats, garanties, modèles, versions, décisions et résultats vers l’Ontology du client et son système d’Actions ; traiter les Markings et l’autorisation au niveau objet. Ces conventions ne doivent pas être inventées sans accès à l’environnement du client.

## GCP n’est pas une seule data platform

BigQuery pour l’analytique, Cloud Storage pour les objets, Cloud SQL pour les métadonnées, GKE/VM/Cloud Run pour l’exécution et Vertex AI pour les services IA sont des capacités différentes. L’adaptateur actuel couvre **BigQuery en lecture**, pas cet ensemble.

Cloud Run a un système de fichiers éphémère. **Ne pas y déployer SQLite en prétendant conserver les données.** Une architecture cible doit externaliser l’état et traiter les jobs durablement. Le worker embarqué de cette version nécessite du CPU hors requêtes ; le contrat Cloud Run par défaut n’offre pas les garanties nécessaires sans configuration et architecture supplémentaires. Privilégier d’abord une VM contrôlée pour le pilote, ou recetter un worker dédié sur GKE/VM avec PostgreSQL. Les déclarations de compatibilité native attendent une vraie recette.

## Autres plateformes

Une extension doit implémenter la lecture bornée de tables, des références de secrets, l’allowlist de tenant/tables, les limites, les erreurs explicites, les tests de contrat et une recette réelle. Les prochaines abstractions utiles sont l’exécution de jobs, les références d’artefacts, les événements et l’identité fédérée. Ne pas factoriser toute la sémantique des plateformes dans un faux connecteur universel.

## Sources primaires consultées le 10 octobre 2026

- Databricks, Statement Execution API : https://docs.databricks.com/api/statement-execution/v1/statement-execution
- Databricks Apps : https://docs.databricks.com/aws/en/dev-tools/databricks-apps/
- Snowflake, SQL API : https://docs.snowflake.com/en/developer-guide/sql-api/reference
- Snowflake, Snowpark Container Services : https://docs.snowflake.com/en/developer-guide/snowpark-container-services/overview
- Palantir, Foundry v2 Read Table Dataset : https://www.palantir.com/docs/foundry/api/v2/datasets-v2-resources/datasets/read-table-dataset
- Google, BigQuery Python Client : https://docs.cloud.google.com/python/docs/reference/bigquery/latest/google.cloud.bigquery.client.Client
- Google, Cloud Run container contract : https://cloud.google.com/run/docs/container-contract

Ces pages justifient les points d’intégration proposés. Elles ne certifient pas que cette version fonctionne déjà dans chacun de ces environnements.
