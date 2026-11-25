# Kế hoạch triển khai đồ án IDS – Nhóm 13

> Đối chiếu đề trực tuyến ngày 13/11/2026: xem [SPEC_AUDIT](docs/SPEC_AUDIT_2026-11-13.md) và [hướng dẫn notebook độc lập](docs/HUONG_DAN_CAO_SONG_SONG.md). Những mốc tiến độ cũ phía dưới là lịch kế hoạch, không phải xác nhận đã làm xong. M1 protocol 4 bổ sung all-reference snapshots và metadata từng version; M2/M3 vẫn cần triển khai/kiểm chứng thực tế.

> Cập nhật 01/11/2026 theo giải đáp mới của giảng viên: benchmark cuối chạy **toàn bộ dữ liệu của nhóm trên Google Colab CPU**, gồm delay/retry. Được chia nhiều phiên với checkpoint và log từng phiên. Sample chỉ dùng pilot. Được crawl nhiều lượt; báo kết quả lượt đầu và sau phục hồi. Số bài thực tế lấy từ manifest discovery đã xác minh, không mặc định 15.000.
>
> Lịch điều chỉnh: 01–02/11 sửa crawler/benchmark và kết nối Colab; 02–10/11 full crawl qua nhiều phiên; 02–11/11 M2 theo shard đã validate; 08–12/11 labels; 13–16/11 model; các deadline nộp bên dưới giữ nguyên. Nộp URL Book ngày 06/11 với số liệu tạm được ghi nhãn rõ ràng, cập nhật kết quả đầy đủ trước hạn Poster.

## 1. Tóm tắt và các quyết định đã khóa

Mục tiêu là xây dựng một pipeline tái lập hoàn chỉnh:

**arXiv ID → crawl toàn bộ phiên bản → phân tích LaTeX phân cấp → chuẩn hóa/khử trùng lặp → ghép nối trích dẫn bằng ML → xuất 6 bảng Parquet → Jupyter Book + Poster.**

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
  → raw/{paper}/v1...vN + metadata.json + references_all.json + references.json
  → processed/{paper}/hierarchy.json + refs.bib
  → labels/features/models/predictions
  → exports/{student_id}/6 bảng Parquet
