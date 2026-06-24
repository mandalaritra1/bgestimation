# Repository Agent Instructions

This is the **2DAlphabet background-estimation + Combine fit/limit** stage of the
ttbarhadronic all-hadronic ttbar resonance search. You may edit this repository
when the user asks for code work.

## Position in the analysis pipeline

This repo is the **downstream fit layer**. Full chain:

```
TTbarHadronicSkimmer (coffea, branch coffea-2025)         ── UPSTREAM
  ttbarprocessor.py / ttbaranalysis.py  ->  outputs/dy/{data,QCD,TTbar,ZPrime}_2024*.coffea
  plots/make2Drootfiles.py  (+ scaleCoffeaFiles.ipynb)
        -> TH2  MttvsMt{Cen,Fwd}2024{Pass,Fail}  inside  TTbarAllHad24_*.root
                              │  handoff
                              ▼
  EOS  /eos/user/a/amandal/ttbarhad_root_files/2dAlphabetInputs/
                              │
                              ▼
bgestimation  (THIS repo)                                 ── DOWNSTREAM
  ttbar.py -> 2DAlphabet workspace -> Combine fit / AsymptoticLimits / GOF / impacts
```

- **Upstream skimmer:** `mandalaritra1/TTbarHadronicSkimmer` (branch `coffea-2025`),
  local at `/Users/aritra/Projects/TTBarHadronicSkimmer`. The **interface contract**
  is the histogram names `MttvsMt{Cen,Fwd}2024{Pass,Fail}` inside `TTbarAllHad24_*.root`;
  they are produced by the skimmer's `plots/make2Drootfiles.py` from the coffea
  `mtt_vs_mt` histograms. If the binning, region split, or hist names change here,
  they must change in `make2Drootfiles.py` too (and vice versa).
- **Inputs this repo reads:** `/eos/user/a/amandal/ttbarhad_root_files/2dAlphabetInputs`
  (the `run_fit_2024.sh` `BASE_INPUT` default; `root://eosuser.cern.ch//...` xrootd
  works from both LPC and lxplus).

## Knowledge base (read first)

- `/Users/aritra/Projects/ai-wiki/AGENTS.md` and `wiki/meta/index.md`
- This repo's card: `/Users/aritra/Projects/ai-wiki/wiki/repos/ttbarhadronic_bgestimation.md`
- Upstream skimmer card: `/Users/aritra/Projects/ai-wiki/wiki/repos/ttbarhadronic_skimmer.md`
- Project documentation site: `/Users/aritra/Projects/documentations/doc-ttbarhad`

Log durable outcomes proactively: code/workflow/debugging knowledge to `ai-wiki`
(update `wiki/meta/index.md`, append `wiki/meta/log.md`); physics findings/results
to `/Users/aritra/Projects/research-notes` (promote into `topics/`/`bugs/`, update
`projects/ttbarhadronic.md`, include plots) — following each repo's own `AGENTS.md`.

## Run context (NOT the skimmer's coffea venv)

Runs inside the CMSSW + Combine + 2DAlphabet environment. Full GitHub-driven setup
(lxplus and LPC) is in this repo's `README.md`. Key facts:

- `CMSSW_14_1_0_pre4`, Combine **v10.0.1**, CombineHarvester (`CMSSW_14_1_0_pre4`),
  2DAlphabet fork `mandalaritra1/2DAlphabet@blinded-subregion-fix`, `twoD-env` venv.
- **Run wrappers from the repo root** (e.g. `bash run3/run_fit_2024.sh`). Layout:
  shared driver at root (`ttbar.py`, `header.py`, `jsons/`); `run2/` (2016-2018),
  `run3/` (2024+), `studies/`, `docs/`.
- Works on both **LPC** (`ssh cmslpc`) and **lxplus** (`ssh lxw`). For lxplus access,
  sshuttle, and LPC/CERN Kerberos switching, see the research-notes runbook
  `topics/cern_lxplus_noninteractive_ssh.md`.
- Generated fit areas, plots, ROOT, logs, and runtime per-signal
  `jsons/config/ttbar_<cat>__signal*.json` are git-ignored — only code/source-config.
