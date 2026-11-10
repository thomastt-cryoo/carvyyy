"""Check Intel ONNX output against independent FP32 PyTorch reference predictions."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
from PIL import Image


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--models", type=Path, required=True)
    parser.add_argument("--references", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    from app.config import MODEL_REGISTRY, settings
    from app.onnx_depth import OnnxDA2Backend

    settings.models_dir = args.models.resolve()
    backend = OnnxDA2Backend(MODEL_REGISTRY["da2-small"])
    backend.load("cpu")
    records = []
    with np.load(args.references, allow_pickle=False) as references:
        for index in range(len(references.files) // 2):
            actual = backend.infer(Image.fromarray(references[f"image{index}"]))
            expected = references[f"depth{index}"]
            assert actual.shape == expected.shape
            error = np.abs(actual - expected)
            record = {
                "shape": list(actual.shape),
                "max_error": float(error.max()),
                "mean_error": float(error.mean()),
            }
            assert error.max() < 0.001 and error.mean() < 0.0001, record
            records.append(record)
    args.output.write_text(json.dumps(records, indent=2) + "\n")
    print(json.dumps(records, indent=2))


if __name__ == "__main__":
    main()
