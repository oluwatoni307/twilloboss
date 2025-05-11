import requests
import jwt
import time
import os
from dotenv import load_dotenv

# Load from .env file
load_dotenv()

application_id = os.getenv("VONAGE_APPLICATION_ID")
private_key_path = os.getenv("VONAGE_PRIVATE_KEY_PATH")

# Read private key
with open(private_key_path, "r") as key_file:
    private_key = key_file.read()

# Create JWT
token = jwt.encode({
    "application_id": application_id,
    "iat": int(time.time()),
    "exp": int(time.time()) + 60 * 60,
    "jti": "auth-test-123"
}, private_key, algorithm="RS256")

# Send authenticated GET request to test
headers = {
    "Authorization": f"Bearer {token}",
    "Content-Type": "application/json"
}

# Hit a safe endpoint that doesn't modify anything
url = "https://api.nexmo.com/v2/applications"

response = requests.get(url, headers=headers)

# Output result
if response.status_code == 200:
    print("✅ Auth is correct! Response:")
    print(response.json())
else:
    print(f"❌ Auth failed with status {response.status_code}")
    print(response.text)
