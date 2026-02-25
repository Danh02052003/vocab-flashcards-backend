# Hướng Dẫn Test API Bằng Postman (Copy/Paste Dùng Ngay)

Tài liệu này viết đúng theo backend hiện tại trong repo `vocab-flashcards-backend`.
Mục tiêu: bạn chỉ cần copy/paste request và test tuần tự.

## 1) Chạy backend

Trong thư mục `vocab-flashcards-backend`:

```powershell
pip install -r requirements.txt
uvicorn app.main:app --reload
```

URL mặc định:
- Base URL: `http://127.0.0.1:8000`
- Swagger: `http://127.0.0.1:8000/docs`

## 2) Tạo Postman Environment

Tạo environment tên `vocab-local` với các biến:
- `base_url` = `http://127.0.0.1:8000`
- `vocab_id` = (để trống)
- `pack_id` = (để trống)
- `sync_payload` = (để trống)

Lưu ý:
- Bắt buộc chọn đúng environment `vocab-local` trước khi gửi request.
- Với request có body JSON, thêm header `Content-Type: application/json`.

Quy tắc mới cho kiểm tra chính tả/ngữ nghĩa khi thêm từ:
- `inputMethod = "typed"`: backend sẽ gọi AI để kiểm tra chính tả và nghĩa trước khi lưu.
- `inputMethod = "pasted"`: backend bỏ qua bước AI check để tiết kiệm chi phí.
- `ipa` chỉ dùng để học phiên âm/cách đọc, không dùng để check đúng/sai.

## 3) Bộ test đầy đủ theo thứ tự

## 3.1 Health

Request:
- Method: `GET`
- URL: `{{base_url}}/health`

Kỳ vọng:
- Status `200`
- Body:

```json
{
  "status": "ok"
}
```

## 3.2 Tạo vocab mới - POST /vocab

Request:
- Method: `POST`
- URL: `{{base_url}}/vocab`
- Body:

```json
{
  "term": "resilient",
  "meanings": ["bền bỉ", "có khả năng phục hồi nhanh"],
  "ipa": "/rɪˈzɪliənt/",
  "exampleEn": "She is resilient after every setback.",
  "exampleVi": "Cô ấy rất bền bỉ sau mỗi lần thất bại.",
  "mnemonic": "Re-silient = quay lại mạnh mẽ",
  "tags": ["adjective", "personality"],
  "collocations": ["build resilience", "highly resilient"],
  "phrases": ["be resilient in adversity"],
  "wordFamily": {
    "noun": ["resilience"],
    "adverb": ["resiliently"]
  },
  "topics": ["Education", "Personal Development"],
  "cefrLevel": "B2",
  "ieltsBand": 6.5,
  "inputMethod": "typed"
}
```

Script (tab `Tests`) để lưu `vocab_id`:

```javascript
pm.test("Status 200", function () {
  pm.response.to.have.status(200);
});
const json = pm.response.json();
pm.environment.set("vocab_id", json.id);
```

Cần kiểm tra:
- `termNormalized` phải là `resilient`.
- SM-2 khởi tạo đúng:
  - `easeFactor = 2.5`
  - `intervalDays = 0`
  - `repetitions = 0`
  - `lapses = 0`

## 3.3 Duplicate add + re-add penalty - POST /vocab

Request:
- Method: `POST`
- URL: `{{base_url}}/vocab`
- Body:

```json
{
  "term": "Resilient!!!",
  "meanings": ["có sức chịu đựng cao", "bền bỉ"],
  "tags": ["readd"]
}
```

Kỳ vọng:
- Status `200` (không tạo vocab mới, cập nhật vocab cũ).
- `readdCount` tăng thêm 1.
- `lastReaddAt` có giá trị.
- `repetitions = 0`, `intervalDays = 0`, `dueAt` gần now.
- `easeFactor` giảm 0.2 (không thấp hơn 1.3).
- `meanings` được gộp (union), không trùng.

Lưu ý đúng theo code hiện tại:
- Duplicate add chỉ merge `meanings`.
- `tags` từ request duplicate không được merge vào vocab cũ.

Lưu ý:
- Nếu `inputMethod = "typed"` và AI đánh giá từ/nghĩa có vấn đề, API có thể trả `422` kèm gợi ý sửa.

