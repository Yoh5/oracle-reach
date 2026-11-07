# How much of a patch does the oracle actually constrain?

**A measurement of oracle reach on the Gemma 4 SWE corpus, and a tool to repeat it.**

*Target category: Best New Resource.*

---

## Abstract

A benchmark that scores a code-repair agent by running a validation suite
measures agreement with that suite, not correctness. We make the gap measurable.
For each of the 129 public tasks in the Gemma 4 SWE corpus we apply the
reference patch and the validation tests, run the harness's own pytest command
under coverage, and intersect the executed lines with the lines the patch adds.
We call that fraction the patch's **oracle reach**.

Reach is high — mean 92.1% over the 100 tasks where it is defined — so the
hypothesis that these oracles are weak is refuted. What matters is that reach is
not uniform: it falls with patch size (ρ = −0.512, n = 100), inside each
repository, and with every unmeasured task taken at a lower bound. None
of the 6 patches above 76 lines is fully constrained, against 27 of 28 one- and
two-line patches. **A benchmark score is most trustworthy where the task is
easiest and least trustworthy where it is substantial.**

Reach only bounds constraint from above, so we also delete each covered
statement and re-run the oracle. A survivor is a line that executes and is free:
**effective constraint is 80.2%**, and **the size effect survives** at
ρ = −0.429 — the decline is not an artifact of coverage. Deleting all of a
task's survivors at once is accepted in **40 of 47 tasks**, omitting up to
twenty-two lines. Restricting the run to the tests `test_patch` touches drops
reach to 88.0%: much of the oracle's grip is **incidental**.

Weak oracles and patch-region coverage are documented before (STING, arXiv
2604.01518); §2 states what we add. The published tool runs offline from four
git clones (197 MB), with no GPU and no container.

---

## 1. Introduction — the score is an agreement, not a proof

The harness's verification command is explicit (`HARNESS_README`, §8.2):
`pytest <pytest_targets> -p no:anyio -o timeout=0 -o python_classes="Test*
*Test" -q`, with a JUnit report. A task is resolved when it exits zero **and**
the report shows `passed_tests > 0, failures == 0, errors == 0`, every required
node (`FAIL_TO_PASS`, `PASS_TO_PASS`, or the test functions extracted from
`test_patch`) explicitly passed, not skipped.

Two things follow, the second easy to get wrong. The targets are the test
**files** `test_patch` touches, with no `-k` selection: every test in those
files must pass. The required-node list is an *additional* check against a
silently skipped node, not a restriction of what runs. **The oracle is
the whole target file.**

So the score measures agreement with `test_patch`, written by the same human,
in the same commit, as the reference patch it validates. That is not a
criticism; it is what any execution-based benchmark must do. But it raises a
question the score cannot answer about itself: **when an agent
reproduces behaviour the target files never exercise, the benchmark cannot tell
whether it got that behaviour right.**

## 2. Related work — what is already known, and what is not

Weak oracles in issue-resolution benchmarks are well documented, and the
headline numbers depend sharply on definition. **SWE-Bench+** (arXiv 2410.06992)
judged 31.08% of 251 passing patches on SWE-bench *Full* suspicious for weak
tests; **PatchDiff** (ICSE 2026) finds 29.6% of plausible patches behave
differently from ground truth; **SWE-ABS** reports the best agent falling from
78.80% to 62.20% once tests are strengthened. **SWE-Mutation** (Findings of ACL
2026) asks instead whether *LLMs* can write discriminating suites.

Closest to us is **STING** (arXiv 2604.01518), which probes Verified with
semantically modified variants: 77% of instances admit at least one survivor. It
measures line and branch coverage over the patch region, and lowers the top ten
agents' resolved rates by 4.2 to 9.0 points.

So "the oracles are too weak" is not our contribution, and neither is "how much
of the patch region do the tests cover" — STING measures it. **What remains
unreported is what this paper is for:**

1. **How oracle reach varies with patch size.** None of the above examines it.
   We find a strong monotone decline, replicated inside each repository and
   robust to every unmeasured task.
2. **How much of the reach is incidental** (§7) — on some tasks the difference
   between 100% and 12.5%.
