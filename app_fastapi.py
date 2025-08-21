import sys
import csv
import time
import locale
import logging
import requests
import numpy as np
# from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright
from sklearn.cluster import KMeans
import matplotlib.pyplot as plt
from fastapi import FastAPI, Query
from pydantic import BaseModel
from typing import List, Dict, Optional
from fastapi.responses import FileResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
import io
import base64




# ------------------ Setup ------------------
locale.setlocale(locale.LC_ALL, '')
logging.basicConfig(level=logging.INFO,
                    format='%(asctime)s - %(levelname)s - %(message)s')

api_all_currencies: dict = requests.get(
    'https://cdn.jsdelivr.net/npm/@fawazahmed0/currency-api@latest/v1/currencies.json'
).json()

headers: dict = {
    'User-Agent': 'Mozilla/5.0 (X11; Ubuntu; Linux x86_64; rv:91.0) Gecko/20100101 Firefox/91.0'
}

symbols_hash_map: dict = {
    '$': 'usd', '€': 'eur', '£': 'gbp', '¥': 'jpy', '₩': 'krw',
    '₹': 'inr', '₽': 'rub', '₱': 'php', 'R$': 'brl', '₿': 'btc'
}

remove_currency_from_csv: bool = True
currency_symbol: str = "$"
currency: str = "usd"
api_url_for_currencies: dict = {}

# ------------------ Utility Functions ------------------


def convert_price(price_data: str, source_url: str) -> str:
    try:
        price_data = price_data.replace(u'\xa0', ' ').strip()
        original_symbol = ''.join(c for c in price_data.split(
        )[0] if not c.isdigit() and c not in ('.', ',')).strip()
        if not original_symbol:
            original_symbol = '$'
        original_currency = symbols_hash_map.get(original_symbol, 'usd')

        if 'to' in price_data.lower():
            price_parts = price_data.split('to')[0]
        else:
            price_parts = price_data

        numeric_part = ''.join(
            c for c in price_parts if c.isdigit() or c == '.')
        amount = float(numeric_part) if numeric_part else 0.0
        converted_amount = amount / \
            api_url_for_currencies[currency][original_currency]

        return f'{converted_amount:.2f}' if remove_currency_from_csv else f'{currency_symbol} {converted_amount:.2f}'
    except Exception as e:
        logging.warning(f"Price conversion failed for '{price_data}': {e}")
        return '0.00'


def parse_amazon(target_url) -> List[Dict]:
    data: list = []
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        page = browser.new_page()
        page.goto(target_url)

        try:
            items = page.query_selector_all('div.a-section.a-spacing-small')
            for item in items:
                if item.query_selector('h2.a-size-mini > a > span'):
                    item_data = {
                        'Name': item.query_selector('h2.a-size-mini > a > span').inner_text(),
                        'Price': convert_price(item.query_selector('span.a-price > span.a-offscreen').inner_text(), 'amazon'),
                        'Link': f"https://amazon.com{item.query_selector('h2.a-size-mini > a').get_attribute('href')}"
                    }
                    data.append(item_data)
            browser.close()
        except AttributeError as e:
            logging.warning(f"Skipping item due to missing data: {e}")
    return data


def parse_ebay_playwright(target_url: str) -> List[Dict]:
    data: list = []
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        page = browser.new_page()
        page.goto(target_url, wait_until="domcontentloaded")

        items = page.query_selector_all('li.s-item')
        for item in items:
            try:
                title = item.query_selector('div.s-item__title')
                price = item.query_selector('span.s-item__price')
                link = item.query_selector('a.s-item__link')
                if title and price and link:
                    item_data = {
                        'Name': title.inner_text().strip(),
                        'Price': convert_price(price.inner_text().strip(), 'ebay'),
                        'Link': link.get_attribute('href')
                    }
                    data.append(item_data)
            except Exception as e:
                logging.warning(f"Skipping eBay item: {e}")
        browser.close()
    return data

# def parse_ebay(soup: BeautifulSoup) -> List[Dict]:
#     data: list = []
#     items = soup.find_all('li', class_='s-item s-item__pl-on-bottom')
#     for item in items:
#         if item.find('div', class_='s-item__title').text.strip() != 'Shop on eBay':
#             try:
#                 item_data = {
#                     'Name': item.find('div', class_='s-item__title').text.strip(),
#                     'Price': convert_price(item.find('span', class_='s-item__price').text.strip(), 'ebay'),
#                     'Link': item.find('a', href=True)['href']
#                 }
#                 data.append(item_data)
#             except AttributeError as e:
#                 logging.warning(f"Skipping item due to missing data: {e}")
#     return data


