# AGENTFLOW_PLAN.md — Fiabiliser, sécuriser, améliorer et déployer AgentFlow

> Brief pour Claude Code. Lis-le en entier. Une étape à la fois, dans l'ordre.
> Fin d'étape : tests verts → commit → push → coche ici → résume et stop.

## Contexte

- Premier projet IA de Gninho : 5 agents (Planner, FileAgent, CodeAgent, Reporter, Supervisor) orchestrés avec LangGraph, LLM local via Ollama, FastAPI + WebSocket, React/TypeScript, SQLite.
- État actuel : 2 commits, **aucun test**, modèle par défaut `llama3.2:1b` (le README dit « Llama 3.2 3B »).
- **Problème de sécurité vérifié le 21/11/2026** : `backend/tools/code_executor.py` exécute le code généré par le LLM avec `exec()` **dans le processus du serveur**. Les builtins sont restreints, mais :
  - `pd.read_csv('/etc/hostname')` lit n'importe quel fichier du serveur (testé : ça marche) ; pandas peut aussi écrire des fichiers ;
  - `().__class__.__base__.__subclasses__()` est accessible (730 classes), point de départ classique d'une évasion ;
  - le timeout de 30 s repose sur `future.result(timeout=...)` : le thread n'est pas tué, une boucle infinie continue de consommer le CPU.
  → **Rien ne doit être déployé publiquement avant l'Étape 2.** Le README ne doit plus dire « sandboxed » tant que ce n'est pas vrai.

## Règles

