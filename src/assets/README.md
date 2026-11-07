# Assets

## voice_ref.wav

Place a short WAV file here named `voice_ref.wav` to serve as the voice reference for NeuTTS speech synthesis.

- **Purpose**: NeuTTS uses this clip for zero-shot voice cloning. The synthesized speech will mimic the voice characteristics (tone, pitch, cadence) from this reference.
- **Format**: WAV, 24 kHz sample rate recommended.
- **Duration**: As little as 3 seconds is sufficient; longer clips may improve quality.
- **Reference text**: Update `NEUTTS_REF_TEXT` in `src/mesly/tts/speech.py` to match the transcript of this audio file. Accurate text-audio alignment improves cloning quality.
