# Kế hoạch triển khai đồ án IDS – Nhóm 13

## 1. Tóm tắt và các quyết định đã khóa

Mục tiêu là xây dựng một pipeline tái lập hoàn chỉnh:

**arXiv ID → crawl toàn bộ phiên bản → phân tích LaTeX phân cấp → chuẩn hóa/khử trùng lặp → ghép nối trích dẫn bằng ML → xuất 7 bảng Parquet → Jupyter Book + Poster.**

### Phạm vi dữ liệu

| Thành viên | MSSV | Dải arXiv ID |
|---|---:|---|
| Phạm Minh Thông | 23120364 | `2508.17872` → `2509.01046` |
| Nguyễn Tiến Thành | 23120358 | `2509.01047` → `2509.06046` |
| Nguyễn Trịnh Quang | 23120345 | `2509.06047` → `2509.11046` |

- Cả nhóm dùng chung code, pipeline, mô hình và kho dữ liệu làm việc.
- Dữ liệu cuối cùng được tách theo dải ID để mỗi thành viên tự đưa lên Hugging Face.
- M3 dùng Machine Learning truyền thống, không dùng LLM/pretrained model.
- Báo cáo và poster viết bằng tiếng Việt.
- Poster: `13.pptx`, một slide, A2 dọc 42 × 59,4 cm.

### Các mốc bắt buộc và mốc đóng nội bộ

| Hạng mục | Deadline chính thức | Đóng nội bộ |
|---|---:|---:|
| Link Jupyter Book | 06/11/2026 | 18:00, 05/11 |
| GitHub repository | 23:59, 14/11/2026 | 18:00, 13/11 |
| Ba Hugging Face Dataset | 20/11/2026 | 18:00, 19/11 |
| Poster | 27/11/2026 | 18:00, 26/11 |

Repository hiện có: `thong7d/arxiv-ids-project`. Tiếp tục sử dụng repository này làm code repo và chứa source Jupyter Book; GitHub Pages được triển khai từ cùng repository để giảm chi phí quản trị.

---

## 2. Kiến trúc, môi trường và giao diện pipeline

### 2.1. Môi trường

- Python 3.11, virtual environment `.venv`.
- Phát triển trên Windows nhưng mọi đường dẫn phải dùng `pathlib` để chạy được trên Linux/Google Colab.
- Google Colab CPU là môi trường benchmark chính thức.
- GitHub Actions chạy kiểm thử, kiểm tra schema và build Jupyter Book.
- Dữ liệu thật nằm trong ổ cứng làm việc và thư mục Google Drive riêng của nhóm; tuyệt đối không commit dữ liệu, token hay archive.
- Mỗi thành viên tạo:
  - GitHub account và bật 2FA;
  - Hugging Face account cá nhân;
  - Hugging Face write token;
  - yêu cầu Semantic Scholar API key.
- Nếu API key chưa được cấp, pipeline tự chuyển sang giới hạn anonymous: tối đa 1 request/giây và 100 request/5 phút.

### 2.2. Cấu trúc repository dự kiến

```text
arxiv-ids-project/
├── src/ids_arxiv/       # crawl, parse, matching, export, validation
├── configs/             # dải ID và cấu hình chạy, không chứa secret
├── tests/fixtures/      # corpus LaTeX tổng hợp kích thước nhỏ
├── notebooks/           # thí nghiệm, benchmark Colab
├── book/                # source Jupyter Book
├── scripts/             # entrypoints hỗ trợ
├── README.md
├── requirements.txt
└── .env.example
```

Dữ liệu bị `.gitignore`:

```text
data/raw/
data/processed/
artifacts/
exports/
```

### 2.3. CLI công khai

Pipeline phải có các lệnh độc lập, chạy lại được và hỗ trợ `--resume`:

```powershell
python -m ids_arxiv discover --config configs/members.csv
python -m ids_arxiv crawl --manifest data/manifests/papers.parquet --resume
python -m ids_arxiv parse --input data/raw --output data/processed --resume
python -m ids_arxiv label --input data/processed
python -m ids_arxiv train --config configs/model.yaml
python -m ids_arxiv export --student-id 23120364
python -m ids_arxiv validate --stage raw
python -m ids_arxiv validate --stage processed
python -m ids_arxiv validate --stage hf --student-id 23120364
python -m ids_arxiv benchmark --stage crawl
python -m ids_arxiv benchmark --stage parse
```