3. **On the competition's own corpus and verification command**, not Verified.
4. **Omission specifically.** STING's variants probe behaviour; deletion asks
   whether a line is constrained against *its own absence* — for some tasks,
   the official fix minus k lines, scored as resolved (§6).

## 3. Method — what we measure

For a task with reference patch `P` and validation tests `T`:

1. Check out `base_commit` in a detached worktree.
2. Apply `P`, then `T`.
3. Run the harness's command on the target files, under line coverage.
4. Let `A` be the lines `P` adds that coverage treats as measurable statements,
   and `E ⊆ A` those executed. **Oracle reach** is `|E| / |A|`.

Three choices are worth defending.

**Reach is undefined, not zero, when `A` is empty.** coverage.py counts
statements; a line inside a multi-line call is not one. Scoring such a task 0%
would claim the oracle reaches nothing where there is nothing to reach; 100%
claims the opposite. They are excluded and counted: **12 of 112 measured
tasks (10.7%)**.

**A task counts only if the oracle is green.** An interrupted collection
executes nothing, so the task surfaced at 0% with an `ok` status — read as "the
oracle constrains nothing" when no measurement had occurred. Twenty-two of the first
forty-five fell into that hole.

**One declared deviation.** The harness passes `-o timeout=0`; we cap each test
at 60 seconds, because two `requests` tasks hang under Windows sockets. The cap
changes no verdict, turning a silent timeout into a named failure.

## 4. Results

| | |
|---|---|
| tasks in corpus | 129 |
| measured | 112 |
| reach defined, usable | **100** |
| mean reach per task | **92.1%** |
| lines covered / measurable | **1671 / 2004 = 83.4%** |
| tasks at 100% | 67 / 100 |

**The starting hypothesis is refuted.** At 92.1% mean
reach with two thirds of tasks fully constrained, the validation suites of this
corpus are strong.

**But the two aggregates disagree by nine points, and that is the finding.** A
mean over tasks treats a 2-line patch like a 200-line one; a line-weighted share
does not. They can only diverge this far if reach depends on patch size.

## 5. Reach degrades with patch size

| patch size (measurable lines) | n | mean reach | lines | at 100% |
|---|---|---|---|---|
| 1–2 | 28 | **98.2%** | 39/40 | 27/28 |
| 3–5 | 19 | 93.2% | 70/75 | 14/19 |
| 6–10 | 21 | 91.7% | 145/158 | 16/21 |
| 11–25 | 14 | 95.7% | 209/218 | 9/14 |
| 26–75 | 12 | **79.1%** | 451/569 | 1/12 |
| 76+ | 6 | **79.4%** | 757/944 | **0/6** |

Spearman ρ = −0.512 (t = −5.90, n = 100).

**Confound one: the repository.** Large patches might be one repository's
habit. They are not — the relation holds inside each repository with enough
tasks to test, at the same median patch size on both sides.

| repository | n | ρ | t |
|---|---|---|---|
| fastapi | 59 | −0.551 | −4.98 |
| rich | 36 | −0.389 | −2.46 |

**Confound two: the tasks we could not measure.** Seventeen fail their oracle
on our platform, and dropping them could flatter the result. For 13 a restricted run
still yields a **lower bound**; including all 13 at that bound moves ρ from −0.512 to −0.497 (t = −6.03, n = 113). The effect does not
live in the missing tasks.

**It is a tendency, not a law.** `fastapi_14262` adds 109 measurable lines and
reaches 93.6%: large, well-constrained patches exist. The claim is that reach
degrades with size — never that large patches go untested.

**Why it matters.** The corpus median patch is 6 measurable lines, and 28 of
100 tasks add one or two, where any test entering the function returns 100%
without constraining anything. The mean is carried by the easy
end. At the other end, 18 patches of 26+ lines hold **75.5% of all measurable
lines** (1513 of 2004) and reach **79.8%**.

The benchmark's guarantee is therefore not uniform, and it weakens exactly on
the tasks that justify having a benchmark.

## 6. From reach to constraint: mutating the covered lines

Executing a line is necessary to constrain it, not sufficient: a line can run
with no assertion depending on its effect. For every covered line of every
reference patch we replace the statement with `pass` and re-run the oracle. A
**survivor** is a line that executes and is free.

