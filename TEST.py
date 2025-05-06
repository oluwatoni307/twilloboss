import asyncio
from pydantic import BaseModel
from process import make_outbound_call, OutboundCallRequest

async def test_outbound_call():
    """Test making an outbound call to a specified phone number."""
    call_request = OutboundCallRequest(to_phone_number="+2348145857460")
    try:
        result = await make_outbound_call(call_request)
        print(result)
    except Exception as e:
        print(f"Error making outbound call: {e}")

if __name__ == "__main__":
    asyncio.run(test_outbound_call())