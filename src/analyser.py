"""Les tableaux de l'article, depuis les résultats bruts.

Produit, dans l'ordre où l'article en a besoin :

1. **Ce qui a pu être mesuré**, et ce qui ne l'a pas été, avec la raison. Un taux
   calculé sur les seules tâches dociles mesurerait la facilité d'installation.
2. **Les deux agrégats**, parce qu'ils ne disent pas la même chose : la moyenne
   par tâche traite un correctif de 2 lignes comme un de 200 ; la part pondérée
   par les lignes dit ce qu'un agent peut rater sur l'ensemble du corpus.
3. **La queue**, nommée. C'est la ressource : savoir *lesquelles* des tâches
   laissent un agent se tromper gratuitement vaut mieux qu'une moyenne.
4. **La nature des lignes non atteintes.** Si ce sont surtout des branches
   d'erreur, le constat cesse d'être « l'oracle couvre 93 % » pour devenir
   « l'oracle couvre le chemin nominal et laisse le traitement d'erreur libre »,
   ce qui est à la fois plus précis et plus actionnable.
"""

from __future__ import annotations

import json
import re
from collections import Counter
from pathlib import Path

RACINE = Path(__file__).resolve().parent.parent

#: Catégories de lignes, reconnues sur le texte source. L'ordre compte : une
#: ligne `raise` dans un `except` est comptée comme levée, pas comme capture.
CATEGORIES = [
    ("levee d'erreur", re.compile(r"^\s*raise\b")),
    ("capture d'erreur", re.compile(r"^\s*(except|finally)\b")),
    ("garde / condition", re.compile(r"^\s*(if|elif)\b")),
    ("sortie anticipee", re.compile(r"^\s*(return|continue|break|yield)\b")),
    ("boucle", re.compile(r"^\s*(for|while|with|async\s+with|async\s+for)\b")),
    ("definition", re.compile(r"^\s*(def|async\s+def|class)\b")),
    ("import", re.compile(r"^\s*(import|from)\b")),
]


def categorie(texte: str) -> str:
    for nom, motif in CATEGORIES:
        if motif.match(texte):
            return nom
    return "autre"


def charger(chemins: list[str] | None = None) -> list[dict]:
    """Les résultats à analyser, en disant lesquels et d'où.

    **Pourquoi cette fonction annonce ses sources.** Elle ramassait tout ce qui
    correspondait à `resultats*.jsonl` et laissait « la dernière gagner ». Après
    une passe complète écrite dans `resultats_accordes.jsonl`, l'ordre
    alphabétique a fait que `resultats_fastapi.jsonl` — l'ancienne passe — a
    écrasé la nouvelle, tâche par tâche. L'analyseur a alors imprimé les
    chiffres d'avant la correction sous le titre de la passe d'après, sans rien
    signaler, et je les ai presque rapportés comme neufs.

    Un agrégateur qui choisit ses entrées en silence est pire qu'un agrégateur
    qui échoue : les chiffres sortent, ils ont l'air normaux, et rien ne dit
    qu'ils viennent du mauvais fichier.

    **Et documenter le piège ne suffisait pas.** Après la première correction,
    la fonction annonçait ses sources mais fusionnait toujours ce qu'elle
    trouvait. Six fichiers de résultats cohabitaient dans `data/`, dont deux
    passes complètes et quatre passes par dépôt : un appel sans argument les
    mélangeait encore, et une ligne de journal au milieu d'un rapport de
    quarante lignes ne protège personne.

    Alors le repli **refuse** quand le motif trouve plus d'un fichier, et il
    nomme les candidats. On ne devine pas quelle passe l'utilisateur voulait :
    on le lui demande.
    """
    if chemins:
        fichiers = [Path(c) for c in chemins]
    else:
        fichiers = sorted((RACINE / "data").glob("resultats*.jsonl"))
        if len(fichiers) > 1:
            # La suggestion est le fichier le plus récemment écrit, et non le
            # dernier par ordre alphabétique : ce tri désignait
            # `resultats_rich.jsonl`, une passe périmée. Un message d'aide qui
            # oriente vers la mauvaise passe est pire qu'un message absent.
            recent = max(fichiers, key=lambda f: f.stat().st_mtime)
            noms = "\n".join(f"    {f.name}" for f in fichiers)
            raise SystemExit(
                f"{len(fichiers)} fichiers de resultats correspondent au motif, et "
                "les fusionner melangerait des passes differentes :\n"
                f"{noms}\n\nNommez celle a analyser. La plus recente est :\n"
                f"    python src/{Path(__file__).name} data/{recent.name}")

    par_id: dict[str, dict] = {}
    for f in fichiers:
        avant = len(par_id)
        lues = [json.loads(x) for x in f.open(encoding="utf-8") if x.strip()]
        # Une tâche peut avoir été mesurée deux fois (reprise) : la dernière
        # gagne, mais on compte les écrasements pour pouvoir les voir.
        par_id.update({x["instance_id"]: x for x in lues})
        ecrases = len(lues) - (len(par_id) - avant)
        print(f"   lu {f.name:28} {len(lues):4} lignes"
              + (f"  ({ecrases} ecrasent une mesure precedente)" if ecrases else ""))

    print()
    return list(par_id.values())


