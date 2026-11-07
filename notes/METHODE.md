# La mesure : ce qu'elle fait, ce qu'elle ne dit pas

Validée de bout en bout le 7 octobre 2026 sur `httpx_3672`.

## Ce qu'on mesure

Pour chaque tâche : arbre de travail au `base_commit`, correctif de référence
appliqué, correctif de test appliqué, pytest sous couverture **sur les fichiers
de test que le harnais lui-même viserait**, puis intersection avec les lignes
ajoutées par le correctif de référence.

**Une ligne du correctif de référence que les tests de validation n'exécutent
jamais est une ligne où un agent peut écrire autre chose — ou rien — et marquer
`PASS`.**

Premier résultat : `httpx_3672` → **17,1 %**. Sept des quarante-et-une
instructions ajoutées sont exécutées. Trente-quatre ne le sont pas.

## Pourquoi pas les snapshots du concours

Les 129 snapshots pèsent 21,50 Go sur les 22,42 du jeu de données — 96 %. Ce ne
sont que les quatre dépôts publics figés à `base_commit`, **avec l'historique
postérieur retiré pour qu'un agent ne puisse pas lire la solution**.

Cette mesure ne fait tourner aucun agent. Le masquage ne lui sert à rien. Les
quatre `base_commit` ont été vérifiés atteignables en amont, et quatre clones
pèsent **197 Mo** (relevé le 09/10/2026 ; 179 Mo au premier relevé, les
clones grossissent avec les fetches — un chiffre exact dans un article doit
donc être daté, sinon il se périme sans bruit).

Noté parce que je m'étais trompé en sens inverse : j'avais annoncé que graphes et
embeddings formaient le gros du volume. Ils font 0,89 Go.

## Ce que la mesure NE dit PAS

**Une ligne exécutée n'est pas une ligne vérifiée.** Un test peut traverser une
ligne sans rien affirmer sur son effet. La couverture est donc une **borne
supérieure** de ce que l'oracle contraint : le vrai chiffre est plus bas, jamais
plus haut. À écrire dans l'article, et pas en note de bas de page.

**Seules les lignes ajoutées comptent.** Un correctif purement soustractif
échappe à la mesure — `requests_7315` en est un, il ne fait que retirer deux
lignes. `part_couverte` rend `None` pour ces cas plutôt qu'un zéro trompeur.

**L'échantillon est déséquilibré** : fastapi 67 tâches, rich 48, requests 13,
httpx 1. Aucune affirmation par dépôt ne tiendra pour httpx.

## Trois défauts de l'outil, et comment chacun a été trouvé

Ils vont dans l'article. Un outil de mesure dont on ne publie pas les erreurs de
jeunesse demande qu'on lui fasse confiance sur parole — c'est exactement ce que
le projet reproche aux autres.

### 1. Le parseur ne lisait aucun des 129 correctifs

Il attendait des en-têtes `diff --git`. **Zéro correctif sur 129 n'en a** : ils
sont au format unifié simple, `--- a/x` puis `+++ b/x`. Il aurait rendu « 0 ligne
ajoutée » pour les 129 tâches, sans erreur ni avertissement — un résultat vide
qui ressemble à une mesure.

**Pourquoi l'essai à blanc ne l'a pas vu :** il portait sur un commit local lu
par `git show`, qui produit l'autre format. **Valider sur une entrée qui ne
ressemble pas aux vraies données ne valide rien.**

### 2. `mesurables = executees`

Dans la lecture du fichier de couverture, l'ensemble des instructions mesurables
était initialisé avec les instructions exécutées. La part couverte valait donc
100 % par construction. Trouvé en relisant, **avant la première exécution**.

### 3. Un fichier jamais importé sortait du dénominateur

Le plus grave des trois, parce qu'il penche du côté flatteur. Un module que les
tests n'importent jamais n'apparaît pas dans les données de couverture : ses
lignes ajoutées étaient comptées « non mesurables » — comme un commentaire — au
lieu de « non couvertes ». Un correctif entier que l'oracle ignore passait donc
pour hors sujet.

