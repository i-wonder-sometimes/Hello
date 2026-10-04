import json
import os
import re
import uuid
import requests

from flask import Flask, jsonify, request


# ============================================================
# FLASK
# ============================================================

app = Flask(__name__)


# ============================================================
# ORIGINAL SETTINGS
# ============================================================

url = "https://www.perplexity.ai/rest/sse/perplexity_ask"

session_context_uuid = str(uuid.uuid4())


# ---- memory state ----
LAST_BACKEND_UUID = None
READ_WRITE_TOKEN = None
FRONTEND_CONTEXT_UUID = None


headers = {
    'User-Agent': (
        "Mozilla/5.0 (Linux; Android 10; K) AppleWebKit/537.36 (KHTML, like"
        " Gecko) Chrome/154.0.0.0 Mobile Safari/537.36"
    ),
    'Accept': "text/event-stream",
    'Accept-Encoding': "gzip, deflate, br, zstd",
    'Content-Type': "application/json",
    'pragma': "no-cache",
    'cache-control': "no-cache",
    'origin': "https://www.perplexity.ai",
    'referer': "https://www.perplexity.ai/",
    'accept-language': "en-US,en;q=0.9",
    'Cookie': "",
}


# ============================================================
# PROXY
# ============================================================

def get_proxies():
    proxy_url = os.environ.get("PROXY_URL", "").strip()

    if proxy_url:
        return {
            "http": proxy_url,
            "https": proxy_url,
        }

    return None


# ============================================================
# HEADER VALIDATION
# ============================================================

def is_valid_header_key(key):
    # Keep the exact behavior from the original script.
    #
    # HTTP/2 pseudo headers such as:
    # :method
    # :authority
    # :path
    # :scheme
    #
    # are intentionally rejected because requests generates
    # those itself.

    key_str = str(key).strip()

    if not key_str or key_str.startswith(":"):
        return False

    return bool(re.match(r"^[a-zA-Z0-9\-_]+$", key_str))


# ============================================================
# UPDATE HEADERS
# ============================================================

def update_headers(data):
    global headers

    if not data or not isinstance(data, dict):
        return {
            "error": "Invalid payload format, expected JSON object"
        }

    valid_items = []

    for k, v in data.items():

        clean_k = str(k).strip()
        clean_v = str(v).strip()

        if is_valid_header_key(clean_k):
            valid_items.append((clean_k, clean_v))

    updated_count = 0

    for key, value in valid_items:
        headers[key] = value
        updated_count += 1

    return {
        "message": f"Updated {updated_count} headers successfully."
    }


# ============================================================
# UPDATE COOKIES
# ============================================================

def update_cookies(data):
    global headers

    if not data or not isinstance(data, dict):
        return {
            "error": "Invalid payload format, expected JSON object"
        }

    items = [
        (str(k).strip(), str(v).strip())
        for k, v in data.items()
    ]

    cookie_str = "; ".join(
        [f"{k}={v}" for k, v in items]
    )

    headers["Cookie"] = cookie_str
    headers["cookie"] = cookie_str

    return {
        "message": "Cookies updated successfully."
    }


# ============================================================
# STATE CAPTURE
# ============================================================

def capture_state(data_obj):
    global LAST_BACKEND_UUID
    global READ_WRITE_TOKEN
    global FRONTEND_CONTEXT_UUID

    if isinstance(data_obj, dict):

        bu = data_obj.get("backend_uuid")

        if isinstance(bu, str) and bu:
            LAST_BACKEND_UUID = bu

        rwt = data_obj.get("read_write_token")

        if isinstance(rwt, str) and rwt:
            READ_WRITE_TOKEN = rwt

        fcu = data_obj.get("frontend_context_uuid")

        if isinstance(fcu, str) and fcu:
            FRONTEND_CONTEXT_UUID = fcu

        for v in data_obj.values():
            capture_state(v)

    elif isinstance(data_obj, list):

        for item in data_obj:
            capture_state(item)


# ============================================================
# RESPONSE EXTRACTION
# ============================================================

def extract_final_text(data_obj):

    if isinstance(data_obj, dict):

        if "text" in data_obj and isinstance(data_obj["text"], str):
            return data_obj["text"]

        if "answer" in data_obj and isinstance(data_obj["answer"], str):
            return data_obj["answer"]

        if "snippet" in data_obj and isinstance(data_obj["snippet"], str):
            return data_obj["snippet"]

        for v in data_obj.values():

            res = extract_final_text(v)

            if res:
                return res

    elif isinstance(data_obj, list):

        for item in data_obj:

            res = extract_final_text(item)

            if res:
                return res

    return None


# ============================================================
# ORIGINAL SEND MESSAGE LOGIC
# ============================================================

