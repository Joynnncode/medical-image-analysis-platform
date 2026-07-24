# AI Service (Python / FastAPI / MONAI)

Runs spleen CT segmentation using the pretrained MONAI Model Zoo bundle
`spleen_ct_segmentation` (3D UNet trained on the Medical Segmentation
Decathlon Task09_Spleen dataset).

> Educational / demo project. Not a medical device. Not for clinical use.

## Endpoints

- `GET /health` - service + model status
- `POST /segment` - multipart upload of a `.nii` / `.nii.gz` CT volume, returns
  a base64-encoded segmentation mask (same shape/affine as the input) plus
  basic stats (voxel count, estimated volume in mL, inference time).

The pretrained weights (~tens of MB) are downloaded automatically on the
first `/segment` request and cached under `MODEL_DIR` (default
`/app/models`), so the first request after a fresh start will be slower.

## Local development (without Docker)

```bash
cd ai-service
python3.11 -m venv .venv
source .venv/bin/activate
pip install torch --index-url https://download.pytorch.org/whl/cpu
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8001
```
