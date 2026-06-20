# AI-Powered Transaction Processing — draw.io Architecture Diagram

A precise, step-by-step specification for recreating the system's architecture in [app.diagrams.net](https://app.diagrams.net) (draw.io). Reflects the **actual** implementation, not the planned one.

---

## 1. Canvas Setup

1. Open **app.diagrams.net** → **File → New** → choose **Blank Diagram**.
2. Set page size: **File → Page Setup → Custom → Width 1600, Height 1100**, Landscape.
3. Set grid: **View → Grid → 10px**, **View → Snap to Grid: ON**.
4. Set style defaults once (avoids repetition):
   - Default font: **Helvetica**, 11pt, dark grey `#333333`.
   - Default edge: `orthogonalEdgeStyle=1;rounded=0;html=1;strokeColor=#6C8EBF;strokeWidth=2;endArrow=classic;endFill=1;`
   - Default vertex: `whiteSpace=wrap;html=1;rounded=1;arcSize=12;shadow=1;fontSize=11;`

> **Tip:** In draw.io, every shape and edge has a "Style" textbox on the **Style** tab of the right panel. Paste the style strings below directly into that box.

---

## 2. Layer Layout (Top to Bottom)

| Y-band  | Region                              |
|---------|--------------------------------------|
| y ≈ 60  | External Actor (User)                |
| y ≈ 200 | Edge / API Tier                      |
| y ≈ 420 | Async Worker + Pipeline Stages       |
| y ≈ 760 | Persistence Tier                     |
| y ≈ 920 | Cross-cutting Infrastructure         |

Use **container shapes** (draw.io rounded rectangles in "Container" style) to enclose tiers — this makes the diagram read top-to-bottom as a request travels.

---

## 3. Tier 1 — User (External Actor)

**Shape:** Stick figure (shape library → **People → Male** or **Female**).

| Field | Value                  |
|-------|------------------------|
| Label | `User`                 |
| X, Y  | 760, 40                |
| W, H  | 60, 80                 |
| Fill  | `#F5F5F5` (neutral)    |

> Only one user is needed — requests are stateless and identical from the actor's perspective.

---

## 4. Tier 2 — API Edge

### 4.1 Outer container — "API Edge"

| Field       | Value                                                         |
|-------------|---------------------------------------------------------------|
| Label       | `API Edge`                                                    |
| Style       | `rounded=1;whiteSpace=wrap;html=1;fillColor=#DAE8FC;strokeColor=#6C8EBF;dashed=1;verticalAlign=top;fontStyle=1;fontSize=13;` |
| X, Y        | 80, 160                                                       |
| W, H        | 1440, 220                                                     |

### 4.2 FastAPI service shape

| Field       | Value                                                         |
|-------------|---------------------------------------------------------------|
| Label       | `**FastAPI**\nuvicorn · app.main:app\nREST + OpenAPI`         |
| Style       | `rounded=1;whiteSpace=wrap;html=1;fillColor=#1F77B4;fontColor=#FFFFFF;strokeColor=#0B3D66;fontStyle=1;fontSize=12;` |
| X, Y        | 680, 220                                                      |
| W, H        | 240, 90                                                       |
| Icon hint   | Stack of the FastAPI lightning-bolt logo (insert → image)      |

### 4.3 Endpoints reference block (small grey rectangle, right side)

| Field       | Value                                                                                       |
|-------------|---------------------------------------------------------------------------------------------|
| Label       | `**Endpoints**\nGET /health\nPOST /jobs/upload\nGET /jobs/{id}/status\nGET /jobs/{id}/results\nGET /jobs?status=&limit=&offset=` |
| Style       | `rounded=1;whiteSpace=wrap;html=1;fillColor=#F5F5F5;strokeColor=#666666;align=left;fontSize=10;` |
| X, Y        | 1020, 200                                                                                  |
| W, H        | 460, 140                                                                                   |

---

