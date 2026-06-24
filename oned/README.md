# `oned/` — 1D background-estimation cross-check

A **1D cross-check** of the nominal **2DAlphabet** (2D, `(m_SD, m_tt)`) background
estimate, run on the *same* inputs so the comparison is apples-to-apples. Two
complementary methods (see the literature notes in the research-notes vault):

| | Method | Tool | Independent of Fail region? |
|---|---|---|---|
| **①** | **Parametric bump-hunt** — fit the Pass-region `m_tt` spectrum with a smooth analytic function | Combine `RooParametricShapeBinPdf` + `RooMultiPdf` (discrete profiling) — both ship with Combine v10 | **Yes** (strongest cross-check) |
| **②** | **1D alphabet** — `Pass(m_tt) = TF(m_tt) × Fail(m_tt)` transfer factor | `rhalphalib` (in `twoD-env`) | No (shares the 2DAlphabet TF idea) |

## Inputs (shared with 2DAlphabet)

Same EOS files as `run_fit_2024.sh`:
`/eos/user/a/amandal/ttbarhad_root_files/2dAlphabetInputs/TTbarAllHad24_{Data,TTbar,signalZPrime<mass>}.root`.

Each holds TH2 `MttvsMt{Cen,Fwd}24{Pass,Fail}` with **X = jet `m_SD` [0,500] GeV**
(100 bins), **Y = `m_tt` [800,10000] GeV** (92 bins). The 1D methods use the
**`ProjectionY` (m_tt) spectrum** of the Pass (and, for ②, Fail) region — QCD is
data-driven (②) or absorbed into the parametric function (①), never an input file.

## Workflow

```bash
# from the bgestimation repo root, env active (cmsenv + twoD-env)
python oned/project_inputs.py --cat cen24 --signal signalZPrime4000   # -> oned/out/oned_inputs_cen24.root
python oned/bumphunt.py       --cat cen24 --signal signalZPrime4000   # method ①  (TODO)
python oned/alphabet1d.py     --cat cen24 --signal signalZPrime4000   # method ②  (TODO)
python oned/compare.py        --cat cen24                             # vs 2DAlphabet (TODO)
```

Run wrappers from the repo root (paths are repo-root relative). Outputs go to
`oned/out/` (git-ignored).

## Cross-verification

Compare the **expected AsymptoticLimits** (and the background estimate in the
signal window) from ①/② against bgestimation's 2DAlphabet result per category
(`cen24`, `fwd24`), then combined. Agreement validates the 2D data-driven TF;
disagreement flags model dependence.

## Status

- [x] Tooling installed/verified on lxplus: `rhalphalib 0.3.0`,
      `RooParametricShapeBinPdf` + `RooMultiPdf` (in Combine v10.0.1).
- [x] `project_inputs.py` — projects the TH2s to 1D `m_tt` templates.
- [ ] `bumphunt.py` (①), `alphabet1d.py` (②), `compare.py`.
