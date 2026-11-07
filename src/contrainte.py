"""Une ligne exécutée est-elle une ligne contrainte ?

`portee_oracle.py` mesure la **portée** : quelle part des lignes ajoutées par le
correctif de référence les tests de validation exécutent. C'est une borne
supérieure, et l'article le dit — exécuter une ligne est nécessaire pour la
contraindre, pas suffisant. Une ligne peut tourner sans qu'aucune assertion ne
dépende de son effet.

Ce module ferme cet écart. Pour chaque ligne **couverte** du correctif, on la
supprime et on relance exactement les tests que le harnais exigerait. Si les
tests passent encore, la ligne était exécutée et **libre** : son oubli ne serait
pas vu.

**Pourquoi la suppression d'instruction, et pas un jeu d'opérateurs.** La
question posée est « cette ligne est-elle contrainte contre son absence ? ».
La suppression est exactement cet opérateur, et c'est le plus fort : une ligne
qui survit à sa suppression survit à toute mutation plus fine. Un seul opérateur
rend aussi le chiffre lisible — « part des lignes couvertes qui survivent à la
suppression » — là où un mélange d'opérateurs produit un score dont personne ne
sait ce qu'il pèse.

**Ce n'est pas le terrain de SWE-Mutation.** Ces travaux mutent la solution
entière sur 800 instances et 9 langages pour demander si une suite sait séparer
un correctif juste d'un correctif plausible mais faux. Ici on mute **seulement
les lignes que le correctif de référence ajoute**, on juge **seulement avec les
nœuds de test que le harnais exige**, et le but est de valider ou de réfuter
notre propre mesure de portée. Si la contrainte est très en dessous de la
portée, c'est notre chiffre principal qui tombe — et c'est le risque qu'il faut
prendre pour que l'article tienne en relecture.

**Les mutants invalides se détectent, ils ne s'énumèrent pas.** Remplacer un
décorateur, un en-tête `else:` ou la seule instruction d'un bloc par `pass`
produit du code que Python refuse. Plutôt que de lister ces cas — liste qu'on
oublierait de compléter — on reparse le fichier muté et on écarte ce qui ne
parse pas. Un mutant qui ne compile pas n'enseigne rien, et le compter comme
« tué » gonflerait le résultat exactement dans le sens qui nous arrange.
"""

from __future__ import annotations

import argparse
import ast
import json
import shutil
import subprocess
import sys
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from lancer_mesure import (  # noqa: E402
    CLONE,
    DEPOTS,
    TRAVAIL,
    RACINE,
    _accorder_les_dependances,
    _executer,
    _plafond_par_test,
    _poser_pytest_ini_du_harnais,
    avec_saut,
    cibles_pytest,
    interprete,
    noeuds_exiges,
)
from portee_oracle import couverture_depuis, lignes_ajoutees  # noqa: E402


@dataclass
class Contrainte:
    """Ce qu'une tâche rend : la décomposition de ses lignes couvertes."""

    instance_id: str
    repo: str
    statut: str = "ok"
    #: Lignes couvertes du correctif soumises à mutation.
    tentees: int = 0
    #: Mutants dont la suppression casse au moins un test.
    tues: int = 0
    #: Mutants que la suite laisse passer : lignes exécutées mais libres.
    survivants: int = 0
    #: Mutants que Python refuse de compiler — écartés, pas comptés.
    invalides: int = 0
    #: Les lignes survivantes, pour pouvoir les relire une par une.
    detail: dict[str, list[int]] = field(default_factory=dict)
    #: `noeuds` ou `fichier_entier` : de quoi la contrainte est la contrainte.
    mode: str = ""
    noeuds: int = 0
    #: Toutes les lignes survivantes supprimees **ensemble** : les tests exiges
    #: passent-ils encore ? Un `True` ici est un correctif qui omet
    #: `cumul_lignes` lignes du correctif officiel et que le bareme accepte.
    cumul_passe: bool | None = None
    cumul_lignes: int = 0
    cumul_note: str = ""
    secondes: float = 0.0
    note: str = ""

    @property
    def part_contrainte(self) -> float | None:
        """None quand aucun mutant valide n'a pu être construit.

        Même discipline que `part_couverte` : ne pas inventer un 0 ou un 1 là
        où la mesure n'a pas eu lieu.
        """
        valides = self.tues + self.survivants
        return self.tues / valides if valides else None