**Écart sur la même tâche : 26,9 % (7/26) contre 17,1 % (7/41).** Trouvé parce
que le lanceur par lots et la mesure manuelle ne concordaient pas, et que je suis
allé voir pourquoi au lieu de retenir le chiffre le plus récent.

Correction : les fichiers du correctif sont analysés par `coverage.analysis2`
qu'ils aient été exécutés ou non.

## Un piège du jeu de données, pour quiconque bâtira dessus

**Les 258 correctifs (129 × 2) n'ont pas de saut de ligne final.** `git apply`
répond « corrupt patch at line N » sur chacun d'eux. Une ligne de code le règle,
et une demi-journée se perd à le chercher.

## Reproduire

```bash
python src/lancer_mesure.py --taches data/tasks.jsonl --sortie data/resultats.jsonl
python src/lancer_mesure.py --depot Textualize/rich --limite 5   # un sous-ensemble
```

Le lanceur écrit une ligne JSON par tâche, vidée immédiatement : une
interruption ne perd rien et une reprise saute ce qui est déjà fait.

**Chaque échec est consigné avec son statut** — `patch_refuse`,
`tests_echoues`, `sans_couverture`, `erreur` — et non sauté. Un taux calculé sur
les seules tâches qui ont bien voulu s'exécuter mesurerait la facilité
d'installation, pas la portée d'un oracle.

---

# Écueils découverts en industrialisant (7 octobre, suite)

## La dérive de versions fait échouer un correctif de référence sur ses propres tests

C'est le piège le plus coûteux, et il invalide silencieusement des tâches.

| Dépôt | Épinglé à l'époque | Installé par défaut | Effet |
|---|---|---|---|
| `rich` | pygments **2.19.2** | 2.21.0 | les tests comparent des chaînes de coloration exactes → échec |
| `fastapi` | starlette **1.0.0** | 1.7.0 | `filterwarnings = error` + dépréciations → échec à la collecte |

Un correctif de référence qui échoue sur ses propres tests de validation n'est
pas un correctif fautif : c'est l'environnement qui a bougé. **C'est exactement
pourquoi le concours livre 124 wheels épinglées**, et pourquoi une mesure qui les
ignore doit relever les versions depuis le verrou du dépôt au `base_commit`.

## Un dépôt ne doit pas décider où la mesure atterrit

`fastapi` déclare dans son `pyproject.toml` :

```toml
[tool.coverage.run]
parallel = true
data_file = "coverage/.coverage"
```

Coverage écrivait donc des fichiers suffixés dans un sous-dossier. Le lanceur
cherchait `.coverage` à la racine et concluait « coverage n'a rien écrit » —
alors que seize tests venaient de passer. Corrigé par un `--rcfile` imposé et
`COVERAGE_FILE` en absolu.

## Exécuter n'est pas passer

Ces dépôts configurent pytest en `filterwarnings = error`. Une dépendance
moderne y déclenche des dépréciations que le code d'époque ignorait, et le test
s'arrête **à la collecte**, avant d'avoir exercé la moindre ligne.

Décision de méthode, à écrire dans l'article : **la mesure a besoin que les
tests s'exécutent, pas qu'ils passent.** Un avertissement venu d'une version
récente ne change pas quelles lignes le test traverse. Le résultat du test est
consigné à part (`tests_passent`) et n'écarte plus la tâche — et l'analyse
rapporte le chiffre avec et sans ces tâches.

## Le lanceur n'est pas sûr en parallèle

Deux lots simultanés sur des dépôts différents se sont quand même gênés :
worktrees résiduels d'une exécution interrompue, et un fichier de correctif
disparu entre son écriture et sa relecture. Corrigé en passant le correctif en
mémoire plutôt qu'en le relisant, et en élaguant les worktrees avant chaque lot.
**Les lots se lancent l'un après l'autre.**

