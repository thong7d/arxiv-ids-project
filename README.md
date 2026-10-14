# Đồ án Nhập môn Khoa học Dữ liệu (FIT - HCMUS)
**Chủ đề:** arXiv Project — Thu thập mã nguồn LaTeX, Phân tích cú pháp phân cấp và Pipeline Machine Learning Ghép nối trích dẫn

---

## 📌 Bộ Tài Liệu Định Hướng và Context Chi Tiết (Project Documentation)

Toàn bộ yêu cầu của giảng viên, phân tích kỹ thuật, cấu trúc schema và quy định nộp bài đã được tổng hợp chi tiết trong thư mục [`docs/`](file:///d:/000MINHTHONG/Final-year%20Semeter%20I/IDS/Prj/docs/):

1. **[PROJECT_OVERVIEW.md](file:///d:/000MINHTHONG/Final-year%20Semeter%20I/IDS/Prj/docs/PROJECT_OVERVIEW.md)**: Tổng quan kiến trúc đồ án, phân biệt trách nhiệm nhóm vs cá nhân, các cổng nộp bài Moodle và quy định chung.
2. **[MILESTONE_1_CRAWLING.md](file:///d:/000MINHTHONG/Final-year%20Semeter%20I/IDS/Prj/docs/MILESTONE_1_CRAWLING.md)**: Hướng dẫn cào dữ liệu arXiv (toàn bộ version, mirror `export.arxiv.org`, rate limit 3s, lọc bỏ ảnh binary), truy vấn Semantic Scholar API, cấu trúc `metadata.json` & `references.json`, và benchmark Colab CPU cho Jupyter Book Section 1.
3. **[MILESTONE_2_PARSING.md](file:///d:/000MINHTHONG/Final-year%20Semeter%20I/IDS/Prj/docs/MILESTONE_2_PARSING.md)**: Hướng dẫn phân tích cây phân cấp tài liệu từ mã LaTeX đa file, lọc nhiễu, chuẩn hóa toán học, bóc tách `\bibitem` thành BibTeX, khử trùng lặp 2 cấp độ (trích dẫn & toàn văn), và tạo `hierarchy.json` & `refs.bib`.
4. **[MILESTONE_3_MATCHING_AND_SUBMISSION.md](file:///d:/000MINHTHONG/Final-year%20Semeter%20I/IDS/Prj/docs/MILESTONE_3_MATCHING_AND_SUBMISSION.md)**: Hướng dẫn xây dựng Pipeline Machine Learning ghép nối trích dẫn (Entity Resolution, đánh giá bằng MRR), đặc tả 7 bảng Parquet nộp Hugging Face cá nhân, và quy cách thiết kế Poster A2 dọc (`<ID nhóm>.pptx`).
5. **[CHECKLIST_AND_DELIVERABLES.md](file:///d:/000MINHTHONG/Final-year%20Semeter%20I/IDS/Prj/docs/CHECKLIST_AND_DELIVERABLES.md)**: Actionable checklist từng bước kiểm tra từ M1 đến M3, cấu trúc mã nguồn chuẩn trong repository.

---

## 🚀 Các Hạn Mục Nộp Bài Chính (Moodle Links)

- **Jupyter Book (Milestones 1 & 2):** [Assign 129042](https://courses.fit.hcmus.edu.vn/mod/assign/view.php?id=129042) — Đại diện nhóm nộp link GitHub Pages (`github.io`).
- **Hugging Face Dataset:** [Assign 129043](https://courses.fit.hcmus.edu.vn/mod/assign/view.php?id=129043) — **Mỗi cá nhân tự nộp** link dataset cá nhân (7 bảng Parquet).
- **Poster báo cáo:** [Assign 129044](https://courses.fit.hcmus.edu.vn/mod/assign/view.php?id=129044) — Đại diện nhóm nộp file `<ID nhóm>.pptx` khổ A2 dọc.