def etendue_des_instructions(source: str) -> dict[int, tuple[int, int]]:
    """Pour chaque ligne qui démarre une instruction, son étendue (début, fin).

    Une ligne mesurable par coverage est le début d'une instruction, mais cette
    instruction peut courir sur plusieurs lignes. Supprimer la seule première
    laisserait une queue orpheline et un fichier illisible — on remplace donc
    l'instruction entière.
    """
    arbre = ast.parse(source)
    etendues: dict[int, tuple[int, int]] = {}
    for noeud in ast.walk(arbre):
        if isinstance(noeud, ast.stmt):
            fin = getattr(noeud, "end_lineno", noeud.lineno) or noeud.lineno
            # Un `def` décoré commence, pour ast, à la ligne du `def` ; les
            # lignes de décorateur sont portées par le même nœud. On garde la
            # première occurrence, qui est la plus fine.
            etendues.setdefault(noeud.lineno, (noeud.lineno, fin))
    return etendues


def lignes_sans_omission_possible(source: str) -> set[int]:
    """Les instructions dont le retrait n'est l'oubli de rien.

    **Le cas qui a imposé cette fonction.** `fastapi_15661` rendait cinq
    survivants, dont `if __name__ == "__main__":` à la fin de
    `scripts/prepare_release.py`. Les quatre autres sont de vraies gardes
    d'erreur que les tests traversent sans jamais déclencher — le résultat qu'on
    cherche. Le cinquième n'en est pas un : retirer le bloc `__main__` d'un
    module qu'on importe ne change rien d'observable, et personne n'appellerait
    son absence un défaut.

    C'est l'artefact classique du test par mutation, et le laisser passer
    gonflerait **tous** les totaux, y compris le nombre de lignes de la
    démonstration cumulée — le chiffre que l'article met en avant. On l'écarte
    donc comme on écarte `pass` et les docstrings : par construction, en le
    comptant dans les mutants invalides plutôt qu'en le taisant.

    Repéré sur l'arbre syntaxique et non par motif textuel : `if __name__ ==
    "__main__":`, `if "__main__" == __name__:` et les variantes d'espacement
    doivent toutes tomber, et un commentaire qui contient ce texte ne doit pas.
    """
    def est_garde_main(noeud: ast.expr) -> bool:
        if not isinstance(noeud, ast.Compare) or len(noeud.ops) != 1:
            return False
        if not isinstance(noeud.ops[0], ast.Eq):
            return False
        cotes = [noeud.left, noeud.comparators[0]]
        a_nom = any(isinstance(c, ast.Name) and c.id == "__name__" for c in cotes)
        a_main = any(isinstance(c, ast.Constant) and c.value == "__main__" for c in cotes)
        return a_nom and a_main

    try:
        arbre = ast.parse(source)
    except SyntaxError:
        return set()
    return {n.lineno for n in ast.walk(arbre)
            if isinstance(n, ast.If) and est_garde_main(n.test)}


def muter(lignes: list[str], debut: int, fin: int) -> list[str] | None:
    """Remplace l'instruction [debut, fin] par `pass`, ou rend None.

    `pass` et non la suppression pure : un bloc vide est une erreur de syntaxe,
    et on veut mesurer l'absence de l'effet, pas l'absence du bloc.

    Rend None quand l'instruction est déjà un `pass`, une ellipse ou une chaîne
    seule — muter ça ne change rien d'observable, et compter un tel mutant
    comme survivant ferait passer un non-événement pour une lacune d'oracle.
    """
    # Une etendue hors limites doit degrader vers « mutant invalide », qui est
    # compte et visible, et non lever dans la boucle de production ou le
    # `except Exception` large la transformerait en « erreur » sans explication.
    # L'appel bas-vers-haut de `_omettre_tout` garantit des indices valides ;
    # cette garde est la pour que la garantie ne soit pas la seule protection.
    if not (1 <= debut <= fin <= len(lignes)):
        return None

    corps = "".join(lignes[debut - 1:fin]).strip()
    if corps in ("pass", "...") or (corps[:1] in ("'", '"') and corps[-1:] in ("'", '"')):
        return None

    indentation = lignes[debut - 1][: len(lignes[debut - 1]) - len(lignes[debut - 1].lstrip())]
    mute = list(lignes)
    mute[debut - 1:fin] = [f"{indentation}pass\n"]
    return mute


