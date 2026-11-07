"""La même mesure sur un autre banc, avec un oracle qui ne se devine pas.

**Pourquoi ce module existe.** Le barème du Paper Track définit *Quality* comme
la généralisation : « how general and universal is the Submission approach
beyond the competition ». Une mesure faite sur 129 tâches et quatre
bibliothèques Python ne répond pas à ça. Celle-ci la refait sur **SWE-bench
Verified**, un corpus indépendant, et répond à trois questions que le corpus du
concours ne peut pas trancher.

**1. L'oracle y est explicitement spécifié.** Chaque instance porte
`FAIL_TO_PASS` et `PASS_TO_PASS`, des identifiants de nœuds pytest complets. Il
n'y a donc rien à extraire ni à deviner — et c'est précisément l'ambiguïté qui
m'a fait corriger la mesure du concours dans le mauvais sens pendant une passe
entière. Ici, le doute n'existe pas : l'oracle est la liste.

**2. La difficulté est notée par des humains.** Le champ `difficulty` classe
chaque instance en « <15 min fix », « 15 min - 1 hour », « 1-4 hours ». Si la
portée se dégrade aussi avec cette note, alors le résultat ne dépend plus de mon
compte de lignes : deux mesures indépendantes de la substantialité d'une tâche
concordent, et l'effet n'est plus un artefact du proxy.

**3. Quatre dépôts de plus.** `pytest`, `pylint`, `requests`, `flask`.

**Ce qui est écarté, et pourquoi.** `django` fournit 231 des 500 instances mais
lance ses tests par `tests/runtests.py`, pas par pytest : mon outil ne sait pas
le mesurer, et prétendre le contraire serait pire que l'omettre. `sympy`,
`matplotlib`, `scikit-learn`, `astropy`, `xarray` demandent des compilations que
cette machine ne mène pas à bien. Restent 38 instances purement Python et
pytest, et le biais de cette sélection est à déclarer : ce sont les dépôts les
plus légers, donc probablement les mieux outillés.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
from dataclasses import asdict, dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from lancer_mesure import (  # noqa: E402
    CERTS,
    PYTEST_INI_DU_HARNAIS,
    RACINE,
    _executer,
    avec_saut,
)
from portee_oracle import couverture_depuis, mesurer  # noqa: E402

DEPOTS_SWE = RACINE / "repos_swe"
VENVS_SWE = RACINE / "venvs_swe"
TRAVAIL = RACINE / "work"

#: Le nom local du clone, par dépôt amont.
CLONE = {
    "pytest-dev/pytest": "pytest",
    "pylint-dev/pylint": "pylint",
    "psf/requests": "requests",
    "pallets/flask": "flask",
}


#: Les reglages reseau de pip pour ce transfert.
#:
#: **Pourquoi ils sont larges ici et serres ailleurs.** Sur le corpus principal
#: tout vient d'un dossier de roues local, donc `--retries 1 --timeout 30`
#: protege d'un pip qui pend — il avait coute 75 minutes sur une tache. Ici il
#: n'y a aucune roue locale : chaque dependance traverse PyPI a travers
#: l'interception TLS d'Avast, les lectures expirent a repetition, et pip
#: abandonne au deuxieme essai en annoncant « Could not find a version that
#: satisfies the requirement astroid<2.7,>=2.6.0 ».
#:
#: Ce message ressemble a une resolution impossible et c'est un probleme de
#: reseau. Dix-neuf instances sur dix-neuf sont tombees dessus avant que je lise
#: l'erreur en entier plutot que sa derniere ligne.
#:
#: `PIP_CERT` sur le bundle qui contient la racine Avast reste indispensable :
#: sans lui, c'est un `CERTIFICATE_VERIFY_FAILED` au lieu d'un delai.
RESEAU = ("--retries", "5", "--timeout", "120")


#: Où les dépôts déclarent leurs dépendances de test, par ordre de préférence.
#:
#: Les verrous épinglés d'abord (`*.txt` produit par pip-compile), parce qu'ils
#: portent les versions exactes de l'époque ; les `.in` et les extras ensuite,
#: qui laissent pip choisir et donc ramènent du moderne.
FICHIERS_DE_TEST = (
    "requirements/tests.txt",
    "requirements_test_min.txt",
    "requirements_test.txt",
    "requirements-dev.txt",
    "requirements/dev.txt",
    "testing/requirements.txt",
    "test-requirements.txt",
    "tests/requirements.txt",
    "requirements/tests.in",
)

EXTRAS_DE_TEST = ("tests", "test", "testing", "dev")


def _poser_les_dependances_de_test(py: str, arbre: Path, pip_env: dict) -> str:
    """Installe ce que **le commit** déclare pour ses tests, et dit quoi.

    **Le cas qui a imposé ça.** `pallets__flask-5014` sortait avec 60 erreurs :
    `module '_pytest.monkeypatch' has no attribute 'notset'`. Le conftest de ce
    commit utilise un attribut privé que pytest a retiré depuis. J'installais le
    pytest du jour là où le commit a besoin du pytest de son époque — la même
    erreur que sur le corpus principal, où un venv par dépôt ne pouvait pas
    porter 67 commits aux contraintes contradictoires.

    Un verrou `requirements/tests.txt` produit par pip-compile porte ces
    versions exactes. On le préfère donc à un extra, qui laisserait pip résoudre
    au plus récent et reproduirait exactement la panne.

    Rend une note, vide si tout s'est bien passé. On n'abandonne pas sur échec :
    l'instance garde sa chance, et la note dira pourquoi un chiffre manque.
    """
    for relatif in FICHIERS_DE_TEST:
        if (arbre / relatif).exists():
            fait = _executer([py, "-m", "pip", "install", "-q",
                              "--disable-pip-version-check", *RESEAU,
                              "-r", relatif], arbre, 900, pip_env)
            if fait.returncode == 0:
                return ""
            return (f"pip -r {relatif} [{fait.returncode}] "
                    f"{(fait.stderr or fait.stdout).strip()[-110:]}")

    for extra in EXTRAS_DE_TEST:
        fait = _executer([py, "-m", "pip", "install", "-q",
                          "--disable-pip-version-check", *RESEAU,
                          "-e", f".[{extra}]"], arbre, 900, pip_env)
        if fait.returncode == 0:
            return ""

    return "aucune dependance de test declaree au commit"


@dataclass
class Resultat:
    instance_id: str
    repo: str
    statut: str
    difficulte: str = ""
    #: Nombre de nœuds de l'oracle, qui est ici donné et non déduit.
    noeuds: int = 0
    mesurables: int = 0
    couvertes: int = 0
    hors_mesure: int = 0
    part: float | None = None
    note: str = ""
    secondes: float = 0.0


def interprete(nom: str) -> str:
    chemin = VENVS_SWE / nom / "Scripts" / "python.exe"
    if chemin.exists():
        return str(chemin)
    chemin = VENVS_SWE / nom / "bin" / "python"
    return str(chemin) if chemin.exists() else sys.executable


def base_python() -> str:
    """L'interpréteur sur lequel bâtir les environnements du transfert.

    **Python 3.12 ne peut pas mesurer ce corpus.** Trois incompatibilités de
    langage, et non de dépendance, l'ont montré instance par instance :

    - `psf__requests-1142` (2013) embarque un urllib3 qui fait
      `from collections import MutableMapping`, retiré du langage en 3.10 ;
    - `pylint-dev__pylint-4661` (2021) tire un `wrapt` qui fait
      `from inspect import formatargspec`, retiré en 3.11 ;
    - `pallets__flask-5014` s'en sort mieux mais hérite d'un Werkzeug moderne
      que son `pyproject` autorise sans l'avoir testé.

    Aucun chemin d'import ne rattrape une fonction que le langage a supprimée,
    et c'est précisément pourquoi le harnais officiel de SWE-bench donne une
    image par instance. Faute de Docker ici, **Python 3.9** couvre toute la
    plage 2013-2023 de ces quatre dépôts : flask 2.3, pylint 2.x et pytest 7
    l'acceptent tous, et les vieux commits en ont besoin.

    `PY_TRANSFERT` permet d'en imposer un autre sans toucher au code.
    """
    impose = os.environ.get("PY_TRANSFERT")
    if impose and Path(impose).exists():
        return impose
    trouve = _executer(["py", "-3.9", "-c", "import sys;print(sys.executable)"],
                       RACINE, 120)
    if trouve.returncode == 0 and trouve.stdout.strip():
        return trouve.stdout.strip()
    # Repli sur l'interpréteur courant, en sachant qu'il mesurera moins : mieux
    # vaut un rendement faible et déclaré qu'un plantage au premier appel.
    return sys.executable


def preparer_venv(nom: str) -> str | None:
    """Un environnement par dépôt, créé une fois.

    L'alignement sur les épingles du commit se fait ensuite par instance, parce
    que l'environnement est une propriété du commit et non du dépôt — la leçon
    la plus coûteuse de la mesure principale.
    """
    dossier = VENVS_SWE / nom
    if not dossier.exists():
        fait = _executer([base_python(), "-m", "venv", str(dossier)], RACINE, 600)
        if fait.returncode != 0:
            return f"venv: {fait.stderr.strip()[:140]}"
    py = interprete(nom)
    env = {"PIP_CERT": str(CERTS)} if CERTS.exists() else {}
    base = _executer([py, "-m", "pip", "install", "-q", "--disable-pip-version-check",
                      *RESEAU,
                      "coverage", "pytest", "pytest-timeout"], RACINE, 900, env)
    if base.returncode != 0:
        return f"pip base: {(base.stderr or base.stdout).strip()[-160:]}"
    return None


def _noeuds(valeur) -> list[str]:
    """Les identifiants de nœuds, que le parquet rend en chaîne JSON ou en liste."""
    if isinstance(valeur, str):
        try:
            return list(json.loads(valeur))
        except json.JSONDecodeError:
            return [valeur]
    return list(valeur or [])


def _fichiers_des_noeuds(noeuds: list[str]) -> list[str]:
    """Les fichiers que les nœuds désignent, pour cibler l'installation."""
    return sorted({n.split("::", 1)[0] for n in noeuds if "::" in n})


