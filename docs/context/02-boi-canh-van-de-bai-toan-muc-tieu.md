# Bối cảnh, vấn đề, bài toán cần giải và mục tiêu (ĐÃ CHỐT)

Chốt: Bối cảnh, Vấn đề, Bài toán ngày 12/10/2026; Mục tiêu ngày 15/10/2026. Đây là nguồn chuẩn về nghiệp vụ. Khi code và khi viết tài liệu, giữ đúng thuật ngữ trong file này ("doanh nghiệp", "số tiền phải nhận", "số tiền thực nhận", "chênh lệch").

## Bối cảnh

Mỗi đơn hàng thương mại điện tử đều phải qua hãng vận chuyển. Với đơn COD (thanh toán khi nhận hàng), hãng còn thu tiền thay cho người bán: thu tiền từ người mua, trừ các khoản phí, rồi chuyển phần còn lại cho người bán theo từng kỳ đối soát (chu kỳ hãng tổng hợp đơn và thanh toán). Kèm theo là bảng kê, tức danh sách các đơn và khoản tiền tương ứng. Trong thời gian đó, tiền nằm ở hãng.

Doanh nghiệp bán hàng là đơn vị bán trên nhiều sàn thương mại điện tử (Shopee, TikTok Shop, Lazada...), gửi hàng qua nhiều hãng vận chuyển (GHN, GHTK, Viettel Post, J&T Express, Ninja Van, SPX Express...) và nhận tiền COD từ các hãng. Từ đây gọi tắt là "doanh nghiệp".

Mỗi hãng áp dụng quy tắc riêng về khối lượng quy đổi (khối lượng tính theo kích thước kiện hàng thay cho cân thực), phí và phụ phí, lịch trả tiền COD, định dạng bảng kê và thời hạn khiếu nại (thời gian tối đa để phản đối một khoản tiền). Mỗi kỳ gồm 4 khoản cộng và 7 khoản trừ, nhiều hơn khi có đơn hoàn hàng (hàng không giao được, quay về người bán), trả hàng (người mua trả sau khi đã nhận) hoặc hàng lỗi. Số tiền hãng vận chuyển chuyển vào tài khoản sau khi cộng trừ gọi là **số tiền thực nhận**. Dòng tiền COD đúng hay lệch, nhanh hay chậm đều ảnh hưởng trực tiếp đến vốn xoay vòng của doanh nghiệp.

[Hình 1. Một kỳ đối soát: các khoản cộng, trừ và cách xác định chênh lệch. Hình nằm trong file Word đã giao ngày 12/10, không có trong repo.]

## Vấn đề

> **Doanh nghiệp bán hàng chỉ biết số tiền thực nhận, không biết số tiền phải nhận, và khi phát hiện chênh lệch thì thường đã hết hạn khiếu nại.**

*Số tiền phải nhận* là số tính theo quy tắc của hãng cho từng đơn. *Chênh lệch* là số tiền phải nhận trừ số tiền thực nhận.

1. **Mỗi hãng một bộ quy tắc.** Doanh nghiệp đối soát với nhiều hãng cùng lúc, nên số quy tắc phải theo dõi tăng theo số hãng. Không có thước đo chung giữa các hãng.

2. **Chênh lệch phát sinh ở nhiều khâu.**
   - Cước tính lệch so với quy định.
   - Phí hoàn bị trừ lệch hoặc trừ hai lần.
   - Đơn đã giao thiếu trong bảng kê.
   - Tiền thu hộ ghi thiếu hoặc lệch.
   - Tiền chuyển chậm so với hạn hẹn.

3. **Thiếu số tiền phải nhận để đối chiếu.** Doanh nghiệp không có sẵn số tiền mình phải nhận để so với số tiền hãng vận chuyển đã chuyển. Muốn có, phải tự tính lại từng đơn theo quy tắc và bảng kê của từng hãng.

4. **Thời hạn khiếu nại ngắn.** Có hãng chỉ cho 24 giờ, mỗi hãng một thời hạn. Kiểm tra thủ công tốn nhiều công hơn giá trị khoản đòi lại, nên nhiều khoản bị bỏ qua. Quá hạn là mất quyền đòi.

