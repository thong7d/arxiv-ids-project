# Đối chiếu đề trực tuyến — 13/11/2026

Nguồn kiểm tra: [tổng quan](https://hcmus-cs-ta.github.io/lab-book/intro-ds/statement/),
[M1](https://hcmus-cs-ta.github.io/lab-book/intro-ds/statement/crawling/),
[M2](https://hcmus-cs-ta.github.io/lab-book/intro-ds/statement/parsing/),
[M3](https://hcmus-cs-ta.github.io/lab-book/intro-ds/statement/matching/).
Nếu tài liệu snapshot cũ mâu thuẫn, dùng kết quả đối chiếu này và hướng dẫn giảng viên.

## Hợp đồng dữ liệu và các sửa đổi

| Điểm | Mã/cấu hình hiện hành |
|---|---|
| M1 source nguyên bản | Chỉ extract `.tex`/`.bib`; không xóa lệnh figure; PDF/Word không có TeX có record rỗng |
| M1 version | Không bỏ v1/revision; lấy metadata Atom theo version, không chép ngày cuối cho version thiếu |
| M1 references | Lưu toàn bộ S2 snapshot; view arXiv riêng, giữ ID cũ về ngữ nghĩa; ngày submission lấy arXiv |
| Benchmark | Colab CPU, đủ tập nhóm, retry/delay và toàn hệ thống; cache/resume không phải cold start |
| Book | Một Book hai chương M1/M2; hình/bảng sinh khi compile, host repo Pages riêng; chưa hoàn tất nội dung |
| Dataset | `papers`, `references`, `elements`, `hierarchy`, `bibtex`, `predictions`; không có bảng `sources` |

Protocol 4 không tự công nhận protocol 3 là đạt các yêu cầu mới. Baseline được giữ
nguyên, chỉ tái sử dụng bytes đã kiểm hash. Lượt live cũ dùng SHA `507ba...` vẫn là
protocol 3; số success trong lượt đó không chứng minh đã đạt toàn bộ hợp đồng mới.
Chỉ số cải thiện phải đo thật; unit test không chứng minh speedup hoặc chất lượng
toàn corpus. Không có cam kết tuyệt đối rằng Google/arXiv/S2 sẽ không ngắt hoặc lỗi.

## Ràng buộc cho giai đoạn sau

M2 phải đi từ root `documentclass`, theo include/input thực sự; không đọc file thừa
hay include trong comment. Parser cần đúng granularity, math/figure/table, giữ
appendix/acknowledgements, loại references khỏi cây; dedup nội dung sau cleanup
và union trường BibTeX qua version, đổi citation key nhất quán. Hiện chưa có
implementation parser đầy đủ; validator/fixture không thay cho parser.

M3: mỗi người ≥5 publication manual, mỗi publication ≥20 entry được gán nhãn,
tổng ≥100 entry/người; nhóm ba người ≥15 publication/300 entry. Đây không phải
chỉ 20 positive pairs cho toàn pool. Auto ≥10% phần còn lại, và pool đủ cho split;
mục tiêu 500 publication/người đáp ứng an toàn. Mỗi người đóng góp 1 manual +
1 auto vào test và tương tự vào valid; phần được gán nhãn còn lại là train.
MRR@5 dùng tất cả entry test có nhãn; không thấy đáp án trong top-5 thì 0, kể cả
entry không có đối ứng. Không để cùng publication/version rò giữa các split.
Predictions chỉ cho các publication thực sự tham gia matching. Model còn cần xây.

## Song song không có dịch vụ chung

Ba Colab riêng, cùng source, Drive và manifest; mặc định owner riêng. Actor và
owner độc lập, output tách runner/runtime; hỗ trợ dải khác không đổi owner hay đè
file người khác. Lịch UTC nối tiếp request arXiv, không tăng quota bằng số máy.
Điều kiện: một runtime/runner, đồng hồ UTC đúng, cùng lịch, key S2 cá nhân.
[arXiv ToU](https://info.arxiv.org/help/api/tou.html) áp dụng giới hạn cho toàn bộ
máy dưới cùng sự điều khiển; khóa local không được gọi là khóa xuyên Colab.

Chưa có phép thử ba tài khoản thật hoặc benchmark cuối đủ nhóm cho bản mới.
Chưa được kết luận “đồ án hoàn chỉnh/đúng tuyệt đối” chỉ từ việc notebook chạy.