## 5. Tier 3 — Async Worker + Pipeline

### 5.1 Outer container — "Async Worker (Celery)"

| Field       | Value                                                          |
|-------------|-----------------------------------------------------------------|
| Label       | `Async Worker (Celery · prefork pool · concurrency=2)`          |
| Style       | `rounded=1;whiteSpace=wrap;html=1;fillColor=#D5E8D4;strokeColor=#82B366;dashed=1;verticalAlign=top;fontStyle=1;fontSize=13;` |
| X, Y        | 80, 400                                                         |
| W, H        | 1440, 320                                                      |

### 5.2 Pipeline stages — five sequential rectangles, left to right

All five shapes share style:
`rounded=1;whiteSpace=wrap;html=1;fillColor=#FFFFFF;strokeColor=#82B366;strokeWidth=2;fontSize=11;`

| # | Label                                                       | X, Y            | W, H     | Fill accent       |
|---|-------------------------------------------------------------|------------------|----------|-------------------|
| 1 | `**1. Cleaning**\nservices/cleaning.py\npandas · Decimal · date parse · dedup` | 120, 480 | 220, 80 | `#E1F5E1` |
| 2 | `**2. Anomaly Detection**\nservices/anomaly.py\n4 rules (median · one-off merchant · FAILED · currency)` | 380, 480 | 260, 100 | `#FFF2CC` |
| 3 | `**3. LLM Enrichment**\nservices/llm_client.py · enrich_batch\nGroq · llama-3.3-70b-versatile · batched + retried` | 680, 480 | 260, 100 | `#FCE4D6` |
| 4 | `**4. Summary Generation**\nservices/llm_client.py · generate_summary\nLLM narrative · local fallback` | 980, 480 | 260, 100 | `#F8CECC` |
| 5 | `**5. Persistence**\nbulk_insert_mappings · delete-then-insert\nidempotent re-runs` | 1280, 480 | 220, 80 | `#D9E1F2` |

### 5.3 External LLM box (right of Tier 3, outside the container)

| Field       | Value                                                          |
|-------------|-----------------------------------------------------------------|
| Label       | `**Groq LLM API**\nllama-3.3-70b-versatile\nHTTPS · JSON mode` |
| Style       | `rounded=1;whiteSpace=wrap;html=1;fillColor=#6A3D9A;fontColor=#FFFFFF;strokeColor=#3D1361;fontStyle=1;fontSize=12;shape=cloud;` |
| X, Y        | 1500, 540                                                       |
| W, H        | 180, 90                                                         |

> The `shape=cloud` flag turns it into the cloud shape — visually distinct as "external".

### 5.4 Worker entry-point rectangle (top of Tier 3 container)

| Field       | Value                                                                                     |
|-------------|-------------------------------------------------------------------------------------------|
| Label       | `**Celery Worker**\ntasks/pipeline.py · process_job\n`202 Accepted` → off-thread`         |
| Style       | `rounded=1;whiteSpace=wrap;html=1;fillColor=#2E7D32;fontColor=#FFFFFF;strokeColor=#1B5E20;fontStyle=1;fontSize=12;` |
| X, Y        | 680, 420                                                                                  |
| W, H        | 240, 50                                                                                   |

The four pipeline stages are linked *from* this rectangle (see Edges section).

---

## 6. Tier 4 — Persistence

### 6.1 Outer container — "PostgreSQL 16"

| Field       | Value                                                          |
|-------------|-----------------------------------------------------------------|
| Label       | `PostgreSQL 16 (SQLAlchemy 2.x · Alembic migrations)`           |
| Style       | `rounded=1;whiteSpace=wrap;html=1;fillColor=#E8D4F0;strokeColor=#9673A6;dashed=1;verticalAlign=top;fontStyle=1;fontSize=13;` |
| X, Y        | 80, 760                                                         |
| W, H        | 1100, 220                                                       |

### 6.2 Three table shapes (cylinder = "Entity Relation" in draw.io)

