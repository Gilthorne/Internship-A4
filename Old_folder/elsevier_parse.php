<?php
define('API_KEY', '5e0c4b89c3dc998fda16c52f50e7f4a2');

if ($argc < 2) {
    die("Usage: php elsevier_parse.php <DOI>\n");
}

$doi = $argv[1];

function getElsevierAPIData($doi) {
    // Récupérer les données directement depuis l'API Elsevier
    $apiUrl = 'https://api.elsevier.com/content/article/doi/' . urlencode($doi) . '?view=FULL';
    
    $ch = curl_init();
    curl_setopt_array($ch, [
        CURLOPT_URL => $apiUrl,
        CURLOPT_RETURNTRANSFER => true,
        CURLOPT_HTTPHEADER => [
            'X-ELS-APIKey: ' . API_KEY,
            'Accept: application/json'
        ],
        CURLOPT_TIMEOUT => 30
    ]);
    
    $response = curl_exec($ch);
    $httpCode = curl_getinfo($ch, CURLINFO_HTTP_CODE);
    
    if (curl_errno($ch)) {
        echo "Erreur cURL: " . curl_error($ch) . "\n";
        curl_close($ch);
        return null;
    }
    
    curl_close($ch);
    
    if ($httpCode !== 200) {
        echo "Erreur API HTTP: $httpCode\n";
        return null;
    }
    
    $data = json_decode($response, true);
    
    if (!$data) {
        echo "Erreur lors du parsing JSON de la réponse API\n";
        return null;
    }
    
    return $data;
}

function extractDataAvailabilityFromAPI($originalText) {
    // Patterns pour extraire la section Data Availability du texte de l'API
    $patterns = [
        // Pattern principal: chercher "Data availability" suivi du contenu
        '/Data\s+availability\s+(.*?)(?=\s*(?:1\s+Introduction|Declaration\s+of\s+|CRediT\s+|Funding\s+|Acknowledgement|References|$))/si',
        
        // Pattern alternatif plus spécifique
        '/(This\s+work\s+is\s+partly\s+based\s+on\s+data.*?Repository[^.]*\.)/si',
        
        // Pattern pour capturer jusqu'à "1 Introduction"
        '/Data\s+availability\s+(.*?)(?=\s*1\s+Introduction)/si'
    ];
    
    foreach ($patterns as $pattern) {
        if (preg_match($pattern, $originalText, $matches)) {
            $section = trim($matches[1]);
            // Vérifier que la section n'est pas trop courte ou trop longue
            if (strlen($section) > 50 && strlen($section) < 2000) {
                return $section;
            }
        }
    }
    
    return null;
}