---

# Ce que les données disent, et ce qu'elles ne disent pas

Trois hypothèses posées, trois réfutées par la mesure :

| Hypothèse | Verdict |
|---|---|
| Les oracles de validation sont troués | **Non** — 90,4 % des lignes ajoutées sont exécutées |
| Les lignes libres sont du traitement d'erreur | **Non** — les levées d'erreur font 6,7 % |
| Des fichiers entiers du correctif ne sont jamais chargés | **Non** — 1 sur 66 |

`httpx_3672` à 17,1 % est une valeur aberrante, pas un échantillon. L'avoir prise
pour un signal a orienté une demi-journée de travail dans une direction que les
données ont ensuite fermée.

**Ce qui reste :** une minorité de tâches laisse de la place — 15 sur 51 sous
100 %, 6 sous 75 % — et la ressource utile est de les **nommer**, pas d'en faire
une moyenne.

---

# Ce qui débloquait vraiment la mesure (8 octobre)

J'ai passé une demi-journée à contourner des échecs de collecte pytest — en
épinglant `pygments 2.19.2`, puis `starlette 1.0.0`, puis en posant
`-W ignore::DeprecationWarning` sur la ligne de commande. **Chacun de ces
correctifs reproduisait un symptôme sans reproduire l'environnement.**

La vraie réponse est dans `harnais/sandbox/setup.py`, fonction
`configure_workspace_pytest_ini` : **le harnais écrit son propre `pytest.ini`
dans l'arbre de travail.**

```ini
[pytest]
addopts = --import-mode=importlib -p no:anyio
norecursedirs = .* build dist venv
python_classes = Test* *Test
python_files = test_*.py *_test.py
filterwarnings =
    ignore::DeprecationWarning
    ignore::UserWarning
```

Un `pytest.ini` à la racine **prime sur `[tool.pytest.ini_options]` de
`pyproject.toml`**. Le `filterwarnings = error` de fastapi est donc neutralisé
par construction, et ce n'est pas un contournement : c'est la condition dans
laquelle les 129 tâches ont été validées.

`--import-mode=importlib` et `-p no:anyio` comptent autant. **Mesurer ailleurs,
c'est mesurer autre chose.**

## Et les wheels ne font pas ce que je croyais

`deduplicate_wheels` **prend la version la plus haute** de chaque paquet, pas la
version d'époque. Le harnais installerait donc pygments 2.21.0 — celui-là même
qui faisait échouer `rich` chez moi avant que je l'épingle à 2.19.2.

Ce n'était donc jamais une question de version. C'était la configuration pytest.

**Leçon, et c'est la même que pour le parseur de diffs :** quand on reproduit un
environnement, on lit ce qu'il fait au lieu de deviner d'après les symptômes. Le
harnais était téléchargé depuis le matin ; j'aurais pu lire `setup.py` avant de
poser trois épinglages.

## Un écart assumé

Quand un dépôt porte déjà une section `[pytest]`, le harnais se contente
d'ajouter `addopts` et `norecursedirs` sans toucher aux `filterwarnings`. Mon
implémentation écrase toujours. L'écart va dans le sens permissif et il est noté
dans le code ; à vérifier si l'un des quatre dépôts venait à porter son propre
`pytest.ini`.

## L'environnement est une propriété du commit, pas du dépôt

**Le symptôme.** 31 des 67 tâches fastapi s'arrêtaient sur
`pytest code 2 : Interrupted: N errors during collection`. Rien n'était
exécuté, donc rien n'était mesurable.

**Trois diagnostics faux, dans l'ordre.** J'ai d'abord accusé les versions de
dépendances figées trop anciennes, puis `filterwarnings = error` que
`-W ignore` devait neutraliser, puis le `pytest.ini` que le harnais pose et
qui écrase `[tool.pytest.ini_options]`. La troisième correction a **empiré** le
résultat : 15 tâches mesurables au lieu de 18. Les trois fois, j'ai déduit la
cause du symptôme au lieu de lire la trace.

