import requests
import json

API_KEY = '5e0c4b89c3dc998fda16c52f50e7f4a2'

response = requests.get(
    "https://api.elsevier.com/content/article/pii/S1574954125004352",
    headers={'X-ELS-APIKey': API_KEY}
)

print (response.status_code)