import asyncio
import websockets
import json
import logging
import os

# Set up logging
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

async def open_websocket_session():
    url = "wss://api.openai.com/v1/realtime?model=gpt-4o-realtime-preview-2024-10-01"
    headers = {"Authorization": f"Bearer {os.environ.get('OPENAI_API_KEY')}", "OpenAI-Beta": "realtime=v1"}

    try:
        async with websockets.connect(url, extra_headers=headers) as websocket:
            logger.info("Connected to server.")
            # Listen for incoming messages
            while True:
                message = await websocket.recv()
                parsed_message = json.loads(message)
                logger.info(f"Received message: {parsed_message}")

                # Process the message as needed

    except websockets.exceptions.WebSocketException as e:
        logger.error(f"WebSocket error: {e}")
    except Exception as e:
        logger.error(f"An unexpected error occurred: {e}")

# Run the async function
if __name__ == "__main__":
    asyncio.run(open_websocket_session())