```

Các bảng Hugging Face giữ đúng schema đề bài:

| Bảng | Khóa/quan hệ chính |
|---|---|
| `papers` | `arxiv_id` |
| `elements` | `element_id`, liên kết đến `papers` |
| `hierarchy` | `arxiv_id + version + element_id + parent_id` |
| `bibtex` | `arxiv_id + citation_key` |
| `references` | `arxiv_id + ref_arxiv_id` |
| `predictions` | `arxiv_id + citation_key`, chỉ chứa publications tham gia M3 |

Các artifact nội bộ như raw source, crawl status, labels, features, benchmark và error logs không đưa vào sáu bảng chính.

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
**Mô tả:** Khóa schema và hành vi pipeline trước khi chạy trên toàn bộ dải ID được giao; số lượng chỉ chốt sau discovery thực tế.

**Việc cần làm**

- Tạo `members.csv` với student ID, tháng bắt đầu/kết thúc và ID biên.
- Dùng OAI-PMH để khám phá ID thực tế trong tháng 08–09/2025, sau đó lọc đúng ba khoảng; không lọc category.
- Kiểm tra:
  - không chồng lấn giữa ba thành viên;
  - không bỏ sót ID hợp lệ trong khoảng;
  - mỗi ID chỉ có một owner;
  - ghi rõ ID không tồn tại/withdrawn thay vì im lặng bỏ qua.
- Định nghĩa Pydantic/JSON schema cho metadata, references, hierarchy, label và sáu bảng Parquet.
- Tạo fixture tổng hợp gồm:
  - bài một và nhiều version;
  - LaTeX nhiều file;
  - `\input`, `\include`, include cycle;
  - figure, table, equation, itemize;
  - acknowledgements, appendix, references;
  - `.bib`, `\bibitem` trong `.tex`; file `.bbl` chỉ làm negative fixture cho bộ lọc source;
  - câu lặp giữa các version.
- Xây end-to-end smoke test: fixture → parse → matching nhỏ → sáu bảng. Fixture/validator không đồng nghĩa parser/model đã hoàn thành.

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
   - Đo tổng bytes archive trước lọc; chỉ extract `.tex`/`.bib`, không sửa một byte LaTeX figure/table.
   - Xóa archive sau khi đã trích text thành công để hạn chế peak disk.

4. **Semantic Scholar**
   - Limiter đúng phạm vi key/người; key cá nhân không chia sẻ và không xoay key/IP để né quota.
   - Thu thập paper ID, external arXiv ID, title, authors, year/date và venue.
   - Chỉ đưa reference có arXiv ID vào `references.json`.
   - Giữ toàn bộ snapshot S2 trong `references_all.json`, kể cả reference không có arXiv ID; không giả snapshot publication thành lịch sử S2 theo revision.
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
├── references_all.json
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
   - Đọc `.bib` và các `\bibitem` trong `.tex`; không phụ thuộc vào `.bbl` vốn không được giữ trong corpus M1 theo đề hiện tại.
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
- Raw `.tex`/`.bib` nguyên bản được giữ nội bộ cho M2 và audit; không có bảng `sources` trong dataset nộp.

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
- M1: benchmark toàn bộ dải ID ba thành viên trên Colab CPU. Sample chỉ dùng thử nghiệm. Runtime gồm discovery, download, xử lý, delay, backoff, retry và checkpoint trong lượt đo. Không dùng cache pilot để thay cold-start full benchmark.
- M2: benchmark toàn bộ corpus nguồn hợp lệ trên Colab CPU; ghi riêng số publication/version không có TeX. Sample chỉ dùng debug.
- Cho phép nhiều phiên Colab: lưu session ID, commit, manifest checksum, môi trường, thời gian, HTTP attempt và checkpoint để đối chiếu. Runtime thực thi cộng các phiên; thời gian lịch và khoảng chờ giữa phiên báo riêng.
- Tổng hợp RAM bằng peak lớn nhất và trung bình có trọng số theo thời gian; không cộng các peak. Phân biệt disk usage của volume với dung lượng corpus thực tế.
- Crawl phục hồi được phép: báo success/coverage của lượt đầu và sau tối đa ba lượt phục hồi, giữ đầy đủ danh sách lỗi cuối và lịch sử attempt.
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
- Mỗi thành viên có ít nhất 5 publication manual; mỗi publication có ≥20 BibTeX entry được gán nhãn, tổng ≥100 entry/thành viên. Nhóm ba người có ≥15 publication/300 entry; không thay yêu cầu này bằng 20 positive pairs.
- Gán một ground-truth arXiv ID hoặc `null` cho từng BibTeX entry.
- Sinh nhãn nhị phân cho toàn bộ không gian `m × n`; candidate đúng là 1, các candidate còn lại là 0.
- Người khác review toàn bộ positive labels và ít nhất 10% negative labels.
- Lưu annotator, reviewer, evidence URL, confidence và note.
- Tính agreement trên phần được double-label; disagreement phải được phân xử trước data freeze.

**Gán nhãn tự động**

- Tối thiểu 10% số publication còn lại của mỗi thành viên; với dải khoảng 5.000 bài, mục tiêu tối thiểu 500 publication/người.
- Chọn publication có `m > 0`; trường hợp không có candidate vẫn được biểu diễn bằng nhãn không đối ứng, không sửa denominator về riêng tập dễ/đủ điều kiện.
- Luật high-precision:
  - DOI/arXiv ID exact; hoặc
  - normalized title exact; hoặc
  - title similarity rất cao kết hợp first-author match và year difference ≤1.
- Trong publication auto đã chọn, phải gán nhãn toàn bộ entry. Trường hợp mơ hồ cần giải quyết/review hoặc thay cả publication trước khóa pool; không bỏ riêng entry thành unlabeled để làm đẹp điểm.
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
- Mỗi người chịu trách nhiệm ≥5 publication, ≥20 entry/publication và ≥100 entry manual; nhãn không có đối ứng vẫn hợp lệ.

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
- MRR@5 tính trên toàn bộ BibTeX entry test được gán nhãn; đáp án ngoài top-5 hoặc không có đối ứng nhận 0, không tự loại khỏi mẫu số. Báo thêm coverage.
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

- Flatten JSON/BibTeX thành đúng sáu bảng theo đề trực tuyến.
- Dùng Arrow types rõ ràng:
  - dictionary encoding cho `kind`, `entry_type`, `partition`;
  - list of strings cho authors/revised dates;
  - year nullable integer;
  - các field thiếu dùng null, không dùng chuỗi `"None"`.
- Kiểm tra primary key, foreign key, uniqueness và nullable constraints.
- `predictions` chỉ gồm publications tham gia M3.
- Raw source chỉ giữ `.tex`/`.bib` nguyên byte, không xuất bảng `sources`.
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
- Mỗi thành viên đạt ≥5 publication manual, mỗi publication ≥20 entry có nhãn và tổng ≥100 entry.
- Automatic labels đạt ≥10% phần còn lại theo từng thành viên.
- Split được thực hiện theo publication và không có leakage.
- Model tạo top 5 xác định và MRR tái lập được.
- Ba HF datasets có đủ sáu bảng đúng tên/schema và load được.
- Jupyter Book build sạch trên URL đã nộp.
- Poster đúng một slide A2 dọc và có bằng chứng định lượng.
- README cho phép một người mới thiết lập môi trường và chạy lại từng stage.

### Rủi ro và biện pháp

- **Rate limit/network:** centralized scheduler, cache, retry queue, checkpoint và buffer nhiều ngày.
- **Colab mất session:** tiếp tục full benchmark từ checkpoint Drive, giữ log từng phiên và tổng hợp có đối chiếu; không thay bằng sample.
- **Source không chuẩn:** giữ failure taxonomy, manual override cho main file, không âm thầm bỏ bài.
- **Pseudo-label bias:** high-precision rules, manual audit và báo riêng manual/auto MRR.
- **Class imbalance:** class weighting và đánh giá theo ranking, không chỉ accuracy.
- **Trễ deadline:** đóng nội bộ sớm một ngày; URL Book/repo được tạo ngay Phase 0.
- **Giấy phép dữ liệu:** giữ provenance/license metadata nội bộ và mô tả rõ trong dataset card, không tuyên bố một giấy phép chung nếu corpus có nhiều loại.

---

## 6. HỒ SƠ BÀN GIAO THỰC THI MILESTONE 2 (DÀNH CHO THÀNH `23120358` → BÀN GIAO TRỰC TIẾP SANG QUANG `23120345`)

> **Cập nhật bàn giao thực chiến (25/11/2026):** Đây là đặc tả kỹ thuật khép kín dành cho **Nguyễn Tiến Thành (`23120358`)** để triển khai toàn bộ **Milestone 2 (Hierarchical Parsing, Standardization & Two-level Deduplication)** tuân thủ 100% đề trực tuyến (`statement/parsing/`), giải đáp của giảng viên, và hợp đồng dữ liệu đầu vào của **Nguyễn Trịnh Quang (`23120345`)** ở Milestone 3 + xuất 6 bảng Parquet Hugging Face.

### 6.1. Hiện trạng Đầu vào từ Milestone 1 (Đã Kiểm toán Độc lập)

Đường dẫn thư mục chung trên Google Drive: `/content/drive/MyDrive/IDS_Nhom13_Corpus_Backup`

| Thành viên | MSSV | Đường dẫn Raw Corpus chính tắc (`m1-team-v4`) | Trạng thái M1 | Chi tiết Kiểm toán (`5.000` ID/người) |
|:---|:---:|:---|:---|:---|
| **Phạm Minh Thông** | `23120364` | `m1-team-v4/23120364/main/full/23120364/raw/` | **ĐÃ CHỐT (`operational_closed=True`)** | `4.959` `full_success`, `37` `verified_exception` (rút bài HTTP 404 có bằng chứng), `4` `references_unavailable` (S2 404) |
| **Nguyễn Tiến Thành** | `23120358` | `m1-team-v4/23120358/main/full/23120358/raw/` | **ĐÃ CHỐT (`operational_closed=True`)** | `4.962` `full_success`, `35` `verified_exception` (rút bài HTTP 404 có bằng chứng), `3` `references_unavailable` (S2 404) |
| **Nguyễn Trịnh Quang** | `23120345` | `m1-team-v4/23120345/main/full/23120345/raw/` | **Đang cào tiếp** | `1.669` `full_success`, `11` `verified_exception`, `2` `references_unavailable`, `3.318` `pending` |

**Nguyên tắc chạy song song không chờ đợi:**
1. Thành bắt đầu code trên local/fixture (`tests/fixtures/synthetic_paper/`), test pilot trên 30 bài thật, rồi **chạy production M2 ngay lập tức trên `10.000` bài đã đóng băng** của `23120364` và `23120358` (không đụng/sửa bất kỳ byte nào trong `raw/`).
2. Khi dải `23120345` của Quang đóng sổ (`operational_closed=True`), chỉ cần chạy lại đúng 1 lệnh có `--resume` cho `23120345` để hoàn tất đủ `15.000` bài toàn nhóm.
3. **Ràng buộc công cụ từ Giảng viên (Q&A):** Mọi thư viện/xử lý trong parser bắt buộc chạy **offline trên Google Colab CPU-only**, **tuyệt đối không gọi API bên ngoài** (không gọi LLM API, không gọi server GROBID ngoài). Sử dụng bộ phân tích tất định trên CPU (`pylatexenc`, `bibtexparser`, `regex`, state-machine scanner tự viết có kiểm soát).

---

### 6.2. Kiến trúc Module M2 Cần Xây dựng & Giao diện CLI

Thành tạo nhánh `feature/m2-parsing`, triển khai gói `src/ids_arxiv/parser/` gồm các module tách bạch:

```text
src/ids_arxiv/parser/
├── __init__.py            # Hàm điều phối parse_corpus(), parse_publication()
├── compilation_path.py    # Chấm điểm root .tex, strip comment %, đệ quy \input/\include/\subfile, chống cycle/traversal
├── hierarchy_builder.py   # Tokenizer/AST xây cây phân cấp động, xử lý list/item, lọc bỏ References, giữ Acknowledgements & Appendix
├── normalizer.py          # Dọn lệnh bố cục LaTeX, chuẩn hóa Inline Math ($...$) & Block Math (\begin{equation}...\end{equation})
├── sentence_splitter.py   # Che placeholder ($...$, \cite, \ref, URL) rồi tách câu chống cắt nhầm viết tắt/số thập phân
├── bib_extractor.py       # Đọc đa file .bib + chuyển đổi \bibitem[opt]{key} sang BibTeX chuẩn (không bịa trường thiếu)
├── deduplicator.py        # Cấp 1: Gộp BibTeX + Hợp nhất trường (Field Union) + Rewrite \cite{}; Cấp 2: Full-text Dedup sau cleanup
└── m2_report.py           # Tổng hợp thống kê & biểu đồ cho Chương 2 Jupyter Book (book/ch2_parsing.md)
```

**Kết nối vào CLI có sẵn tại `src/ids_arxiv/cli.py`:**
- `python -m ids_arxiv parse --input <raw_dir> --output <processed_dir> --student-id <mssv> --resume`
- `python -m ids_arxiv validate --stage processed --path <processed_dir>`
- `python -m ids_arxiv benchmark --stage parse --manifest ... --output ...` (chạy và ghi log RAM/thời gian trên Google Colab CPU).

---

### 6.3. Hợp đồng Đầu ra M2 (Khớp 100% Đề Trực tuyến & Sẵn sàng Cho Quang ở M3)

Đường dẫn lưu trữ chuẩn trên Google Drive cho mỗi thành viên:
`m1-team-v4/<owner>/main/processed/<owner>/<yymm-id>/` (ví dụ `2509-01047/`), gồm **4 tệp chuẩn**:

1. **`hierarchy.json`** (bắt buộc qua `HierarchyData.model_validate` tại `src/ids_arxiv/schemas/hierarchy.py`):
   ```json
   {
     "elements": {
       "2509-01047#root_v1": "Version 1 root",
       "2509-01047#sec_a1b2c3d4": "Introduction",
       "2509-01047#sent_9f8e7d6c": "We formalize citation matching in $d$-dimensional space \\cite{2509-01047_vaswani2017}."
     },
     "hierarchy": {
       "1": {
         "2509-01047#sec_a1b2c3d4": "2509-01047#root_v1",
         "2509-01047#sent_9f8e7d6c": "2509-01047#sec_a1b2c3d4"
       },
       "2": {}
     },
     "version_states": {
       "1": "downloaded",
       "2": "not_found_404"
     },
     "element_kinds": {
       "2509-01047#root_v1": "document",
       "2509-01047#sec_a1b2c3d4": "section",
       "2509-01047#sent_9f8e7d6c": "sentence"
     }
   }
   ```
   - **Lưu ý cực kỳ quan trọng:** Luôn điền đầy đủ `element_kinds` với tập giá trị chuẩn: `document`, `chapter`, `section`, `subsection`, `subsubsection`, `paragraph`, `list`, `item`, `sentence`, `formula`, `figure` (trong đó **Table bắt buộc gán `kind = "figure"`** theo đề bài). Nhờ có `element_kinds`, module `src/ids_arxiv/exporter.py` và Quang xuất thẳng bảng `elements` sang Parquet mà không phải đoán hay parse lại!
   - Trong `hierarchy[ver]`: **chỉ lưu các cạnh con → cha (`child_id: parent_id` với `child_id != parent_id`)**, đúng như bảng mẫu của đề trực tuyến (`statement/parsing/`). Node gốc `2509-01047#root_v1` nằm trong `elements` (`kind="document"`), đóng vai trò `parent_id` cao nhất của version `1` nhưng không tự trỏ vào chính nó.