Mỗi lần chạy tạo `run_id`, log, thời gian, phiên bản package, seed, input checksum, số record thành công/thất bại và nguyên nhân thất bại.

### 2.4. Quy ước dữ liệu

- ID persisted dùng dạng `2509-01047`; khi gọi API chuyển sang `2509.01047`.
- ID arXiv cũ như `hep-th/9901001` được giữ nguyên về ngữ nghĩa và chỉ làm sạch ký tự khi tạo tên thư mục.
- Version lưu dưới dạng số nguyên.
- Mọi file được ghi atomically: ghi file tạm rồi rename sau khi kiểm tra hoàn tất.

Luồng dữ liệu:

```text
members.csv
  → paper manifest
  → raw/{paper}/v1...vN + metadata.json + references.json
  → processed/{paper}/hierarchy.json + refs.bib
  → labels/features/models/predictions
  → exports/{student_id}/7 bảng Parquet
```

Các bảng Hugging Face giữ đúng schema đề bài:

| Bảng | Khóa/quan hệ chính |
|---|---|
| `papers` | `arxiv_id` |
| `elements` | `element_id`, liên kết đến `papers` |
| `element_parents` | `arxiv_id + version + element_id + parent_id` |
| `bibtex_entries` | `arxiv_id + citation_key` |
| `paper_references` | `arxiv_id + ref_arxiv_id` |
| `predictions` | `arxiv_id + citation_key`, chỉ chứa publications tham gia M3 |
| `sources` | `arxiv_id + version + filename` |

Các artifact nội bộ như crawl status, labels, features, benchmark và error logs không đưa vào bảy bảng chính.

---

## 3. Kế hoạch theo từng Phase

### Phase 0 — Thiết lập quản trị và môi trường

**Thời gian:** 25/10/2026  
**Mô tả:** Chuẩn hóa cách cộng tác trước khi viết pipeline để tránh mất dữ liệu, lộ secret hoặc lịch sử commit không phản ánh đóng góp.

**Đầu vào**

- Repository hiện có.
- Ba thành viên và ba dải ID.
- Các deadline đã xác định.

**Việc cần làm**

- Xác nhận repository ở chế độ public; thêm Thành và Quang làm collaborator.
- Áp dụng nhánh `feature/*`, pull request và một người review trước khi merge `main`.
- Bật GitHub Pages với URL cố định ngay từ đầu.
- Tạo project board: Backlog, In progress, Review, Done.
- Tạo shared Google Drive cho corpus, checkpoint và bản backup; token vẫn lưu riêng trong `.env`.
- Thiết lập Python 3.11 và kiểm tra cài đặt sạch từ `requirements.txt`.
- Bổ sung dependency:
  - crawl/data: `arxiv`, `requests`, `sickle`, `pandas`, `pyarrow`, `pydantic`, `typer`, `pyyaml`, `tqdm`, `psutil`;
  - parsing: `pylatexenc`, `bibtexparser`, `pysbd`, `rapidfuzz`, `latexcodec`;
  - ML: `scikit-learn`, `scipy`, `joblib`;
  - report/test: `jupyter-book`, `matplotlib`, `seaborn`, `plotly`, `pytest`, `pytest-cov`, `ruff`.
- Pin phiên bản sau khi clean-install thành công.

**Đầu ra và kết quả mong đợi**

- Ba thành viên clone, tạo branch, chạy được test smoke.
- GitHub Pages có URL cố định dù nội dung mới là trang khung.
- Không có token hoặc dữ liệu trong Git.
- README có hướng dẫn cài đặt Windows và Colab.

**Phụ trách**

- Thông: repository, CI, Pages, môi trường chung.
- Thành: kiểm tra cài đặt mới và cấu trúc test.
- Quang: project board, convention log/metrics và khung Jupyter Book.

---

### Phase 1 — Đặc tả dữ liệu, fixture và kiểm thử nền

**Thời gian:** 26/10/2026  
**Mô tả:** Khóa schema và hành vi pipeline trước khi chạy trên 15.000 bài.

**Việc cần làm**

