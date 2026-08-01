"""
StudyMate AI - An Accessible Study & Notes Companion
------------------------------------------------------
Season of AI 2.0 - Final Capstone Project

Problem it solves:
  Students often photograph handwritten/printed notes, textbook pages, or
  whiteboards but never revisit them because the content isn't searchable,
  summarized, or easy to revise on the go. Visually-impaired or dyslexic
  students also struggle to consume dense written notes.

  StudyMate AI turns any photo of notes into:
    1. Clean extracted text            (Azure AI Vision - OCR/Read)
    2. Key phrases + detected language (Azure AI Language)
    3. A short abstractive summary     (Azure OpenAI)
    4. A searchable, semantic note library (Azure AI Search)
    5. An audio version you can listen to (Azure AI Speech - TTS)
    6. A voice-driven Q&A chatbot over your own notes (Azure AI Speech STT
       + Azure AI Search + Azure OpenAI - Retrieval Augmented Generation)

Azure AI services used (5, well above the 3-service minimum):
  - Azure AI Vision      -> OCR text extraction from note images
  - Azure AI Language    -> key phrase extraction + language detection
  - Azure OpenAI         -> abstractive summarization + RAG chat answers
  - Azure AI Search      -> semantic search / retrieval over stored notes
  - Azure AI Speech      -> text-to-speech (listen to notes) and
                             speech-to-text (ask questions by voice)
"""

import os
import io
import uuid
import datetime
import tempfile

from flask import Flask, request, jsonify, render_template, send_file
from dotenv import load_dotenv

load_dotenv()

# ---- Azure SDKs -----------------------------------------------------------
from azure.core.credentials import AzureKeyCredential
from azure.ai.vision.imageanalysis import ImageAnalysisClient
from azure.ai.vision.imageanalysis.models import VisualFeatures

from azure.ai.textanalytics import TextAnalyticsClient

from azure.search.documents import SearchClient
from azure.search.documents.indexes import SearchIndexClient
from azure.search.documents.indexes.models import (
    SearchIndex,
    SimpleField,
    SearchableField,
    SearchFieldDataType,
    SemanticConfiguration,
    SemanticSearch,
    SemanticPrioritizedFields,
    SemanticField,
)
from azure.search.documents.models import QueryType

import azure.cognitiveservices.speech as speechsdk

from openai import AzureOpenAI

# ---- Config -----------------------------------------------------------
VISION_ENDPOINT = os.getenv("VISION_ENDPOINT")
VISION_KEY = os.getenv("VISION_KEY")

LANGUAGE_ENDPOINT = os.getenv("LANGUAGE_ENDPOINT")
LANGUAGE_KEY = os.getenv("LANGUAGE_KEY")

AOAI_ENDPOINT = os.getenv("AZURE_OPENAI_ENDPOINT")
AOAI_KEY = os.getenv("AZURE_OPENAI_KEY")
AOAI_DEPLOYMENT = os.getenv("AZURE_OPENAI_DEPLOYMENT")
AOAI_API_VERSION = os.getenv("AZURE_OPENAI_API_VERSION", "2024-12-01-preview")

SEARCH_ENDPOINT = os.getenv("AZURE_SEARCH_ENDPOINT")
SEARCH_KEY = os.getenv("AZURE_SEARCH_KEY")
SEARCH_INDEX = os.getenv("AZURE_SEARCH_INDEX", "studymate-notes")
SEMANTIC_CONFIG_NAME = "studymate-semantic-config"

SPEECH_KEY = os.getenv("SPEECH_KEY")
SPEECH_REGION = os.getenv("SPEECH_REGION")

app = Flask(__name__)
app.secret_key = os.getenv("FLASK_SECRET_KEY", "dev-secret")
app.config["MAX_CONTENT_LENGTH"] = 15 * 1024 * 1024  # 15 MB upload cap


# ---- Lazy Azure client factories ------------------------------------------
def vision_client():
    if not VISION_ENDPOINT or not VISION_KEY:
        raise RuntimeError("Azure AI Vision is not configured (VISION_ENDPOINT/VISION_KEY).")
    return ImageAnalysisClient(endpoint=VISION_ENDPOINT, credential=AzureKeyCredential(VISION_KEY))


