"""Quelle part d'un correctif de référence les tests de validation exécutent-ils ?

Le barème du concours est binaire : le correctif de l'agent est appliqué, les
tests de validation tournent, et la tâche est résolue si pytest sort en 0. Ce
barème suppose que les tests de validation contraignent le correctif. Cet outil
mesure à quel point c'est vrai, tâche par tâche.

La mesure : prendre les lignes **ajoutées** par le correctif de référence,
exécuter les tests de validation sous couverture, et relever celles que rien
n'atteint. Une ligne du correctif que les tests n'exécutent jamais est une ligne
où un agent peut écrire autre chose — ou rien — et marquer `PASS` quand même.

Trois précautions, et elles décident de la validité du chiffre :

1. **Seules les lignes que la couverture sait mesurer comptent.** Un commentaire,
   une ligne vide, une continuation d'expression ne sont pas des instructions :
   coverage ne les rapportera jamais comme exécutées, et les compter comme
   « non couvertes » gonflerait le résultat sans rien signifier. On intersecte
   donc les lignes ajoutées avec l'ensemble des instructions mesurables du
   fichier, que coverage nous donne lui-même.

2. **Les numéros sont ceux de l'image APRÈS correctif.** Un diff unifié donne
   pour chaque hunk la ligne de départ dans le nouveau fichier ; on l'incrémente
   sur les lignes de contexte et les ajouts, jamais sur les suppressions.

3. **Les fichiers de test du correctif sont exclus.** Un correctif de référence
   touche parfois ses propres tests ; les compter reviendrait à mesurer si les
   tests se couvrent eux-mêmes.

Ce que l'outil NE dit PAS, et l'article doit le dire aussi : une ligne exécutée
n'est pas une ligne vérifiée. Les tests peuvent traverser une ligne sans rien
affirmer sur son effet. La couverture est donc une **borne supérieure** de ce que
l'oracle contraint — le vrai chiffre est plus bas, jamais plus haut.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

# Le nom du fichier est lu sur la ligne `+++`, pas sur `diff --git`.
#
# Les 129 correctifs du concours n'ont AUCUN en-tête `diff --git` : ils sont au
# format unifié simple, `--- a/x` puis `+++ b/x`. Un parseur qui attend
# `diff --git` rend zéro ligne ajoutée pour les 129 tâches — sans erreur, sans
# avertissement, juste un résultat vide qui ressemble à une mesure.
#
# L'essai à blanc sur un dépôt local n'avait rien vu, parce que `git show`
# produit l'autre forme. Valider sur une entrée qui ne ressemble pas aux vraies
# données ne valide rien. `+++` est présent dans les deux formats.
ENTETE_NOUVEAU = re.compile(r"^\+\+\+ (?:b/)?(?P<nom>[^\t\n]+)")
ENTETE_HUNK = re.compile(r"^@@ -\d+(?:,\d+)? \+(?P<debut>\d+)(?:,(?P<n>\d+))? @@")


def est_un_test(chemin: str) -> bool:
    """Un fichier de test, selon la convention que le harnais lui-même applique."""
    nom = chemin.rsplit("/", 1)[-1]
    return (
        nom.startswith("test_")
        or nom.endswith("_test.py")
        or any(p in chemin.split("/") for p in ("tests", "test", "testing"))
    )


@dataclass
class LignesAjoutees:
    """Les lignes qu'un correctif ajoute, par fichier, numérotées après correctif."""

    par_fichier: dict[str, set[int]] = field(default_factory=dict)

    def total(self) -> int:
        return sum(len(v) for v in self.par_fichier.values())


