import requests


def download_github_zip(owner, repo, branch='main', output_filename=None):
    url = f"https://github.com/{owner}/{repo}/archive/refs/heads/{branch}.zip"
    if output_filename is None:
        output_filename = f"{repo}-{branch}.zip"
    response = requests.get(url, stream=True)
    response.raise_for_status()
    with open(output_filename, 'wb') as f:
        for chunk in response.iter_content(chunk_size=8192):
            f.write(chunk)
    print(f"Fichier téléchargé : {output_filename}")

# Test
download_github_zip('Pulongon', 'Shei-Pa-National-Park-Study', 'main')