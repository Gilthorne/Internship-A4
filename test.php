<?php
$url = "http://hivecore.famnit.upr.si:6666/api/chat";

$data = [
    "model" => "hf.co/unsloth/Qwen3-4b-Instruct-2507-GGUF:UD-Q4_K_XL",
    "stream" => false,
    "keep_alive" => "5m",
    "messages" => [
        [
            "role" => "system",
            "content" => "be usefull"
        ],
        [
            "role" => "user",
            "content" => "who teaches in referat?\n"
        ]
    ]
];

$ch = curl_init($url);
curl_setopt($ch, CURLOPT_RETURNTRANSFER, true);
curl_setopt($ch, CURLOPT_POST, true);
curl_setopt($ch, CURLOPT_HTTPHEADER, [
    "Content-Type: application/json"
]);
curl_setopt($ch, CURLOPT_POSTFIELDS, json_encode($data));

$response = curl_exec($ch);

if (curl_errno($ch)) {
    echo "cURL Error: " . curl_error($ch);
} else {
    echo $response;
}

curl_close($ch);
?>