def _cause(sortie: str, erreur: str, note_pip: str) -> str:
    """La ligne qui dit pourquoi, et non la dernière ligne imprimée.

    **Pourquoi cette fonction existe.** Les notes des quatre premières instances
    disaient toutes la même chose : `self._warn("No data was collected.")`. C'est
    l'avertissement de coverage, qui sort **après** la trace, et comme je ne
    gardais que les deux dernières lignes il noyait la cause à chaque fois.
    J'ai dû relancer une instance à la main pour apprendre qu'il s'agissait d'un
    `ImportError` sur `formatargspec`.

    Un diagnostic tronqué par la fin rapporte le bruit le plus récent. On
    cherche donc d'abord les lignes qui portent une erreur, et on ne retombe sur
    la queue que si aucune ne ressort.
    """
    melange = (sortie or "") + "\n" + (erreur or "")
    lignes = [x.strip() for x in melange.splitlines() if x.strip()]
    marqueurs = ("Error:", "error:", "ERROR ", "FAILED ", "E   ", "Interrupted",
                 "ImportError", "ModuleNotFoundError", "AttributeError")
    portantes = [x for x in lignes if any(m in x for m in marqueurs)]
    retenues = portantes[-2:] if portantes else lignes[-2:]
    cause = " | ".join(x[:90] for x in retenues)
    return f"{note_pip} || {cause}" if note_pip else cause


