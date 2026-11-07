"""Chaque chiffre de l'article est-il celui que les données rendent ?

**Pourquoi ce contrôle existe.** L'article annonçait « quatre clones, 179 Mo »
dans l'abrégé et sous *Availability*. Ils en font 197. Le 179 était vrai au
premier relevé, les clones grossissent à chaque fetch, et rien ne l'annonçait.
Dix pour cent d'écart sur un nombre cité deux fois n'est pas grave en soi — mais
un relecteur qui vérifie un chiffre et le trouve faux arrête de croire ceux
qu'il ne peut pas vérifier, et *Verifiability* est un cinquième de la note.

Ce module recalcule depuis `data/` ce que le texte affirme, et dit où ça
diverge. Il ne corrige rien : il signale, parce qu'un écart peut venir du texte
comme d'une passe refaite, et seul un humain sait lequel.

Usage :
    python src/verifier_article.py
    python src/verifier_article.py --article article/ARTICLE.md
"""

from __future__ import annotations

import argparse
import json
import math
import re
import statistics
from pathlib import Path

RACINE = Path(__file__).resolve().parent.parent


def charger(chemin: Path) -> list[dict]:
    return [json.loads(l) for l in chemin.open(encoding="utf-8") if l.strip()]


def spearman(xs: list[float], ys: list[float]) -> tuple[float, float]:
    def rangs(v: list[float]) -> list[float]:
        ordre = sorted(range(len(v)), key=lambda i: v[i])
        rg = [0.0] * len(v)
        i = 0
        while i < len(ordre):
            j = i
            while j + 1 < len(ordre) and v[ordre[j + 1]] == v[ordre[i]]:
                j += 1
            m = (i + j) / 2 + 1
            for k in range(i, j + 1):
                rg[ordre[k]] = m
            i = j + 1
        return rg

    rx, ry = rangs(xs), rangs(ys)
    mx, my = statistics.mean(rx), statistics.mean(ry)
    num = sum((a - mx) * (b - my) for a, b in zip(rx, ry))
    den = math.sqrt(sum((a - mx) ** 2 for a in rx) * sum((b - my) ** 2 for b in ry))
    rho = num / den
    n = len(xs)
    return rho, rho * math.sqrt((n - 2) / max(1e-12, 1 - rho**2))