def lignes_ajoutees(diff: str, *, python_seulement: bool = True,
                    garder_les_tests: bool = False) -> LignesAjoutees:
    """Extrait les lignes ajoutées d'un diff unifié, numérotées dans le nouveau fichier.

    Les fichiers de test sont écartés : mesurer si les tests se couvrent eux-mêmes
    ne dit rien sur la contrainte que l'oracle exerce sur le code corrigé.
    """
    resultat = LignesAjoutees()
    fichier: str | None = None
    ligne_courante = 0
    retenu = False

    for ligne in diff.splitlines():
        # L'ordre compte : `+++ b/x` commence par `+` et serait compté comme une
        # ligne ajoutée si on testait l'ajout avant l'en-tête.
        entete = ENTETE_NOUVEAU.match(ligne)
        if entete:
            fichier = entete.group("nom").strip()
            ligne_courante = 0
            # `garder_les_tests` sert a extraire les noeuds exiges d'un
            # `test_patch` : la, ce sont justement les fichiers de test qu'on
            # veut lire. Faux par defaut, parce que mesurer si les tests se
            # couvrent eux-memes ne dit rien de l'oracle.
            retenu = fichier != "/dev/null" and (
                garder_les_tests or not est_un_test(fichier)
            ) and (not python_seulement or fichier.endswith(".py"))
            continue

        if ligne.startswith("--- "):
            continue  # l'ancien nom ; le nouveau fait foi

        hunk = ENTETE_HUNK.match(ligne)
        if hunk:
            ligne_courante = int(hunk.group("debut"))
            continue

        if not retenu or fichier is None or ligne_courante == 0:
            continue

        if ligne.startswith("+"):
            resultat.par_fichier.setdefault(fichier, set()).add(ligne_courante)
            ligne_courante += 1
        elif ligne.startswith("-"):
            pass  # une suppression n'occupe aucune ligne dans le nouveau fichier
        else:
            ligne_courante += 1  # contexte, et aussi la ligne vide d'un diff

    return resultat


@dataclass
class Portee:
    """Le résultat pour une tâche."""

    instance_id: str
    mesurables: int          # lignes ajoutées que la couverture sait mesurer
    couvertes: int           # celles que les tests de validation exécutent
    hors_mesure: int         # commentaires, lignes vides, continuations
    detail: dict[str, list[int]] = field(default_factory=dict)  # non couvertes

    @property
    def part_couverte(self) -> float | None:
        """None quand il n'y a aucune ligne mesurable — ne pas inventer un 0 ou un 1."""
        return self.couvertes / self.mesurables if self.mesurables else None

    def resume(self) -> str:
        p = self.part_couverte
        part = "n/a" if p is None else f"{p:5.1%}"
        return (
            f"{self.instance_id:24} {part}  "
            f"{self.couvertes:4}/{self.mesurables:<4} lignes  "
            f"({self.hors_mesure} hors mesure)"
        )


def instructions_du_fichier(racine: Path, relatif: str) -> set[int]:
    """Les instructions d'un fichier, qu'un test l'ait exécuté ou non.

    Indispensable, et pour une raison qui fausse le chiffre dans le sens
    flatteur : un module que les tests n'importent jamais n'apparaît pas dans
    les données de couverture. Ses lignes ajoutées seraient alors comptées
    « non mesurables » — comme un commentaire — au lieu de « non couvertes »,
    et un correctif entier que l'oracle ignore passerait pour hors sujet.

    Écart constaté : 7/26 (26,9 %) contre 7/41 (17,1 %) sur la même tâche.
    """
    import coverage

    chemin = racine / relatif
    if not chemin.exists():
        return set()
    try:
        cov = coverage.Coverage()
        _, instructions, _, _, _ = cov.analysis2(str(chemin))
        return set(instructions)
    except Exception:
        return set()


def mesurer(
    instance_id: str,
    diff: str,
    executees_par_fichier: dict[str, set[int]],
    mesurables_par_fichier: dict[str, set[int]],
    racine: Path | None = None,
) -> Portee:
    """Croise les lignes ajoutées avec ce que la couverture a vu.

    `executees_par_fichier` et `mesurables_par_fichier` viennent de coverage :
    les instructions exécutées, et l'ensemble des instructions du fichier. La
    différence entre « ajoutée » et « ajoutée et mesurable » est ce qui empêche
    un commentaire de compter comme un trou.
    """
    ajouts = lignes_ajoutees(diff)
    mesurables = couvertes = hors = 0
    detail: dict[str, list[int]] = {}

    for fichier, lignes in ajouts.par_fichier.items():
        connues = mesurables_par_fichier.get(fichier)
        if connues is None:
            # Coverage n'a pas vu ce fichier : il n'a jamais été importé. On
            # l'analyse quand même, sinon ses lignes sortent du dénominateur.
            connues = instructions_du_fichier(racine, fichier) if racine else set()
        vues = executees_par_fichier.get(fichier, set())

        instructions = lignes & connues
        hors += len(lignes) - len(instructions)
        mesurables += len(instructions)
        couvertes += len(instructions & vues)

        manquantes = sorted(instructions - vues)
        if manquantes:
            detail[fichier] = manquantes

    return Portee(instance_id, mesurables, couvertes, hors, detail)


