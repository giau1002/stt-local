#!/usr/bin/env python3
from pathlib import Path
import secrets

root = Path(__file__).resolve().parents[1]
target = root / ".env"
if target.exists():
    raise SystemExit(".env đã tồn tại; giữ nguyên cấu hình hiện có.")
content = (root / ".env.example").read_text().replace("CHANGE_ME_WITH_BOOTSTRAP", secrets.token_urlsafe(36)).replace("CHANGE_DB_PASSWORD", secrets.token_hex(24))
target.write_text(content)
target.chmod(0o600)
(root / "models").mkdir(exist_ok=True)
(root / "data").mkdir(exist_ok=True)
print("Đã tạo .env. Xem APP_KEY trong file để đăng nhập giao diện.")
