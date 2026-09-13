#!/usr/bin/env python3
"""Score the segmentation model against ground truth, case by case.

This is the other half of "did it work". The end-to-end suite in `tests/`
answers whether the platform runs; this answers whether what comes out of it
is any good, which needs labelled scans and the real model rather than a stub.

    ./evaluation/run.sh --dataset evaluation/data/Task09_Spleen --organ spleen

Expects a dataset laid out as

    <dataset>/
      images/case_0001.nii.gz
      labels/case_0001.nii.gz

matched by filename. `--label-value` picks one structure out of a multi-label
ground truth; without it anything non-zero counts as the organ.

Writing the numbers down matters more than any single run: pass `--json` to
save a run, then `--baseline` on a later one to see what moved.
"""

import argparse
import base64
import json
import statistics
import sys
import tempfile
import time
from dataclasses import asdict, dataclass
from pathlib import Path

import nibabel as nib
import numpy as np
import requests

sys.path.insert(0, str(Path(__file__).resolve().parent))

from metrics import score_case  # noqa: E402

DEFAULT_URL = "http://localhost:8001"
# One case can take minutes on CPU, and the whole-body bundle is the slow one.
CASE_TIMEOUT_S = 900


@dataclass(frozen=True)
class Case:
    name: str
    image: Path
    label: Path


def discover_cases(dataset: Path) -> list[Case]:
    images_dir = dataset / "images"
    labels_dir = dataset / "labels"

    if not images_dir.is_dir() or not labels_dir.is_dir():
        raise SystemExit(
            f"{dataset} does not look like a dataset: expected {images_dir.name}/ "
            f"and {labels_dir.name}/ inside it. See evaluation/README.md."
        )

    cases = []
    for image in sorted(images_dir.glob("*.nii*")):
        label = labels_dir / image.name
        if not label.exists():
            print(f"  skipping {image.name}: no matching label", file=sys.stderr)
            continue
        cases.append(Case(name=image.name, image=image, label=label))

    if not cases:
        raise SystemExit(f"No image/label pairs found under {dataset}.")
    return cases


def segment(url: str, image: Path, organ: str) -> tuple[np.ndarray, dict]:
    """Send one scan to the AI service and read the mask back."""
    with image.open("rb") as handle:
        response = requests.post(
            f"{url.rstrip('/')}/segment",
            files={"file": (image.name, handle, "application/gzip")},
            data={"organ": organ},
            timeout=CASE_TIMEOUT_S,
        )
    response.raise_for_status()
    body = response.json()

    with tempfile.TemporaryDirectory() as tmp_dir:
        mask_path = Path(tmp_dir) / "mask.nii.gz"
        mask_path.write_bytes(base64.b64decode(body["mask_base64"]))
        mask = np.asarray(nib.load(mask_path).dataobj)

    return mask, body


def evaluate_case(url: str, case: Case, organ: str, label_value: int | None) -> dict:
    started = time.monotonic()
    prediction, body = segment(url, case.image, organ)

    label_image = nib.load(case.label)
    truth_raw = np.asarray(label_image.dataobj)
    truth = truth_raw == label_value if label_value is not None else truth_raw > 0

    if prediction.shape != truth.shape:
        return {
            "case": case.name,
            "error": (
                f"mask shape {prediction.shape} does not match label shape "
                f"{truth.shape}"
            ),
        }

    scores = score_case(prediction, truth, label_image.affine)
    return {
        "case": case.name,
        "dice": round(scores.dice, 4),
        "iou": round(scores.iou, 4),
        "predicted_ml": round(scores.predicted_ml, 2),
        "truth_ml": round(scores.truth_ml, 2),
        "volume_error_ml": round(scores.volume_error_ml, 2),
        "volume_error_pct": round(scores.volume_error_pct, 1),
        "reported_ml": body.get("volume_ml"),
        "inference_time_ms": body.get("inference_time_ms"),
        "model_name": body.get("model_name"),
        "wall_time_s": round(time.monotonic() - started, 1),
    }


