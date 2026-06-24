# **TTbar Hadronic Background Estimation**

## **Requirements**
This directory requires the **2DAlphabet** and **TTbarAllHadUproot** packages to run. You can find instructions to run it [here](https://github.com/b2g-nano/TTbarAllHadUproot/tree/optimize). 

---

## **Setup Instructions (from scratch, GitHub-driven)**

> Reproducible bootstrap verified on **lxplus** (RHEL 9, `el9_amd64_gcc12`) on
> 2026-06-24. The LPC steps are identical; only the access/quota notes differ.
> Everything below is cloned from GitHub — no machine-to-machine copying.

**Prerequisites**
- lxplus non-interactive access (`ssh lxw` via sshuttle, AFS token via `aklog`):
  see the research-notes runbook `cern_lxplus_noninteractive_ssh.md`.
- The CMSSW build lives on **AFS home** (keep it small); keep all ROOT files and
  fit outputs on **EOS** (`/eos/user/a/amandal/...`).
- Public repos (CombinedLimit, JHU-Tools/CombineHarvester, JHU-Tools/2DAlphabet)
  clone over HTTPS with no auth. The analysis repos (`mandalaritra1/bgestimation`,
  `hayfasfar/TTbarHadronicBGEstimation`) need a **GitHub token or SSH key** on
  lxplus if they are private — swap the `https://` URL for `git@github.com:` then.
- ⚠️ **Reproducibility caveat:** these clones reproduce the *committed* state.
  The working area may carry **uncommitted local edits** in `bgestimation` and
  `TTbarHadronicBGEstimation` — commit and push them first for an exact
  reproduction. (2DAlphabet's local fix is already captured in the fork branch
  cloned above.)

### 1. CMSSW + Combine + CombineHarvester + 2DAlphabet

Start from the directory where the CMSSW release area should live (AFS home on lxplus):

```bash
source /cvmfs/cms.cern.ch/cmsset_default.sh
export SCRAM_ARCH=el9_amd64_gcc12          # native arch on RHEL-9 lxplus

cmsrel CMSSW_14_1_0_pre4
cd CMSSW_14_1_0_pre4/src
cmsenv

# Combine v10.0.1
git clone --depth 1 -b v10.0.1 \
  https://github.com/cms-analysis/HiggsAnalysis-CombinedLimit.git HiggsAnalysis/CombinedLimit

# CombineHarvester (JHU-Tools fork, CMSSW_14_1_0_pre4 branch)
git clone -b CMSSW_14_1_0_pre4 \
  https://github.com/JHU-Tools/CombineHarvester.git CombineHarvester

# 2DAlphabet — your fork with the blinded-subregion plot.py fix.
# Branch is based off upstream JHU-Tools 2799fba; the fork's master still tracks
# upstream, so rebase the branch onto newer upstream when you want to update.
git clone -b blinded-subregion-fix https://github.com/mandalaritra1/2DAlphabet.git 2DAlphabet

# Compile the C++ (Combine + CombineHarvester); 2DAlphabet is pure Python
scram b -j 8
```

### 2. Analysis code (this repo + the shared package)

```bash
# still in CMSSW_14_1_0_pre4/src
git clone -b cmslpc-el9 https://github.com/mandalaritra1/bgestimation.git
git clone https://github.com/hayfasfar/TTbarHadronicBGEstimation.git
```

### 3. Python environment (`twoD-env` — rebuilt, never copied)

```bash
# from CMSSW_14_1_0_pre4/src
python3 -m venv twoD-env                    # or: python3 -m virtualenv twoD-env
source twoD-env/bin/activate
python -m pip install --upgrade pip
cd 2DAlphabet && python setup.py develop && cd ..
```

### 4. Inputs (already on CERN EOS — nothing to copy)

The 2DAlphabet input ROOT files live at
`/eos/user/a/amandal/ttbarhad_root_files/2dAlphabetInputs` (see **Samples** below).

> Note: each fresh lxplus shell needs `source /cvmfs/cms.cern.ch/cmsset_default.sh`,
> `cmsenv` (from `CMSSW_14_1_0_pre4/src`), and `source twoD-env/bin/activate` before
> running fits. Non-interactive `ssh lxw` sessions also need `aklog` for AFS.

## **Repository layout**

```
bgestimation/
  ttbar.py  header.py  style.py        # shared driver (parametrised by --cat)
  fit_ftest.py  results_ftest.py       # F-test machinery
  plot_limits.py  plot_limits_mpl.py  extract_limits.py  extract_bands.py
  remove_constraints.py  make_elog_entry.py  compare_conv.py
  jsons/        # configs (named by era: ttbar_<cat>.json) + TransferFunctions + signals
  scripts/      # shared helper scripts
  run2/         # Run-2 (2016/2017/2018, RSGluon): run_fit.sh, combine_cards1{6,7,8}.sh, ...
  run3/         # Run-3 (2024 now; more years added here): run_fit_2024.sh, combine_cards24.sh,
                #        impacts24.sh, plot_*_2d.py, analysis2024/
  studies/      # side studies off the main line (recomb_ttag, oldtag taggers)
  docs/         # notes + F-test presentation generators
```

> **Invocation convention:** run all wrapper scripts **from the repo root**, e.g.
> `bash run3/run_fit_2024.sh`. Bash resolves their relative paths (`jsons/`,
> `output/`, `ttbar.py`) against your current directory, so the repo root is the
> correct place to launch them from.
>
> All generated fit areas, plots, ROOT files, logs, and the per-signal
> `jsons/config/ttbar_<cat>__signal*.json` configs are git-ignored — only code and
> source configs are tracked. The topcolor σ×B work area lives in its own repo.

## **Samples**

The 2DAlphabet input ROOT files needed for background estimation are located in:

```bash
/eos/user/a/amandal/ttbarhad_root_files/2dAlphabetInputs
```


## **Running Fits**

To obtain fit results for both central and forward categories for each Run-2 year (2016, 2017, 2018), from the repo root run:

```bash
bash run2/run_fit.sh
```
This will execute the ttbar.py script for different scenarios. You can choose to run fits, limits, and goodness-of-fit (GOF) tests using the "--all" argument, or adjust the argument based on your needs.

Fit results for a given category will be stored under the "output/" directory.

For the 2024 single-year workflow, run central and forward with the 2024 inputs and the transfer functions currently stored in `jsons/TransferFunctions.json`:

```bash
cd "$CMSSW_BASE/src/bgestimation"          # run from the repo root
LOCAL_INPUT="/eos/user/a/amandal/ttbarhad_root_files/2dAlphabetInputs"

python -u ttbar.py --cat cen2024 --senario ZPrime_1 --input "$LOCAL_INPUT" --signal ZPrime4000 --study all 2>&1 | tee output_2024_cen_all.log
python -u ttbar.py --cat fwd2024 --senario ZPrime_1 --input "$LOCAL_INPUT" --signal ZPrime4000 --study all 2>&1 | tee output_2024_fwd_all.log
```

These commands expect the signal input file to be named `TTbarAllHad24_signalZPrime4000.root` under `LOCAL_INPUT`. If the existing EOS file is still named with `signalRSGluon4000`, rename/copy it before rerunning so the model label and the filename agree.

If the fit/postfit plotting has already run and only the limit/GOF card directories are missing, run `--study limit` for each category instead of rerunning the full fit. The combined-card step below uses the plain `signalZPrime4000_area/card.txt` cards made by `perform_limit`, not the `ttbar-signalZPrime4000_area/card.txt` cards made by `ML_fit`.

### Combining datacards

To combine cards for a specific year:

```bash
bash run2/combine_cards16.sh
bash run2/combine_cards17.sh
bash run2/combine_cards18.sh
```
Once these cards are combined, you can run the Run-2 combination using:

```bash 
bash run2/combine_cardsrun2.sh
```

For 2024, combine only central plus forward. After the `cen2024` and `fwd2024` `signalZPrime4000_area/card.txt` files exist, run:

```bash
bash run3/combine_cards24.sh
```

This reads `cen2024` and `fwd2024` from `jsons/TransferFunctions.json`, writes `output/cards_combined_24/signalZPrime4000_area/signalZPrime4000_card_combined.txt`, builds a masked workspace, runs the blind saturated GOF with pass-region masks, collects the toys, and writes `gof_blind.json` plus `gof_plot_blind_2024.pdf/png`. Set `NTOYS` to override the default 200 toys, for example `NTOYS=50 bash run3/combine_cards24.sh` for a quick test.

### Goodness of fit (GOF) 

These are run2 GOF command, to run it on a specific category or year please change the card  accordingly. 

Blind : 

```bash
1- text2workspace.py  output/cards_combined_run2/signalRSGluon2000_area/signalRSGluon2000_card_combined.txt  -o workspace.root --channel-masks 
2- combineTool.py -M GoodnessOfFit -d workspace.root --algo saturated -n _blind  -m 2000 --setParameterRanges r=-5.0,5.0  --setParameters mask_Name1_Name1_cen16Pass_SIG=1,mask_Name1_Name2_fwd16Pass_SIG=1,mask_Name2_Name1_cen17Pass_SIG=1,mask_Name2_Name2_fwd17Pass_SIG=1,mask_Name3_Name1_cen18Pass_SIG=1,mask_Name3_Name2_fwd18Pass_SIG=1
3- combineTool.py -M GoodnessOfFit -d workspace.root --algo saturated -n _blind  -m 2000 --setParameterRanges r=-5.0,5.0 --toysFreq -t 200 -s -1 --setParameterRanges r=-5.0,5.0  -setParameters mask_Name1_Name1_cen16Pass_SIG=1,mask_Name1_Name2_fwd16Pass_SIG=1,mask_Name2_Name1_cen17Pass_SIG=1,mask_Name2_Name2_fwd17Pass_SIG=1,mask_Name3_Name1_cen18Pass_SIG=1,mask_Name3_Name2_fwd18Pass_SIG=1
4- combineTool.py -M CollectGoodnessOfFit --input higgsCombine_blind.GoodnessOfFit.mH2000.root higgsCombine_blind.GoodnessOfFit.mH2000.969972814.root -m 2000 -o gof_blind.json
5- plotGof.py gof_blind.json --statistic saturated --mass 2000.0 -o gof_plot_blind_run2 --title-right="Combined run2 blind"
```

Unblind: 
```bash
1- text2workspace.py  output/cards_combined_run2/signalRSGluon2000_area/signalRSGluon2000_card_combined.txt  -o workspace.root
2- combineTool.py -M GoodnessOfFit -d workspace.root --algo saturated -n _unblind  -m 2000 --setParameterRanges r=-5.0,5.0
3- combineTool.py -M GoodnessOfFit -d workspace.root --algo saturated -n _unblind  -m 2000 --setParameterRanges r=-5.0,5.0 --toysFreq -t 200 -s -1 
4- combineTool.py -M CollectGoodnessOfFit --input higgsCombine_unblind.GoodnessOfFit.mH2000.root higgsCombine_unblind.GoodnessOfFit.mH2000.969972814.root -m 2000 -o gof_unblind.json
5- plotGof.py gof_unblind.json --statistic saturated --mass 2000.0 -o gof_plot_unblind_run2 --title-right="Combined run2 unblind"
```
### Fit Diagnostics 
Run the Fit diagnostics to check the sanity of the fit and systematic uncertainties: you can do it per category, per year or for combined run2:
Example using combined 2017 i.e central and forward 2017 combined categories: 
```bash 
text2workspace.py  output/cards_combined_17/signalRSGluon2000_area/signalRSGluon2000_card.txt  -o workspace.root
combine -M FitDiagnostics workspace.root -m 1 --rMin -1 --rMax 2 --saveShapes --saveWithUncertainties -n .combined2017
```

### Limits 
To plot limits run the following command: 
```bash 
python plot_limits.py --signal RSGluon --width ""  --output limits --year run2  
```
this will plot unblinded limits if you want blind ones you should add the option --blind True 

For the 2024 combined central+forward card, first run the Combine limit inside the combined-card directory:

```bash
cd output/cards_combined_24/signalZPrime4000_area
combineTool.py -M AsymptoticLimits -d signalZPrime4000_card_combined.txt --run blind --saveWorkspace --cminDefaultMinimizerStrategy 0 --cminPreScan --cminPreFit 1 --rAbsAcc 0.0001 -v 0
```

Then plot from the `bgestimation` directory:

```bash
cd ../../..
python3 plot_limits.py --signal ZPrime --width 1 --output limits --year 2024 --blind True
```

The `--run blind`/`--blind True` path gives expected-only limits and does not require unblinding. For observed limits, remove `--run blind` from the Combine command and use `--blind False` in `plot_limits.py`. A mass-limit crossing is only meaningful once the combined limit outputs exist for multiple signal masses; with only `ZPrime4000` present, the plot is a single available point/check.

### Impact plot

To get Run2 Impact plot run the following command lines, if you want to run it only for one year, consider changing the datacard accordingly. For unblinded Impact remove -t -1 : 
```bash
text2workspace.py  output/cards_combined_run2/signalRSGluon2000_area/signalRSGluon2000_card_combined.txt  -o workspace.root
combineTool.py -M Impacts -d workspace.root -m 2000 --doInitialFit --robustFit 1 --expectSignal=1 --rMin -1 --rMax 2  --cminDefaultMinimizerStrategy 0 --cminPreScan --cminPreFit 1  -t -1 
combineTool.py -M Impacts -d workspace.root -m 2000 --robustFit 1 --doFits --parallel 16 --expectSignal=1 --cminDefaultMinimizerStrategy 0 --cminPreScan --cminPreFit 1  --rMin -1 --rMax 2 -t -1  --job-mode condor
combineTool.py -M Impacts -d workspace.root -m 2000  -o impacts.json
plotImpacts.py -i impacts.json -o impacts  --units pb
```
To remove QCD bins from the impact plot for visualisation purpose, you can do this before plotting it: 
```bash
python remove_constraints.py -i impact.json -o impact.json
```

For blinded 2024 impacts, use the combined 2024 workspace and keep `-t -1`:

```bash
cd output/cards_combined_24/signalZPrime4000_area
combineTool.py -M Impacts -d workspace.root -m 4000 --doInitialFit --robustFit 1 --expectSignal=1 --rMin -1 --rMax 2 --cminDefaultMinimizerStrategy 0 --cminPreScan --cminPreFit 1 -t -1
combineTool.py -M Impacts -d workspace.root -m 4000 --robustFit 1 --doFits --parallel 16 --expectSignal=1 --cminDefaultMinimizerStrategy 0 --cminPreScan --cminPreFit 1 --rMin -1 --rMax 2 -t -1 --job-mode condor
combineTool.py -M Impacts -d workspace.root -m 4000 -o impacts_2024_blind.json
python ../../../remove_constraints.py -i impacts_2024_blind.json -o impacts_2024_blind.json
plotImpacts.py -i impacts_2024_blind.json -o impacts_2024_blind --units pb
```

For observed/unblinded impacts, build an unmasked workspace from `signalZPrime4000_card_combined.txt`, use that workspace in the commands above, and remove `-t -1`.

### Transfer functions 

The transfer functions (TFs) are stored in `jsons/TransferFunctions.json`.

To re-determine them for the 2024 central and forward categories, first run the F-test fit scan:

```bash 
cd "$CMSSW_BASE/src/bgestimation"          # run from the repo root
LOCAL_INPUT="/eos/user/a/amandal/ttbarhad_root_files/2dAlphabetInputs"

python -u fit_ftest.py --preset 2024 --input "$LOCAL_INPUT" --signal ZPrime4000 2>&1 | tee output_ftest_2024.log
```

This runs `ttbar.py --study ftest` for the candidate transfer-function forms and writes the fit work areas under `ftest/`. To perform the F-test comparisons and plot the results, run:

```bash 
python -u results_ftest.py --preset 2024 --signal ZPrime4000 2>&1 | tee output_ftest_results_2024.log
```

All F-test summary CSVs and plots will be stored in the `ftest_results/` directory.






## Running all years combined

To run on all years/eras combined, you can go to the directory where your histograms are and execute: 

```
source rename_all_hists.sh
source hadd_files.sh
```

Then you can execute

```
nohup python ttbar.py --cat cenComb --senario RSGluon --input /afs/cern.ch/user/s/srappocc/TTBarRes/CMSSW_10_6_14/src/TTbarHadronicBGEstimation/files_loosetomedium_Sep24_Comb --signal RSGluon2000 > output1.log 2>&1 &
nohup python ttbar.py --cat cenFwd --senario RSGluon --input /afs/cern.ch/user/s/srappocc/TTBarRes/CMSSW_10_6_14/src/TTbarHadronicBGEstimation/files_loosetomedium_Sep24_Comb --signal RSGluon2000 > output1.log 2>&1 &
```