Statement deletion is the operator the question asks for, and the strongest:
a line surviving deletion survives any finer mutation. Invalid mutants (a
decorator, an `else:` header, an emptied block) are **detected by re-parsing,
not enumerated** — a list of pathological cases is one you forget to finish, and
counting an uncompilable mutant as killed would inflate the result in our
favour. Statements whose removal omits nothing are excluded by construction. A
collection error counts as killed: deleting an `import` breaks the module, an
omission the oracle does detect.

**Results.** Over the 100 tasks with both measurements, 1 575 valid mutants were
built (96 excluded as uncompilable or effect-free) and 221 survived.

| | mean | median |
|---|---|---|
| reach — lines executed | 92.1% | 100% |
| of those, killed by deletion | 86.1% | 100% |
| **effective constraint** | **80.2%** | 92.6% |

Line-weighted, 1 437 of 2 004 lines are constrained: **71.7%**. Only 49 of 100
tasks are fully constrained, against 67 by reach alone — **reach over-estimates
by twelve points on the mean and by eighteen tasks.** Two tasks have reach of
100% and constraint of 0%: each adds one line, executes it, and the oracle
cannot tell it from its absence.

**The size effect survives the mutation**, which is the test this section exists
for. Had the decline lived only in coverage, the result would have been an
artifact:

| | ρ | t | n |
|---|---|---|---|
| reach | −0.512 | −5.90 | 100 |
| **effective constraint** | **−0.429** | **−4.70** | 100 |

It holds inside each repository (fastapi −0.432, n = 59; rich −0.365, n = 36),
and by bucket the floor is lower than reach suggested: 89.3% for one- and
two-line patches, **64.8% for 26–75 lines and 68.0% above 76**. A third of a
large reference change is constrained by nothing.

**And the survivors are a different kind of line from the unreached ones.**
Among lines never executed, guards were 8.6%; among lines executed but free they
are **33.9%** — a fourfold shift — while imports fall from 16.9% to 7.7%. The
oracle walks through the condition and never trips it.

**What a survivor licenses one to say needs care.** The oracle does not
distinguish the reference solution from a program where that statement is
absent. For a **pure addition** that is exactly "the official fix minus this
line still passes". For a line that **replaces** one the same patch deletes, the
mutant is a third program — the finding stays true, arguably harsher, but the
wording becomes "differs from the reference in k statements". **72% of survivors
are replacements**, so the distinction matters.

Deleting *all* of a task's survivors at once: **40 of the 47 tasks with
survivors accept it**, from one line omitted up to twenty-two.
Sixteen tasks have survivors that are all pure additions, and fifteen accept the
cumulative deletion — for them, "the official fix minus k lines scores as
resolved" is exact.

On `fastapi_15661`, whose covered lines are 93.4% killed, the four survivors are
removed together and the oracle still passes. They are error guards the required
tests walk through without ever tripping:

```
if not match:
if len(matches) != 1:
if not content.startswith(RELEASE_NOTES_HEADER):
if not content.startswith(latest_header):
```

A program a reviewer can read, omitting four lines the official fix adds,
which this benchmark scores as resolved.

**The cumulative deletion does not always survive**, and the seven exceptions
are the large ones. `fastapi_14099` has 17 individual
survivors, yet removing 16 together is caught. Lines unconstrained one at a time
interact once all are gone, so small cumulative omissions pass and large ones
get caught — the size effect again, from the other direction.

## 7. Where the reach comes from: the incidental share

The oracle is the whole target file, so a patch line counts as reached even
when the only test touching it has nothing to do with the change. We re-ran
everything restricted to the test functions `test_patch` introduces or modifies,
found by mapping its added lines onto the parsed post-patch file —
not by `grep '+def test_'`, which misses tests whose body the patch only
edits.

| | measured | usable | mean | line-weighted |
|---|---|---|---|---|
| harness command (whole files) | 112 | 100 | 92.1% | 83.4% |
| change-targeting tests only | 126 | 113 | 88.0% | 77.6% |

