# Traçabilité par rapport à l’audit Claude

**Source reçue :** `Audit RiskIQ Studio.html`, daté du 10 octobre 2026. Il annonce 8 constats critiques, 14 élevés, 12 moyens et 10 faibles. Les 137 tests de l’ancienne application y sont rapportés comme verts. Ses conclusions sont celles de son auteur ; les sources complètes de cette application ne sont pas présentes dans le livrable reçu, et ces 137 tests n’ont pas été réexécutés ici.

**Nature du travail livré :** nouvelle implémentation de référence, périmètre réduit et tests propres. « Traité dans cette version » ne signifie jamais « corrigé dans les fichiers d’origine ». Les recommandations de l’audit sont conservées comme entrées, pas acceptées sans analyse mathématique ou juridique. Les taux fiscaux et les exemples de réglementation cités par le rapport ne sont ni recopiés comme droit en vigueur ni intégrés au moteur.

## Constats critiques

| ID source | Constat source | Traitement dans la nouvelle application | Preuve / limite |
|---|---|---|---|
| C1 | Elastic net affiché alors que seul L2 fonctionne | L2 explicitement annoncé ; aucun sélecteur L1, paramètre `l1_ratio` non supporté rejeté | Tests de contrat. Pas d’elastic net/group-lasso implémenté |
| C2 | Variables entières traitées comme des modalités absentes | Type explicite et design figé ; scorer exact | Test d’effet numérique de `vehicle_power` |
| C3 | Milieux de tranches déformant les extrêmes | Pas de conversion en grille par milieux : scoring du modèle explicite | Parité calcul sklearn / JSON. Grilles éditables non livrées |
| C4 | Lissage complété par des zéros | Aucun lissage de grille implicite | Risque évité par conception, pas de réécriture du lissage historique |
| C5 | `_` interprété comme séparateur de modalités | Variables/modalités décrites explicitement dans le bundle | Tests de noms avec `_`, score unitaire et par lot |
| C6 | Optimiseur sensible à l’échelle monétaire | Objectif/contraintes normalisés, gradients, multi-départs et contrôle de faisabilité | Test d’invariance d’échelle. Pas de preuve d’optimalité globale |
| C7 | Deux `getTariff` dans le client Next.js | Nouveau frontend indépendant, routes non ambiguës | Parcours UI de la nouvelle version ; Next.js d’origine non corrigé |
| C8 | Aucun endpoint métier authentifié | Sessions serveur, Argon2id, CSRF, droits, tenant, approbateur différent | Tests négatifs API. SSO/MFA non livrés |

**Précision C6 :** l’absence de déplacement du solveur n’est pas, à elle seule, une erreur. Le tarif inchangé peut être optimal ou le seul point faisable. La version rapporte la faisabilité et la variation objective sans inventer une amélioration.

## Constats élevés

| ID | Sujet | Réponse / limite |
|---|---|---|
| H1 | Sévérité agrégée mal pondérée | Gamma sur charge / nombre, poids nombre ; contrat d’unité explicite et tests de vérité |
| H2 | Référence d’encodage variable selon le lot | Design, référence et imputation figés à l’entraînement ; scores singleton/lot identiques |
| H3 | Importance d’arbre utilisée comme coefficient | Aucun arbre annoncé dans cette version ; les modèles non supportés sont refusés. Pas de pickle |
| H4 | Rétention de base différente avant/après | Même référence des deux côtés ; scénario identique produit un delta nul |
| H5 | Intercept et relativités incohérents | Reproduction exacte du prédicteur avec centrage explicite, sans grille parallèle |
| H6 | PSI excluant les observations extrêmes | Classes extrêmes ouvertes à ±∞ ; classe de manquants ; test avec choc hors plage |
| H7 | CSV français | Séparateur détecté ou choisi, décimale explicite, UTF-8/BOM/CP1252 ; tests |
| H8 | Faux bon score qualité | Règles bloquantes de grain, nombre/montant, exposition, dates ; pas de note décorative. Borne d’exposition configurable selon le grain |
| H9 | Cockpit mélangeant fréquence et euros | Workflow produit uniquement des candidats de prime pure ; KPI monétaires cohérents et liés à la revue |
| H10 | Simulation non reliée au moteur | Simulation réellement calculée ; scénario avant/après visible dans la revue |
| H11 | Écrans factices | Actions fournies branchées au backend. Connecteurs non configurés explicitement indisponibles ; aucune temporisation de faux succès |
| H12 | Échecs TypeScript | Frontend JavaScript indépendant vérifié par `node --check` et navigateur ; pas de correction des 7 erreurs historiques |
| H13 | `DataFrame.query()` non sûr, exploitation non confirmée | Filtres structurés ; aucun `eval`/`query` sur contenu utilisateur. Le statut « exploitation non confirmée » du rapport source n’est pas transformé en attaque démontrée |
| H14 | Messages système et écritures IA sans validation | Schéma refuse rôles/messages système ; agents bornés et outils serveur ; LLM read-only ; publication humaine séparée |

## Constats moyens et faibles

M1 : effets par morceaux disponibles, pas GAM complet. M2 : entraînement/validation/test disjoints ; pas de validation croisée imbriquée ou auto-tuning. M3 : XGBoost/LightGBM/RF non repris. M4 : zonage spatial non repris. M5 : inconnus et champs absents en renvoi explicite ; casse normalisée. M6 : baisse exprimée comme fraction positive et bornée. M7 : A/E porte sur des montants, pas un mélange nombre/montant. M8 : volumes exprimés en exposition, sans crédibilité de grille non implémentée. M9 : import borné et erreurs de conversion visibles. M10 : journal séparé des objets, identité serveur, deux comptes distincts. M11 : LLM désactivé par défaut et agrégats en liste blanche à son activation. M12 : une seule représentation du modèle et de son scorer.

Constats faibles traités : réconciliation HT/taxe/TTC au centime, UUID complets, conteneur non-root déclaré, volume persistant déclaré, ressources visuelles locales, suivi et tests propres. Images Docker et dépendances doivent encore être contrôlées dans la CI et par la DSI. La source R et ses conventions ne sont pas utilisées comme oracle sans validation.

## Non couvert par cette version

Tarification simultanée multi-garanties, taxes/CRM/CatNat réglementaires, IBNR et développement des sinistres, réassurance/coût du capital, couches de souscription complètes, modèles de demande estimés/causaux, contrôle avancé d’équité, SHAP/GBM, éditeur de grilles, SSO/MFA, registre objet S3, migrations de production Alembic, SOC2/ISO/DORA ou certification réglementaire, connecteurs d’exécution distribuée et intégration Ontology/AIP. Ces sujets restent dans le plan produit ; ils ne portent aucun badge de fonction opérationnelle.
