import json
import os
import re
import uuid

from flask import Flask, jsonify, request
import requests

app = Flask(__name__)

URL = "https://www.perplexity.ai/rest/sse/perplexity_ask"

session_context_uuid = str(uuid.uuid4())

# Conversation state
LAST_BACKEND_UUID = None
READ_WRITE_TOKEN = None
FRONTEND_CONTEXT_UUID = None

headers = {
    "User-Agent": (
        "Mozilla/5.0 (Linux; Android 10; K) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/154.0.0.0 Mobile Safari/537.36"
    ),
    "Accept": "text/event-stream",
    "Accept-Encoding": "gzip, deflate, br, zstd",
    "Content-Type": "application/json",
    "pragma": "no-cache",
    "cache-control": "no-cache",
    "origin": "https://www.perplexity.ai",
    "referer": "https://www.perplexity.ai/",
    "accept-language": "en-US,en;q=0.9",
    "Cookie": "",
}


def is_valid_header_key(key):
    key = str(key).strip()

    if not key or key.startswith(":"):
        return False

    return bool(re.match(r"^[a-zA-Z0-9\-_]+$", key))


def get_proxies():
    proxy_url = os.environ.get("PROXY_URL", "").strip()

    if not proxy_url:
        return None

    return {
        "http": proxy_url,
        "https": proxy_url,
    }


def capture_state(data_obj):
    global LAST_BACKEND_UUID
    global READ_WRITE_TOKEN
    global FRONTEND_CONTEXT_UUID

    if isinstance(data_obj, dict):

        backend = data_obj.get("backend_uuid")

        if isinstance(backend, str) and backend:
            LAST_BACKEND_UUID = backend

        token = data_obj.get("read_write_token")

        if isinstance(token, str) and token:
            READ_WRITE_TOKEN = token

        context = data_obj.get("frontend_context_uuid")

        if isinstance(context, str) and context:
            FRONTEND_CONTEXT_UUID = context

        for value in data_obj.values():
            capture_state(value)

    elif isinstance(data_obj, list):

        for item in data_obj:
            capture_state(item)


def extract_final_text(data_obj):

    if isinstance(data_obj, dict):

        if "text" in data_obj:
            value = data_obj["text"]

            if isinstance(value, str):
                return value

        if "answer" in data_obj:
            value = data_obj["answer"]

            if isinstance(value, str):
                return value

        if "snippet" in data_obj:
            value = data_obj["snippet"]

            if isinstance(value, str):
                return value

        for value in data_obj.values():

            result = extract_final_text(value)

            if result:
                return result

    elif isinstance(data_obj, list):

        for item in data_obj:

            result = extract_final_text(item)

            if result:
                return result

    return None


def send_message(user_text):

    global LAST_BACKEND_UUID
    global READ_WRITE_TOKEN
    global FRONTEND_CONTEXT_UUID

    frontend_uuid = str(uuid.uuid4())

    is_followup = READ_WRITE_TOKEN is not None

    params = {
        "attachments": [],
        "language": "en-US",
        "timezone": "Africa/Tunis",
        "search_focus": "writing",
        "sources": [],
        "frontend_uuid": frontend_uuid,
        "mode": "copilot",
        "model_preference": "turbo",
        "is_related_query": False,
        "is_sponsored": False,
        "prompt_source": "user",
        "query_source": "followup" if is_followup else "home",
        "is_incognito": False,
        "local_search_enabled": False,
        "use_schematized_api": True,
        "send_back_text_in_streaming_api": False,
        "supported_block_use_cases": [
            "answer_modes",
            "media_items",
            "inline_entity_cards",
            "diff_blocks",
            "canvas_mode",
            "answer_tabs",
            "in_context_suggestions",
        ],
        "dsl_query": user_text,
        "skip_search_enabled": False,
        "source": "mweb",
        "client_search_results_cache_key": frontend_uuid,
        "version": "2.18",
        "followup_source": "link",
    }

    if is_followup:

        params["last_backend_uuid"] = LAST_BACKEND_UUID
        params["read_write_token"] = READ_WRITE_TOKEN

        if FRONTEND_CONTEXT_UUID:
            params["frontend_context_uuid"] = FRONTEND_CONTEXT_UUID

    else:

        params["frontend_context_uuid"] = session_context_uuid

    payload = {
        "params": params,
        "query_str": user_text,
    }

    req_headers = {
        key: value
        for key, value in headers.copy().items()
        if is_valid_header_key(key)
    }

    req_headers["x-request-id"] = frontend_uuid

    if is_followup and LAST_BACKEND_UUID:

        req_headers["referer"] = (
            f"https://www.perplexity.ai/search/{LAST_BACKEND_UUID}"
        )

    response = requests.post(
        URL,
        json=payload,
        headers=req_headers,
        stream=True,
        proxies=get_proxies(),
        timeout=60,
        verify=False,
    )

    if response.status_code != 200:

        raise RuntimeError(
            f"Perplexity returned HTTP {response.status_code}"
        )

    final_reply = ""

    for line in response.iter_lines():

        if not line:
            continue

        if isinstance(line, bytes):
            decoded = line.decode("utf-8", errors="ignore")
        else:
            decoded = line

        if not decoded.startswith("data:"):
            continue

        raw_data = decoded[5:].strip()

        try:

            data = json.loads(raw_data)

            capture_state(data)

            extracted = extract_final_text(data)

            if extracted:

                extracted = extracted.strip()

                if len(extracted) > len(final_reply):
                    final_reply = extracted

        except (json.JSONDecodeError, TypeError):
            continue

    if not final_reply:
        raise RuntimeError(
            "No valid response returned from Perplexity."
        )

    return re.sub(r"\s+", " ", final_reply).strip()


@app.route("/", methods=["GET"])
def home():

    return jsonify({
        "status": "online",
        "service": "MaskAi",
        "endpoints": {
            "POST /ask": "Send a message"
        }
    })


@app.route("/ask", methods=["POST"])
def ask():

    data = request.get_json(silent=True)

    if not isinstance(data, dict):
        return jsonify({
            "error": "JSON body required"
        }), 400

    prompt = data.get("prompt")

    if not isinstance(prompt, str) or not prompt.strip():
        return jsonify({
            "error": "Field 'prompt' is required."
        }), 400

    try:

        reply = send_message(prompt.strip())

        return jsonify({
            "response": reply
        })

    except Exception as e:

        return jsonify({
            "error": f"Stream failure: {str(e)}"
        }), 500


if __name__ == "__main__":

    port = int(os.environ.get("PORT", 5000))

    app.run(
        host="0.0.0.0",
        port=port
    )