- Tạo `members.csv` với student ID, tháng bắt đầu/kết thúc và ID biên.
- Dùng OAI-PMH để khám phá ID thực tế trong tháng 08–09/2025, sau đó lọc đúng ba khoảng; không lọc category.
- Kiểm tra:
  - không chồng lấn giữa ba thành viên;
  - không bỏ sót ID hợp lệ trong khoảng;
  - mỗi ID chỉ có một owner;
  - ghi rõ ID không tồn tại/withdrawn thay vì im lặng bỏ qua.
- Định nghĩa Pydantic/JSON schema cho metadata, references, hierarchy, label và bảy bảng Parquet.
- Tạo fixture tổng hợp gồm:
  - bài một và nhiều version;
  - LaTeX nhiều file;
  - `\input`, `\include`, include cycle;
  - figure, table, equation, itemize;
  - acknowledgements, appendix, references;
  - `.bib`, `.bbl`, `\bibitem`;
  - câu lặp giữa các version.
- Xây end-to-end smoke test: fixture → parse → matching nhỏ → bảy bảng.

**Đầu ra**

- Manifest ID có owner rõ ràng.
- Schema không còn phụ thuộc vào suy đoán ở các phase sau.
- Bộ test nhỏ chạy dưới một phút.

**Cổng nghiệm thu**

- Không có ID overlap.
- Fixture end-to-end chạy thành công.
- Mọi schema có validator tự động.

**Phụ trách**

- Thành là owner schema và fixture.
- Thông review manifest/range.
- Quang review schema M3 và Parquet.

---

### Phase 2 — Milestone 1: Crawling và xây raw corpus

**Thời gian:** 27/10–01/11/2026  
**Mô tả:** Chạy một crawler tập trung cho toàn bộ nhóm, có checkpoint, rate limiter và provenance; sau đó mới tách thống kê theo thành viên.

**Đầu vào**

- Manifest đã được Phase 1 xác nhận.
- API key nếu có.
- Dung lượng local/Drive đã kiểm tra.

**Việc cần làm**

1. **Pilot**
   - Chọn 30 bài, 10 bài mỗi thành viên, bao gồm multi-version, source lạ và PDF-only nếu tìm thấy.
   - Chỉ chạy full corpus sau khi pilot qua validator.

2. **Metadata và version**
   - Truy vấn arXiv API theo batch bằng `client.results`.
   - Lấy version mới nhất từ suffix của Atom ID và tải tuần tự `v1…vN`.
   - Lưu title, authors, submission date, revised dates, venue.
   - References là cấp publication vì Semantic Scholar không phân biệt version.

3. **Source download**
   - Chỉ dùng `https://export.arxiv.org/src/{id}vN`.
   - Một connection, khoảng cách tối thiểu 3 giây, User-Agent có email liên hệ.
   - Retry có exponential backoff, jitter và tôn trọng `Retry-After`.
   - Download vào `.part`, checksum, rồi mới giải nén.
   - Chống tar path traversal, symlink ra ngoài thư mục và archive bomb.
   - Nhận diện tar.gz, tar, gzip đơn, plain TeX và PDF-only.
   - Đo dung lượng trước khi lọc; xóa ảnh/binary nhưng giữ nguyên LaTeX figure/table.
   - Xóa archive sau khi đã trích text thành công để hạn chế peak disk.

4. **Semantic Scholar**
   - Một centralized rate limiter; không dùng nhiều API key để lách rate limit.
   - Thu thập paper ID, external arXiv ID, title, authors, year/date và venue.
   - Chỉ đưa reference có arXiv ID vào `references.json`.
   - Batch-enrich submission date của reference bằng arXiv API và cache theo arXiv ID.
   - Với 404, 429, 5xx hoặc chưa được index: ghi trạng thái và nguyên nhân.

5. **Quan sát và khôi phục**
   - Resume theo publication/version.
   - Log JSON Lines, crawl status và retry queue riêng.
   - Backup corpus text đã lọc theo shard lên Drive hằng ngày.

**Đầu ra**

```text
raw/<paper-id>/
├── v1/
├── v2/
├── metadata.json
├── references.json
└── crawl_status.json
```

Các trường hợp không có TeX vẫn có metadata, status và thư mục version rỗng; không được loại bỏ publication.

**Kết quả mong đợi**

