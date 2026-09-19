import os
import requests
import json
from dotenv import load_dotenv

# Load environment variables from the .env file
load_dotenv()

# 1. Configuration
API_KEY = os.environ.get("DronaHQ")
WEBHOOK_URL = os.environ.get("webhook_fitment")

# 2. Setup Headers
headers = {
    "api-key": API_KEY,
    "Content-Type": "application/json"
}

# 3. Format the Test Data
# Mapping your raw URL list to the expected "url" key
raw_websites = [
    {"website_url": "https://lovable.dev"},
    {"website_url": "https://www.tessl.io"},
    {"website_url": "https://www.flex.ai"},
    {"website_url": "https://n8n.io"},
    {"website_url": "https://bfl.ai"},
    {"website_url": "https://legora.com"},
    {"website_url": "https://www.tacto.ai"},
    {"website_url": "https://www.photoroom.com"},
    {"website_url": "https://www.port.io"},
    {"website_url": "https://www.vertice.one"},
    {"website_url": "http://nelly-solutions.de"},
    {"website_url": "https://www.flowdesk.co"},
    {"website_url": "https://granola.ai"},
    {"website_url": "https://www.finom.co"},
    {"website_url": "http://taktile.com"},
    {"website_url": "https://www.primer.io"},
    {"website_url": "http://fetcherr.io"},
    {"website_url": "https://www.incident.io"},
    {"website_url": "https://www.robinai.com"},
    {"website_url": "http://doccla.com"},
    {"website_url": "https://www.autone.io"},
    {"website_url": "https://qdrant.tech"},
    {"website_url": "http://weaviate.io"},
    {"website_url": "https://monta.com"},
    {"website_url": "https://www.hcompany.ai"},
    {"website_url": "https://www.sosafe-awareness.com"},
    {"website_url": "https://www.remberg.de"},
    {"website_url": "https://www.swan.io"},
    {"website_url": "http://finmid.com"},
    {"website_url": "http://legalfly.com"},
    {"website_url": "https://www.sweep.net"},
    {"website_url": "https://www.73strings.com"},
    {"website_url": "https://www.senio.net"},
    {"website_url": "http://www.trigo.com"},
    {"website_url": "https://www.advastore.com"},
    {"website_url": "http://www.charles.com"},
    {"website_url": "https://www.moralis.io"},
    {"website_url": "https://www.gitpod.io"},
    {"website_url": "https://www.v7labs.com"},
    {"website_url": "https://www.cledara.com"},
    {"website_url": "https://www.fonoa.com"}
]

formatted_websites = [{"url": site["website_url"]} for site in raw_websites]

# Structuring the payload to match your DronaHQ webhook schema
payload = {
    "websites": formatted_websites,
    "user_prompt": {
        "location": "Europe",
        "industry": "B2B SaaS",
        "minimum_revenue": 500000,
        "raw_query": "Find me B2b saas companies from europe, make sure they have more than 500k euro revenue."
    }
}

# 4. Execute the Call
if not API_KEY or not WEBHOOK_URL:
    print("Error: Missing 'DronaHQ' or 'webhook' in your .env file.")
else:
    try:
        print("Sending prospect data to ICP Fitment Agent...\n")
        response = requests.post(WEBHOOK_URL, headers=headers, json=payload)
        
        if response.status_code == 200:
            print("✅ Agent executed successfully!\n")
            
            # Print the formatted JSON response to see the 1-100 scores
            print(json.dumps(response.json(), indent=2))
        else:
            print(f"❌ Error: {response.status_code}")
            print(response.text)

    except Exception as e:
        print(f"An error occurred: {e}")