# Local speech-to-text with faster-whisper

Speech-to-text runs locally with faster-whisper (`base.en`, int8, CPU), so the tool needs no second API key and audio never leaves the machine. We picked it over NVIDIA Parakeet because Parakeet's official tooling (NeMo) needs CUDA and doesn't pip-install cleanly on macOS. faster-whisper installed with one pip command on Apple Silicon, transcribes a short command in about 0.2s after a roughly 9s one-time model load, and accepts in-memory audio, so no ffmpeg is needed. An initial prompt listing sample commands biases Whisper toward command vocabulary and app names.

## Considered Options

- **parakeet-mlx / mlx-whisper.** These are faster on Apple Silicon but tie the speech layer to MLX and macOS. Worth revisiting if latency matters more than portability.
- **A cloud speech API.** Rejected: it needs a second key, and the brief asked for local speech-to-text.