In draw.io the **Cylinder** shape is in the shape library under **Entity Relation → Cylinder**. Use the same base style and vary the fill.

Base style: `shape=cylinder3;whiteSpace=wrap;html=1;boundedLbl=1;backgroundOutline=1;size=15;fontSize=11;fontStyle=1;`

| Table           | Label                                                                                                                | X, Y         | W, H   | Fill         |
|-----------------|----------------------------------------------------------------------------------------------------------------------|---------------|--------|--------------|
| **jobs**        | `**jobs**\nid (UUID)\nfilename · file_path\nstatus enum (pending / processing / completed / failed)\nrow_count_raw · row_count_clean\ncreated_at · updated_at · completed_at` | 120, 800  | 280, 160 | `#D5E8D4` |
| **transactions**| `**transactions**\nid (UUID)\njob_id FK → jobs (CASCADE)\ntxn_id · date · merchant · amount · currency\nstatus · category · account_id · notes\nis_anomaly · anomaly_reason\nllm_category · llm_subcategory · llm_risk_level · llm_merchant_type · llm_confidence · llm_raw_response · llm_failed` | 470, 800 | 360, 160 | `#DAE8FC` |
| **job_summaries**| `**job_summaries**\nid (UUID)\njob_id FK UNIQUE → jobs (CASCADE)\ntotal_spend_inr · total_spend_usd\ntop_merchants (JSONB) · category_breakdown (JSONB)\nanomaly_count · narrative · ai_summary · risk_level\nllm_raw_response (JSONB)` | 900, 800 | 270, 160 | `#FFF2CC` |

---

## 7. Tier 5 — Cross-cutting Infrastructure

Two shapes placed *outside* the tier-3 container, alongside the API and worker.

### 7.1 Redis container

| Field       | Value                                                                                       |
|-------------|---------------------------------------------------------------------------------------------|
| Label       | `**Redis 7**\nBroker: redis://redis:6379/0\nResult backend: redis://redis:6379/1`           |
| Style       | `rounded=1;whiteSpace=wrap;html=1;fillColor=#A33B3B;fontColor=#FFFFFF;strokeColor=#6B1F1F;fontStyle=1;fontSize=12;` |
| X, Y        | 1320, 220                                                                                  |
| W, H        | 240, 90                                                                                     |

### 7.2 Uploaded CSVs container

| Field       | Value                                                                       |
|-------------|-----------------------------------------------------------------------------|
| Label       | `**uploaded_csvs/**\nDocker named volume\nshared between api + worker`       |
| Style       | `shape=folder;whiteSpace=wrap;html=1;fillColor=#FFE699;strokeColor=#BF9000;fontStyle=1;fontSize=12;` |
| X, Y        | 100, 220                                                                    |
| W, H        | 220, 90                                                                     |

> The `shape=folder` style is the standard yellow folder glyph — instantly recognisable.

### 7.3 External API container (right edge)

The Groq cloud shape from §5.3 lives here, fully outside any container.

---

## 8. Title Block

| Field | Value                                                                |
|-------|----------------------------------------------------------------------|
| Text  | `**AI-Powered Transaction Processing — System Architecture**`         |
| X, Y  | 80, 0                                                                |
| Style | `text;html=1;strokeColor=none;fillColor=none;align=left;verticalAlign=middle;whiteSpace=wrap;fontSize=18;fontStyle=1;fontColor=#1F3864;` |
| W, H  | 1100, 36                                                              |

Add a subtitle directly under the title:

| Field | Value                                                                                       |
|-------|---------------------------------------------------------------------------------------------|
| Text  | `Async ingestion · Rule-based + LLM anomaly detection · Idempotent Celery pipeline`         |
| X, Y  | 80, 30                                                                                      |
| Style | `text;html=1;strokeColor=none;fillColor=none;align=left;verticalAlign=middle;whiteSpace=wrap;fontSize=11;fontColor=#666666;` |
| W, H  | 1100, 22                                                                                    |