2. **`refs.bib`**: Toàn bộ các mục BibTeX của bài báo sau khi hợp nhất xuyên version và khử trùng lặp.

3. **`bibtex_entries.json`** (sidecar phẳng giúp Quang nạp M3 & xuất bảng `bibtex` tức thì không cần parse lại `.bib`):
   Danh sách JSON các dict chứa đúng 8 trường của `BibtexEntryRow` (`citation_key`, `entry_type`, `title`, `authors: list[str]`, `year: int | None`, `doi`, `journal`, `url`) kèm `raw_key_aliases: list[str]` (các key cũ đã gộp vào `citation_key`).

4. **`parse_status.json`** (phục vụ `--resume`, Chương 2 Jupyter Book, và Feature Engineering M3 của Quang):
   - Trạng thái từng version (`parsed`, `pdf_only`, `not_found_404`, `non_tex_source`, `parse_failed` kèm lý do phân loại).
   - Bộ đếm trước/sau khử trùng lặp: `raw_element_count`, `dedup_element_count`, `raw_bib_count`, `dedup_bib_count`, `rewritten_cite_count`, `unresolved_cite_keys`, `tree_max_depth`.
   - **`citation_contexts`** (bàn giao vàng cho Quang làm Feature Hierarchy ở M3!): với mỗi `citation_key`, ghi sẵn `frequency` (tổng số lần được `\cite` trong bài), `first_depth` (độ sâu xuất hiện đầu tiên trong cây), `section_titles` (danh sách tiêu đề mục chứa trích dẫn, ví dụ `["Introduction", "Related Work"]`), `min_normalized_position` ($\in [0, 1]$, vị trí câu đầu tiên chứa trích dẫn chia tổng số nút lá của version mới nhất).
   - Thời gian chạy (`elapsed_seconds`) và kích thước output (`output_bytes`).

