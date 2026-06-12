"""
watch/transcribe.py — backend switching, routing, and graceful fallbacks.
All tests are pure: no network, no real models, no API calls.
"""

import types
from unittest.mock import MagicMock, patch

import pytest

from conftest import patch_settings
from watch import transcribe as tr


# ================================================================ URL routing

def test_youtube_url_routes_to_captions(monkeypatch):
    called = []
    monkeypatch.setattr(tr, "_youtube_captions", lambda url: (called.append(url), "transcript")[1])
    monkeypatch.setattr(tr, "_transcribe_audio", lambda url: None)
    result = tr.transcribe_url("https://www.youtube.com/watch?v=abc12345678")
    assert called == ["https://www.youtube.com/watch?v=abc12345678"]
    assert result == "transcript"


def test_youtu_be_url_routes_to_captions(monkeypatch):
    called = []
    monkeypatch.setattr(tr, "_youtube_captions", lambda url: (called.append(1), "text")[1])
    monkeypatch.setattr(tr, "_transcribe_audio", lambda url: None)
    tr.transcribe_url("https://youtu.be/abc12345678")
    assert called == [1]


def test_non_youtube_url_skips_captions_goes_to_audio(monkeypatch):
    captions_called = []
    audio_called = []
    monkeypatch.setattr(tr, "_youtube_captions",
                        lambda url: (captions_called.append(1), None)[1])
    monkeypatch.setattr(tr, "_transcribe_audio",
                        lambda url: (audio_called.append(1), "audio text")[1])
    result = tr.transcribe_url("https://podcast.example.com/ep1.mp3")
    assert captions_called == []
    assert audio_called == [1]
    assert result == "audio text"


def test_empty_url_returns_none():
    assert tr.transcribe_url("") is None
    assert tr.transcribe_url(None) is None


# ================================================================ caption fallback

def test_youtube_captions_fail_falls_back_to_audio_when_backend_configured(monkeypatch):
    monkeypatch.setattr(tr, "_youtube_captions", lambda url: None)  # captions unavailable
    patch_settings(monkeypatch, tr, transcription_backend="assemblyai")
    audio_called = []
    monkeypatch.setattr(tr, "_transcribe_audio",
                        lambda url: (audio_called.append(1), "fallback")[1])
    result = tr.transcribe_url("https://www.youtube.com/watch?v=abc12345678")
    assert audio_called == [1]
    assert result == "fallback"


def test_youtube_captions_fail_no_fallback_for_youtube_captions_backend(monkeypatch):
    monkeypatch.setattr(tr, "_youtube_captions", lambda url: None)
    patch_settings(monkeypatch, tr, transcription_backend="youtube_captions")
    audio_called = []
    monkeypatch.setattr(tr, "_transcribe_audio",
                        lambda url: (audio_called.append(1), "x")[1])
    result = tr.transcribe_url("https://www.youtube.com/watch?v=abc12345678")
    assert audio_called == []
    assert result is None


# ================================================================ AssemblyAI backend

def test_assemblyai_no_key_returns_none(monkeypatch):
    patch_settings(monkeypatch, tr, assemblyai_api_key="", transcription_backend="assemblyai")
    assert tr._via_assemblyai("https://example.com/ep.mp3") is None


def test_assemblyai_missing_package_returns_none(monkeypatch):
    patch_settings(monkeypatch, tr, assemblyai_api_key="key123",
                   transcription_backend="assemblyai")
    import sys
    monkeypatch.setitem(sys.modules, "assemblyai", None)
    assert tr._via_assemblyai("https://example.com/ep.mp3") is None


def test_assemblyai_success(monkeypatch):
    patch_settings(monkeypatch, tr, assemblyai_api_key="key123",
                   transcription_backend="assemblyai")

    fake_transcript = MagicMock()
    fake_transcript.text = "PM Modi announced a new policy today."
    fake_transcript.status = "completed"

    fake_transcriber = MagicMock()
    fake_transcriber.return_value.transcribe.return_value = fake_transcript

    fake_aai = types.ModuleType("assemblyai")
    fake_aai.settings = MagicMock()
    fake_aai.Transcriber = fake_transcriber

    import sys
    monkeypatch.setitem(sys.modules, "assemblyai", fake_aai)

    result = tr._via_assemblyai("https://example.com/ep.mp3")
    assert result == "PM Modi announced a new policy today."