## 3.4 List vocab - GET /vocab

Request 1:
- `GET {{base_url}}/vocab?page=1&limit=20`

Request 2:
- `GET {{base_url}}/vocab?search=resilient`

Request 3:
- `GET {{base_url}}/vocab?tag=adjective`

Kỳ vọng:
- Status `200`
- Trả về mảng object vocab.

## 3.5 Lấy chi tiết vocab - GET /vocab/{id}

Request:
- `GET {{base_url}}/vocab/{{vocab_id}}`

Kỳ vọng:
- Status `200`
- `id` đúng bằng `{{vocab_id}}`.

Negative test:
- `GET {{base_url}}/vocab/invalid-id`
- Kỳ vọng `400` với `Invalid ObjectId`.

## 3.6 Cập nhật vocab - PUT /vocab/{id}

Request:
- `PUT {{base_url}}/vocab/{{vocab_id}}`
- Body:

```json
{
  "term": "Resilient  ",
  "meanings": ["bền bỉ", "dẻo dai"],
  "tags": ["adjective", "updated"],
  "mnemonic": "resilient -> re + silent = im lặng nhưng bền bỉ"
}
```

Kỳ vọng:
- Status `200`
- `updatedAt` thay đổi.
- `termNormalized` vẫn là `resilient`.
- `meanings` và `tags` được loại trùng.

## 3.7 Session hôm nay - GET /session/today

Request:
- `GET {{base_url}}/session/today?limit=30`

Kỳ vọng:
- Status `200`
- Có 2 mảng:
  - `todayNew`
  - `review`
- Trong `review` không có item trùng.

## 3.8 Review - POST /review

Request:
- `POST {{base_url}}/review`
- Body:

```json
{
  "vocabId": "{{vocab_id}}",
  "mode": "typing",
  "questionType": "term_to_meaning",
  "grade": 4,
  "userAnswer": "bền bỉ"
}
```

Kỳ vọng:
- Status `200`
- Có các field: `nextDueAt`, `intervalDays`, `easeFactor`, `repetitions`, `lapses`.
- Có thêm 1 log mới trong `review_logs`.

Negative tests:
1. `grade = 6` -> `422`.
2. `vocabId = "abc"` -> `400`.

## 3.9 AI enrich - POST /ai/enrich

Request:
- `POST {{base_url}}/ai/enrich`
- Body:

```json
{
  "term": "resilient",
  "meaningsExisting": ["bền bỉ"]
}
```

Kỳ vọng:
- Status `200`
- Có:
  - `provider` (`stub` nếu không có OPENAI_API_KEY)
  - `aiCalled`
  - `fromCache`
  - `data.examples`, `data.mnemonics`, `data.meaningVariants`, `data.ipa`

Cách test cache:
1. Gọi lần 1.
2. Gọi lại y chang lần 2.
3. Lần 2 thường sẽ `fromCache = true`.

## 3.10 AI judge equivalence - POST /ai/judge_equivalence

Case A (fuzzy match):
- `POST {{base_url}}/ai/judge_equivalence`
- Body:

```json
{
  "term": "resilient",
  "userAnswer": "bền bỉ",
  "meanings": ["bền bỉ", "dẻo dai"]
}
```

Kỳ vọng:
- Status `200`
- `isEquivalent = true`
- `reasonShort = "fuzzy match"`
- `provider = "fuzzy"`

Case B (đi qua AI/cache):

```json
{
  "term": "resilient",
  "userAnswer": "có thể đứng dậy sau thất bại",
  "meanings": ["bền bỉ", "phục hồi nhanh"]
}
```

Kỳ vọng:
- Lần 1: `cached = false`.
- Lần 2 cùng input: `cached = true`.
- Khi `isEquivalent = true`, backend tự học `userAnswer`:
  - Nếu từ đã có trong `vocabs` thì thêm vào `meanings` (nếu chưa có).
  - Đồng thời thêm vào `ai_cache` key `enrich:v1:<termNormalized>` trong `data.meaningVariants`.
  - Mục tiêu: lần sau tăng khả năng fuzzy match/cached và giảm gọi AI.

## 3.11 Sync export - GET /sync/export

Request:
- `GET {{base_url}}/sync/export`

