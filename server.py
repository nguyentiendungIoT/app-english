import os
import json
import uuid
import glob
from typing import Optional, List

from fastapi import FastAPI, HTTPException, Request, BackgroundTasks
from fastapi.responses import HTMLResponse, JSONResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from modules.tts_engine import TTSEngine
from modules.ai_agent import AIAgent

app = FastAPI(title="App English - Web Version")

# Ensure static and audio output directories exist
os.makedirs("web", exist_ok=True)
os.makedirs("audio_output", exist_ok=True)

# Mount the static directory to serve MP3 files
app.mount("/audio", StaticFiles(directory="audio_output"), name="audio")

# We don't mount the whole /web directory right away to "/" because we want to serve index.html directly on "/"
app.mount("/static", StaticFiles(directory="web"), name="web_static")

# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------


# Read from environment variable (set on Render/hosting platform)
# Fallback to local key only for development
GEMINI_API_KEY = os.environ.get(
    "GEMINI_API_KEY", "AIzaSyD9wQA1kk9nMOcNoxbm0zYe0ly2DBou08U"
)


class NewsRequest(BaseModel):
    topic: str
    model_id: str


class SynthesizeRequest(BaseModel):
    text: str
    voice: str = "en-US-GuyNeural"
    rate: str = "+0%"


class WordBoundaryData(BaseModel):
    word: str
    start_time_ms: int
    end_time_ms: int
    text_index_start: int
    text_index_end: int


class SynthesizeResponse(BaseModel):
    audio_url: str
    duration_ms: int
    boundaries: List[WordBoundaryData]


# ---------------------------------------------------------------------------
# Web Routes
# ---------------------------------------------------------------------------


@app.get("/", response_class=HTMLResponse)
async def serve_index():
    index_path = os.path.join("web", "index.html")
    if not os.path.exists(index_path):
        return HTMLResponse(
            "<h1>Error: web/index.html not found.</h1>Please create the frontend.",
            status_code=404,
        )
    with open(index_path, "r", encoding="utf-8") as f:
        return f.read()


# ---------------------------------------------------------------------------
# API Routes
# ---------------------------------------------------------------------------


@app.post("/api/generate_news")
async def generate_news(req: NewsRequest):
    try:
        agent = AIAgent(api_key=GEMINI_API_KEY)
        article_text = agent.generate_news_article(req.topic, model_id=req.model_id)
        return JSONResponse(content={"article": article_text})
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Failed to generate news: {str(e)}"
        )


@app.post("/api/synthesize", response_model=SynthesizeResponse)
async def synthesize_text(req: SynthesizeRequest, background_tasks: BackgroundTasks):
    text = req.text.strip()
    if not text:
        raise HTTPException(status_code=400, detail="Text cannot be empty")

    try:
        if req.voice.startswith("gemini-"):
            # Gemini TTS Mode
            from google import genai
            from google.genai import types
            import uuid

            import wave

            if not GEMINI_API_KEY:
                raise HTTPException(
                    status_code=400, detail="API key is required for Gemini TTS."
                )

            client = genai.Client(api_key=GEMINI_API_KEY)
            audio_filename = f"tts_gemini_output_{uuid.uuid4().hex}.wav"
            audio_path = os.path.join("audio_output", audio_filename)

            # Using the native audio model
            response = client.models.generate_content(
                model="gemini-2.5-flash-preview-tts",
                contents=text,
                config=types.GenerateContentConfig(
                    response_modalities=["AUDIO"],
                    speech_config=types.SpeechConfig(
                        voice_config=types.VoiceConfig(
                            prebuilt_voice_config=types.PrebuiltVoiceConfig(
                                voice_name="Aoede",  # Default premium voice
                            )
                        )
                    ),
                ),
            )

            # Extract audio bytes
            audio_bytes = None
            for part in response.candidates[0].content.parts:
                if part.inline_data:
                    audio_bytes = part.inline_data.data
                    break

            if not audio_bytes:
                raise ValueError("Model did not return audio data.")

            with wave.open(audio_path, "wb") as f:
                f.setnchannels(1)  # mono
                f.setsampwidth(2)  # 16-bit
                f.setframerate(24000)  # 24kHz
                f.writeframes(audio_bytes)

            audio_url = f"/audio/{audio_filename}"
            boundaries = []  # No word boundaries for Gemini TTS yet
            duration_ms = 0

        else:
            # edge-tts Mode
            engine = TTSEngine(
                voice=req.voice, rate=req.rate, volume="+0%", output_dir="audio_output"
            )
            result = await engine._synthesize_async(text)
            audio_filename = os.path.basename(result.audio_path)
            audio_url = f"/audio/{audio_filename}"
            boundaries = [
                WordBoundaryData(
                    word=wb.word,
                    start_time_ms=wb.start_time_ms,
                    end_time_ms=wb.end_time_ms,
                    text_index_start=wb.text_index_start,
                    text_index_end=wb.text_index_end,
                )
                for wb in result.boundaries
            ]
            duration_ms = result.duration_ms

        # Schedule cleanup
        background_tasks.add_task(cleanup_old_audio_files)

        return SynthesizeResponse(
            audio_url=audio_url,
            duration_ms=duration_ms,
            boundaries=boundaries,
        )

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"TTS error: {str(e)}")


# ---------------------------------------------------------------------------
# Cleanup Task
# ---------------------------------------------------------------------------


def cleanup_old_audio_files(max_files=20):
    """
    Keep the audio_output directory from growing infinitely.
    Keeps only the most recent N files.
    """
    files = glob.glob(os.path.join("audio_output", "*.*"))
    files.sort(key=os.path.getmtime, reverse=True)

    # Delete older files
    for f in files[max_files:]:
        try:
            os.remove(f)
        except OSError:
            pass


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("server:app", host="0.0.0.0", port=5000, reload=False)