def _sans_les_imbriquees(
    etendues: dict[int, tuple[int, int]], numeros: list[int]
) -> list[int]:
    """Écarte toute ligne dont l'instruction est contenue dans une autre retenue.

    Si une instruction A contient une instruction B et que les deux survivent,
    remplacer A par `pass` supprime déjà B. Les muter toutes les deux compterait
    deux omissions là où il n'y en a qu'une, et gonflerait `cumul_lignes` —
    exactement le chiffre que la démonstration met en avant.
    """
    retenues: list[int] = []
    for n in sorted(numeros):
        debut, fin = etendues[n]
        if any(etendues[m][0] <= debut and fin <= etendues[m][1] and m != n
               for m in retenues):
            continue
        retenues.append(n)
    return retenues


def _omettre_tout(
    arbre: Path, survivants: dict[str, list[int]]
) -> tuple[int, str | None]:
    """Supprime d'un coup toutes les lignes survivantes. Rend (lignes, souci).

    **Pourquoi cette étape existe.** Chaque survivant pris seul est déjà un
    correctif que le barème accepte en omettant une ligne du correctif officiel.
    Les cumuler répond à la question qu'un lecteur posera ensuite : *de combien
    peut-on s'écarter du correctif de référence sans que le barème le voie ?*
    La réponse n'est pas un indicateur, c'est un correctif qu'on peut relire.

    Les fichiers sont modifiés **de bas en haut** : remplacer une instruction par
    une ligne décale les numéros de ce qui suit, et appliquer du haut vers le bas
    muterait la mauvaise ligne au deuxième tour.
    """
    total = 0
    for fichier, numeros in survivants.items():
        chemin = arbre / fichier
        if not chemin.exists():
            continue
        source = chemin.read_text(encoding="utf-8", errors="replace")
        lignes = source.splitlines(keepends=True)
        try:
            etendues = etendue_des_instructions(source)
        except SyntaxError:
            return 0, f"{fichier} ne parse pas"

        sans_omission = lignes_sans_omission_possible(source)
        utiles = [n for n in numeros if n in etendues and n not in sans_omission]
        if not utiles:
            continue
        for numero in sorted(_sans_les_imbriquees(etendues, utiles), reverse=True):
            mute = muter(lignes, *etendues[numero])
            if mute is None:
                continue
            lignes = mute
            total += 1

        texte = "".join(lignes)
        try:
            ast.parse(texte)
        except SyntaxError:
            return 0, f"{fichier} : le cumul ne compile pas"
        chemin.write_text(texte, encoding="utf-8", newline="")

    return total, None


def _lignes_couvertes_ajoutees(
    tache: dict, arbre: Path, fichier_coverage: Path
) -> dict[str, set[int]]:
    """Les lignes que le correctif ajoute, que coverage mesure, et qui tournent.

    L'intersection des trois est le seul ensemble sur lequel la question a un
    sens : une ligne non ajoutée n'est pas notre sujet, une ligne non mesurable
    n'a pas d'instruction à supprimer, et une ligne non exécutée est déjà
    comptée comme libre par la mesure de portée.
    """
    executees, mesurables = couverture_depuis(fichier_coverage, arbre)
    ajoutees = lignes_ajoutees(avec_saut(tache["patch"]))
    cible: dict[str, set[int]] = {}
    for fichier, numeros in ajoutees.par_fichier.items():
        vues = executees.get(fichier)
        connues = mesurables.get(fichier)
        if not vues or connues is None:
            continue
        retenues = set(numeros) & connues & vues
        if retenues:
            cible[fichier] = retenues
    return cible