Kỳ vọng:
- Status `200`
- Có `schemaVersion = "v1"`, `exportedAt`, `vocabs`, `review_logs`, `events`.

Script (tab `Tests`) để lưu payload import:

```javascript
pm.test("Status 200", function () {
  pm.response.to.have.status(200);
});
pm.environment.set("sync_payload", JSON.stringify(pm.response.json()));
```

## 3.12 Sync import - POST /sync/import

Request:
- `POST {{base_url}}/sync/import`
- Body raw JSON:

```json
{{sync_payload}}
```

Lưu ý:
- Chọn body kiểu `raw` + `JSON`.
- Không bọc `{{sync_payload}}` trong dấu ngoặc kép.

Kỳ vọng:
- Status `200`
- Trả report gồm: `addedVocabs`, `updatedVocabs`, `addedLogs`, `conflicts`.

## 3.13 Xóa vocab - DELETE /vocab/{id}

Request:
- `DELETE {{base_url}}/vocab/{{vocab_id}}`

Kỳ vọng:
- Status `200`
- Body:

```json
{
  "deleted": true
}
```

Kiểm tra thêm:
- `GET {{base_url}}/vocab/{{vocab_id}}` -> `404`.
- Các `review_logs` liên quan vocab này đã bị xóa.

## 3.14 API mới: Upsert + AI trong 1 lần gọi - POST /vocab/upsert_with_ai

API này đúng flow bạn yêu cầu:
- Từ chưa có: tự thêm vào `vocabs`.
- Từ đã có + gửi nghĩa mới: ghi đè nghĩa cũ (mặc định).
- Có thể gọi AI gợi ý luôn trong cùng request.

Request:
- `POST {{base_url}}/vocab/upsert_with_ai`
- Body:

```json
{
  "term": "resilient",
  "meanings": ["kiên cường", "phục hồi nhanh"],
  "ipa": "/rɪˈzɪliənt/",
  "tags": ["adjective", "smart-upsert"],
  "collocations": ["emotionally resilient"],
  "topics": ["Health", "Psychology"],
  "cefrLevel": "C1",
  "ieltsBand": 7.0,
  "inputMethod": "typed",
  "overwriteExisting": true,
  "useAi": true,
  "forceAi": false
}
```

Ý nghĩa các cờ:
- `overwriteExisting=true`: từ đã có thì ghi đè `meanings/tags` bằng dữ liệu mới gửi lên.
- `useAi=true`: bật AI enrich.
- `forceAi=true`: ép gọi AI lại và refresh cache enrich ngay cả khi dữ liệu đã đủ.

Kỳ vọng:
- Status `200`
- Response có:
  - `action`: `created` hoặc `updated`
  - `overwritten`: `true/false`
  - `vocab`: bản ghi sau cùng
  - `ai`: trạng thái gọi AI (`provider`, `aiCalled`, `fromCache`)
- `suggestions`: dữ liệu gợi ý (`examples`, `mnemonics`, `meaningVariants`, ...)
- `suggestions.ipa` để học phát âm.

## 3.15 Cloze practice - POST /practice/cloze/generate

Request:
- `POST {{base_url}}/practice/cloze/generate`
- Body:

```json
{
  "topic": "Education",
  "limit": 5
}
```

Kỳ vọng:
- Status `200`
- Trả `items` gồm: `vocabId`, `term`, `ipa`, `question`, `hint`, `acceptableAnswers`.

## 3.16 Cloze submit - POST /practice/cloze/submit

Request:
- `POST {{base_url}}/practice/cloze/submit`
- Body:

```json
{
  "vocabId": "{{vocab_id}}",
  "userAnswer": "resilient"
}
```

Kỳ vọng:
- Status `200`
- Có `correct`, `nearCorrect`, `expected`.
- Backend lưu log vào `practice_logs`.

## 3.17 Speaking lexical feedback - POST /practice/speaking_feedback

Request:
- `POST {{base_url}}/practice/speaking_feedback`
- Body:

```json
{
  "prompt": "Describe a challenge you overcame.",
  "responseText": "I faced a difficult period at school but I was resilient and adapted quickly.",
  "targetWords": ["resilient", "adapt", "overcome"]
}
```

Kỳ vọng:
- Status `200`
- Có: `estimatedBand`, `targetCoverage`, `usedTargetWords`, `strengths`, `improvements`.
- Có `provider` (`openai` hoặc `stub`).

