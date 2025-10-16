import sys
import requests
import urllib.parse

API_KEY = '5e0c4b89c3dc998fda16c52f50e7f4a2'

if len(sys.argv) < 2:
    sys.exit("Usage: python elsevier_parse.py <DOI>")

doi = sys.argv[1]

# Test multiple API endpoints
endpoints = {
    'article': f'https://api.elsevier.com/content/article/doi/{urllib.parse.quote(doi)}',
    'abstract': f'https://api.elsevier.com/content/abstract/doi/{urllib.parse.quote(doi)}',
    'search': f'https://api.elsevier.com/content/search/scopus?query=DOI({urllib.parse.quote(doi)})'
}

for name, url in endpoints.items():
    print(f"\n=== Testing endpoint: {name} ===")
    
    headers = {
        'X-ELS-APIKey': API_KEY,
        'Accept': 'application/json'
    }
    
    try:
        response = requests.get(url, headers=headers)
        
        print(f"HTTP Code: {response.status_code}")
        print(f"Headers:\n{dict(response.headers)}\n")
        
        if response.status_code != 200:
            print(f"Error: HTTP status {response.status_code}")
        else:
            with open(f"response_{name}.json", "w", encoding="utf-8") as f:
                f.write(response.text)
            print(f"Response body saved to response_{name}.json")
        
    except Exception as e:
        print(f"Error: {str(e)}")

print("\nTroubleshooting steps:")
print("1. Verify key at https://dev.elsevier.com/apikey_manager")
print("2. Check response_*.json files")
print("3. Inspect response headers")
print("4. Test with DOI 10.1016/j.cub.2020.06.022 (known working)")
