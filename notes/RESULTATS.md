# Ce que la mesure rend

Relevé du 9 octobre 2026.

**Mesure principale : `data/fichier-entier/resultats_accordes.jsonl`** — la
commande du harnais, c'est-à-dire `pytest` sur les **fichiers** cibles entiers.
**Mesure secondaire : `data/resultats_noeuds.jsonl`** — restreinte aux tests que
`test_patch` touche, qui répond à une autre question (§ « D'où vient la portée »).

> **J'ai inversé ces deux rôles pendant une passe entière.** Croyant corriger un
> biais, j'ai pris les *nœuds* pour la mesure principale, publié des chiffres
> plus bas, et annoncé que la correction allait dans le bon sens. Le
> `HARNESS_README` était sur le disque depuis le début : section 8.2, la commande
> est `pytest <pytest_targets>` sans `-k`, et `resolved` exige `exit_code == 0`,
> donc **tous** les tests du fichier. La liste `FAIL_TO_PASS / PASS_TO_PASS /
> fonctions extraites` sert à la validation JUnit **par-dessus**, pour vérifier
> qu'aucun nœud requis n'a été sauté. Détail dans `METHODE.md`.

## L'assiette

| | |
|---|---|
| tâches du corpus | 129 |
| mesurées | 112 |
| portée définie, donc exploitables | **100** |
| portée **indéfinie** | 12 sur 112 (10,7 %) |

La portée indéfinie n'est pas une portée nulle : le correctif ne modifie que des
lignes qu'aucune instruction ne porte — une valeur au milieu d'un appel
multi-ligne, par exemple. Ces tâches sont exclues de la moyenne, et l'analyseur
les nomme au lieu de les écarter en silence.

## Les deux agrégats, et leur écart

| | |
|---|---|
| moyenne par tâche | **92,1 %** |
| lignes couvertes / lignes mesurables | **1671 / 2004 = 83,4 %** |
| tâches à 100 % | 67 / 100 |

**L'écart de 9 points entre les deux est le résultat.** La moyenne par tâche
traite un correctif de 2 lignes comme un de 200. La part pondérée ne le fait pas.
Quand elles divergent à ce point, c'est que la couverture dépend de la taille.

## L'hypothèse qui survit : la portée se dégrade avec la taille

| taille du correctif | n | moyenne | lignes | à 100 % |
|---|---|---|---|---|
| 1-2 lignes | 28 | **98,2 %** | 39/40 | 27/28 |
| 3-5 lignes | 19 | 93,2 % | 70/75 | 14/19 |
| 6-10 lignes | 21 | 91,7 % | 145/158 | 16/21 |
| 11-25 lignes | 14 | 95,7 % | 209/218 | 9/14 |
| 26-75 lignes | 12 | **79,1 %** | 451/569 | 1/12 |
| 76+ lignes | 6 | **79,4 %** | 757/944 | **0/6** |

Spearman **ρ = −0,512** sur n = 100 (t = −5,90).

### Confondant 1 : le dépôt

| dépôt | n | ρ | t | médiane |
|---|---|---|---|---|
| fastapi | 59 | −0,551 | −4,98 | 6 |
| rich | 36 | −0,389 | −2,46 | 6 |

Même signe, même médiane de part et d'autre. Ce n'est pas un effet de dépôt.

### Confondant 2 : les tâches non mesurées

Dix-sept tâches échouent à leur oracle sur cette machine, et les écarter pourrait
flatter le résultat. Pour 13 d'entre elles, la mesure restreinte rend quand même
un chiffre, qui est une **borne inférieure** de leur portée réelle (elle n'utilise
qu'une partie de l'oracle).

| | n | moyenne | pondérée | ρ | t |
|---|---|---|---|---|---|
| principale | 100 | 92,1 % | 83,4 % | −0,512 | −5,90 |
| **+ les 13 bornes inférieures** | **113** | **92,2 %** | 83,8 % | **−0,497** | **−6,03** |

La moyenne bouge de 0,1 point. **L'effet ne vit pas dans les tâches manquantes.**

### Ce que l'effet n'est pas : une loi

`fastapi_14262` ajoute 109 lignes mesurables et atteint 93,6 %. Il existe de
grands correctifs bien contraints. La formulation à tenir est « la portée se
dégrade avec la taille », jamais « les gros correctifs ne sont pas testés ».

## Pourquoi ça compte

**L'hypothèse de départ est réfutée.** Je cherchais des oracles faibles ; à
92,1 % de moyenne, ils ne sont pas faibles.

**Mais la moyenne est portée par les correctifs minuscules.** La médiane du
corpus est de **6 lignes mesurables**, et 28 des 100 tâches en font 1 ou 2 — là
où n'importe quel test qui traverse la fonction rend 100 % sans rien contraindre
de particulier. Vingt-sept de ces 28 sont à 100 %.

**Là où ça pèse, l'oracle lâche.** Les 18 correctifs de 26 lignes et plus portent
**75,5 % des lignes du corpus** (1513 sur 2004) et n'atteignent que **79,8 %**.
Aucun des 6 correctifs de 76 lignes et plus n'est entièrement contraint.

Formulation à tenir : **un score de banc est le plus fiable là où la tâche est la
plus facile, et le moins fiable là où elle est substantielle.**

## D'où vient la portée : la part incidentale

L'oracle étant le fichier entier, une ligne du correctif compte comme atteinte
même quand le seul test qui la traverse n'a rien à voir avec le changement. La
mesure restreinte aux tests que `test_patch` touche sépare les deux.

| | mesurées | exploitables | moyenne | pondérée |
|---|---|---|---|---|
| commande du harnais (fichiers entiers) | 112 | 100 | 92,1 % | 83,4 % |
| tests visant le changement seulement | 126 | 113 | 88,0 % | 77,6 % |

À assiette constante sur les 100 tâches communes : **−4,8 points, 19 tâches en
baisse, 0 en hausse.** Les cas individuels sont bien plus tranchés :

| tâche | fichiers entiers | tests visant le changement |
|---|---|---|
| `fastapi_15023` | 16/16 = 100 % | **2/16 = 12,5 %** |
| `rich_3905` | 4/4 = 100 % | 1/4 = 25,0 % |
| `rich_3772` | 16/19 = 84,2 % | 6/19 = 31,6 % |
| `fastapi_14609` | 90/107 = 84,1 % | 58/107 = 54,2 % |

`fastapi_15023` est le cas net : son `test_patch` modifie le corps d'**un seul**
test existant, et quinze autres tests du même fichier exécutent incidemment le
code corrigé.

Donc une partie de la prise du banc est réelle mais **incidentelle**. Elle compte
— le critère exige que ces tests passent — mais elle ne vient pas de quelqu'un
qui a décidé de vérifier ce changement. Pour un consommateur de banc, la
distinction compte : une couverture incidentelle est un accident de rangement des
fichiers, et elle ne survivra pas à un remaniement qui déplace les tests.

## Nature des lignes jamais exécutées

| | | |
|---|---|---|
| autre | 138 | 42,3 % |
| import | 55 | 16,9 % |
| définition | 41 | 12,6 % |
| sortie anticipée | 32 | 9,8 % |
| garde / condition | 28 | 8,6 % |
| levée d'erreur | 18 | 5,5 % |
| boucle | 7 | 2,1 % |
| capture d'erreur | 7 | 2,1 % |

**Deuxième hypothèse réfutée :** je m'attendais à du traitement d'erreur. Les
levées et captures font **7,6 %** à elles deux. Ce qui échappe à l'oracle, c'est
du code ordinaire.

À comparer avec la nature des lignes **exécutées mais libres** (mesure de
contrainte, en cours) : sur `fastapi_15661`, les quatre survivants sont tous des
gardes d'erreur. L'oracle traverse la garde et ne l'éprouve pas.

## Les trois hypothèses mortes, nommées

Elles sont ici pour que l'article ne les ressuscite pas, et parce qu'une
hypothèse réfutée publiée vaut mieux qu'une hypothèse tue.

1. **« Les oracles sont faibles. »** Non : 92,1 % de moyenne, 67 tâches sur 100
   entièrement contraintes.
2. **« Les lignes non atteintes sont du traitement d'erreur. »** Non : 7,6 %.
3. **« Des fichiers entiers du correctif ne sont jamais chargés. »** Non : 1 sur
   66 lors du premier relevé.

Ce qui reste debout est la quatrième, que je ne cherchais pas : **la portée
dépend de la taille**, et elle le fait assez fort pour qu'on la mesure dans
chaque dépôt séparément et qu'elle survive à l'inclusion des tâches manquantes.

---

# La contrainte : de la portée à ce que l'oracle tient vraiment

Passe du 9 octobre 2026, `data/contrainte.jsonl`, 129 tâches traitées.
100 exploitables, 17 oracles rouges, 12 sans ligne à muter.

**1 575 mutants valides** (96 écartés : incompilables, ou sans effet
observable), **221 survivants**.

| | moyenne | médiane |
|---|---|---|
| portée — lignes exécutées | 92,1 % | 100 % |
| parmi elles, tuées par suppression | 86,1 % | 100 % |
| **contrainte effective** | **80,2 %** | 92,6 % |

Pondéré : **1 437 / 2 004 = 71,7 %**. Entièrement contraintes : **49 tâches sur
100**, contre 67 par la portée seule. La portée surestime donc de **douze
points** et de **dix-huit tâches**.

Deux tâches ont une portée de 100 % et une contrainte de **0 %** :
`fastapi_14794` et `rich_3944` exécutent chaque ligne qu'elles ajoutent et
l'oracle n'en distingue aucune de son absence.

## Le test qui justifiait toute la mesure

Si la dégradation ne vivait que dans la couverture, le résultat principal était
un artefact.

| | ρ | t | n |
|---|---|---|---|
| portée | −0,512 | −5,90 | 100 |
| **contrainte effective** | **−0,429** | **−4,70** | 100 |

Elle survit, et tient dans chaque dépôt : fastapi −0,432 (n = 59), rich −0,365
(n = 36).

| taille | n | portée | tuées | **effective** |
|---|---|---|---|---|
| 1-2 | 28 | 98,2 % | 91,1 % | **89,3 %** |
| 3-5 | 19 | 93,2 % | 83,3 % | 79,9 % |
| 6-10 | 21 | 91,7 % | 85,6 % | 78,6 % |
| 11-25 | 14 | 95,7 % | 86,9 % | 83,6 % |
| 26-75 | 12 | 79,1 % | 79,0 % | **64,8 %** |
| 76+ | 6 | 79,4 % | 84,9 % | **68,0 %** |

Le plancher est plus bas que la portée le laissait croire : **un tiers d'un gros
correctif de référence n'est contraint par rien.**

## Deux résultats non cherchés

**Le cumul passe 40 fois sur 47.** Supprimer d'un coup toutes les lignes libres
d'une tâche est accepté par le barème dans **40 des 47 tâches à survivants**, de
une ligne omise jusqu'à **vingt-deux**. Les sept exceptions sont les grosses :
les lignes libres une à une interagissent quand toutes disparaissent. L'effet de
taille revient par l'autre bout.

**Seize tâches n'ont que des ajouts purs comme survivants, et quinze acceptent
le cumul.** Pour celles-là, « le correctif officiel moins k lignes est compté
comme résolu » est exact au mot. Sur l'ensemble, **68,3 % des survivants sont
des remplacements**, donc la formulation générale doit rester « diffère de la
référence en k instructions ».

## Les survivants ne sont pas la même espèce que les non atteintes

| | jamais exécutées | **exécutées mais libres** |
|---|---|---|
| garde / condition | 8,6 % | **33,9 %** |
| import | 16,9 % | 7,7 % |
| définition | 12,6 % | 4,1 % |
| sortie anticipée | 9,8 % | 11,8 % |
| levée d'erreur | 5,5 % | 1,4 % |
| autre | 42,3 % | 38,9 % |

**Les gardes passent de 8,6 % à 33,9 % — un facteur 4.** Ce qui échappe à la
couverture est du code ordinaire ; ce qui tourne sans être contraint, ce sont
des gardes. L'oracle traverse la condition et ne l'éprouve jamais. Les imports
font le trajet inverse (16,9 % → 7,7 %), ce qui est cohérent : un import non
exécuté est libre, un import exécuté casse le module quand on le retire.

Cette table n'est apparue qu'après correction d'un bug : `texte_des_lignes` rend
des paires `(fichier, texte)` et je les déballais à l'envers, donc je
catégorisais des noms de fichiers — « autre 100 % ». **Le cent pour cent était
le signal** : une vraie distribution ne tombe jamais dans un seul seau.

## Le transfert sur SWE-bench Verified n'a pas abouti

Cinq causes corrigées, zéro instance mesurée. Couches de référence absentes ;
pytest du jour contre le conftest du commit ; Python 3.12 contre des retraits du
langage (`collections.MutableMapping` en 3.10, `inspect.formatargspec` en 3.11) ;
`urllib` sans `User-Agent` renvoyé en 403 ; et des délais pip trop serrés dont
le message d'erreur **mentait** — « Could not find a version that satisfies the
requirement astroid<2.7,>=2.6.0 » était un dépassement de lecture derrière
l'interception TLS.

La sixième cause est un échec de construction PEP 517, et il y en aurait une
septième. SWE-bench livre **une image par instance** exactement pour ça.
Déclaré comme limite dans l'article plutôt que publié sur les trois instances
qui s'installaient — ce qui aurait été un biais de sélection déguisé en
généralisation.