- Tất cả ID được biểu diễn bằng success record hoặc failure record có lý do.
- Tất cả version phát hiện được đã tải.
- Không còn `.png`, `.jpg`, `.pdf`, `.eps`, `.svg` hoặc binary trong corpus cuối.
- Có đủ số liệu success rate, kích thước trước/sau, reference coverage và runtime.

**Cổng nghiệm thu**

- Pilot 30/30 qua schema.
- Validator chạy trên 100% corpus.
- Mỗi thành viên kiểm tra thủ công ít nhất 10 bài thuộc dải của mình.

**Phụ trách**

- Thông: crawler, rate limiter, checkpoint và runner chính.
- Thành: safe extraction, figure filter và raw validator.
- Quang: Semantic Scholar client, metrics M1 và phân tích lỗi.
- Mỗi người chịu trách nhiệm cuối cùng về QA dải ID cá nhân.

---

### Phase 3 — Milestone 2: Parsing, chuẩn hóa và deduplication

**Thời gian phát triển:** 29/10–01/11 trên fixture/pilot  
**Chạy production:** 02/11–05/11 trên các shard M1 đã đạt chuẩn  
**Mô tả:** Code có thể phát triển song song trên pilot, nhưng dữ liệu production M2 chỉ nhận shard đã qua cổng M1.

**Việc cần làm**

1. **Tìm compilation path**
   - Chấm điểm main file dựa trên `\documentclass`, `\begin{document}` và dependency graph.
   - Resolve đệ quy `\input`, `\include`, `\subfile`, có cycle detection.
   - Bỏ orphan files.
   - Nếu nhiều main candidate ngang điểm, dùng override config và ghi audit log.
   - Hỗ trợ UTF-8, UTF-8 BOM và fallback encoding có cảnh báo.

2. **Xây hierarchy**
   - Dùng parser/tokenizer LaTeX, không dùng một regex duy nhất cho toàn tài liệu.
   - Các kind: document, chapter, section, subsection, subsubsection, paragraph, list, item, sentence, formula và figure.
   - Table được xuất với kind `figure` theo yêu cầu.
   - Loại references khỏi hierarchy.
   - Giữ acknowledgements và appendices.
   - Giữ lệnh `\cite{}` trong nội dung để tạo hierarchy features ở M3.

3. **Tách leaf**
   - Bảo vệ math/citation bằng placeholder trước khi tách câu.
   - Không tách sai tại `e.g.`, `i.e.`, `et al.`, `Fig.`, `Eq.`.
   - Block formula và figure/table là leaf độc lập.

4. **Chuẩn hóa**
   - Loại lệnh bố cục nhưng giữ text có ý nghĩa.
   - Inline math → `$...$`.
   - Block math → `\begin{equation}...\end{equation}`.
   - Chuẩn hóa khoảng trắng theo quy tắc xác định, không làm thay đổi nội dung toán.

5. **Reference extraction**
   - Đọc `.bib` trước, sau đó `.bbl` và `\bibitem`.
   - Tách `\bibitem` theo boundary, rồi dùng heuristic lấy author/title/year/venue/DOI.
   - Không bịa trường không trích xuất được; lưu nullable và error note nội bộ.

6. **Reference deduplication**
   - Thứ tự khóa: DOI exact → arXiv ID exact → normalized title + author + year.
   - Chỉ fuzzy merge khi vượt threshold và không có candidate cạnh tranh gần bằng.
   - Chọn một canonical key có tiền tố paper ID.
   - Hợp nhất trường, log conflict và rewrite toàn bộ `\cite{}`.

7. **Full-text deduplication**
   - Thực hiện sau cleanup.
   - Element ID dùng paper ID, kind và SHA-256 của normalized content.
   - Với nội dung giống nhau xuất hiện nhiều lần trong cùng version, thêm occurrence index; cùng occurrence qua các version dùng lại ID.
   - Cách này vừa dedup xuyên version vừa không làm mất các câu lặp ở hai vị trí khác nhau.

**Đầu ra**

- Một `hierarchy.json` và `refs.bib` cho mỗi publication.
- Parse status, unresolved citation report, duplicate merge report và metrics.
- Raw source vẫn được giữ để tạo bảng `sources`.

**Kết quả mong đợi**

