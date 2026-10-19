#!/usr/bin/env python3
"""Download pinned models once. The inference process never fetches files."""
import argparse
import hashlib
import json
from pathlib import Path
import urllib.request
from huggingface_hub import hf_hub_download
import sentencepiece as spm

SOURCES = {
    "streaming": ("hynt/Zipformer-30M-RNNT-Streaming-6000h", "c122fdc21cea4894fd775e9d3fe66ebbc787e26b"),
    "offline": ("hynt/Zipformer-30M-RNNT-6000h", "ad6f873b5f5b6ed083821253a88d81afed2505c4"),
    "diarization": ("nvidia/Nemotron-3-Diarization", "f667ed73aee57d40cc39428eb768b4fd87a0a29e"),
}
VAD_URL = "https://github.com/k2-fsa/sherpa-onnx/releases/download/asr-models/silero_vad.onnx"
VAD_SHA256 = "9e2449e1087496d8d4caba907f23e0bd3f78d91fa552479bb9c23ac09cbb1fd6"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=Path("models"))
    args = parser.parse_args()
    root = args.output.resolve()
    root.mkdir(parents=True, exist_ok=True)
    manifest = {"schema": 1, "sources": {}, "sha256": {}}
    for kind, (repo, revision) in SOURCES.items():
        directory = root / kind
        if kind == "streaming":
            names = {p: f"{p}-epoch-31-avg-11-chunk-16-left-128.fp16.onnx" for p in ("encoder", "decoder", "joiner")}
        elif kind == "offline":
            names = {p: f"{p}-epoch-20-avg-10.int8.onnx" for p in ("encoder", "decoder", "joiner")}
        else:
            names = {}
        files = list(names.values()) + (["bpe.model", "README.md"] if names else
                                        ["model.safetensors", "config.json", "processor_config.json", "README.md"])
        manifest["sources"][kind] = {"repo": repo, "revision": revision}
        for name in files:
            print(f"Downloading {kind}/{name}", flush=True)
            hf_hub_download(repo, filename=name, revision=revision, local_dir=directory)
        if names:
            # Upstream omits tokens.txt; preserve BPE IDs, including blank=0.
            sp = spm.SentencePieceProcessor(model_file=str(directory / "bpe.model"))
            if sp.id_to_piece(0) != "<blk>":
                raise RuntimeError("Unexpected blank ID; do not renumber vocabulary")
            (directory / "tokens.txt").write_text("".join(f"{sp.id_to_piece(i)} {i}\n" for i in range(sp.vocab_size())), encoding="utf-8")
            names["tokens"] = "tokens.txt"
            manifest[kind] = {part: f"{kind}/{name}" for part, name in names.items()}
        # Hash the explicit payload only; Hub may leave transient dotfiles during atomic moves.
        for name in files + (["tokens.txt"] if names else []):
            path = directory / name
            with path.open("rb") as handle:
                manifest["sha256"][str(path.relative_to(root))] = hashlib.file_digest(handle, "sha256").hexdigest()
    vad = root / "vad" / "silero_vad.onnx"
    vad.parent.mkdir(exist_ok=True)
    if not vad.exists() or hashlib.sha256(vad.read_bytes()).hexdigest() != VAD_SHA256:
        print("Downloading Silero VAD", flush=True)
        with urllib.request.urlopen(VAD_URL, timeout=120) as response:
            data = response.read()
        if hashlib.sha256(data).hexdigest() != VAD_SHA256:
            raise RuntimeError("Silero VAD checksum mismatch")
        vad.write_bytes(data)
    manifest["vad"] = "vad/silero_vad.onnx"
    manifest["sources"]["vad"] = {"url": VAD_URL, "sha256": VAD_SHA256}
    manifest["sha256"][manifest["vad"]] = VAD_SHA256
    temp = root / "manifest.json.tmp"
    temp.write_text(json.dumps(manifest, indent=2))
    temp.replace(root / "manifest.json")
    print(f"Models ready: {root}")


if __name__ == "__main__":
    main()
