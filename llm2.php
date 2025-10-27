<?php
define('ELSEVIER_API_KEY', '5e0c4b89c3dc998fda16c52f50e7f4a2');
define('LLM_ENDPOINT', 'http://hivecore.famnit.upr.si:6666/api/chat');
global $OLLAMA_ENDPOINT;

// 1. Fetch paper content from Elsevier
function fetchElsevierPaper($doi) {
    $url = "https://api.elsevier.com/content/article/doi/" . urlencode($doi);
    
    $ch = curl_init();
    curl_setopt_array($ch, [
        CURLOPT_URL => $url,
        CURLOPT_RETURNTRANSFER => true,
        CURLOPT_HTTPHEADER => [
            'Accept: text/plain',
            'X-ELS-APIKey: ' . ELSEVIER_API_KEY
        ],
        CURLOPT_SSL_VERIFYPEER => false,
        CURLOPT_SSL_VERIFYHOST => 0
    ]);
    
    $response = curl_exec($ch);
    if(curl_errno($ch)) {
        $error = curl_error($ch);
        curl_close($ch);
        throw new Exception("Elsevier API failed: $error");
    }
    curl_close($ch);
    return $response;
}

function queryLLM($content) {
    $OLLAMA_ENDPOINT = "http://hivecore.famnit.upr.si:6666/api/chat";
    // 1. Define the System Instructions (the rules for the LLM)
    $system_instructions = <<<PROMPT
    EXTRACT DATA AVAILABILITY LINKS FROM THE PROVIDED PAPER.
    You MUST return STRICT JSON format. Do not include any other text or markdown.
    The JSON structure must be:
    {
      "links": [
        {"text": "Description", "url": "URL_OR_DOI"},
        // ... more entries
      ]
    }
    RULES:
    1. Only include actual data/resources links (e.g., datasets, code repositories).
    2. Use DOI URLs where available (format: https://doi.org/...).
    3. If no links are found, you MUST return {"links": []}.
    PROMPT;
    $user_content = "PAPER CONTENT:\n\n" . $content;
    $request_payload = [
        'model' => 'hf.co/unsloth/Qwen3-4b-Instruct-2507-GGUF:UD-Q4_K_XL',
        'options' => [
            'temperature' => 0.7,
            'top_p' => 0.8,
            'top_k' => 20,
            'min_p' => 0.0,
            'presence_penalty' => 0.1
        ],
        'stream' => false,
        'keep_alive' => '5m',
        'messages' => [
            [
                'role' => 'system',
                'content' => $system_instructions
            ],
            [
                'role' => 'user',
                'content' => $user_content
            ]
        ]
    ];

    // 4. Convert the PHP array to a JSON string
    $json_payload = json_encode($request_payload);
    if ($json_payload === false) {
        throw new Exception("Failed to encode JSON payload: " . json_last_error_msg());
    }

    // 5. Initialize cURL
    $ch = curl_init();
    if (!$ch) {
        throw new Exception("Failed to initialize cURL");
    }

    // 6. Set cURL options to send JSON
    // 1. Do not verify the certificate's authenticity
    curl_setopt($ch, CURLOPT_SSL_VERIFYPEER, false);

    // 2. Do not verify that the certificate's name matches the host
    curl_setopt($ch, CURLOPT_SSL_VERIFYHOST, 0);
    curl_setopt($ch, CURLOPT_URL, $OLLAMA_ENDPOINT);
curl_setopt($ch, CURLOPT_RETURNTRANSFER, true);
curl_setopt($ch, CURLOPT_POST, true);
curl_setopt($ch, CURLOPT_HTTPHEADER, [
    "Content-Type: application/json"
]);
curl_setopt($ch, CURLOPT_POSTFIELDS, json_encode($request_payload));

    $response = curl_exec($ch);

    // 8. Handle cURL errors (as requested)
    if (curl_errno($ch)) {
        $error_msg = curl_error($ch);
        curl_close($ch);
        throw new Exception("cURL Error: " . $error_msg);
    }
    curl_close($ch);

    // 9. Process the response (with a critical fix)
    echo "--- RAW RESPONSE ---\n" . $response . "\n--- END RAW ---\n\n";

    $result = json_decode($response, true);

    // *** CRITICAL FIX ***
    // The /api/chat endpoint returns the message in ['message']['content'],
    // NOT in ['response'] like the /api/generate endpoint does.
    if (!$result || !isset($result['message']['content'])) {
        throw new Exception("Invalid LLM response structure. Expected 'message.content'.");
    }

    // Get the actual text output from the LLM
    $llm_output = $result['message']['content'];

    // Try direct JSON parse first
    $parsed = json_decode($llm_output, true);
    
    // If JSON parse failed, try text extraction
    if(json_last_error() !== JSON_ERROR_NONE) {
        echo "JSON parse failed, attempting text extraction...\n";
        // Assuming extractLinksFromText is defined elsewhere
        $parsed = extractLinksFromText($llm_output); 
    }
 if(!isset($parsed['links'])) {
        throw new Exception("Failed to extract links structure from LLM output");
    }

    return $parsed['links'];
}


function extractLinksFromText($text) {
    $links = [];
    
    // Look for DOI patterns
    preg_match_all('/\b(10\.[0-9]{4,}(?:\.[0-9]+)*\/[^\s\]]+)/i', $text, $doiMatches);
    // Look for URL patterns
    preg_match_all('/https?:\/\/[^\s\]]+/i', $text, $urlMatches);

    // Combine matches and format
    $allUrls = array_merge($doiMatches[0], $urlMatches[0]);
    foreach($allUrls as $url) {
        // Find preceding description (look back 150 characters)
        preg_match('/([^\n\.]+)\.?\s*(?:https?|doi)/i', 
                 substr($text, max(0, strpos($text, $url)-150), 150), 
                 $textMatches);
        
        $description = $textMatches[1] ?? 'Data resource';
        $links[] = [
            'text' => trim(str_replace(["\n", "\r"], ' ', $description)),
            'url' => strpos($url, 'doi.org/') === false && preg_match('/^10\./', $url)
                    ? 'https://doi.org/' . $url
                    : $url
        ];
    }

    return ['links' => array_unique($links, SORT_REGULAR)];
}


// Main execution
if ($argc < 2) die("Usage: php paper_processor.php <DOI>\n");

try {
    $doi = $argv[1];
    echo "Fetching paper: $doi\n";
    $content = fetchElsevierPaper($doi);
    
    echo "Processing with LLM...\n";
    $links = queryLLM($content);
    
    echo "Success! Extracted Links:\n";
    echo json_encode($links, JSON_PRETTY_PRINT | JSON_UNESCAPED_SLASHES) . "\n";
    
} catch(Exception $e) {
    die("\nERROR: " . $e->getMessage() . "\n");
}
