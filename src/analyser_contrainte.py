"""Croiser portée et contrainte, et refaire le test de taille sur le produit.

La portée est une borne supérieure : elle compte les lignes du correctif que les
tests exécutent. La contrainte compte, parmi celles-là, celles dont la
suppression casse au moins un test. Le produit des deux est ce que l'oracle
contraint réellement :

    contrainte effective = portée × (part des lignes couvertes qui sont tuées)

Ce module rend les trois chiffres côte à côte, puis **refait le test de taille
sur la contrainte effective**. C'est le point où l'article se joue : si l'effet
de taille ne tient que sur la portée et s'évanouit sur la contrainte, le
résultat principal était un artefact de la couverture.

On nomme les fichiers d'entrée explicitement. L'analyseur de portée acceptait un
motif et laissait « la dernière gagner » : une passe périmée a écrasé une passe
fraîche, tâche par tâche, et les chiffres d'avant sont sortis sous le titre
d'après sans un mot. On ne refait pas ça.
"""

from __future__ import annotations

import argparse
import json
import math
import statistics
import sys
from collections import Counter
from pathlib import Path

RACINE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))

from analyser import categorie, texte_des_lignes  # noqa: E402
from portee_oracle import classer_ajouts  # noqa: E402


def spearman(xs: list[float], ys: list[float]) -> tuple[float | None, float | None]:
    """Corrélation de rang et sa statistique t.

    Rang et non Pearson : la taille des correctifs est très étalée (1 à 200+
    lignes) et une poignée de gros correctifs dominerait une corrélation
    linéaire. Le rang demande seulement « quand la taille monte, la contrainte
    descend-elle ? », qui est la question posée.
    """
    if len(xs) < 4:
        return None, None

    def rangs(v: list[float]) -> list[float]:
        ordre = sorted(range(len(v)), key=lambda i: v[i])
        rg = [0.0] * len(v)
        i = 0
        while i < len(ordre):
            j = i
            while j + 1 < len(ordre) and v[ordre[j + 1]] == v[ordre[i]]:
                j += 1
            moyen = (i + j) / 2 + 1
            for k in range(i, j + 1):
                rg[ordre[k]] = moyen
            i = j + 1
        return rg

    rx, ry = rangs(xs), rangs(ys)
    mx, my = statistics.mean(rx), statistics.mean(ry)
    num = sum((a - mx) * (b - my) for a, b in zip(rx, ry))
    den = math.sqrt(sum((a - mx) ** 2 for a in rx) * sum((b - my) ** 2 for b in ry))
    if den == 0:
        return None, None
    rho = num / den
    n = len(xs)
    return rho, rho * math.sqrt((n - 2) / max(1e-12, 1 - rho**2))