**Ce que la trace disait, en entier :**

```
docs_src/metadata/tutorial001_1_py39.py:18: app = FastAPI(
fastapi/routing.py:906: super().__init__(
E   TypeError: Router.__init__() got an unexpected keyword argument 'on_startup'
```

Rien à voir avec pytest. Le venv portait **Starlette 1.0.0** là où le commit
de base exige `starlette>=0.40.0,<0.51.0`. `APIRouter` passait `on_startup` à
un `Router` qui ne l'accepte plus.

**La cause structurelle.** J'avais un venv par dépôt, installé depuis le HEAD,
puis je plaçais l'arbre de travail sur des commits de 2023-2024. Les épingles
changent d'un commit à l'autre ; l'environnement ne changeait pas. Un venv par
dépôt ne peut pas porter 67 commits dont les contraintes se contredisent.

**Ce qui a tranché, et comment on aurait pu le voir plus tôt.** Le harnais du
concours livre **57 versions de Starlette**, de 0.19.0 à 1.6.0. Un jeu de roues
qui couvre toute la plage n'a de sens que si l'installation se fait *par tâche*.
La forme du matériel fourni portait la réponse — je l'avais sous les yeux en
téléchargeant les 124 roues, et j'en ai tiré la conclusion inverse (« ce sont
les versions d'époque qui plafonnent ma mesure »).

**La correction.** `_accorder_les_dependances()` lit `[project].dependencies`
dans le `pyproject.toml` **de l'arbre de travail**, donc du commit mesuré, et
aligne le venv avant de lancer les tests. Les épingles en place sont mémorisées
par dépôt : deux tâches consécutives aux mêmes contraintes ne relancent pas pip.

`--find-links` sans `--no-index` : les roues du concours sont des manylinux et
`pydantic_core` n'a pas de binaire Windows dedans. On privilégie le jeu local,
et on laisse pip chercher ailleurs ce qui n'y est pas installable ici.

**L'essai cadré.** Les six premières tâches bloquées à la collecte, relancées :
six mesures. `fastapi_14786` 100 %, `fastapi_14463` 100 %, `fastapi_14487`
100 %, `fastapi_14306` 95,0 %, `fastapi_14099` 51,2 %, `fastapi_14492` sans
ligne mesurable.

**La règle.** Reproduire un environnement, c'est reproduire celui du commit —
pas celui du dépôt. Et quand un diagnostic échoue deux fois, le troisième ne se
devine pas : il se lit.

## L'oracle, c'est les nœuds exigés — pas le fichier où ils habitent

**Comment c'est venu.** `requests_7433` ressortait en échec. Le plafond par test
a nommé le coupable : `TestPreparingURLs::test_different_connection_pool_for_tls_settings`,
**un** test rouge sur 337. Avant de l'accuser, j'ai regardé s'il faisait partie
de ce que le harnais exige. Il n'en fait pas partie : le `test_patch` de cette
tâche ajoute une seule fonction, `test_getattr_proxy_stream_follows_redirect`.

**Ce que le règlement dit, et que je n'avais pas suivi jusqu'au bout.** Les
nœuds requis sont « FAIL_TO_PASS, PASS_TO_PASS, **ou les fonctions extraites de
`test_patch`** ». Et `tasks.jsonl` ne porte **aucune** des deux premières
listes. Pour ce corpus, c'est donc la troisième branche qui s'applique, et je
lançais des fichiers entiers.

**Deux biais, tous les deux flatteurs.** C'est ce qui rend l'erreur
intéressante : elle ne faisait pas du bruit, elle faisait du bien.

1. **Portée gonflée.** Une ligne du correctif atteinte par un test que le
   harnais n'exige pas ne pèse pas sur le score. La compter comme contrainte
   crédite l'oracle d'une garantie qu'il ne donne pas.