def test_assemblyai_truncates_to_max_chars(monkeypatch):
    patch_settings(monkeypatch, tr, assemblyai_api_key="k",
                   transcription_backend="assemblyai")

    fake_transcript = MagicMock()
    fake_transcript.text = "x" * 10000
    fake_transcript.status = "completed"

    fake_aai = types.ModuleType("assemblyai")
    fake_aai.settings = MagicMock()
    fake_aai.Transcriber = MagicMock(return_value=MagicMock(
        transcribe=MagicMock(return_value=fake_transcript)))

    import sys
    monkeypatch.setitem(sys.modules, "assemblyai", fake_aai)

    result = tr._via_assemblyai("https://example.com/ep.mp3")
    assert len(result) == tr.TRANSCRIPT_MAX_CHARS


# ================================================================ OpenAI backend

def test_openai_no_key_returns_none(monkeypatch):
    patch_settings(monkeypatch, tr, openai_api_key="", transcription_backend="openai")
    assert tr._via_openai("https://example.com/ep.mp3") is None


def test_openai_missing_package_returns_none(monkeypatch):
    patch_settings(monkeypatch, tr, openai_api_key="sk-x", transcription_backend="openai")
    import sys
    monkeypatch.setitem(sys.modules, "openai", None)
    monkeypatch.setattr(tr, "_download_audio", lambda url: "/tmp/fake.mp3")
    assert tr._via_openai("https://example.com/ep.mp3") is None


# ================================================================ local backend

def test_local_no_package_returns_none(monkeypatch):
    import sys
    monkeypatch.setitem(sys.modules, "faster_whisper", None)
    tr._model_cache = None   # reset cache
    monkeypatch.setattr(tr, "_download_audio", lambda url: "/tmp/fake.mp3")
    patch_settings(monkeypatch, tr, transcription_backend="local", whisper_model="tiny")
    result = tr._via_local("https://example.com/ep.mp3")
    assert result is None


def test_local_model_cached_on_second_call(monkeypatch):
    """_load_local_model() must not reload the model between calls."""
    load_count = [0]

    class FakeModel:
        def transcribe(self, path, **kwargs):
            seg = MagicMock(); seg.text = "hello world"
            return [seg], None

    def fake_WhisperModel(size, **kwargs):
        load_count[0] += 1
        return FakeModel()

    fake_fw = types.ModuleType("faster_whisper")
    fake_fw.WhisperModel = fake_WhisperModel

    import sys
    monkeypatch.setitem(sys.modules, "faster_whisper", fake_fw)
    tr._model_cache = None      # reset between test runs
    patch_settings(monkeypatch, tr, whisper_model="tiny")

    tr._load_local_model()
    tr._load_local_model()
    assert load_count[0] == 1   # loaded once, then cached


# ================================================================ helper utils

def test_is_youtube_detects_variants():
    assert tr._is_youtube("https://www.youtube.com/watch?v=abc")
    assert tr._is_youtube("https://youtu.be/abc12345678")
    assert not tr._is_youtube("https://vimeo.com/123")
    assert not tr._is_youtube("https://podcast.example.com/ep.mp3")


def test_is_direct_audio():
    assert tr._is_direct_audio("https://cdn.example.com/ep001.mp3")
    assert tr._is_direct_audio("https://cdn.example.com/ep.m4a?v=1")
    assert not tr._is_direct_audio("https://www.youtube.com/watch?v=abc")
    assert not tr._is_direct_audio("https://news.com/article")


def test_backend_routing_returns_none_for_unrecognised(monkeypatch):
    patch_settings(monkeypatch, tr, transcription_backend="nonexistent_backend")
    assert tr._transcribe_audio("https://example.com/ep.mp3") is None


# ================================================================ youtube.py delegation

def test_youtube_fetch_transcript_delegates_to_transcribe_url():
    """youtube.py's fetch_transcript is now a thin wrapper around transcribe_url."""
    with patch("watch.transcribe.transcribe_url", return_value="delegated") as mock_fn:
        from watch.youtube import fetch_transcript
        result = fetch_transcript("https://www.youtube.com/watch?v=abc")
        mock_fn.assert_called_once_with("https://www.youtube.com/watch?v=abc")
        assert result == "delegated"
