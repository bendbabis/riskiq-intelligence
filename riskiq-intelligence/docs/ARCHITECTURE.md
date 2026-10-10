# Architecture — boucle d’intelligence tarifaire augmentée

## Décision d’architecture

Un **monolithe modulaire**, une interface HTML/CSS/JavaScript servie par FastAPI et des calculs Python séparés. Ce choix réduit les prérequis d’installation : un service applicatif au lieu de deux chaînes de build distinctes. Ce n’est pas une migration automatique du frontend Next.js d’origine.

Le domaine `riskiq/core/` n’importe ni FastAPI, ni SQLAlchemy, ni SDK cloud. `scoring.py` ne dépend que de la bibliothèque standard Python. `modeling.py` et `pricing.py` utilisent les bibliothèques scientifiques. Le stockage et la coordination sont dans `store.py` et `workflow.py`. Les fournisseurs sont exclusivement dans `adapters.py` et `copilot.py`.

```text
Interface web / API / commande headless
                |
Identité serveur + tenant + autorisations + CSRF
                |
Orchestrateur persistant (état / bail / points de contrôle)
    |           |            |             |
 agents       outils       preuves       approbation humaine
    |           |            |             |
    +----- noyau actuariel indépendant ----+
                |
  version tarifaire / API de cotation interne
                |
  nouvel instantané / monitoring / revue liée

Adaptateurs de données : CSV local, PostgreSQL,
Databricks SQL, Snowflake SQL, Foundry Dataset, BigQuery
```

## Une vraie boucle, avec une autonomie bornée

Les agents sont des responsabilités métier exécutables, pas des personas de chat qui prétendent collaborer. Chaque agent appelle un outil déterministe et produit un résultat typé/versionné. Le graphe d’exécution est borné ; une anomalie qualité ou un scénario infaisable bloque la suite.

| Étape | Agent | Responsabilité implémentée | Preuve produite |
|---|---|---|---|
| 1 | Atlas | Contrôler le grain et les unités, sélectionner la garantie, bloquer les données invalides | Rapport de qualité et empreinte du jeu |
| 2 | Sentinel | Calculer fréquence, coût, prime acquise et S/P historique ; signaler le besoin d’investigation | Diagnostic chiffré avec limites |
| 3 | Helios | Entraîner fréquence × sévérité et Tweedie ; sélectionner sur validation | Modèles JSON, encodage figé, manifeste de split |
| 4 | Echo | Vérifier séparation des échantillons, parité du scorer et garde-fous de calibration | Rapport de contrôle automatisé, distinct d’un avis actuariel humain |
| 5 | Vega | Simuler et optimiser un tarif de renouvellement borné par segment | Scénario réalisable, contraintes, frontière locale et candidat tarifaire |
| 6 | Iris | Sceller les preuves et préparer le passage à une personne habilitée | Empreinte de dossier à approuver |
| 7 | Humain | Approuver/rejeter avec un autre compte ; publier ensuite | Identités, motif, empreinte, publication interne |
| 8 | Suivi | Mesurer charges observées/attendues et dérive sur un autre instantané | Observation liée à la décision ; revue suivante sur demande |

**Limite :** pas de planification libre par LLM, de collaboration multi-LLM auto-organisée, ni d’apprentissage autonome des politiques. Le LLM facultatif reformule une liste blanche de résultats calculés. Le message libre de l’utilisateur, les lignes individuelles, noms de segments, identifiants et secrets ne lui sont pas transmis. Les agrégats restent potentiellement confidentiels ; activation explicite par l’opérateur et par appel.

## États et reprise

`queued → running → … → awaiting_approval → approved → deployed → measured`.

Sorties alternatives : `blocked`, `failed`, `cancelled`, `rejected`, `withdrawn`. Les objets proposés sont immuables dans l’API. Une nouvelle revue produit de nouveaux objets.

Le worker revendique une étape avec un bail de 15 minutes et un jeton de possession. Les résultats sont calculés hors transaction, puis les nouveaux artefacts et le point de contrôle sont validés ensemble. Un worker périmé ou un travail annulé ne peut pas écraser le nouvel état. Une étape interrompue est recalculée, une étape terminée ne l’est pas. La clé d’idempotence de création refuse sa réutilisation avec une demande différente.