2. **Tâches perdues.** Un échec sans rapport dans le même fichier disqualifie
   une tâche dont l'oracle propre fonctionne parfaitement.

**La correction.** `noeuds_exiges()` projette les lignes ajoutées du
`test_patch` sur le fichier **parsé après application** et retient toute
fonction de test dont l'étendue contient une de ces lignes. Pas un
`grep '+def test_'` : ça manquerait les tests dont le correctif ne modifie que
le corps, que le harnais exige aussi. Quand rien n'est extractible — un
`test_patch` qui ne touche que des fixtures — on retombe sur le fichier entier,
et le mode voyage dans le résultat, parce qu'un chiffre obtenu dans l'un ou
l'autre mode ne veut pas la même chose.

**Effets immédiats.** Trois tâches `requests` récupérées (100 %, 100 %, 66,7 %).
Le temps par tâche passe de 76-153 s à 3-4 s. Et la portée **baisse** :
`fastapi_15588` de 100 % (8/8) à 87,5 % (7/8), `fastapi_14851` de 98,0 % (50/51)
à 88,2 % (45/51).

**La leçon, et c'est la même que pour l'environnement.** J'avais lu le critère
du concours, je l'avais même cité mot pour mot dans la note de cadrage, et je
n'avais pas vérifié laquelle de ses trois branches s'appliquait à mes données.
Citer une règle n'est pas la suivre.

## De la portée à la contrainte, et à la démonstration

**Pourquoi la portée ne suffit pas.** Exécuter une ligne est nécessaire pour la
contraindre, pas suffisant : une ligne peut tourner sans qu'aucune assertion ne
dépende de son effet. La portée est donc une borne supérieure, et l'article le
dit — ce qui en fait l'endroit exact où un relecteur attaquera.

**L'opérateur.** `contrainte.py` remplace l'instruction par `pass` et relance
les nœuds exigés. La suppression est l'opérateur que la question demande — « cette
ligne est-elle contrainte contre son absence ? » — et le plus fort : une ligne
qui survit à sa suppression survit à toute mutation plus fine. Un seul opérateur
rend le chiffre lisible, là où un mélange produit un score dont personne ne sait
ce qu'il pèse.

**Les mutants invalides se détectent, ils ne s'énumèrent pas.** Décorateur,
en-tête `else:`, bloc rendu vide : plutôt que lister ces cas — liste qu'on
oublierait de compléter — on reparse le mutant et on écarte ce qui ne compile
pas. Compter un mutant incompilable comme « tué » gonflerait le résultat
exactement dans le sens qui arrange.

**Ce qui compte comme tué, et pourquoi c'est défendable.** Une erreur de
collecte compte comme un mutant tué. Supprimer un `import` casse le module, et
l'oracle détecte bien **cette** omission. Ce qui serait faux, c'est de compter
ainsi un mutant que Python refuse de compiler, et celui-là est écarté avant.

**Deux limites à écrire dans l'article.** Un mutant tué par un plantage est tué
parce que le code casse, pas parce qu'une assertion vérifie le comportement :
« l'omission serait vue » reste vrai, mais pas pour la bonne raison. Et
supprimer une instruction peut rendre des instructions suivantes du correctif
inatteignables, donc une mutation en teste parfois plus d'une.

**La démonstration.** Un survivant **est** déjà un correctif qui omet une ligne
du correctif officiel et que le barème accepte. Les cumuler répond à la question
suivante : *de combien peut-on s'écarter du correctif de référence sans que le
barème le voie ?* `_omettre_tout()` supprime toutes les lignes survivantes d'un
coup — de bas en haut, parce qu'une substitution décale les numéros de ce qui
suit — écarte les instructions imbriquées dans une autre déjà retenue (sinon
`cumul_lignes` compterait deux omissions pour une), reparse, et relance. Un
`cumul_passe = True` n'est pas un indicateur : c'est un correctif qu'on peut
relire.