def language_client():
    if not LANGUAGE_ENDPOINT or not LANGUAGE_KEY:
        raise RuntimeError("Azure AI Language is not configured (LANGUAGE_ENDPOINT/LANGUAGE_KEY).")
    return TextAnalyticsClient(endpoint=LANGUAGE_ENDPOINT, credential=AzureKeyCredential(LANGUAGE_KEY))


def openai_client():
    if not AOAI_ENDPOINT or not AOAI_KEY or not AOAI_DEPLOYMENT:
        raise RuntimeError("Azure OpenAI is not configured (AZURE_OPENAI_* env vars).")
    return AzureOpenAI(azure_endpoint=AOAI_ENDPOINT, api_key=AOAI_KEY, api_version=AOAI_API_VERSION)


def search_client():
    if not SEARCH_ENDPOINT or not SEARCH_KEY:
        raise RuntimeError("Azure AI Search is not configured (AZURE_SEARCH_* env vars).")
    return SearchClient(endpoint=SEARCH_ENDPOINT, index_name=SEARCH_INDEX, credential=AzureKeyCredential(SEARCH_KEY))


def search_index_client():
    return SearchIndexClient(endpoint=SEARCH_ENDPOINT, credential=AzureKeyCredential(SEARCH_KEY))


# ---- Search index bootstrap -------------------------------------------
def ensure_search_index():
    """Create the Azure AI Search index if it doesn't already exist."""
    idx_client = search_index_client()
    existing = [i.name for i in idx_client.list_indexes()]
    if SEARCH_INDEX in existing:
        return

    fields = [
        SimpleField(name="id", type=SearchFieldDataType.String, key=True),
        SearchableField(name="filename", type=SearchFieldDataType.String),
        SearchableField(name="content", type=SearchFieldDataType.String, analyzer_name="en.microsoft"),
        SearchableField(name="summary", type=SearchFieldDataType.String, analyzer_name="en.microsoft"),
        SearchableField(name="keyphrases",type=SearchFieldDataType.String,),
        SimpleField(name="language", type=SearchFieldDataType.String, filterable=True),
        SimpleField(name="uploaded_at", type=SearchFieldDataType.DateTimeOffset, sortable=True, filterable=True),
    ]

    semantic_config = SemanticConfiguration(
        name=SEMANTIC_CONFIG_NAME,
        prioritized_fields=SemanticPrioritizedFields(
            title_field=SemanticField(field_name="filename"),
            content_fields=[SemanticField(field_name="content"), SemanticField(field_name="summary")],
            keywords_fields=[SemanticField(field_name="keyphrases")],
        ),
    )
    semantic_search = SemanticSearch(configurations=[semantic_config])

    index = SearchIndex(name=SEARCH_INDEX, fields=fields, semantic_search=semantic_search)
    idx_client.create_index(index)


# ---- Routes: pages ------------------------------------------------------
@app.route("/")
def home():
    return render_template("index.html")


@app.route("/api/health")
def health():
    return jsonify(
        {
            "status": "ok",
            "vision_configured": bool(VISION_ENDPOINT and VISION_KEY),
            "language_configured": bool(LANGUAGE_ENDPOINT and LANGUAGE_KEY),
            "openai_configured": bool(AOAI_ENDPOINT and AOAI_KEY and AOAI_DEPLOYMENT),
            "search_configured": bool(SEARCH_ENDPOINT and SEARCH_KEY),
            "speech_configured": bool(SPEECH_KEY and SPEECH_REGION),
        }
    )