Cette version ne renouvelle pas le bail pendant une étape longue : les limites d’import bornent les calculs, mais les durées doivent être mesurées avant montée en charge. Prévoir heartbeat, annulation coopérative, files séparées et supervision avant usages lourds. Les fichiers d’artefacts sont compressés dans la base ; cela simplifie la durabilité mais n’est pas une stratégie lakehouse pour des millions de lignes.

## Modèles et cohérence actuarielle

Fréquence : cible `N / exposition`, poids `exposition`, modèle Poisson lien log. Sévérité : sur lignes avec `N > 0`, cible `charge / N`, poids `N`, Gamma lien log. Prime pure : Tweedie sur `charge / exposition` avec poids exposition, puissance 1,5 déclarée. Les formulations de dispersion ne sont pas généralisées abusivement comme une équivalence universelle entre poids et offsets.

Variables numériques explicites, y compris celles à faible cardinalité et contenant `_`. Effets non linéaires disponibles sous forme de fonctions linéaires par morceaux à nœuds appris sur entraînement. Modalités et référence catégorielles figées, normalisation de casse/espaces, valeurs manquantes traitées par transformation apprise. Une variable obligatoire absente ou une modalité inconnue provoque un renvoi explicite plutôt qu’un prix arbitraire.

Trois échantillons distincts : entraînement, validation pour sélectionner le candidat, test final réservé. Dates chronologiques ou séparation groupée par police si le mapping indique explicitement l’absence de date. Les polices répétées traversant les frontières temporelles sont refusées dans cette version ; pas de stratégie avancée de purge/embargo implicite. Pas de réajustement final sur tout le portefeuille après sélection.

L’API et l’export utilisent le même modèle sérialisé explicitement, pas des grilles discrétisées recalculées dans plusieurs endroits. Les arbres, l’elastic net, les bandes de confiance et les grilles éditables ne sont pas annoncés comme implémentés.

## Simulation et optimisation

Le tarif proposé part de la prime pure / (1 − ratio de frais), puis d’un facteur commercial par segment et de limites de variation par risque. Le prix TTC utilise un taux illustratif fourni par l’utilisateur, avec HT et taxe arrondis au centime, puis somme TTC exacte. Une seule garantie par devis ; pas de fiscalité française présumée.

Avant et après utilisent la même rétention de référence. L’élasticité est une hypothèse paramétrique bornée. L’objectif et les contraintes sont normalisés ; des gradients sont fournis à SLSQP et plusieurs départs sont explorés. Le meilleur résultat faisable est retenu. Aucun certificat d’optimum global n’est annoncé. Un optimum inchangé peut être valide : on ne rejette pas systématiquement l’absence de mouvement comme le suggère le correctif C6 du rapport source.

## Données et isolation

Identifiants UUID complets ; contrôles tenant sur chaque lecture/écriture métier ; contexte tenant et auteur dans les jobs. Les utilisateurs, sessions, versions, revues, approbations et journaux sont persistés côté serveur, pas dans localStorage. Le serveur n’accepte ni requête SQL libre ni expression Python de l’utilisateur ou de l’agent.

Le journal est append-only au niveau applicatif et chaîné par HMAC. Il ne constitue pas une garantie WORM ; un administrateur disposant de la base et de la clé peut le réécrire. Une ancre signée/externalisée et une politique de conservation sont nécessaires pour un déploiement entreprise.

## Modes de portabilité

1. **Autonome** : application + SQLite sur poste/VM, sans fournisseur data/LLM.
2. **Connecté** : même application ; lectures de tables autorisées via adaptateurs. Les données sont copiées en instantanés bornés : pas de promesse zéro copie.
3. **Au plus près des données** : package Python et `analyse_frame` dans un environnement d’exécution client ; recettes spécifiques à recetter.
4. **Natif distribué / marketplace** : non implémenté. Databricks Apps/Jobs, Snowpark Container Services, Foundry/AIP et GCP ont des identités, droits et contrats d’exécution différents ; Docker seul ne les rend pas interchangeables.