function extractRepositoryLinksFromText($text) {
    $repositories = [];
    
    if (empty($text)) {
        return $repositories;
    }
    
    // Recherche BExIS avec patterns spécifiques
    $bexisPatterns = [
        '/(https?:\/\/(?:www\.)?bexis\.uni-jena\.de\/[^\s"\'<>)]+)/i',
        '/Biodiversity\s+Exploratories\s+Information\s+System\s+BExIS/i'
    ];
    
    foreach ($bexisPatterns as $pattern) {
        if (preg_match($pattern, $text, $matches)) {
            if (isset($matches[1]) && filter_var($matches[1], FILTER_VALIDATE_URL)) {
                $repositories[] = [
                    'type' => 'BExIS',
                    'url' => rtrim($matches[1], '.,;:)'),
                    'source' => 'Data Availability Section'
                ];
            } else {
                // Mention trouvée sans URL spécifique
                $repositories[] = [
                    'type' => 'BExIS',
                    'url' => 'https://www.bexis.uni-jena.de',
                    'source' => 'Data Availability Mention'
                ];
            }
            break;
        }
    }
    
    // Recherche Mendeley Data - améliorer l'extraction du DOI
    $mendeleyPatterns = [
        // Pattern pour capturer le DOI Mendeley spécifique dans le contexte
        '/Mendeley\s+Data\s+Repository[^\(]*\(([^)]*(?:10\.17632\/[\w\d.\/]+)[^)]*)\)/i',
        // Pattern direct pour le DOI
        '/(10\.17632\/[\w\d.\/]+)/i',
        // Pattern pour URL complète
        '/(https?:\/\/(?:www\.)?data\.mendeley\.com\/datasets\/[\w\d\/]+)/i',
        // Pattern pour mention générale
        '/Mendeley\s+Data\s+Repository/i'
    ];
    
    $mendeleyFound = false;
    
    foreach ($mendeleyPatterns as $pattern) {
        if (preg_match($pattern, $text, $matches)) {
            if (isset($matches[1])) {
                $match = $matches[1];
                
                // Si on a trouvé un DOI dans le contexte, l'extraire
                if (preg_match('/(10\.17632\/[\w\d.\/]+)/', $match, $doiMatch)) {
                    $doi = $doiMatch[1];
                    $repositories[] = [
                        'type' => 'Mendeley Data',
                        'url' => "https://doi.org/$doi",
                        'source' => 'Data Availability DOI Reference'
                    ];
                    $mendeleyFound = true;
                    break;
                } else if (strpos($match, '10.17632/') === 0) {
                    // DOI direct
                    $repositories[] = [
                        'type' => 'Mendeley Data',
                        'url' => "https://doi.org/$match",
                        'source' => 'Data Availability DOI Reference'
                    ];
                    $mendeleyFound = true;
                    break;
                } else if (strpos($match, 'https://') === 0) {
                    // URL complète
                    $repositories[] = [
                        'type' => 'Mendeley Data',
                        'url' => rtrim($match, '.,;:)'),
                        'source' => 'Data Availability Section'
                    ];
                    $mendeleyFound = true;
                    break;
                }
            } else {
                // Mention trouvée sans URL/DOI spécifique
                if (!$mendeleyFound) {
                    $repositories[] = [
                        'type' => 'Mendeley Data',
                        'url' => 'https://data.mendeley.com',
                        'source' => 'Data Availability Mention'
                    ];
                    $mendeleyFound = true;
                }
            }
        }
    }
    
    return $repositories;
}

function extractExcelCSVFiles($apiData) {
    $files = [];
    
    if (!$apiData || !isset($apiData['full-text-retrieval-response']['objects']['object'])) {
        return $files;
    }
    
    $objects = $apiData['full-text-retrieval-response']['objects']['object'];
    if (!is_array($objects)) {
        $objects = [$objects];
    }
    
    foreach ($objects as $object) {
        $ref = $object['@ref'] ?? 'unknown';
        $mimetype = $object['@mimetype'] ?? '';
        $url = $object['$'] ?? '';
        
        // Identifier les fichiers Excel/CSV
        if (strpos($mimetype, 'excel') !== false || 
            strpos($mimetype, 'csv') !== false || 
            preg_match('/\.(xlsx?|csv)$/i', $ref)) {
            
            $files[] = [
                'ref' => $ref,
                'type' => (strpos($mimetype, 'excel') !== false || preg_match('/\.xlsx?$/i', $ref)) ? 'Excel' : 'CSV',
                'url' => $url,
                'size' => $object['@size'] ?? 'unknown'
            ];
        }
    }
    
    return $files;
}

// === EXECUTION PRINCIPALE ===

echo "=== ANALYSE DE L'ARTICLE ELSEVIER ===\n";
echo "DOI: $doi\n\n";

// 1. Récupérer les données directement depuis l'API Elsevier
echo "1. Récupération des données depuis l'API Elsevier...\n";
$apiData = getElsevierAPIData($doi);

if (!$apiData) {
    die("Impossible de récupérer les données depuis l'API Elsevier\n");
}

if (!isset($apiData['full-text-retrieval-response'])) {
    die("Réponse API incomplète - pas de données full-text\n");
}

echo "✓ Données API récupérées avec succès\n\n";

// Sauvegarder la réponse API pour debug (optionnel)
$debugFile = 'debug_api_' . str_replace(['/', '.'], ['_', '_'], $doi) . '.json';
file_put_contents($debugFile, json_encode($apiData, JSON_PRETTY_PRINT | JSON_UNESCAPED_UNICODE));
echo "Debug: Réponse API sauvegardée dans $debugFile\n";

// 2. Extraire le PII
$pii = $apiData['full-text-retrieval-response']['coredata']['pii'] ?? 'Non trouvé';
echo "PII: $pii\n\n";

// 3. Extraire le texte original
$originalText = $apiData['full-text-retrieval-response']['originalText'] ?? '';

if (empty($originalText)) {
    die("Texte original non disponible dans les données API\n");
}