def mesurer_une(inst: dict, *, garder: bool = False) -> Resultat:
    depart = time.time()
    iid, repo = inst["instance_id"], inst["repo"]
    nom = CLONE[repo]
    r = lambda **kw: Resultat(iid, repo, difficulte=inst.get("difficulty", ""),
                              secondes=round(time.time() - depart, 1), **kw)

    clone = DEPOTS_SWE / nom
    if not (clone / ".git").exists():
        return r(statut="erreur", note=f"clone absent : {clone}")

    arbre = TRAVAIL / f"swe_{iid}"
    diffs = TRAVAIL / f"swe_{iid}.diffs"
    diffs.mkdir(parents=True, exist_ok=True)
    p_ref, p_test = diffs / "patch.diff", diffs / "test.diff"
    p_ref.write_text(avec_saut(inst["patch"]), encoding="utf-8", newline="\n")
    p_test.write_text(avec_saut(inst["test_patch"]), encoding="utf-8", newline="\n")

    noeuds = _noeuds(inst.get("FAIL_TO_PASS")) + _noeuds(inst.get("PASS_TO_PASS"))
    if not noeuds:
        return r(statut="erreur", note="aucun noeud d'oracle")

    try:
        if arbre.exists():
            _executer(["git", "worktree", "remove", "--force", str(arbre)], clone, 120)
            shutil.rmtree(arbre, ignore_errors=True)
        _executer(["git", "worktree", "unlock", str(arbre)], clone, 120)
        _executer(["git", "worktree", "prune"], clone, 120)
        a = _executer(["git", "worktree", "add", "-q", "--detach",
                       str(arbre), inst["base_commit"]], clone, 300)
        if a.returncode != 0:
            return r(statut="erreur", note=f"worktree: {a.stderr.strip()[:140]}")

        for quoi, chemin in (("reference", p_ref), ("test", p_test)):
            ap = _executer(["git", "apply", str(chemin)], arbre, 180)
            if ap.returncode != 0:
                return r(statut="patch_refuse",
                         note=f"{quoi}: {ap.stderr.strip()[:140]}")

        py = interprete(nom)
        env = {"PYTHONDONTWRITEBYTECODE": "1"}
        pip_env = {"PIP_CERT": str(CERTS)} if CERTS.exists() else {}

        # Installer le projet **au commit mesuré**, en editable, pour que
        # l'import et les épingles viennent de l'arbre et non du HEAD.
        pose = _executer([py, "-m", "pip", "install", "-q", "--disable-pip-version-check",
                          *RESEAU, "-e", "."],
                         arbre, 900, pip_env)
        note_pip = "" if pose.returncode == 0 else (
            f"pip -e . [{pose.returncode}] "
            f"{(pose.stderr or pose.stdout).strip()[-120:]}")

        # Puis les dépendances de test **du commit**, qui fixent la version de
        # pytest. Sans ça, le conftest d'époque rencontre un pytest moderne.
        souci_tests = _poser_les_dependances_de_test(py, arbre, pip_env)
        if souci_tests:
            note_pip = f"{note_pip} || {souci_tests}" if note_pip else souci_tests

        # Repli quand l'installation editable échoue : importer depuis l'arbre.
        #
        # Les vieux commits ne se posent pas avec un setuptools moderne, mais
        # ces projets sont de purs paquets Python — la mesure principale les
        # importe déjà ainsi (`PYTHONPATH=src`). Le repli ne sauve pas tout :
        # `psf__requests-1142` est de 2013 et son urllib3 vendu fait
        # `from collections import MutableMapping`, retiré de Python en 3.10.
        # Aucun chemin d'import ne rattrape une incompatibilité de langage, et
        # c'est pour ça que le harnais officiel donne une image par instance.
        if pose.returncode != 0:
            chemins = [str(arbre)]
            if (arbre / "src").is_dir():
                chemins.insert(0, str(arbre / "src"))
            env["PYTHONPATH"] = ";".join(chemins)

        (arbre / "pytest.ini").write_text(PYTEST_INI_DU_HARNAIS,
                                          encoding="utf-8", newline="\n")
        env["COVERAGE_FILE"] = str(arbre / ".coverage")
        t = _executer([py, "-m", "coverage", "run",
                       f"--rcfile={RACINE / 'mesure.coveragerc'}", "--source=.",
                       "-m", "pytest", *noeuds, "-q", "-p", "no:cacheprovider",
                       "--timeout", "60",
                       "-W", "ignore::DeprecationWarning",
                       "-W", "ignore::PendingDeprecationWarning"],
                      arbre, 900, env)
        if t.returncode != 0:
            return r(statut="oracle_rouge", noeuds=len(noeuds),
                     note=f"pytest {t.returncode} : "
                          f"{_cause(t.stdout, t.stderr, note_pip)}")

        fichier = arbre / ".coverage"
        if not fichier.exists():
            return r(statut="sans_couverture", noeuds=len(noeuds),
                     note="coverage n'a rien ecrit")

        exec_, mes = couverture_depuis(fichier, arbre)
        p = mesurer(iid, avec_saut(inst["patch"]), exec_, mes, racine=arbre)
        return r(statut="ok", noeuds=len(noeuds), mesurables=p.mesurables,
                 couvertes=p.couvertes, hors_mesure=p.hors_mesure,
                 part=p.part_couverte, note=note_pip)

    except subprocess.TimeoutExpired:
        return r(statut="erreur", note="delai depasse")
    except Exception as e:  # noqa: BLE001
        return r(statut="erreur", note=f"{type(e).__name__}: {str(e)[:140]}")
    finally:
        if not garder:
            _executer(["git", "worktree", "remove", "--force", str(arbre)], clone, 120)
            shutil.rmtree(arbre, ignore_errors=True)
            shutil.rmtree(diffs, ignore_errors=True)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--instances", default=str(RACINE / "data/swebench/legers.jsonl"))
    ap.add_argument("--sortie", required=True)
    ap.add_argument("--depot", default=None, help="ex: psf/requests")
    ap.add_argument("--limite", type=int, default=None)
    ap.add_argument("--garder", action="store_true")
    args = ap.parse_args()

    insts = [json.loads(l) for l in open(args.instances, encoding="utf-8") if l.strip()]
    if args.depot:
        insts = [x for x in insts if x["repo"] == args.depot]
    if args.limite:
        insts = insts[: args.limite]

    TRAVAIL.mkdir(exist_ok=True)
    VENVS_SWE.mkdir(exist_ok=True)

    sortie = Path(args.sortie)
    deja: set[str] = set()
    if sortie.exists():
        deja = {json.loads(l)["instance_id"] for l in sortie.open(encoding="utf-8") if l.strip()}
        print(f"{len(deja)} deja mesurees, elles sont sautees", flush=True)

    prets: set[str] = set()
    with sortie.open("a", encoding="utf-8") as f:
        for i, inst in enumerate(insts, 1):
            if inst["instance_id"] in deja:
                continue
            nom = CLONE[inst["repo"]]
            if nom not in prets:
                souci = preparer_venv(nom)
                if souci:
                    print(f"[{i:3}/{len(insts)}] {inst['instance_id']:28} venv: {souci}", flush=True)
                prets.add(nom)
            res = mesurer_une(inst, garder=args.garder)
            f.write(json.dumps(asdict(res), ensure_ascii=False) + "\n")
            f.flush()
            part = "    -" if res.part is None else f"{res.part:5.1%}"
            print(f"[{i:3}/{len(insts)}] {res.instance_id:28} {res.statut:14} "
                  f"{part} {res.couvertes:4}/{res.mesurables:<4} "
                  f"{res.noeuds:3}n {res.difficulte:16} {res.secondes:6.1f}s"
                  f"{'  ' + res.note[:70] if res.note else ''}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
