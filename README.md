# VietVoice Local

Project self-host chuyển giọng nói tiếng Việt thành văn bản trực tiếp, tự phân biệt người nói và lưu bản ghi. Giao diện Vue 3; API FastAPI/WebSocket; Docker dành cho máy NVIDIA L40S 48 GB.

**Bản 0.1 là triển khai tham chiếu có luồng AI thật.** Có bản nháp streaming, nhận dạng lại trước khi chốt, speaker ID, đổi tên người nói và xuất TXT/JSON/SRT. Không gọi API nhận dạng trả phí. Model tải một lần; suy luận đọc hoàn toàn từ ổ đĩa.

## Chạy nhanh trên L40S

Yêu cầu: Linux x86-64, Docker Engine + Compose v2.30 trở lên, NVIDIA driver tương thích CUDA 12.8 và NVIDIA Container Toolkit. Kiểm tra `nvidia-smi` trên host trước. Khuyến nghị khởi đầu 16 CPU threads, RAM 64 GB, SSD trống 30 GB; đây là cấu hình dự kiến, chưa phải mức tối thiểu đã benchmark.

```bash
cd vietvoice-local
python3 scripts/bootstrap.py
docker compose build api
docker compose --profile setup run --rm download
docker compose run --rm --no-deps api python scripts/doctor.py --load
docker compose up -d api
docker compose logs -f api
```

Mở **http://localhost:8080** trên máy chủ. Nhập `APP_KEY` được sinh trong `.env`, chờ trạng thái “AI đã sẵn sàng”, bấm **Bắt đầu ghi**, cấp quyền microphone rồi **Dừng & lưu**. Không có mật khẩu mặc định trong mã nguồn. Thư mục `models/` khoảng 1 GB; image CUDA lớn hơn đáng kể.

Nếu truy cập từ máy khác trong LAN, **phải dùng HTTPS** để trình duyệt cho phép microphone. Làm theo [DEPLOYMENT.md](DEPLOYMENT.md). Cổng 8080 mặc định chỉ bind loopback.

## Thành phần

| Thành phần | Cách dùng |
|---|---|
| `hynt/Zipformer-30M-RNNT-Streaming-6000h` | RNNT streaming thật, ONNX FP16 chunk 16, chạy CPU bằng sherpa-onnx |
| `hynt/Zipformer-30M-RNNT-6000h` | Model anh chọn, ONNX INT8 nhận dạng lại đoạn trước khi phát bản chốt |
| Silero VAD | Loại đoạn không có tiếng nói để giảm việc sinh chữ trên im lặng |
| `nvidia/Nemotron-3-Diarization` | Streaming diarization trên GPU qua Transformers; cache riêng cho từng phiên |
| PostgreSQL | Lưu bản chốt, metadata phiên và tên người nói; SQLite cho chạy Python trực tiếp |
| Vue 3 + AudioWorklet | Microphone mono 16 kHz, gửi PCM16 mỗi 100 ms qua WebSocket |

L40S 48 GB phù hợp với hướng triển khai này. Hai Zipformer nhỏ chạy CPU; GPU dành cho Nemotron. Mặc định chỉ **1 phiên đồng thời** để nghiệm thu chất lượng/độ trễ trước; chưa có số liệu xác nhận số phiên L40S chịu được. Tăng `MAX_SESSIONS` sau khi đo; worker hiện khóa suy luận chung để bảo vệ model/cache.

## Những gì cần hiểu đúng

- Tối đa **8 người nói trong một phiên**, do model diarization. ID không nhận diện danh tính thật và không nối danh tính qua phiên.
- Bản nháp thay đổi; bản chốt đã lưu không bị nhận dạng lại âm thầm. Tên hiển thị có thể đổi riêng.
- Gần ranh giới đổi người nói hoặc khi nói chồng, trả `speaker_id=null`/`overlap=true`. **Không tách thành hai nguồn âm thanh** và không bảo đảm chép đủ hai giọng nói đồng thời.
- Timestamp RNNT là thời điểm phát token; kết thúc token được ước lượng. Không phải forced alignment chính xác từng âm vị.
- Endpoint theo Silero VAD/khoảng lặng và giới hạn 12 giây; không có semantic endpoint như Soniox. Nói liền quá lâu có thể bị cắt giữa từ; cần đo và điều chỉnh `MAX_SEGMENT_SECONDS` với dữ liệu thật.
- Đây là giao diện/trải nghiệm tương tự dịch vụ streaming, **không phải API Soniox tương thích hoàn toàn**, không cam kết độ chính xác tương đương Soniox.
- Mất kết nối kết thúc phiên: máy chủ cố chốt phần đã nhận; client mở lại bản lưu. Chưa có tiếp tục âm thanh qua reconnect hay khôi phục cache sau restart. Âm thanh chưa tới máy chủ không được phục hồi.
- Bản 0.1 dùng một mã truy cập chung cho nhóm nội bộ; chưa có tài khoản riêng/RBAC/multi-tenant. Văn bản lưu trong DB; file âm thanh không lưu. Không có punctuation model hay viết hoa thông minh; model có thể trả chữ IN HOA.

## Giấy phép

Mã tự viết trong project dùng MIT; **không đổi giấy phép của model hoặc dependency**. Hai model `hynt` ghi **CC-BY-NC-ND-4.0**: không mặc định được dùng thương mại. Cần có quyền phù hợp từ tác giả cho mục đích thương mại/triển khai dịch vụ. Xem [MODEL_LICENSES.md](MODEL_LICENSES.md). Không có trọng số model trong gói mã nguồn.

## Kiểm tra và tích hợp

- [TEST_REPORT.md](TEST_REPORT.md): những gì đã thực sự kiểm thử và phần chưa đo.
- [API.md](API.md): giao thức WebSocket, REST và định dạng sự kiện.
- [ARCHITECTURE.md](ARCHITECTURE.md): cache, đồng bộ thời gian và vòng đời phiên.
- [DEPLOYMENT.md](DEPLOYMENT.md): LAN HTTPS, chạy Python, offline, sao lưu và benchmark.

```bash
# Sau khi cài môi trường phát triển theo DEPLOYMENT.md
pytest -q
ruff check backend scripts tests
cd frontend
npm ci
npm run build
```

Các mock chỉ nằm trong `tests/`. Thiếu model hoặc CUDA thì `/health/ready` trả 503 và nút ghi âm bị khóa; không có nội dung AI giả trong sản phẩm.
