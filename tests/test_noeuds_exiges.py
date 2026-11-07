"""Les nœuds que le harnais exige, et les deux cas où on se tromperait.

`noeuds_exiges()` décide quels tests pèsent sur le score. S'il en rend trop, la
portée est gonflée et une tâche peut être disqualifiée par un échec sans
rapport ; s'il en rend trop peu, l'oracle est sous-estimé. Les deux erreurs
produisent un chiffre plausible, donc elles se testent.

Le cas qui justifie de parser plutôt que de grepper est
`test_un_corps_modifie_compte_aussi` : un `grep '+def test_'` le manquerait, et
le harnais exige pourtant ce test.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from lancer_mesure import noeuds_exiges  # noqa: E402


def poser(arbre: Path, relatif: str, contenu: str) -> None:
    chemin = arbre / relatif
    chemin.parent.mkdir(parents=True, exist_ok=True)
    chemin.write_text(contenu, encoding="utf-8", newline="\n")


def test_une_fonction_ajoutee_est_un_noeud_exige(tmp_path):
    poser(tmp_path, "tests/test_x.py",
          "def test_ancien():\n"
          "    assert True\n"
          "\n"
          "def test_nouveau():\n"
          "    assert 1 == 1\n")
    diff = (
        "--- a/tests/test_x.py\n"
        "+++ b/tests/test_x.py\n"
        "@@ -1,2 +1,5 @@\n"
        " def test_ancien():\n"
        "     assert True\n"
        "+\n"
        "+def test_nouveau():\n"
        "+    assert 1 == 1\n"
    )
    noms, mode = noeuds_exiges(diff, tmp_path)
    assert noms == ["test_nouveau"]
    assert mode == "noeuds"


def test_un_corps_modifie_compte_aussi(tmp_path):
    """Le cas qui condamne `grep '+def test_'`.

    Le correctif ne déclare aucune fonction ; il change une ligne **dans** une
    fonction existante. Le harnais exige ce test, donc la mesure doit le lancer.
    """
    poser(tmp_path, "tests/test_x.py",
          "def test_a():\n"
          "    assert 2 == 2\n"
          "\n"
          "def test_b():\n"
          "    assert True\n")
    diff = (
        "--- a/tests/test_x.py\n"
        "+++ b/tests/test_x.py\n"
        "@@ -1,2 +1,2 @@\n"
        " def test_a():\n"
        "-    assert 1 == 2\n"
        "+    assert 2 == 2\n"
    )
    noms, mode = noeuds_exiges(diff, tmp_path)
    assert noms == ["test_a"]
    assert mode == "noeuds"


def test_une_methode_de_classe_est_trouvee(tmp_path):
    """Les suites de ce corpus rangent leurs tests en classes (`TestPreparingURLs`).
    Une recherche qui ne descendrait pas dans les classes n'en trouverait aucun."""
    poser(tmp_path, "tests/test_x.py",
          "class TestTruc:\n"
          "    def test_dedans(self):\n"
          "        assert True\n")
    diff = (
        "--- a/tests/test_x.py\n"
        "+++ b/tests/test_x.py\n"
        "@@ -1,1 +1,3 @@\n"
        " class TestTruc:\n"
        "+    def test_dedans(self):\n"
        "+        assert True\n"
    )
    noms, mode = noeuds_exiges(diff, tmp_path)
    assert noms == ["test_dedans"]


def test_sans_fonction_touchee_on_retombe_sur_le_fichier(tmp_path):
    """Un `test_patch` qui ne touche qu'une fixture ou une constante de module.

    Le repli est honnête, mais il ne mesure pas la même chose — d'où le mode
    rendu, qui voyage ensuite dans le résultat.
    """
    poser(tmp_path, "tests/test_x.py",
          "SEUIL = 5\n"
          "\n"
          "def test_a():\n"
          "    assert SEUIL\n")
    diff = (
        "--- a/tests/test_x.py\n"
        "+++ b/tests/test_x.py\n"
        "@@ -1,1 +1,1 @@\n"
        "-SEUIL = 3\n"
        "+SEUIL = 5\n"
    )
    noms, mode = noeuds_exiges(diff, tmp_path)
    assert noms == []
    assert mode == "fichier_entier"


def test_une_fonction_qui_n_est_pas_un_test_est_ignoree(tmp_path):
    """Une fonction d'aide ajoutée au fichier de test n'est pas un nœud exigé :
    la passer à `-k` ne sélectionnerait rien et masquerait les vrais nœuds."""
    poser(tmp_path, "tests/test_x.py",
          "def aide():\n"
          "    return 1\n"
          "\n"
          "def test_a():\n"
          "    assert aide()\n")
    diff = (
        "--- a/tests/test_x.py\n"
        "+++ b/tests/test_x.py\n"
        "@@ -1,0 +1,3 @@\n"
        "+def aide():\n"
        "+    return 1\n"
        "+\n"
    )
    noms, mode = noeuds_exiges(diff, tmp_path)
    assert noms == []
    assert mode == "fichier_entier"


def test_un_fichier_absent_de_l_arbre_ne_fait_pas_echouer(tmp_path):
    """Robustesse : un `test_patch` peut nommer un fichier que l'arbre n'a pas
    (correctif partiellement appliqué). On retombe sur le fichier entier plutôt
    que de lever au milieu d'une passe de 129 tâches."""
    diff = (
        "--- a/tests/test_absent.py\n"
        "+++ b/tests/test_absent.py\n"
        "@@ -1,0 +1,2 @@\n"
        "+def test_z():\n"
        "+    assert True\n"
    )
    noms, mode = noeuds_exiges(diff, tmp_path)
    assert noms == []
    assert mode == "fichier_entier"


def test_plusieurs_fichiers_de_test_sont_cumules(tmp_path):
    poser(tmp_path, "tests/test_a.py", "def test_un():\n    assert True\n")
    poser(tmp_path, "tests/test_b.py", "def test_deux():\n    assert True\n")
    diff = (
        "--- a/tests/test_a.py\n"
        "+++ b/tests/test_a.py\n"
        "@@ -1,0 +1,2 @@\n"
        "+def test_un():\n"
        "+    assert True\n"
        "--- a/tests/test_b.py\n"
        "+++ b/tests/test_b.py\n"
        "@@ -1,0 +1,2 @@\n"
        "+def test_deux():\n"
        "+    assert True\n"
    )
    noms, _ = noeuds_exiges(diff, tmp_path)
    assert noms == ["test_deux", "test_un"]
