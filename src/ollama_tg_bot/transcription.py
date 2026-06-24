from __future__ import annotations

import asyncio
import logging
import tempfile
import time
from collections.abc import AsyncIterator
from dataclasses import dataclass
from pathlib import Path

from .config import Settings
from .whisper_client import WhisperClient, WhisperError


logger = logging.getLogger(__name__)


class AudioPreparationError(WhisperError):
  user_message = 'Не удалось подготовить аудио. Проверь формат файла и наличие ffmpeg.'


@dataclass(frozen=True)
class TranscriptionChunk:
  index: int
  total: int
  text: str


class TranscriptionService:

  def __init__(self, settings: Settings) -> None:
    self.settings = settings
    self.client = WhisperClient(settings)

  async def transcribe(self, source_path: Path) -> AsyncIterator[TranscriptionChunk]:
    started_at = time.monotonic()
    with tempfile.TemporaryDirectory(prefix='xoribot-audio-') as temp_dir_name:
      temp_dir = Path(temp_dir_name)
      segments = await self._prepare_segments(source_path, temp_dir)
      total = len(segments)
      if total == 0:
        raise AudioPreparationError('ffmpeg did not produce any output segments')

      logger.info('audio prepared source=%s segments=%s', source_path.name, total)
      for index, segment_path in enumerate(segments, start=1):
        text = await self.client.transcribe(segment_path)
        yield TranscriptionChunk(index=index, total=total, text=text.strip())

    logger.info('audio transcription completed source=%s elapsed=%.2fs', source_path.name, time.monotonic() - started_at)

  async def _prepare_segments(self, source_path: Path, temp_dir: Path) -> list[Path]:
    output_pattern = temp_dir / 'segment_%03d.flac'
    process = await asyncio.create_subprocess_exec(
      self.settings.ffmpeg_bin,
      '-hide_banner',
      '-loglevel',
      'error',
      '-y',
      '-i',
      str(source_path),
      '-map',
      '0:a:0',
      '-vn',
      '-ac',
      '1',
      '-ar',
      '16000',
      '-af',
      'highpass=f=80,lowpass=f=7600,afftdn=nf=-25,loudnorm',
      '-c:a',
      'flac',
      '-compression_level',
      '8',
      '-f',
      'segment',
      '-segment_time',
      str(self.settings.whisper_segment_seconds),
      '-reset_timestamps',
      '1',
      str(output_pattern),
      stdout=asyncio.subprocess.PIPE,
      stderr=asyncio.subprocess.PIPE,
    )
    _, stderr = await process.communicate()
    if process.returncode != 0:
      detail = stderr.decode('utf-8', errors='replace').strip()
      raise AudioPreparationError(detail or f'ffmpeg exited with code {process.returncode}')

    return sorted(temp_dir.glob('segment_*.flac'))