---

### 6.4. Danh mục 20 Trường hợp Biên (Edge Cases) Bắt buộc Xử lý Triệt để

Giảng viên đặc biệt đánh giá cao các nhóm xử lý chính xác dữ liệu nhiễu thực tế trên arXiv thay vì chỉ chạy được trên LaTeX mẫu sạch. Thành cần đảm bảo parser xử lý và có unit test cho đủ **20 trường hợp biên** sau:

#### Nhóm A — Phiên bản rỗng & Ngoại lệ từ Milestone 1
1. **Phiên bản không có mã nguồn TeX (`pdf_only`, `not_found` HTTP 404 do tác giả rút bản nộp, hoặc định dạng phi-TeX):** Đọc `crawl_status.json` của bài báo; với mọi version trong `expected_versions` không có file `.tex`, **tuyệt đối không bỏ qua version hoặc xóa bài báo** — bắt buộc giữ khóa `"<v>": {}` trong `hierarchy` và ghi nhận đúng lý do vào `version_states["<v>"]` (đúng quy định đề bài & câu trả lời Q&A của thầy).
2. **Bài có nhiều version trong đó một số version có TeX và một số version bị rút (`v1` tải được, `v2` HTTP 404):** Vẫn parse đầy đủ `v1`, giữ `"2": {}`, không để lỗi thiếu thư mục `v2` làm hỏng cả bài báo.
3. **Bài thuộc diện `references_unavailable` (S2 trả 404 ở M1, `references.json = {}`):** Vẫn parse đầy đủ `hierarchy.json` và `refs.bib` như bình thường để giữ trọn vẹn thống kê M2 và các bảng `papers`, `elements`, `hierarchy`, `bibtex`.