def mesures() -> dict[str, str]:
    """Recalcule les chiffres de l'article. Les clés sont ce que le texte doit dire."""
    portee = charger(RACINE / "data/fichier-entier/resultats_accordes.jsonl")
    noeuds = charger(RACINE / "data/resultats_noeuds.jsonl")
    contr = {x["instance_id"]: x for x in charger(RACINE / "data/contrainte.jsonl")}

    util = lambda x: x["statut"] == "ok" and x.get("part") is not None
    ok = [x for x in portee if util(x)]
    okn = [x for x in noeuds if util(x)]

    out: dict[str, str] = {}
    out["taches du corpus"] = str(len(portee))
    out["mesurees (fichier entier)"] = str(sum(1 for x in portee if x["statut"] == "ok"))
    out["exploitables (fichier entier)"] = str(len(ok))
    out["moyenne de portee"] = f"{statistics.mean(x['part'] for x in ok):.1%}"
    c, t = sum(x["couvertes"] for x in ok), sum(x["mesurables"] for x in ok)
    out["portee ponderee"] = f"{c}/{t} = {c/t:.1%}"
    out["taches a 100 % de portee"] = f"{sum(1 for x in ok if x['part'] >= 1)}/{len(ok)}"
    indef = sum(1 for x in portee if x["statut"] == "ok" and x.get("part") is None)
    mes = sum(1 for x in portee if x["statut"] == "ok")
    out["portee indefinie"] = f"{indef}/{mes} = {indef/mes:.1%}"

    rho, tt = spearman([x["mesurables"] for x in ok], [x["part"] for x in ok])
    out["rho de la portee"] = f"{rho:+.3f} (t = {tt:+.2f}, n = {len(ok)})"
    for d, etiq in (("fastapi/fastapi", "fastapi"), ("Textualize/rich", "rich")):
        g = [x for x in ok if x["repo"] == d]
        r2, t2 = spearman([x["mesurables"] for x in g], [x["part"] for x in g])
        out[f"rho portee {etiq}"] = f"{r2:+.3f} (n = {len(g)})"

    gros = [x for x in ok if x["mesurables"] >= 26]
    cg, tg = sum(x["couvertes"] for x in gros), sum(x["mesurables"] for x in gros)
    out["gros correctifs (>=26)"] = (
        f"{len(gros)} taches, {tg}/{t} = {tg/t:.1%} des lignes, portee {cg/tg:.1%}")
    out["mediane de taille"] = f"{statistics.median(x['mesurables'] for x in ok):.0f}"

    # Mode noeuds, cite en section 7.
    out["mesurees (noeuds)"] = str(sum(1 for x in noeuds if x["statut"] == "ok"))
    out["exploitables (noeuds)"] = str(len(okn))
    out["moyenne noeuds"] = f"{statistics.mean(x['part'] for x in okn):.1%}"
    cn, tn = sum(x["couvertes"] for x in okn), sum(x["mesurables"] for x in okn)
    out["noeuds pondere"] = f"{cn}/{tn} = {cn/tn:.1%}"

    # Contrainte.
    paires = []
    for x in ok:
        k = contr.get(x["instance_id"])
        if not k or k["statut"] != "ok":
            continue
        valides = k["tues"] + k["survivants"]
        if valides == 0:
            continue
        paires.append({**x, "part_tuee": k["tues"] / valides,
                       "effective": x["part"] * k["tues"] / valides,
                       "survivants": k["survivants"], "invalides": k["invalides"],
                       "cumul": k.get("cumul_passe"), "cumul_lignes": k.get("cumul_lignes", 0)})
    out["taches avec les deux mesures"] = str(len(paires))
    tous = [v for v in contr.values() if v["statut"] == "ok" and (v["tues"] + v["survivants"])]
    out["mutants valides"] = str(sum(v["tues"] + v["survivants"] for v in tous))
    out["mutants ecartes"] = str(sum(v["invalides"] for v in tous))
    out["survivants"] = str(sum(v["survivants"] for v in tous))
    out["moyenne de contrainte des couvertes"] = (
        f"{statistics.mean(p['part_tuee'] for p in paires):.1%}")
    out["contrainte effective"] = (
        f"{statistics.mean(p['effective'] for p in paires):.1%} "
        f"(mediane {statistics.median(p['effective'] for p in paires):.1%})")
    ce = sum(p["mesurables"] * p["effective"] for p in paires)
    cm = sum(p["mesurables"] for p in paires)
    out["contrainte ponderee"] = f"{ce:.0f}/{cm} = {ce/cm:.1%}"
    out["entierement contraintes"] = (
        f"{sum(1 for p in paires if p['effective'] >= 1)}/{len(paires)}")

    r3, t3 = spearman([p["mesurables"] for p in paires], [p["effective"] for p in paires])
    out["rho de la contrainte"] = f"{r3:+.3f} (t = {t3:+.2f}, n = {len(paires)})"
    for d, etiq in (("fastapi/fastapi", "fastapi"), ("Textualize/rich", "rich")):
        g = [p for p in paires if p["repo"] == d]
        r4, _ = spearman([p["mesurables"] for p in g], [p["effective"] for p in g])
        out[f"rho contrainte {etiq}"] = f"{r4:+.3f} (n = {len(g)})"

    avec = [v for v in tous if v["survivants"]]
    acc = [v for v in avec if v.get("cumul_passe") is True]
    out["cumul accepte"] = f"{len(acc)}/{len(avec)} taches, max {max((v['cumul_lignes'] for v in acc), default=0)} lignes"

    for bas, haut, etiq in ((1, 2, "1-2"), (26, 75, "26-75"), (76, 10**9, "76+")):
        g = [p for p in paires if bas <= p["mesurables"] <= haut]
        if g:
            out[f"tranche {etiq}"] = (
                f"n={len(g)}, portee {statistics.mean(p['part'] for p in g):.1%}, "
                f"effective {statistics.mean(p['effective'] for p in g):.1%}")
    return out