echo "2. Extraction de la section Data Availability depuis l'API...\n";
echo "Longueur du texte original: " . strlen($originalText) . " caractères\n";

// 4. Extraire la section Data Availability
$dataAvailabilityText = extractDataAvailabilityFromAPI($originalText);

if ($dataAvailabilityText) {
    echo "✓ Section Data Availability trouvée !\n";
    echo "Longueur: " . strlen($dataAvailabilityText) . " caractères\n\n";
    
    echo "=== CONTENU DE LA SECTION DATA AVAILABILITY ===\n";
    echo str_repeat("-", 60) . "\n";
    echo $dataAvailabilityText . "\n";
    echo str_repeat("-", 60) . "\n\n";
    
    // 5. Analyser les dépôts de données dans la section
    echo "3. Analyse des dépôts de données...\n";
    $repositories = extractRepositoryLinksFromText($dataAvailabilityText);
    
    if (!empty($repositories)) {
        echo "✓ Dépôts de données identifiés:\n";
        foreach ($repositories as $i => $repo) {
            echo "  " . ($i + 1) . ". {$repo['type']}: {$repo['url']}\n";
            echo "     Source: {$repo['source']}\n";
        }
    } else {
        echo "✗ Aucun dépôt de données identifié automatiquement\n";
    }
    echo "\n";
} else {
    echo "✗ Section Data Availability non trouvée dans le texte API\n";
    echo "Recherche de mots-clés dans le texte complet...\n";
    
    // Recherche alternative de mots-clés
    $keywords = ['BExIS', 'Mendeley', 'Data Repository', 'Biodiversity Exploratories', 'data availability'];
    foreach ($keywords as $keyword) {
        $count = substr_count(strtolower($originalText), strtolower($keyword));
        if ($count > 0) {
            echo "- '$keyword' trouvé $count fois\n";
            
            // Afficher contexte de la première occurrence
            $pos = stripos($originalText, $keyword);
            if ($pos !== false) {
                $start = max(0, $pos - 100);
                $context = substr($originalText, $start, 200);
                echo "  Contexte: " . trim($context) . "\n\n";
            }
        }
    }
    $repositories = [];
}

// 6. Extraire les fichiers Excel/CSV
echo "\n4. Extraction des fichiers Excel/CSV depuis l'API...\n";
$excelCsvFiles = extractExcelCSVFiles($apiData);

if (!empty($excelCsvFiles)) {
    echo "✓ Fichiers Excel/CSV trouvés:\n";
    foreach ($excelCsvFiles as $i => $file) {
        echo "  " . ($i + 1) . ". {$file['type']}: {$file['ref']}\n";
        echo "     URL: {$file['url']}\n";
        echo "     Taille: {$file['size']} bytes\n\n";
    }
} else {
    echo "✗ Aucun fichier Excel/CSV trouvé\n";
}

// 7. Sauvegarder les résultats
$results = [
    'doi' => $doi,
    'pii' => $pii,
    'data_availability_section' => $dataAvailabilityText,
    'data_availability_found' => !empty($dataAvailabilityText),
    'repositories' => $repositories ?? [],
    'excel_csv_files' => $excelCsvFiles ?? [],
    'extraction_date' => date('Y-m-d H:i:s'),
    'source' => 'API Data - Live Request'
];

$filename = 'data_availability_extraction_' . str_replace(['/', '.'], ['_', '_'], $doi) . '.json';
file_put_contents($filename, json_encode($results, JSON_PRETTY_PRINT | JSON_UNESCAPED_UNICODE));

echo "\n=== RÉSUMÉ ===\n";
echo "Section Data Availability: " . ($dataAvailabilityText ? 'Trouvée' : 'Non trouvée') . "\n";
echo "Dépôts de données: " . count($repositories ?? []) . "\n";
echo "Fichiers Excel/CSV: " . count($excelCsvFiles ?? []) . "\n";
echo "Résultats sauvegardés dans: $filename\n";

// 8. Afficher la section Data Availability extraite pour debug
if ($dataAvailabilityText) {
    echo "\n=== DEBUG: SECTION EXTRAITE ===\n";
    echo "Début: " . substr($dataAvailabilityText, 0, 100) . "...\n";
    echo "Fin: ..." . substr($dataAvailabilityText, -100) . "\n";
}

?>