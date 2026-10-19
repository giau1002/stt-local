#!/usr/bin/env python3
import argparse
import hashlib
import json
import os
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--load", action="store_true")
    args = parser.parse_args()
    root = Path(os.getenv("MODEL_DIR", "models"))
    manifest = json.loads((root / "manifest.json").read_text())
    for name, expected in manifest["sha256"].items():
        with (root / name).open("rb") as handle:
            if hashlib.file_digest(handle, "sha256").hexdigest() != expected:
                raise SystemExit(f"Checksum mismatch: {name}")
    import torch
    print(json.dumps({"torch": torch.__version__, "cuda_available": torch.cuda.is_available(),
                      "gpu": torch.cuda.get_device_name(0) if torch.cuda.is_available() else None,
                      "model_files_verified": len(manifest["sha256"])}, indent=2))
    if args.load:
        import numpy as np
        from vietvoice.config import Settings
        from vietvoice.models import ModelBundle
        from vietvoice.pipeline import Pipeline
        pipeline = Pipeline(ModelBundle(Settings()))
        events = []
        for _ in range(15):
            events += pipeline.feed(np.zeros(1600, dtype="<i2").tobytes())
        events += pipeline.finish()
        print(json.dumps(events[-1], ensure_ascii=False))
        if any(e.get("text", "").strip() for e in events):
            raise SystemExit("Unexpected text on silence")
        print("PASS: real models loaded; streaming and final flush passed.")


if __name__ == "__main__":
    main()
