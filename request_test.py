import requests
import json
from dotenv import load_dotenv
import os
import mysql.connector as sql


load_dotenv()


input_files = open('ResearchTestLinks.json')
json_decode=json.load(input_files)

db_connect=sql.connect(
    user = os.getenv('DB_USER'),
    password = os.getenv('DB_PASSWORD'),
    host = os.getenv('DB_HOST'),
    database = os.getenv('DB_NAME'),
    port = int(os.getenv('DB_PORT'))
)

response = requests.get(
    "https://api.elsevier.com/content/article/pii/S1574954125004352",
    headers={'X-ELS-APIKey': os.getenv('ELSEVIER_API_KEY'), 
             'Accept': 'application/json'}
)


print(b'Data availability' in response.content)
print (response.status_code)