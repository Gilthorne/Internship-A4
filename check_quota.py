#!/usr/bin/env python3
import os
import time
import requests
from datetime import datetime
from dotenv import load_dotenv

load_dotenv()

API_KEY = os.getenv("ELSEVIER_API_KEY")

def check_quota():
    if not API_KEY:
        print("Error: ELSEVIER_API_KEY not found in environment")
        return

    url = "https://api.elsevier.com/content/abstract/doi/10.1016/j.bbrc.2024.151090"
    headers = {
        "X-ELS-APIKey": API_KEY,
        "Accept": "application/json"
    }

    try:
        response = requests.get(url, headers=headers, timeout=10)
        
        limit = response.headers.get("X-RateLimit-Limit", "N/A")
        remaining = response.headers.get("X-RateLimit-Remaining", "N/A")
        reset_timestamp = response.headers.get("X-RateLimit-Reset", None)

        print(f"Quota Limit:      {limit}")
        print(f"Quota Remaining: {remaining}")
        
        if reset_timestamp:
            try:
                reset_time = datetime.fromtimestamp(int(reset_timestamp))
                now = datetime.now()
                time_left = reset_time - now

                print(f"Quota Resets At: {reset_time.strftime('%Y-%m-%d %H:%M:%S')}")
                
                if time_left.total_seconds() > 0:
                    hours = int(time_left.total_seconds() // 3600)
                    minutes = int((time_left.total_seconds() % 3600) // 60)
                    print(f"Time Until Reset: {hours}h {minutes}m")
                else: 
                    print("Quota should have already reset")
            except ValueError: 
                print(f"X-RateLimit-Reset:  {reset_timestamp} (invalid format)")
        else:
            print("X-RateLimit-Reset: Not provided by API")

    except requests.RequestException as e:
        print(f"Error calling API: {e}")


if __name__ == "__main__":
    check_quota()
