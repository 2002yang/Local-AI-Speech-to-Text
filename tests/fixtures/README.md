# Browser recording fixture

`browser-recorded.webm` was encoded by the in-app Chromium browser `MediaRecorder` with `audio/webm;codecs=opus` from `samples/english.wav` played through an `AudioContext`/`MediaStreamDestination`. It is an actual browser-produced WebM/Opus file; the source is synthesized speech, **not a live microphone recording**. Duration: approximately 10.44 seconds.

This fixture verifies decoding and the full upload/ASR path. Its source and distribution caveat are the same as `samples/english.wav`; see `samples/SOURCE.md`. Reference text is in `samples/reference.txt`.
