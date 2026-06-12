# Voice reference clips

Drop reference audio files here to clone voices with CosyVoice3.

## Requirements for a good clone
- **Format:** `.mp3`, `.wav`, `.m4a`, `.ogg`, `.flac`, or `.aac`; non-wav files
  are auto-converted to wav on first use and cached here.
- **Length:** 3-30 seconds, clean speech, one speaker.
- **Transcript:** add a matching `.txt` file with the exact words spoken in the
  reference clip. Example: `default.wav` should have `default.txt`.
- **Naming:** the filename without extension is the voice name.

## Example
```text
voices/
  default.mp3
  default.txt
  alice.wav
  alice.txt
```

The frontend voice picker lists supported audio files automatically through
`GET /voices`.

## ffmpeg
Conversion uses ffmpeg under the hood. If it is not installed:

```powershell
winget install ffmpeg
```

Then reopen the terminal and verify with:

```powershell
ffmpeg -version
```
