# Báo cáo kiểm thử — 19/10/2026

Kiểm thử trong môi trường Linux x86-64, Python 3.12.14, PyTorch 2.10.0+cpu, sherpa-onnx 1.13.8, Transformers commit `d4804f9d76b8c071b993d813e9e87067b780cbee`. Không có GPU và Docker daemon ở môi trường này.

## Đã thực hiện

| Kiểm tra | Kết quả |
|---|---|
| Pytest giao thức và pipeline | 9 tests passed |
| Ruff backend/scripts/tests | Passed |
| Vue TypeScript + Vite production build | Passed; frontend build sẵn có trong `frontend/dist/` |
| Tải model theo revision, tạo vocab, load local | Tất cả 2 Zipformer, Silero và Nemotron nạp được |
| Mẫu im lặng 1,5 giây | Không sinh chữ sau khi thêm VAD |
| Tiếng Việt thật 3,74 giây | Có draft streaming, final, token timestamp và speaker_1 |
| Hai giọng luân phiên, 15,28 giây | Nhận speaker_1/speaker_2; ID giữ nguyên khi giọng tương ứng lặp lại; một số token ngắn để unknown |
| WebSocket qua server Uvicorn thật | Start → audio/ACK → partial/final → done → lưu DB; client WAV chạy được |
| Chromium 134 + AudioWorklet | Login → cấp microphone giả bằng WAV thật → ghi → dừng → final → rename → tải TXT thành công |
| Giao diện desktop 1440 px và mobile 390 px | Đã xem ảnh render; không có lỗi JS và không tràn ngang |

9 tests gồm: đợi diarization trước final, final không lặp, overlap/unknown và prune timeline, phiên trống/cách ly state, VAD chặn refine im lặng, auth/origin, duplicate + rename/export, gap sequence, giới hạn phiên, missing-model readiness (một số nội dung nằm chung test).

Nguồn audio công khai dùng nội bộ để test (không kèm trong archive):

- https://huggingface.co/spaces/hynt/k2-automatic-speech-recognition-demo/resolve/main/test_wavs/vietnamese/0.wav
- https://huggingface.co/spaces/hynt/k2-automatic-speech-recognition-demo/resolve/main/test_wavs/vietnamese/1.wav

Mẫu hai giọng là ghép 0 → 1 → 0 → 1, chèn 1 giây im lặng giữa các đoạn, tổng 15,28 giây. Đây là kiểm tra cache/đổi người nói trên clip ghép, không thay cho hội thoại tự nhiên và không chứng minh chất lượng diarization khi nói chồng.

## Kết quả hiệu năng có giới hạn

- Clip 3,74 giây: tổng thời gian xử lý pipeline khoảng 0,94 giây trong một lượt WebSocket CPU, RTF khoảng 0,25.
- Clip ghép 15,28 giây: khoảng 5,54 giây xử lý, RTF khoảng 0,36; có lúc kiểm thử khác cùng chạy.
- Các số này là smoke test ngắn, không phải benchmark ổn định, không phải độ trễ toàn trình hay p95. Không dùng để suy ra số phiên L40S hỗ trợ.

## Lỗi tích hợp đã sửa trong lúc kiểm tra

1. Zipformer offline sinh chữ trên im lặng: thêm Silero gate trước refine.
2. Endpoint RNNT trễ có thể cắt vào lời tiếp theo: dùng endpoint VAD và giữ context khi refine.
3. Đoạn im lặng dài ở cuối làm phát sinh thêm từ: crop vùng speech + 100 ms, dịch timestamp trở lại đúng offset.
4. Model repo không có `tokens.txt`: sinh đúng từ BPE, không đổi token IDs.
5. Checksum có thể nhặt file tạm của Hub: chỉ hash danh sách payload rõ ràng.

## Chưa được xác nhận

- Docker image build/run, PostgreSQL service, Caddy/CA, network isolation thực tế và CUDA/L40S.
- WER/CER/DER/JER trên tập kiểm thử có nhãn; chất lượng giọng địa phương, thuật ngữ, mic xa.
- 4–8 người thật, nói chồng, phiên 60–120 phút và tải đồng thời.
- Khả năng nhận đủ hai người đang nói cùng lúc: bản này không có speech separation.

Chỉ nên chốt cấu hình production sau khi chạy các bài nghiệm thu trong `DEPLOYMENT.md` trên máy và dữ liệu mục tiêu.
