"""Registry of organs the AI service can segment, and which underlying
model/label produces each one.

"spleen" uses the dedicated single-organ `spleen_ct_segmentation` bundle
(app/model.py). Everything else comes from the multi-organ
`wholeBody_ct_segmentation` bundle (app/wholebody_model.py), which predicts
105 structures in one pass - we just pick out the label index for the
requested organ. Label indices are from that bundle's published
`channel_def` metadata.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class OrganSpec:
    engine: str  # "spleen" | "wholebody"
    label_index: int | None  # index into the wholebody model's 105 labels
    display_name: str
    model_name: str


ORGANS: dict[str, OrganSpec] = {
    "spleen": OrganSpec("spleen", None, "Spleen", "spleen_ct_segmentation"),
    "liver": OrganSpec("wholebody", 5, "Liver", "wholeBody_ct_segmentation"),
    "kidney_right": OrganSpec("wholebody", 2, "Right kidney", "wholeBody_ct_segmentation"),
    "kidney_left": OrganSpec("wholebody", 3, "Left kidney", "wholeBody_ct_segmentation"),
    "gallbladder": OrganSpec("wholebody", 4, "Gallbladder", "wholeBody_ct_segmentation"),
    "stomach": OrganSpec("wholebody", 6, "Stomach", "wholeBody_ct_segmentation"),
    "pancreas": OrganSpec("wholebody", 10, "Pancreas", "wholeBody_ct_segmentation"),
    "urinary_bladder": OrganSpec("wholebody", 104, "Urinary bladder", "wholeBody_ct_segmentation"),
}

DEFAULT_ORGAN = "spleen"