On the 100 tasks common to both, the mean falls 4.8 points with **19 tasks
down and none up**. Individual cases are starker: `fastapi_15023` goes from 16
of 16 covered lines to 2 of 16, its `test_patch` modifying one existing test
while fifteen others in the file incidentally execute the patched code.

So part of the benchmark's grip is real but **incidental**. It counts — the
criterion requires those tests to pass — but it does not come from anyone deciding
to check this change, and will not survive a refactor that moves tests around.

## 8. Discussion — what reach and constraint do not mean

**Full constraint does not make a suite adequate.** In an append-only hash-chained ledger we built outside this corpus (220
tests), the verifier hashes a whitelist of body keys: adding `"severity":
"benign"` to a sealed record left `verify()` answering *the chain holds*.
Coverage was complete and every mutant of the hashing code died. No test ever built a
record with an unknown key, so the defect had neither an uncovered line nor a
mutant: invisible to both measurements here.

**A suite proves the rules it was written from, and only those.** Reach and
constraint measure how much of a change the rules touch. Neither can measure
rules nobody wrote.

## 9. Limitations, declared

**A mutant killed by a crash is killed because the code breaks, not because an
assertion checks behaviour.** "The omission would be seen" stays true, but not
for the reason one might assume.

**Deleting a statement can make later patch statements unreachable**, so one
mutation sometimes tests more than one line.

**A survivor on a replaced line is not an omission.** 72% of survivors sit in
hunks that also delete lines; the clean "fix minus k lines" reading is reserved
for tasks whose survivors are all pure additions. Our split is at hunk granularity,
which over-counts replacements — the approximation errs toward the
reading that restrains us.

**Undefined reach: 10.7%**, reported per task.

**Seventeen tasks unmeasured**, sensitivity analysis in §4.
Two hang on this platform; the rest fail their oracle in our environment, which
a clean Linux sandbox may not reproduce.

**Four repositories**, Python only, all library code. Whether reach degrades
with size in application code, or in other languages, is open.

**We could not validate the transfer.** The method needs only a
`(base_commit, patch, test_patch, test runner)` quadruple, so it should apply to any
execution-based benchmark; we tried SWE-bench Verified. It failed from this
machine: those commits span 2013 to 2023 and break on language removals (`collections.MutableMapping` gone in 3.10), on floors their own
pyproject permits but never tested, and on era-specific build chains. SWE-bench
ships one container per instance for exactly this reason; without containers we
reproduced five distinct causes and measured nothing. Publishing a transfer over
the three instances that happened to install would be selection bias dressed as
generalization.

**One corpus.** The size effect is tested against two confounds and replicated
across two repositories. It is not replicated across benchmarks.

## 10. What to do with this

**Reading a benchmark.** Read a resolution rate alongside the size
distribution of its tasks. A corpus of one- and two-line patches at 98.2% reach
measures something close to agreement with a strong oracle; a corpus whose lines
live mostly in large patches does not: the same percentage means less.

**Building one.** Reach costs no GPU, no container and no model, so it can be
published per task beside the resolution criterion — turning "resolved" into
"resolved, with the oracle constraining 80% of the reference change, a quarter
of that only incidentally."

**Training on one, which is what this competition is about.** A resolution
verdict is a reward signal, and reach measures how much of the intended change
that signal witnesses. A task whose oracle constrains 65% of the reference fix
rewards a two-thirds-right patch indistinguishably from a wholly right one. For
post-training that is systematic bias, not noise: the gradient is strongest on
tiny patches, where the oracle is near-perfect and the task easiest, and weakest
on substantial ones. Reach is cheap enough to compute over a whole training
corpus, so it can weight the reward or filter the corpus.

## 11. Availability and reproduction

We publish the runner, the mutation tool, the analysers, per-task results for
all 129 tasks in both selection modes, and a method note recording every defect
found in our own instrument, at https://github.com/Yoh5/oracle-reach (Apache 2.0).

```
python src/lancer_mesure.py --taches data/tasks.jsonl --sortie data/portee.jsonl
python src/contrainte.py --taches data/tasks.jsonl --sortie data/contrainte.jsonl
```

Each analyser is given its input explicitly and refuses to guess when several
passes match its pattern — one once let a stale pass overwrite a fresh one, task
by task, and printed pre-fix numbers without a word.
