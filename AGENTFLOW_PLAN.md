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
- [x] Si le code généré lève une erreur, renvoyer le code + la traceback au LLM et demander une correction ; **3 tentatives max**.
- [x] Stocker chaque tentative dans l'état (`code`, `error`, `attempt`) et l'envoyer au frontend via WebSocket.
- [x] Tests avec faux LLM : réussite au 1er essai ; échec puis réussite au 2e ; 3 échecs → l'erreur remonte proprement au Reporter, qui le signale dans le rapport.
- [x] Commit : `feat(code-agent): self-correction loop with error feedback` → push.
- Bilan : tests écrits d'abord (rouges), puis boucle dans `CodeAgent.run` (`MAX_ATTEMPTS = 3`). 82 tests backend, 21 frontend.
  - La correction envoie au LLM la tâche, les colonnes, le code fautif et la traceback (limitée au code généré). Un code refusé par le pré-filtre compte comme une tentative ratée, avec la raison du refus, et n'atteint jamais le sandbox.
  - `code_attempts` dans l'état, persisté dans `result.code_attempts`. Un événement WebSocket `code_attempt` par tentative ; `useWebSocket` expose `attempts` et affiche « Attempt N failed… Retrying » sur le CodeAgent.
  - Après 3 échecs : le pipeline va quand même au Reporter, qui ajoute une section déterministe « Code execution failed » (nombre de tentatives, dernière erreur). Le statut reste `completed`, avec `error` renseigné.
  - Limite : les événements `code_attempt` partent à la fin du nœud CodeAgent, pas en direct pendant les tentatives. L'affichage détaillé (code, tentatives) est prévu à l'étape 5.
  - `_ensure_dataframe_setup` supprimé : le sandbox fournit déjà `df`.