#### Nhóm B — Tìm Root & Gom Đa File (`Multi-file Gathering`)
4. **Lệnh `\input` / `\include` nằm trong dòng comment `%` hoặc sau dấu phần trăm được escape `\%`:** Ví dụ `% \input{old_intro}` phải bị bỏ qua, nhưng `We achieve 99\% accuracy \input{results}` thì `\input{results}` **phải được thực thi**. Luôn chạy bộ lọc comment nhận diện đúng `\%` và bỏ qua môi trường nguyên văn (`verbatim`, `lstlisting`, `\verb|...|`) trước khi tìm lệnh nhúng file.
5. **Biến thể cú pháp nhúng file & thiếu đuôi `.tex`:** Hỗ trợ `\input{sec/intro}`, `\input{sec/intro.tex}`, `\input sec/intro` (cú pháp TeX cổ không ngoặc nhọn), `\include{...}`, `\subfile{...}`, `\import{dir/}{file.tex}`, `\subimport{dir/}{file}`. Tự động nối `.tex` nếu đường dẫn chưa có đuôi; giải quyết đường dẫn tương đối chuẩn xác và **chặn tuyệt đối path traversal** (`..` trỏ ra ngoài thư mục version `vN/`).
6. **Chu trình nhúng file (Include Cycle: `a.tex -> b.tex -> a.tex`) & nhúng lặp file macro:** Duy trì `call_stack` theo nhánh đệ quy; nếu phát hiện chu trình thì ngắt ngay nhánh lặp, ghi vào `parse_status.json` (`include_cycle_detected=True`) thay vì đệ quy vô hạn gây tràn bộ nhớ (`RecursionError`).
7. **Nhiều file chứa `\documentclass` trong cùng thư mục (ví dụ `main.tex`, `supplement.tex`, `rebuttal.tex`, hoặc file con dùng `\documentclass[../main.tex]{subfiles}`):**
   - Loại trừ các file có `\documentclass[...]{subfiles}` hoặc `standalone` hình vẽ khỏi vị trí root nếu có tài liệu chính.
   - Chấm điểm ứng viên root theo thứ tự ưu tiên tất định: có `\begin{document}` + không bị file khác `\input` vào + số lượng file con được gọi hợp lệ lớn nhất + tên chuẩn (`main.tex`, `paper.tex`, `ms.tex`, `article.tex`, `<arxiv_id>.tex`) + độ dài thân bài lớn nhất; lưu `selected_root_file` và danh sách file mồ côi bị loại (`ignored_orphan_files`) vào log.
8. **Bài Plain TeX hoặc thiếu `\documentclass`:** Nếu không file nào có `\documentclass`, ưu tiên file duy nhất có `\begin{document}`; nếu vẫn không có (plain TeX dùng `\bye`), chọn file `.tex` chính theo heuristic kích thước/tên và gắn cờ `plain_tex_fallback=True` thay vì làm rớt bài báo.
9. **Lỗi bảng mã ký tự (Encoding Fallback):** Nguồn arXiv cũ/đa quốc gia thường lẫn `UTF-8-SIG` (BOM), `ISO-8859-1` (`latin-1`), `Windows-1252`. Đọc tuần tự `utf-8-sig` $\rightarrow$ `cp1252` $\rightarrow$ `latin-1` (kèm cờ log encoding) để không bao giờ văng `UnicodeDecodeError`.

#### Nhóm C — Dựng Cây Phân cấp, Giữ & Loại trừ Đúng Quy định
10. **Cấp độ đề mục nhảy bậc hoặc khác lớp tài liệu (`book`/`report` có `\part`, `\chapter` vs `article` bắt đầu từ `\section`, hoặc tác giả nhảy từ `\section` xuống thẳng `\subsubsection`):** Sử dụng ngăn xếp phân cấp theo trọng số (`document: 0 < part: 1 < chapter: 2 < section: 3 < subsection: 4 < subsubsection: 5 < paragraph: 6 < subparagraph: 7`). Khi gặp đề mục mới ở mức $w$, pop các phần tử trên đỉnh stack có mức $\ge w$ rồi gắn node mới vào đỉnh stack hiện tại $\rightarrow$ đảm bảo cây luôn liên thông, đơn gốc, không chu trình dù tác giả đánh cấp lộn xộn.
11. **Bắt buộc GIỮ Acknowledgements & Appendices (kể cả không đánh số `\section*`):**
    - Nhận diện đầy đủ: `\section*{Acknowledgements}`, `\section*{Acknowledgments}`, `\subsection*{...}`, `\paragraph{Acknowledgements}`, môi trường `\begin{acks}...\end{acks}` (chuẩn ACM), lệnh chuyển vùng `\appendix`, môi trường `\begin{appendices}...\end{appendices}`.
12. **Bắt buộc LOẠI TRỪ phần Tài liệu tham khảo khỏi `hierarchy.json`:**
    - Không đưa vào cây phân cấp mọi khối `\begin{thebibliography}...\end{thebibliography}`, lệnh `\bibliography{...}`, `\addbibresource{...}`, `\printbibliography`, môi trường `bibunit`/`refsection`, và cả trường hợp tác giả tự gõ mục `\section*{References}` / `\section*{Bibliography}` thủ công bằng `\item` hoặc đoạn văn cuối bài (chuyển toàn bộ nội dung đó sang `bib_extractor.py`).
13. **Danh sách lồng nhau (`itemize`, `enumerate`, `description`) & Bảng biểu (`table` $\rightarrow$ `figure`):**
    - Mỗi khối `\begin{itemize|enumerate|description}` tạo 1 node `kind="list"`; mỗi `\item` (kể cả `\item[Bước 1:]`) tạo 1 node con `kind="item"`, bên trong `\item` tiếp tục tách câu/công thức/danh sách con.
    - Mọi môi trường hình và bảng (`figure`, `figure*`, `subfigure`, `wrapfigure`, `table`, `table*`, `wraptable`, `longtable`, `tabularx` độc lập) đều là nút lá độc lập với **`kind="figure"`** theo đúng quy ước của đề bài.

#### Nhóm D — Chuẩn hóa Toán học, Dọn LaTeX & Tách Câu Chính xác
14. **Chuẩn hóa Toán học an toàn (không vỡ bởi `\$` tiền tệ hoặc môi trường con `aligned`/`cases`/`matrix`):**
    - Phân biệt chính xác `\$` (ký hiệu đô-la văn bản, giữ nguyên) với `$ ... $` (toán nội dòng) và `$$ ... $$` (toán khối).
    - Inline math: đổi `\(...\)`, `\begin{math}...\end{math}`, `\ensuremath{...}` về `$...$`.
    - Block math: đổi `$$...$$`, `\[...\]`, `equation*`, `align`, `align*`, `gather`, `gather*`, `multline`, `multline*`, `flalign`, `eqnarray` thành leaf node `kind="formula"` dạng chuẩn `\begin{equation}...\end{equation}`. Giữ nguyên các môi trường con bên trong công thức (`\begin{aligned}`, `\begin{pmatrix}`, `\begin{cases}`) và **không chạy bộ lọc xóa lệnh LaTeX văn bản lên bên trong công thức toán**.
