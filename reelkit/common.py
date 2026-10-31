import math, re, subprocess
from dataclasses import dataclass, field
import imageio_ffmpeg
import numpy as np

W, H, FPS = 1080, 1920, 30
SR = 44100
FFMPEG = imageio_ffmpeg.get_ffmpeg_exe()
FORMATS = {"9:16": (1080, 1920), "4:5": (1080, 1350), "1:1": (1080, 1080), "16:9": (1920, 1080)}


@dataclass
class Scene:
    text: str
    kind: str = "card"                  # hook | card | stat | cta
    words: list = field(default_factory=list)
    audio: "np.ndarray | None" = None   # int16 mono @ SR
    speech: float = 0.0                 # seconds of actual speech (before gap/beat padding)
    start: float = 0.0
    dur: float = 0.0
    word_times: list = field(default_factory=list)   # (start, end) per word, relative to scene
    timing_source: str = "estimated"
    prop: "str | None" = None


def norm(w: str) -> str:
    return re.sub(r"[\W_]+", "", w.lower())


def to_pcm(audio_bytes: bytes) -> np.ndarray:
    """Decode any audio container to 44.1k mono int16 via ffmpeg."""
    p = subprocess.run([FFMPEG, "-v", "error", "-i", "pipe:0", "-f", "s16le", "-ac", "1",
                        "-ar", str(SR), "pipe:1"], input=audio_bytes, capture_output=True, check=True)
    return np.frombuffer(p.stdout, dtype=np.int16)


def pcm_to_16k_float(pcm: np.ndarray) -> np.ndarray:
    p = subprocess.run([FFMPEG, "-v", "error", "-f", "s16le", "-ar", str(SR), "-ac", "1", "-i", "pipe:0",
                        "-f", "f32le", "-ac", "1", "-ar", "16000", "pipe:1"],
                       input=pcm.tobytes(), capture_output=True, check=True)
    return np.frombuffer(p.stdout, dtype=np.float32)