def mesurer_une(tache: dict, *, plafond: int | None = None,
                garder: bool = False, selection_voulue: str = "fichier") -> Contrainte:
    depart = time.time()
    iid, repo = tache["instance_id"], tache["repo"]
    r = lambda **kw: Contrainte(iid, repo, secondes=round(time.time() - depart, 1), **kw)

    clone = DEPOTS / CLONE[repo]
    arbre = TRAVAIL / f"mut_{iid}"
    diffs = TRAVAIL / f"mut_{iid}.diffs"
    diffs.mkdir(parents=True, exist_ok=True)
    p_ref, p_test = diffs / "patch.diff", diffs / "test.diff"
    p_ref.write_text(avec_saut(tache["patch"]), encoding="utf-8", newline="\n")
    p_test.write_text(avec_saut(tache["test_patch"]), encoding="utf-8", newline="\n")

    try:
        if arbre.exists():
            _executer(["git", "worktree", "remove", "--force", str(arbre)], clone, 120)
            shutil.rmtree(arbre, ignore_errors=True)
        _executer(["git", "worktree", "unlock", str(arbre)], clone, 120)
        _executer(["git", "worktree", "prune"], clone, 120)
        a = _executer(["git", "worktree", "add", "-q", "--detach",
                       str(arbre), tache["base_commit"]], clone, 300)
        if a.returncode != 0:
            return r(statut="erreur", note=f"worktree: {a.stderr.strip()[:140]}")

        for nom, chemin in (("reference", p_ref), ("test", p_test)):
            ap = _executer(["git", "apply", str(chemin)], arbre, 180)
            if ap.returncode != 0:
                return r(statut="patch_refuse", note=f"{nom}: {ap.stderr.strip()[:140]}")

        cibles = cibles_pytest(tache["test_patch"])
        if not cibles:
            return r(statut="erreur", note="aucun fichier de test dans test_patch")

        _poser_pytest_ini_du_harnais(arbre)
        _accorder_les_dependances(repo, arbre)
        env = {"PYTHONPATH": "src", "PYTHONDONTWRITEBYTECODE": "1"}
        plafond_test = _plafond_par_test(repo)

        # Meme selection que la mesure de portee, et pour la meme raison : la
        # contrainte doit etre celle des noeuds que le harnais exige. Juger un
        # mutant avec le fichier entier le ferait tuer par un test qui ne pese
        # pas sur le score, et surestimerait la contrainte exactement comme le
        # fichier entier surestimait la portee.
        #
        # Effet secondaire decisif pour le cout : un mutant se juge en 3 a 5
        # secondes au lieu de 30 a 150, ce qui rend la passe complete possible.
        # Meme defaut que la mesure de portee, et pour la meme raison : le
        # harnais juge sur les fichiers cibles entiers (HARNESS_README section
        # 8.2). Un mutant doit donc etre juge par ce qui decide le score.
        noms, mode = ([], "fichier_entier")
        if selection_voulue == "noeuds":
            noms, mode = noeuds_exiges(tache["test_patch"], arbre)
        selection = ["-k", " or ".join(noms)] if noms else []

        def lancer_les_tests(avec_couverture: bool,
                             arreter_au_premier_echec: bool = False,
                             muet: bool | None = None) -> subprocess.CompletedProcess:
            """Lance les noeuds exiges, avec ou sans couverture.

            `muet` decide du mode d'execution, et c'est lui qui protege du
            blocage : par defaut il suit `arreter_au_premier_echec`, mais le
            lancement **cumule** doit l'imposer explicitement. Ce lancement-la
            juge un programme prive de toutes ses lignes libres d'un coup —
            precisement la ou une suppression massive peut creer une boucle sans
            fin — et il passait encore par le chemin qui capture. La passe est
            restee muette 1 h 46 sur `rich_3930` avant que je le voie : j'avais
            bouche un trou et laisse l'autre, dans la meme fonction.

            `arreter_au_premier_echec` (`-x`) sur les mutants seulement. Le
            verdict est binaire — un echec quelconque tue le mutant — donc
            s'arreter au premier ne peut pas le changer, et la majorite des
            mutants etant tues, ca supprime la majorite du travail. Le temoin,
            lui, tourne en entier : on veut savoir que **tout** passe avant de
            muter, pas seulement que le premier noeud passe.

            Une erreur de collecte compte comme un mutant tue, et c'est
            correct : supprimer un `import` casse le module, et l'oracle detecte
            bien cette omission-la. Ce qui serait faux, c'est de compter ainsi
            un mutant que Python refuse de compiler — celui-la est ecarte avant
            d'arriver ici.
            """
            base = [interprete(repo)]
            e = dict(env)
            if avec_couverture:
                e["COVERAGE_FILE"] = str(arbre / ".coverage")
                base += ["-m", "coverage", "run",
                         f"--rcfile={RACINE / 'mesure.coveragerc'}", "--source=."]
            cmd = base + ["-m", "pytest", *cibles, "-q",
                          "-p", "no:cacheprovider", *selection, *plafond_test,
                          *(["-x"] if arreter_au_premier_echec else []),
                          "-W", "ignore::DeprecationWarning",
                          "-W", "ignore::PendingDeprecationWarning"]
            sans_tuyaux = arreter_au_premier_echec if muet is None else muet
            if not sans_tuyaux:
                # Le temoin : on garde sa sortie, elle sert au diagnostic.
                return _executer(cmd, arbre, 300, e)

            # Un mutant : seul le code de retour compte, et capturer la sortie
            # ouvre un mode de panne qui a coute neuf heures sur une seule
            # tache. `subprocess.run(capture_output=True, timeout=...)` tue
            # bien l'enfant au delai, puis **relit les tuyaux** ; si un
            # petit-enfant du test les a herites et pend, cette lecture bloque
            # sans limite. Le plafond ne plafonnait donc rien, et quatre taches
            # sont sorties en « erreur » avec 302 s, 375 s, 558 s et **32 751 s**.
            #
            # Sans tuyaux a relire, le delai est le delai. On y perd la sortie
            # du mutant, qu'on ne lisait pas.
            import os
            import subprocess as sp
            try:
                fini = sp.run(cmd, cwd=arbre, stdout=sp.DEVNULL, stderr=sp.DEVNULL,
                              stdin=sp.DEVNULL, timeout=120, env={**os.environ, **e})
                return sp.CompletedProcess(cmd, fini.returncode, "", "")
            except sp.TimeoutExpired:
                # Un mutant qui pend est un mutant que l'oracle refuse : la
                # suppression a cree une boucle sans fin, ce qui se voit. On le
                # compte comme tue plutot que de perdre la tache entiere.
                return sp.CompletedProcess(cmd, 124, "", "delai du mutant depasse")

        # Le témoin. Sans suite verte au départ, « le mutant a été tué » ne veut
        # rien dire : on ne saurait pas si c'est la mutation ou l'état initial
        # qui fait rougir les tests.
        temoin = lancer_les_tests(True)
        if temoin.returncode != 0:
            queue = " | ".join(x[:60] for x in (temoin.stdout or temoin.stderr).strip().splitlines()[-2:])
            return r(statut="temoin_rouge", note=f"pytest {temoin.returncode} : {queue}")

        couvertes = _lignes_couvertes_ajoutees(tache, arbre, arbre / ".coverage")
        if not couvertes:
            return r(statut="rien_a_muter", note="aucune ligne ajoutee couverte")

        res = r()
        res.mode, res.noeuds = mode, len(noms)
        survivants: dict[str, list[int]] = {}

        for fichier, numeros in sorted(couvertes.items()):
            chemin = arbre / fichier
            if not chemin.exists():
                continue
            original = chemin.read_text(encoding="utf-8", errors="replace")
            lignes = original.splitlines(keepends=True)
            try:
                etendues = etendue_des_instructions(original)
            except SyntaxError:
                continue
            sans_omission = lignes_sans_omission_possible(original)

            a_muter = sorted(numeros)
            if plafond and len(a_muter) > plafond:
                # Échantillon régulier et non aléatoire : la passe doit être
                # rejouable à l'identique, et un pas constant ne privilégie
                # aucune zone du correctif.
                pas = len(a_muter) / plafond
                a_muter = [a_muter[int(i * pas)] for i in range(plafond)]
                res.note = f"echantillon {plafond}/{len(numeros)} par fichier"

            try:
                for numero in a_muter:
                    etendue = etendues.get(numero)
                    if etendue is None or numero in sans_omission:
                        res.invalides += 1
                        continue
                    mute = muter(lignes, *etendue)
                    if mute is None:
                        res.invalides += 1
                        continue
                    texte = "".join(mute)
                    try:
                        ast.parse(texte)
                    except SyntaxError:
                        # Décorateur, en-tête `else:`, bloc rendu vide : un
                        # mutant que Python refuse n'enseigne rien.
                        res.invalides += 1
                        continue

                    chemin.write_text(texte, encoding="utf-8", newline="")
                    sortie = lancer_les_tests(False, arreter_au_premier_echec=True)
                    res.tentees += 1
                    if sortie.returncode == 0:
                        res.survivants += 1
                        survivants.setdefault(fichier, []).append(numero)
                    else:
                        res.tues += 1
            finally:
                # Toujours remettre le fichier, même sur interruption : un
                # fichier laissé muté contaminerait toutes les lignes suivantes
                # et la tâche rendrait un chiffre faux sans rien signaler.
                chemin.write_text(original, encoding="utf-8", newline="")

        res.detail = survivants

        # La demonstration : tout omettre d'un coup et voir si le bareme le voit.
        if survivants:
            originaux = {f: (arbre / f).read_text(encoding="utf-8", errors="replace")
                         for f in survivants if (arbre / f).exists()}
            try:
                res.cumul_lignes, souci = _omettre_tout(arbre, survivants)
                if souci:
                    res.cumul_note = souci
                elif res.cumul_lignes:
                    # `muet=True` : voir la docstring de `lancer_les_tests`.
                    # Supprimer toutes les lignes libres a la fois est l'endroit
                    # le plus propice a une boucle sans fin, donc c'est le
                    # dernier endroit ou laisser un tuyau a relire.
                    sortie = lancer_les_tests(False, muet=True)
                    res.cumul_passe = sortie.returncode == 0
                    if not res.cumul_passe:
                        queue = (sortie.stdout or sortie.stderr).strip().splitlines()[-1:]
                        res.cumul_note = queue[0][:90] if queue else ""
            finally:
                for f, texte in originaux.items():
                    (arbre / f).write_text(texte, encoding="utf-8", newline="")

        res.secondes = round(time.time() - depart, 1)
        return res

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
    ap.add_argument("--taches", default=str(RACINE / "data/tasks.jsonl"))
    ap.add_argument("--sortie", required=True)
    ap.add_argument("--depot", default=None, help="ex: Textualize/rich")
    ap.add_argument("--limite", type=int, default=None)
    ap.add_argument("--plafond", type=int, default=None,
                    help="nombre maximal de mutants par fichier (echantillon regulier)")
    ap.add_argument("--garder", action="store_true")
    ap.add_argument("--selection", choices=("fichier", "noeuds"), default="fichier",
                    help="fichier = ce que fait le harnais (defaut)")
    args = ap.parse_args()

    taches = [json.loads(l) for l in open(args.taches, encoding="utf-8") if l.strip()]
    if args.depot:
        taches = [t for t in taches if t["repo"] == args.depot]
    if args.limite:
        taches = taches[: args.limite]

    TRAVAIL.mkdir(exist_ok=True)
    sortie = Path(args.sortie)
    deja: set[str] = set()
    if sortie.exists():
        deja = {json.loads(l)["instance_id"] for l in sortie.open(encoding="utf-8") if l.strip()}
        print(f"{len(deja)} deja faites, elles sont sautees", flush=True)

    with sortie.open("a", encoding="utf-8") as f:
        for i, t in enumerate(taches, 1):
            if t["instance_id"] in deja:
                continue
            res = mesurer_une(t, plafond=args.plafond, garder=args.garder,
                              selection_voulue=args.selection)
            f.write(json.dumps(asdict(res), ensure_ascii=False) + "\n")
            f.flush()
            part = "    -" if res.part_contrainte is None else f"{res.part_contrainte:5.1%}"
            cumul = ""
            if res.cumul_passe is True:
                cumul = f"  ACCEPTE EN OMETTANT {res.cumul_lignes}"
            elif res.cumul_passe is False:
                cumul = f"  cumul de {res.cumul_lignes} attrape"
            print(f"[{i:3}/{len(taches)}] {res.instance_id:22} {res.statut:13} "
                  f"{part}  tues {res.tues:3} survivants {res.survivants:3} "
                  f"invalides {res.invalides:3}  {res.secondes:6.1f}s{cumul}"
                  f"{'  ' + res.note if res.note else ''}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
