"""Export the pinned FP32 Small model; validate dynamic aspect ratios against PyTorch."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import numpy as np
from PIL import Image

from tools.m5.package_runtime import SMALL_REVISION


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--source", type=Path)
    args = parser.parse_args()
    import onnx
    import torch
    from huggingface_hub import snapshot_download
    from transformers import pipeline

    torch.set_num_threads(4)
    source = args.source or Path(
        snapshot_download("depth-anything/Depth-Anything-V2-Small-hf", revision=SMALL_REVISION)
    )
    output = args.output.resolve()
    folder = output / "depth"
    folder.mkdir(parents=True, exist_ok=False)
    pipe = pipeline("depth-estimation", model=str(source), device=-1, dtype=torch.float32)
    pipe.model.eval()
    pipe.image_processor.save_pretrained(folder / "processor")

    class Model(torch.nn.Module):
        def __init__(self):
            super().__init__()
            self.model = pipe.model

        def forward(self, pixel_values):
            # The upstream head casts dynamic dimensions to int, freezing square
            # output during tracing. Keep the identical operations and weights
            # while passing the actual tensor dimensions to the final resize.
            height = pixel_values.shape[2] // self.model.config.patch_size
            width = pixel_values.shape[3] // self.model.config.patch_size
            features = self.model.backbone.forward_with_filtered_kwargs(pixel_values).feature_maps
            features = self.model.neck(features, height, width)
            head = self.model.head
            value = head.conv1(features[head.head_in_index])
            value = torch.nn.functional.interpolate(
                value,
                size=(height * head.patch_size, width * head.patch_size),
                mode="bilinear",
                align_corners=True,
            )
            value = head.conv3(head.activation1(head.conv2(value)))
            return (head.activation2(value) * head.max_depth).squeeze(1)

    model = Model().eval()
    filename = folder / "da2-small.onnx"
    with torch.inference_mode():
        torch.onnx.export(
            model,
            (torch.zeros(1, 3, 518, 518),),
            str(filename),
            input_names=["pixel_values"],
            output_names=["predicted_depth"],
            dynamic_axes={
                "pixel_values": {2: "height", 3: "width"},
                "predicted_depth": {1: "depth_height", 2: "depth_width"},
            },
            opset_version=17,
            dynamo=False,
        )
    onnx.checker.check_model(str(filename))
    metadata = {
        "model_id": "da2-small",
        "source": "depth-anything/Depth-Anything-V2-Small-hf",
        "source_revision": SMALL_REVISION,
        "precision": "float32",
        "opset": 17,
        "bytes": filename.stat().st_size,
        "sha256": hashlib.file_digest(filename.open("rb"), "sha256").hexdigest(),
        "torch": torch.__version__,
        "onnx": onnx.__version__,
    }
    (folder / "metadata.json").write_text(json.dumps(metadata, indent=2) + "\n")

    from app.config import MODEL_REGISTRY, settings
    from app.depth import normalize_to_closest
    from app.onnx_depth import OnnxDA2Backend

    settings.models_dir = output
    backend = OnnxDA2Backend(MODEL_REGISTRY["da2-small"])
    backend.load("cpu")
    tiger = Image.open(
        Path(__file__).resolve().parents[2] / "docs/m3/evidence/inputs/tiger.png"
    ).convert("RGB")
    references, records = {}, []
    for index, size in enumerate([(384, 384), (320, 480), (480, 320), (800, 300), (300, 800)]):
        image = tiger.resize(size, Image.Resampling.LANCZOS)
        with torch.inference_mode():
            expected = normalize_to_closest(pipe(image)["predicted_depth"].numpy(), "disparity")
        actual = backend.infer(image)
        error = np.abs(expected - actual)
        record = {
            "width": size[0],
            "height": size[1],
            "max_error": float(error.max()),
            "mean_error": float(error.mean()),
        }
        assert error.max() < 0.001 and error.mean() < 0.0001, record
        references[f"image{index}"] = np.array(image)
        references[f"depth{index}"] = expected
        records.append(record)
    np.savez_compressed(output / "references.npz", **references)
    (output / "parity.json").write_text(json.dumps(records, indent=2) + "\n")
    print(json.dumps({"metadata": metadata, "parity": records}, indent=2))


if __name__ == "__main__":
    main()
