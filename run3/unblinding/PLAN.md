# Staged unblinding plan — tight-WP 2024+2025 Z' → tt̄

**Status: GATE 1 PAUSED — hard gate 1.4 failed as written; forensics show a pre-existing blinded condition that SR data IMPROVE. GoF not run. Awaiting Aritra's ruling (options A/B in the decision log).**

This is the living checklist for unblinding. Maintained in-repo on the
`unblinding` branch (`run3/unblinding/PLAN.md`); every gate's outcome is
recorded here *and* in research-notes when it happens. The frozen blinded
state is tag `blinded-freeze-20260814` (= `1085d9a`, branch `cmslpc-el9`);
quotable blinded result: research-notes
`topics/ttbarhadronic_tightwp_2425_finegrid_result.md`.

**Prime rule: the criteria below were fixed while blind (2026-08-14) and may
not be loosened after any SR data are seen. Deviations must be documented
here as deviations, not silently absorbed.**

Model (frozen): cen 2x2 + fwd 2x0 TFs, nine nuisances (jes, jer, pileup,
pdf, q2, ttag_pt1, lumi24, lumi25, ttbar_xsec), 1 pb signal normalization,
masses ≥ 1.2 TeV. Known quoted caveats (do NOT block gates): no
template-MC-stat nuisances; 10–15% high-mass signal absorption; w1 M7000
85.7% in-window.

---

## Gate 0 — freeze closeout (blind)