- Cây không chu trình, có đúng một root/version.
- Mọi node trừ root có parent hợp lệ.
- Không có references section trong hierarchy.
- Citation key sau rewrite tồn tại trong `refs.bib` hoặc nằm trong unresolved report.
- Mục tiêu parser: thành công ≥98% các version có TeX hợp lệ; mọi failure còn lại được phân loại.

**Phụ trách**

- Thành: owner parser, normalization và deduplication.
- Quang: hierarchy validator và review edge cases.
- Thông: integration với raw corpus, performance và resume.
- Mỗi người audit 10 hierarchy thuộc dải cá nhân.

---

### Phase 4 — Jupyter Book và hoàn thiện M1/M2

**Thời gian:** 02/11–06/11; tiếp tục cập nhật đến 26/11  
**Mô tả:** Nộp URL cố định trước, sau đó cập nhật nội dung trên cùng URL đến hạn Poster.

**Chương 1 – Crawling**

- Kiến trúc crawler, rate limiting, retry và checkpoint.
- Số bài được cấp, success/failure theo nguyên nhân.
- Phân bố version.
- Kích thước trước/sau lọc ảnh và tỷ lệ tiết kiệm.
- Citation/reference coverage.
- Runtime, RAM và disk usage.

**Chương 2 – Parsing**

- Main-file detection và include graph.
- Hierarchy model và leaf rules.
- Math normalization, BibTeX extraction.
- Hai cấp deduplication.
- Parse success, tree depth, element counts.
- Số element/reference trước và sau dedup.
- Runtime, RAM và output size.

**Quy tắc báo cáo**

- Tất cả bảng và biểu đồ được sinh bằng code khi build.
- Không dùng ảnh chụp màn hình của bảng/biểu đồ.
- Mỗi số liệu ghi `run_id`, thời điểm, sample/full corpus và môi trường.
- Nếu build ngày 05/11 chưa có full corpus, số liệu phải ghi rõ “provisional”; thay bằng full metrics trước 26/11.
- Sau khi Hugging Face public, book loader đọc trực tiếp ba dataset hoặc artifact tổng hợp để tái lập biểu đồ.

**Benchmark**

- Google Colab CPU cố định.
- M1: benchmark một sample phân tầng cố định, báo riêng measured sample wall time và production full-corpus wall time; không giả lập số full corpus thành số đo Colab.
- M2: benchmark sample cố định đủ loại source/version, tối thiểu ba lần.
- Ghi Python/package versions, CPU, peak RAM, peak disk và random seed.

**Cổng nghiệm thu**

- Build sạch từ đầu.
- Không có broken links hoặc notebook error.
- URL Pages không đổi.
- Internal freeze 05/11; nộp link 06/11.

**Phụ trách**

- Thông: build/deploy và performance section.
- Thành: chương Parsing.
- Quang: chương Crawling, biểu đồ và kiểm tra tính nhất quán số liệu.
- Cả nhóm proofread tiếng Việt.

---

### Phase 5 — Ground truth và feature dataset cho M3

**Thời gian:** 06/11–11/11/2026  
**Mô tả:** Chỉ sử dụng publication đã qua M2; khóa split trước khi fit TF-IDF hoặc mô hình.

**Gán nhãn thủ công**

Mỗi thành viên:

- Chọn sáu publication dự phòng, chính thức giữ ít nhất năm publication.
- Đảm bảo năm publication chính thức có tổng cộng ít nhất 20 positive associations.
- Gán một ground-truth arXiv ID hoặc `null` cho từng BibTeX entry.
- Sinh nhãn nhị phân cho toàn bộ không gian `m × n`; candidate đúng là 1, các candidate còn lại là 0.
- Người khác review toàn bộ positive labels và ít nhất 10% negative labels.
- Lưu annotator, reviewer, evidence URL, confidence và note.
- Tính agreement trên phần được double-label; disagreement phải được phân xử trước data freeze.

**Gán nhãn tự động**

- Tối thiểu 10% số publication còn lại của mỗi thành viên; với dải khoảng 5.000 bài, mục tiêu tối thiểu 500 publication/người.
- Publication phải có `m > 0` BibTeX entries và `n > 0` Semantic Scholar references.
- Luật high-precision:
  - DOI/arXiv ID exact; hoặc
  - normalized title exact; hoặc
  - title similarity rất cao kết hợp first-author match và year difference ≤1.
