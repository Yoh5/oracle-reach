"""Mesure la portée de l'oracle sur les tâches du concours, une par une.

Pour chaque tâche : un arbre de travail au `base_commit`, le correctif de
référence, le correctif de test, pytest sous couverture sur les fichiers de test
que le harnais lui-même viserait, puis l'intersection.

**Chaque échec est consigné avec sa raison.** Une tâche qui n'a pas pu tourner
ne disparaît pas du décompte : elle apparaît avec son statut. Un taux calculé
sur les seules tâches qui ont bien voulu s'exécuter mesurerait la facilité
d'installation, pas la portée d'un oracle.

Usage :
    python src/lancer_mesure.py --taches data/tasks.jsonl --sortie resultats.jsonl
    python src/lancer_mesure.py --depot Textualize/rich --limite 5
"""

from __future__ import annotations

import argparse
import ast
import json
import re
import shutil
import subprocess
import sys
import time
from dataclasses import asdict, dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from portee_oracle import couverture_depuis, mesurer  # noqa: E402

RACINE = Path(__file__).resolve().parent.parent
DEPOTS = RACINE / "repos"
TRAVAIL = RACINE / "work"

#: Le nom local du clone, par dépôt amont.
CLONE = {
    "fastapi/fastapi": "fastapi",
    "Textualize/rich": "rich",
    "psf/requests": "requests",
    "encode/httpx": "httpx",
}

CIBLE_TEST = re.compile(r"^\+\+\+ (?:b/)?(?P<nom>[^\t\n]+)", re.M)

VENVS = RACINE / "venvs"


def interprete(repo: str) -> str:
    """Le Python à utiliser pour ce dépôt.

    Ces suites ont besoin de leurs dépendances d'époque. Celle de `requests`
    lance un serveur httpbin local : sans lui, 197 tests tombent en erreur avant
    d'avoir rien exercé, et la tâche se compte comme un échec alors que c'est
    l'installation qui manquait. Un environnement par dépôt les porte sans
    toucher à l'interpréteur du poste.

    À défaut d'environnement dédié, on retombe sur l'interpréteur courant plutôt
    que d'échouer : certaines suites n'ont besoin de rien, httpx en est une.
    """
    for sous in ("Scripts/python.exe", "bin/python"):
        chemin = VENVS / CLONE[repo] / sous
        if chemin.exists():
            return str(chemin)
    return sys.executable


@dataclass
class Resultat:
    instance_id: str
    repo: str
    statut: str                 # ok | patch_refuse | tests_echoues | sans_couverture | erreur
    mesurables: int = 0
    couvertes: int = 0
    hors_mesure: int = 0
    part: float | None = None
    detail: dict | None = None
    note: str = ""
    secondes: float = 0.0
    tests_passent: bool | None = None   # séparé du statut : voir `mesurer_une`
    #: `noeuds` quand la sélection a porté sur les fonctions exigées par
    #: `test_patch`, `fichier_entier` quand aucune n'a pu être extraite. Un
    #: chiffre obtenu dans l'un ou l'autre mode ne veut pas la même chose, donc
    #: il voyage avec le résultat au lieu d'être supposé.
    mode: str = ""
    noeuds: int = 0


PYTEST_INI_DU_HARNAIS = """[pytest]
addopts = --import-mode=importlib -p no:anyio
norecursedirs = .* build dist venv
python_classes = Test* *Test
python_files = test_*.py *_test.py
filterwarnings =
    ignore::DeprecationWarning
    ignore::UserWarning
"""


def _poser_pytest_ini_du_harnais(arbre: Path) -> None:
    """Écrit le `pytest.ini` que le harnais du concours écrit lui-même.

    Copié de `harnais/sandbox/setup.py`, fonction `configure_workspace_pytest_ini`,
    dans la branche employée quand le dépôt n'a pas de section `[pytest]`.

    **C'est ce qui débloquait la mesure, et je l'approximais à la main.** fastapi
    déclare `filterwarnings = error` dans son `pyproject.toml` ; une dépendance
    moderne y lève des dépréciations et pytest s'arrête à la collecte, avant
    d'avoir exercé la moindre ligne. Un `pytest.ini` à la racine prime sur
    `[tool.pytest.ini_options]`, donc le harnais neutralise cette configuration
    par construction — et mon `-W ignore::DeprecationWarning` reproduisait le
    symptôme sans reproduire l'environnement.

    `--import-mode=importlib` et `-p no:anyio` comptent autant : ce sont les
    conditions dans lesquelles les tâches ont été validées. Mesurer ailleurs,
    c'est mesurer autre chose.

    Note sur ce que je ne reproduis pas : quand le dépôt a déjà une section
    `[pytest]`, le harnais se contente d'ajouter `addopts` et `norecursedirs`
    sans toucher aux `filterwarnings`. Ici on écrase toujours. L'écart est connu
    et il va dans le sens permissif ; il est à vérifier si un dépôt venait à
    porter son propre `pytest.ini`.
    """
    (arbre / "pytest.ini").write_text(PYTEST_INI_DU_HARNAIS, encoding="utf-8", newline=chr(10))


