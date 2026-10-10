# Sécurité, exploitation et limites de la version 0.1.0

## Usage autorisé par le niveau de recette atteint

Cette livraison est une **version de référence pour démonstration locale et évaluation en pilote privé**, d’abord avec des données synthétiques. Ce n’est pas une autorisation de mise en production publique de données d’assurés. Aucun audit de sécurité indépendant, homologation, certification ni test sur portefeuille client réel n’a été réalisé.

Le service écoute sur la boucle locale dans le compose fourni. Ne pas remplacer cette adresse par `0.0.0.0` côté port publié pour le rendre public sans l’ensemble des contrôles d’hébergement. GitHub contient le code ; il ne protège pas un serveur mal configuré.

## Contrôles effectivement codés

Identités locales réelles ; mots de passe Argon2id ; sessions aléatoires conservées sous empreinte en base ; cookies HttpOnly/SameSite ; CSRF pour les méthodes mutantes ; contrôle Origin et Host ; limite persistée des tentatives de connexion ; suspension/révocation ; espaces tenant contrôlés côté serveur ; UUID ; schémas API à champs supplémentaires interdits ; imports bornés ; filtres structurés ; secrets exclusivement serveur ; contenu UI échappé ; absence de chargement de modèles pickle ; contrôle de version/empreinte des artefacts ; journal HMAC par tenant ; séparation de l’auteur et de l’approbateur ; jobs avec étapes persistantes et jeton de bail.

Le navigateur local utilise HTTP sur `127.0.0.1` et donc des cookies non-Secure. Le mode serveur exige `RISKIQ_MODE=server`, une `RISKIQ_PUBLIC_URL=https://…`, `RISKIQ_COOKIE_SECURE=true` et une clé HMAC persistante. Ces paramètres sont **nécessaires mais non suffisants** pour exposer l’outil : le TLS doit être fourni réellement par l’infrastructure et testé par navigateur.

## Rôles fournis

| Rôle | Capacités principales |
|---|---|
| admin | Gérer les comptes de son tenant ; importer ; lancer ; publier un candidat approuvé ; audit |
| analyst | Importer ; transformer ; lancer ; exporter ; publier après approbation ; suivre |
| approver | Examiner ; approuver/rejeter un dossier créé par un autre compte ; retirer une publication ; consulter audit |
| viewer | Lire les ressources de son tenant et demander un devis sur une version active ; aucun lancement/modification tarifaire |

Un admin ne peut pas approuver sa propre revue. La séparation porte sur les identifiants de comptes, pas sur une preuve biométrique de personnes différentes. L’organisation doit attribuer ces comptes à des personnes distinctes. L’admin système du serveur peut réinitialiser un mot de passe par CLI : ce pouvoir doit être limité et audité dans l’exploitation.

## Créer et faire tourner les mots de passe

Les scripts de configuration génèrent deux mots de passe distincts. Ne jamais commiter `.env` ou `.local-credentials.txt`. Une fois les identifiants placés dans le coffre approuvé, retirer le fichier de lecture locale. Ne pas perdre la clé HMAC d’audit.

```bash
python -m riskiq.cli create-user --tenant demo --email prenom.nom@example.com --role analyst
python -m riskiq.cli set-password --tenant demo --email admin@riskiq.local
python -m riskiq.cli verify-audit --tenant demo
```

`set-password` demande deux saisies masquées et révoque les sessions du compte. Sous Docker, utiliser `docker compose exec app python -m riskiq.cli …` pour exécuter la commande dans la base du conteneur, pas dans une autre base sur l’hôte. Il n’existe pas de reset par e-mail, d’invitation fédérée, de SSO ou de MFA dans cette release.

## Sauvegarde et restauration

En mode Python local, la base est `var/riskiq.db`. Le script utilise l’API de sauvegarde SQLite, vérifie l’intégrité et refuse d’écraser une destination existante :

```bash
python scripts/backup_sqlite.py var/riskiq.db CHEMIN_PRIVE/sauvegarde-datee.db
```

Créer auparavant un dossier privé. Le script ne sauvegarde ni `.env`, ni clé d’audit ni secrets de connecteurs : conserver la configuration et la clé dans le coffre approuvé, séparément de la base. Une sauvegarde sans sa clé ne permet pas de vérifier la chaîne d’audit après restauration.

