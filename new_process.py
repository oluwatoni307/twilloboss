import os
import json
import base64
import asyncio
import websockets
import requests
from fastapi import FastAPI, WebSocket, HTTPException, WebSocketDisconnect
from fastapi.responses import JSONResponse
from vonage import Vonage, Auth
from dotenv import load_dotenv
from pydantic import BaseModel

# Load environment variables
load_dotenv()

# Initialize Vonage and OpenAI API keys
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
VONAGE_API_KEY = os.getenv("VONAGE_API_KEY")
VONAGE_API_SECRET = os.getenv("VONAGE_API_SECRET")
DOMAIN = os.getenv("PUBLIC_HOST", "default-domain.com")

# Setup Vonage Auth and Client
auth = Auth(api_key=VONAGE_API_KEY, api_secret=VONAGE_API_SECRET)
vonage = Vonage(auth=auth)

# FastAPI app setup
app = FastAPI()

# Define the voice type and the allowed events
VOICE = "alloy"
LOG_EVENT_TYPES = [
    "error",
    "response.content.done",
    "rate_limits.updated",
    "response.done",
    "input_audio_buffer.committed",
    "input_audio_buffer.speech_stopped",
    "input_audio_buffer.speech_started",
    "session.created",
]

# Vonage Call NCCO configuration (with WebSocket)
ncco = [
    {
        "action": "connect",
        "endpoint": [
            {
                "type": "websocket",
                "uri": f"wss://{DOMAIN}/media-stream",  # Ensure the domain is correct
                "content-type": "audio/l16;rate=16000",
                "headers": {
                    "caller": "VonageBot"
                }
            }
        ]
    }
]

# Start the call to Vonage
def initiate_vonage_call():
    try:
        response = vonage.voice.create_call({
            "to": [{"type": "phone", "number": "+2349078447367"}],  # Replace with actual number
            "from": {"type": "phone", "random_from_number": True},  # Use random number for the "from" field
            "ncco": ncco
        })
        print(f"Call initiated with response: {response}")
    except Exception as e:
        print(f"Error initiating Vonage call: {e}")

# FastAPI WebSocket endpoint to handle media stream
@app.websocket("/media-stream")
async def handle_media_stream(websock: WebSocket):
    print("Client connected to media stream")
    await websock.accept()

    async with websockets.connect(
        "wss://api.openai.com/v1/realtime?model=gpt-4o-mini-realtime-preview-2024-12-17",
        extra_headers={
            "Authorization": f"Bearer {OPENAI_API_KEY}",
            "OpenAI-Beta": "realtime=v1",
        },
    ) as openai_ws:
        await initialize_session(openai_ws)
        stream_sid = None
        latest_media_timestamp = 0
        last_assistant_item = None
        mark_queue = []

        # Handling messages received from Vonage WebSocket
        async def receive_from_vonage():
            nonlocal stream_sid, latest_media_timestamp
            try:
                async for message in websock.iter_text():
                    data = json.loads(message)
                    if data["event"] == "media" and openai_ws.open:
                        latest_media_timestamp = int(data["media"]["timestamp"])
                        audio_append = {
                            "type": "input_audio_buffer.append",
                            "audio": data["media"]["payload"],
                        }
                        await openai_ws.send(json.dumps(audio_append))
                    elif data["event"] == "start":
                        stream_sid = data["start"]["streamSid"]
                        print(f"Incoming stream started with streamSid: {stream_sid}")
                        latest_media_timestamp = 0
                        last_assistant_item = None
                    elif data["event"] == "mark":
                        if mark_queue:
                            mark_queue.pop(0)
            except WebSocketDisconnect:
                print("Client disconnected from Vonage WebSocket.")
                if openai_ws.open:
                    await openai_ws.close()

        # Handling messages sent from OpenAI WebSocket
        async def send_to_vonage():
            nonlocal stream_sid, last_assistant_item
            try:
                async for openai_message in openai_ws:
                    response = json.loads(openai_message)
                    if response["type"] in LOG_EVENT_TYPES:
                        print(f"Received event: {response['type']}", response)

                    if response.get("type") == "response.audio.delta" and "delta" in response:
                        audio_payload = base64.b64encode(
                            base64.b64decode(response["delta"])
                        ).decode("utf-8")
                        audio_delta = {
                            "event": "media",
                            "streamSid": stream_sid,
                            "media": {"payload": audio_payload},
                        }
                        await websock.send_json(audio_delta)

                    if response.get("type") == "input_audio_buffer.speech_started":
                        print("Speech started detected.")
                        if last_assistant_item:
                            print(f"Interrupting response with ID: {last_assistant_item}")
                            await handle_speech_started_event()
            except Exception as e:
                print(f"Error in send_to_vonage: {e}")

        # Handle speech started event
        async def handle_speech_started_event():
            nonlocal stream_sid, last_assistant_item
            print("Handling speech started event.")
            if mark_queue:
                mark_event = {
                    "event": "mark",
                    "streamSid": stream_sid,
                    "mark": {"name": "responsePart"},
                }
                await websock.send_json(mark_event)

            mark_queue.clear()
            last_assistant_item = None

        # Initiating tasks concurrently
        await asyncio.gather(receive_from_vonage(), send_to_vonage())

# Initialize OpenAI session
async def initialize_session(openai_ws):
    print("Initializing OpenAI session")
    session_update = {
        "type": "session.update",
        "session": {
            "turn_detection": {"type": "server_vad"},
            "input_audio_format": "g711_ulaw",
            "output_audio_format": "g711_ulaw",
            "voice": VOICE,
            "instructions": "Hello",
            "modalities": ["text", "audio"],
            "temperature": 0.8,
        },
    }
    print("Sending session update:", json.dumps(session_update))
    await openai_ws.send(json.dumps(session_update))

# POST endpoint to create a session
class SessionRequest(BaseModel):
    prompt: str = "you are a student and you want to ask me philosophical questions about life."

@app.post("/session")
async def session(request: SessionRequest):
    try:
        response = requests.post(
            "https://api.openai.com/v1/realtime/sessions",
            headers={
                "Authorization": f"Bearer {OPENAI_API_KEY}",
                "Content-Type": "application/json",
            },
            json={
                "model": "gpt-4o-realtime-preview-2024-12-17",
                "voice": VOICE,
                "instructions": request.prompt,
            },
        )

        if response.status_code != 200:
            raise HTTPException(
                status_code=response.status_code,
                detail=f"Failed to create session: {response.text}",
            )

        data = response.json()
        return JSONResponse(content=data["client_secret"]["value"])
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# Start the application
if __name__ == "__main__":
    initiate_vonage_call()
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=5050)
