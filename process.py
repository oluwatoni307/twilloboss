import os
import json
import base64
import asyncio
import websockets
import requests
from fastapi import FastAPI, WebSocket, Request, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.websockets import WebSocketDisconnect
from twilio.twiml.voice_response import VoiceResponse, Connect, Say, Stream
from twilio.rest import Client
from dotenv import load_dotenv
from pydantic import BaseModel
import websocket
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.date import DateTrigger
from datetime import datetime, timedelta
from uuid import uuid4
from threading import Lock
from fastapi.middleware.cors import CORSMiddleware

load_dotenv()

scheduler = BackgroundScheduler()
scheduler.start()

# Configuration
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
TWILIO_ACCOUNT_SID = os.getenv("TWILIO_ACCOUNT_SID")
TWILIO_AUTH_TOKEN = os.getenv("TWILIO_AUTH_TOKEN")
TWILIO_PHONE_NUMBER = os.getenv("TWILIO_PHONE_NUMBER")
PORT = int(os.getenv("PORT", 5050))

# Store prompts by call_id
call_prompts = {}
call_lock = Lock()  # Lock for sequential call execution

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
SHOW_TIMING_MATH = False

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Or specify domains like ["https://yourdomain.com"]
    allow_credentials=True,
    allow_methods=["*"],  # Allows all methods including OPTIONS
    allow_headers=["*"],  # Allows all headers
)

# Initialize Twilio client
if not all(
    [OPENAI_API_KEY, TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN, TWILIO_PHONE_NUMBER]
):
    raise ValueError(
        "Missing required environment variables. Set OPENAI_API_KEY, TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN, and TWILIO_PHONE_NUMBER in .env."
    )

twilio_client = Client(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)

class ScheduleCallRequest(BaseModel):
    to_phone_number: str
    call_type: bool
    call_time: datetime
    Language: str
    Accent: str
    prompt: str

@app.post("/schedule-call")
async def schedule_call(req: ScheduleCallRequest):
    call_id = str(uuid4())
    prompt = f"""
    You are an elite real‑time conversational voice assistant, designed for clarity and expressiveness.
    • Language: Speak flawlessly in ${req.Language}, with native‑level fluency.
    • Accent: Embrace the full character of a ${req.Accent} accent—honoring its unique phonetics, rhythm, and intonation.
    • Instruction: Listen fully, then engage in a natural, conversational style as you follow the user’s request: ${req.prompt}.
    """
    call_prompts[call_id] = prompt
    print(call_prompts)

    def trigger_call(to_phone_number: str, call_id: str):
        with call_lock:
            try:
                twiml_url = f"{os.getenv('PUBLIC_HOST')}/outbound-twiml?call_id={call_id}"
                print(twiml_url)
                call = twilio_client.calls.create(
                    to=to_phone_number, from_=TWILIO_PHONE_NUMBER, url=twiml_url
                )
                print(f"Call to {to_phone_number} initiated (SID: {call.sid})")
            except Exception as e:
                print(f"Scheduled call failed: {str(e)}")

    if req.call_type:
        trigger_call(req.to_phone_number, call_id)
        return {"message": f"Call initiated immediately to {req.to_phone_number}"}

    now = datetime.utcnow()
    if req.call_time <= now:
        raise HTTPException(status_code=400, detail="Call time must be in the future.")

    scheduler.add_job(
        trigger_call,
        trigger=DateTrigger(run_date=req.call_time),
        args=[req.to_phone_number, call_id],
        id=call_id,
        replace_existing=True
    )
    return {
        "message": f"Call scheduled to {req.to_phone_number} at {req.call_time.isoformat()}"
    }


class OutboundCallRequest(BaseModel):
    to_phone_number: str

@app.get("/", response_class=JSONResponse)
async def index_page():
    return {"message": "Twilio Media Stream Server is running!"}

@app.api_route("/outbound-twiml", methods=["GET", "POST"])
async def outbound_twiml(request: Request):
    
    response = VoiceResponse()
    response.say(
        "Hello! You are now connected to an A. I. voice assistant powered by Twilio and the Open-A.I. Realtime API."
    )
    response.pause(length=1)
    response.say("O.K. you can start talking!")
    host = request.url.hostname
    call_id = request.query_params.get("call_id", "")
    print(call_id)
    
    connect = Connect()
    connect.stream(url=f"wss://{host}/media-stream/{call_id}")
    response.append(connect)
    return HTMLResponse(content=str(response), media_type="application/xml")