def charger(chemin: str) -> dict[str, dict]:
    p = Path(chemin)
    lignes = [json.loads(x) for x in p.open(encoding="utf-8") if x.strip()]
    print(f"   lu {p.name:30} {len(lignes):4} lignes")
    return {x["instance_id"]: x for x in lignes}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--portee", required=True, help="resultats de lancer_mesure.py")
    ap.add_argument("--contrainte", nargs="+", required=True, help="resultats de contrainte.py")
    args = ap.parse_args()

    print("=== 0. Sources ===")
    portee = charger(args.portee)
    chemin_taches = RACINE / "data/tasks.jsonl"
    taches = ({json.loads(l)["instance_id"]: json.loads(l)
               for l in chemin_taches.open(encoding="utf-8") if l.strip()}
              if chemin_taches.exists() else {})
    contrainte: dict[str, dict] = {}
    for c in args.contrainte:
        contrainte.update(charger(c))
    print()

    # Une tâche ne compte que si les deux mesures ont abouti. Compléter l'une
    # par une hypothèse sur l'autre serait inventer le résultat.
    paires = []
    for iid, c in contrainte.items():
        p = portee.get(iid)
        if not p or p["statut"] != "ok" or p.get("part") is None:
            continue
        if c["statut"] != "ok":
            continue
        valides = c["tues"] + c["survivants"]
        if valides == 0:
            continue
        paires.append({
            "instance_id": iid,
            "repo": p["repo"],
            "mesurables": p["mesurables"],
            "portee": p["part"],
            "part_tuee": c["tues"] / valides,
            "effective": p["part"] * (c["tues"] / valides),
            "survivants": c["survivants"],
            "invalides": c["invalides"],
            "cumul_passe": c.get("cumul_passe"),
            "cumul_lignes": c.get("cumul_lignes", 0),
            "detail": c.get("detail") or {},
        })

    if not paires:
        print("(aucune tache avec les deux mesures)")
        return 1

    print(f"=== 1. Les trois chiffres ({len(paires)} taches avec les deux mesures) ===")
    for nom, cle in (("portee (lignes executees)", "portee"),
                     ("contrainte des couvertes", "part_tuee"),
                     ("contrainte effective", "effective")):
        v = [x[cle] for x in paires]
        print(f"   {nom:28} moyenne {statistics.mean(v):6.1%}   mediane {statistics.median(v):6.1%}")

    tot_mes = sum(x["mesurables"] for x in paires)
    tot_eff = sum(x["mesurables"] * x["effective"] for x in paires)
    print(f"\n   pondere par les lignes : {tot_eff:.0f}/{tot_mes} = {tot_eff/tot_mes:.1%} contraint")
    surv = sum(x["survivants"] for x in paires)
    print(f"   lignes executees mais libres : {surv}")
    print(f"   mutants ecartes (invalides)  : {sum(x['invalides'] for x in paires)}")
    plein = sum(1 for x in paires if x["effective"] >= 1)
    print(f"   taches entierement contraintes : {plein}/{len(paires)}")

    print("\n=== 2. L'ecart entre portee et contrainte, par tache ===")
    ecarts = sorted(paires, key=lambda x: x["portee"] - x["effective"], reverse=True)
    print(f"   {'tache':22} {'portee':>8} {'x tuees':>8} {'= effectif':>11}  {'ecart':>7}")
    for x in ecarts[:12]:
        print(f"   {x['instance_id']:22} {x['portee']:8.1%} {x['part_tuee']:8.1%} "
              f"{x['effective']:11.1%}  {x['portee']-x['effective']:+7.1%}")

    print("\n=== 3. Le test de taille, refait sur la contrainte effective ===")
    print("   (si l'effet ne tient que sur la portee, le resultat principal")
    print("    etait un artefact de la couverture)")
    for nom, cle in (("portee", "portee"), ("contrainte effective", "effective")):
        rho, t = spearman([x["mesurables"] for x in paires], [x[cle] for x in paires])
        if rho is None:
            print(f"   {nom:22} (echantillon trop petit)")
        else:
            print(f"   {nom:22} rho = {rho:+.3f}   t = {t:+.2f}   n = {len(paires)}")

    print("\n   par depot, sur la contrainte effective :")
    for d in sorted({x["repo"] for x in paires}):
        g = [x for x in paires if x["repo"] == d]
        rho, t = spearman([x["mesurables"] for x in g], [x["effective"] for x in g])
        if rho is None:
            print(f"      {d:20} n = {len(g):3}  (trop peu pour conclure)")
        else:
            print(f"      {d:20} n = {len(g):3}  rho = {rho:+.3f}  t = {t:+.2f}")

    print("\n=== 4. Par tranche de taille ===")
    print(f"   {'taille':10} {'n':>4} {'portee':>8} {'tuees':>8} {'effectif':>9} {'lignes libres':>14}")
    for bas, haut in [(1, 2), (3, 5), (6, 10), (11, 25), (26, 75), (76, 10**6)]:
        g = [x for x in paires if bas <= x["mesurables"] <= haut]
        if not g:
            continue
        etiq = f"{bas}-{haut}" if haut < 10**6 else f"{bas}+"
        print(f"   {etiq:10} {len(g):4} {statistics.mean(x['portee'] for x in g):8.1%} "
              f"{statistics.mean(x['part_tuee'] for x in g):8.1%} "
              f"{statistics.mean(x['effective'] for x in g):9.1%} "
              f"{sum(x['survivants'] for x in g):14}")

    print("\n=== 5. Ou sont les lignes executees mais libres ===")
    libres = [(x["instance_id"], f, n) for x in paires
              for f, ns in x["detail"].items() for n in ns]
    print(f"   {len(libres)} lignes, dans {len({(a, b) for a, b, _ in libres})} fichiers")

    # La nature des survivants, et le contraste qui en fait un resultat.
    #
    # Pour les lignes **jamais executees**, les levees et captures d'erreur ne
    # faisaient que 7,6 % : ce qui echappe a la couverture est du code
    # ordinaire. Pour les lignes **executees mais libres**, l'hypothese nee de
    # `fastapi_15661` est l'inverse — quatre de ses cinq survivants etaient des
    # gardes d'erreur que les tests traversent sans jamais declencher. On le
    # mesure sur le corpus plutot que de le raconter sur une tache.
    if taches:
        compte = Counter()
        exemples: dict[str, list[str]] = {}
        for x in paires:
            # `texte_des_lignes` rend des paires (fichier, texte). Les avoir
            # deballees a l'envers donnait « autre 100 % » — et c'etait le
            # signal : une vraie distribution ne tombe jamais dans un seul seau.
            for _, texte in texte_des_lignes(
                    {"instance_id": x["instance_id"], "detail": x["detail"]}, taches):
                cat = categorie(texte)
                compte[cat] += 1
                exemples.setdefault(cat, []).append(
                    f"{x['instance_id']}: {texte.strip()[:60]}")
        total = sum(compte.values())
        if total:
            print(f"\n   nature des {total} lignes retrouvees dans les correctifs :")
            for cat, n in compte.most_common():
                print(f"      {cat:20} {n:4} {n/total:6.1%}")
            print("\n   un exemple par categorie :")
            for cat, _ in compte.most_common():
                print(f"      {cat:20} {exemples[cat][0]}")
    else:
        print("   (tasks.jsonl absent : pas de categorisation)")

    # Ajout pur ou remplacement : ce que l'article peut affirmer en depend.
    #
    # Pour un **ajout pur**, un survivant veut dire exactement ce qu'on
    # voudrait : le correctif officiel prive de cette ligne passe quand meme.
    # Pour un **remplacement**, supprimer l'instruction retire aussi du
    # comportement anterieur au correctif, donc le programme obtenu n'est ni
    # l'avant ni l'apres, et « omet k lignes du correctif » devient inexact.
    # Ce que le survivant dit reste vrai et reste severe — l'oracle ne
    # distingue pas la reference d'un programme ou l'instruction est absente —
    # mais le mot doit changer.
    if taches:
        genre = Counter()
        par_genre: dict[str, list[str]] = {}
        for x in paires:
            cl = classer_ajouts(taches[x["instance_id"]]["patch"])
            for f, ns in x["detail"].items():
                for n in ns:
                    g = cl.get(f, {}).get(n, "inconnu")
                    genre[g] += 1
                    par_genre.setdefault(g, []).append(f"{x['instance_id']} {f}:{n}")
        tg = sum(genre.values())
        if tg:
            print(f"\n   nature du changement, pour les {tg} survivants :")
            for g, n in genre.most_common():
                print(f"      {g:14} {n:4} {n/tg:6.1%}   ex. {par_genre[g][0]}")
            purs = [x for x in paires
                    if x["survivants"] and all(
                        classer_ajouts(taches[x["instance_id"]]["patch"])
                        .get(f, {}).get(n) == "ajout"
                        for f, ns in x["detail"].items() for n in ns)]
            print(f"\n   taches dont TOUS les survivants sont des ajouts purs : "
                  f"{len(purs)}")
            print("   (seules celles-la autorisent la phrase « omet k lignes "
                  "du correctif officiel »)")
            for x in purs:
                etat = ("acceptee" if x.get("cumul_passe") else "cumul attrape")
                print(f"      {x['instance_id']:22} {x['survivants']} survivants  {etat}")

    print()
    for iid, f, n in libres[:15]:
        print(f"      {iid:20} {f}:{n}")
    if len(libres) > 15:
        print(f"      ... et {len(libres)-15} autres")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
