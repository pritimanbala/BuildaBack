import os
import requests
from dotenv import load_dotenv

# Load environment variables from the .env file
load_dotenv()

# 1. Configuration
# Retrieve the DronaHQ API key securely from your .env file
API_KEY = os.environ.get("DronaHQ")
WEBHOOK_URL = "https://agents-backend.dronahq.com/webhook/906250f9-115d-40ab-b87c-6e22ce5cfa41" 

# 2. Setup Headers
# DronaHQ requires the API key to be passed in the 'api-key' header
headers = {
    "api-key": API_KEY,
    "Content-Type": "application/json"
}

# 3. Define the Payload
# The data passed to the DronaHQ agent
payload = {
    "company_type": "B2B SaaS in Chennai",
    "number_to_shortlist": 5
}

# 4. Execute the Call
if not API_KEY:
    print("Error: 'DronaHQ' key not found. Check your .env file.")
else:
    try:
        response = requests.post(WEBHOOK_URL, headers=headers, json=payload)
        
        if response.status_code == 200:
            print("Agent executed successfully!")
            print(response.json())
        else:
            print(f"Error: {response.status_code}")
            print(response.text)

    except Exception as e:
        print(f"An error occurred: {e}")