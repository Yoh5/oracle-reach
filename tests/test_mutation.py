"""La machinerie de mutation, éprouvée sur les cas qui la casseraient en silence.

Le chiffre principal de l'article repose sur ce code. S'il mute la mauvaise
ligne, laisse un fichier en morceaux, ou compte un mutant incompilable comme
tué, le résultat est faux **et plausible** — la pire combinaison.

Ces tests portent sur les fonctions pures. Les cas qui exigent un dépôt réel et
un lancement de pytest sont couverts par la passe de mesure elle-même, dont les
résultats sont publiés tâche par tâche.
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from contrainte import (  # noqa: E402
    _sans_les_imbriquees,
    etendue_des_instructions,
    lignes_sans_omission_possible,
    muter,
)


def lignes(source: str) -> list[str]:
    return source.splitlines(keepends=True)


# ── L'étendue d'une instruction ──────────────────────────────────────────

def test_une_instruction_sur_une_ligne():
    etendues = etendue_des_instructions("x = 1\ny = 2\n")
    assert etendues[1] == (1, 1)
    assert etendues[2] == (2, 2)


def test_une_instruction_multiligne_porte_jusqu_a_sa_fin():
    """Le cas qui motive la fonction : muter la seule première ligne d'un appel
    multiligne laisserait une queue orpheline et un fichier illisible."""
    source = "app = Truc(\n    a=1,\n    b=2,\n)\n"
    assert etendue_des_instructions(source)[1] == (1, 4)


def test_les_lignes_interieures_ne_demarrent_aucune_instruction():
    """coverage ne rapporte que la ligne de début ; si elle rapportait une ligne
    intérieure, on ne doit pas lui inventer une étendue."""
    etendues = etendue_des_instructions("app = Truc(\n    a=1,\n)\n")
    assert 2 not in etendues and 3 not in etendues


# ── La mutation ──────────────────────────────────────────────────────────

def test_une_instruction_est_remplacee_par_pass():
    mute = muter(lignes("def f():\n    return 42\n"), 2, 2)
    assert mute is not None
    assert "".join(mute) == "def f():\n    pass\n"


def test_l_indentation_est_conservee():
    """`pass` à la mauvaise colonne est une erreur de syntaxe, donc un mutant
    écarté — ce qui ferait disparaître la ligne de la mesure au lieu de la
    mesurer."""
    mute = muter(lignes("class C:\n    def f(self):\n        x = 1\n"), 3, 3)
    assert "".join(mute).endswith("        pass\n")


def test_une_instruction_multiligne_disparait_en_entier():
    source = "y = 0\napp = Truc(\n    a=1,\n)\nz = 2\n"
    mute = muter(lignes(source), 2, 4)
    assert "".join(mute) == "y = 0\npass\nz = 2\n"
    ast.parse("".join(mute))


def test_le_fichier_mute_parse_encore():
    """Un mutant qui ne compile pas n'enseigne rien. On vérifie ici le cas
    normal ; les cas pathologiques sont écartés par le reparsage côté appelant."""
    source = "def f(a):\n    if a:\n        return 1\n    return 2\n"
    for debut in (3, 4):
        mute = muter(lignes(source), debut, debut)
        assert mute is not None
        ast.parse("".join(mute))


@pytest.mark.parametrize("corps", ["pass", "...", '"une docstring"', "'autre'"])
def test_les_instructions_sans_effet_ne_sont_pas_mutees(corps):
    """Muter un `pass` ou une docstring ne change rien d'observable. Un tel
    mutant survivrait toujours, et le compter ferait passer un non-événement
    pour une lacune d'oracle."""
    assert muter(lignes(f"def f():\n    {corps}\n"), 2, 2) is None


def test_une_affectation_dont_la_valeur_est_une_chaine_est_mutee():
    """La garde précédente ne doit pas avaler une vraie instruction : seule une
    chaîne **seule** est sans effet, pas une affectation de chaîne."""
    mute = muter(lignes('def f():\n    x = "valeur"\n'), 2, 2)
    assert mute is not None


# ── Les instructions imbriquées, lors du cumul ───────────────────────────

def test_une_instruction_contenue_dans_une_autre_est_ecartee():
    """Si `if` et son `return` survivent tous deux, remplacer le `if` par `pass`
    supprime déjà le `return`. Les compter tous les deux gonflerait le nombre
    d'omissions — le chiffre même que la démonstration met en avant."""
    source = "def f(a):\n    if a:\n        return 1\n"
    etendues = etendue_des_instructions(source)
    assert _sans_les_imbriquees(etendues, [2, 3]) == [2]


def test_deux_instructions_soeurs_sont_toutes_deux_gardees():
    source = "def f():\n    x = 1\n    y = 2\n"
    etendues = etendue_des_instructions(source)
    assert _sans_les_imbriquees(etendues, [2, 3]) == [2, 3]


