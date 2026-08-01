# StudyMate AI 🎓
### An accessible study companion — Season of AI 2.0 Capstone Project

> Snap a photo of your notes. StudyMate reads it, summarizes it, files it away for
> instant search, and reads it back to you — by text or by voice.

---

## 1. The problem

Students photograph notes, whiteboards, and textbook pages constantly — and then
almost never revisit them, because the photos aren't searchable, aren't
summarized, and are hard to consume for anyone who is visually impaired, dyslexic,
or just revising on the go between classes.

**StudyMate AI** turns a pile of note photos into a searchable, listenable,
question-answerable study library.

## 2. What it does

| Step | Feature | What happens |
|---|---|---|
| 1 | **Capture** | Upload a photo of handwritten/printed notes |
| 2 | **Extract** | OCR pulls out the raw text |
| 3 | **Understand** | Key phrases + language are detected; an AI-generated bullet summary is produced |
| 4 | **File** | The note is indexed into a searchable library |
| 5 | **Retrieve** | Search your whole library by meaning, not just keywords |
| 6 | **Converse** | Ask questions about your notes in a chat — answers are grounded only in what you've actually uploaded (RAG) |
| 7 | **Listen** | Any summary or answer can be read aloud; you can also ask questions by voice |

## 3. Azure AI services used (5 — exceeds the 3-service minimum)

| Service | Role in the app |
|---|---|
| **Azure AI Vision** | OCR (`Read`) extracts raw text from the uploaded note image |
| **Azure AI Language** | Detects the note's language and extracts key phrases used as searchable tags |
| **Azure OpenAI** | Generates the abstractive bullet-point summary, and powers the RAG chat answers in "Ask" |
| **Azure AI Search** | Stores every note as a searchable document; semantic search retrieves the most relevant notes for a library search or a chat question |
| **Azure AI Speech** | Text-to-speech reads summaries/answers aloud; speech-to-text lets you ask questions by voice |

## 4. Architecture

```
                     ┌────────────────────────┐
   Browser  ───────▶ │   Flask app (app.py)   │
  (index.html + JS)  │                        │
                     └───────────┬────────────┘
                                 │
        ┌────────────────┬──────┼───────┬─────────────────┐
        ▼                ▼      ▼       ▼                 ▼
  Azure AI Vision   Azure AI  Azure    Azure AI        Azure AI
  (OCR / Read)      Language  OpenAI   Search           Speech
                     (key     (summary  (semantic        (TTS / STT)
                     phrases, + RAG     index of
                     lang id) answers)  notes)
```

Flow for an upload: **image → Vision (OCR text) → Language (key phrases/lang) →
OpenAI (summary) → Search (index the note)**

Flow for "Ask": **question → Search (retrieve relevant notes) → OpenAI (answer
grounded in retrieved text) → response (+ optional Speech playback)**

## 5. Project structure

```
studymate-ai/
├── app.py                  # Flask backend — all 5 Azure service integrations
├── requirements.txt
├── .env.example             # copy to .env and fill in your keys
├── Dockerfile
├── templates/
│   └── index.html
├── static/
│   ├── css/style.css
│   └── js/app.js
└── README.md
```

## 6. Local setup

### Prerequisites
- Python 3.10+
- Azure resources (can all be created on the free/low-cost tiers):
  - Azure AI Vision resource
  - Azure AI Language resource
  - Azure OpenAI resource with a chat-completion model deployed (e.g. `gpt-4o-mini`)
  - Azure AI Search resource
  - Azure AI Speech resource

### Steps

```bash
git clone <your-repo-url>
cd studymate-ai

python -m venv .venv
source .venv/bin/activate      # Windows: .venv\Scripts\activate

pip install -r requirements.txt

cp .env.example .env
# open .env and paste in your Azure endpoints/keys

python app.py
```

The app runs at **http://localhost:8000**.

> The Azure AI Search index is created automatically on first run — you do not
> need to pre-create it in the Azure portal.

## 7. Deployment

### Option A — Azure App Service (recommended, keeps everything in Azure)

```bash
az login

az group create --name studymate-rg --location eastus

az appservice plan create --name studymate-plan --resource-group studymate-rg \
  --sku B1 --is-linux

az webapp create --name <your-unique-app-name> --resource-group studymate-rg \
  --plan studymate-plan --runtime "PYTHON:3.11"

# Push your env vars as App Settings (repeat for every var in .env.example)
az webapp config appsettings set --name <your-unique-app-name> \
  --resource-group studymate-rg --settings \
  VISION_ENDPOINT="..." VISION_KEY="..." \
  LANGUAGE_ENDPOINT="..." LANGUAGE_KEY="..." \
  AZURE_OPENAI_ENDPOINT="..." AZURE_OPENAI_KEY="..." \
  AZURE_OPENAI_DEPLOYMENT="..." AZURE_OPENAI_API_VERSION="2024-12-01-preview" \
  AZURE_SEARCH_ENDPOINT="..." AZURE_SEARCH_KEY="..." AZURE_SEARCH_INDEX="studymate-notes" \
  SPEECH_KEY="..." SPEECH_REGION="..."

az webapp config set --name <your-unique-app-name> --resource-group studymate-rg \
  --startup-file "gunicorn --bind 0.0.0.0:8000 app:app"

# Deploy from your local folder
az webapp up --name <your-unique-app-name> --resource-group studymate-rg --runtime "PYTHON:3.11"
```

Your app will be live at `https://<your-unique-app-name>.azurewebsites.net`.

### Option B — Any container host (Render, Railway, Azure Container Apps, Fly.io)

The included `Dockerfile` runs out of the box:

```bash
docker build -t studymate-ai .
docker run -p 8000:8000 --env-file .env studymate-ai
```

Push the image to your host of choice and set the same environment variables
from `.env.example` in its dashboard.

## 8. Known limitations / next steps

- Speech-to-text expects a browser-recorded clip; some browsers record in
  WebM/Opus rather than PCM WAV, which the Speech SDK's file-based recognizer
  expects most reliably — for a production build, add a server-side transcode
  step (e.g. `ffmpeg`) or switch to the Speech SDK's push-stream API for
  broader format support.
- The note library currently has no per-user accounts — all notes share one
  index, which is fine for a demo/single-user deployment but would need
  auth + per-user filtering for multi-user use.
- Summaries are capped at ~350 tokens to control cost; long lecture transcripts
  would benefit from chunking before summarization.

## 9. Submission checklist

- [x] Uses 3+ Azure AI services (uses 5: Vision, Language, OpenAI, Search, Speech)
- [ ] Deployed to a publicly accessible URL — add your link here: `___________`
- [ ] 2-minute demo video — add your link here: `___________`
- [ ] GitHub repository — add your link here: `___________`

---

Built for the **Season of AI 2.0** final capstone.
