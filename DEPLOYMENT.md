# Triển khai và vận hành

## LAN có HTTPS

1. Tạo DNS nội bộ, ví dụ `voice.office.internal`, trỏ tới máy L40S.
2. Thêm/sửa trong `.env`:

```dotenv
VV_DOMAIN=voice.office.internal
ALLOWED_ORIGINS=https://voice.office.internal
SECURE_COOKIE=true
```

3. Chạy:

```bash
docker compose -f compose.yaml -f compose.tls.yaml up -d
docker compose -f compose.yaml -f compose.tls.yaml cp proxy:/data/caddy/pki/authorities/local/root.crt ./vietvoice-root.crt
```

4. Cài `vietvoice-root.crt` vào kho CA tin cậy của máy/trình duyệt người dùng. Mở `https://voice.office.internal`. Phải hết lỗi chứng chỉ trước khi thử microphone. Caddy đang dùng CA nội bộ, không cần mua chứng chỉ hay gọi dịch vụ STT ngoài.

Nếu đã có reverse proxy của công ty, dùng proxy đó tới `127.0.0.1:8080`, bật WebSocket và timeout ít nhất 2 giờ. Đặt `ALLOWED_ORIGINS` đúng origin HTTPS (không có dấu `/` cuối), `SECURE_COOKIE=true`. Không thêm wildcard origin. Để cổng PostgreSQL nội bộ.

## Offline hoàn toàn

Build image, tải model và pull PostgreSQL/Caddy trên máy có Internet trước. Sau đó chuyển image và `models/` vào máy kín:

```bash
docker compose pull db
docker save vietvoice-local:0.1 postgres:17.6-bookworm -o vietvoice-images.tar
# Nếu dùng TLS, pull/save thêm caddy:2.10.2-alpine.
# Máy đích:
docker load -i vietvoice-images.tar
docker compose up -d --no-build api
```

Sao chép cả `models/manifest.json` và các thư mục model. Script download pin revision HF, tạo `tokens.txt` từ BPE đúng ID, ghi SHA256; doctor kiểm tra checksum. Không dùng `config.json` của hai repo Zipformer vì inference sử dụng metadata ONNX.

Runtime đặt `HF_HUB_OFFLINE=1`, `TRANSFORMERS_OFFLINE=1`, `HF_HUB_DISABLE_TELEMETRY=1`, `DO_NOT_TRACK=1`, và `local_files_only=True`. API/DB ở Docker network `internal: true`; chỉ service `download` dùng mạng ra ngoài trong bước chuẩn bị. Cần xác minh chính sách egress thực tế ở host trước khi đưa vào sử dụng.

## Chạy Python để phát triển / chẩn đoán CPU

Python 3.12; trên Linux cần thư viện hệ thống `libsndfile1` và `libgomp1`. Gói bàn giao đã có frontend build sẵn. Node 22 cần khi sửa UI.

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install torch==2.10.0 --index-url https://download.pytorch.org/whl/cpu
pip install -r backend/requirements-dev.txt
python scripts/bootstrap.py
python scripts/download_models.py
set -a
source .env
set +a
export DIAR_DEVICE=cpu
export PYTHONPATH=backend
export HF_HUB_OFFLINE=1
export TRANSFORMERS_OFFLINE=1
python scripts/doctor.py --load
uvicorn vietvoice.app:create_app --factory --host 127.0.0.1 --port 8080 --workers 1 --ws websockets --ws-max-queue 16 --ws-max-size 8192
```

Chạy Python trực tiếp mặc định tạo `data/vietvoice.db` bằng SQLite. Nếu chỉ muốn kiểm tra UI không tải AI, thêm `LOAD_MODELS=false`; ứng dụng sẽ báo chưa sẵn sàng và không cho ghi. Đây không phải chế độ STT giả.

Nếu dùng Vite dev server ở `http://localhost:5173`, thêm origin này vào `ALLOWED_ORIGINS`, giữ backend ở 8080 và chạy `npm run dev` trong `frontend/`.

