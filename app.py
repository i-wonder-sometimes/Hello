import json
import re
import uuid
import os
import requests

from flask import Flask, jsonify, request

app = Flask(__name__)

# ============================================================
# SAME SETTINGS AS YOUR ORIGINAL SCRIPT
# ============================================================

url = "https://www.perplexity.ai/rest/sse/perplexity_ask"

session_context_uuid = str(uuid.uuid4())

# ---- memory state ----
LAST_BACKEND_UUID = None
READ_WRITE_TOKEN = None
FRONTEND_CONTEXT_UUID = None

headers = {
    'User-Agent': (
        "Mozilla/5.0 (Linux; Android 10; K) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/154.0.0.0 Mobile Safari/537.36"
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
# HEADER VALIDATION
# Same logic as your original script
# ============================================================

def is_valid_header_key(key):
    key_str = str(key).strip()

    if not key_str or key_str.startswith(":"):
        return False

    return bool(re.match(r"^[a-zA-Z0-9\-_]+$", key_str))


# ============================================================
# UPDATE HEADERS
# ============================================================

@app.route("/headers", methods=["POST"])
def update_headers():

    global headers

    data = request.get_json(silent=True) or {}

    if not isinstance(data, dict):
        return jsonify({
            "error": "Invalid payload format, expected JSON object"
        }), 400

    updated_count = 0

    for k, v in data.items():

        clean_k = str(k).strip()
        clean_v = str(v).strip()

        if is_valid_header_key(clean_k):
            headers[clean_k] = clean_v
            updated_count += 1

    return jsonify({
        "message": f"Updated {updated_count} headers successfully."
    })


# ============================================================
# UPDATE COOKIES
# Same cookie behavior as your original script
# ============================================================

@app.route("/cookies", methods=["POST"])
def update_cookies():

    global headers

    data = request.get_json(silent=True) or {}

    if not isinstance(data, dict):
        return jsonify({
            "error": "Invalid payload format, expected JSON object"
        }), 400

    items = [
        (str(k).strip(), str(v).strip())
        for k, v in data.items()
    ]

    cookie_str = "; ".join(
        f"{k}={v}"
        for k, v in items
    )

    headers["Cookie"] = cookie_str
    headers["cookie"] = cookie_str

    return jsonify({
        "message": "Cookies updated successfully."
    })


# ============================================================
# SAME STATE CAPTURE
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

        for value in data_obj.values():
            capture_state(value)

    elif isinstance(data_obj, list):

        for item in data_obj:
            capture_state(item)


# ============================================================
# SAME RESPONSE EXTRACTION
# ============================================================

def extract_final_text(data_obj):

    if isinstance(data_obj, dict):

        if "text" in data_obj and isinstance(
            data_obj["text"], str
        ):
            return data_obj["text"]

        if "answer" in data_obj and isinstance(
            data_obj["answer"], str
        ):
            return data_obj["answer"]

        if "snippet" in data_obj and isinstance(
            data_obj["snippet"], str
        ):
            return data_obj["snippet"]

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


# ============================================================
# SAME PERPLEXITY REQUEST
# ============================================================

def send_message(user_text):

    global LAST_BACKEND_UUID
    global READ_WRITE_TOKEN
    global FRONTEND_CONTEXT_UUID

    frontend_uuid = str(uuid.uuid4())

    is_followup = READ_WRITE_TOKEN is not None

    # --------------------------------------------------------
    # EXACT SAME PARAMETER SET
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
        "query_source": (
            "followup" if is_followup else "home"
        ),
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
    # SAME SESSION / FOLLOW-UP LOGIC
    # --------------------------------------------------------

    if is_followup:

        params["last_backend_uuid"] = LAST_BACKEND_UUID
        params["read_write_token"] = READ_WRITE_TOKEN

        if FRONTEND_CONTEXT_UUID:
            params["frontend_context_uuid"] = (
                FRONTEND_CONTEXT_UUID
            )

    else:

        params["frontend_context_uuid"] = (
            session_context_uuid
        )

    payload = {
        "params": params,
        "query_str": user_text,
    }

    # --------------------------------------------------------
    # SAME HEADER CLEANING
    # --------------------------------------------------------

    req_headers = {
        k: v
        for k, v in headers.copy().items()
        if is_valid_header_key(k)
    }

    req_headers["x-request-id"] = frontend_uuid

    if is_followup and LAST_BACKEND_UUID:

        req_headers["referer"] = (
            f"https://www.perplexity.ai/search/"
            f"{LAST_BACKEND_UUID}"
        )

    # --------------------------------------------------------
    # UPSTREAM REQUEST
    #
    # verify=False is ONLY here because Render is currently
    # reporting:
    #
    # CERTIFICATE_VERIFY_FAILED
    #
    # Everything else stays the same.
    # --------------------------------------------------------

    response = requests.post(
        url,
        data=json.dumps(payload),
        headers=req_headers,
        stream=True,
        timeout=60,
        verify=False,
    )

    if response.status_code != 200:

        if response.status_code != 200:
    try:
        upstream_body = response.text[:3000]
    except Exception:
        upstream_body = ""

    return None, {
        "error": f"Bad server response ({response.status_code})",
        "upstream_status": response.status_code,
        "upstream_content_type": response.headers.get("content-type"),
        "upstream_server": response.headers.get("server"),
        "upstream_body": upstream_body,
    }, 502

    # --------------------------------------------------------
    # SAME SSE PARSING
    # --------------------------------------------------------

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
            decoded = str(line)

        if not decoded.startswith("data: "):
            continue

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

    if final_reply:

        clean_reply = re.sub(
            r"\s+",
            " ",
            final_reply
        ).strip()

        return {
            "response": clean_reply
        }, None, 200

    return None, {
        "error": "No valid response returned from upstream."
    }, 500


# ============================================================
# API ENDPOINT
# ============================================================

@app.route("/ask", methods=["POST"])
def ask():

    data = request.get_json(silent=True) or {}

    user_text = data.get(
        "prompt",
        ""
    ).strip()

    if not user_text:

        return jsonify({
            "error": "Field 'prompt' is required."
        }), 400

    try:

        result, error, status = send_message(
            user_text
        )

        if error:

            return jsonify(error), status

        return jsonify(result), status

    except Exception as e:

        return jsonify({
            "error": f"Stream failure: {str(e)}"
        }), 500


# ============================================================
# ROOT
# ============================================================

@app.route("/", methods=["GET"])
def home():

    return jsonify({

        "status": "online",

        "message":
            "Render Perplexity API is operational.",

        "endpoints": {
            "POST /ask":
                "Send prompt payload: {'prompt': 'your question'}",

            "POST /headers":
                "Update active request headers",

            "POST /cookies":
                "Update active request cookies",
        },

        "state": {
            "backend_uuid":
                LAST_BACKEND_UUID is not None,

            "read_write_token":
                READ_WRITE_TOKEN is not None,

            "frontend_context_uuid":
                FRONTEND_CONTEXT_UUID is not None,
        },
    })


# ============================================================
# RENDER ENTRYPOINT
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
