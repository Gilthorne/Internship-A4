import requests

def download_github_zip(owner, repo, branch='main'):
    url = f"https://github.com/{owner}/{repo}/archive/refs/heads/{branch}.zip"
    output_filename = f"{repo}-{branch}.zip"
    response = requests.get(url)
    response.raise_for_status()
    with open(output_filename, 'wb') as f:
        f.write(response.content)
    print(f"Fichier téléchargé : {output_filename}")

# Test
download_github_zip('Pulongon', 'Shei-Pa-National-Park-Study')