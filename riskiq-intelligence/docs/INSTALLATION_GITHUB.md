# Installer puis déposer dans ton GitHub

## 1. Décompresser correctement

Extraire `RiskIQ_Intelligence_0.1.0.zip`. Entrer dans le sous-dossier **riskiq-intelligence** : il doit contenir `README.md`, `pyproject.toml`, `docker-compose.yml`, `riskiq/`, `tests/`, `.github/` et `scripts/`.

Ne pas déposer uniquement le ZIP ou `index.html` dans GitHub : il faut l’arborescence complète. Créer un nouveau dépôt pour conserver l’ancien projet intact. L’archive ne contient ni `.git`, ni environnement virtuel, ni base client, ni secrets.

## 2. Lancer localement

Méthode Docker : installer Docker Desktop selon la politique de ton poste ; le lancer. Depuis PowerShell dans ce dossier :

```powershell
py scripts/configure.py
docker compose up --build -d
```

Le premier appel crée `.env` et `.local-credentials.txt` avec des valeurs aléatoires locales. Le second construit une image et démarre le service. La construction nécessite Internet et peut prendre plusieurs minutes. Elle n’a pas pu être testée dans l’environnement de livraison, qui ne possède pas Docker : traiter tout échec comme un point de recette à résoudre, pas comme un succès présumé.

Accéder à `http://127.0.0.1:8080`, pas à une adresse publique. Utiliser **exactement cette adresse** avec la configuration par défaut : le contrôle Origin attend ce nom. L’espace est `demo` ; les mots de passe figurent uniquement dans `.local-credentials.txt`.

Alternative sans Docker : voir les commandes Python du README. Si `py -3.13` n’existe pas, installer une version Python prise en charge ; ne pas sélectionner arbitrairement Python 3.14.

## 3. Vérifier la première boucle

Créer les données synthétiques ; lancer une revue ; attendre « À valider ». Se connecter avec le compte approbateur, examiner et approuver. Revenir au compte administrateur et publier **en interne**. Tester un devis. Créer un nouvel instantané synthétique dans le suivi et observer les métriques. La démonstration ne prouve pas la qualité sur un portefeuille client réel.

## 4. Créer le dépôt privé GitHub

Sur GitHub, choisir **New repository**, nom `riskiq-intelligence`, visibilité **Private**. Pour utiliser les commandes suivantes, ne pas cocher la création d’un README, d’un `.gitignore` ou d’une licence : ces fichiers existent localement. Authentifier Git avec GitHub Desktop, GitHub CLI ou le gestionnaire de credentials officiel ; ne jamais inscrire un token dans l’URL du remote.

```powershell
git init -b main
git add .
git status
```

**Arrêt de contrôle avant le commit** : vérifier qu’aucun `.env`, `.local-credentials.txt`, `sources.local.json`, contenu de `var/`, `.pem`, `.key`, portefeuille réel ou token n’est ajouté. Le `.gitignore` livré exclut ces chemins. Une règle `.gitignore` ne protège pas un secret déjà commité ailleurs.

```powershell
git commit -m "Initial RiskIQ Intelligence reference release"
git remote add origin https://github.com/TON-COMPTE/riskiq-intelligence.git
git push -u origin main
```

Remplacer `TON-COMPTE` par ton utilisateur ou organisation. Si Git demande l’identité de commit, la configurer pour ce dépôt avec tes propres nom/e-mail. Si l’organisation bloque les pushes ou les Actions, respecter sa procédure d’accès ; ne pas désactiver ses protections.

Avec GitHub CLI déjà installé et autorisé, alternative à la création manuelle du dépôt distant :

```powershell
gh auth login
gh repo create riskiq-intelligence --private --source=. --remote=origin --push
```

À exécuter après le commit local, à la place des commandes `remote add`/`push`, pas en plus.

## 5. Contrôler l’onglet Actions

Le workflow **CI / actuarial & governance** exécute les tests Python, vérifie le JavaScript et construit le package. Une recette Playwright utilise un vrai serveur HTTP, des comptes générés et une base synthétique temporaire. L’audit de dépendances peut bloquer sur une vulnérabilité trouvée : ne pas le neutraliser pour obtenir un badge vert.

Les pipelines sont fournis mais n’ont pas été exécutés dans ton compte GitHub. Leur statut n’est donc pas « vérifié sur GitHub ». Les preuves locales se trouvent dans `qa/` ; les preuves de CI seront les artefacts du workflow.

Le workflow **Container / manual** est déclenchable manuellement. Il construit une image ; une case de confirmation permet éventuellement de l’envoyer dans GitHub Container Registry. Les permissions `packages: write` doivent être autorisées par ton organisation. Ce workflow ne crée aucun serveur et ne modifie aucun DNS.

## 6. GitHub n’est pas l’hébergeur de cette application

GitHub Pages sert des fichiers statiques. Il ne peut pas exécuter FastAPI, les modèles, la base SQL, les sessions ou le worker. Pour un site accessible sur Internet, il faudra un hébergement applicatif distinct, un domaine, HTTPS et une recette de sécurité. Les workflows livrés ne mettent rien en ligne automatiquement.

**Ordre recommandé** : code privé → tests CI → démonstration locale → pilote privé sur une VM contrôlée → revue de sécurité/actuarielle → intégration cloud → éventuelle production client.

## 7. Arrêter, sauvegarder, mettre à jour

```powershell
docker compose stop
docker compose up -d
```

Ces commandes conservent le volume. Pour une sauvegarde cohérente locale, arrêter l’application puis utiliser `scripts/backup_sqlite.py` sur la base (voir SECURITY_AND_OPERATIONS). Garder la clé d’audit séparément. Ne pas supprimer de volume, ni réinitialiser une base, pour résoudre un simple problème d’interface.

## Sources officielles consultées le 10 octobre 2026

- GitHub : « Adding locally hosted code to GitHub » — https://docs.github.com/en/migrations/importing-source-code/using-the-command-line-to-import-source-code/adding-locally-hosted-code-to-github
- GitHub : « What is GitHub Pages? » — https://docs.github.com/en/pages/getting-started-with-github-pages/what-is-github-pages

Ces sources décrivent les produits GitHub. Elles ne constituent pas une validation du code RiskIQ.