def texte_des_lignes(res: dict, taches: dict[str, dict]) -> list[tuple[str, str]]:
    """Le texte source des lignes non atteintes, lu dans le correctif lui-même.

    Lire le correctif plutôt que l'arbre de travail évite d'avoir à le garder :
    une ligne ajoutée par le correctif y figure, précédée de `+`, et son numéro
    dans le nouveau fichier se recalcule comme à la mesure.
    """
    from portee_oracle import ENTETE_HUNK, ENTETE_NOUVEAU

    t = taches.get(res["instance_id"])
    if not t or not res.get("detail"):
        return []

    voulu = {(f, n) for f, lignes in res["detail"].items() for n in lignes}
    trouve: list[tuple[str, str]] = []
    fichier, courant = None, 0

    for ligne in t["patch"].splitlines():
        e = ENTETE_NOUVEAU.match(ligne)
        if e:
            fichier, courant = e.group("nom").strip(), 0
            continue
        if ligne.startswith("--- "):
            continue
        h = ENTETE_HUNK.match(ligne)
        if h:
            courant = int(h.group("debut"))
            continue
        if fichier is None or courant == 0:
            continue
        if ligne.startswith("+"):
            if (fichier, courant) in voulu:
                trouve.append((fichier, ligne[1:]))
            courant += 1
        elif not ligne.startswith("-"):
            courant += 1
    return trouve