## La correction que j'ai faite à l'envers

**Ce qui s'est passé.** Convaincu que lancer les fichiers de test entiers
gonflait la portée, j'ai restreint la mesure aux fonctions que `test_patch`
touche, relancé les 129 tâches, obtenu des chiffres plus bas (88,0 % au lieu de
92,1 %) et annoncé que la correction allait dans le bon sens — « 19 tâches en
baisse, 0 en hausse, la signature d'un biais unidirectionnel ».

**Ce que disait le harnais, que j'avais sur le disque depuis le premier jour.**
`harnais/HARNESS_README.md`, section 8.2 :

```
python3 -s -m pytest <pytest_targets> --junitxml=... -p no:anyio \
  -o timeout=0 -o python_classes="Test* *Test" -q
```

Pas de `-k`. Les cibles sont les **fichiers**, et `resolved = True` exige
`exit_code == 0` : tous les tests du fichier doivent passer. La liste
`FAIL_TO_PASS / PASS_TO_PASS / fonctions extraites` sert à la validation JUnit
**par-dessus**, pour vérifier qu'aucun nœud requis n'a été sauté. C'est une
exigence supplémentaire, pas une restriction.

**L'oracle est donc le fichier entier, et ma mesure d'origine était juste.**

**Comment je m'étais convaincu du contraire.** Un seul test rouge sans rapport
disqualifiait `requests_7433`, et j'ai conclu que mon critère était trop large.
Il était bien trop large — mais pour une autre raison : ce test échoue sur
*cette machine*, pas dans le bac à sable Linux du concours. J'ai pris un
artefact d'environnement pour un défaut de méthode, et j'ai « corrigé » la
méthode.

**La leçon, et elle est pénible parce que je venais de l'écrire.** Deux
paragraphes plus haut dans ce fichier : « citer une règle n'est pas la suivre ».
Cette fois j'avais lu le critère, choisi une de ses trois branches, et jamais
ouvert la commande qui l'applique. **Lire la règle n'est pas lire ce qui
l'exécute.** Quand les deux sont disponibles, c'est le code qui tranche.

**Ce qui se récupère, et pourquoi la passe n'est pas perdue.** La mesure
restreinte répond à une question réelle : *quelle part de la portée vient des
tests qui visent le changement, et quelle part de tests du même fichier qui n'en
parlent pas ?* Sur `fastapi_15023`, 16 lignes sur 16 contre **2 sur 16** : son
`test_patch` modifie le corps d'un seul test, et quinze autres tests du fichier
exécutent incidemment le code corrigé. Une partie de la prise du banc est donc
**incidentelle** — elle compte, puisque le critère exige que ces tests passent,
mais elle ne vient de l'intention de personne. C'est un résultat secondaire de
l'article.

**Et elle sert une deuxième fois, comme borne.** Pour 13 des 17 tâches que cette
machine ne peut pas mesurer en fichier entier, la mesure restreinte rend quand
même un chiffre, qui est une borne inférieure de leur portée réelle. Les inclure
à cette borne déplace la moyenne de 92,1 % à 92,2 % et ρ de −0,512 à −0,497.
L'effet de taille ne vit pas dans les tâches manquantes — ce qui est exactement
l'objection qu'un relecteur formulerait en premier.

**Le mode est désormais explicite.** `--selection fichier` (défaut, celui du
harnais) ou `--selection noeuds`. Le défaut n'est plus une opinion implicite
dans le code : c'est un drapeau avec la commande du harnais citée en commentaire
à côté.

**Une déviation à déclarer dans l'article.** Le harnais passe `-o timeout=0`,
donc aucun délai. J'impose 60 s par test, parce que deux tâches `requests`
pendent ici. Le drapeau n'est passé que si `pytest_timeout` est importable, et
il ne change aucun verdict — il transforme un dépassement silencieux en échec
nommé.