- Chỉ nhận match duy nhất có margin đủ lớn; trường hợp mơ hồ để unlabeled.
- Audit thủ công tối thiểu 100 automatic positives toàn nhóm; nếu precision dưới 98%, tăng threshold và chạy lại.
- Báo rõ denominator, số đủ điều kiện và lý do loại.

**Chia tập**

Áp dụng riêng cho từng thành viên:

- Test: đúng 1 manual publication + 1 automatic publication.
- Validation: đúng 1 manual publication + 1 automatic publication.
- Train: tất cả publication M3 còn lại.

Mô hình nhóm:

- Train trên hợp của ba training partitions.
- Chọn mô hình trên hợp validation nhưng báo thêm MRR từng thành viên.
- Test một lần sau khi đã khóa model.
- Mỗi personal HF dataset vẫn có đủ train/valid/test theo đúng yêu cầu cá nhân.

**Feature engineering**

- Title: normalized Levenshtein, Jaro-Winkler, token Jaccard, word/character TF-IDF cosine, length ratio.
- Authors: first-author surname match, author Jaccard, overlap ratio, author-count difference.
- Time: year exact, absolute year difference, missing-year flag.
- Identifier: DOI/arXiv exact khi có.
- Hierarchy: citation frequency, first occurrence depth, section category, normalized document position.
- Missing-value flags cho mọi nhóm dữ liệu không đầy đủ.
- TF-IDF chỉ fit trên training publications để tránh leakage.

**Đầu ra**

- Versioned manual labels, automatic labels, split manifest và feature Parquet.
- Data dictionary và lý giải từng feature.
- Biểu đồ phân phối positive/negative phục vụ poster.

**Phụ trách**

- Quang: owner label schema, feature pipeline và split.
- Thành: hierarchy features và review labels của Quang.
- Thông: leakage audit và review labels của Thành.
- Quang review labels của Thông.
- Mỗi người tự chịu trách nhiệm tối thiểu 5 publication/20 positive pairs của mình.

---

### Phase 6 — Huấn luyện, đánh giá và phân tích lỗi

**Thời gian:** 12/11–16/11/2026  
**Mô tả:** So sánh baseline với mô hình truyền thống, khóa model bằng validation MRR rồi mới mở test.

**Mô hình**

1. Exact/heuristic matcher làm baseline.
2. Weighted similarity baseline.
3. Logistic Regression hoặc SGD logistic với class weighting.
4. Random Forest hoặc HistGradientBoosting trên cùng feature set.

Toàn bộ `m × n` pair được giữ. Nếu bộ nhớ không đủ, xử lý theo batch/publication; không loại candidate khỏi evaluation.

**Quy trình**

- Seed cố định `42`.
- Preprocessing fit trên train.
- Hyperparameter selection chỉ dùng validation.
- Với mỗi citation key, score toàn bộ `n` candidates, sắp xếp giảm dần và chọn top 5.
- Tie-break theo normalized `ref_arxiv_id` để kết quả xác định.
- Nếu `n < 5`, các cột còn lại là null.
- MRR chỉ tính trên citation có ground truth; đồng thời báo coverage.
- Báo:
  - pooled MRR;
  - MRR của manual test;
  - MRR của auto test;
  - MRR theo từng thành viên;
  - Recall@1 và Recall@5 làm chỉ số phụ.
- Thực hiện ablation:
  - title only;
  - title + author/year;
  - toàn bộ feature;
  - bỏ hierarchy features.
- Bootstrap confidence interval theo query.
- Phân tích tối thiểu 20 lỗi hoặc toàn bộ lỗi nếu ít hơn.

**Lựa chọn mô hình cuối**

- Mô hình có validation MRR cao nhất được khóa.
- Nếu learned model không hơn heuristic, vẫn báo trung thực; predictions dùng phương pháp tốt nhất trên validation và poster phân tích nguyên nhân.
- Không chỉnh threshold/model sau khi xem test.

**Đầu ra**

- Model artifact, preprocessing artifact, model card nội bộ.
- Top-5 predictions.
- Metrics, ablation table và error-analysis table.

**Phụ trách**

