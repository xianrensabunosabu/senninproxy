from flask import Flask, request, Response, render_template_string
import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin, quote
import time

app = Flask(__name__)

# --- 簡易キャッシュ（メモリ上） ---
cache = {}
CACHE_EXPIRE = 120  # 秒（2分）

# --- UIテンプレート ---
INDEX_HTML = """
<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<title>Proxy Browser</title>
<style>
body {
  background: #0e0e0e; color: #e5e5e5; font-family: system-ui, sans-serif; margin: 0; padding: 0;
}
header {
  background: #1b1b1b; padding: 10px; display: flex; align-items: center;
  justify-content: space-between; box-shadow: 0 2px 4px rgba(0,0,0,0.5);
}
.tabs {
  display: flex; gap: 6px; align-items: center; overflow-x: auto;
}
.tab {
  background: #2b2b2b; padding: 6px 12px; border-radius: 6px; cursor: pointer;
}
.tab.active { background: #444; color: #fff; font-weight: bold; }
input[type=text] {
  width: 60%; padding: 8px; border-radius: 6px; border: none; background: #222; color: #eee;
}
button {
  padding: 8px 10px; margin-left: 4px; border: none; border-radius: 6px;
  background: #444; color: white; cursor: pointer;
}
button:hover { background: #555; }
iframe {
  width: 100%; height: calc(100vh - 80px); border: none; background: white;
}
</style>
</head>
<body>
<header>
  <div class="tabs" id="tabs"></div>
  <div>
    <input type="text" id="urlInput" placeholder="https://example.com">
    <button onclick="openTab()">Open</button>
  </div>
</header>
<main id="content"></main>

<script>
let tabCount = 0;
let tabs = [];
let activeTab = null;

function openTab() {
  const url = document.getElementById('urlInput').value;
  if (!url) return;
  const id = 'tab-' + (++tabCount);
  const tab = { id, url };
  tabs.push(tab);
  renderTabs();
  openSite(tab);
}

function renderTabs() {
  const tabDiv = document.getElementById('tabs');
  tabDiv.innerHTML = '';
  tabs.forEach(t => {
    const div = document.createElement('div');
    div.className = 'tab' + (t.id === activeTab?.id ? ' active' : '');
    div.textContent = t.url.replace(/^https?:\\/\\//, '');
    div.onclick = () => openSite(t);
    tabDiv.appendChild(div);
  });
}

function openSite(tab) {
  activeTab = tab;
  renderTabs();
  document.getElementById('content').innerHTML = 
    `<iframe src="/proxy?url=${encodeURIComponent(tab.url)}"></iframe>`;
}
</script>
</body>
</html>
"""

@app.route("/")
def home():
    return render_template_string(INDEX_HTML)


@app.route("/proxy", methods=["GET", "POST"])
def proxy():
    target_url = request.args.get("url") or request.form.get("url")
    if not target_url:
        return "Error: No URL"

    method = request.method
    headers = {"User-Agent": request.headers.get("User-Agent", "Mozilla/5.0")}

    # --- キャッシュ確認 ---
    now = time.time()
    if target_url in cache and now - cache[target_url]["time"] < CACHE_EXPIRE:
        cached = cache[target_url]["data"]
        return Response(cached["content"], content_type=cached["type"])

    try:
        if method == "POST":
            resp = requests.post(target_url, data=request.form, headers=headers)
        else:
            resp = requests.get(target_url, headers=headers, params=request.args)

        ctype = resp.headers.get("Content-Type", "")

        # --- HTMLの場合のみURL書き換え ---
        if "text/html" in ctype:
            soup = BeautifulSoup(resp.text, "html.parser")

            for tag, attr in [
                ("a", "href"), ("img", "src"), ("script", "src"),
                ("link", "href"), ("form", "action")
            ]:
                for t in soup.find_all(tag):
                    if t.has_attr(attr):
                        orig = t[attr]
                        abs_url = urljoin(target_url, orig)
                        t[attr] = f"/proxy?url={quote(abs_url)}"

            # JSのfetch/XHRをproxy化
            inject_script = """
            <script>
            const originalFetch = window.fetch;
            window.fetch = function(url, options) {
              const proxyUrl = '/proxy?url=' + encodeURIComponent(new URL(url, location.href).href);
              if (options && options.body && options.method === 'POST') {
                const formData = new URLSearchParams();
                for (const [k, v] of new URLSearchParams(options.body)) formData.append(k, v);
                return originalFetch(proxyUrl, {method: 'POST', body: formData});
              }
              return originalFetch(proxyUrl);
            };
            const originalXHROpen = XMLHttpRequest.prototype.open;
            XMLHttpRequest.prototype.open = function(method, url, ...rest) {
              const proxyUrl = '/proxy?url=' + encodeURIComponent(new URL(url, location.href).href);
              return originalXHROpen.call(this, method, proxyUrl, ...rest);
            };
            </script>
            """
            soup.body.append(BeautifulSoup(inject_script, "html.parser"))
            html = str(soup)

            cache[target_url] = {
                "time": now,
                "data": {"content": html, "type": "text/html; charset=utf-8"}
            }

            return Response(html, content_type="text/html; charset=utf-8")
        else:
            cache[target_url] = {
                "time": now,
                "data": {"content": resp.content, "type": ctype}
            }
            return Response(resp.content, content_type=ctype)

    except Exception as e:
        return f"<pre>Error: {e}</pre>"


if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0")