@app.websocket("/media-stream/{call_id}")
async def handle_media_stream(websock: WebSocket, call_id: str = None):
    print("WebSocket received call_id:", call_id)

    print("Client connected")
    await websock.accept()

    async with websockets.connect(
        "wss://api.openai.com/v1/realtime?model=gpt-4o-mini-realtime-preview-2024-12-17",
        extra_headers={
            "Authorization": f"Bearer {OPENAI_API_KEY}",
            "OpenAI-Beta": "realtime=v1",
        },
    ) as openai_ws:
        await initialize_session(openai_ws, call_id)
        stream_sid = None
        latest_media_timestamp = 0
        last_assistant_item = None
        mark_queue = []
        response_start_timestamp_twilio = None

        async def receive_from_twilio():
            nonlocal stream_sid, latest_media_timestamp
            try:
                async for message in websock.iter_text():
                    data = json.loads(message)
                    if data["event"] == "stop":
                            print("Twilio call terminated")
                            if openai_ws.open:
                                await openai_ws.close()
                            await websock.close(code=1000, reason="Call terminated")
                            return
                    if data["event"] == "media" and openai_ws.open:
                        latest_media_timestamp = int(data["media"]["timestamp"])
                        audio_append = {
                            "type": "input_audio_buffer.append",
                            "audio": data["media"]["payload"],
                        }
                        await openai_ws.send(json.dumps(audio_append))
                    elif data["event"] == "start":
                        stream_sid = data["start"]["streamSid"]
                        print(f"Incoming stream has started {stream_sid}")
                        response_start_timestamp_twilio = None
                        latest_media_timestamp = 0
                        last_assistant_item = None
                    elif data["event"] == "mark":
                        if mark_queue:
                            mark_queue.pop(0)
            except WebSocketDisconnect:
                print("Client disconnected.")
                await websock.close(code=1000, reason="Call terminated")

                if openai_ws.open:
                    await openai_ws.close()

        async def send_to_twilio():
            nonlocal stream_sid, last_assistant_item, response_start_timestamp_twilio
            try:
                async for openai_message in openai_ws:
                    response = json.loads(openai_message)
                    if response["type"] in LOG_EVENT_TYPES:
                        print(f"Received event: {response['type']}", response)

                    if (
                        response.get("type") == "response.audio.delta"
                        and "delta" in response
                    ):
                        audio_payload = base64.b64encode(
                            base64.b64decode(response["delta"])
                        ).decode("utf-8")
                        audio_delta = {
                            "event": "media",
                            "streamSid": stream_sid,
                            "media": {"payload": audio_payload},
                        }
                        await websock.send_json(audio_delta)

                        if response_start_timestamp_twilio is None:
                            response_start_timestamp_twilio = latest_media_timestamp
                            if SHOW_TIMING_MATH:
                                print(
                                    f"Setting start timestamp for new response: {response_start_timestamp_twilio}ms"
                                )

                        if response.get("item_id"):
                            last_assistant_item = response["item_id"]

                        await send_mark(websock, stream_sid)

                    if response.get("type") == "input_audio_buffer.speech_started":
                        print("Speech started detected.")
                        if last_assistant_item:
                            print(
                                f"Interrupting response with id: {last_assistant_item}"
                            )
                            await handle_speech_started_event()
            except Exception as e:
                await websock.close(code=1000, reason="Call terminated")

                print(f"Error in send_to_twilio: {e}")

        async def handle_speech_started_event():
            nonlocal response_start_timestamp_twilio, last_assistant_item
            print("Handling speech started event.")
            if mark_queue and response_start_timestamp_twilio is not None:
                elapsed_time = latest_media_timestamp - response_start_timestamp_twilio
                if SHOW_TIMING_MATH:
                    print(
                        f"Calculating elapsed time for truncation: {latest_media_timestamp} - {response_start_timestamp_twilio} = {elapsed_time}ms"
                    )

                if last_assistant_item:
                    if SHOW_TIMING_MATH:
                        print(
                            f"Truncating item with ID: {last_assistant_item}, Truncated at: {elapsed_time}ms"
                        )

                    truncate_event = {
                        "type": "conversation.item.truncate",
                        "item_id": last_assistant_item,
                        "content_index": 0,
                        "audio_end_ms": elapsed_time,
                    }
                    await openai_ws.send(json.dumps(truncate_event))

                await websock.send_json({"event": "clear", "streamSid": stream_sid})

                mark_queue.clear()
                last_assistant_item = None
                response_start_timestamp_twilio = None

        async def send_mark(connection, stream_sid):
            if stream_sid:
                mark_event = {
                    "event": "mark",
                    "streamSid": stream_sid,
                    "mark": {"name": "responsePart"},
                }
                await connection.send_json(mark_event)
                mark_queue.append("responsePart")

        await asyncio.gather(receive_from_twilio(), send_to_twilio())

async def send_initial_conversation_item(openai_ws):
    initial_conversation_item = {
        "type": "conversation.item.create",
        "item": {
            "type": "message",
            "role": "user",
            "content": [
                {
                    "type": "input_text",
                    "text": "Begin the call conversation in a natural way that aligns with your defined purpose. Greet the user appropriately.",
                }
            ],
        },
    }
    await openai_ws.send(json.dumps(initial_conversation_item))
    await openai_ws.send(json.dumps({"type": "response.create"}))

async def initialize_session(openai_ws, call_id: str):
    print("Hello")
    print(call_prompts.get(call_id, ""))
    print(call_id)
    session_update = {
        "type": "session.update",
        "session": {
            "turn_detection": {"type": "server_vad"},
            "input_audio_format": "g711_ulaw",
            "output_audio_format": "g711_ulaw",
            "voice": VOICE,
            "instructions": call_prompts.get(call_id, ""),
            "modalities": ["text", "audio"],
            "temperature": 0.8,
        },
    }
    print("Sending session update:", json.dumps(session_update))
    await openai_ws.send(json.dumps(session_update))
    await send_initial_conversation_item(openai_ws)
    call_prompts.pop(call_id, None)



class SessionRequest(BaseModel):
    prompt: str = "you are a student and you want to ask me philosophical questions about life."

@app.post("/session")
async def session(request: SessionRequest):
    try:
        # it should take in instructions as part of the request
        # Make a POST request to the OpenAI Real-Time Sessions endpoint
        response = requests.post(
            "https://api.openai.com/v1/realtime/sessions",
            headers={
                "Authorization": f"Bearer {OPENAI_API_KEY}",
                "Content-Type": "application/json",
            },
            json={
                "model": "gpt-4o-realtime-preview-2024-12-17",
                "voice": "alloy",
                "instructions":request.prompt
            },
        )

        # Check if the request was successful
        if response.status_code != 200:
            raise HTTPException(
                status_code=response.status_code,
                detail=f"Failed to create session: {response.text}"
            )

        # Parse the JSON response from OpenAI
        data = response.json()
        print(data)

        # Send back the client secret value we received from the OpenAI REST API
        return JSONResponse(content=data["client_secret"]["value"])

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))









if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=PORT) 
