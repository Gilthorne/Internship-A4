import fitz

doc = fitz.open("article.pdf")
links = []

for page_num in range(len(doc)):
    page = doc[page_num]
    text = page.get_text()
    
    if "data availability" in text.lower():
        # Trouver position de Data availability
        data_avail = page.search_for("Data availability")
        if data_avail:
            start_y = data_avail[0].y0
            
            # Trouver fin de section
            end_y = page.rect.height
            refs = page.search_for("References")
            if refs and refs[0].y0 > start_y:
                end_y = refs[0].y0
            
            # Récupérer liens dans cette zone
            for link in page.get_links():
                if "uri" in link and start_y <= link["from"][1] <= end_y:
                    links.append(link["uri"])

doc.close()

# Supprimer doublons
links = list(set(links))
print(f"Liens trouvés: {len(links)}")
for link in links:
    print(link)