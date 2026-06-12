"""
transcribe.py — unified transcription layer with swappable backends.

Single entry point: transcribe_url(url) -> Optional[str]

BACKEND (set TRANSCRIPTION_BACKEND in .env):

  youtube_captions  [default, free, no setup]
    Uses YouTube's own auto-generated captions via youtube-transcript-api.
    Only works for YouTube URLs. Most accurate for YouTube content since it's
    the same transcript YouTube shows. Falls back to None (not an error) when
    a video has no captions.

  assemblyai        [free 100 hrs/month, best quality]
    AssemblyAI API. Accepts any public audio/video URL directly — no download
    needed. Best accuracy for Indian English and Hinglish code-switching.
    Speaker diarization (who said what) is available via config.
    Free tier: 100 hours/month, no expiry. Needs ASSEMBLYAI_API_KEY.

  openai            [paid, $0.006/min, whisper-large-v3 quality]
    OpenAI Whisper API. Downloads audio then sends to OpenAI. Needs
    OPENAI_API_KEY. Equivalent to the original CLAUDE.md design.

  local             [free, needs ≥1GB free RAM + ffmpeg]
    faster-whisper running on-device. Zero API cost. Downloads audio, runs
    the WHISPER_MODEL (default: 'small') with int8 quantisation on CPU.
    Accuracy: small ≈ openai whisper-small. Medium is better but needs 2GB.
    Runs on Hetzner CX22 (4GB RAM) comfortably; too tight for Railway 512MB.
    Model is cached in memory after first load (no reload per call).

FLOW:
  YouTube URLs → captions first (always, all backends). If captions succeed,
    done. If they fail AND backend != youtube_captions, falls through to the
    audio backend (downloads YT audio via yt-dlp).
  Non-YouTube URLs → audio backend directly.
  Any failure → None. Never raises. The caller always gets a string or None.
"""

from __future__ import annotations

import logging
import os
import re
import tempfile
from typing import Optional

from config import settings

logger = logging.getLogger("watch.transcribe")

TRANSCRIPT_MAX_CHARS = 6000
TRANSCRIPT_LANGS = ("en", "en-IN", "en-US", "hi")

_YT = re.compile(r"(youtube\.com|youtu\.be)")
_VID = re.compile(r"(?:v=|youtu\.be/|/shorts/)([A-Za-z0-9_-]{11})")
_AUDIO_EXT = (".mp3", ".m4a", ".wav", ".ogg", ".flac", ".aac", ".opus")


# ======================================================================== API

def transcribe_url(url: str) -> Optional[str]:
    """Transcribe any video or audio URL. Returns plain text or None."""
    if not url:
        return None
    if _is_youtube(url):
        text = _youtube_captions(url)
        if text:
            return text
        # Captions failed: try audio backend only if one is actually configured
        if settings.transcription_backend == "youtube_captions":
            return None
        return _transcribe_audio(url)
    return _transcribe_audio(url)


# ==================================================================== backends

def _youtube_captions(url: str) -> Optional[str]:
    """YouTube's own captions — free, keyless, always more accurate than
    re-transcribing compressed audio. Returns None when unavailable."""
    vid = _video_id(url)
    if not vid:
        return None
    try:
        from youtube_transcript_api import YouTubeTranscriptApi
        try:
            segs = YouTubeTranscriptApi.get_transcript(vid, languages=list(TRANSCRIPT_LANGS))
            texts = [s.get("text", "") for s in segs]
        except AttributeError:          # youtube-transcript-api 1.x
            fetched = YouTubeTranscriptApi().fetch(vid, languages=list(TRANSCRIPT_LANGS))
            texts = [getattr(s, "text", "") for s in fetched]
        text = " ".join(t.strip() for t in texts if t and t.strip())
        return text[:TRANSCRIPT_MAX_CHARS] or None
    except ImportError:
        logger.debug("youtube-transcript-api not installed — no captions.")
        return None
    except Exception as exc:            # noqa: BLE001 — no captions is normal
        logger.debug("No captions for %s: %s", vid, exc)
        return None


def _transcribe_audio(url: str) -> Optional[str]:
    b = settings.transcription_backend
    if b == "assemblyai":
        return _via_assemblyai(url)
    if b == "openai":
        return _via_openai(url)
    if b == "local":
        return _via_local(url)
    return None     # youtube_captions or unrecognised — no audio path


def _via_assemblyai(url: str) -> Optional[str]:
    """AssemblyAI — submits the URL directly, polls for completion.
    Free: 100 hours/month, no expiry. pip install assemblyai"""
    if not settings.assemblyai_api_key:
        logger.warning("ASSEMBLYAI_API_KEY not set — skipping transcription.")
        return None
    try:
        import assemblyai as aai        # pip install assemblyai
        aai.settings.api_key = settings.assemblyai_api_key
        t = aai.Transcriber().transcribe(url)
        if hasattr(t, "status") and str(t.status).endswith("error"):
            logger.error("AssemblyAI error for %s: %s", url, getattr(t, "error", "?"))
            return None
        text = (t.text or "").strip()
        logger.info("AssemblyAI: transcribed %d chars from %s", len(text), url)
        return text[:TRANSCRIPT_MAX_CHARS] or None
    except ImportError:
        logger.warning("assemblyai not installed — pip install assemblyai")
        return None
    except Exception as exc:            # noqa: BLE001
        logger.error("AssemblyAI failed for %s: %s", url, exc)
        return None


