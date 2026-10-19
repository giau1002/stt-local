"""Real local model adapters. No fabricated transcription fallback."""
import json
import threading
from pathlib import Path
import numpy as np

SR = 16000


class ModelBundle:
    def __init__(self, settings):
        import sherpa_onnx
        import torch
        from transformers import AutoModelForAudioFrameClassification, AutoProcessor
        self.lock = threading.RLock()
        root = Path(settings.model_dir)
        manifest = json.loads((root / "manifest.json").read_text())
        self.manifest = manifest
        torch.set_num_threads(settings.threads)
        if settings.diar_device == "cuda" and not torch.cuda.is_available():
            raise RuntimeError("CUDA unavailable. Check NVIDIA driver / Container Toolkit; DIAR_DEVICE=cpu is for diagnostics.")
        self.vad_config = sherpa_onnx.VadModelConfig(
            silero_vad=sherpa_onnx.SileroVadModelConfig(
                model=str(root / manifest["vad"]), threshold=0.5, min_speech_duration=0.1,
                min_silence_duration=0.4, max_speech_duration=settings.segment_seconds),
            sample_rate=SR, num_threads=1, provider="cpu")

        def paths(name):
            return {key: str(root / manifest[name][key]) for key in ("encoder", "decoder", "joiner", "tokens")}
        # Small Zipformers on CPU; GPU reserved for the diarizer. No CUDA sherpa wheel dependency.
        self.online = sherpa_onnx.OnlineRecognizer.from_transducer(
            **paths("streaming"), provider="cpu", num_threads=settings.threads, sample_rate=SR,
            feature_dim=80, decoding_method="greedy_search", enable_endpoint_detection=True,
            rule1_min_trailing_silence=2.0, rule2_min_trailing_silence=0.8,
            rule3_min_utterance_length=settings.segment_seconds)
        self.offline = sherpa_onnx.OfflineRecognizer.from_transducer(
            **paths("offline"), provider="cpu", num_threads=settings.threads, sample_rate=SR,
            feature_dim=80, decoding_method="greedy_search")
        self.processor = AutoProcessor.from_pretrained(root / "diarization", local_files_only=True, trust_remote_code=False)
        self.processor.set_streaming_mode(settings.diar_mode)
        self.diarizer = AutoModelForAudioFrameClassification.from_pretrained(
            root / "diarization", local_files_only=True, trust_remote_code=False,
            dtype=torch.float32, attn_implementation="sdpa").to(settings.diar_device).eval()

    def create(self):
        with self.lock:
            return ZipformerStream(self), DiarizationStream(self)

    def refine(self, audio):
        with self.lock:
            stream = self.offline.create_stream()
            stream.accept_waveform(SR, audio)
            self.offline.decode_stream(stream)
            result = stream.result
            return {"text": result.text, "tokens": list(result.tokens), "timestamps": list(result.timestamps)}


class ZipformerStream:
    def __init__(self, bundle):
        import sherpa_onnx
        self.bundle = bundle
        self.stream = bundle.online.create_stream()
        self.vad = sherpa_onnx.VoiceActivityDetector(bundle.vad_config, buffer_size_in_seconds=30)
        self.has_speech = False
        self.speech_start = None
        self.speech_end = 0

    def _collect_vad(self):
        self.has_speech = self.has_speech or self.vad.is_speech_detected() or not self.vad.empty()
        completed = False
        while not self.vad.empty():
            segment = self.vad.front
            self.speech_start = segment.start if self.speech_start is None else min(self.speech_start, segment.start)
            self.speech_end = max(self.speech_end, segment.start + len(segment.samples))
            completed = True
            self.vad.pop()
        return completed

    def finish_speech(self):
        self.vad.flush()
        self._collect_vad()
        return self.has_speech

    def speech_bounds(self, total):
        # Retain 100 ms context around detected speech; don't refine long trailing silence.
        return max(0, (self.speech_start or 0) - 1600), min(total, self.speech_end + 1600)

    def feed(self, audio):
        with self.bundle.lock:
            self.vad.accept_waveform(audio)
            completed = self._collect_vad()
            rec = self.bundle.online
            self.stream.accept_waveform(SR, audio)
            while rec.is_ready(self.stream):
                rec.decode_stream(self.stream)
            # RNNT endpoints lag due to lookahead and can cut into the next voice.
            endpoint = (completed and not self.vad.is_speech_detected()) or (not self.has_speech and rec.is_endpoint(self.stream))
            return rec.get_result(self.stream) if self.has_speech else "", endpoint

    def reset(self):
        with self.bundle.lock:
            self.stream = self.bundle.online.create_stream()
            self.vad.reset()
            self.has_speech = False
            self.speech_start = None
            self.speech_end = 0


class DiarizationStream:
    """Overlapping STFT windows, continuous per-session cache, bounded audio buffer."""
    def __init__(self, bundle):
        self.bundle = bundle
        self.cache = None
        self.buffer = np.empty(0, dtype=np.float32)
        self.base = 0
        self.mel_cursor = 0
        self.first = True
        self.finished = False
        p = bundle.processor
        self.frame_seconds = p.feature_extractor.hop_length / p.feature_extractor.sampling_rate

    def _infer(self, audio, final=False):
        import torch
        p, model = self.bundle.processor, self.bundle.diarizer
        with self.bundle.lock, torch.inference_mode():
            inputs = p(audio, sampling_rate=SR, is_streaming=True, is_first_audio_chunk=self.first,
                       is_last_audio_chunk=final, return_tensors="pt")
            if final:
                inputs["num_lookahead_frames"] = 0
            inputs = inputs.to(model.device, dtype=model.dtype)
            output = model(**inputs, speaker_cache=self.cache)
            self.cache = output.speaker_cache
            return output.logits[0].sigmoid().float().cpu().numpy()

    def feed(self, audio, final=False):
        if self.finished:
            raise RuntimeError("Diarization stream already finished")
        self.buffer = np.concatenate((self.buffer, audio))
        p, chunks = self.bundle.processor, []
        while True:
            start = 0 if self.first else p.audio_chunk_start(self.mel_cursor)
            offset = start - self.base
            needed = p.num_samples_first_audio_chunk if self.first else p.num_samples_per_audio_chunk
            available = len(self.buffer) - offset
            if available < needed:
                break
            chunks.append(self._infer(self.buffer[offset:offset + needed]))
            self.first = False
            self.mel_cursor += p.num_mel_frames_per_step
            next_start = p.audio_chunk_start(self.mel_cursor)
            self.buffer = self.buffer[next_start - self.base:]
            self.base = next_start
        if final:
            if available > 0:
                tail = self.buffer[offset:]
                if self.first and len(tail) < 512:
                    tail = np.pad(tail, (0, 512 - len(tail)))
                chunks.append(self._infer(tail, final=True))
            self.finished = True
            self.cache = None
            self.buffer = np.empty(0, dtype=np.float32)
        return np.concatenate(chunks) if chunks else np.empty((0, 8), dtype=np.float32)