def send_message(user_text):

    global LAST_BACKEND_UUID
    global READ_WRITE_TOKEN
    global FRONTEND_CONTEXT_UUID

    frontend_uuid = str(uuid.uuid4())

    is_followup = READ_WRITE_TOKEN is not None


    # --------------------------------------------------------
    # EXACT ORIGINAL PARAMS
    # --------------------------------------------------------

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


    # --------------------------------------------------------
    # ORIGINAL FOLLOW-UP STATE
    # --------------------------------------------------------

    if is_followup:

        params["last_backend_uuid"] = LAST_BACKEND_UUID
        params["read_write_token"] = READ_WRITE_TOKEN

        if FRONTEND_CONTEXT_UUID:
            params["frontend_context_uuid"] = FRONTEND_CONTEXT_UUID

    else:

        params["frontend_context_uuid"] = session_context_uuid


    # --------------------------------------------------------
    # ORIGINAL PAYLOAD
    # --------------------------------------------------------

    payload = {
        "params": params,
        "query_str": user_text,
    }


    # --------------------------------------------------------
    # ORIGINAL HEADER CLEANING
    # --------------------------------------------------------

    req_headers = {
        k: v
        for k, v in headers.copy().items()
        if is_valid_header_key(k)
    }

    req_headers["x-request-id"] = frontend_uuid


    # --------------------------------------------------------
    # ORIGINAL FOLLOW-UP REFERER
    # --------------------------------------------------------

    if is_followup and LAST_BACKEND_UUID:

        req_headers["referer"] = (
            f"https://www.perplexity.ai/search/{LAST_BACKEND_UUID}"
        )


    # --------------------------------------------------------
    # ORIGINAL REQUEST
    # --------------------------------------------------------

    try:

        response = requests.post(
            url,
            data=json.dumps(payload),
            headers=req_headers,
            stream=True,
            proxies=get_proxies(),
            timeout=60,
        )


        # ----------------------------------------------------
        # STATUS
        # ----------------------------------------------------

        if response.status_code != 200:

            return {
                "ok": False,
                "error": (
                    f"Bad server response "
                    f"({response.status_code})."
                ),
                "status_code": response.status_code,
            }


        # ----------------------------------------------------
        # ORIGINAL SSE PARSING
        # ----------------------------------------------------

        final_reply = ""

        for line in response.iter_lines():

            if not line:
                continue

            if isinstance(line, bytes):

                decoded = line.decode(
                    "utf-8",
                    errors="ignore"
                )

            else:

                decoded = line


            if decoded.startswith("data: "):

                raw_data = decoded[6:].strip()

                try:

                    data = json.loads(raw_data)

                    capture_state(data)

                    extracted = extract_final_text(data)

                    if (
                        extracted
                        and len(extracted.strip())
                        > len(final_reply)
                    ):
                        final_reply = extracted.strip()

                except json.JSONDecodeError:

                    pass


        # ----------------------------------------------------
        # ORIGINAL FINAL CLEANING
        # ----------------------------------------------------

        if final_reply:

            clean_reply = re.sub(
                r"\s+",
                " ",
                final_reply
            ).strip()

            return {
                "ok": True,
                "response": clean_reply,
            }


        return {
            "ok": False,
            "error": "No valid response returned.",
        }


    except Exception as e:

        return {
            "ok": False,
            "error": f"Stream failure: {str(e)}",
        }


# ============================================================
# HOME
# ============================================================

@app.route("/", methods=["GET"])
def home():

    return jsonify({
        "status": "online",
        "service": "Perplexity API",
        "endpoints": {
            "POST /ask": "Send a prompt",
            "POST /headers": "Update request headers",
            "POST /cookies": "Update request cookies",
        },
    })


# ============================================================
# ASK
# ============================================================

@app.route("/ask", methods=["POST"])
def ask():

    data = request.get_json(silent=True) or {}

    user_text = data.get("prompt", "")

    if not isinstance(user_text, str):
        return jsonify({
            "error": "Field 'prompt' must be a string."
        }), 400

    user_text = user_text.strip()

    if not user_text:

        return jsonify({
            "error": "Field 'prompt' is required."
        }), 400


    result = send_message(user_text)


    if result.get("ok"):

        return jsonify({
            "response": result["response"]
        })


    return jsonify({
        "error": result.get(
            "error",
            "Unknown error"
        )
    }), 500


# ============================================================
# HEADERS
# ============================================================

@app.route("/headers", methods=["POST"])
def headers_endpoint():

    data = request.get_json(silent=True) or {}

    result = update_headers(data)

    if "error" in result:

        return jsonify(result), 400

    return jsonify(result)


# ============================================================
# COOKIES
# ============================================================

@app.route("/cookies", methods=["POST"])
def cookies_endpoint():

    data = request.get_json(silent=True) or {}

    result = update_cookies(data)

    if "error" in result:

        return jsonify(result), 400

    return jsonify(result)


# ============================================================
# RUN
# ============================================================

if __name__ == "__main__":

    port = int(
        os.environ.get(
            "PORT",
            5000
        )
    )

    app.run(
        host="0.0.0.0",
        port=port
    )
