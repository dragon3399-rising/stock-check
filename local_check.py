#!/usr/bin/env python3
"""ローカル巡回用スクリプト（家庭IPで実行する側）。

GitHub Actions（Azure IP）がbot判定されるサイトを家庭IPからチェックし、
verify_log_local.csv（本垢）/ verify_log_local_sub.csv（サブ垢・価格監視つき）に追記する。
curlで判定できないサイト（駿河屋・任天堂・メルカリShops等）は標準出力に
「ブラウザ確認が必要」リストとして出すので、呼び出し元（AIタスク）がブラウザで確認して追記する。

使い方: リポジトリのクローン内で `SHEET_ID=... SHEET_ID_SUB=... python3 local_check.py`
（環境変数 DATA_DIR でverify_log_local*.csvの出力先ディレクトリを指定可能。既定はカレントディレクトリ）
"""
from __future__ import annotations

import csv
import os
import re
import sys
import time
import urllib.parse
from datetime import datetime

import check_stock as cs

SHEET_ID = os.environ.get("SHEET_ID", "")
SHEET_ID_SUB = os.environ.get("SHEET_ID_SUB", "")
SHEET_SUB_GID = os.environ.get("SHEET_SUB_GID", "")

HTTP_HOSTS = {"www.amazon.co.jp", "item.rakuten.co.jp",
              "biccamera.rakuten.co.jp", "www.yodobashi.com"}
BROWSER_HOSTS = {"www.suruga-ya.jp", "store-jp.nintendo.com"}

ASIN_RE = re.compile(r"/(?:dp|gp/product)/([A-Z0-9]{10})")


def amazon_price(html: str) -> int | None:
    """買い箱（メイン価格）の金額を取得。取れなければNone。"""
    m = (re.search(r'corePrice.{0,600}?a-offscreen">(?:￥|\\u00a5)?\s*([\d,]+)', html, re.S)
         or re.search(r'a-price-whole">([\d,]+)', html))
    return int(m.group(1).replace(",", "")) if m else None


def check_amazon(url: str) -> tuple[str, str, int | None]:
    m = ASIN_RE.search(url)
    if not m:
        return cs.UNKNOWN, "ASIN抽出失敗", None
    status, html = cs.fetch_html(f"https://www.amazon.co.jp/dp/{m.group(1)}?th=1")
    if status in (404, 410):
        return cs.LINK_DEAD, f"HTTP {status}", None
    if status != 200:
        return cs.UNKNOWN, f"HTTP {status}", None
    result = cs.rule_amazon(html)
    if result is None:
        return cs.UNKNOWN, "在庫表示が見つからない", None
    cat, reason = result
    return cat, reason, (amazon_price(html) if cat == cs.IN_STOCK else None)


def check_yodobashi(url: str) -> tuple[str, str]:
    status, html = cs.fetch_html(url)
    if status in (404, 410):
        return cs.LINK_DEAD, f"HTTP {status}"
    if status != 200:
        return cs.UNKNOWN, f"HTTP {status}（bot対策の可能性）"
    if "販売休止中" in html or "予定数の販売を終了" in html or "販売を終了しました" in html:
        return cs.OUT_OF_STOCK, "販売終了/休止表示"
    if "ショッピングカートに入れる" in html or "カートに入れる" in html:
        return cs.IN_STOCK, "カートボタンあり"
    return cs.UNKNOWN, "在庫表示が見つからない"


def check_row(row: dict) -> dict:
    url = row["url"]
    host = urllib.parse.urlparse(url).netloc
    price = None
    if host == "www.amazon.co.jp":
        cat, reason, price = check_amazon(url)
    elif host in ("item.rakuten.co.jp", "biccamera.rakuten.co.jp"):
        status, html = cs.fetch_html(url)
        if status in (404, 410):
            cat, reason = cs.LINK_DEAD, f"HTTP {status}"
        elif status != 200:
            cat, reason = cs.UNKNOWN, f"HTTP {status}"
        else:
            cat, reason = cs.rule_rakuten(html) or cs.rule_jsonld(html) \
                or (cs.UNKNOWN, "在庫表示が見つからない")
    elif host == "www.yodobashi.com":
        cat, reason = check_yodobashi(url)
    else:
        cat, reason = cs.UNKNOWN, "ローカルスクリプト対象外"
    out = {**row, "category": cat, "reason": reason, "site": host}
    reg = row.get("reg_price")
    if price and reg:
        dev = (price - reg) / reg
        if abs(dev) >= cs.PRICE_ALERT_PCT:
            out["price_alert"] = f"¥{reg:,}→¥{price:,}（{dev:+.1%}）"
    return out


def append_local_log(path: str, rows: list[dict], with_price: bool) -> None:
    new_file = not os.path.exists(path)
    ts = datetime.now(cs.JST).strftime("%Y-%m-%d %H:%M")
    with open(path, "a", newline="") as f:
        w = csv.writer(f)
        if new_file:
            header = ["datetime_jst", "sku", "url", "category", "reason"]
            w.writerow(header + (["price_alert"] if with_price else []))
        for r in rows:
            line = [ts, r["sku"], r["url"], r["category"], r["reason"]]
            if with_price:
                line.append(r.get("price_alert", ""))
            w.writerow(line)


def main() -> int:
    if not SHEET_ID:
        cs.log("SHEET_ID環境変数が未設定です。終了します。")
        return 1
    rows_main, _ = cs.fetch_sheet(SHEET_ID)
    rows_sub, _ = cs.fetch_sheet_sub(SHEET_ID_SUB, SHEET_SUB_GID) if SHEET_ID_SUB else ([], {})
    targets, browser_needed = [], []
    for row in rows_main + rows_sub:
        host = urllib.parse.urlparse(row["url"]).netloc
        if host in HTTP_HOSTS:
            targets.append(row)
        elif host in BROWSER_HOSTS or "jp.mercari.com/shops/" in row["url"]:
            browser_needed.append(row)

    cs.log(f"ローカル巡回対象: HTTP判定{len(targets)}件 / ブラウザ確認{len(browser_needed)}件")
    results = []
    for row in targets:
        results.append(check_row(row))
        time.sleep(1.5)

    append_local_log(cs.data_path("verify_log_local.csv"),
                     [r for r in results if r["account"] == "本垢"], with_price=False)
    append_local_log(cs.data_path("verify_log_local_sub.csv"),
                     [r for r in results if r["account"] == "サブ垢"], with_price=True)

    counts = {c: sum(1 for r in results if r["category"] == c)
              for c in (cs.IN_STOCK, cs.OUT_OF_STOCK, cs.LINK_DEAD, cs.UNKNOWN)}
    cs.log(f"HTTP判定結果: {counts}")
    for r in results:
        if r["category"] != cs.IN_STOCK or r.get("price_alert"):
            cs.log(f"  {r['category']:12} {r['sku']:8} {r['site']} {r['reason']} "
                   f"{r.get('price_alert', '')}")
    print("\n=== ブラウザ確認が必要（この結果はAIが確認してCSVに追記すること） ===")
    for r in browser_needed:
        print(f"{r['account']}\t{r['sku']}\t{r['url']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