15. **Làm sạch lệnh định dạng thừa nhưng bảo toàn ngữ nghĩa & lệnh `\cite{}`:**
    - Xóa các lệnh/tham số trang trí thuần hình thức: `\centering`, `\raggedright`, `\raggedleft`, `\noindent`, `\newpage`, `\clearpage`, `\pagebreak`, `\vspace*{...}`, `\hspace*{...}`, `\smallskip`, `\medskip`, `\bigskip`, `\toprule`, `\midrule`, `\bottomrule`, `\hline`, `\cline{...}`, tham số vị trí float `[htbp!]`, `[!t]`, `[H]`.
    - Mở gói các lệnh bọc chữ mang nội dung: `\textbf{abc}` $\rightarrow$ `abc`, `\textit{abc}` $\rightarrow$ `abc`, `\emph{abc}` $\rightarrow$ `abc`, `\underline{abc}` $\rightarrow$ `abc` (chỉ áp dụng ngoài vùng toán).
    - **Bắt buộc giữ nguyên các lệnh trích dẫn** (`\cite`, `\citep`, `\citet`, `\citealt`, `\citeauthor`, `\citeyear`, `\parencite`, `\textcite`, `\autocite`, `\nocite`) để bước sau đổi sang `canonical_key` và truyền sang M3!
16. **Tách câu (Sentence Splitting) có che chắn (Placeholder Masking):**
    - Trước khi tách câu trên một đoạn văn: thay thế tạm toàn bộ inline math `$...$`, lệnh `\cite...{...}`, `\ref{...}`, `\eqref{...}`, `\autoref{...}`, `\url{...}`, `\href{...}{...}` bằng token không chứa dấu chấm (ví dụ `__MATH_0__`, `__CITE_0__`).
    - Không tách câu sau chữ viết tắt học thuật (`e.g.`, `i.e.`, `et al.`, `cf.`, `vs.`, `w.r.t.`, `a.k.a.`, `resp.`, `Fig.`, `Figs.`, `Tab.`, `Tabs.`, `Eq.`, `Eqs.`, `Sec.`, `Secs.`, `Alg.`, `Thm.`, `Lem.`, `Prop.`, `Cor.`, `App.`, `Ch.`, `Vol.`, `No.`, `pp.`, `Dr.`, `Prof.`, `Mr.`, `Mrs.`, `Ms.`, chữ cái tên tắt `J. Doe`), số thực (`3.14`), hoặc dấu ba chấm (`...`).
    - Khôi phục lại placeholder sau khi tách câu, chuẩn hóa khoảng trắng thừa (`" ".join(s.split())`), bỏ các mảnh rỗng chỉ có dấu câu/comment.

#### Nhóm E — Trích xuất BibTeX & Khử Trùng lặp 2 Cấp độ
17. **Đọc `.bib` lỗi cú pháp thực tế & Bóc tách `\bibitem` có tham số tùy chọn:**
    - File `.bib` thực tế trên arXiv hay có macro `@STRING{cvpr = "Proc. IEEE CVPR"}`, ngoặc nhọn lồng nhiều cấp `title = {{BERT}: Pre-training of Deep Bidirectional Transformers}`, thiếu dấu phẩy cuối trường, hoặc trùng key ngay trong cùng 1 file `.bib` $\rightarrow$ cần mở rộng `@STRING` và bắt ngoại lệ từng entry để 1 entry lỗi không làm mất cả file `.bib`.
    - Với `\bibitem`: hỗ trợ cả `\bibitem{key}` lẫn `\bibitem[Vaswani et al., 2017]{key}`; xử lý các cách trình bày phổ biến (nháy kép `"Title"`, `\emph{Title}`, `\newblock`, năm `(2023)` hoặc `, 2023.`, `arXiv:2301.12345`, `doi:10.xxxx/...`). Trường không có trong văn bản gốc thì để `None`/`""`, **không tự suy diễn hoặc bịa giá trị**.
    - *(Lưu ý bám sát đề trực tuyến)*: Corpus M1 chỉ giữ `.tex` và `.bib`, không giữ `.bbl`; parser trích từ toàn bộ `.bib` trong thư mục version và mọi `\bibitem` nằm trong các file `.tex` thuộc luồng biên dịch.