- Quang: model training và evaluation.
- Thành: ablation/hierarchy feature analysis.
- Thông: reproducibility run, leakage audit và review metric implementation.

**Checkpoint GitHub**

Đến 13/11 phải có code hoàn chỉnh cho M1, M2, label/feature pipeline, baseline M3, tests và README. Đại diện nhóm nộp repository trước 23:59 ngày 14/11; các commit sau đó vẫn tiếp tục trên cùng URL.

---

### Phase 7 — Xuất và nộp ba Hugging Face Dataset

**Thời gian:** 17/11–20/11/2026  
**Mô tả:** Cùng một exporter nhưng chạy ba lần theo owner range.

**Việc cần làm**

- Flatten JSON/BibTeX thành đúng bảy bảng.
- Dùng Arrow types rõ ràng:
  - dictionary encoding cho `kind`, `entry_type`, `partition`;
  - list of strings cho authors/revised dates;
  - year nullable integer;
  - các field thiếu dùng null, không dùng chuỗi `"None"`.
- Kiểm tra primary key, foreign key, uniqueness và nullable constraints.
- `predictions` chỉ gồm publications tham gia M3.
- `sources` chỉ chứa text LaTeX/BibTeX, không chứa binary.
- Ghi Parquet với ZSTD, shard mục tiêu khoảng 200 MB để viewer/streaming hoạt động tốt.
- Dataset card tiếng Việt gồm:
  - nguồn dữ liệu và mục đích;
  - ba milestone;
  - schema;
  - cách tạo labels;
  - split;
  - benchmark/model metrics;
  - limitations, coverage, failures;
  - provenance và lưu ý giấy phép arXiv;
  - thông tin sinh viên sở hữu dải ID.
- Token chỉ đọc từ biến môi trường.
- Upload ba repo cá nhân, ví dụ `ids-arxiv-23120364`.
- Kiểm tra bằng Hugging Face viewer và streaming load.

**Đầu ra**

- Dataset của Thông chỉ chứa dải của Thông.
- Dataset của Thành chỉ chứa dải của Thành.
- Dataset của Quang chỉ chứa dải của Quang.
- Cả ba có cùng schema, pipeline version và cách đặt ID.

**Cổng nghiệm thu**

- Bảy config đều load được.
- Không có row ngoài dải cá nhân.
- Không có token, archive hoặc binary.
- Random sample đối chiếu ngược được về raw/processed source.
- Internal freeze 19/11; từng thành viên tự nộp link ngày 20/11.

**Phụ trách**

- Quang: exporter và dataset-card template.
- Thành: schema/foreign-key validator.
- Thông: upload automation và final reproducibility check.
- Mỗi người tự đăng nhập, upload và nộp link cá nhân.

---

### Phase 8 — Hoàn thiện học thuật, Jupyter Book và Poster

**Thời gian:** 20/11–27/11/2026  
**Mô tả:** Chuyển kết quả kỹ thuật thành bằng chứng học thuật và câu chuyện thực tế rõ ràng.

**Jupyter Book cuối**

- Thay provisional metrics bằng full-corpus metrics.
- Kiểm tra mọi biểu đồ được sinh lại từ dữ liệu đã phát hành.
- Thêm methodology, limitations, failure taxonomy và reproducibility.
- Gắn link GitHub, ba HF datasets và commit/tag cuối.

**Poster `13.pptx`**

Một slide A2 dọc, bố cục ba cột:

1. Bài toán, dữ liệu và pipeline tổng thể.
2. Parsing/deduplication và feature engineering nổi bật.
3. Model comparison, MRR, ablation, error analysis và kết luận.

Bắt buộc có:

- tên nhóm và ba thành viên/MSSV;
- số publication, version, source success và parse success;
- tỷ lệ giảm dung lượng và dedup;
- bảng model/MRR;
- một biểu đồ feature hoặc ablation;
- 2–3 failure cases tiêu biểu;
- limitations;
- QR/link GitHub, Jupyter Book và Hugging Face.

**Kiểm tra cuối**

- Slide đúng 42 × 59,4 cm, portrait, đúng một trang.
- Font đọc được khi in A2, không dùng đoạn văn dài.
- Xuất PDF thử để kiểm tra font và clipping nhưng file nộp vẫn là `13.pptx`.
- Mỗi thành viên chuẩn bị phần nói 2–3 phút:
  - Thông: crawling, kiến trúc, benchmark;
  - Thành: parsing, normalization, deduplication;
  - Quang: labeling, features, model, MRR.