# ---- Route: upload a note image -> OCR -> analyze -> summarize -> index --
@app.route("/api/upload", methods=["POST"])
def upload_note():
    if "file" not in request.files:
        return jsonify({"error": "No file uploaded. Attach an image under field name 'file'."}), 400

    file = request.files["file"]
    if file.filename == "":
        return jsonify({"error": "Empty filename."}), 400

    image_bytes = file.read()

    try:
        # 1) OCR the image using Azure AI Vision
        vclient = vision_client()
        result = vclient.analyze(image_data=image_bytes, visual_features=[VisualFeatures.READ])

        extracted_lines = []
        if result.read is not None:
            for block in result.read.blocks:
                for line in block.lines:
                    extracted_lines.append(line.text)
        extracted_text = "\n".join(extracted_lines).strip()

        if not extracted_text:
            return jsonify({"error": "No readable text was found in this image."}), 422

        # 2) Language analysis: detect language + extract key phrases
        lclient = language_client()
        lang_result = lclient.detect_language(documents=[extracted_text])[0]
        detected_language = lang_result.primary_language.iso6391_name if not lang_result.is_error else "en"

        kp_result = lclient.extract_key_phrases(documents=[extracted_text])[0]
        key_phrases = kp_result.key_phrases if not kp_result.is_error else []

        # 3) Abstractive summary via Azure OpenAI
        summary = generate_summary(extracted_text)

        # 4) Index into Azure AI Search for later retrieval
        note_id = str(uuid.uuid4())
        doc = {
            "id": note_id,
            "filename": file.filename,
            "content": extracted_text,
            "summary": summary,
            "keyphrases": ", ".join(key_phrases),
            "language": detected_language,
            "uploaded_at": datetime.datetime.utcnow().isoformat() + "Z",
        }
        ensure_search_index()
        search_client().upload_documents(documents=[doc])

        return jsonify(
            {
                "id": note_id,
                "filename": file.filename,
                "extracted_text": extracted_text,
                "summary": summary,
                "key_phrases": key_phrases,
                "language": detected_language,
            }
        )

    except RuntimeError as cfg_err:
        return jsonify({"error": str(cfg_err)}), 500
    except Exception as e:  # noqa: BLE001
        return jsonify({"error": f"Upload processing failed: {e}"}), 500


def generate_summary(text: str) -> str:
    """Use Azure OpenAI to produce a short study-friendly summary."""
    client = openai_client()
    response = client.chat.completions.create(
        model=AOAI_DEPLOYMENT,
        messages=[
            {
                "role": "system",
                "content": (
                    "You are a study assistant. Summarize the student's notes into "
                    "5 or fewer concise bullet points a student can revise from quickly. "
                    "Keep technical terms intact. Do not invent facts not present in the text."
                ),
            },
            {"role": "user", "content": text},
        ],
        max_tokens=350,
        temperature=0.3,
    )
    return response.choices[0].message.content.strip()


# ---- Route: list stored notes -------------------------------------------
@app.route("/api/notes", methods=["GET"])
def list_notes():
    try:
        ensure_search_index()
        results = search_client().search(
            search_text="*",
            order_by=["uploaded_at desc"],
            top=50,
            select=["id", "filename", "summary", "keyphrases", "language", "uploaded_at"],
        )
        notes = [dict(r) for r in results]
        return jsonify({"notes": notes})
    except RuntimeError as cfg_err:
        return jsonify({"error": str(cfg_err)}), 500
    except Exception as e:  # noqa: BLE001
        return jsonify({"error": f"Could not list notes: {e}"}), 500


# ---- Route: semantic search across notes ---------------------------------
@app.route("/api/search", methods=["POST"])
def semantic_search():
    payload = request.get_json(silent=True) or {}
    query = (payload.get("query") or "").strip()
    if not query:
        return jsonify({"error": "Provide a 'query' string."}), 400

    try:
        ensure_search_index()
        results = search_client().search(
            search_text=query,
            query_type=QueryType.SEMANTIC,
            semantic_configuration_name=SEMANTIC_CONFIG_NAME,
            select=["id", "filename", "content", "summary", "keyphrases", "uploaded_at"],
            top=5,
        )
        hits = []
        for r in results:
            hits.append(
                {
                    "id": r["id"],
                    "filename": r["filename"],
                    "summary": r.get("summary"),
                    "keyphrases": r.get("keyphrases"),
                    "uploaded_at": r.get("uploaded_at"),
                    "reranker_score": r.get("@search.reranker_score"),
                }
            )
        return jsonify({"results": hits})
    except RuntimeError as cfg_err:
        return jsonify({"error": str(cfg_err)}), 500
    except Exception as e:  # noqa: BLE001
        return jsonify({"error": f"Search failed: {e}"}), 500


