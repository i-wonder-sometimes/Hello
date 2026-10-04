import json
import re
import uuid
import os
import requests
import urllib3

from flask import Flask, jsonify, request

app = Flask(__name__)

urllib3.disable_warnings(
    urllib3.exceptions.InsecureRequestWarning
)

# ============================================================
# CONFIG
# ============================================================

UPSTREAM_URL = (
    "https://www.perplexity.ai/rest/sse/perplexity_ask"
)

session_context_uuid = str(uuid.uuid4())

LAST_BACKEND_UUID = None
READ_WRITE_TOKEN = None
FRONTEND_CONTEXT_UUID = None


# ============================================================
# HEADERS
# ============================================================

headers = {
    "User-Agent": (
        "Mozilla/5.0 (Linux; Android 10; K) "
        "AppleWebKit/537.36 "
        "(KHTML, like Gecko) "
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
}


# ============================================================
# HEADER VALIDATION
# ============================================================

def is_valid_header_key(key):
    key_str = str(key).strip()

    if not key_str:
        return False

    if key_str.startswith(":"):
        return False

    return bool(
        re.match(
            r"^[a-zA-Z0-9\-_]+$",
            key_str
        )
    )


# ============================================================
# UPDATE HEADERS
# ============================================================

@app.route("/headers", methods=["POST"])
def update_headers():

    global headers

    data = request.get_json(
        silent=True
    ) or {}

    if not isinstance(data, dict):

        return jsonify({
            "error":
                "Invalid payload format, "
                "expected JSON object"
        }), 400

    updated_count = 0

    for k, v in data.items():

        clean_k = str(k).strip()
        clean_v = str(v).strip()

        if not is_valid_header_key(clean_k):
            continue

        # requests generates these itself.
        if clean_k.lower() in {
            "host",
            "content-length",
            "cookie",
        }:
            continue

        headers[clean_k] = clean_v

        updated_count += 1

    return jsonify({
        "message":
            f"Updated {updated_count} headers successfully."
    })


# ============================================================
# UPDATE COOKIES
# ============================================================

@app.route("/cookies", methods=["POST"])
def update_cookies():

    global headers

    data = request.get_json(
        silent=True
    ) or {}

    if not isinstance(data, dict):

        return jsonify({
            "error":
                "Invalid payload format, "
                "expected JSON object"
        }), 400

    cookie_items = []

    for k, v in data.items():

        key = str(k).strip()
        value = str(v).strip()

        if key:
            cookie_items.append(
                f"{key}={value}"
            )

    cookie_string = "; ".join(
        cookie_items
    )

    # Keep exactly one canonical Cookie header.
    headers["Cookie"] = cookie_string

    # Remove accidental lowercase duplicate.
    headers.pop("cookie", None)

    return jsonify({
        "message":
            "Cookies updated successfully.",
        "cookie_count":
            len(cookie_items)
    })


# ============================================================
# CAPTURE STATE
# ============================================================

def capture_state(data_obj):

    global LAST_BACKEND_UUID
    global READ_WRITE_TOKEN
    global FRONTEND_CONTEXT_UUID

    if isinstance(data_obj, dict):

        backend_uuid = data_obj.get(
            "backend_uuid"
        )

        if (
            isinstance(backend_uuid, str)
            and backend_uuid
        ):
            LAST_BACKEND_UUID = backend_uuid

        read_write_token = data_obj.get(
            "read_write_token"
        )

        if (
            isinstance(read_write_token, str)
            and read_write_token
        ):
            READ_WRITE_TOKEN = read_write_token

        frontend_context_uuid = data_obj.get(
            "frontend_context_uuid"
        )

        if (
            isinstance(frontend_context_uuid, str)
            and frontend_context_uuid
        ):
            FRONTEND_CONTEXT_UUID = (
                frontend_context_uuid
            )

        for value in data_obj.values():
            capture_state(value)

    elif isinstance(data_obj, list):

        for item in data_obj:
            capture_state(item)


# ============================================================
# EXTRACT FINAL ANSWER
# ============================================================

def extract_final_text(data_obj):

    if isinstance(data_obj, dict):

        # Prefer an actual markdown answer.
        markdown_block = data_obj.get(
            "markdown_block"
        )

        if isinstance(
            markdown_block,
            dict
        ):

            answer = markdown_block.get(
                "answer"
            )

            if (
                isinstance(answer, str)
                and answer.strip()
            ):
                return answer

        # Generic fallback.
        for key in (
            "answer",
            "text",
            "snippet",
        ):

            value = data_obj.get(key)

            if (
                isinstance(value, str)
                and value.strip()
            ):
                return value

        for value in data_obj.values():

            result = extract_final_text(
                value
            )

            if result:
                return result

    elif isinstance(data_obj, list):

        for item in data_obj:

            result = extract_final_text(
                item
            )

            if result:
                return result

    return None


# ============================================================
# SEND MESSAGE TO PERPLEXITY
# ============================================================

def send_message(user_text):

    global LAST_BACKEND_UUID
    global READ_WRITE_TOKEN
    global FRONTEND_CONTEXT_UUID

    frontend_uuid = str(
        uuid.uuid4()
    )

    is_followup = (
        READ_WRITE_TOKEN is not None
    )

    # --------------------------------------------------------
    # PARAMETERS
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
            "followup"
            if is_followup
            else "home"
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
        "client_search_results_cache_key":
            frontend_uuid,
        "version": "2.18",
        "followup_source": "link",
    }

    # --------------------------------------------------------
    # SESSION / FOLLOW-UP
    # --------------------------------------------------------

    if is_followup:

        params["last_backend_uuid"] = (
            LAST_BACKEND_UUID
        )

        params["read_write_token"] = (
            READ_WRITE_TOKEN
        )

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
    # REQUEST HEADERS
    # --------------------------------------------------------

    req_headers = {}

    for key, value in headers.copy().items():

        if not is_valid_header_key(key):
            continue

        if key.lower() in {
            "host",
            "content-length",
        }:
            continue

        req_headers[key] = value

    req_headers["x-request-id"] = (
        frontend_uuid
    )

    if is_followup and LAST_BACKEND_UUID:

        req_headers["referer"] = (
            "https://www.perplexity.ai/search/"
            + LAST_BACKEND_UUID
        )

    # --------------------------------------------------------
    # DEBUG INFORMATION
    # --------------------------------------------------------

    print(
        "[UPSTREAM] Sending request to Perplexity",
        flush=True
    )

    print(
        "[UPSTREAM] Follow-up:",
        is_followup,
        flush=True
    )

    print(
        "[UPSTREAM] Headers:",
        len(req_headers),
        flush=True
    )

    # --------------------------------------------------------
    # UPSTREAM REQUEST
    # --------------------------------------------------------

    try:

        response = requests.post(
            UPSTREAM_URL,
            data=json.dumps(payload),
            headers=req_headers,
            stream=True,
            timeout=90,
            verify=False,
        )

    except requests.RequestException as exc:

        print(
            "[UPSTREAM] Request failed:",
            repr(exc),
            flush=True
        )

        return None, {
            "error":
                "Could not connect to upstream.",
            "exception":
                str(exc),
        }, 502

    print(
        "[UPSTREAM] Status:",
        response.status_code,
        flush=True
    )

    print(
        "[UPSTREAM] Content-Type:",
        response.headers.get(
            "content-type"
        ),
        flush=True
    )

    print(
        "[UPSTREAM] Server:",
        response.headers.get(
            "server"
        ),
        flush=True
    )

    print(
        "[UPSTREAM] CF-Ray:",
        response.headers.get(
            "cf-ray"
        ),
        flush=True
    )

    # --------------------------------------------------------
    # IMPORTANT:
    # RETURN THE ACTUAL UPSTREAM ERROR
    # --------------------------------------------------------

    if response.status_code != 200:

        try:

            upstream_body = (
                response.text[:5000]
            )

        except Exception:

            upstream_body = ""

        return None, {

            "error":
                f"Bad server response "
                f"({response.status_code})",

            "upstream_status":
                response.status_code,

            "upstream_content_type":
                response.headers.get(
                    "content-type"
                ),

            "upstream_server":
                response.headers.get(
                    "server"
                ),

            "upstream_cf_ray":
                response.headers.get(
                    "cf-ray"
                ),

            "upstream_body":
                upstream_body,

        }, 502

    # --------------------------------------------------------
    # SSE PARSING
    # --------------------------------------------------------

    final_reply = ""

    try:

        for line in response.iter_lines():

            if not line:
                continue

            if isinstance(
                line,
                bytes
            ):

                decoded = line.decode(
                    "utf-8",
                    errors="ignore"
                )

            else:

                decoded = str(line)

            if not decoded.startswith(
                "data: "
            ):
                continue

            raw_data = (
                decoded[6:].strip()
            )

            if raw_data == "[DONE]":
                break

            try:

                data = json.loads(
                    raw_data
                )

            except json.JSONDecodeError:
                continue

            capture_state(data)

            extracted = (
                extract_final_text(data)
            )

            if (
                extracted
                and len(extracted.strip())
                > len(final_reply)
            ):

                final_reply = (
                    extracted.strip()
                )

            if data.get(
                "final_sse_message"
            ):
                break

    except requests.RequestException as exc:

        return None, {
            "error":
                "SSE stream failed.",
            "exception":
                str(exc),
        }, 502

    # --------------------------------------------------------
    # FINAL RESPONSE
    # --------------------------------------------------------

    if final_reply:

        clean_reply = re.sub(
            r"\s+",
            " ",
            final_reply
        ).strip()

        return {
            "response":
                clean_reply
        }, None, 200

    return None, {
        "error":
            "No valid response returned from upstream."
    }, 500