18. **Khử trùng lặp Cấp 1 — Reference Deduplication + Field Unionization + Đổi tên `\cite{}` đa khóa:**
    - Gom tất cả mục trích dẫn từ mọi version `v1..vN` của bài báo. Hai mục được coi là cùng một tài liệu tham khảo khi:
      1. Trùng `DOI` chuẩn hóa (bỏ tiền tố `https://doi.org/`, viết thường); hoặc
      2. Trùng `arXiv ID` chuẩn hóa (bỏ hậu tố `vN`, viết thường); hoặc
      3. Tiêu đề chuẩn hóa (bỏ dấu câu/ngoặc LaTeX, lowercase) khớp chính xác (hoặc Jaro-Winkler / token ratio $\ge 0.95$ không mơ hồ) **kèm** trùng họ tác giả đầu tiên và chênh lệch năm $\le 1$ (tránh gộp nhầm *"Paper Title — Part I"* và *"Paper Title — Part II"* bằng cách kiểm tra hậu tố số La Mã/Part/Volume!).
    - **Chọn `canonical_key`:** Ưu tiên key xuất hiện sớm nhất có tiền tố định danh ổn định, đồng thời lưu ánh xạ `alias_map[old_key] = canonical_key`.
    - **Field Unionization (Hợp nhất trường — bắt buộc theo ví dụ đề bài):** Hợp nhất tất cả các trường không rỗng (`title`, `authors`, `year`, `doi`, `journal`, `url`, `entry_type` ưu tiên cụ thể hơn `@misc`). Nếu `v1` có `year=2017`, `v2` thêm `doi` nhưng `v3` mất `year`, bản ghi cuối cùng bắt buộc giữ đủ cả `year=2017` và `doi`!
    - **Rewrite `\cite{}` đa khóa:** Cập nhật mọi lệnh trích dẫn trong câu và trong `\caption{}` của Figure/Table, xử lý chính xác danh sách nhiều key cách nhau bởi dấu phẩy và khoảng trắng: ví dụ `\citep[see][]{key_a, vit_transformer, key_b}` $\rightarrow$ `\citep[see][]{key_a, vaswani2017, key_b}` (đồng thời khử lặp nếu hai key trong cùng một `\cite{k1, k2}` cùng gộp về một `canonical_key` $\rightarrow$ `\cite{canonical_key}`!).
19. **Khử trùng lặp Cấp 2 — Full-text Content Deduplication (Sau Cleanup & Sau khi Đổi tên `\cite{}`):**
    - **Thứ tự bắt buộc:** Cleanup LaTeX $\rightarrow$ Chuẩn hóa Math $\rightarrow$ Đổi tên `\cite{}` sang `canonical_key` $\rightarrow$ **Mới tính mã băm nội dung để khử trùng lặp Full-text!** (Nếu dedup trước khi đổi tên `\cite{}`, một câu không đổi giữa `v1` và `v2` nhưng tác giả đổi tên citation key sẽ bị tính thành 2 element khác nhau — mất điểm dedup!).
    - **Xử lý câu giống hệt nhau lặp lại nhiều lần trong CÙNG một version (ví dụ câu tiêu đề phụ `"Experimental Setup"` hoặc `"Proof."` xuất hiện 3 lần trong `v1`):**
      - Đánh chỉ số lần xuất hiện `occ_idx` (`0, 1, 2...`) cho cặp `(kind, normalized_content)` bên trong một version: `element_id = f"{dir_id}#{kind_code}_{sha256_12}"` (với `occ_idx == 0`) và `f"{dir_id}#{kind_code}_{sha256_12}_{occ_idx}"` (với `occ_idx >= 1`).
      - Nhờ vậy: trong cùng `v1`, 3 câu `"Proof."` ở 3 định lý khác nhau là 3 nút riêng (mỗi nút có đúng 1 cha duy nhất trong `hierarchy["1"]`, không bị ghi đè mất 2 cạnh trước!); đồng thời sang `v2`, câu `"Proof."` lần thứ nhất, thứ hai, thứ ba tự động khớp lại đúng `element_id` tương ứng của `v1`!
20. **Kiểm soát RAM & Thời gian trên Bài báo Cực lớn (Colab CPU Budget):**
    - Một số bài survey/thesis trên arXiv có hàng trăm trang `.tex` hoặc file `.bib` vài chục MB: xử lý cuốn chiếu từng bài báo, ghi kết quả atomic (`tmp` $\rightarrow$ `replace`), giải phóng cây AST ngay sau mỗi bài, đặt giới hạn an toàn cho regex tránh catastrophic backtracking, và ghi checkpoint mỗi bài để `--resume` bỏ qua ngay các bài đã có `parse_status.json` hợp lệ.

---

### 6.5. Quy trình Thực hiện Từng Bước cho Thành (`Step-by-Step`)

1. **Bước 1 — Khởi tạo nhánh & Cài đặt gói bổ sung (nếu cần):**
   - `git checkout main && git pull && git checkout -b feature/m2-parsing`
   - Nếu thêm thư viện CPU nhẹ (như `pylatexenc`, `bibtexparser`), cập nhật đồng thời vào cả `pyproject.toml`, `requirements.txt` và `requirements-colab-m1.txt` (hoặc tạo `requirements-colab-m2.txt`).
2. **Bước 2 — Xây bộ Unit Test cho 20 Edge Cases trước/song song khi code:**
   - Tạo `tests/test_parser_compilation.py`, `tests/test_parser_hierarchy.py`, `tests/test_parser_normalization.py`, `tests/test_parser_dedup.py`.
   - Đảm bảo `ruff check src tests` và `pytest` xanh 100% trên GitHub Actions CI.
3. **Bước 3 — Chạy Pilot kiểm chứng trên 30 bài thật (10 bài/thành viên):**
   - Chọn cả bài nhiều version (`v1..v4`), bài `pdf_only`, bài có `verified_exception` HTTP 404, bài có cả `.bib` lẫn `\bibitem`.
   - Kiểm tra bằng `python -m ids_arxiv validate --stage processed` và đọc kiểm tra bằng mắt ít nhất 10 bài trong dải `23120358`.
4. **Bước 4 — Chạy Production & Benchmark trên Google Colab CPU:**
   - Chạy parser trên Colab CPU cho toàn bộ dải `23120364` (`5.000` bài) và `23120358` (`5.000` bài), lưu output vào `m1-team-v4/<owner>/main/processed/<owner>/`, thu thập đầy đủ Wall Time, trung bình giây/bài, Peak RAM, dung lượng output và tỷ lệ giảm trùng lặp.
   - Chạy tiếp cho dải `23120345` ngay khi Quang hoàn tất cào M1.