def test_l_ordre_d_entree_ne_change_pas_le_resultat():
    """Appelée avec les numéros dans le désordre — ce qui arrive, les survivants
    étant collectés fichier par fichier — la fonction doit rendre la même
    chose."""
    source = "def f(a):\n    if a:\n        x = 1\n        y = 2\n    z = 3\n"
    etendues = etendue_des_instructions(source)
    assert _sans_les_imbriquees(etendues, [5, 3, 2, 4]) == [2, 5]


# ── Le cumul appliqué de bas en haut ────────────────────────────────────

def test_muter_plusieurs_lignes_de_bas_en_haut_reste_coherent():
    """Le piège que `_omettre_tout` évite : une substitution décale les numéros
    de ce qui suit. Appliqué du haut vers le bas, le deuxième tour muterait la
    mauvaise ligne."""
    source = "a = Truc(\n    x=1,\n)\nb = 2\nc = 3\n"
    etendues = etendue_des_instructions(source)
    courant = lignes(source)
    for numero in sorted([1, 4, 5], reverse=True):
        courant = muter(courant, *etendues[numero])
    texte = "".join(courant)
    assert texte == "pass\npass\npass\n"
    ast.parse(texte)


def test_du_haut_vers_le_bas_la_mutation_derape():
    """Le test qui prouve que l'ordre n'est pas une préférence de style.

    Appliqué du haut vers le bas avec les étendues d'origine, le cumul mute la
    mauvaise ligne et laisse un fichier qui ne dit plus ce qu'on croit — et il
    peut très bien parser, donc rien ne le signalerait.
    """
    source = "a = Truc(\n    x=1,\n)\nb = 2\nc = 3\n"
    etendues = etendue_des_instructions(source)
    courant = lignes(source)
    for numero in sorted([1, 4, 5]):
        mute = muter(courant, *etendues[numero])
        if mute is None:
            break
        courant = mute
    assert "".join(courant) != "pass\npass\npass\n"


def test_une_etendue_hors_limites_rend_none_au_lieu_de_lever():
    """La garde qui fait échouer dans la bonne catégorie.

    Une `IndexError` dans la boucle de production serait avalée par le
    `except Exception` large, et la tâche sortirait en « erreur » sans dire
    pourquoi. En rendant `None`, le cas devient un « mutant invalide » : compté,
    visible, et exclu du dénominateur.

    C'est le test précédent qui a révélé le besoin : muter du haut vers le bas
    ne produit pas seulement un mauvais fichier, ça sort du fichier.
    """
    assert muter(lignes("x = 1\n"), 5, 5) is None     # début au-delà de la fin
    assert muter(lignes("x = 1\n"), 1, 9) is None     # fin au-delà de la fin
    assert muter(lignes("x = 1\n"), 0, 1) is None     # numérotation à partir de 1


# ── Les gardes `__main__`, artefact classique du test par mutation ───────

def test_la_garde_main_est_ecartee():
    """Retirer `if __name__ == "__main__":` d'un module importé ne change rien
    d'observable. Le compter comme survivant gonflerait tous les totaux, y
    compris le nombre de lignes de la démonstration cumulée."""
    source = "def f():\n    return 1\n\nif __name__ == \"__main__\":\n    f()\n"
    assert lignes_sans_omission_possible(source) == {4}


def test_la_garde_main_ecrite_a_l_envers_tombe_aussi():
    """Repérée sur l'arbre syntaxique et non par motif : l'ordre des opérandes
    ne doit pas la sauver."""
    source = "if \"__main__\" == __name__:\n    pass\n"
    assert lignes_sans_omission_possible(source) == {1}


def test_un_commentaire_qui_cite_main_ne_compte_pas():
    """L'inverse de l'erreur précédente : un motif textuel écarterait cette
    ligne alors qu'elle porte une vraie instruction."""
    source = "x = 1  # voir le bloc if __name__ == \"__main__\" plus bas\n"
    assert lignes_sans_omission_possible(source) == set()


def test_une_condition_sur_name_sans_main_n_est_pas_ecartee():
    """`if __name__ == "autre":` n'est pas la garde d'entrée : son retrait est
    une vraie omission."""
    source = "if __name__ == \"autre\":\n    pass\n"
    assert lignes_sans_omission_possible(source) == set()


def test_une_source_qui_ne_parse_pas_ne_fait_pas_echouer():
    """Robustesse au milieu d'une passe de 129 tâches : on rend un ensemble
    vide plutôt que de lever, le reparsage du mutant attrapera le vrai souci."""
    assert lignes_sans_omission_possible("def f(:\n") == set()