def avec_saut(texte: str) -> str:
    """Les 258 correctifs du jeu de données n'ont pas de saut de ligne final.

    Sans lui, `git apply` répond « corrupt patch at line N » sur chacun d'eux.
    """
    return texte if texte.endswith("\n") else texte + "\n"


def cibles_pytest(test_patch: str) -> list[str]:
    """Les fichiers de test que le harnais vise : ceux que `test_patch` touche.

    Le harnais lance `pytest <pytest_targets>` et non la suite entière, donc la
    mesure doit porter sur les mêmes fichiers. Mesurer la suite complète
    donnerait un chiffre plus flatteur et répondrait à une autre question.
    """
    return sorted({m.group("nom").strip() for m in CIBLE_TEST.finditer(test_patch)
                   if m.group("nom").strip() != "/dev/null"})


def noeuds_exiges(test_patch: str, arbre: Path) -> tuple[list[str], str]:
    """Les fonctions de test que `test_patch` introduit ou modifie.

    **Pourquoi ce raffinement existe, et pourquoi il baisse nos chiffres.**
    `cibles_pytest` rend des *fichiers*. Le critère du concours exige des
    *nœuds* : « chaque nœud de test requis (FAIL_TO_PASS, PASS_TO_PASS, ou **les
    fonctions extraites de `test_patch`**) ». Et `tasks.jsonl` ne porte aucune
    des deux premières listes — seulement `test_patch`. Les nœuds exigés sont
    donc exactement les fonctions que ce correctif de test touche.

    Lancer le fichier entier a deux effets, tous deux dans le sens qui nous
    arrange :

    - il **gonfle la portée**, parce qu'une ligne du correctif atteinte par un
      test que le harnais n'exige pas est comptée comme contrainte alors
      qu'elle ne pèse pas sur le score ;
    - il **perd des tâches**, parce qu'un échec sans rapport dans le même
      fichier disqualifie une tâche dont l'oracle propre fonctionne.
      `requests_7433` en est le cas net : un seul test rouge sur 337, nommé
      `test_different_connection_pool_for_tls_settings`, absent du `test_patch`,
      alors que la seule fonction que ce correctif ajoute est
      `test_getattr_proxy_stream_follows_redirect`.

    **Comment les nœuds sont trouvés.** On ne cherche pas `+def test_` : ça
    manquerait les tests dont `test_patch` modifie seulement le corps, que le
    harnais exige aussi. On prend les lignes que le correctif ajoute dans chaque
    fichier de test, on parse le fichier *après application*, et on retient
    toute fonction de test dont l'étendue contient une de ces lignes.

    Rend `(noms, mode)`. Quand aucun nom ne ressort — un `test_patch` qui ne
    touche que des fixtures ou des données de module — on retombe sur le fichier
    entier, et le mode le dit, parce que le chiffre ne veut alors pas la même
    chose.
    """
    from portee_oracle import lignes_ajoutees

    ajoutees = lignes_ajoutees(test_patch, garder_les_tests=True)
    noms: set[str] = set()

    for fichier, numeros in ajoutees.par_fichier.items():
        chemin = arbre / fichier
        if not chemin.exists():
            continue
        try:
            arbre_py = ast.parse(chemin.read_text(encoding="utf-8", errors="replace"))
        except SyntaxError:
            continue
        for noeud in ast.walk(arbre_py):
            if not isinstance(noeud, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            if not noeud.name.startswith("test"):
                continue
            fin = getattr(noeud, "end_lineno", noeud.lineno) or noeud.lineno
            if any(noeud.lineno <= n <= fin for n in numeros):
                noms.add(noeud.name)

    return sorted(noms), ("noeuds" if noms else "fichier_entier")


def _executer(cmd: list[str], cwd: Path, secondes: int = 600, env: dict | None = None):
    import os
    e = {**os.environ, **(env or {})}
    return subprocess.run(cmd, cwd=cwd, capture_output=True, text=True,
                          timeout=secondes, env=e, errors="replace")


ROUES = RACINE / "harnais" / "wheels"
CERTS = RACINE / "certs" / "ca-bundle.pem"

#: Le greffon `pytest-timeout` est-il importable dans le venv de ce dépôt.
_A_LE_PLAFOND: dict[str, bool] = {}


def _plafond_par_test(repo: str) -> list[str]:
    """Un plafond par test, quand le venv du dépôt sait le faire.

    **Pourquoi par test et pas seulement par tâche.** Cinq tâches `requests`
    consommaient le plafond global entier sans rendre un chiffre. En les lançant
    avec `--timeout`, la cause apparaît : `TestTimeout::test_encoded_methods`
    bloque dans `select.select` contre le serveur `pytest-httpbin` local. Un
    seul test pendu emportait la suite entière, et le journal ne disait que
    « délai dépassé ».

    Un plafond par test change le coût et le diagnostic : 60 secondes au lieu
    de 300, et le nom du test dans la note au lieu d'un silence. Il ne rend pas
    ces tâches mesurables — un test tué reste un test qui échoue — mais il dit
    **pourquoi** elles ne le sont pas, ce qui est la différence entre une limite
    déclarée et un trou.

    Le drapeau n'est passé que si le greffon est là. Il n'est pas dans les roues
    du concours : `fastapi` et `requests` l'ont par leurs propres dépendances de
    test, `rich` non, et une option inconnue ferait sortir pytest en erreur
    d'usage — ce qui transformerait un dépôt qui mesure très bien en dépôt qui
    ne mesure plus rien.
    """
    if repo not in _A_LE_PLAFOND:
        sonde = _executer([interprete(repo), "-c", "import pytest_timeout"], RACINE, 60)
        _A_LE_PLAFOND[repo] = sonde.returncode == 0
    return ["--timeout", "60"] if _A_LE_PLAFOND[repo] else []

#: Les épingles déjà en place dans le venv de chaque dépôt, pour ne pas
#: relancer pip quand deux tâches consécutives exigent la même chose.
_EPINGLES_EN_PLACE: dict[str, tuple[str, ...]] = {}


def _dependances_du_commit(arbre: Path) -> tuple[str, ...]:
    """Les dépendances d'exécution déclarées par le commit de base lui-même.

    Lues dans l'arbre de travail, pas dans le dépôt : c'est tout le point. Les
    épingles changent d'un commit à l'autre, et c'est celles du commit mesuré
    qui font foi.
    """
    import tomllib

    fichier = arbre / "pyproject.toml"
    if not fichier.exists():
        return ()
    try:
        projet = tomllib.loads(fichier.read_text(encoding="utf-8")).get("project", {})
    except tomllib.TOMLDecodeError:
        return ()
    return tuple(projet.get("dependencies", ()))


def _accorder_les_dependances(repo: str, arbre: Path) -> str | None:
    """Aligne le venv du dépôt sur les épingles du commit mesuré.

    **Pourquoi ce pas existe.** Un venv par dépôt installé depuis le HEAD, puis
    un arbre de travail placé sur un commit de 2024, donne un environnement que
    ce commit interdit. Sur `fastapi_14492` le venv portait Starlette 1.0.0 là
    où le commit exige `>=0.40.0,<0.51.0` : `APIRouter.__init__` passait
    `on_startup` à un `Router` qui ne l'accepte plus, et la collecte
    s'interrompait avant d'exécuter une ligne. La tâche se comptait comme un
    échec de test, ce qu'elle n'était pas.

    J'ai d'abord cru à un problème de configuration pytest, puis de versions
    figées, et corrigé deux fois à côté. Ce qui a tranché, c'est de lire la
    trace en entier : le harnais du concours livre **57 versions de Starlette**,
    de 0.19 à 1.6. Un jeu de roues qui couvre toute la plage n'a de sens que si
    l'installation se fait **par tâche**. La forme du harnais disait la réponse.

    `--find-links` sans `--no-index` : les roues du concours sont des
    manylinux, et `pydantic_core` n'a pas de binaire Windows dedans. On
    privilégie le jeu local et on laisse pip chercher ailleurs ce qui n'y est
    pas installable ici, plutôt que d'échouer sur une roue d'une autre
    plate-forme.
    """
    specs = _dependances_du_commit(arbre)
    if not specs or _EPINGLES_EN_PLACE.get(repo) == specs:
        return None

    # `--retries 1 --timeout 20` : `requests_7328` a tourné **75 minutes**, bien
    # au-delà des deux plafonds de 900 s cumulés. C'est pip qui réessayait
    # derrière l'interception TLS d'Avast, chaque dépendance absente du jeu
    # local relançant sa propre série. Une roue qu'on ne trouve pas en 20
    # secondes ne se trouvera pas en vingt minutes.
    cmd = [interprete(repo), "-m", "pip", "install", "-q",
           "--disable-pip-version-check", "--only-binary", ":all:",
           "--retries", "1", "--timeout", "20",
           "--find-links", str(ROUES), *specs]
    env = {"PIP_CERT": str(CERTS)} if CERTS.exists() else {}
    res = _executer(cmd, arbre, 300, env)
    if res.returncode != 0:
        # Pas un abandon : la tâche garde sa chance, et la note dira pourquoi
        # un chiffre manque s'il manque.
        return f"pip {res.returncode} : {(res.stderr or res.stdout).strip()[-200:]}"
    _EPINGLES_EN_PLACE[repo] = specs
    return None


def mesurer_une(tache: dict, *, garder: bool = False,
                selection_voulue: str = "fichier") -> Resultat:
    depart = time.time()
    iid, repo = tache["instance_id"], tache["repo"]
    r = lambda **kw: Resultat(iid, repo, secondes=round(time.time() - depart, 1), **kw)

    clone = DEPOTS / CLONE[repo]
    arbre = TRAVAIL / iid
    diffs = TRAVAIL / f"{iid}.diffs"
    diffs.mkdir(parents=True, exist_ok=True)
    p_ref = diffs / "patch.diff"
    p_test = diffs / "test.diff"
    p_ref.write_text(avec_saut(tache["patch"]), encoding="utf-8", newline="\n")
    p_test.write_text(avec_saut(tache["test_patch"]), encoding="utf-8", newline="\n")

    try:
        # Un arbre laissé par une passe interrompue bloque la suivante :
        # `fastapi_14262` est tombée là-dessus après l'arrêt de la session.
        # `worktree remove` échoue si le dossier est déjà parti ou si git a
        # perdu son enregistrement, donc on nettoie des deux côtés — le
        # registre par `prune`, le disque par `rmtree` — avant de rajouter.
        if arbre.exists():
            _executer(["git", "worktree", "remove", "--force", str(arbre)], clone, 120)
            shutil.rmtree(arbre, ignore_errors=True)
        # `unlock` avant `prune`, parce que `prune` saute les arbres verrouillés.
        # `fastapi_14262` a échoué deux fois là-dessus : « missing but locked
        # worktree ». Le dossier avait disparu, l'enregistrement restait, et le
        # verrou empêchait de le nettoyer. Le message de git nommait le remède
        # — « use 'add -f -f' to override, or 'unlock' and 'prune' » — ce qu'on
        # ne voit qu'en lisant l'erreur en entier plutôt que son premier mot.
        _executer(["git", "worktree", "unlock", str(arbre)], clone, 120)
        _executer(["git", "worktree", "prune"], clone, 120)
        a = _executer(["git", "worktree", "add", "-q", "--detach",
                       str(arbre), tache["base_commit"]], clone, 300)
        if a.returncode != 0:
            return r(statut="erreur", note=f"worktree: {a.stderr.strip()[:160]}")

        for nom, chemin in (("reference", p_ref), ("test", p_test)):
            ap = _executer(["git", "apply", str(chemin)], arbre, 180)
            if ap.returncode != 0:
                return r(statut="patch_refuse", note=f"{nom}: {ap.stderr.strip()[:160]}")

        cibles = cibles_pytest(tache["test_patch"])
        if not cibles:
            return r(statut="erreur", note="aucun fichier de test dans test_patch")

        env = {"PYTHONPATH": "src", "PYTHONDONTWRITEBYTECODE": "1"}
        # Critère retenu : **une tâche ne compte que si ses tests passent.**
        #
        # J'avais d'abord séparé « les tests passent » du statut, pour ne pas
        # perdre une tâche sur un avertissement de dépréciation. C'était trop
        # grossier : une collecte interrompue n'exécute rien, et la tâche
        # ressortait à 0 % avec le statut `ok` — lue comme « l'oracle ne
        # contraint rien » alors que la mesure n'avait pas eu lieu. 22 des 45
        # premières tâches fastapi sont tombées dans ce trou.
        #
        # Même un échec franc rend la couverture douteuse : un test qui casse
        # avant d'atteindre le correctif produit un 0 % qui ne dit rien de
        # l'oracle. Le coût est de l'échantillon, et c'est le bon échange : un
        # chiffre sur moins de tâches vaut mieux qu'un chiffre faux sur toutes.
        #
        # `-W ignore::DeprecationWarning` : ces dépôts configurent pytest en
        # `filterwarnings = error`, et une dépendance moderne y déclenche des
        # dépréciations que le code d'époque ignorait. Le test s'arrête alors à
        # la collecte, avant d'avoir exercé la moindre ligne.
        #
        # La mesure a besoin que les tests **s'exécutent**, pas qu'ils
        # **passent** : un avertissement venu d'une version récente ne change
        # pas quelles lignes le test traverse. Le résultat du test est donc
        # consigné à part, dans `tests_passent`, et n'écarte plus la tâche.
        _poser_pytest_ini_du_harnais(arbre)
        souci_pip = _accorder_les_dependances(repo, arbre)

        # Restreindre aux noeuds que `test_patch` introduit ou modifie, parce
        # que ce sont eux que le harnais exige. Voir `noeuds_exiges` : lancer le
        # fichier entier gonflait la portee et perdait des taches sur des echecs
        # sans rapport.
        # Le harnais lance `pytest <pytest_targets>` sur les **fichiers**, sans
        # `-k`, et exige `exit_code == 0` : tous les tests du fichier doivent
        # passer. La liste FAIL_TO_PASS / PASS_TO_PASS / fonctions extraites
        # sert a la validation JUnit **par-dessus**, pour verifier qu'aucun
        # noeud requis n'a ete saute. C'est une exigence supplementaire, pas une
        # restriction — verifie dans `harnais/HARNESS_README.md` section 8.2.
        #
        # J'avais pris l'inverse pendant une passe entiere, en choisissant une
        # branche du critere sans lire la commande qui l'applique, alors qu'elle
        # etait dans un fichier de ce depot. Le mode par defaut est donc celui
        # du harnais, et l'autre s'opte explicitement.
        #
        # `--selection noeuds` reste utile, pour une autre question : quelle
        # part de la portee vient des tests qui visent le changement, et quelle
        # part vient de tests du meme fichier qui n'en parlent pas. Sur
        # `fastapi_15023`, 16 lignes sur 16 contre 2 sur 16.
        noms, mode = ([], "fichier_entier")
        if selection_voulue == "noeuds":
            noms, mode = noeuds_exiges(tache["test_patch"], arbre)
        selection = ["-k", " or ".join(noms)] if noms else []
        env["COVERAGE_FILE"] = str(arbre / ".coverage")
        t = _executer([interprete(repo), "-m", "coverage", "run",
                       f"--rcfile={RACINE / 'mesure.coveragerc'}", "--source=.",
                       "-m", "pytest", *cibles, "-q", "-p", "no:cacheprovider",
                       *selection, *_plafond_par_test(repo),
                       "-W", "ignore::DeprecationWarning",
                       "-W", "ignore::PendingDeprecationWarning"],
                      # 300 s et non 900 : les suites qui mesurent tournent en
                      # 5 à 13 secondes. Les cinq tâches `requests` qui
                      # dépassent **pendent** — elles ne calculent pas lentement
                      # — et attendre quinze minutes chacune coûtait 75 minutes
                      # par passe sans rien rendre. 300 s laisse 25× la marge
                      # de la suite la plus lente observée.
                      arbre, 300, env)
        # Codes de sortie de pytest : 0 tout passe, 1 des tests ont échoué,
        # 2 interrompu (erreur de collecte), 4 erreur d'usage, 5 rien collecté.
        #
        # La distinction décide de la validité du chiffre. « Des tests ont
        # échoué » laisse une mesure exploitable : les tests ont tourné, les
        # lignes ont été traversées. « Interrompu à la collecte » n'en laisse
        # aucune : rien n'a été exécuté, la couverture est vide, et la tâche
        # ressortait à **0 %** avec le statut `ok` — lue comme « l'oracle ne
        # contraint rien » alors que c'est la mesure qui n'a pas eu lieu.
        #
        # Quatre tâches fastapi ont été enregistrées ainsi avant que ce soit vu.
        if t.returncode != 0:
            queue = " | ".join(x[:70] for x in (t.stdout or t.stderr).strip().splitlines()[-2:])
            # Si l'accord des dépendances a échoué, c'est l'explication la
            # plus probable de l'échec et elle doit voyager avec le résultat :
            # sans ça on relit « pytest code 2 » et on rediagnostique à vide.
            if souci_pip:
                queue = f"{souci_pip} || {queue}"
            return r(statut="tests_echoues", tests_passent=False, mode=mode,
                     noeuds=len(noms), note=f"pytest code {t.returncode} : {queue}")

        passent = True
        queue = " | ".join(x[:70] for x in (t.stdout or t.stderr).strip().splitlines()[-2:])

        fichier = arbre / ".coverage"
        if not fichier.exists():
            # Sans couverture, l'échec des tests est la seule explication utile.
            return r(statut="tests_echoues" if not passent else "sans_couverture",
                     tests_passent=passent, note=queue if not passent else "coverage n'a rien ecrit")

        exec_, mes = couverture_depuis(fichier, arbre)
        # Le correctif est déjà en mémoire : le relire depuis le disque
        # ajoutait une fenêtre où un nettoyage concurrent — ou l'antivirus —
        # pouvait le faire disparaître entre l'écriture et la lecture.
        p = mesurer(iid, avec_saut(tache["patch"]), exec_, mes, racine=arbre)
        return r(statut="ok", mode=mode, noeuds=len(noms),
                 mesurables=p.mesurables, couvertes=p.couvertes,
                 hors_mesure=p.hors_mesure, part=p.part_couverte, detail=p.detail,
                 tests_passent=passent, note="" if passent else "mesure malgre " + queue[:90])

    except subprocess.TimeoutExpired:
        return r(statut="erreur", note="delai depasse")
    except Exception as e:  # noqa: BLE001
        return r(statut="erreur", note=f"{type(e).__name__}: {str(e)[:140]}")
    finally:
        if not garder:
            _executer(["git", "worktree", "remove", "--force", str(arbre)], clone, 120)
            shutil.rmtree(diffs, ignore_errors=True)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--taches", default=str(RACINE / "data/tasks.jsonl"))
    ap.add_argument("--sortie", default=str(RACINE / "data/resultats.jsonl"))
    ap.add_argument("--depot", default=None, help="n'en traiter qu'un, ex: Textualize/rich")
    ap.add_argument("--limite", type=int, default=None)
    ap.add_argument("--garder", action="store_true", help="ne pas supprimer les arbres")
    ap.add_argument("--selection", choices=("fichier", "noeuds"), default="fichier",
                    help="fichier = ce que fait le harnais (defaut) ; "
                         "noeuds = seulement les tests que test_patch touche")
    args = ap.parse_args()

    taches = [json.loads(l) for l in open(args.taches, encoding="utf-8")]
    if args.depot:
        taches = [t for t in taches if t["repo"] == args.depot]
    if args.limite:
        taches = taches[: args.limite]

    TRAVAIL.mkdir(exist_ok=True)
    sortie = Path(args.sortie)
    deja = set()
    if sortie.exists():
        deja = {json.loads(l)["instance_id"] for l in sortie.open(encoding="utf-8")}
        print(f"{len(deja)} deja mesurees, elles sont sautees", flush=True)

    with sortie.open("a", encoding="utf-8") as f:
        for i, t in enumerate(taches, 1):
            if t["instance_id"] in deja:
                continue
            res = mesurer_une(t, garder=args.garder,
                              selection_voulue=args.selection)
            f.write(json.dumps(asdict(res), ensure_ascii=False) + "\n")
            f.flush()  # ligne par ligne : une interruption ne perd pas le travail
            part = "    -" if res.part is None else f"{res.part:5.1%}"
            print(f"[{i:3}/{len(taches)}] {res.instance_id:22} {res.statut:15} "
                  f"{part}  {res.couvertes:3}/{res.mesurables:<3} {res.secondes:5.1f}s"
                  f"{'  ' + res.note if res.note else ''}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