- Commit = une étape terminée (code + tests + doc). Conventional Commits en anglais. Push sur `main` après chaque étape (le projet n'est pas encore déployé).
- **TDD pour tout nouveau code** (Red → Green → Refactor). Étape 1 = tests de caractérisation du code existant.
- Jamais de `--force`, jamais de secrets commités (clé Groq uniquement en variable d'environnement).
- Les tests ne doivent **jamais** appeler un vrai LLM : utiliser un faux LLM (`FakeListChatModel` de langchain_core ou un stub) qui renvoie des réponses scriptées.
- Toute affirmation du README doit être vraie et vérifiable.

---

## Étape 1 — Filet de tests + CI
- [x] `pytest` + `pytest-asyncio` + `httpx`, dossier `backend/tests/`.
- [x] Planner : parsing JSON (bloc ```json, texte autour, JSON invalide → fallback), normalisation (agents inconnus filtrés, `reporter` toujours ajouté, 4 sous-tâches max).
- [x] Workflow LangGraph avec faux LLM : routage avec et sans fichier (FileAgent sauté sans fichier), état final `completed`, erreur d'un agent → état `error` propre.
- [x] API (`TestClient`) : création, exécution, statut, liste, suppression, upload (types et tailles refusés), rate limiting.
- [x] Frontend : `vitest` + Testing Library sur `TaskInput` (validation, upload) et `useWebSocket` (messages reçus → état du pipeline).
- [x] GitHub Actions : job backend (pytest) + job frontend (lint, typecheck, vitest, build). Badge dans le README.
- [x] Commit : `test: characterization tests and CI` → push.
- Bilan : 50 tests backend (pytest), 19 tests frontend (vitest). Bugs révélés par les tests et corrigés au minimum :
  - un agent qui lève une exception laissait l'agent suivant écraser le statut `error` (ou faisait boucler le Supervisor jusqu'à `GraphRecursionError`) → arêtes conditionnelles vers `END` ;
  - sans fichier uploadé, le FileAgent essayait de lire le chemin `"None"` ;
  - aucun graphique n'était jamais produit quand le LLM suivait la consigne (`import matplotlib.pyplot as plt` refusé par l'import restreint, et `plt.savefig` remplacé par un commentaire qui empêchait l'injection du vrai `savefig`).
  - Reste noté pour plus tard : `ValueError` & co. absents des builtins autorisés (le code généré ne peut pas lever d'exception explicite) ; renderer `code` de `ResultViewer` typé `any` (react-markdown v9 ne passe plus `inline`).

## Étape 2 — Vraie isolation du code généré (TDD, priorité absolue)
- [x] Écrire d'abord les tests d'attaque, qui doivent **échouer** avec l'exécuteur actuel :
  - lecture d'un fichier hors du dossier de travail (`/etc/passwd`, fichier `.env` du backend) ;
  - écriture d'un fichier hors du dossier de travail ;
  - évasion par `__subclasses__` / `__globals__` ;
  - ouverture d'une socket réseau ;
  - lancement d'un sous-processus ;
  - boucle infinie (doit être **tuée** sous 10 s, le serveur reste réactif) ;
  - allocation mémoire massive (doit être tuée, le serveur survit) ;
  - variables d'environnement du serveur (ex. `GROQ_API_KEY`) invisibles depuis le code exécuté.
- [x] Nouvelle implémentation : exécution dans un **sous-processus séparé** (`python -I -S`), dossier temporaire dédié comme `cwd` contenant uniquement une **copie** du fichier uploadé, `env` vide, limites `resource` (CPU, mémoire, nombre de processus, taille de fichier), timeout dur avec `kill`, + `sys.addaudithook` dans l'enfant pour refuser `open` hors du dossier temporaire, `socket.*`, `subprocess.*`, `os.system`. Sortie (stdout, graphiques) récupérée via le dossier temporaire, puis dossier supprimé.
- [x] Docker : backend en utilisateur non-root, système de fichiers en lecture seule sauf `/tmp` et le dossier des uploads.
- [x] Interface `Sandbox` pour pouvoir brancher plus tard un service externe (E2B, etc.) sans toucher aux agents.
- [x] README : section « Security model » honnête (ce qui est bloqué, et que ce n'est pas une isolation de niveau production multi-tenant).
- [x] Commit : `feat(security): run generated code in an isolated subprocess` → push.
- Bilan : 12 tests d'attaque (`backend/tests/test_sandbox_attacks.py`), tous rouges avec l'ancien `exec()` en processus (9 sur Windows ; les 2 tests POSIX vérifiés sous Linux), verts avec `SubprocessSandbox`. 14 tests fonctionnels du sandbox et de l'interface. Total backend : 76 tests, verts sous Linux en non-root dans l'image Docker.
  - Le timeout (5 s par défaut) démarre après le verrouillage de l'enfant ; le démarrage de confiance (imports, cache de polices) a son propre budget de 60 s.
  - `chart_generator.py` supprimé : il faisait lui aussi un `exec()` dans le serveur. Les graphiques sont maintenant produits dans le sandbox et copiés dans `uploads/`.
  - `CodeAgent.run` renvoie aussi `error` et `traceback` (traceback limité au code généré), prêt pour l'étape 3.
  - `DATABASE_URL` configurable (racine en lecture seule dans Docker). Job CI `docker` : tests lancés dans l'image en non-root.
  - Builtins autorisés élargis (`isinstance`, `map`, `filter`, `ValueError`, etc.) maintenant que l'isolation est réelle.
  - Limite connue : sous Windows (dev local), pas de limite mémoire ni de nombre de processus (pas de `setrlimit`).

## Étape 3 — Boucle d'auto-correction du CodeAgent (TDD)
- [ ] Si le code généré lève une erreur, renvoyer le code + la traceback au LLM et demander une correction ; **3 tentatives max**.
- [ ] Stocker chaque tentative dans l'état (`code`, `error`, `attempt`) et l'envoyer au frontend via WebSocket.
- [ ] Tests avec faux LLM : réussite au 1er essai ; échec puis réussite au 2e ; 3 échecs → l'erreur remonte proprement au Reporter, qui le signale dans le rapport.
- [ ] Commit : `feat(code-agent): self-correction loop with error feedback` → push.

## Étape 4 — Choix du fournisseur LLM (nécessaire pour le déploiement)
- [ ] Une seule fabrique `get_llm()` (supprimer les `ChatOllama(model="llama3.2:1b")` par défaut dans chaque agent).
- [ ] `LLM_PROVIDER=ollama|groq`, `LLM_MODEL=...` ; Ollama par défaut en local, Groq (`langchain-groq`) pour la démo en ligne.
- [ ] Corriger l'incohérence : README et défaut du code doivent annoncer le **même** modèle.
- [ ] Tests : sélection du fournisseur, erreur claire si `groq` sans `GROQ_API_KEY`.
- [ ] Commit : `feat(llm): configurable provider (Ollama local, Groq for hosted demo)` → push.

## Étape 5 — Démo utilisable par un visiteur
- [ ] **3 exemples en un clic**, chacun avec un petit jeu de données fourni dans le repo (ex. ventes mensuelles CSV, catalogue produits JSON, avis clients TXT) : la tâche et le fichier se remplissent automatiquement. Un visiteur n'a pas de CSV sous la main.
- [ ] Dans le résultat : **code généré** affiché (repliable, coloration syntaxique), **tentatives** de correction visibles, **graphiques** affichés dans le rapport, **durée par agent**.
- [ ] Rapport téléchargeable en Markdown (existe) + copie en un clic.
- [ ] Tests frontend correspondants.
- [ ] Commit : `feat(ui): one-click examples, generated code, retries and charts in results` → push.

## Étape 6 — Interface (skill frontend-design)
- [ ] Même direction que le portfolio silue-dev : fond sombre bleuté, une couleur d'accent, police sans-serif pour le texte et monospace seulement pour le code et les labels.
- [ ] Pipeline des agents : états clairs (en attente / en cours / terminé / erreur / sauté), lisible sur mobile.
- [ ] États vides, chargement, erreurs (LLM indisponible, serveur en réveil) explicites.
- [ ] Accessibilité : contraste AA, focus clavier, `prefers-reduced-motion`.
- [ ] Captures avant/après pour Gninho.
- [ ] Commit : `feat(ui): visual refresh aligned with portfolio` → push.

## Étape 7 — Déploiement
- [ ] **Backend sur Render** (Docker, WebSockets supportés, offre gratuite qui se met en veille) avec `LLM_PROVIDER=groq`. **Frontend sur Vercel.**
- [ ] CORS limité au domaine Vercel ; URL du backend en variable d'environnement côté frontend.
- [ ] Message côté frontend quand le backend se réveille (premier appel lent sur l'offre gratuite).
- [ ] Limites de la démo : rate limiting par IP, taille de fichier max, nettoyage automatique des tâches et fichiers de plus de 24 h.
- [ ] `render.yaml` dans le repo. Gninho crée les comptes et colle `GROQ_API_KEY` dans Render lui-même ; **ne jamais demander ni écrire la clé**.
- [ ] Vérifier la démo en ligne avec les 3 exemples.
- [ ] Commit : `chore(deploy): Render backend and Vercel frontend` → push.

## Étape 8 — README et cohérence
- [ ] README : lien de démo en ligne, GIF ou capture du pipeline, architecture (Mermaid), section sécurité, comment lancer en local avec Ollama, tests et CI.
- [ ] Ne plus dire « zero API cost » sans nuance : « runs fully locally with Ollama; the hosted demo uses Groq's free tier ».
- [ ] Résumé final pour Gninho : fonctionnalités ajoutées, nombre de tests, URL de démo, textes à mettre à jour sur LinkedIn, le portfolio et le README de profil GitHub.
