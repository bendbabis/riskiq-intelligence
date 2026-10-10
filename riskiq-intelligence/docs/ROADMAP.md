# Trajectoire vers la cible complète

Ce document distingue les travaux futurs du code livré. Aucune durée ou estimation financière non mesurée n’est présentée comme un engagement.

## Palier 1 — valider le socle livré

Installer le nouveau dépôt privé ; exécuter CI Python et navigateur direct ; construire l’image ; recetter sur le poste de l’utilisateur ; faire relire les mathématiques et les critères d’acceptation par un actuaire indépendant. Conserver les preuves et les cas où la pipeline bloque plutôt que forcer un modèle.

## Palier 2 — reprendre l’application d’origine sans perte

Obtenir le ZIP complet `frontend/`, `backend/`, dépendances verrouillées et tests. Reproduire les constats C1–C8/H1–H14 sur une branche séparée. Établir une matrice fonctionnalités existantes/nouveau noyau ; remplacer progressivement les services à risque par les contrats de calcul, jamais les écrans en masse sans recette. Migrer jeux/modèles/versions avec schémas et empreintes explicites. L’archive 0.1.0 n’effectue pas cette migration.

## Palier 3 — agentique contrôlée enrichie

Conserver l’orchestrateur d’état comme autorité. Ajouter un planificateur LLM en lecture/proposition seulement, un registre typé d’outils et une politique de consentement/budget par action. Un plan proposé doit être validé avant exécution. Ajouter évaluations d’injection, abstention, provenance, qualité des diagnostics, sélection des outils, boucles bornées et consommation. Autoriser la collaboration entre spécialistes par messages structurés sans leur donner le droit de publier. Aucune tarification transactionnelle ne doit dépendre d’une génération de texte.

## Palier 4 — portabilité d’exécution, pas seulement connectivité

Introduire `DataReference`, `ArtifactStore`, `ExecutionBackend`, `IdentityContext`, `EventPublisher` sous contrats versionnés, seulement après avoir fixé les besoins sur de vraies plateformes clientes. Préserver le backend autonome de référence.

Databricks : Jobs/Apps, catalogue, MLflow, identity et tables gouvernées. Snowflake : Snowpark/Container Services, stockage/version des modèles, intégration Native App selon le besoin. Foundry : Ontology, Actions, Markings, AIP et déploiement spécifique. GCP : BigQuery, Cloud Storage, Cloud SQL, worker durable GKE/VM/Jobs, Vertex AI selon besoin. Chaque cible doit passer une recette d’accès, confidentialité, volumes, coûts, arrêts/reprises et parité numérique. Ne pas convertir une extraction `.toPandas()` en promesse de calcul distribué.

## Palier 5 — profondeur métier

Multi-garanties et produits, souscription et délégations, séparation coût technique / tarif commercial / CRM selon contexte applicable, fiscalité par garantie/pays/date validée, préparation sinistres et IBNR, sévérité lourde, GLM/GAM/GBM avec pénalisation vérifiable, grilles versionnées et mesure de fidélité, scénarios prospectifs, demande estimée et incertitude/causalité, optimisation multi-objectifs robuste, risque climatique et territorial avec vraies données sous licence.

## Palier 6 — mesure de la valeur et production

Relier devis exposés, offres, souscriptions, renouvellements et sinistres matures à la version réellement servie. Séparer effet prix, mix, saisonnalité, développement des sinistres, concurrence et biais de sélection. Interdire de présenter un A/E sur données immatures comme un gain causal. Ajouter fenêtres statistiques, groupes de référence, incertitude, seuils approuvés et suivi de valeur économique. Homologation sécurité et actuarielle avant tarifs réels ; SLO, observabilité, PRA, suppression/rétention et responsabilités contractuelles explicités.

**Critère de réussite du produit cible :** une décision tarifaire est explicable et reproductible depuis les données autorisées jusqu’au prix effectivement servi et à ses résultats observés, sans lier son moteur métier à un fournisseur cloud particulier.