**Hệ quả đối với doanh nghiệp**

| Hệ quả | Biểu hiện |
|---|---|
| Thiếu căn cứ so sánh các hãng | Không có dữ liệu để chọn hãng phù hợp |
| Thất thoát khó nhận biết | Bị trừ lệch mà không hay biết |
| Khó xác định đơn bị trừ lệch | Hãng vận chuyển chuyển một khoản tổng cho cả kỳ, chênh lệch bị gộp bên trong |
| Không kịp đòi lại | Quá hạn khiếu nại hoặc chi phí kiểm tra quá cao |

[Hình 2. Quy trình đối soát 6 bước, 4 nhóm nguyên nhân và 4 hệ quả. Hình nằm trong file Word đã giao ngày 12/10, không có trong repo.]

## Bài toán cần giải

Làm thế nào để doanh nghiệp bán hàng, dù gửi qua bao nhiêu hãng, đều biết sớm **số tiền phải nhận**, **chênh lệch nằm ở đâu** và **còn bao lâu để đòi lại**, từ đó thu hồi khoản bị trừ lệch, giảm đối soát thủ công, chủ động dòng tiền và có dữ liệu chung để so sánh các hãng?

Đây là bài toán vận hành thời gian thực: doanh nghiệp không thiếu dữ liệu mà thiếu khả năng phát hiện sớm. Mỗi chênh lệch là một sự cố có hạn xử lý, phải phát hiện, điều tra và khiếu nại trước khi hết hạn, đúng luồng phát hiện, điều tra, phản ứng mà đề bài yêu cầu.

## Mục tiêu

Giúp doanh nghiệp bán hàng biết sớm **số tiền phải nhận** từ các hãng vận chuyển, **đơn nào đang chênh lệch** và **còn bao lâu để đòi lại**, thay vì chỉ biết số tiền thực nhận khi đã quá hạn khiếu nại.

**Lợi ích mang lại cho doanh nghiệp**

- **Lấy lại được tiền bị trừ lệch.** Hệ thống tính số tiền phải nhận của từng đơn rồi so với số thực nhận. Khoản nào lệch được báo ngay, kèm hạn khiếu nại, nên doanh nghiệp kịp đòi lại thay vì mất tiền mà không hay biết.
- **Tiết kiệm thời gian và nhân sự đối soát.** Mỗi hãng có quy tắc phí riêng nên hiện phải đối chiếu từng dòng bằng tay. Hệ thống tự đối soát theo quy tắc từng hãng, nhân viên chỉ xử lý những đơn đã được đánh dấu chênh lệch.
- **Chủ động dòng tiền.** Doanh nghiệp biết trước mình sẽ nhận bao nhiêu và đơn nào còn treo, nên lập kế hoạch nhập hàng và chi phí chính xác hơn.
- **Có căn cứ để chọn và làm việc với hãng vận chuyển.** Dữ liệu chênh lệch của từng hãng được đặt trên cùng một thước đo. Doanh nghiệp so sánh được các hãng và có bằng chứng cụ thể khi trao đổi hoặc khiếu nại.
- **Không bỏ sót đơn phát sinh.** Các trường hợp hoàn hàng, trả hàng, hàng lỗi vẫn được tính đúng theo công thức đối soát, nên không bị lọt khi tổng hợp thủ công.

**Tóm lại:** doanh nghiệp bớt thất thoát, bớt việc thủ công, rõ dòng tiền, và có dữ liệu thay vì cảm tính khi làm việc với các hãng vận chuyển.

*Ghi chú số liệu: chưa có số liệu công khai về tỷ lệ chênh lệch hay tổng thiệt hại, nên phần này không dùng số liệu thị trường. Mốc 24 giờ là thông tin do đội cung cấp. Con số minh họa trong slide, kể cả mức tiết kiệm ở phần Mục tiêu, cần ghi rõ là kịch bản giả định.*
