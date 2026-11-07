"""Ajout pur ou remplacement : le mot que le résultat peut employer.

Quand une ligne survivante est un **ajout pur**, « le correctif officiel privé
de cette ligne passe quand même » est exact. Quand elle **remplace** une ligne
que le même correctif supprime, supprimer l'instruction retire aussi du
comportement antérieur, et la phrase devient fausse — il faut dire « diffère de
la référence en k instructions ».

71 % des survivants mesurés sont des remplacements, donc la classification n'est
pas un ornement : elle décide de ce que l'article peut affirmer.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from portee_oracle import classer_ajouts  # noqa: E402


def test_un_hunk_qui_n_ajoute_que_des_lignes_donne_des_ajouts_purs():
    diff = (
        "--- a/src/m.py\n"
        "+++ b/src/m.py\n"
        "@@ -10,2 +10,4 @@\n"
        " def f():\n"
        "+    if not x:\n"
        "+        raise ValueError\n"
        "     return 1\n"
    )
    assert classer_ajouts(diff)["src/m.py"] == {11: "ajout", 12: "ajout"}


def test_un_hunk_qui_supprime_marque_ses_ajouts_comme_remplacements():
    diff = (
        "--- a/src/m.py\n"
        "+++ b/src/m.py\n"
        "@@ -10,3 +10,3 @@\n"
        " def f():\n"
        "-    return 1\n"
        "+    return 2\n"
        " # fin\n"
    )
    assert classer_ajouts(diff)["src/m.py"] == {11: "remplacement"}


def test_la_numerotation_suit_le_nouveau_fichier():
    """Une suppression n'occupe aucune ligne dans le nouveau fichier ; compter
    ces lignes décalerait tous les numéros suivants et classerait la mauvaise."""
    diff = (
        "--- a/src/m.py\n"
        "+++ b/src/m.py\n"
        "@@ -5,4 +5,4 @@\n"
        " a = 1\n"
        "-b = 2\n"
        "-c = 3\n"
        "+b = 20\n"
        "+c = 30\n"
        " d = 4\n"
    )
    assert classer_ajouts(diff)["src/m.py"] == {6: "remplacement", 7: "remplacement"}


def test_deux_hunks_sont_classes_independamment():
    """L'approximation est au grain du hunk, pas du fichier : un hunk qui
    supprime ne doit pas contaminer un autre hunk qui n'ajoute que."""
    diff = (
        "--- a/src/m.py\n"
        "+++ b/src/m.py\n"
        "@@ -1,2 +1,2 @@\n"
        " x = 0\n"
        "-y = 1\n"
        "+y = 2\n"
        "@@ -20,1 +20,2 @@\n"
        " z = 3\n"
        "+w = 4\n"
    )
    assert classer_ajouts(diff)["src/m.py"] == {2: "remplacement", 21: "ajout"}


def test_les_fichiers_de_test_sont_ecartes():
    """Comme pour `lignes_ajoutees` : classer les lignes des tests ne dit rien
    de la contrainte que l'oracle exerce sur le code corrigé."""
    diff = (
        "--- a/tests/test_m.py\n"
        "+++ b/tests/test_m.py\n"
        "@@ -1,0 +1,2 @@\n"
        "+def test_x():\n"
        "+    assert True\n"
    )
    assert classer_ajouts(diff) == {}


def test_les_fichiers_non_python_sont_ecartes():
    diff = (
        "--- a/README.md\n"
        "+++ b/README.md\n"
        "@@ -1,0 +1,1 @@\n"
        "+une ligne\n"
    )
    assert classer_ajouts(diff) == {}


def test_un_fichier_cree_est_un_ajout_pur():
    """Un hunk `@@ -0,0 +1,n @@` ne supprime rien, donc tout y est un ajout."""
    diff = (
        "--- /dev/null\n"
        "+++ b/src/neuf.py\n"
        "@@ -0,0 +1,2 @@\n"
        "+def g():\n"
        "+    return 1\n"
    )
    assert classer_ajouts(diff)["src/neuf.py"] == {1: "ajout", 2: "ajout"}


def test_l_approximation_va_dans_le_sens_prudent():
    """Le grain du hunk surestime les remplacements : ici la ligne ajoutée n'a
    rien à voir avec la ligne supprimée, et elle est quand même classée
    remplacement. C'est voulu — l'approximation ne doit pas embellir le
    resultat, donc elle se trompe du côté qui le retient."""
    diff = (
        "--- a/src/m.py\n"
        "+++ b/src/m.py\n"
        "@@ -1,5 +1,5 @@\n"
        " a = 1\n"
        "-vieux = 2\n"
        " b = 3\n"
        "+neuf = 4\n"
        " c = 5\n"
    )
    assert classer_ajouts(diff)["src/m.py"] == {3: "remplacement"}