## 3.18 Writing error bank - POST /writing/error-bank

Request:
- `POST {{base_url}}/writing/error-bank`
- Body:

```json
{
  "sentence": "People is become more depend on technology.",
  "correctedSentence": "People are becoming more dependent on technology.",
  "category": "grammar",
  "topic": "Technology",
  "notes": "SVA + adjective form"
}
```

Kỳ vọng:
- Status `200`
- Trả item có `count`.
- Nếu gửi trùng lỗi, `count` sẽ tăng.

## 3.19 Xem error bank + deck

Request 1:
- `GET {{base_url}}/writing/error-bank?topic=Technology&limit=20`

Request 2:
- `GET {{base_url}}/writing/error-bank/deck?limit=10`

Kỳ vọng:
- Status `200`
- Có dữ liệu lỗi để ôn tập.

## 3.20 Tạo topic pack - POST /packs

Request:
- `POST {{base_url}}/packs`
- Body:

```json
{
  "name": "IELTS Environment Pack",
  "description": "Core vocabulary for environment topic",
  "topics": ["Environment"],
  "targetBand": 7.0,
  "vocabIds": ["{{vocab_id}}"]
}
```

Kỳ vọng:
- Status `200`
- Trả `id` của pack.

Script (tab `Tests`) để lưu `pack_id`:

```javascript
const json = pm.response.json();
pm.environment.set("pack_id", json.id);
```

## 3.21 Add vocab vào pack - POST /packs/{pack_id}/add_vocab

Request:
- `POST {{base_url}}/packs/{{pack_id}}/add_vocab`
- Body:

```json
{
  "vocabId": "{{vocab_id}}"
}
```

Kỳ vọng:
- Status `200`
- `vocabIds` trong pack có thêm id mới (không trùng).

## 3.22 Lấy session theo pack - GET /packs/{pack_id}/session

Request:
- `GET {{base_url}}/packs/{{pack_id}}/session?limit=20`

Kỳ vọng:
- Status `200`
- Trả `pack` và `vocabs` để học theo chủ đề.

## 3.23 Analytics - GET /analytics/overview và /analytics/topics

Request 1:
- `GET {{base_url}}/analytics/overview?days=30`

Request 2:
- `GET {{base_url}}/analytics/topics?days=30`

Kỳ vọng:
- Status `200`
- `overview`: có `accuracyRate`, `typingAccuracy`, `avgGrade`, `dueNow`.
- `topics`: thống kê theo từng topic.

## 4) Checklist nghiệm thu

- [ ] `/health` hoạt động.
- [ ] Tạo vocab thành công, `termNormalized` đúng.
- [ ] Duplicate add kích hoạt re-add penalty đúng.
- [ ] List/search/tag hoạt động đúng.
- [ ] Get detail + validate ObjectId đúng.
- [ ] Update vocab đúng normalize + updatedAt.
- [ ] Session `/session/today` trả đúng cấu trúc.
- [ ] Review lưu log và cập nhật SM-2 đúng.
- [ ] AI enrich có cache.
- [ ] AI judge fuzzy-first và có cache.
- [ ] Metadata IELTS (collocation/phrase/wordFamily/CEFR/band/topics) lưu đúng.
- [ ] Cloze generate + submit hoạt động.
- [ ] Speaking feedback trả band estimate + gợi ý cải thiện.
- [ ] Writing error bank lưu lỗi và tạo deck ôn tập.
- [ ] Topic packs tạo được và trả session theo pack.
- [ ] Analytics overview/topics trả số liệu hợp lý.
- [ ] Sync export/import chạy được.
- [ ] Delete vocab xóa cả logs liên quan.

## 5) Test lỗi nên chạy thêm

1. POST `/vocab` với:

```json
{ "term": "" }
```

Kỳ vọng: `422`.

2. POST `/review` với:

```json
{
  "vocabId": "abc",
  "mode": "typing",
  "questionType": "term_to_meaning",
  "grade": 3
}
```

Kỳ vọng: `400`.

3. POST `/review` với `grade = 6` -> `422`.
4. GET `/vocab/not-an-objectid` -> `400`.
5. POST `/sync/import` với `schemaVersion = "v2"` -> `422`.
