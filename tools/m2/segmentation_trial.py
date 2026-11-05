"""Measure optional U2NETP against the retained GrabCut failures."""

import json
import os
import threading
import time
from pathlib import Path

import cv2
import numpy as np
import onnxruntime as ort
import psutil
from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "docs/m2/evidence"


def main():
    process = psutil.Process(os.getpid())
    baseline = process.memory_info().rss
    peak = [baseline]
    stop = threading.Event()

    def sample():
        while not stop.wait(0.02):
            peak[0] = max(peak[0], process.memory_info().rss)

    worker = threading.Thread(target=sample, daemon=True)
    worker.start()
    options = ort.SessionOptions()
    options.intra_op_num_threads = 4
    options.inter_op_num_threads = 1
    started = time.perf_counter()
    model = ort.InferenceSession(
        str(ROOT / "data/m2/segmentation-trial/u2netp.onnx"),
        options,
        providers=["CPUExecutionProvider"],
    )
    results = {"load_s": time.perf_counter() - started, "cases": []}
    for name in ["portrait", "pet", "ornament", "object", "complex"]:
        photo = Image.open(ROOT / f"docs/m1/evidence/inputs/{name}.png").convert("RGB")
        started = time.perf_counter()
        image = np.asarray(photo.resize((320, 320), Image.Resampling.LANCZOS))
        tensor = image.astype(np.float32) / max(float(image.max()), 1e-6)
        tensor = (tensor - np.array([0.485, 0.456, 0.406], np.float32)) / np.array(
            [0.229, 0.224, 0.225], np.float32
        )
        output = model.run(None, {model.get_inputs()[0].name: tensor.transpose(2, 0, 1)[None]})
        mask = output[0][0, 0]
        mask = (mask - mask.min()) / max(float(np.ptp(mask)), 1e-6)
        mask = cv2.resize(mask, photo.size, interpolation=cv2.INTER_LINEAR)
        elapsed = time.perf_counter() - started
        path = OUT / name
        Image.fromarray(np.rint(mask * 255).astype(np.uint8)).save(path / "u2netp-mask.png")
        overlay = np.asarray(photo).astype(np.float32).copy()
        overlay[:, :, 1:] *= mask[:, :, None] * 0.8 + 0.2
        sheet = Image.new("RGB", (900, 340), "white")
        draw = ImageDraw.Draw(sheet)
        for column, (picture, label) in enumerate(
            [
                (photo, "Photo"),
                (Image.open(path / "automatic-mask.png"), "GrabCut (failure retained)"),
                (Image.fromarray(overlay.astype(np.uint8)), "U2NETP mask / red = removed"),
            ]
        ):
            picture = picture.convert("RGB")
            picture.thumbnail((294, 300))
            sheet.paste(picture, (column * 300 + (300 - picture.width) // 2, 30))
            draw.text((column * 300 + 6, 8), label, fill="black")
        sheet.save(path / "segmentation-trial.jpg", quality=93)
        results["cases"].append(
            {"case": name, "inference_s": elapsed, "coverage": float(mask.mean())}
        )
        print(name, round(elapsed, 3), flush=True)
    stop.set()
    worker.join()
    results.update(
        baseline_rss_mb=baseline / 2**20,
        peak_rss_mb=peak[0] / 2**20,
        added_peak_mb=(peak[0] - baseline) / 2**20,
    )
    (OUT / "segmentation-trial.json").write_text(json.dumps(results, indent=2) + "\n")


if __name__ == "__main__":
    main()