def couverture_depuis(fichier_coverage: str | Path, racine: str | Path) -> tuple[
    dict[str, set[int]], dict[str, set[int]]
]:
    """Lit un fichier .coverage et rend (exécutées, mesurables) par chemin relatif.

    Les chemins sont ramenés au dépôt et en séparateurs avant, parce que c'est la
    forme qu'un diff git emploie. Sans cette normalisation, rien ne s'intersecte
    sur Windows et la mesure rend 0 % partout — un résultat spectaculaire et faux.
    """
    import coverage

    racine = Path(racine).resolve()
    cov = coverage.Coverage(data_file=str(fichier_coverage))
    cov.load()
    donnees = cov.get_data()

    executees: dict[str, set[int]] = {}
    mesurables: dict[str, set[int]] = {}

    for absolu in donnees.measured_files():
        try:
            rel = Path(absolu).resolve().relative_to(racine).as_posix()
        except ValueError:
            continue  # hors du dépôt : site-packages, bibliothèque standard

        executees[rel] = set(donnees.lines(absolu) or [])

        # `analysis2` rend TOUTES les instructions du fichier, exécutées ou non.
        # Les lire ici plutôt que réutiliser les lignes exécutées est la
        # différence entre une mesure et une tautologie : avec les secondes, la
        # part couverte vaut 100 % par construction et le chiffre ne veut rien
        # dire. Trouvé en relisant, avant la première exécution.
        try:
            _, instructions, _, _, _ = cov.analysis2(absolu)
            mesurables[rel] = set(instructions)
        except Exception:
            # Fichier illisible ou disparu depuis la mesure : on ne devine pas,
            # on le laisse hors de l'ensemble mesurable plutôt que d'inventer.
            mesurables[rel] = set()

    return executees, mesurables


def classer_ajouts(diff: str) -> dict[str, dict[int, str]]:
    """Chaque ligne ajoutée est-elle un ajout pur, ou le remplacement d'une autre ?

    **Pourquoi la distinction compte, et d'où elle vient.** La mesure de
    contrainte supprime l'instruction d'une ligne ajoutée et regarde si l'oracle
    s'en aperçoit. Quand la ligne est un **ajout pur**, un survivant signifie
    exactement ce qu'on voudrait lui faire dire : le correctif officiel privé de
    cette ligne passe quand même, donc l'oracle accepte un correctif incomplet.

    Quand la ligne **remplace** une ligne supprimée par le même correctif,
    supprimer l'instruction retire aussi du comportement antérieur au correctif.
    Le programme obtenu n'est alors ni l'avant ni l'après : c'est un troisième
    programme, et la phrase « omet k lignes du correctif » devient inexacte.

    Ce que le survivant dit **reste vrai**, et reste sévère : l'oracle ne
    distingue pas la solution de référence d'un programme où cette instruction
    est absente. Pour un remplacement c'est même une accusation plus lourde,
    puisque le mutant est plus éloigné du correct qu'une simple omission. Seul
    le mot change — « diffère de la référence en k instructions » plutôt que
    « omet k lignes du correctif ».

    Sur l'échantillon mesuré, **71 % des survivants sont des remplacements**, ce
    qui est assez pour que la formulation ne soit pas un détail.

    **Le grain est le hunk**, et c'est une approximation assumée : un hunk qui
    supprime une ligne quelque part marque toutes ses lignes ajoutées comme
    remplacements. L'approximation va dans le sens prudent — elle surestime la
    part de remplacements, donc elle n'embellit pas le résultat.
    """
    out: dict[str, dict[int, str]] = {}
    fichier: str | None = None
    depart = 0
    hunk: list[str] = []

    def vider() -> None:
        if fichier is None or not hunk:
            return
        a_suppression = any(x[:1] == "-" for x in hunk)
        n = depart
        for ligne in hunk:
            marque = ligne[:1] or " "
            if marque == "+":
                out.setdefault(fichier, {})[n] = (
                    "remplacement" if a_suppression else "ajout")
                n += 1
            elif marque == " ":
                n += 1

    for ligne in diff.splitlines():
        entete = ENTETE_NOUVEAU.match(ligne)
        if entete:
            vider()
            hunk = []
            nom = entete.group("nom").strip()
            fichier = None if (nom == "/dev/null" or est_un_test(nom)
                               or not nom.endswith(".py")) else nom
            continue
        if ligne.startswith("--- "):
            continue
        h = ENTETE_HUNK.match(ligne)
        if h:
            vider()
            hunk = []
            depart = int(h.group("debut"))
            continue
        if fichier is None:
            continue
        hunk.append(ligne)

    vider()
    return out
