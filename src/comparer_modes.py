"""De combien le fichier entier surestimait-il la portée ?

Deux passes, deux sélections de tests :

- **fichier entier** — tous les tests du fichier que `test_patch` touche ;
- **nœuds exigés** — seulement les fonctions de test que `test_patch` introduit
  ou modifie, c'est-à-dire celles que le critère du concours exige.

La différence n'est pas un détail d'implémentation. Une ligne du correctif
atteinte par un test que le harnais n'exige pas ne pèse pas sur le score : la
compter comme contrainte crédite l'oracle d'une garantie qu'il ne donne pas.
Ce module chiffre l'écart, tâche par tâche, et dit aussi combien de tâches
chaque mode fait gagner ou perdre.

On nomme les deux fichiers explicitement. Les comparer suppose de savoir lequel
est lequel.
"""

from __future__ import annotations

import argparse
import json
import statistics
from pathlib import Path


def charger(chemin: str) -> dict[str, dict]:
    p = Path(chemin)
    lignes = [json.loads(x) for x in p.open(encoding="utf-8") if x.strip()]
    print(f"   lu {p.name:30} {len(lignes):4} lignes")
    return {x["instance_id"]: x for x in lignes}


def exploitable(x: dict | None) -> bool:
    return bool(x) and x["statut"] == "ok" and x.get("part") is not None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--fichier-entier", required=True)
    ap.add_argument("--noeuds", required=True)
    args = ap.parse_args()

    print("=== 0. Sources ===")
    avant = charger(args.fichier_entier)
    apres = charger(args.noeuds)
    print()

    print("=== 1. Ce que chaque mode mesure ===")
    for nom, d in (("fichier entier", avant), ("noeuds exiges", apres)):
        ok = [x for x in d.values() if exploitable(x)]
        mesurees = sum(1 for x in d.values() if x["statut"] == "ok")
        print(f"   {nom:16} {mesurees:3} mesurees, {len(ok):3} exploitables", end="")
        if ok:
            c = sum(x["couvertes"] for x in ok)
            t = sum(x["mesurables"] for x in ok)
            print(f"   moyenne {statistics.mean(x['part'] for x in ok):6.1%}"
                  f"   ponderee {c}/{t} = {c/t:6.1%}")
        else:
            print()

    modes = {}
    for x in apres.values():
        modes[x.get("mode") or "(absent)"] = modes.get(x.get("mode") or "(absent)", 0) + 1
    print(f"\n   mode de selection retenu : {modes}")
    replis = [x["instance_id"] for x in apres.values() if x.get("mode") == "fichier_entier"]
    if replis:
        print(f"   {len(replis)} taches sans noeud extractible, donc fichier entier :")
        for i in replis[:10]:
            print(f"      {i}")
        if len(replis) > 10:
            print(f"      ... et {len(replis)-10} autres")

    # Les deux ensembles de tâches exploitables ne coïncident pas : c'est la
    # moitié du résultat. Comparer les moyennes sur des assiettes différentes
    # mélangerait l'effet de la sélection et l'effet du changement d'assiette,
    # donc on compare d'abord à assiette constante.
    communes = [i for i in apres if exploitable(avant.get(i)) and exploitable(apres[i])]
    gagnees = [i for i in apres if exploitable(apres[i]) and not exploitable(avant.get(i))]
    perdues = [i for i in avant if exploitable(avant[i]) and not exploitable(apres.get(i))]

    print(f"\n=== 2. A assiette constante ({len(communes)} taches dans les deux) ===")
    if communes:
        pa = [avant[i]["part"] for i in communes]
        pb = [apres[i]["part"] for i in communes]
        print(f"   moyenne fichier entier : {statistics.mean(pa):6.1%}")
        print(f"   moyenne noeuds exiges  : {statistics.mean(pb):6.1%}")
        print(f"   ecart                  : {statistics.mean(pb)-statistics.mean(pa):+6.1%}")
        baisse = sum(1 for i in communes if apres[i]["part"] < avant[i]["part"] - 1e-9)
        hausse = sum(1 for i in communes if apres[i]["part"] > avant[i]["part"] + 1e-9)
        print(f"   taches en baisse : {baisse}   en hausse : {hausse}   "
              f"inchangees : {len(communes)-baisse-hausse}")

        print("\n   les plus grosses baisses :")
        pires = sorted(communes, key=lambda i: apres[i]["part"] - avant[i]["part"])
        print(f"      {'tache':22} {'entier':>8} {'noeuds':>8} {'ecart':>8}  lignes")
        for i in pires[:12]:
            if apres[i]["part"] >= avant[i]["part"] - 1e-9:
                break
            print(f"      {i:22} {avant[i]['part']:8.1%} {apres[i]['part']:8.1%} "
                  f"{apres[i]['part']-avant[i]['part']:+8.1%}  "
                  f"{apres[i]['couvertes']}/{apres[i]['mesurables']}")

    print(f"\n=== 3. Les taches que la selection change de camp ===")
    print(f"   gagnees par les noeuds ({len(gagnees)}) — un echec sans rapport les disqualifiait :")
    for i in gagnees[:12]:
        a = avant.get(i)
        print(f"      {i:22} {apres[i]['part']:6.1%}   avant : "
              f"{a['statut'] if a else 'absent'}")
    if len(gagnees) > 12:
        print(f"      ... et {len(gagnees)-12} autres")

    print(f"\n   perdues ({len(perdues)}) :")
    for i in perdues[:12]:
        b = apres.get(i)
        print(f"      {i:22} avant {avant[i]['part']:6.1%}   apres : "
              f"{b['statut'] if b else 'absent'}"
              f"{' — ' + (b.get('note') or '')[:50] if b else ''}")
    if len(perdues) > 12:
        print(f"      ... et {len(perdues)-12} autres")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
