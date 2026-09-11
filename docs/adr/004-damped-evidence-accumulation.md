# ADR-004: Damped Evidence Accumulation Across Cache Layers

## Status

Accepted

## Context

BitMod's cache engine consults nine layers for every query. Each layer that finds a candidate contributes a piece of evidence with a confidence, and the engine combines them into a single number that the serve decision is made against.

The combination is noisy-OR: each layer is treated as an independent chance to be right, and the total is one minus the probability that all of them are wrong. This is the standard way to pool independent evidence, and it assumes the layers are conditionally independent given the label.

They are not. Semantic similarity and fuzzy similarity are computed from the same two strings. When both fire, they are not two witnesses agreeing — they are one signal read twice through different instruments. Noisy-OR has no way to know that, so it treats the second reading as fresh evidence and raises the total accordingly.

This predicts a specific, checkable failure: confidence should be accurate where one layer contributed, because nothing was combined and the assumption was never used, and should overstate progressively as more layers contribute. That is what we measure.

Claimed confidence minus observed duplicate rate, bucketed by how many layers contributed:

| contributing layers | n | mean claimed | observed | claimed − observed |
|---|---|---|---|---|
| 1 | 503 | 0.676 | 0.682 | −0.006 |
| 2 | 138 | 0.923 | 0.797 | **+0.126** |
| 3 | 5 | 0.986 | 0.600 | **+0.386** |

Measurement conditions: 1,000 human-labelled pairs from `sentence-transformers/quora-duplicates` (pair-class, train split), embedder `ollama/nomic-embed-text`, entity guard enabled. Artifact `tests/benchmark/results/accumulation_fit.json`, produced by `tests/benchmark/fit_accumulation.py` at commit `3229d6dc` against a dirty tree with 12 untracked files.

Note that the single-layer control row is negative here (−0.006) where earlier row sets measured it positive (+0.011). Both are inside ±0.01 and the conclusion is unchanged: confidence is accurate to within a hundredth where nothing was combined. The sign of a residual that small carries no information; its magnitude does.

Two things about this table constrain how much weight it can carry.

The single-layer row is the control, and it is the important one. No combining happened there, so the accumulated value is whatever the one layer said, and it is accurate to within 0.01. The error is absent exactly where the independence assumption is unused and present exactly where it is used. That localises the defect to the combination step rather than to any layer's own confidence, which is what justifies correcting only the combination.

The three-layer row rests on five observations. It is directionally consistent with the two-layer row and nothing more; it is not a quantity anything should be fitted to. Three or more layers contributing is rare in this corpus.

## Decision

The gain that combining adds over the strongest single piece of evidence is damped by a constant. The strongest single piece passes through untouched.

```
pos_total = best + (pos_total - best) * accumulation_damping
```

Applied at `core/bitmod/cache_engine.py:1336`, only when more than one layer contributed positive evidence, and gated on the `calibrated_confidence` flag. `accumulation_damping` defaults to `0.50` (`core/bitmod/config.py:324`, overridable via `BITMOD_CACHE_ACCUMULATION_DAMPING`).

Three properties follow from damping the gain rather than the total. A single contributing layer is unchanged, which is correct because it is already calibrated. An exact match still means 1.0, because there is no gain over a best piece that is already certain. And the undamped noisy-OR total remains the ceiling — combining always adds something, just less than it claimed.

**Why 0.5.** It is the a priori midpoint between the two defensible extremes: treating the layers as fully independent, which is what noisy-OR already does and which the table shows is wrong, and treating agreement between them as carrying no information at all, which is equally indefensible because the layers are correlated but not identical. The value was chosen on that reasoning before any outcome was measured.

**0.5 is not a fitted value, and this corpus cannot fit it.** Fitting the constant against the available benchmark data was recorded at the time as yielding 0.00 on the quora passes, 1.00 on the conversational passes, and 0.77 combined — no two agreeing, and none of them 0.5. No artifact in `tests/benchmark/results/` reproduces these three figures, and no script in the repository fits a damping constant, so they cannot be re-derived as stated. What the argument rests on is not their magnitudes but the fact that fits over different pass subsets disagreed with each other, which is the expected consequence of how the benchmark is constructed: every pass is entirely positive or entirely negative by design, so a fit recovers the base rate of whichever pass it was run against rather than the correlation between layers. A constant chosen that way would be fitted to the shape of the test harness. That is precisely the reasoning this ADR rejects, and it is why the value is set from the prior rather than from the data. The mechanism is recorded in ADR-004's own history: figures that went from working notes into an artifact remained verifiable; figures that went from working notes straight into a code comment did not.

**Outcomes at the chosen value.** Three full benchmark runs, all at `serve_threshold=0.85`, all 4,600 queries, same dataset and embedder, one variable moving:

| damping | paraphrase recall | rewrite recall | wrong answers | per 1,000 | artifact |
|---|---|---|---|---|---|
| 0.25 | 33.0% | 20.7% | 7 | 1.5 | `inprocess_calibrated.json` |
| **0.50** | **40.4%** | **28.1%** | **8** | **1.7** | `inprocess_damp050.json` |
| 1.00 | 51.6% | 75.3% | 37 | 8.0 | `inprocess_damp100_at085.json` |

Rates are per 1,000 over the full 4,600-query run. Wrong answers are counted on the 3,900 label-checked queries; against that denominator the rates are 1.8, 2.1 and 9.5. The ranking is unaffected, as is every conclusion below.

Provenance of these three artifacts is uneven and is recorded here rather than smoothed over. The first two predate `tests/benchmark/provenance.py` and carry no fingerprint. The third carries `147b6cf4/e3b0c442` recording a clean tree, but the run was launched against a dirty one; because Python imports at launch, its numbers describe the code that ran, while its fingerprint does not identify that code. What makes the comparison valid is not the fingerprints but the conditions: all three runs used the same dataset, the same embedder, the same `serve_threshold`, and the same harness, with damping as the only variable.

**Error budget: no more than 6 wrong answers per 1,000.** This is a product judgement, not a measurement. It was set at roughly 1.5× the then-current measured rate of 3.9 per 1,000 (18 false positives in 4,600), on the reasoning that a support and documentation cache can absorb some wrong answers but not triple the current rate. It is not derived from a cost model, an SLA, or user research, and it has a single author rather than a source.

It also inherits the benchmark's composition. The corpus is half hard negatives by construction — 500 labelled duplicate pairs against 500 labelled non-duplicates, deliberately confusable. Real traffic is not built that way. Both the 3.9 that anchored the budget and the 8.0 that breaches it are drawn from that same adversarial mix, so they are an upper bound on production error rather than a forecast of it. Because both sides of the comparison use the same ruler, the comparison holds; neither number should be quoted as a production figure.

What would replace this budget: an estimate of what a wrong cached answer actually costs in a given deployment, or a measured false-positive rate on real traffic.

**Damping 0.5 does not rest on the budget.** The a priori argument stands on its own: noisy-OR uses an assumption the layers violate, the violation is measured, and the correction is set from the prior because the data cannot set it. The budget is the second reason, not the first. If the budget were 10 per 1,000, damping 1.00 would fall inside it and 0.5 would still be the choice, because full weight is the value the measurement says is wrong.

**What would be needed to fit the constant properly.** A labelled corpus whose passes contain both positive and negative cases in the same pass, at a base rate resembling production traffic, with enough queries where three or more layers contribute to make that bucket meaningful. Given that, the damping constant becomes a fitted calibration with a held-out score. Without it, the constant is a conservatism control set from the prior, and should be described as one.

## Consequences

**What becomes easier:**

- The cases that were already calibrated are provably untouched. A single contributing layer passes through unchanged, and an exact match still means certainty, so damping cannot introduce error where there was none.
- Wrong answers run at 1.7 per 1,000 rather than the 8.0 that undamped accumulation produces at the same serve threshold — a fifth of the error rate for a quarter of the paraphrase recall.
- The correction is one named constant in one place, with its reasoning attached, rather than a set of hand-tuned per-layer confidences. Changing it is a one-line experiment, and `BITMOD_CACHE_CALIBRATED=false` disables it entirely for comparison.
- `serve_threshold` stays free to act as the operational dial. Conservatism about layer correlation and conservatism about when to serve are separated, so tuning one does not silently move the other.

**What becomes harder or requires care:**

- Recall is left on the table. Paraphrase recall is 40.4% against 51.6% at full weight, and rewrite recall 28.1% against 75.3%. That gap is the price of the error rate, and it is a real cost, not a rounding difference.
- **The constant cannot be improved by sweeping it against the current benchmark.** Any value a sweep selects is fitted to pass construction, which is the reasoning rejected above — so a sweep would not refine the decision, it would remove its justification. Improving on 0.5 requires building a corpus with mixed-outcome passes at a realistic base rate. That is corpus work, not tuning work.
- The constant is a conservatism control, not a calibration, and must not be described as calibrated. Nothing about 0.5 claims the damped total is now an accurate probability; it claims only that it overstates less.
- `serve_threshold` currently sits at 0.85, derived when damping was 0.25. It has not been re-derived at 0.5, so the operating point is a value chosen under a different accumulation rule. Re-deriving it is open work.
- The evidence for three or more contributing layers is n=5. Any future change whose justification leans on the three-layer case needs a larger sample first.
