# ENU Көмек

Құжаттарға негізделген студент көмекшісі / помощник студента по документам ЕНУ.

Local MVP for «ЖИ-әзірлемелер» 2026. Chat with a local Qwen model and search university PDF/DOCX sources in Kazakh or Russian,
inspect exact excerpts and open the original page. The interface starts in Kazakh.

## Run on macOS

Requires Python 3.11+ and Poppler (recommended for PDF text extraction and PNG previews).

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
# If Poppler is missing: brew install poppler
.venv/bin/python server.py
```

Open **http://127.0.0.1:8777**. In the prepared local workspace, dependencies are already installed.
Double-click `Запустить ENU Көмек.command` to start, or run `bash "Запустить ENU Көмек.command"`.
Use `--port 8778` if the default port is occupied. Stop with Ctrl+C.

Place authorized PDF/DOCX files in `enu-data/documents/`, or add them through Documents → Add.
The existing local workspace also reads source files directly from the project root.
The GitHub repository intentionally contains NO university source documents or extracted text.
A fresh clone starts with an empty library until you add sources.

## What works

- Kazakh / Russian interface; keyboard and mobile layouts.
- PDF and DOCX ingestion, SHA-256 deduplication, extraction cache.
- Character TF-IDF + latent semantic analysis (TruncatedSVD), cosine ranking and evidence gates.
- Small explicit Kazakh/Russian concept dictionary; it is not automatic translation.
- Exact source excerpts with PDF page references / DOCX section references.
- Source library, filters, upload, reindex, metadata export, PDF page previews.
- Student-oriented defaults; optional staff documents in the library.
- History, saved answers and feedback in browser localStorage.
- Explicit refusal to answer when no sufficiently relevant excerpts are found.

## Chat modes

- **Документы ЕНУ / ЕҰУ құжаттары**: retrieves source evidence with TF-IDF + LSA, then local Qwen 2.5 3B composes a cited answer and optional steps (RAG). Source excerpts remain in their original language. Missing/invalid citations cause fallback to excerpts. Citation validation does not prove factual entailment.
- **Свободный разговор / Еркін әңгіме**: general conversation and study explanations through the local model. These answers are explicitly labelled as not checked against ENU documents.
- Questions/answers appear in a conversation. Short follow-up retrieval questions use previous user questions as topic context. This is limited context handling, not unrestricted long-term memory.
- Greetings/help work without an LLM. When Ollama is unavailable, document search still works and general chat shows a setup message.

Install [Ollama](https://ollama.com/) and run once:

```bash
ollama pull qwen2.5:3b
```

The launcher/server starts the installed Ollama runtime if necessary. It never downloads models automatically. Ollama requests go only to `127.0.0.1:11434`. No cloud API key is needed. Model responses may take tens of seconds on a laptop; timeout is 90 seconds.

## Architecture

```text
Local PDF / DOCX
    → extraction by page / section
    → overlapping source windows
    → TF-IDF + LSA index
Question + explicit bilingual expansion
    → hybrid ranking + relevance gates + role filter
    → local Qwen answer + cited steps + expandable original excerpts (or extractive fallback)
```

Python standard-library HTTP server, scikit-learn, pypdf. Buildless vanilla JS/CSS frontend.
Ollama runs locally. Optional Gemini sends questions to Google; retrieved document snippets require explicit opt-in. PDF extraction uses Poppler when available and pypdf as fallback.
PDF page preview requires `pdftoppm`; original download remains available without it.

## Tests

```bash
.venv/bin/python -m unittest discover -s tests -v
node --check web/app.js
.venv/bin/python scripts/evaluate.py
```

The evaluation command needs local university sources; generic unit/API tests work on a clean clone.
See [API contract](docs/API.md), [design contract](docs/DESIGN.md), and [demo guide](docs/DEMO.md).

## Scope and limits

This is a local single-user demonstration, not a production deployment. Files are only served on
loopback; host and origin checks reduce cross-site access. Role filtering is NOT access control.
In local Ollama mode, questions and documents stay on this computer. When a cloud provider is selected, questions and conversation context are sent to that provider; retrieved document fragments require separate opt-in. Browser history/saved answers persist until browser storage is cleared.
Source content is treated as data, not executable agent instructions.

Scanned PDFs without embedded text are marked `needs_ocr` and excluded from search. No dates or
validity are inferred from filenames. Documents need manual review for currency and reuse rights.
Retrieval can miss paraphrases and cannot guarantee correctness; inspect the original source.
No real SMART.ENU integration, student account connection, form submission or official ENU affiliation.

Before the competition: verify Kazakh wording with a fluent reviewer, review OCR text against originals,
expand the evaluation set, validate document currency, and measure usefulness with students. The local generative model can make mistakes; inspect the cited sources. General chat is not verified university guidance.

## OCR for scanned PDFs

`scripts/ocr_documents.py` explicitly processes documents marked `needs_ocr` using Tesseract + Poppler. Install Tesseract and place official `kaz.traineddata` and `rus.traineddata` in `enu-data/ocr-languages/`, then run `.venv/bin/python scripts/ocr_documents.py`. Originals remain unchanged. OCR flags are preserved in cached pages and document metadata; text needs manual review. Restart the server or reindex afterward.

For direct transcript-document questions the assistant can produce a short exact source quote instead of asking the model to paraphrase. Small-model Kazakh generation remains limited and requires human review.

## Gemini and model selection

Open **Модели и API** using the active-model button or sidebar. Choose Google Gemini, enter an API key, and select **Проверить и загрузить модели**. The available list comes from Google, supports search and may include unavailable/deprecated variants; text chat disables image/audio/specialized models. Select a text model and save. Ollama remains a separate selectable provider.

Keys live only in the server-side `.env` file (owner-only 0600; ignored by version control). API responses expose only `key_saved`, never the key. Blank input preserves the key, and a separate action removes it. Google uses the fixed official HTTPS endpoint and a key header, with redirects disabled. Do not publish `.env`. The app remains a loopback-only single-user MVP, not a multi-user credential vault.

General chat sends questions and prior user questions to Google when Gemini is selected. Retrieved source fragments are not sent unless **Разрешить отправку найденных фрагментов документов в Google** is checked. With this off, document retrieval and exact summaries remain available. Invalid keys, quotas, unavailable models and network errors are shown without exposing raw provider responses.

## OpenAI and Claude

The provider selector now includes **ChatGPT · OpenAI API** and **Claude · Anthropic API** alongside Gemini and local Ollama. Each cloud provider keeps a separate server-side key, model preference and document-sharing permission. Select the provider, enter its own API key, click the model-loading button, choose a text model and save. Saving or testing a new key does not change the active provider until you save the selection. Blank key fields preserve saved values; clearing affects only the selected provider.

OpenAI uses native `/v1/responses` with JSON schema output and `store: false`; Claude uses native `/v1/messages` with `output_config.format`. Model lists come from the respective official APIs. Missing keys show a setup message and never borrow another provider's credentials. Live OpenAI/Anthropic inference has not been verified without their keys; request construction and parsing have been checked with fixtures.

## Public demo on Render Free

See [Render deployment](docs/RENDER.md). The Dockerfile and render.yaml select a Free web service. Public visitors use isolated temporary workspaces and their own API keys; Ollama and the developer’s local document corpus are not available online. Free-tier restarts discard visitor files/settings. No paid disk or database is required.
