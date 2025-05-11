import requests
import json
from datetime import datetime, timedelta
import os
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Configuration
API_URL = "http://localhost:5050"  # Change this to match your server's address
TO_PHONE_NUMBER = "+2349078447367"  # Add this to your .env file

def test_immediate_call():
    """Test the immediate call functionality of the voice assistant."""
    
    # Prepare the request payload
    payload = {
        "to_phone_number": TO_PHONE_NUMBER,
        "call_type": True,  # True for immediate call
        "call_time": (datetime.utcnow() + timedelta(seconds=5)).isoformat(),  # Not used for immediate calls but required
        "Language": "English",
        "Accent": "American",
        "prompt": "You are a helpful assistant calling to check in on the user. Ask them how their day is going and engage in a brief, friendly conversation."
    }
    
    print(f"Initiating test call to {TO_PHONE_NUMBER}...")
    
    try:
        # Send the request to the API
        response = requests.post(f"{API_URL}/schedule-call", json=payload)
        
        # Check if the request was successful
        if response.status_code == 200:
            result = response.json()
            print(f"Success: {result['message']}")
        else:
            print(f"Error: {response.status_code}")
            print(response.text)
    
    except Exception as e:
        print(f"Exception occurred: {str(e)}")

def test_session_creation():
    """Test the session creation endpoint."""
    
    payload = {
        "prompt": "You are a friendly assistant who specializes in explaining complex topics in simple terms."
    }
    
    print("Testing session creation...")
    
    try:
        response = requests.post(f"{API_URL}/session", json=payload)
        
        if response.status_code == 200:
            client_secret = response.json()
            print(f"Session created successfully. Client secret: {client_secret}")
        else:
            print(f"Error: {response.status_code}")
            print(response.text)
    
    except Exception as e:
        print(f"Exception occurred: {str(e)}")

if __name__ == "__main__":
    print("Voice Assistant Bot Test")
    print("-----------------------")
    
    # Ask user which test to run
    print("Select a test to run:")
    print("1. Test immediate call")
    print("2. Test session creation")
    
    choice = "1"
    
    if choice == "1":
        if not TO_PHONE_NUMBER:
            TO_PHONE_NUMBER = input("Enter the phone number to call (E.164 format, e.g., +1234567890): ")
        test_immediate_call()
    elif choice == "2":
        test_session_creation()
    else:
        print("Invalid choice. Please run the script again and select 1 or 2.")