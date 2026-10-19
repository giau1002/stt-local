# API v0.1

API riêng của project, không phải drop-in replacement cho Soniox.

## Đăng nhập

`POST /api/login` với JSON `{"key":"APP_KEY"}`. Server trả cookie HttpOnly `vv_session`, SameSite strict, hết hạn 12 giờ. Client trình duyệt cùng origin tự gửi cookie; client khác dùng cookie jar. Không truyền key trên URL WebSocket.

`POST /api/logout` xóa cookie. Mọi `/api/status`, `/api/sessions` và stream đều cần đăng nhập. Origin trình duyệt phải nằm trong `ALLOWED_ORIGINS`; client không có Origin vẫn phải có cookie hợp lệ.

## WebSocket `/api/stream`

1. Gửi JSON đầu tiên trong 15 giây:

```json
{"type":"start","encoding":"pcm_s16le","sample_rate":16000,"title":"Họp nội bộ"}
```

2. Nhận `{"type":"started","session_id":"UUID","next_seq":0}`.
3. Gửi binary: **4 byte uint32 little-endian sequence**, sau đó PCM signed int16 little-endian, mono, 16 kHz. Tối đa 3200 mẫu/packet (200 ms); UI dùng 1600 mẫu (100 ms). Sequence tăng 0,1,2… và gửi theo thời gian thực.
4. Nhận các sự kiện sau. `partial` là toàn bộ giả thuyết của segment, thay draft cũ cùng ID. `final` thay draft cùng ID và trở thành bất biến. Có thể vẫn có draft của segment sau trong lúc segment trước chờ diarization.

```json
{"type":"partial","segment_id":0,"text":"XIN CHÀO","start":0,"end":1.2,"is_final":false}
```

```json
{
  "type":"final","segment_id":0,"is_final":true,"start":0,"end":1.6,
  "text":"XIN CHÀO",
  "tokens":[{"text":" XIN","start":0.2,"end":0.5,"timing":"rnnt_estimated","speaker_id":"speaker_1","speaker_score":0.95,"overlap":false}],
  "turns":[{"text":"XIN CHÀO","start":0.2,"end":1.2,"speaker_id":"speaker_1","overlap":false}]
}
```

Ví dụ rút gọn; một từ có thể có nhiều BPE token. Không nối token bằng thêm dấu cách; token đã chứa dấu cách cần thiết. `speaker_id` có thể null. `turns` nhóm token liền nhau cùng người nói/overlap, thuận tiện hiển thị.

`{"type":"ack","seq":4,"audio_seconds":0.5}` xác nhận xử lý audio. Duplicate thêm `duplicate:true`, không tăng audio duration.

5. Gửi `{"type":"end"}`. Chờ các final còn lại và:

```json
{"type":"done","audio_seconds":12.3,"compute_seconds":3.4,"rtf":0.276,"status":"completed"}
```

Server đóng socket sau done. `status` có thể `interrupted`. Lỗi có dạng `{"type":"error","code":"...","message":"..."}`. Không coi socket close là hoàn thành nếu chưa nhận done. Sau lỗi flush, DB có thể ở trạng thái failed; phần final trước đó vẫn có.

## REST

| Method / path | Kết quả |
|---|---|
| `GET /health/live` | Process đang phục vụ |
| `GET /health/ready` | 200 khi model nạp được, 503 khi chưa sẵn sàng |
| `GET /api/status` | Model readiness, lỗi khởi động, device, số phiên |
| `GET /api/sessions` | 100 phiên gần nhất |
| `GET /api/sessions/{id}` | Metadata, tên người nói, tất cả final segments |
| `PUT /api/sessions/{id}/speakers/speaker_1` | Body `{"name":"Anh An"}`, tối đa 80 ký tự |
| `GET /api/sessions/{id}/export/txt` | Bản ghi có timestamp và tên |
| `GET /api/sessions/{id}/export/json` | Metadata, tokens, turns và speaker mapping |
| `GET /api/sessions/{id}/export/srt` | Phụ đề theo các lượt lời ước lượng |

Ví dụ client WAV hoàn chỉnh: `scripts/stream_wav.py`. Raw audio không được lưu hay đưa vào REST response.