# def parse_html(html: str, target_url: str) -> List[Dict]:
#     soup = BeautifulSoup(html, 'html.parser')
#     if 'ebay' in target_url:
#         return parse_ebay(soup)
#     else:
#         logging.warning(f"No parsing logic for {target_url}")
#         return []


def fetch_html(url: str, headers: dict | None = None) -> Optional[str]:
    try:
        response = requests.get(url, headers=headers)
        response.raise_for_status()
        return response.text
    except requests.RequestException as e:
        logging.error(f"Error fetching {url}: {e}")
        return None


def scrape_website(target_url: str, pages: int = 1, sleep_time: int = 1) -> List[Dict]:
    all_data: list = []
    for page in range(1, pages + 1):
        url = f"{target_url}&page={page}"
        logging.info(f"Scraping {url}")

        # Handle website-specific parsing
        if "ebay.com" in target_url:
            all_data.extend(parse_ebay_playwright(url))
        elif "amazon.com" in target_url:
            all_data.extend(parse_amazon(url))
        else:
            html = fetch_html(url, headers)
            if html:
                data = parse_html(html, target_url)
                all_data.extend(data)
                logging.info(
                    f"Page {page} scraped successfully, {len(data)} items found."
                )

        time.sleep(sleep_time)

    return all_data

# def scrape_website(target_url: str, pages: int = 1, sleep_time: int = 1) -> List[Dict]:
#     all_data: list = []
#     for page in range(1, pages + 1):
#         url = f"{target_url}&page={page}"
#         logging.info(f"Scraping {url}")
#         if url.startswith('https://amazon'):
#             all_data.extend(parse_amazon(url))
#         else:
#             html = fetch_html(url, headers)
#             if html:
#                 data = parse_html(html, target_url)
#                 all_data.extend(data)
#                 logging.info(
#                     f"Page {page} scraped successfully, {len(data)} items found.")
#         time.sleep(sleep_time)
#     return all_data


def save_to_csv(data: List[Dict], filename: str = 'output.csv'):
    if not data:
        return
    keys = data[0].keys()
    with open(filename, mode='w', newline='', encoding='utf-8') as file:
        writer = csv.DictWriter(file, fieldnames=keys)
        writer.writeheader()
        writer.writerows(data)



def pie_graph_base64(data: list) -> str | None:
    if not data:
        return None
    prices = []
    for item in data:
        if ',' in item['Price']:
            prices.extend([float(v) for v in item['Price'].split(', ')])
        else:
            try:
                prices.append(float(item['Price']))
            except ValueError:
                continue

    if not prices:
        return None

    numpy_prices = np.array(prices).reshape(-1, 1)
    n_clusters = min(5, len(numpy_prices))
    if n_clusters == 0:
        return None

    kmeans = KMeans(n_clusters=n_clusters, random_state=0).fit(numpy_prices)
    labels = kmeans.predict(numpy_prices)
    unique_labels, counts = np.unique(labels, return_counts=True)
    price_ranges = [(int(numpy_prices[labels == l].min()), int(numpy_prices[labels == l].max()))
                    for l in unique_labels]
    label_names = [f'Around {currency_symbol}{low}-{high}' for low, high in price_ranges]

    plt.figure(figsize=(8, 6))
    plt.pie(counts, labels=label_names, autopct='%1.1f%%')
    plt.tight_layout()

    buffer = io.BytesIO()
    plt.savefig(buffer, format='png')
    plt.close()
    buffer.seek(0)
    img_base64 = base64.b64encode(buffer.read()).decode('utf-8')
    return f"data:image/png;base64,{img_base64}"


# def pie_graph(data: List[Dict], filename: str):
#     if not data:
#         return
#     prices = []
#     for item in data:
#         if ',' in item['Price']:
#             prices.extend([float(v) for v in item['Price'].split(', ')])
#         else:
#             prices.append(float(item['Price']))