## Benchmark trên L40S

Chuyển file kiểm thử về PCM16 mono 16 kHz:

```bash
ffmpeg -i input.wav -ar 16000 -ac 1 -c:a pcm_s16le test.wav
python scripts/stream_wav.py test.wav --url http://localhost:8080 --output result.json
```

Script hỏi APP_KEY nếu biến môi trường chưa có. Không đặt APP_KEY trên URL. Với HTTPS CA nội bộ, cài CA cho Python/máy chạy client; không bỏ kiểm tra TLS.

Theo dõi `nvidia-smi`, CPU, RAM và `docker compose logs api`. Kết quả JSON chứa `client_elapsed` tại sự kiện, audio timestamp, `compute_seconds` và RTF. RTF là thời gian xử lý gồm thời gian chờ khóa chia cho thời lượng âm thanh; không thay thế p95 latency.

Nghiệm thu bằng ghi âm thực của đơn vị:

- 1, 2, 4 rồi 8 người; Bắc/Trung/Nam; nói ngắn và đổi lượt nhanh.
- Tên riêng, số, thuật ngữ; mic xa, tiếng quạt, im lặng, nói chồng.
- Ít nhất một phiên 60–120 phút để quan sát drift, RAM và speaker cache.
- Đo WER/CER bằng transcript chuẩn; DER/JER bằng nhãn người nói chuẩn; p50/p95 cho nháp và chốt.
- Tăng tải đồng thời từ 1 phiên. Không tăng workers của cùng instance; mỗi worker tạo bản sao model và giới hạn riêng. Muốn mở rộng cần nhiều instance, định tuyến phiên và đo lại.

Mục tiêu nháp khoảng 1–2 giây và chốt thêm vài giây sau endpoint chỉ là mục tiêu nghiệm thu, **chưa được bảo đảm** cho dữ liệu/máy của anh. `DIAR_MODE=low_latency` ưu tiên ngữ cảnh; có thể thử `very_low_latency` hoặc `ultra_low_latency`, nhưng phải đo lại lỗi gán người nói.

## Dữ liệu và phục hồi

PostgreSQL volume `postgres_data` giữ transcript; API không ghi raw audio ra file. Xem/lưu/sao lưu dữ liệu theo chính sách nội bộ. Ví dụ sao lưu:

```bash
docker compose exec -T db pg_dump -U vietvoice -d vietvoice > backup.sql
```

Đổi APP_KEY sẽ hết hiệu lực cookie hiện tại. Giữ `.env`, backup và DB ngoài git. `docker compose down` giữ volume; **không dùng `down -v` nếu muốn giữ bản ghi**.

Khi restart, phiên đang ghi chuyển trạng thái `interrupted`. Chỉ bản chốt đã commit vào DB tồn tại sau crash; draft/audio trong RAM không tồn tại. Mất mạng vẫn cố flush phần đã nhận, nhưng client cần mở lại phiên để đọc kết quả lưu cuối.

## Lỗi thường gặp

| Hiện tượng | Cách kiểm tra |
|---|---|
| CUDA unavailable | `nvidia-smi`, NVIDIA Container Toolkit, quyền GPU của container |
| 503 / chưa nạp model | Log API, đã chạy download chưa, đường dẫn/permission của `models/` |
| Microphone bị từ chối | HTTPS/localhost, chứng chỉ CA, quyền mic của trình duyệt |
| WebSocket bị từ chối | APP_KEY/cookie, origin chính xác, reverse proxy WebSocket |
| Dừng vì chậm | CPU threads, tải GPU, giảm MAX_SESSIONS; không bỏ kiểm tra hàng đợi |
| Người nói chưa xác định | Câu quá ngắn, đổi lượt hoặc nói chồng; kiểm thử với mic tách kênh nếu cần |

Docker image/Compose và đường chạy CUDA cần được chạy thử trên máy đích; môi trường bàn giao không có Docker daemon hay GPU để xác minh hai phần này.
