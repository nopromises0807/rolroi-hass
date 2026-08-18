## Hướng dẫn cài đặt

**Bước 1:** Thêm kho lưu trữ `https://github.com/thangnguyen0807/rolroi-hass` vào HACS.

**Bước 2:** Cài đặt như bình thường. Ưu tiên chọn phiên bản cao nhất để tránh lỗi.

**Bước 3:** Vào **Thiết bị và dịch vụ** → **Thêm bộ tích hợp** → chọn **ROL-ROI Steel Door**.

**Bước 4:** Nhập SĐT và mật khẩu phù hợp.

> ⚠️ **Lưu ý:** Nên sử dụng tài khoản phụ để tránh bị đăng xuất khi đăng nhập trên HASS.

🎉 **Cuối cùng, tận hưởng thành quả!**

## Bảo mật — v2.3.0

- Không chứa MQTT username/password dự phòng trong mã nguồn.
- Chỉ kết nối khi dịch vụ discovery của Hunonic trả đủ thông tin broker.
- Không ghi MQTT topic, `root_id`, payload đã giải mã, device ID hoặc user ID vào log.
- Nếu discovery MQTT không hoạt động, integration sẽ báo lỗi thay vì thử một credential nhúng sẵn.

> TLS/WSS và MQTT topic ACL phải được Hunonic cung cấp ở phía broker. Integration không thể tự biến một broker chỉ hỗ trợ `ws://` thành kết nối TLS an toàn.

<img width="512" height="512" alt="icon" src="https://github.com/user-attachments/assets/4220c12e-0e0e-46b5-9e6a-bd790b93872d" />
