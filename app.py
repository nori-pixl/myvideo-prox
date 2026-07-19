import os

import requests
from flask import Flask, request, Response, jsonify
from flask_cors import CORS

app = Flask(__name__)
# フロントエンド(Renderの別サービス)からのアクセスを許可する
CORS(app)

# PC側(cloudflared経由)の本物のバックエンドURL。
# Renderの環境変数「UPSTREAM_URL」で設定する。
# cloudflaredを再起動してURLが変わったら、Renderの環境変数をここだけ書き換えればよい。
UPSTREAM_URL = os.environ.get("UPSTREAM_URL", "").rstrip("/")

# そのまま転送すると壊れるヘッダーは除外する
EXCLUDED_REQUEST_HEADERS = {"host", "content-length"}
EXCLUDED_RESPONSE_HEADERS = {"content-encoding", "content-length", "transfer-encoding", "connection"}


def proxy_request(path):
    if not UPSTREAM_URL:
        return jsonify({"error": "UPSTREAM_URLが設定されていません(Renderの環境変数を確認してください)"}), 500

    target = f"{UPSTREAM_URL}/{path}"
    headers = {k: v for k, v in request.headers.items() if k.lower() not in EXCLUDED_REQUEST_HEADERS}

    try:
        upstream_resp = requests.request(
            method=request.method,
            url=target,
            headers=headers,
            params=request.args,
            data=request.get_data() or None,
            stream=True,
            timeout=60,
        )
    except requests.exceptions.RequestException as e:
        return jsonify({"error": f"バックエンド(PC側)に接続できませんでした: {e}"}), 502

    response_headers = [
        (k, v) for k, v in upstream_resp.headers.items()
        if k.lower() not in EXCLUDED_RESPONSE_HEADERS
    ]

    return Response(
        upstream_resp.iter_content(chunk_size=8192),
        status=upstream_resp.status_code,
        headers=response_headers,
    )


@app.route("/", defaults={"path": ""}, methods=["GET", "POST", "DELETE", "PUT", "PATCH", "HEAD"])
@app.route("/<path:path>", methods=["GET", "POST", "DELETE", "PUT", "PATCH", "HEAD"])
def proxy(path):
    return proxy_request(path)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)), debug=True)