# ============================================================
# ASK ENDPOINT
# ============================================================

@app.route(
    "/ask",
    methods=["POST"]
)
def ask():

    data = request.get_json(
        silent=True
    ) or {}

    user_text = data.get(
        "prompt",
        ""
    )

    if not isinstance(
        user_text,
        str
    ):

        return jsonify({
            "error":
                "Field 'prompt' must be a string."
        }), 400

    user_text = user_text.strip()

    if not user_text:

        return jsonify({
            "error":
                "Field 'prompt' is required."
        }), 400

    try:

        result, error, status = (
            send_message(user_text)
        )

        if error:

            return jsonify(
                error
            ), status

        return jsonify(
            result
        ), status

    except Exception as exc:

        print(
            "[SERVER] Exception:",
            repr(exc),
            flush=True
        )

        return jsonify({
            "error":
                "Stream failure",
            "exception":
                str(exc),
        }), 500


# ============================================================
# ROOT
# ============================================================

@app.route(
    "/",
    methods=["GET"]
)
def home():

    return jsonify({

        "status":
            "online",

        "message":
            "Render Perplexity API is operational.",

        "endpoints": {

            "POST /ask":
                "Send {'prompt': 'your question'}",

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
            "5000"
        )
    )

    app.run(
        host="0.0.0.0",
        port=port
    )