def summarise(rows: list[dict]) -> dict:
    scored = [row for row in rows if "dice" in row]
    failed = [row for row in rows if "error" in row]

    if not scored:
        return {"cases": len(rows), "scored": 0, "failed": len(failed)}

    dice_scores = [row["dice"] for row in scored]
    abs_volume_errors = [abs(row["volume_error_ml"]) for row in scored]

    return {
        "cases": len(rows),
        "scored": len(scored),
        "failed": len(failed),
        "mean_dice": round(statistics.fmean(dice_scores), 4),
        "median_dice": round(statistics.median(dice_scores), 4),
        "min_dice": round(min(dice_scores), 4),
        "worst_case": min(scored, key=lambda row: row["dice"])["case"],
        "mean_abs_volume_error_ml": round(statistics.fmean(abs_volume_errors), 2),
        "mean_inference_time_ms": round(
            statistics.fmean(
                [row["inference_time_ms"] for row in scored if row["inference_time_ms"]]
            ),
            1,
        ),
    }


def render(rows: list[dict], summary: dict, baseline: dict | None):
    header = f"{'case':<28}{'dice':>8}{'iou':>8}{'pred mL':>10}{'true mL':>10}{'err %':>8}{'time s':>8}"
    print()
    print(header)
    print("-" * len(header))
    for row in rows:
        if "error" in row:
            print(f"{row['case']:<28}{'ERROR':>8}  {row['error']}")
            continue
        print(
            f"{row['case']:<28}{row['dice']:>8.4f}{row['iou']:>8.4f}"
            f"{row['predicted_ml']:>10.2f}{row['truth_ml']:>10.2f}"
            f"{row['volume_error_pct']:>8.1f}{row['wall_time_s']:>8.1f}"
        )

    print()
    for key, value in summary.items():
        line = f"  {key:<28} {value}"
        if baseline and key in baseline and isinstance(value, (int, float)):
            delta = value - baseline[key]
            line += f"   ({delta:+.4g} vs baseline)"
        print(line)
    print()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, required=True,
                        help="Directory holding images/ and labels/.")
    parser.add_argument("--organ", default="spleen",
                        help="Organ key, as in ai-service/app/organs.py.")
    parser.add_argument("--url", default=DEFAULT_URL,
                        help=f"AI service base URL (default {DEFAULT_URL}).")
    parser.add_argument("--label-value", type=int, default=None,
                        help="Value in the ground truth that marks this organ. "
                             "Omit when the label file is already binary.")
    parser.add_argument("--limit", type=int, default=None,
                        help="Score only the first N cases.")
    parser.add_argument("--json", type=Path, default=None,
                        help="Write the full run here.")
    parser.add_argument("--baseline", type=Path, default=None,
                        help="An earlier --json run to compare against.")
    parser.add_argument("--min-mean-dice", type=float, default=None,
                        help="Exit non-zero if the mean Dice falls below this, "
                             "so the run can gate something.")
    args = parser.parse_args()

    try:
        health = requests.get(f"{args.url.rstrip('/')}/health", timeout=10)
        health.raise_for_status()
    except requests.RequestException as exc:
        raise SystemExit(
            f"No AI service answering at {args.url}: {exc}\n"
            "Start it with `uvicorn app.main:app --port 8001` from ai-service/."
        )

    cases = discover_cases(args.dataset)
    if args.limit:
        cases = cases[: args.limit]

    print(f"Scoring {len(cases)} case(s) for '{args.organ}' against {args.url}")

    rows = []
    for index, case in enumerate(cases, start=1):
        print(f"[{index}/{len(cases)}] {case.name}", flush=True)
        try:
            rows.append(evaluate_case(args.url, case, args.organ, args.label_value))
        except requests.RequestException as exc:
            rows.append({"case": case.name, "error": str(exc)})

    summary = summarise(rows)
    baseline = None
    if args.baseline:
        baseline = json.loads(args.baseline.read_text()).get("summary")

    render(rows, summary, baseline)

    if args.json:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(json.dumps(
            {
                "organ": args.organ,
                "dataset": str(args.dataset),
                "url": args.url,
                "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
                "summary": summary,
                "cases": rows,
            },
            indent=2,
        ))
        print(f"Written to {args.json}")

    if summary.get("failed"):
        print(f"{summary['failed']} case(s) did not produce a score.", file=sys.stderr)
        return 1

    if args.min_mean_dice is not None:
        mean_dice = summary.get("mean_dice")
        if mean_dice is None or mean_dice < args.min_mean_dice:
            print(
                f"Mean Dice {mean_dice} is below the required {args.min_mean_dice}.",
                file=sys.stderr,
            )
            return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
