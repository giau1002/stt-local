# Model và nguồn tham khảo

Trọng số không được đóng gói. Script tải trực tiếp từ nguồn theo revision cố định. Người vận hành cần có quyền sử dụng thích hợp; mã nguồn MIT của ứng dụng không cấp lại quyền đối với model.

| Thành phần | Giấy phép công bố / nguồn |
|---|---|
| Zipformer offline của hynt | CC-BY-NC-ND-4.0 — https://huggingface.co/hynt/Zipformer-30M-RNNT-6000h |
| Zipformer streaming của hynt | CC-BY-NC-ND-4.0 — https://huggingface.co/hynt/Zipformer-30M-RNNT-Streaming-6000h |
| NVIDIA Nemotron-3-Diarization | OpenMDW 1.1 — https://huggingface.co/nvidia/Nemotron-3-Diarization |
| Silero VAD | MIT — https://github.com/snakers4/silero-vad |
| sherpa-onnx | Apache-2.0 — https://github.com/k2-fsa/sherpa-onnx |
| Transformers | Apache-2.0 — https://github.com/huggingface/transformers |
| Vue | MIT — https://github.com/vuejs/core |
| FastAPI | MIT — https://github.com/fastapi/fastapi |

Hai model hynt có hạn chế NonCommercial và NoDerivatives. Không mặc định rằng dịch vụ thương mại hoặc phân phối model chuyển đổi/được chỉnh sửa là được phép. Cần xin quyền phù hợp từ tác giả cho trường hợp sử dụng đó. Các file model tải về giữ README gốc; vocab tokens.txt được dựng ở máy người dùng từ BPE để sherpa đọc, không chỉnh sửa weights.

Nguồn API kỹ thuật đã dùng:

- https://github.com/k2-fsa/sherpa-onnx/blob/master/sherpa-onnx/python/sherpa_onnx/online_recognizer.py
- https://github.com/k2-fsa/sherpa-onnx/blob/master/sherpa-onnx/python/sherpa_onnx/offline_recognizer.py
- https://github.com/huggingface/transformers/blob/d4804f9d76b8c071b993d813e9e87067b780cbee/src/transformers/models/nemotron3_diarization/processing_nemotron3_diarization.py
- https://soniox.com/docs/stt/rt/real-time-transcription — tham khảo hành vi draft/final, không dùng dịch vụ hay SDK Soniox.

Model revisions nằm trong `scripts/download_models.py`; manifest tạo khi tải bao gồm SHA256 từng file. Transformers pin commit vì API Nemotron streaming còn mới ở thời điểm xây dựng. Thay phiên bản phải chạy lại kiểm thử adapter/cursor/flush.