def _via_openai(url: str) -> Optional[str]:
    """OpenAI Whisper API (whisper-1). Downloads audio first then sends file."""
    if not settings.openai_api_key:
        logger.warning("OPENAI_API_KEY not set — skipping transcription.")
        return None
    audio = _download_audio(url)
    if not audio:
        return None
    try:
        import openai                   # pip install openai
        with open(audio, "rb") as f:
            result = openai.OpenAI(api_key=settings.openai_api_key)\
                           .audio.transcriptions.create(model="whisper-1", file=f)
        text = (result.text or "").strip()
        return text[:TRANSCRIPT_MAX_CHARS] or None
    except ImportError:
        logger.warning("openai not installed — pip install openai")
        return None
    except Exception as exc:            # noqa: BLE001
        logger.error("OpenAI Whisper failed for %s: %s", url, exc)
        return None
    finally:
        _rm(audio)


def _via_local(url: str) -> Optional[str]:
    """faster-whisper on CPU — zero API cost.
    Needs: pip install faster-whisper  and  apt-get install ffmpeg
    Model (WHISPER_MODEL env var, default 'small') is loaded once and cached."""
    audio = _download_audio(url)
    if not audio:
        return None
    try:
        model = _load_local_model()
        segs, _ = model.transcribe(audio, language="en",
                                   beam_size=1, vad_filter=True)
        text = " ".join(s.text.strip() for s in segs if s.text and s.text.strip())
        logger.info("local whisper: transcribed %d chars from %s", len(text), url)
        return text[:TRANSCRIPT_MAX_CHARS] or None
    except ImportError:
        logger.warning("faster-whisper not installed — pip install faster-whisper")
        return None
    except Exception as exc:            # noqa: BLE001
        logger.error("Local Whisper failed for %s: %s", url, exc)
        return None
    finally:
        _rm(audio)


# ================================================================ model cache

_model_cache: Optional[object] = None


def _load_local_model():
    global _model_cache
    if _model_cache is None:
        from faster_whisper import WhisperModel
        size = settings.whisper_model
        logger.info("Loading faster-whisper '%s' (downloads model on first use)…", size)
        _model_cache = WhisperModel(size, device="cpu", compute_type="int8")
        logger.info("faster-whisper model ready.")
    return _model_cache


# ================================================================ audio download

def _download_audio(url: str) -> Optional[str]:
    """Download audio to a temp file. Returns local path or None."""
    try:
        if _is_youtube(url) or not _is_direct_audio(url):
            return _via_ytdlp(url)
        return _direct_download(url)
    except Exception as exc:            # noqa: BLE001
        logger.error("Audio download failed for %s: %s", url, exc)
        return None


def _is_direct_audio(url: str) -> bool:
    return any(url.lower().split("?")[0].endswith(ext) for ext in _AUDIO_EXT)


def _direct_download(url: str, max_mb: int = 60) -> Optional[str]:
    """Stream a direct audio URL to a temp file."""
    import requests
    tmp = tempfile.NamedTemporaryFile(suffix=".mp3", delete=False)
    limit, total = max_mb * 1024 * 1024, 0
    with requests.get(url, stream=True, timeout=60) as r:
        r.raise_for_status()
        for chunk in r.iter_content(65536):
            if total + len(chunk) > limit:
                logger.warning("Audio >%dMB, truncating.", max_mb)
                break
            tmp.write(chunk)
            total += len(chunk)
    tmp.flush(); tmp.close()
    return tmp.name


def _via_ytdlp(url: str) -> Optional[str]:
    """Download audio via yt-dlp (YouTube, video URLs, redirected podcasts).
    Needs: pip install yt-dlp  and  apt-get install ffmpeg"""
    try:
        import yt_dlp               # noqa: F401 — presence check
    except ImportError:
        logger.warning("yt-dlp not installed — pip install yt-dlp")
        return None
    tmpdir = tempfile.mkdtemp()
    opts = {
        "format": "bestaudio/best",
        "outtmpl": os.path.join(tmpdir, "audio.%(ext)s"),
        "quiet": True, "no_warnings": True,
        "postprocessors": [{"key": "FFmpegExtractAudio",
                            "preferredcodec": "mp3", "preferredquality": "96"}],
    }
    try:
        import yt_dlp
        with yt_dlp.YoutubeDL(opts) as ydl:
            ydl.download([url])
        files = [os.path.join(tmpdir, f) for f in os.listdir(tmpdir)]
        return files[0] if files else None
    except Exception as exc:            # noqa: BLE001
        logger.error("yt-dlp failed for %s: %s", url, exc)
        _rm(tmpdir)
        return None


# ==================================================================== helpers

def _is_youtube(url: str) -> bool:
    return bool(_YT.search(url or ""))


def _video_id(url: str) -> Optional[str]:
    m = _VID.search(url or "")
    return m.group(1) if m else None


def _rm(path: Optional[str]) -> None:
    if not path:
        return
    try:
        if os.path.isdir(path):
            import shutil; shutil.rmtree(path, ignore_errors=True)
        elif os.path.exists(path):
            os.unlink(path)
    except OSError:
        pass
