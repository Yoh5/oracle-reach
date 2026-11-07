# oracle-reach

**How much of a reference patch do a benchmark's validation tests actually constrain?**

This repository is the tool and the per-task results behind the paper
*How much of a patch does the oracle actually constrain?*, submitted to the
Kaggle **Gemma 4 Developer Agent Paper Track** (the paper is in
[`article/ARTICLE.md`](article/ARTICLE.md)).

For each task of an execution-based benchmark it applies the reference patch
and the validation tests at `base_commit`, runs the harness's own pytest command
under coverage, and measures:

- **oracle reach** — the share of the lines the patch adds that the tests execute;
- **effective constraint** — the share that the tests also *need*: each covered
  statement is replaced by `pass` and the oracle re-run; a line that survives
  executes but is free.

On the 129 public tasks of the Gemma 4 SWE corpus: mean reach 92.1%, effective
constraint 80.2%, and both fall with patch size (Spearman ρ = −0.512 and −0.429,
n = 100), inside each repository.

It needs no GPU, no container and no model.

## Contents

| path | what it is |
|---|---|
| `src/lancer_mesure.py` | runner: oracle reach per task (`--selection fichier` = whole target files, as the harness runs them; `noeuds` = only the tests `test_patch` touches) |
| `src/contrainte.py` | statement-deletion mutation of every covered line, plus the cumulative deletion |
| `src/portee_oracle.py` | diff parsing, coverage intersection, addition/replacement classification |
| `src/analyser.py`, `src/analyser_contrainte.py`, `src/comparer_modes.py` | the analyses reported in the paper |
| `src/verifier_article.py` | recomputes every figure of the paper from the result files and lists any number absent from the text |
| `src/transfert_swebench.py` | the attempted transfer to SWE-bench Verified, reported as a failure in §9 |
| `data/fichier-entier/`, `data/resultats_noeuds.jsonl`, `data/contrainte.jsonl` | per-task results for all 129 tasks, both selection modes, and the mutation pass |
| `data/swebench/transfert.jsonl` | the failed transfer, instance by instance, with the error |
| `notes/METHODE.md` | how the measure works, and every defect found in the instrument itself |
| `notes/RESULTATS.md` | the full results note |

The code and notes are written in French; the paper is in English.

## Reproducing the paper's figures (no download needed)

```
python -m pip install pytest coverage
python -m pytest -q tests
python src/verifier_article.py
python src/analyser.py data/fichier-entier/resultats_accordes.jsonl
python src/comparer_modes.py --fichier-entier data/fichier-entier/resultats_accordes.jsonl --noeuds data/resultats_noeuds.jsonl
python src/analyser_contrainte.py --portee data/fichier-entier/resultats_accordes.jsonl --contrainte data/contrainte.jsonl
```

Every analyser is given its input explicitly: none of them picks files by pattern.

## Re-running the measurement

The competition data is not redistributed here. To re-run the measurement:

1. Download `tasks.jsonl` from the
   [competition data page](https://www.kaggle.com/competitions/gemma-4-developer-agent/data)
   into `data/`, and the harness wheels into `harnais/wheels/`.
2. Clone the four repositories into `repos/`:
   ```
   git clone https://github.com/fastapi/fastapi.git repos/fastapi
   git clone https://github.com/Textualize/rich.git repos/rich
   git clone https://github.com/psf/requests.git repos/requests
   git clone https://github.com/encode/httpx.git repos/httpx
   ```
3. Run, one pass after the other (the runner mutates a shared virtual environment):
   ```
   python src/lancer_mesure.py --taches data/tasks.jsonl --sortie data/portee.jsonl
   python src/contrainte.py --taches data/tasks.jsonl --sortie data/contrainte.jsonl
   ```

Measured on Windows with Python 3.12. Two `requests` tasks hang under Windows
sockets; each test is capped at 60 seconds (paper, §3).

## License

Apache License 2.0 — see [`LICENSE`](LICENSE).
