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
# content-length は残す: 動画のRange配信(206)ではサイズ情報がバッファリング挙動に直結するため、
# 中身を変換せずそのまま中継しているここでは上流の値をそのまま使って問題ない
EXCLUDED_RESPONSE_HEADERS = {"content-encoding", "transfer-encoding", "connection"}

# 動画アップロードは自宅回線の速度次第でかなり時間がかかるため、
# 接続タイムアウトは短く・読み取り(応答待ち)タイムアウトは長めに分ける
CONNECT_TIMEOUT = 10
READ_TIMEOUT = 600  # 10分


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
            # request.get_data()で全体をメモリに読み込まず、
            # request.stream をそのまま流し込むことで、
            # 受信しながら順次PC側へ転送する(大きい動画ファイル対策)
            data=request.stream if request.content_length else None,
            stream=True,
            timeout=(CONNECT_TIMEOUT, READ_TIMEOUT),
        )
    except requests.exceptions.Timeout:
        return jsonify({"error": "バックエンド(PC側)からの応答がタイムアウトしました。自宅回線が遅いか、PC側が停止している可能性があります。"}), 504
    except requests.exceptions.RequestException as e:
        return jsonify({"error": f"バックエンド(PC側)に接続できませんでした: {e}"}), 502

    response_headers = [
        (k, v) for k, v in upstream_resp.headers.items()
        if k.lower() not in EXCLUDED_RESPONSE_HEADERS
    ]

    return Response(
        upstream_resp.iter_content(chunk_size=65536),
        status=upstream_resp.status_code,
        headers=response_headers,
    )


@app.route("/", defaults={"path": ""}, methods=["GET", "POST", "DELETE", "PUT", "PATCH", "HEAD"])
@app.route("/<path:path>", methods=["GET", "POST", "DELETE", "PUT", "PATCH", "HEAD"])
def proxy(path):
    return proxy_request(path)


if __name__ == "__main__":
    # 動画のシーク時、ブラウザは複数のRangeリクエストを並行して送ってくることがあるため、
    # シングルスレッドだと待ち行列になって再生が止まって見える(threaded=Trueで並行処理する)
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)), debug=True, threaded=True)