## Étape 4 — Choix du fournisseur LLM (nécessaire pour le déploiement)
- [x] Une seule fabrique `get_llm()` (supprimer les `ChatOllama(model="llama3.2:1b")` par défaut dans chaque agent).
- [x] `LLM_PROVIDER=ollama|groq`, `LLM_MODEL=...` ; Ollama par défaut en local, Groq (`langchain-groq`) pour la démo en ligne.
- [x] Corriger l'incohérence : README et défaut du code doivent annoncer le **même** modèle.
- [x] Tests : sélection du fournisseur, erreur claire si `groq` sans `GROQ_API_KEY`.
- [x] Commit : `feat(llm): configurable provider (Ollama local, Groq for hosted demo)` → push.
- Bilan : `backend/llm.py` (`get_llm()`), 9 tests écrits d'abord. Total backend : 91 tests.
  - Modèle par défaut gardé : `llama3.2:1b` (celui qu'utilisait réellement le code) ; README, `.env.example` et docker-compose alignés dessus. Groq : `llama-3.3-70b-versatile`, température 0.
  - `OLLAMA_MODEL` reste accepté (compatibilité) ; `OLLAMA_HOST` est maintenant réellement utilisé comme `base_url`.
  - `groq` sans `GROQ_API_KEY` ou fournisseur inconnu → `LLMConfigError` explicite au démarrage (le workflow est construit à l'import).
  - `langchain-groq==0.2.1` (compatible langchain-core 0.3).
  - Remarque : sous Windows, en pleine suite, le test « boucle infinie < 10 s » a dépassé une fois (12 s) à cause du démarrage lent du sous-processus ; seul il prend environ 7 s, et sous Linux environ 6 s.

## Étape 5 — Démo utilisable par un visiteur
- [x] **3 exemples en un clic**, chacun avec un petit jeu de données fourni dans le repo (ex. ventes mensuelles CSV, catalogue produits JSON, avis clients TXT) : la tâche et le fichier se remplissent automatiquement. Un visiteur n'a pas de CSV sous la main.
- [x] Dans le résultat : **code généré** affiché (repliable, coloration syntaxique), **tentatives** de correction visibles, **graphiques** affichés dans le rapport, **durée par agent**.
- [x] Rapport téléchargeable en Markdown (existe) + copie en un clic.
- [x] Tests frontend correspondants.
- [x] Commit : `feat(ui): one-click examples, generated code, retries and charts in results` → push.
- Bilan : 96 tests backend, 34 frontend. Vérifié dans le navigateur (backend + frontend lancés, sans LLM).
  - Jeux de données dans `frontend/public/examples/` (ventes mensuelles CSV, catalogue produits JSON, avis clients TXT), testés côté backend avec le FileAgent ; `ExamplePicker` charge le fichier et remplit tâche + fichier via la prop `preset` de `TaskInput`.
  - Backend : `result.agent_durations` (secondes par nœud) et `duration` dans chaque événement `agent_update`.
  - ResultViewer : code final repliable (Prism, Python seul), liste des tentatives avec erreur et traceback, durée par agent, bouton Copy (+ Download existant).
  - Bug corrigé : les graphiques du rapport pointaient vers `/uploads/...` sur l'origine du frontend ; ils sont maintenant chargés depuis l'API (`apiBase`). Renderer `code` typé (fin du `any`).
  - À traiter à l'étape 6 : quand Ollama est injoignable, le rapport affiche l'erreur brute (`WinError 10061`) et « 0 attempts » au lieu d'un message clair « LLM indisponible ». Bundle JS passé à 555 kB (Prism) : envisager un import dynamique.

## Étape 6 — Interface (skill frontend-design)
- [x] Même direction que le portfolio silue-dev : fond sombre bleuté, une couleur d'accent, police sans-serif pour le texte et monospace seulement pour le code et les labels.
- [x] Pipeline des agents : états clairs (en attente / en cours / terminé / erreur / sauté), lisible sur mobile.
- [x] États vides, chargement, erreurs (LLM indisponible, serveur en réveil) explicites.
- [x] Accessibilité : contraste AA, focus clavier, `prefers-reduced-motion`.
- [x] Captures avant/après pour Gninho.
- [x] Commit : `feat(ui): visual refresh aligned with portfolio` → push.
- Bilan : 101 tests backend, 40 frontend. Vérifié dans le navigateur (bureau 1280 px et mobile 375 px, focus clavier).
  - Tokens repris du portfolio (`#0d1117`, cartes `#151b23`, ambre `#F59E0B` seulement pour bouton principal, agent en cours, focus, lien), Geist + JetBrains Mono (code, durées, état des agents). Titres en casse de phrase, plus d'emoji ni de libellés en capitales.
  - Pipeline : piste numérotée (vraie séquence), verticale sur mobile, horizontale dès `lg` ; 5 états écrits en toutes lettres (Waiting, Running, Done, Failed, Skipped). Un agent jamais lancé est « Skipped » au lieu de « Done ».
  - États : placeholder « No result yet » et « The agents are working on it » ; bandeau « server waking up » (hook `useBackendStatus`, réessais toutes les 3 s pendant 75 s) puis « unreachable » avec bouton « Try again » ; erreurs HTTP lisibles (429, `detail` de l'API).
  - LLM indisponible : vérification d'Ollama (`check_llm`) avant chaque exécution ; la tâche échoue en moins de 5 s avec « The language model is unavailable. Ollama is not reachable at … Start it with `ollama serve`… » au lieu de faux rapports de secours.
  - Accessibilité : focus visible ambre partout, `prefers-reduced-motion` (animations coupées), zone d'upload atteignable au clavier, bouton de suppression visible au focus et sur mobile, libellé sur la zone de texte, lien d'évitement « Skip to results », états non portés par la couleur seule.
  - Captures avant/après : `docs/screenshots/` (before-desktop-empty, before-desktop-result, before-mobile ; after-desktop-empty, after-desktop-result, after-desktop-llm-unavailable, after-mobile).
  - Restes : bundle JS 557 kB (coloration Prism) ; l'import dynamique est possible mais demande d'adapter les tests du ResultViewer.

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
