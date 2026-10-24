"""Заглушки важких AI-залежностей: тести не завантажують Whisper і Gemini SDK."""
import sys
import types


def _stub_module(name, **attrs):
    if name in sys.modules:
        return
    try:
        __import__(name)
    except ImportError:
        module = types.ModuleType(name)
        for key, value in attrs.items():
            setattr(module, key, value)
        sys.modules[name] = module


_stub_module("faster_whisper", WhisperModel=object)