def main() -> None:
    import sys
    sys.path.insert(0, str(Path(__file__).parent))

    # Les fichiers passés en argument gagnent sur le motif : analyser une passe
    # précise doit être possible sans dépendre de ce qui traîne dans `data/`.
    print("=== 0. Sources ===")
    res = charger([a for a in sys.argv[1:] if not a.startswith("-")] or None)
    taches = {}
    chemin = RACINE / "data/tasks.jsonl"
    if chemin.exists():
        taches = {json.loads(l)["instance_id"]: json.loads(l)
                  for l in chemin.open(encoding="utf-8")}

    print(f"=== 1. Ce qui a pu etre mesure ({len(res)} taches) ===")
    for statut, n in Counter(x["statut"] for x in res).most_common():
        print(f"   {statut:18} {n:4}")
    echecs = [x for x in res if x["statut"] != "ok"]
    if echecs:
        print("\n   taches non mesurees, par depot :")
        for d, n in Counter(x["repo"] for x in echecs).most_common():
            print(f"      {d:22} {n:3}")

    ok = [x for x in res if x["statut"] == "ok" and x["part"] is not None]

    # Une mesure qui écarte une partie de sa population doit le dire.
    #
    # `part` est `None` quand le correctif ne touche aucune ligne *mesurable* —
    # pas quand l'oracle ne l'atteint pas. coverage.py compte des instructions ;
    # une ligne à l'intérieur d'un appel multi-ligne n'en est pas une. Le
    # correctif de `fastapi_14492` change `"identifier": "MIT"` au milieu d'un
    # `app = FastAPI(...)` : coverage rapporte l'instruction qui commence treize
    # lignes plus haut, et la ligne modifiée n'existe pas pour elle.
    #
    # Ces tâches sont exclues de la moyenne, et c'est juste : les compter à 0 %
    # dirait « l'oracle n'atteint rien » là où il n'y a rien à atteindre, et à
    # 100 % l'inverse. Mais l'exclusion est une **limite de la mesure**, pas un
    # détail d'implémentation : la portée d'oracle est indéfinie pour un
    # correctif qui ne modifie que des lignes de continuation, et le lecteur
    # doit savoir sur quelle fraction du corpus le chiffre ne se prononce pas.
    indefinies = [x for x in res if x["statut"] == "ok" and x["part"] is None]
    if indefinies:
        total = len(ok) + len(indefinies)
        print(f"\n   portee indefinie (correctif sans ligne mesurable) : "
              f"{len(indefinies)}/{total} = {len(indefinies) / total:.1%}")
        for x in indefinies:
            print(f"      {x['instance_id']:22} {x['repo']}")

    if not ok:
        print("\n(aucune tache exploitable)")
        return

    print(f"\n=== 2. Les deux agregats ({len(ok)} taches exploitables) ===")
    moy = sum(x["part"] for x in ok) / len(ok)
    lc, lt = sum(x["couvertes"] for x in ok), sum(x["mesurables"] for x in ok)
    print(f"   moyenne par tache        : {moy:6.1%}")
    print(f"   lignes couvertes / total : {lc}/{lt} = {lc/lt:.1%}")
    print(f"   taches a 100 %           : {sum(1 for x in ok if x['part'] >= 1):3}/{len(ok)}")

    echoues = [x for x in ok if x.get("tests_passent") is False]
    if echoues:
        print(f"\n   dont {len(echoues)} mesurees alors que les tests ne passaient pas")
        m2 = [x for x in ok if x.get("tests_passent") is not False]
        if m2:
            print(f"   sans elles : {sum(y['part'] for y in m2)/len(m2):.1%} "
                  f"sur {len(m2)} taches")

    print("\n=== 3. Par depot ===")
    for depot in sorted({x["repo"] for x in ok}):
        g = [x for x in ok if x["repo"] == depot]
        c, t_ = sum(x["couvertes"] for x in g), sum(x["mesurables"] for x in g)
        print(f"   {depot:20} {len(g):3} taches  "
              f"moyenne {sum(x['part'] for x in g)/len(g):6.1%}  "
              f"lignes {c/t_:6.1%}")

    print("\n=== 4. La queue : les taches ou l'oracle ne contraint pas ===")
    queue = sorted([x for x in ok if x["part"] < 1.0], key=lambda x: x["part"])
    print(f"   {len(queue)} taches sous 100 %, "
          f"{sum(1 for x in queue if x['part'] < 0.75)} sous 75 %\n")
    for x in queue[:20]:
        libres = x["mesurables"] - x["couvertes"]
        print(f"   {x['instance_id']:20} {x['part']:6.1%}  "
              f"{libres:3} lignes libres sur {x['mesurables']:<4}")

    if taches:
        print("\n=== 5. Nature des lignes jamais exécutées ===")
        cats: Counter = Counter()
        for x in queue:
            for _, texte in texte_des_lignes(x, taches):
                cats[categorie(texte)] += 1
        total = sum(cats.values())
        if total:
            for nom, n in cats.most_common():
                print(f"   {nom:20} {n:5}  {n/total:6.1%}")
            print(f"   {'TOTAL':20} {total:5}")


if __name__ == "__main__":
    main()