LIMITE_MOTS = 3000


def compter_les_mots(texte: str, limite: int = LIMITE_MOTS) -> bool:
    """La limite de mots, qui n'etait verifiee nulle part.

    L'article annonce lui-meme « 3 000 word limit » en tete, et le depot porte
    un commit « Trim 234 words to make room for the sections that are not
    written yet » : le budget etait suivi — a la main. Les sections ajoutees
    ensuite l'ont depasse sans que rien ne le dise.

    On compte de quatre facons plutot qu'une, parce qu'on ignore laquelle
    Kaggle applique. Si la plus genereuse depasse deja, la question est
    tranchee sans avoir a deviner.
    """
    def mots(s: str) -> int:
        return len(re.findall(r"[A-Za-z0-9\u2019'\-]+", s))

    sans_code = re.sub(r"```.*?```", " ", texte, flags=re.S)
    sans_tableaux = "\n".join(x for x in sans_code.splitlines()
                              if not x.strip().startswith("|"))
    sans_titres = "\n".join(x for x in sans_tableaux.splitlines()
                            if not x.strip().startswith("#"))

    comptes = [("tout compris", mots(texte)),
               ("sans les blocs de code", mots(sans_code)),
               ("sans code ni tableaux", mots(sans_tableaux)),
               ("sans code, tableaux ni titres", mots(sans_titres))]

    print(f"=== Longueur, pour une limite de {limite} mots ===\n")
    for nom, n in comptes:
        print(f"  {nom:36} {n:5}  {'DEPASSE' if n > limite else 'ok'}")
    plus_genereux = min(n for _, n in comptes)
    if plus_genereux > limite:
        print(f"\n  La lecture la plus genereuse depasse de "
              f"{plus_genereux - limite} mots : aucune convention ne sauve ce "
              f"texte.\n")
        return True
    print("\n  Au moins une convention passe ; reste a savoir laquelle Kaggle "
          "applique.\n")
    return False


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--article", default=str(RACINE / "article/ARTICLE.md"))
    args = ap.parse_args()

    texte = Path(args.article).read_text(encoding="utf-8")
    trop_long = compter_les_mots(texte)

    print("=== Ce que les donnees rendent, et ce que l'article en dit ===\n")
    m = mesures()
    absents = []
    for cle, valeur in m.items():
        # On cherche chaque nombre de la mesure dans le texte, en tolerant la
        # virgule decimale et le signe moins typographique.
        # On normalise le texte avant de chercher : l'article ecrit « 1 575 »
        # et « 1 437 of 2 004 » avec une espace de milliers (y compris
        # insecable), que `1575` ne retrouverait pas. Les trois premieres
        # alertes de cet outil etaient de ce genre, et un controleur qui crie
        # au loup ne sera plus lu.
        plat = texte.replace("−", "-").replace(",", "")
        for espace in (" ", " ", " ", " "):
            plat = re.sub(r"(?<=\d)" + espace + r"(?=\d)", "", plat)
        nombres = re.findall(r"\d+\.\d+|\d+", valeur)
        manquants = [n for n in nombres if n not in plat]
        etat = "ok" if not manquants else "A VERIFIER : " + ", ".join(manquants)
        if manquants:
            absents.append(cle)
        print(f"  {cle:36} {valeur:52} {etat}")

    print(f"\n{len(m)} mesures, {len(absents)} dont au moins un nombre"
          " n'apparait pas tel quel dans l'article.")
    if absents:
        print("\n(Un nombre absent n'est pas une erreur : l'article peut l'avoir")
        print(" arrondi, reformule ou volontairement omis. C'est une liste a relire,")
        print(" pas un verdict.)")
        for cle in absents:
            print(f"   - {cle}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