---

## 9. Edges (Arrows)

Every edge below uses orthogonal routing. In draw.io, after drawing an edge, open **Style** and append:

```
edgeStyle=orthogonalEdgeStyle;rounded=0;orthogonalLoop=1;jettySize=auto;html=1;exitX=0.5;exitY=1;exitDx=0;exitDy=0;entryX=0.5;entryY=0;entryDx=0;entryDy=0;endArrow=classic;endFill=1;strokeColor=#555555;strokeWidth=2;
```

Replace `strokeColor` per-edge as noted below.

| # | From                           | To                          | Label                                  | strokeColor | Notes                                                                 |
|---|--------------------------------|-----------------------------|----------------------------------------|--------------|----------------------------------------------------------------------|
| 1 | `User`                         | `FastAPI`                   | `1. POST /jobs/upload (multipart)`     | `#1F77B4`    | Heavy blue — the user-facing hop.                                    |
| 2 | `FastAPI`                      | `uploaded_csvs/`            | `2. write {job_id}.csv`                | `#BF9000`    |                                                                     |
| 3 | `FastAPI`                      | `PostgreSQL.jobs`           | `3. INSERT Job (status=pending)`       | `#6A3D9A`    | Purple for DB writes.                                                |
| 4 | `FastAPI`                      | `Redis`                     | `4. ENQUEUE process_job`               | `#A33B3B`    |                                                                     |
| 5 | `Redis`                        | `Celery Worker`             | `5. dispatch (JSON task)`             | `#A33B3B`    |                                                                     |
| 6 | `Celery Worker`                | `Cleaning`                  | `6a. clean_csv(file_path)`             | `#2E7D32`    |                                                                     |
| 7 | `Cleaning`                     | `Anomaly Detection`         | `6b. cleaned rows`                    | `#2E7D32`    |                                                                     |
| 8 | `Anomaly Detection`            | `LLM Enrichment`            | `6c. rows + is_anomaly flags`         | `#2E7D32`    |                                                                     |
| 9 | `LLM Enrichment`               | `Groq LLM API`              | `7. chat.completions (batch=20)`       | `#6A3D9A`    | Bidirectional: draw a return edge (10) for the response.             |
| 10 | `Groq LLM API`                 | `LLM Enrichment`            | `8. JSON {category, risk, confidence}`| `#6A3D9A`    |                                                                     |
| 11 | `LLM Enrichment`               | `Summary Generation`        | `6d. enriched rows`                   | `#2E7D32`    |                                                                     |
| 12 | `Summary Generation`           | `Groq LLM API`              | `9. summary request`                  | `#6A3D9A`    |                                                                     |
| 13 | `Groq LLM API`                 | `Summary Generation`        | `10. JSON {summary, ai_summary}`      | `#6A3D9A`    |                                                                     |
| 14 | `Summary Generation`           | `Persistence`               | `6e. rows + summary dict`             | `#2E7D32`    |                                                                     |
| 15 | `Persistence`                  | `PostgreSQL.transactions`   | `11. DELETE WHERE job_id + bulk_insert`| `#6A3D9A`    |                                                                     |
| 16 | `Persistence`                  | `PostgreSQL.job_summaries`  | `12. UPSERT summary`                  | `#6A3D9A`    |                                                                     |
| 17 | `Persistence`                  | `PostgreSQL.jobs`           | `13. UPDATE status=completed, completed_at=NOW()` | `#6A3D9A` | |
| 18 | `User`                         | `FastAPI`                   | `14. GET /jobs/{id}/status · /results` | `#1F77B4`    | Second user hop — *poll loop*.                                       |
| 19 | `FastAPI`                      | `PostgreSQL.jobs`           | `15. SELECT (status, summary)`         | `#6A3D9A`    |                                                                     |
| 20 | `FastAPI`                      | `PostgreSQL.transactions`   | `16. SELECT * WHERE job_id`           | `#6A3D9A`    |                                                                     |

