# AI Service (Python / FastAPI / MONAI)

Runs CT organ segmentation using two pretrained MONAI Model Zoo bundles:

- **`spleen_ct_segmentation`** - a dedicated 3D UNet trained on the Medical
  Segmentation Decathlon Task09_Spleen dataset. Used for the "spleen" option
  - the most accurate choice for that one organ.
- **`wholeBody_ct_segmentation`** - a SegResNet trained to segment 104
  structures in one pass (TotalSegmentator-style). Used for every other organ
  in the picker (liver, kidneys, gallbladder, stomach, pancreas, bladder) by
  running the full model once and keeping only the requested label. Runs at
  its "low-res" (3mm) checkpoint by default for CPU-friendly speed.

See `app/organs.py` for the full list of organ keys and which engine backs
each one.

> Educational / demo project. Not a medical device. Not for clinical use.
> Segmentation quality varies by organ - liver/kidney/spleen tend to be
> reliable, pancreas is a known hard case for this class of model (small,
> irregular shape, low contrast) and may under-segment.

## Endpoints

- `GET /health` - service + model status
- `GET /organs` - list of available organ keys + display names
- `POST /segment` - multipart upload of a `.nii` / `.nii.gz` CT volume, plus
  an `organ` form field (defaults to `spleen`). Returns a base64-encoded
  segmentation mask (same shape/affine as the input) plus stats (voxel
  count, estimated volume in mL, inference time, which model/organ ran).

Pretrained weights are downloaded automatically on first use per model and
cached under `MODEL_DIR` (default `/app/models`) - the first `spleen`
request and the first request for any *other* organ (which triggers the
larger `wholeBody_ct_segmentation` download) will each be slower than
subsequent ones.

## Local development (without Docker)

```bash
cd ai-service
python3.11 -m venv .venv
source .venv/bin/activate
pip install torch --index-url https://download.pytorch.org/whl/cpu
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8001
```
