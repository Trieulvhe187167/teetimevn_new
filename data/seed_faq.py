from pathlib import Path
import sqlite3

ROOT = Path(__file__).resolve().parents[1]
DB_PATH = ROOT / 'data' / 'teetimevn_dev.db'

FAQ_ITEMS = [
    ("booking-process", 10, {
        'en': ("How do I book a tee time?", "Select a course, choose date and time, fill your details and submit. We will confirm via email or chat shortly."),
        'vi': ("Làm sao để đặt giờ chơi?", "Chọn sân, ngày giờ, điền thông tin và gửi. Chúng tôi sẽ xác nhận qua email hoặc chat trong thời gian ngắn."),
    }),
    ("payment-methods", 20, {
        'en': ("What payment methods are available?", "We support bank transfer and selected e‑wallets. International cards can be arranged on request."),
        'vi': ("Có những phương thức thanh toán nào?", "Hỗ trợ chuyển khoản và một số ví điện tử. Thẻ quốc tế có thể sắp xếp theo yêu cầu."),
    }),
    ("currency-fx", 30, {
        'en': ("Which currency do you charge in?", "Prices are shown in VND. For reference, we display your selected currency using our latest FX rates."),
        'vi': ("Thanh toán bằng đơn vị tiền nào?", "Giá hiển thị theo VND. Tham khảo thêm tỉ giá quy đổi hiển thị theo tiền tệ bạn chọn."),
    }),
    ("included-services", 40, {
        'en': ("What is included in the green fee?", "Unless stated otherwise, rates typically include green fee and caddy. Cart and rentals may be extra."),
        'vi': ("Giá bao gồm những gì?", "Nếu không ghi chú khác, giá thường bao gồm phí sân và caddy. Xe điện và thuê gậy có thể tính thêm."),
    }),
    ("change-cancel", 50, {
        'en': ("Can I change or cancel my booking?", "Yes. Changes and cancellations follow each course’s policy. Contact us at least 24–48 hours in advance."),
        'vi': ("Có thể đổi/huỷ đặt chỗ không?", "Có. Việc đổi/huỷ tuân theo chính sách từng sân. Vui lòng liên hệ trước 24–48 giờ."),
    }),
    ("confirmation", 60, {
        'en': ("How do I receive confirmation?", "A booking voucher will be sent by email and chat. Please present it at the clubhouse on arrival."),
        'vi': ("Nhận xác nhận như thế nào?", "Chúng tôi gửi voucher đặt chỗ qua email và chat. Vui lòng xuất trình tại clubhouse khi đến."),
    }),
    ("group-booking", 70, {
        'en': ("Do you support group bookings?", "Yes. For 8+ golfers or corporate requests, contact us for tailored slots and transport options."),
        'vi': ("Hỗ trợ đoàn/nhóm không?", "Có. Với nhóm từ 8 người hoặc khách đoàn, hãy liên hệ để sắp xếp giờ chơi và phương tiện phù hợp."),
    }),
    ("languages", 80, {
        'en': ("Which languages are supported?", "We support English, Vietnamese, Korean, Japanese and Chinese (Simplified/Traditional)."),
        'vi': ("Hỗ trợ những ngôn ngữ nào?", "Chúng tôi hỗ trợ tiếng Anh, Việt, Hàn, Nhật và Trung (Giản/Phồn thể)."),
    }),
    ("rating-system", 90, {
        'en': ("How are course ratings calculated?", "Ratings average five aspects: design, turf maintenance, facilities/services, landscape, and playability."),
        'vi': ("Điểm đánh giá được tính như thế nào?", "Điểm trung bình của 5 yếu tố: thiết kế, bảo dưỡng cỏ, tiện ích/dịch vụ, cảnh quan, khả năng chơi."),
    }),
    ("contact", 100, {
        'en': ("How can I contact support?", "Chat with us on the website or email support@teetimevn.com. We’re available daily 08:00–20:00 (VN time)."),
        'vi': ("Liên hệ hỗ trợ bằng cách nào?", "Chat trực tiếp trên website hoặc email support@teetimevn.com. Thời gian hỗ trợ 08:00–20:00 (giờ VN)."),
    }),
]

def main():
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    # Insert base rows
    for slug, order, texts in FAQ_ITEMS:
        cur.execute("INSERT OR IGNORE INTO faq (slug, sort_order) VALUES (?, ?)", (slug, order))
        faq_id = cur.execute("SELECT id FROM faq WHERE slug=?", (slug,)).fetchone()[0]
        for lang, (q, a) in texts.items():
            cur.execute(
                """
                INSERT INTO faq_i18n (faq_id, lang, question, answer)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(faq_id, lang) DO UPDATE SET question=excluded.question, answer=excluded.answer
                """,
                (faq_id, lang, q, a)
            )

    conn.commit()
    conn.close()
    print('Seeded FAQ data.')

if __name__ == '__main__':
    main()