5. **Bước 5 — Viết Chương 2 Jupyter Book (`book/ch2_parsing.md`):**
   - Biến `book/ch2_parsing.md` thành MyST Notebook thực thi code tự động từ file snapshot thống kê M2 (giống cơ chế `artifacts/m1-report/snapshot.json` của Chương 1) — tuyệt đối không dán ảnh chụp màn hình tĩnh!
   - Trình bày đủ: sơ đồ luồng biên dịch đa file, quy tắc dựng cây & chuẩn hóa, giải thuật khử trùng lặp 2 cấp độ, phân bố độ sâu cây, tỷ lệ thành công theo version/publication, số lượng element & BibTeX trước/sau dedup (% giảm dư thừa), bảng phân loại lỗi biên (nếu có), và bảng benchmark Colab CPU (Wall time, s/paper, Peak RAM, Output size).

---

### 6.6. Checklist Nghiệm thu Milestone 2 & Gói Bàn giao Sang Quang (Milestone 3)

Trước khi merge PR `feature/m2-parsing` vào `main` và nhắn Quang bắt đầu chạy M3 trên dữ liệu thật, Thành tích chọn xác nhận đủ **12 tiêu chí cổng nghiệm thu (Acceptance Gate)** sau:

- [ ] **1. Bao phủ 100% Manifest:** Đủ `5.000 / 5.000` bài mỗi dải đã chốt đều có thư mục trong `processed/<owner>/<yymm-id>/` (kể cả bài `pdf_only` hay rút bài đều có `hierarchy.json` ghi version rỗng `{}` và `refs.bib` hợp lệ, không mất bất kỳ ID nào).
- [ ] **2. Tỷ lệ Parse thành công cao:** Đạt $\ge 98\%$ trên tổng số các version có nguồn LaTeX hợp lệ; $100\%$ các trường hợp lỗi còn lại có mã phân loại nguyên nhân rõ ràng trong `parse_status.json`.
- [ ] **3. Tính chất Cây chuẩn Toán học:** `python -m ids_arxiv validate --stage processed` đạt 100% (`0` chu trình, mỗi version có TeX có đúng 1 root `kind="document"`, mọi `child_id != parent_id`, mọi ID trong `hierarchy` đều tồn tại trong `elements` và mang tiền tố mã bài báo).
- [ ] **4. Loại trừ & Bao gồm Đúng Luật:** `0%` cây phân cấp chứa mục References/Bibliography; `100%` bài có Acknowledgements và Appendices (kể cả `\section*`) được giữ nguyên trong cây.
- [ ] **5. Chuẩn hóa Nút lá & Toán học:** Nút lá chỉ thuộc 3 loại (`sentence`, `formula`, `figure` — gồm cả Table); Inline math đồng nhất về `$...$`; Block math đồng nhất về `\begin{equation}...\end{equation}`; không còn rác bố cục (`\centering`, `\midrule`, `[htbp]`).
- [ ] **6. Khử trùng lặp Cấp 1 (BibTeX + Field Union + Cite Rewrite):** Mọi mục trùng qua các version đã hợp nhất đầy đủ các trường (`title`, `authors`, `year`, `doi`, `journal`, `url`) và mọi lệnh `\cite{...}` trong `elements` đã đổi sang `canonical_key` khớp với `refs.bib` / `bibtex_entries.json`.
- [ ] **7. Khử trùng lặp Cấp 2 (Full-text sau Cleanup):** Câu/phần tử không đổi giữa `v1` và `v2` dùng chung đúng 1 `element_id` trong `elements`; câu lặp nhiều lần trong cùng 1 version không làm mất cạnh của cây.
- [ ] **8. Tương thích Xuất Parquet Tự động:** Chạy thử `python -m ids_arxiv export --student-id 23120358 --raw-dir ... --processed-dir ... --output /tmp/test_hf` sinh thành công các bảng `elements`, `hierarchy`, `bibtex` khác rỗng và pass `python -m ids_arxiv validate --stage hf --student-id 23120358`.
- [ ] **9. Gói Đặc trưng Cây sẵn cho Quang (`citation_contexts`):** Trong `parse_status.json` (hoặc bảng tổng hợp `m2_citation_contexts.parquet`), mỗi `(arxiv_id, citation_key)` đã có sẵn `frequency`, `first_depth`, `section_titles`, `min_normalized_position` để Quang ghép thẳng với `references.json` (M1) tạo không gian ứng viên $m \times n$ của M3 mà không cần đọc lại LaTeX.
- [ ] **10. Benchmark Colab CPU Chính thức:** Có file JSON tổng hợp benchmark chạy trên Google Colab CPU (Wall time, mean/median s/bài, Peak RAM, dung lượng đĩa đầu ra).
- [ ] **11. Chương 2 Jupyter Book Build Sạch:** `jupyter-book build book --all --warningiserror --keep-going` pass 100% không lỗi, sinh tự động toàn bộ bảng biểu & đồ thị tương tác.
- [ ] **12. CI/CD Xanh trên GitHub:** `ruff check src tests` và `pytest` pass 100% trên GitHub Actions, không có bất kỳ file dữ liệu/nhị phân/token nào lọt vào Git.

**Ngay khi đạt đủ 12 mục trên, gói bàn giao trao tay cho Quang (`23120345`) gồm:**
1. Nhánh `main` đã merge parser + exporter + `m2_report.py`.
2. Đường dẫn Drive `m1-team-v4/<owner>/main/processed/<owner>/` chứa đủ `hierarchy.json`, `refs.bib`, `bibtex_entries.json`, `parse_status.json` (kèm `citation_contexts`).
3. Snapshot thống kê M2 để cả nhóm ráp vào Dataset Card Hugging Face và Poster khổ A2 dọc (`13.pptx`).