# ---- Route: RAG chat - "Ask my notes" ------------------------------------
@app.route("/api/ask", methods=["POST"])
def ask_notes():
    payload = request.get_json(silent=True) or {}
    question = (payload.get("question") or "").strip()
    if not question:
        return jsonify({"error": "Provide a 'question' string."}), 400

    try:
        ensure_search_index()
        # Retrieve the most relevant notes for this question
        results = search_client().search(
            search_text=question,
            query_type=QueryType.SEMANTIC,
            semantic_configuration_name=SEMANTIC_CONFIG_NAME,
            select=["filename", "content", "summary"],
            top=3,
        )
        context_chunks = []
        sources = []
        for r in results:
            context_chunks.append(f"Source: {r['filename']}\n{r['content']}")
            sources.append(r["filename"])

        if not context_chunks:
            return jsonify(
                {
                    "answer": "I couldn't find anything relevant in your uploaded notes yet. "
                    "Try uploading some notes first, or rephrase your question.",
                    "sources": [],
                }
            )

        context = "\n\n---\n\n".join(context_chunks)

        client = openai_client()
        response = client.chat.completions.create(
            model=AOAI_DEPLOYMENT,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You are StudyMate, a helpful study assistant. Answer the student's "
                        "question using ONLY the provided note excerpts. If the answer isn't "
                        "in the notes, say so honestly rather than guessing. Keep answers concise."
                    ),
                },
                {
                    "role": "user",
                    "content": f"Notes:\n{context}\n\nQuestion: {question}",
                },
            ],
            max_tokens=400,
            temperature=0.2,
        )
        answer = response.choices[0].message.content.strip()

        return jsonify({"answer": answer, "sources": sorted(set(sources))})

    except RuntimeError as cfg_err:
        return jsonify({"error": str(cfg_err)}), 500
    except Exception as e:  # noqa: BLE001
        return jsonify({"error": f"Ask failed: {e}"}), 500


# ---- Route: text-to-speech (listen to notes / summaries) ------------------
@app.route("/api/tts", methods=["POST"])
def text_to_speech():
    payload = request.get_json(silent=True) or {}
    text = (payload.get("text") or "").strip()
    voice = payload.get("voice", "en-US-JennyNeural")
    if not text:
        return jsonify({"error": "Provide 'text' to synthesize."}), 400
    if not SPEECH_KEY or not SPEECH_REGION:
        return jsonify({"error": "Azure AI Speech is not configured (SPEECH_KEY/SPEECH_REGION)."}), 500

    try:
        speech_config = speechsdk.SpeechConfig(subscription=SPEECH_KEY, region=SPEECH_REGION)
        speech_config.speech_synthesis_voice_name = voice
        speech_config.set_speech_synthesis_output_format(
            speechsdk.SpeechSynthesisOutputFormat.Riff16Khz16BitMonoPcm
        )

        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
            tmp_path = tmp.name

        audio_config = speechsdk.audio.AudioOutputConfig(filename=tmp_path)
        synthesizer = speechsdk.SpeechSynthesizer(speech_config=speech_config, audio_config=audio_config)
        result = synthesizer.speak_text_async(text).get()

        if result.reason != speechsdk.ResultReason.SynthesizingAudioCompleted:
            return jsonify({"error": f"Speech synthesis failed: {result.reason}"}), 500

        return send_file(tmp_path, mimetype="audio/wav", as_attachment=False, download_name="studymate_audio.wav")

    except Exception as e:  # noqa: BLE001
        return jsonify({"error": f"Text-to-speech failed: {e}"}), 500


# ---- Route: speech-to-text (ask questions by voice) ------------------------
@app.route("/api/stt", methods=["POST"])
def speech_to_text():
    if "audio" not in request.files:
        return jsonify({"error": "Attach an audio file under field name 'audio' (wav, 16kHz mono recommended)."}), 400
    if not SPEECH_KEY or not SPEECH_REGION:
        return jsonify({"error": "Azure AI Speech is not configured (SPEECH_KEY/SPEECH_REGION)."}), 500

    audio_file = request.files["audio"]

    try:
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
            audio_file.save(tmp.name)
            tmp_path = tmp.name

        speech_config = speechsdk.SpeechConfig(subscription=SPEECH_KEY, region=SPEECH_REGION)
        audio_config = speechsdk.audio.AudioConfig(filename=tmp_path)
        recognizer = speechsdk.SpeechRecognizer(speech_config=speech_config, audio_config=audio_config)

        result = recognizer.recognize_once()

        if result.reason == speechsdk.ResultReason.RecognizedSpeech:
            return jsonify({"text": result.text})
        elif result.reason == speechsdk.ResultReason.NoMatch:
            return jsonify({"error": "Could not understand the audio."}), 422
        else:
            return jsonify({"error": f"Speech recognition failed: {result.reason}"}), 500

    except Exception as e:  # noqa: BLE001
        return jsonify({"error": f"Speech-to-text failed: {e}"}), 500


if __name__ == "__main__":
    port = int(os.getenv("PORT", 8000))
    app.run(host="0.0.0.0", port=port, debug=True)