- Tổ chức ít nhất hai buổi rehearsal và chuẩn bị câu trả lời về leakage, rate limits, parser failures, pseudo-label bias và dataset limitations.
- Internal freeze 26/11; đại diện nộp ngày 27/11.

---

## 4. Phân công tổng hợp

| Hạng mục | Owner | Reviewer | Trách nhiệm chung |
|---|---|---|---|
| Repository, CI, CLI, M1 crawler | Thông | Thành | Cả nhóm kiểm tra range cá nhân |
| Parser, normalization, dedup M2 | Thành | Quang | Cả nhóm audit hierarchy |
| Labels, features, model M3 | Quang | Thông | Mỗi người label tối thiểu 5 publications |
| Schema và data validation | Thành | Thông | Cả nhóm xử lý failure thuộc range mình |
| Jupyter Book deployment | Thông | Quang | Thành viết phần M2 |
| HF exporter | Quang | Thành | Mỗi người upload dataset cá nhân |
| Poster | Quang | Cả nhóm | Mỗi người sở hữu một phần thuyết trình |
| Project management/deadline | Thông | Thành | Cập nhật board hằng ngày |

Quy tắc “owner không làm một mình”: owner chịu trách nhiệm thiết kế và tích hợp; reviewer phải chạy lại, đọc log và chấp thuận acceptance gate.

---

## 5. Test plan và Definition of Done

### Kiểm thử tự động

- API mock: 200, 404, 429 với `Retry-After`, 5xx, timeout và response lỗi.
- Archive: tar.gz, gzip đơn, plain TeX, PDF-only, corrupt archive, path traversal và symlink.
- Version: một version, nhiều version, version thiếu.
- LaTeX:
  - nhiều main candidate;
  - nested include và include cycle;
  - comments/escaped percent;
  - acknowledgements/appendix;
  - references exclusion;
  - abbreviations và inline/block math;
  - figure/table;
  - repeated identical sentence.
- BibTeX:
  - duplicate khác citation key;
  - field union;
  - DOI conflict;
  - cite rewrite;
  - unresolved cite.
- ML:
  - missing title/author/year;
  - `n < 5`;
  - score tie;
  - no ground truth;
  - split leakage;
  - MRR known-answer fixture.
- Parquet:
  - exact Arrow schema;
  - null handling;
  - primary/foreign keys;
  - personal range filter;
  - Hugging Face streaming smoke test.

### Acceptance toàn dự án

Dự án chỉ hoàn thành khi:

- 100% assigned IDs có success hoặc documented failure record.
- Không có data/binary/secret trong Git.
- M1 và M2 có end-to-end resume.
- Parser output qua graph/schema validation.
- Mỗi thành viên đạt ≥5 manual publications và ≥20 positive associations.
- Automatic labels đạt ≥10% phần còn lại theo từng thành viên.
- Split được thực hiện theo publication và không có leakage.
- Model tạo top 5 xác định và MRR tái lập được.
- Ba HF datasets có đủ bảy bảng và load được.
- Jupyter Book build sạch trên URL đã nộp.
- Poster đúng một slide A2 dọc và có bằng chứng định lượng.
- README cho phép một người mới thiết lập môi trường và chạy lại từng stage.

### Rủi ro và biện pháp

- **Rate limit/network:** centralized scheduler, cache, retry queue, checkpoint và buffer nhiều ngày.
- **Colab mất session:** benchmark theo sample cố định; production có checkpoint trên Drive.
- **Source không chuẩn:** giữ failure taxonomy, manual override cho main file, không âm thầm bỏ bài.
- **Pseudo-label bias:** high-precision rules, manual audit và báo riêng manual/auto MRR.
- **Class imbalance:** class weighting và đánh giá theo ranking, không chỉ accuracy.
- **Trễ deadline:** đóng nội bộ sớm một ngày; URL Book/repo được tạo ngay Phase 0.
- **Giấy phép dữ liệu:** giữ provenance/license metadata nội bộ và mô tả rõ trong dataset card, không tuyên bố một giấy phép chung nếu corpus có nhiều loại.