| item | criterion | status |
|---|---|---|
| bgestimation frozen | commits `16f1811` + `1085d9a`, tag `blinded-freeze-20260814` | ☑ done 2026-08-14 |
| push branch + tag + `unblinding` to origin | Aritra (needs credentials) | ☑ done 2026-08-14 — origin has `cmslpc-el9` @1085d9a, `unblinding` @ba762da, tag `blinded-freeze-20260814` (pushed from the Mac clone via the new `lpc` remote; the Mac's ssh config was missing its github.com block) |
| 2x0 injection spot check (w1 m2000 + m6000, bkg/half/one/two) | same gates as the validation campaign: per-fit status ∈ {0,1}, covQual ≥ 2, EDM ≤ 0.1; three-start agreement Δr < 0.1σ, ΔNLL < 0.02; bkg closure \|r̂\| < 0.1σ; recovery within the established envelope (≥ 0.95 at 2 TeV, 0.80–0.95 at 6 TeV) | ☑ **PASS 8/8** (2026-08-14, cluster 85129252): closure exact; recovery 0.981–0.984 (2 TeV) / 0.824–0.865 (6 TeV); Δr/σ ≤ 0.014, ΔNLL ≤ 9e-4; all fits status 0 covQual 3; m6000_two EDM 0.129 = documented noise floor. Ledger: `finegrid/state/injection_spot_2x0_20260814_corrected.json` (v1 spot-harvest σ had a falsy-zero MINOS bug — corrected σ = max(parabolic, MINOS)) |
| supervisor sign-off | show validation deck + the three fine-grid curves; explicit OK to open the SR | ☑ done 2026-08-14 (reported by Aritra) |

**Gate 0 passes when all four boxes are checked. Nothing below runs before that.**

## Gate 1 — background-model unblinding (SR opened; NO signal results)

One condor job per width-independent card (the b-only model is
signal-independent, but the card is built per signal; use w1 m2000's card as
the canonical one — the QCD+ttbar model is identical at every mass). All
Gate-1 fits have **r frozen at 0**. No s+b fit, no signal scan, no limit, no
significance is computed in Gate 1.

Machinery (this branch, `run3/unblinding/`):
- `gate1_bonly_unmasked_job.sh` — combined cen+fwd card, text2workspace with
  `--channel-masks`, **all masks set to 0** (SR data enter the likelihood),
  MultiDimFit b-only (r=0 frozen), strategy 2 + `--cminPreScan --cminPreFit 1`
  + `MaxCalls=5000000`, `--saveWorkspace --saveFitResult`.
- `gate1_gof_data_job.sh` — saturated GoF on the unmasked data + 500
  frequentist toys (condor-split 25×20, from the Gate-1 snapshot).
- Postfit projections: house PostFit2DShapes extractor (masked_postfit v9
  machinery with masks off). Stock PostFitShapesFromWorkspace is forbidden
  (wrong for RooParametricHist2D).

### Pre-registered pass criteria (fixed 2026-08-14, blind)

Hard gates — ALL must pass:

| # | criterion |
|---|---|
| 1.1 | unmasked b-only fit: status 0, covQual 3, EDM ≤ 0.01 |
| 1.2 | saturated GoF p-value ≥ 0.05 (500 toys) |
| 1.3 | every nuisance pull \|θ̂−θ₀\|/σ ≤ 2.5 |
| 1.4 | no TF rpf parameter within 5% of its ±50 bound; no par0 pinned at 0.001 |
| 1.5 | no nuisance constraint tighter than 0.4× its input width (over-constraint check) |

Review items — recorded, do not auto-fail, but must be discussed before
Gate 2:

| # | item |
|---|---|
| R1 | GoF p in [0.01, 0.05): proceed only after postfit-projection review finds no localized SR mis-model |
| R2 | per-channel postfit χ²/ndof and the largest single-bin pull (record; investigate any \|pull\| > 4σ) |
| R3 | ttbar_xsec and q2 pulls vs their masked-fit values (−1.6σ q2, corr −0.60 with ttbar_xsec was the blinded state; a large jump = sideband↔SR tension) |

Failure rule: GoF p < 0.01 or any hard-gate failure → **STOP**. Do not run
Gate 2. Document here + research-notes, diagnose with b-only postfit tools
only. Any model change after this point is a post-unblinding change and must
be labeled as such in the AN; it requires re-running the blinded validation
suite on the changed model before a second unblinding attempt.

## Gate 2 — observed limits (only after Gate 1 passes)

- Same 39-point pipeline (`fullsyst_limit_v3` pattern) with the observed leg:
  AsymptoticLimits WITHOUT `--run blind` from the Gate-1 unmasked b-only
  snapshot; expected quantiles recomputed alongside for the same workspace.
- rMax ledger unchanged (numerical headroom only). If an observed limit
  exceeds 0.9·rMax at any point, raise that point's rMax by one 1-2-5 step
  and rerun the point — pre-agreed, not a model change.
- Deliverable: observed + expected overlay per width; excursion table
  (observed vs expected quantile position at every point).
- Excess protocol (pre-registered): any point with observed above the 97.5%
  expected quantile → check width-coherence (does the excess appear in the
  other width curves at the same mass?), mass-coherence (neighboring points),
  and the postfit mtt window, BEFORE any significance is quoted. A
  significance scan (`--significance`, r ≥ 0) is run only after the full
  limit set is recorded, and only at the pre-identified excess masses.
- Gate-2 scripts are drafted only after Gate 1 passes (deliberate: their
  arguments depend on the Gate-1 snapshot artifact names).

## Decision log

- 2026-08-14: plan created while fully blind; criteria frozen. Gate 0
  items 1 (tag) done; injection spot check in flight; sign-off pending.
- 2026-08-14 (later): injection spot check PASSED 8/8 on corrected σ
  (recoveries 0.98 / 0.82–0.87, exactly the validated envelope; the 2x0
  model is *more* stable than 2x1 at high mass — every fit status 0
  covQual 3). Gate 0 now waits only on the origin push and supervisor
  sign-off.
- 2026-08-14 (evening): Gate 0 COMPLETE (all four boxes). Aritra instructed
  arming Gate 1; sub templates armed with GATE0-PASSED and submitted
  (armed copies committed alongside this entry). The SR enters a b-only
  likelihood for the first time. No signal quantity is computed at this gate.
- 2026-08-14 (night): Gate-1 fit returned (cluster 85133122, 8 min).
  RESULTS: 1.1 PASS (status 0, covQual 3, EDM 1.9e-7); 1.3 PASS (worst pull
  q2 −1.45σ, improved from masked −1.60σ); 1.5 PASS (tightest constraint
  0.48); R3 mild (ttbar_xsec −0.83σ→−1.35σ). **1.4 FAIL as written**:
  QCD_Fwd24rpf_par2 = −47.2 ± 12.5 (within 5% of −50). FORENSICS: in the
  FROZEN MASKED production fit both fwd par2 rail at exactly −50 with errors
  79/67 (sidebands cannot constrain the x² curvature) — the condition
  PRE-EXISTS unblinding and was never checked blind; opening the SR pulls
  Fwd25 par2 fully off the bound (−27.0 ± 13.2) and Fwd24 mostly
  (−47.2 ± 12.5), errors shrink 6×. Per the failure rule the GoF wave was
  NOT launched. Options for Aritra: (A) record 1.4 as a documented deviation
  (criterion targeted unblinding-induced pathology; condition is provably
  blind-side and data relieve it; note the fwd-TF insensitivity of the
  limits, 2x1≡2x0 medians) and resume Gate 1 (GoF + postfit); (B) treat as
  model defect → widen fwd par2 range = post-unblinding model change
  requiring blinded revalidation per the prime rule (note: ±50 was chosen
  2026-07 to kill the −996 runaway mode). Claude recommends (A) with the
  deviation prominently documented.
