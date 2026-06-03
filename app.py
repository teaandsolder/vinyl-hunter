import os
import re
import json
import time
from datetime import datetime, timedelta
from flask import Flask, render_template_string, request, jsonify
import requests

app = Flask(__name__)

GIST_ID = os.environ.get("GIST_ID")
GIST_TOKEN = os.environ.get("GIST_TOKEN")
DISCOGS_TOKEN = os.environ.get("DISCOGS_TOKEN")
GIST_FILENAME = "vinyl-hunter-data.json"
GIST_HEADERS = {
    "Authorization": f"token {GIST_TOKEN}",
    "Accept": "application/vnd.github.v3+json"
}
DISCOGS_HEADERS = {
    "Authorization": f"Discogs token={DISCOGS_TOKEN}",
    "User-Agent": "VinylHunter/1.0"
}

def now_str():
    return (datetime.now() - timedelta(hours=4)).strftime("%d %b %Y, %H:%M")

def load_gist():
    try:
        r = requests.get(f"https://api.github.com/gists/{GIST_ID}", headers=GIST_HEADERS, timeout=10)
        content = r.json()["files"][GIST_FILENAME]["content"]
        return json.loads(content)
    except Exception as e:
        print(f"Error loading gist: {e}")
        return {"records": [], "collection": [], "updated": None}

def save_gist(payload):
    try:
        body = {"files": {GIST_FILENAME: {"content": json.dumps(payload, indent=2)}}}
        requests.patch(f"https://api.github.com/gists/{GIST_ID}", headers=GIST_HEADERS, json=body, timeout=10)
    except Exception as e:
        print(f"Error saving gist: {e}")

def parse_price(v):
    try:
        return float(str(v).replace("$","").replace(",","").strip())
    except:
        return None

def calc_change(old, new):
    o = parse_price(old)
    n = parse_price(new)
    if o is None or n is None or o == 0:
        return None
    pct = ((n - o) / o) * 100
    if abs(pct) < 1:
        return None
    return round(pct, 1)

def get_prices_by_release_id(release_id):
    """Fetch marketplace stats from Discogs - lowest price and num for sale."""
    try:
        url = f"https://api.discogs.com/marketplace/stats/{release_id}"
        r = requests.get(url, headers=DISCOGS_HEADERS, timeout=10)
        if r.status_code != 200:
            return None, None
        data = r.json()
        lowest = data.get("lowest_price", {})
        num_for_sale = data.get("num_for_sale", 0)
        if lowest and lowest.get("value"):
            low_str = f"${lowest['value']:.2f}"
        else:
            low_str = "N/A"
        sale_str = str(num_for_sale) if num_for_sale else "0"
        return low_str, sale_str
    except Exception as e:
        print(f"Error fetching stats for {release_id}: {e}")
        return None, None

def search_discogs(artist, title):
    try:
        query = f"{artist} {title}".strip()
        url = "https://api.discogs.com/database/search"
        params = {"q": query, "type": "release", "per_page": 5, "token": DISCOGS_TOKEN}
        r = requests.get(url, headers=DISCOGS_HEADERS, params=params, timeout=10)
        results = r.json().get("results", [])
        if not results:
            return None, query, artist, None
        best = results[0]
        release_id = best.get("id")
        full_title = best.get("title", query)
        discogs_url = f"https://www.discogs.com{best.get('uri', '')}"
        return release_id, full_title, artist, discogs_url
    except Exception as e:
        print(f"Search error: {e}")
        return None, f"{artist} - {title}", artist, None

def enrich_record(record):
    release_id = record.get("release_id")
    if not release_id:
        return record
    low, sale = get_prices_by_release_id(release_id)
    old_low = record.get("low")
    record["low"] = low or record.get("low", "N/A")
    record["sale"] = sale or record.get("sale", "0")
    record["low_change"] = calc_change(old_low, record["low"])
    return record

HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
<title>Vinyl Hunter</title>
<link href="https://fonts.googleapis.com/css2?family=Bebas+Neue&family=DM+Sans:wght@400;500;600&display=swap" rel="stylesheet">
<style>
:root {
  --amber: #b06a00;
  --amber-light: #e08c1a;
  --amber-dark: #7a4500;
  --brown: #3b1f0a;
  --warm-bg: #f5ede0;
  --card-bg: #fffaf4;
  --text: #2a1800;
  --subtext: #8a6a50;
  --green: #2d6a2d;
  --red: #8b1a1a;
  --border: #e8d5be;
  --gold: #7a5c1e;
  --gold-light: #c49a2a;
}
* { box-sizing: border-box; margin: 0; padding: 0; }
body { font-family: "DM Sans", sans-serif; background: var(--warm-bg); color: var(--text); padding: 20px 16px 40px; }
.container { max-width: 560px; margin: 0 auto; }
.header { text-align: center; margin-bottom: 24px; padding-top: 8px; }
.header h1 { font-family: "Bebas Neue", sans-serif; font-size: 42px; letter-spacing: 3px; color: var(--brown); line-height: 1; }
.header h1 span { color: var(--amber); }
.header p { font-size: 12px; color: var(--subtext); letter-spacing: 1px; text-transform: uppercase; margin-top: 4px; }
.action-bar { display: flex; gap: 8px; margin-bottom: 10px; }
.btn { border: 1.5px solid var(--border); padding: 11px 18px; border-radius: 8px; font-family: "DM Sans", sans-serif; font-weight: 600; font-size: 13px; cursor: pointer; white-space: nowrap; flex: 1; background: var(--card-bg); color: var(--brown); }
.btn:active { opacity: 0.7; }
.btn:disabled { opacity: 0.4; }
.btn-amber { background: var(--amber); color: white; border: none; padding: 10px 18px; border-radius: 8px; font-family: "DM Sans", sans-serif; font-weight: 600; font-size: 13px; cursor: pointer; }
.btn-amber:active { opacity: 0.7; }
.btn-amber:disabled { opacity: 0.4; }
.import-toggle { text-align: center; margin-bottom: 6px; }
.import-toggle button { background: none; border: none; color: var(--subtext); font-size: 12px; font-family: "DM Sans", sans-serif; cursor: pointer; text-decoration: underline; padding: 4px; }
.import-card { background: var(--card-bg); border-radius: 14px; padding: 14px 16px; box-shadow: 0 1px 4px rgba(90,50,10,0.1); margin-bottom: 10px; display: none; border: 1px solid var(--border); }
.import-card.open { display: block; }
.import-card label { display: block; font-size: 11px; font-weight: 600; color: var(--subtext); text-transform: uppercase; letter-spacing: 0.8px; margin-bottom: 8px; }
textarea { width: 100%; height: 90px; border: 1.5px solid var(--border); border-radius: 10px; padding: 10px 12px; font-family: "DM Sans", sans-serif; font-size: 14px; color: var(--text); outline: none; background: #fdf7ee; resize: none; display: block; margin-bottom: 10px; }
textarea:focus { border-color: var(--amber); background: #fff; }
textarea::placeholder { color: #c4a882; line-height: 1.6; }
.import-btn-row { display: flex; justify-content: flex-end; }
.last-updated { text-align: center; font-size: 11px; color: var(--subtext); margin-bottom: 22px; letter-spacing: 0.5px; }
.spinner { display: none; text-align: center; padding: 20px; font-size: 13px; color: var(--subtext); }
.record-card { background: var(--card-bg); border-radius: 14px; box-shadow: 0 1px 4px rgba(90,50,10,0.1); margin-bottom: 12px; overflow: hidden; border: 1px solid var(--border); }
.record-row { display: flex; align-items: center; padding: 12px 16px; border-bottom: 1px solid var(--border); gap: 8px; }
.record-row:last-of-type { border-bottom: none; }
.record-info { flex: 1; min-width: 0; }
.record-title { font-weight: 600; font-size: 14px; color: var(--text); cursor: pointer; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; display: block; }
.record-title:active { color: var(--amber); }
.record-artist { font-size: 11px; color: var(--subtext); margin-top: 2px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.price-box { flex-shrink: 0; display: flex; align-items: center; gap: 6px; }
.price-col { display: flex; flex-direction: column; align-items: flex-end; }
.price-row { display: flex; align-items: center; justify-content: flex-end; height: 22px; }
.change-col { display: flex; flex-direction: column; align-items: flex-end; min-width: 38px; }
.change { font-size: 10px; font-weight: 600; height: 22px; display: flex; align-items: center; justify-content: flex-end; }
.change.up { color: var(--green); }
.change.down { color: var(--red); }
.price-label { font-size: 10px; color: #c4a882; text-transform: uppercase; letter-spacing: 0.5px; margin-right: 3px; }
.low-price { color: var(--green); font-weight: 700; font-size: 15px; }
.sale-count { color: var(--subtext); font-size: 11px; }
.na-price { color: #c4a882; font-size: 12px; }
.del-btn { background: none; border: none; color: #c4a882; font-size: 20px; cursor: pointer; padding: 0 0 0 4px; line-height: 1; flex-shrink: 0; font-weight: 300; }
.del-btn:active { color: var(--red); }
.buy-btn { background: none; border: 1.5px solid var(--border); border-radius: 6px; color: var(--subtext); font-size: 11px; font-weight: 600; cursor: pointer; padding: 3px 7px; white-space: nowrap; font-family: "DM Sans", sans-serif; flex-shrink: 0; }
.buy-btn:active { background: var(--amber-light); color: white; border-color: var(--amber-light); }
.add-row-wrap { background: var(--card-bg); border-radius: 14px; box-shadow: 0 1px 4px rgba(90,50,10,0.1); border: 1px solid var(--border); padding: 12px 16px; display: flex; align-items: center; gap: 8px; }
.add-input { flex: 1; border: none; outline: none; font-family: "DM Sans", sans-serif; font-size: 14px; color: var(--text); background: transparent; }
.add-input::placeholder { color: #c4a882; }
.add-btn { background: none; border: none; color: var(--amber); font-size: 22px; cursor: pointer; line-height: 1; padding: 0 4px; font-weight: 300; }
.fetching-label { font-size: 11px; color: #c4a882; font-style: italic; }
.collection-gap { height: 32px; }
.collection-card { background: var(--card-bg); border-radius: 14px; box-shadow: 0 1px 4px rgba(90,50,10,0.1); margin-bottom: 16px; overflow: hidden; border: 1px solid var(--border); }
.collection-header { background: var(--brown); color: #f5ede0; padding: 10px 16px; font-family: "Bebas Neue", sans-serif; font-size: 18px; letter-spacing: 2px; display: flex; align-items: center; gap: 8px; cursor: pointer; }
.collection-header::before { content: ""; display: inline-block; width: 3px; height: 16px; background: var(--amber-light); border-radius: 2px; flex-shrink: 0; }
.collection-header .chevron { margin-left: auto; font-size: 12px; opacity: 0.6; transition: transform 0.2s; }
.collection-header.open .chevron { transform: rotate(180deg); }
.collection-body { display: none; }
.collection-body.open { display: block; }
.coll-row { display: flex; align-items: center; padding: 11px 16px; border-bottom: 1px solid var(--border); gap: 8px; }
.coll-row:last-of-type { border-bottom: none; }
.coll-info { flex: 1; min-width: 0; }
.coll-title { font-weight: 600; font-size: 14px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; color: var(--text); cursor: pointer; }
.coll-title:active { color: var(--amber); }
.coll-artist { font-size: 11px; color: var(--subtext); margin-top: 2px; }
.coll-prices { flex-shrink: 0; display: flex; flex-direction: column; align-items: flex-end; gap: 2px; }
.coll-paid { font-size: 11px; color: var(--subtext); }
.coll-market { font-size: 14px; font-weight: 700; color: var(--brown); }
.coll-diff { font-size: 12px; font-weight: 700; }
.coll-diff.profit { color: var(--green); }
.coll-diff.loss { color: var(--red); }
.coll-condition { font-size: 10px; color: #c4a882; text-transform: uppercase; }
.coll-add-row { display: flex; align-items: center; gap: 8px; padding: 10px 16px; border-top: 1px solid var(--border); }
.coll-add-input { flex: 1; border: none; outline: none; font-family: "DM Sans", sans-serif; font-size: 14px; color: var(--text); background: transparent; }
.coll-add-input::placeholder { color: #c4a882; }
.coll-add-btn { background: none; border: none; color: var(--amber-light); font-size: 22px; cursor: pointer; line-height: 1; padding: 0 4px; font-weight: 300; }
.modal-overlay { display: none; position: fixed; inset: 0; background: rgba(40,20,5,0.6); z-index: 100; align-items: center; justify-content: center; padding: 20px; }
.modal-overlay.open { display: flex; }
.modal { background: var(--card-bg); border-radius: 16px; padding: 20px; width: 100%; max-width: 340px; border: 1px solid var(--border); }
.modal h3 { font-family: "Bebas Neue", sans-serif; font-size: 22px; letter-spacing: 2px; color: var(--brown); margin-bottom: 4px; }
.modal .record-name { font-size: 13px; color: var(--subtext); margin-bottom: 16px; }
.modal label { display: block; font-size: 11px; font-weight: 600; color: var(--subtext); text-transform: uppercase; letter-spacing: 0.8px; margin-bottom: 6px; margin-top: 12px; }
.modal input[type=text], .modal input[type=number] { width: 100%; border: 1.5px solid var(--border); border-radius: 10px; padding: 10px 12px; font-family: "DM Sans", sans-serif; font-size: 14px; outline: none; background: #fdf7ee; }
.modal input:focus { border-color: var(--amber); }
.modal select { width: 100%; border: 1.5px solid var(--border); border-radius: 10px; padding: 10px 12px; font-family: "DM Sans", sans-serif; font-size: 14px; outline: none; background: #fdf7ee; appearance: none; }
.modal select:focus { border-color: var(--amber); }
.modal-btns { display: flex; gap: 8px; margin-top: 20px; }
.modal-btns button { flex: 1; padding: 12px; border-radius: 10px; font-family: "DM Sans", sans-serif; font-weight: 600; font-size: 14px; cursor: pointer; border: none; }
.modal-cancel { background: var(--warm-bg); color: var(--subtext); }
.modal-confirm { background: var(--amber); color: white; }
</style>
</head>
<body>
<div class="container">
  <div class="header">
    <h1>🎵 VINYL<span>HUNTER</span></h1>
    <p>Live Discogs Prices</p>
  </div>

  <div class="action-bar">
    <button class="btn" id="updateBtn" onclick="updatePrices()">Update</button>
    <button class="btn" id="updateAllBtn" onclick="confirmUpdateAll()">Update All</button>
    <button class="btn" onclick="exportList()">Export</button>
  </div>

  <div class="import-toggle">
    <button onclick="toggleImport()">&#43; Import records</button>
  </div>

  <div class="import-card" id="importCard">
    <label>One record per line: Artist - Title</label>
    <textarea id="recordInput" placeholder="John Williams - Star Wars&#10;Vangelis - Blade Runner&#10;Daft Punk - TRON: Legacy"></textarea>
    <div class="import-btn-row">
      <button class="btn-amber" id="fetchBtn" onclick="fetchRecords()">Add Records</button>
    </div>
  </div>

  <p class="last-updated" id="lastUpdated">{{ updated if updated else "No data loaded yet" }}</p>
  <div class="spinner" id="spinner">Fetching prices, please wait...</div>

  <div id="results">
    {% for record in records %}
    <div class="record-card">
      <div class="record-row" data-id="{{ record.release_id }}" data-url="{{ record.url }}" data-low="{{ record.low }}" data-sale="{{ record.sale }}">
        <div class="record-info">
          <span class="record-title" onclick="openDiscogs(this)">{{ record.title }}</span>
          <div class="record-artist">{{ record.artist }}</div>
        </div>
        <div class="price-box">
          {% if record.low == "N/A" or not record.low %}
            <span class="na-price">N/A</span>
          {% else %}
            <div class="change-col">
              <span class="change {{ 'up' if record.low_change and record.low_change > 0 else 'down' if record.low_change and record.low_change < 0 else '' }}">{% if record.low_change %}{{ '↑' if record.low_change > 0 else '↓' }}{{ record.low_change|abs }}%{% endif %}</span>
              <span class="change"></span>
            </div>
            <div class="price-col">
              <div class="price-row"><span class="price-label">Low</span><span class="low-price">{{ record.low }}</span></div>
              <div class="price-row"><span class="price-label">For sale</span><span class="sale-count">{{ record.sale }}</span></div>
            </div>
          {% endif %}
        </div>
        <button class="buy-btn" onclick="openBuyModal(this, '{{ record.title }}', '{{ record.artist }}', '{{ record.low }}')">✓</button>
        <button class="del-btn" onclick="deleteRecord(this)">&#10005;</button>
      </div>
    </div>
    {% endfor %}
    <div class="add-row-wrap">
      <input class="add-input" type="text" id="addInput" placeholder="Artist - Title or Discogs URL..." />
      <button class="add-btn" onclick="addRecord()">+</button>
    </div>
  </div>

  <div class="collection-gap"></div>

  <div class="collection-card">
    <div class="collection-header" onclick="toggleCollection(this)">
      MY COLLECTION<span class="chevron">&#9660;</span>
    </div>
    <div class="collection-body" id="collectionBody">
      {% for item in collection %}
      <div class="coll-row" data-id="{{ item.id }}" data-release-id="{{ item.release_id }}">
        <div class="coll-info">
          <div class="coll-title" onclick="openCollDiscogs(this)" data-url="{{ item.url }}">{{ item.title }}</div>
          <div class="coll-artist">{{ item.artist }} &middot; <span class="coll-condition">{{ item.condition }}</span></div>
        </div>
        <div class="coll-prices">
          <div class="coll-paid">Paid: {{ item.paid }}</div>
          <div class="coll-market">{{ item.low if item.low and item.low != 'N/A' else '—' }}</div>
          {% if item.paid and item.low and item.low != 'N/A' %}
            {% set diff = (item.low|replace('$','')|replace(',','')|float) - (item.paid|replace('$','')|replace(',','')|float) %}
            <div class="coll-diff {{ 'profit' if diff >= 0 else 'loss' }}">{{ '+' if diff >= 0 else '' }}${{ "%.2f"|format(diff) }}</div>
          {% endif %}
        </div>
        <button class="del-btn" onclick="deleteCollItem(this)">&#10005;</button>
      </div>
      {% endfor %}
      <div class="coll-add-row">
        <input class="coll-add-input" type="text" id="collAddInput" placeholder="Artist - Title..." />
        <button class="coll-add-btn" onclick="openAddCollModal()">+</button>
      </div>
    </div>
  </div>
</div>

<!-- Buy modal -->
<div class="modal-overlay" id="buyModal">
  <div class="modal">
    <h3>MARK AS BOUGHT</h3>
    <div class="record-name" id="buyModalName"></div>
    <input type="hidden" id="buyModalTitle" />
    <input type="hidden" id="buyModalArtist" />
    <input type="hidden" id="buyModalLow" />
    <input type="hidden" id="buyModalUrl" />
    <input type="hidden" id="buyModalReleaseId" />
    <label>What did you pay?</label>
    <input type="number" id="buyModalPaid" placeholder="e.g. 24.99" step="0.01" min="0" />
    <label>Condition</label>
    <select id="buyModalCondition">
      <option value="NM">NM (Near Mint)</option>
      <option value="VG+">VG+ (Very Good Plus)</option>
      <option value="VG">VG (Very Good)</option>
      <option value="M">M (Mint)</option>
    </select>
    <div class="modal-btns">
      <button class="modal-cancel" onclick="closeBuyModal()">Cancel</button>
      <button class="modal-confirm" onclick="confirmBuy()">Add to Collection</button>
    </div>
  </div>
</div>

<!-- Add to collection modal -->
<div class="modal-overlay" id="addCollModal">
  <div class="modal">
    <h3>ADD TO COLLECTION</h3>
    <label>Artist</label>
    <input type="text" id="addCollArtist" placeholder="e.g. Vangelis" />
    <label>Title</label>
    <input type="text" id="addCollTitle" placeholder="e.g. Blade Runner" />
    <label>What did you pay?</label>
    <input type="number" id="addCollPaid" placeholder="e.g. 24.99" step="0.01" min="0" />
    <label>Condition</label>
    <select id="addCollCondition">
      <option value="NM">NM (Near Mint)</option>
      <option value="VG+">VG+ (Very Good Plus)</option>
      <option value="VG">VG (Very Good)</option>
      <option value="M">M (Mint)</option>
    </select>
    <div class="modal-btns">
      <button class="modal-cancel" onclick="closeAddCollModal()">Cancel</button>
      <button class="modal-confirm" onclick="confirmAddCollection()">Add</button>
    </div>
  </div>
</div>

<script>
function exportList() {
  const lines = [];
  document.querySelectorAll(".record-row").forEach(row => {
    const title = row.querySelector(".record-title")?.textContent.trim();
    const artist = row.querySelector(".record-artist")?.textContent.trim();
    if (title) lines.push(artist ? artist + " - " + title : title);
  });
  const text = lines.join("\\n");
  const blob = new Blob([text], {type:"text/plain"});
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a"); a.href = url; a.download = "vinyl-wishlist.txt"; a.click();
  URL.revokeObjectURL(url);
}
function isDiscogsUrl(str) { return str.includes("discogs.com/"); }
function openDiscogs(el) {
  const row = el.closest(".record-row");
  const url = row.dataset.url;
  const title = el.textContent.trim();
  if (!url) return;
  if (confirm("Open " + title + " on Discogs?")) { window.open(url, "_blank"); }
}
function openCollDiscogs(el) {
  const url = el.dataset.url;
  const title = el.textContent.trim();
  if (!url) return;
  if (confirm("Open " + title + " on Discogs?")) { window.open(url, "_blank"); }
}
function toggleImport() { document.getElementById("importCard").classList.toggle("open"); }
function toggleCollection(header) {
  header.classList.toggle("open");
  document.getElementById("collectionBody").classList.toggle("open");
}
function getRecordsData() {
  const records = [];
  document.querySelectorAll(".record-row").forEach(row => {
    const title = row.querySelector(".record-title")?.textContent.trim();
    const artist = row.querySelector(".record-artist")?.textContent.trim();
    if (title) records.push({
      title, artist,
      release_id: row.dataset.id || "",
      url: row.dataset.url || "",
      low: row.dataset.low || "-",
      sale: row.dataset.sale || "0"
    });
  });
  return records;
}
function deleteRecord(btn) { btn.closest(".record-card").remove(); saveList(); }
function addRecord() {
  const input = document.getElementById("addInput");
  const value = input.value.trim();
  if (!value) return;
  input.value = "";
  const resultsDiv = document.getElementById("results");
  const addRowEl = resultsDiv.querySelector(".add-row-wrap");
  const card = document.createElement("div");
  card.className = "record-card";
  card.innerHTML = `<div class='record-row' data-id='' data-url='' data-low='-' data-sale='0'><div class='record-info'><span class='record-title' onclick='openDiscogs(this)'>${value}</span><div class='record-artist fetching-label'>searching...</div></div><div class='price-box'><span class='fetching-label'>fetching...</span></div><button class='del-btn' onclick='deleteRecord(this)'>&#10005;</button></div>`;
  resultsDiv.insertBefore(card, addRowEl);
  const endpoint = isDiscogsUrl(value) ? "/lookup_discogs_url" : "/search_and_price";
  fetch(endpoint, { method: "POST", headers: {"Content-Type":"application/json"}, body: JSON.stringify({query: value}) })
    .then(r => r.json())
    .then(res => {
      const row = card.querySelector(".record-row");
      row.dataset.id = res.release_id || "";
      row.dataset.url = res.url || "";
      row.dataset.low = res.low || "-";
      row.dataset.sale = res.sale || "0";
      row.querySelector(".record-title").textContent = res.title || value;
      row.querySelector(".record-artist").textContent = res.artist || "";
      row.querySelector(".record-artist").classList.remove("fetching-label");
      let priceHtml = "";
      if (!res.low || res.low === "N/A") {
        priceHtml = `<span class='na-price'>N/A</span>`;
      } else {
        priceHtml = `<div class='change-col'><span class='change'></span><span class='change'></span></div><div class='price-col'><div class='price-row'><span class='price-label'>Low</span><span class='low-price'>${res.low}</span></div><div class='price-row'><span class='price-label'>For sale</span><span class='sale-count'>${res.sale}</span></div></div>`;
      }
      row.querySelector(".price-box").innerHTML = priceHtml;
      const t = (res.title||value).replace(/"/g,"&quot;");
      const a = (res.artist||"").replace(/"/g,"&quot;");
      const buyBtn = document.createElement("button");
      buyBtn.className = "buy-btn";
      buyBtn.setAttribute("onclick", `openBuyModal(this,"${t}","${a}","${res.low}")`);
      buyBtn.textContent = "✓";
      row.insertBefore(buyBtn, row.querySelector(".del-btn"));
      saveList();
    })
    .catch(() => {
      card.querySelector(".record-artist").textContent = "Error";
      card.querySelector(".price-box").innerHTML = `<span class='na-price'>Error</span>`;
    });
}
function saveList() {
  const records = getRecordsData();
  const collection = getCollectionData();
  fetch("/save", { method: "POST", headers: {"Content-Type":"application/json"}, body: JSON.stringify({records, collection}) });
}
function setLoading(msg) {
  ["fetchBtn","updateBtn","updateAllBtn"].forEach(id => { const el = document.getElementById(id); if(el) el.disabled = true; });
  const s = document.getElementById("spinner"); s.style.display = "block"; s.textContent = msg;
}
function clearLoading() {
  ["fetchBtn","updateBtn","updateAllBtn"].forEach(id => { const el = document.getElementById(id); if(el) el.disabled = false; });
  document.getElementById("spinner").style.display = "none";
}
function changeHtml(val) {
  if (!val) return "<span class='change'></span>";
  const cls = val > 0 ? "up" : "down";
  const arrow = val > 0 ? "↑" : "↓";
  return `<span class='change ${cls}'>${arrow}${Math.abs(val)}%</span>`;
}
function calcDiffHtml(paid, market) {
  if (!paid || !market || market === "N/A" || market === "—") return "";
  const paidNum = parseFloat(paid.replace("$",""));
  const mktNum = parseFloat(market.replace("$","").replace(",",""));
  if (isNaN(paidNum) || isNaN(mktNum)) return "";
  const diff = mktNum - paidNum;
  return `<div class='coll-diff ${diff>=0?"profit":"loss"}'>${diff>=0?"+":""}$${Math.abs(diff).toFixed(2)}</div>`;
}
function renderResults(records, updated) {
  const resultsDiv = document.getElementById("results");
  let html = "";
  for (const r of records) {
    let priceHtml = (!r.low || r.low === "N/A")
      ? `<span class='na-price'>N/A</span>`
      : `<div class='change-col'>${changeHtml(r.low_change)}<span class='change'></span></div><div class='price-col'><div class='price-row'><span class='price-label'>Low</span><span class='low-price'>${r.low}</span></div><div class='price-row'><span class='price-label'>For sale</span><span class='sale-count'>${r.sale||"0"}</span></div></div>`;
    const t = (r.title||"").replace(/'/g,"&#39;").replace(/"/g,"&quot;");
    const a = (r.artist||"").replace(/"/g,"&quot;");
    const u = (r.url||"").replace(/"/g,"&quot;");
    html += `<div class='record-card'><div class='record-row' data-id='${r.release_id||""}' data-url='${u}' data-low='${r.low||"-"}' data-sale='${r.sale||"0"}'><div class='record-info'><span class='record-title' onclick='openDiscogs(this)'>${r.title||""}</span><div class='record-artist'>${r.artist||""}</div></div><div class='price-box'>${priceHtml}</div><button class='buy-btn' onclick='openBuyModal(this,"${t}","${a}","${r.low}")'>✓</button><button class='del-btn' onclick='deleteRecord(this)'>&#10005;</button></div></div>`;
  }
  html += `<div class='add-row-wrap'><input class='add-input' type='text' id='addInput' placeholder='Artist - Title or Discogs URL...' /><button class='add-btn' onclick='addRecord()'>+</button></div>`;
  resultsDiv.innerHTML = html;
  document.getElementById("lastUpdated").textContent = "Last updated: " + updated;
}
function fetchRecords() {
  const input = document.getElementById("recordInput").value.trim();
  if (!input) return;
  setLoading("Searching Discogs, please wait...");
  fetch("/import_records", { method: "POST", headers: {"Content-Type":"application/json"}, body: JSON.stringify({text: input}) })
    .then(r => r.json())
    .then(res => { clearLoading(); renderResults(res.records, res.updated); document.getElementById("recordInput").value = ""; document.getElementById("importCard").classList.remove("open"); })
    .catch(() => clearLoading());
}
function updatePrices() {
  const records = getRecordsData();
  setLoading("Updating prices...");
  fetch("/update", { method: "POST", headers: {"Content-Type":"application/json"}, body: JSON.stringify({records}) })
    .then(r => r.json())
    .then(res => { clearLoading(); renderResults(res.records, res.updated); })
    .catch(() => clearLoading());
}
function confirmUpdateAll() {
  if (confirm("Update All re-fetches every record. Continue?")) {
    setLoading("Refreshing all prices...");
    fetch("/refresh", { method: "POST" })
      .then(r => r.json())
      .then(res => { clearLoading(); renderResults(res.records, res.updated); renderCollection(res.collection); })
      .catch(() => clearLoading());
  }
}
let _buyRow = null;
function openBuyModal(btn, title, artist, low) {
  _buyRow = btn.closest(".record-row");
  document.getElementById("buyModalName").textContent = title + (artist ? " — " + artist : "");
  document.getElementById("buyModalTitle").value = title;
  document.getElementById("buyModalArtist").value = artist;
  document.getElementById("buyModalLow").value = low;
  document.getElementById("buyModalUrl").value = _buyRow ? (_buyRow.dataset.url||"") : "";
  document.getElementById("buyModalReleaseId").value = _buyRow ? (_buyRow.dataset.id||"") : "";
  document.getElementById("buyModalPaid").value = "";
  document.getElementById("buyModal").classList.add("open");
}
function closeBuyModal() { document.getElementById("buyModal").classList.remove("open"); _buyRow = null; }
function confirmBuy() {
  const title = document.getElementById("buyModalTitle").value;
  const artist = document.getElementById("buyModalArtist").value;
  const paid = document.getElementById("buyModalPaid").value;
  const condition = document.getElementById("buyModalCondition").value;
  const low = document.getElementById("buyModalLow").value;
  const url = document.getElementById("buyModalUrl").value;
  const release_id = document.getElementById("buyModalReleaseId").value;
  if (!paid) { alert("Please enter what you paid."); return; }
  addCollItem({title, artist, paid: "$" + parseFloat(paid).toFixed(2), condition, low, url, release_id, id: Date.now().toString()});
  if (_buyRow) { _buyRow.closest(".record-card").remove(); saveList(); }
  closeBuyModal();
}
function openAddCollModal() {
  const val = document.getElementById("collAddInput").value.trim();
  document.getElementById("collAddInput").value = "";
  const parts = val.split(" - ");
  document.getElementById("addCollArtist").value = parts[0] || "";
  document.getElementById("addCollTitle").value = parts.slice(1).join(" - ") || "";
  document.getElementById("addCollPaid").value = "";
  document.getElementById("addCollModal").classList.add("open");
}
function closeAddCollModal() { document.getElementById("addCollModal").classList.remove("open"); }
function confirmAddCollection() {
  const artist = document.getElementById("addCollArtist").value.trim();
  const title = document.getElementById("addCollTitle").value.trim();
  const paid = document.getElementById("addCollPaid").value;
  const condition = document.getElementById("addCollCondition").value;
  if (!title || !paid) { alert("Please fill in title and price."); return; }
  setLoading("Looking up price...");
  fetch("/search_and_price", { method: "POST", headers: {"Content-Type":"application/json"}, body: JSON.stringify({query: artist + " - " + title}) })
    .then(r => r.json())
    .then(res => {
      clearLoading();
      addCollItem({title: res.title||title, artist: res.artist||artist, paid: "$" + parseFloat(paid).toFixed(2), condition, low: res.low, url: res.url, release_id: res.release_id, id: Date.now().toString()});
      closeAddCollModal(); saveList();
    })
    .catch(() => { clearLoading(); addCollItem({title, artist, paid: "$" + parseFloat(paid).toFixed(2), condition, low: null, id: Date.now().toString()}); closeAddCollModal(); saveList(); });
}
function addCollItem(item) {
  const body = document.getElementById("collectionBody");
  const addRow = body.querySelector(".coll-add-row");
  const diffHtml = calcDiffHtml(item.paid, item.low);
  const row = document.createElement("div");
  row.className = "coll-row";
  row.dataset.id = item.id;
  row.dataset.releaseId = item.release_id || "";
  row.innerHTML = `<div class='coll-info'><div class='coll-title' onclick='openCollDiscogs(this)' data-url='${item.url||""}'>${item.title}</div><div class='coll-artist'>${item.artist||""} &middot; <span class='coll-condition'>${item.condition}</span></div></div><div class='coll-prices'><div class='coll-paid'>Paid: ${item.paid}</div><div class='coll-market'>${item.low && item.low !== "N/A" ? item.low : "—"}</div>${diffHtml}</div><button class='del-btn' onclick='deleteCollItem(this)'>&#10005;</button>`;
  body.insertBefore(row, addRow);
  document.querySelector(".collection-header").classList.add("open");
  document.getElementById("collectionBody").classList.add("open");
}
function deleteCollItem(btn) {
  if (!confirm("Remove this record from your collection?")) return;
  btn.closest(".coll-row").remove(); saveList();
}
function getCollectionData() {
  const items = [];
  document.querySelectorAll(".coll-row").forEach(row => {
    const titleEl = row.querySelector(".coll-title");
    const title = titleEl?.textContent.trim();
    const artistEl = row.querySelector(".coll-artist");
    const artist = artistEl ? artistEl.textContent.split("·")[0].trim() : "";
    const condition = row.querySelector(".coll-condition")?.textContent.trim();
    const paidEl = row.querySelector(".coll-paid");
    const paid = paidEl ? paidEl.textContent.replace("Paid: ","").trim() : "";
    const url = titleEl?.dataset.url || "";
    const release_id = row.dataset.releaseId || "";
    if (title) items.push({id: row.dataset.id || Date.now().toString(), title, artist, condition, paid, url, release_id});
  });
  return items;
}
function renderCollection(collection) {
  if (!collection) return;
  const body = document.getElementById("collectionBody");
  const addRow = body.querySelector(".coll-add-row");
  body.querySelectorAll(".coll-row").forEach(r => r.remove());
  collection.forEach(item => {
    const diffHtml = calcDiffHtml(item.paid, item.low);
    const row = document.createElement("div");
    row.className = "coll-row";
    row.dataset.id = item.id;
    row.dataset.releaseId = item.release_id || "";
    row.innerHTML = `<div class='coll-info'><div class='coll-title' onclick='openCollDiscogs(this)' data-url='${item.url||""}'>${item.title}</div><div class='coll-artist'>${item.artist||""} &middot; <span class='coll-condition'>${item.condition}</span></div></div><div class='coll-prices'><div class='coll-paid'>Paid: ${item.paid}</div><div class='coll-market'>${item.low && item.low !== "N/A" ? item.low : "—"}</div>${diffHtml}</div><button class='del-btn' onclick='deleteCollItem(this)'>&#10005;</button>`;
    body.insertBefore(row, addRow);
  });
}
</script>
</body>
</html>
"""

@app.route("/")
def index():
    saved = load_gist()
    return render_template_string(HTML_TEMPLATE,
        records=saved.get("records", []),
        collection=saved.get("collection", []),
        updated=saved.get("updated"))

@app.route("/import_records", methods=["POST"])
def import_records():
    body = request.get_json()
    text = body.get("text", "")
    saved = load_gist()
    existing = {r["title"].lower(): r for r in saved.get("records", [])}
    new_records = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        parts = line.split(" - ", 1)
        artist = parts[0].strip() if len(parts) > 1 else ""
        title_q = parts[1].strip() if len(parts) > 1 else parts[0].strip()
        if title_q.lower() in existing:
            continue
        time.sleep(0.5)
        release_id, full_title, art, url = search_discogs(artist, title_q)
        low, sale = (None, None)
        if release_id:
            time.sleep(0.5)
            low, sale = get_prices_by_release_id(release_id)
        new_records.append({"title": full_title, "artist": artist or art, "release_id": release_id, "url": url, "low": low or "N/A", "sale": sale or "0"})
    all_records = saved.get("records", []) + new_records
    all_records = sorted(all_records, key=lambda x: x.get("title","").lower())
    updated = now_str()
    save_gist({"records": all_records, "collection": saved.get("collection", []), "updated": updated})
    return jsonify({"records": all_records, "updated": updated})

@app.route("/search_and_price", methods=["POST"])
def search_and_price():
    body = request.get_json()
    query = body.get("query", "")
    parts = query.split(" - ", 1)
    artist = parts[0].strip() if len(parts) > 1 else ""
    title = parts[1].strip() if len(parts) > 1 else query.strip()
    release_id, full_title, art, url = search_discogs(artist, title)
    low, sale = (None, None)
    if release_id:
        time.sleep(0.3)
        low, sale = get_prices_by_release_id(release_id)
    return jsonify({"title": full_title, "artist": artist or art, "release_id": release_id, "url": url, "low": low or "N/A", "sale": sale or "0"})

@app.route("/lookup_discogs_url", methods=["POST"])
def lookup_discogs_url():
    body = request.get_json()
    url = body.get("query", "")
    m = re.search(r'/release/(\d+)', url)
    release_id = m.group(1) if m else None
    title, artist = url, ""
    if release_id:
        try:
            r = requests.get(f"https://api.discogs.com/releases/{release_id}", headers=DISCOGS_HEADERS, timeout=10)
            data = r.json()
            title = data.get("title", url)
            artists = data.get("artists", [])
            artist = artists[0].get("name","") if artists else ""
        except:
            pass
    low, sale = (None, None)
    if release_id:
        low, sale = get_prices_by_release_id(release_id)
    return jsonify({"title": title, "artist": artist, "release_id": release_id, "url": url, "low": low or "N/A", "sale": sale or "0"})

@app.route("/update", methods=["POST"])
def update():
    body = request.get_json()
    records = body.get("records", [])
    saved = load_gist()
    existing = {r.get("release_id"): r for r in saved.get("records", []) if r.get("release_id")}
    updated_records = []
    for r in records:
        rid = r.get("release_id")
        if rid and existing.get(rid, {}).get("low") not in (None, "N/A", "-"):
            updated_records.append(existing[rid])
        elif rid:
            time.sleep(0.5)
            updated_records.append(enrich_record(dict(r)))
        else:
            updated_records.append(r)
    updated_records = sorted(updated_records, key=lambda x: x.get("title","").lower())
    updated = now_str()
    save_gist({"records": updated_records, "collection": saved.get("collection", []), "updated": updated})
    return jsonify({"records": updated_records, "updated": updated})

@app.route("/refresh", methods=["POST"])
def refresh():
    saved = load_gist()
    records = saved.get("records", [])
    collection = saved.get("collection", [])
    refreshed = []
    for r in records:
        time.sleep(0.5)
        refreshed.append(enrich_record(dict(r)))
    refreshed = sorted(refreshed, key=lambda x: x.get("title","").lower())
    refreshed_coll = []
    for item in collection:
        time.sleep(0.5)
        rid = item.get("release_id")
        if rid:
            low, sale = get_prices_by_release_id(rid)
            item["low"] = low or item.get("low", "N/A")
            item["sale"] = sale or item.get("sale", "0")
        refreshed_coll.append(item)
    updated = now_str()
    save_gist({"records": refreshed, "collection": refreshed_coll, "updated": updated})
    return jsonify({"records": refreshed, "collection": refreshed_coll, "updated": updated})

@app.route("/save", methods=["POST"])
def save():
    body = request.get_json()
    records = body.get("records", [])
    collection = body.get("collection", [])
    saved = load_gist()
    existing = {r.get("release_id"): r for r in saved.get("records", []) if r.get("release_id")}
    merged = []
    for r in records:
        rid = r.get("release_id")
        ex = existing.get(rid, {})
        merged.append({
            "title": r.get("title", ex.get("title","")),
            "artist": r.get("artist", ex.get("artist","")),
            "release_id": rid,
            "url": r.get("url") or ex.get("url",""),
            "low": r.get("low") if r.get("low") not in (None,"-","") else ex.get("low","N/A"),
            "sale": r.get("sale") if r.get("sale") not in (None,"","0") else ex.get("sale","0"),
            "low_change": ex.get("low_change"),
        })
    saved_coll = {item["id"]: item for item in saved.get("collection", [])}
    merged_coll = []
    for item in collection:
        if item["id"] in saved_coll:
            si = saved_coll[item["id"]]
            item["low"] = si.get("low", item.get("low"))
            item["url"] = item.get("url") or si.get("url","")
        merged_coll.append(item)
    save_gist({"records": merged, "collection": merged_coll, "updated": saved.get("updated")})
    return jsonify({"ok": True})

if __name__ == "__main__":
    app.run()
