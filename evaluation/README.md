# Model evaluation

`tests/` answers whether the platform runs. This answers whether the
segmentation it produces is any good, which needs labelled scans and the real
model rather than a stub.

```bash
# In one terminal, from ai-service/:
uvicorn app.main:app --port 8001

# In another:
./evaluation/run.sh --dataset evaluation/data/Task09_Spleen \
    --organ spleen --label-value 1 \
    --json evaluation/runs/spleen-2026-09-12.json
```

Output is a per-case table and a summary: mean, median and worst Dice, mean
absolute volume error in mL, and inference time.

## There is no data in the repo

Labelled CT is large and not ours to redistribute, so `evaluation/data/` is
gitignored and starts empty. The layout the script expects is

```
evaluation/data/<dataset>/
  images/case_0001.nii.gz
  labels/case_0001.nii.gz
```

matched by filename. `--label-value N` picks one structure out of a
multi-label ground truth; without it, anything non-zero counts as the organ.

Two sources that fit the two models:

- **[Medical Segmentation Decathlon](http://medicaldecathlon.com/), Task09
  Spleen** for the spleen bundle. Its `imagesTr` / `labelsTr` become
  `images/` / `labels/`, and the spleen is label 1.
- **[TotalSegmentator](https://github.com/wasserth/TotalSegmentator)** for the
  whole-body bundle, whose 104 structures are what the other organs come from.
  Its labels are per-structure files rather than one multi-label volume, so
  pick the file for the organ and drop `--label-value`.

**Read the Dice number with the training set in mind.** The spleen bundle was
trained on Task09_Spleen, so scoring it on those same cases measures how well
it memorised them, not how it generalises. Task09's held-out `imagesTs` ships
without labels, so an honest split means holding back part of `imagesTr` and
never claiming the rest as a result. TotalSegmentator is the cleaner test for
the whole-body model for the same reason, in reverse.

## Recording runs

A single Dice number is hard to interpret. A change in one is not.

```bash
./evaluation/run.sh ... --json evaluation/runs/spleen-2026-09-12.json
./evaluation/run.sh ... --baseline evaluation/runs/spleen-2026-09-12.json
```

The second run prints each summary figure with its delta against the first.
`evaluation/runs/` is small and committed on purpose: it is the record of what
the model scored and when.

`--min-mean-dice 0.9` makes the script exit non-zero when the mean falls
below a threshold, so a run can gate something rather than just report.
Any case that fails to produce a score at all is also a non-zero exit.

## Files

| | |
|---|---|
| `metrics.py` | Dice, IoU, volume. Pure functions over arrays, tested in `tests/test_evaluation_metrics.py`. |
| `evaluate.py` | Sends each case to a running AI service, scores the mask, prints and records the run. |
| `run.sh` | Creates `.venv` if needed, then runs `evaluate.py` with whatever arguments you pass. |
