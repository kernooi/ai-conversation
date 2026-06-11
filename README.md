# ai-conversation
clone a person voice and have a conversation with them

install ollama 

ollama pull nollama/mythomax-l2-13b:Q4_K_S

backend
pip install -r requirements.txt
uvicorn main:app --reload --port 8000
http://localhost:8000/health

frontend
npm install
npm start