**Docker utilise un volume nommé**, pas nécessairement `./var/` sur l’hôte. Pour un backup cohérent, soit exécuter la fonction SQLite dans le conteneur avec une destination accessible, soit arrêter proprement le service et sauvegarder le volume entier par l’outil d’exploitation approuvé. Ne pas copier uniquement un fichier `.db` en cours d’écriture en oubliant son WAL. Ne jamais exécuter `docker compose down -v` sur une installation à conserver.

Restauration : arrêter le service et les workers, préserver une copie de l’état actuel, restaurer dans un nouvel emplacement, utiliser la même clé HMAC, vérifier l’intégrité SQLite et `verify-audit`, redémarrer en réseau privé et valider lecture, droits et dernières versions. Le test fourni reconstruit une base depuis une sauvegarde et vérifie comptes et chaîne d’audit ; il ne constitue pas un exercice PRA sur l’infrastructure du client.

## Transactions, concurrence et jobs

SQLite convient au pilote limité ; les lectures applicatives utilisent une transaction sérialisée. Les données compressées, modèles et journaux sont en base. Aucune garantie de montée en charge multi-réplicas n’est annoncée. PostgreSQL est une option SQLAlchemy/psycopg à recetter réellement ; ce n’est pas une recette de bascule transparente.

Le worker embarqué s’exécute en arrière-plan. Une commande `worker` distincte est possible avec la même base et la même clé ; désactiver alors le worker embarqué si nécessaire. Une étape prend un bail de 15 minutes sans heartbeat. Un travail terminé est conservé, un travail interrompu peut être repris ; les traitements longs nécessitent un mécanisme de renouvellement de bail avant montée en charge.

Une annulation empêche la validation de nouveaux résultats ; elle n’interrompt pas immédiatement un calcul scientifique déjà en cours. Un retrait de tarif empêche les nouveaux devis de cette version ; il n’annule pas les contrats déjà souscrits et n’active pas automatiquement un ancien tarif. Les workflows de rollback externes ne sont pas implémentés.

## Audit et confidentialité

Le journal est append-only au niveau de l’application, avec séquence et HMAC. Une personne possédant la base et la clé peut réécrire l’historique. Pour l’entreprise : ancrage externe du digest, stockage protégé, rétention et séparation des responsabilités à définir. Les logs HTTP contiennent des identifiants de ressource ; ils doivent être protégés.

L’isolement actuel est applicatif, pas une politique PostgreSQL RLS ni une séparation physique. Les volumes/backups ne sont pas automatiquement chiffrés par ce code : appliquer les mécanismes disque/base/coffre de l’hébergeur. La minimisation, la durée de conservation, les droits d’accès et les finalités doivent être approuvés par le client. Aucun portefeuille réel n’est inclus dans l’archive.

## LLM facultatif

Désactivé par défaut. Le fonctionnement actuariel et les agents bornés ne dépendent d’aucun fournisseur. À l’activation, seuls des agrégats en liste blanche sont envoyés ; ni message libre, ni lignes individuelles, ni identifiants ni noms de catégories. Ces agrégats peuvent toutefois rester confidentiels. Évaluer le contrat, la région, la conservation, les logs fournisseur et la base juridique avec le client. Un endpoint « compatible OpenAI » ne garantit pas ces propriétés. Le fournisseur LLM n’a pas été appelé pendant cette recette. Ses sorties sont non contraignantes et ne disposent d’aucun outil d’écriture.

## Points bloquants avant exposition publique

Recetter le conteneur et le navigateur en réseau réel ; exécuter SAST/SCA/DAST et revue indépendante ; compléter SSO/MFA et cycle de vie des identités ; renforcer secrets/chiffrement/rétention ; ajouter migrations de schéma versionnées et rollback ; recetter PostgreSQL et sauvegardes ; tester concurrence et charge ; superviser disponibilité, ressources et jobs ; séparer les environnements ; définir le périmètre de conformité et obtenir les validations actuarielles. Ne pas considérer le mode `server` comme une homologation.

Le schéma 0.1.0 est créé par SQLAlchemy `create_all`. Aucune migration d’une version historique ni migration destructive automatique n’est fournie. Faire un backup avant toute mise à jour ; ne pas pointer cette application vers les données internes de l’ancien studio.