### Bidirectional note for edges 9–10 and 12–13

In draw.io you can either:
- Draw two separate orthogonal edges (cleanest for a layered diagram), or
- Use a single edge with `startArrow=classic;startFill=1;endArrow=classic;endFill=1;` to get arrows on both ends.

**Recommendation:** Two separate arrows. The forward arrow carries the request, the return arrow carries the response — matches the numbered sequence.

### Edge sequence numbers

Add a small `1`, `2`, `3`... label near each edge midpoint:
1. Select the edge.
2. In the right panel **Style** tab, scroll to find the **Label** field — or click the label text directly.
3. Set the label text to the `Label` column value from the table above.
4. Style: `fontSize=10;fontColor=#333333;align=center;verticalAlign=middle;`

---

## 10. Colour Palette (Reference)

| Use                         | Hex       | Applies to                                     |
|-----------------------------|-----------|-------------------------------------------------|
| User / API request          | `#1F77B4` | User ↔ FastAPI edges                             |
| Celery worker / pipeline    | `#2E7D32` | Worker box + intra-pipeline edges                |
| Database                    | `#6A3D9A` | All DB-related edges                             |
| Redis / broker              | `#A33B3B` | Redis box + broker edges                          |
| File system                 | `#BF9000` | uploaded_csvs folder + write edges               |
| External LLM                | `#6A3D9A` | Groq cloud box + LLM edges                        |
| Container backgrounds        | `#DAE8FC`, `#D5E8D4`, `#E8D4F0` | Tier backgrounds          |
| Container borders            | `#6C8EBF`, `#82B366`, `#9673A6` | Tier outlines            |

---

## 11. Recreation Checklist (Under 10 Minutes)

| Step | Action                                                                              | Time  |
|------|--------------------------------------------------------------------------------------|-------|
| 1    | New blank diagram, set page size 1600×1100, enable grid                               | 30 s  |
| 2    | Place title + subtitle text blocks                                                    | 30 s  |
| 3    | Draw four tier containers (API Edge, Async Worker, PostgreSQL, plus two lone shapes)  | 90 s  |
| 4    | Insert User stick figure at top                                                       | 15 s  |
| 5    | Insert FastAPI rectangle + endpoints block                                            | 60 s  |
| 6    | Insert Redis box, uploaded_csvs folder, Celery worker entry rectangle                 | 60 s  |
| 7    | Insert five pipeline stages inside the worker container                               | 90 s  |
| 8    | Insert Groq LLM cloud shape                                                           | 15 s  |
| 9    | Insert three PostgreSQL cylinder tables                                               | 90 s  |
| 10   | Draw all 20 edges, add numeric labels                                                 | 180 s |
| 11   | Apply colours per §10 palette, set shadows, tidy spacing                              | 60 s  |
| 12   | Export as **File → Export As → PNG @ 2×** *and* **PDF**                              | 30 s  |

**Total: ~10 minutes** for a reviewer-ready diagram.

---

## 12. Optional Polish

- **Legend block** in the bottom-right corner — small rectangle listing the colour palette (paste from §10 as four colour swatches + labels).
- **Footer text** at y=1080: `Source: Anjali330/AI-Powered-Transaction-Processing · docker compose up · OpenAPI at /docs`.
- **Snap to grid** while drawing — keeps every shape aligned with the container edges.
- **Group → Convert to Container** — select every shape inside the Async Worker tier and convert it into a true container so they move together.

---

## 13. Export Recommendations for Submission

1. **PNG @ 2×** — for embedding into the README (GitHub renders it crisply).
2. **PDF** — for portfolio submission and printing.
3. **Editable `.drawio`** — include the source file in the repo under `docs/architecture.drawio` so reviewers can edit it.

Add the rendered PNG to the README with:

```markdown
![System Architecture](docs/architecture.png)
```

placed just under the title block.
