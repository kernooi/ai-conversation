# ai-conversation
clone a person's voice and have a conversation with them

install ollama 

ollama pull tripolskypetr/qwen3.5-uncensored-aggressive:9b 

backend
env
OLLAMA_HOST=http://localhost:11434
MODEL_NAME=tripolskypetr/qwen3.5-uncensored-aggressive:9b
SUMMARIZE_AFTER=12
KEEP_RECENT=6
OLLAMA_THINK=false

pip install -r requirements.txt
uvicorn main:app --reload --port 8000
http://localhost:8000/health

frontend
.env.local NEXT_PUBLIC_API_URL=http://localhost:8000
npm install
npm start

cd backend
py -3.11 -m venv venv
venv\Scripts\activate
pip install torch torchaudio --index-url https://download.pytorch.org/whl/cu121
pip install -r requirements.txt
pip install -r requirements-tts.txt

CosyVoice3 notes:
- The CosyVoice source is vendored at `backend/vendor/CosyVoice`.
- The active model path is configured with `COSYVOICE_MODEL_DIR`.
- Put `default.txt` next to `default.wav`/`default.mp3` with the exact reference clip transcript.