#     numpy_prices = np.array(prices).reshape(-1, 1)
#     kmeans = KMeans(n_clusters=5, random_state=0).fit(numpy_prices)
#     labels = kmeans.predict(numpy_prices)

#     unique_labels, counts = np.unique(labels, return_counts=True)
#     price_ranges = [(int(numpy_prices[labels == l].min()), int(
#         numpy_prices[labels == l].max())) for l in unique_labels]

#     label_names = [
#         f'Around {currency_symbol}{low}-{high}' for low, high in price_ranges]
#     plt.figure(figsize=(10, 8))
#     plt.pie(counts, autopct='%1.1f%%')
#     plt.legend(label_names, loc='upper right')
#     plt.savefig(filename)


# ------------------ FastAPI ------------------
app = FastAPI()





# Allow your frontend domain
origins = [
    "https://babyshare.vercel.app",
    "http://localhost:3000",  # for local testing
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,          # domains allowed
    allow_credentials=True,
    allow_methods=["*"],            # GET, POST, etc.
    allow_headers=["*"],            # headers like Content-Type
)





app.mount("/files", StaticFiles(directory="."), name="files")


class ScrapeRequest(BaseModel):
    search_field: str
    currency: str = "usd"
    remove_currency: bool = True
    pages: int = 3



@app.post("/scrape/")
def scrape(request: ScrapeRequest):
    global currency, currency_symbol, remove_currency_from_csv, api_url_for_currencies

    currency = request.currency.lower()
    if currency not in symbols_hash_map.values():
        return {"error": "Unsupported currency"}

    currency_symbol = [k for k, v in symbols_hash_map.items() if v == currency][0]
    remove_currency_from_csv = request.remove_currency

    api_url_for_currencies = requests.get(
        f'https://cdn.jsdelivr.net/npm/@fawazahmed0/currency-api@latest/v1/currencies/{currency}.json'
    ).json()

    urls_to_scrape = [
        f'https://amazon.com/s?k={request.search_field}&s=exact-aware-popularity-rank',
        f'https://ebay.com/sch/i.html?_nkw={request.search_field}'
    ]

    all_scraped_data = []
    for url in urls_to_scrape:
        scraped = scrape_website(url, pages=request.pages)
        all_scraped_data.extend(scraped)

    save_to_csv(all_scraped_data, 'scraped_data.csv')
    graph_base64 = pie_graph_base64(all_scraped_data)

    return {
        "items_found": len(all_scraped_data),
        "csv_file": "scraped_data.csv",
        "graph_base64": graph_base64,
        "data_preview": all_scraped_data[:5]
    }

# @app.post("/scrape/")
# def scrape(request: ScrapeRequest):
#     global currency, currency_symbol, remove_currency_from_csv, api_url_for_currencies

#     currency = request.currency.lower()
#     if currency not in symbols_hash_map.values():
#         return {"error": "Unsupported currency"}

#     currency_symbol = [k for k, v in symbols_hash_map.items()
#                        if v == currency][0]
#     remove_currency_from_csv = request.remove_currency

#     api_url_for_currencies = requests.get(
#         f'https://cdn.jsdelivr.net/npm/@fawazahmed0/currency-api@latest/v1/currencies/{currency}.json'
#     ).json()

#     urls_to_scrape = [
#         f'https://amazon.com/s?k={request.search_field}&s=exact-aware-popularity-rank',
#         f'https://ebay.com/sch/i.html?_nkw={request.search_field}'
#     ]

#     all_scraped_data = []
#     for url in urls_to_scrape:
#         scraped = scrape_website(url, pages=request.pages)
#         all_scraped_data.extend(scraped)

#     save_to_csv(all_scraped_data, 'scraped_data.csv')
#     pie_graph(all_scraped_data, 'scraped_data_graph.png')

#     return {
#         "items_found": len(all_scraped_data),
#         "csv_file": "scraped_data.csv",
#         "graph_file": "scraped_data_graph.png",
#         "data_preview": all_scraped_data[:5]
#     }




@app.get("/download/csv")
def download_csv():
    file_path = "scraped_data.csv"
    return FileResponse(file_path, media_type="text/csv", filename="scraped_data.csv")

@app.get("/download/graph")
def download_graph():
    file_path = "scraped_data_graph.png"
    return FileResponse(file_path, media_type="image/png", filename="scraped_data_graph.png")
