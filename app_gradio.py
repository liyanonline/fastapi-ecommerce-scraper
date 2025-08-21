from typing import List, Dict
import csv
import time
import locale
import logging
import requests
import numpy as np
from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright
from sklearn.cluster import KMeans
import matplotlib.pyplot as plt
import gradio as gr
from datetime import datetime
import os

remove_currency_from_csv = True
locale.setlocale(locale.LC_ALL, '')
logging.basicConfig(level=logging.INFO,
                    format='%(asctime)s - %(levelname)s - %(message)s')
api_all_currencies = requests.get(
    'https://cdn.jsdelivr.net/npm/@fawazahmed0/currency-api@latest/v1/currencies.json').json()
headers = {
    'User-Agent': 'Mozilla/5.0 (X11; Ubuntu; Linux x86_64; rv:91.0) Gecko/20100101 Firefox/91.0'}
symbols_hash_map = {
    '$': 'usd', '€': 'eur', '£': 'gbp', '¥': 'jpy', '₩': 'krw',
    '₹': 'inr', '₽': 'rub', '₱': 'php', 'R$': 'brl', '₿': 'btc'
}


def convert_price(price_data: str, source_url: str) -> str:
    try:
        price_data = price_data.replace(u'\xa0', ' ').strip()
        original_symbol = ''.join(c for c in price_data.split(
        )[0] if not c.isdigit() and c not in ('.', ',')).strip() or '$'
        original_currency = symbols_hash_map.get(original_symbol, 'usd')
        numeric_part = ''.join(c for c in price_data.split('to')[
                               0] if c.isdigit() or c == '.')
        amount = float(numeric_part) if numeric_part else 0.0
        converted_amount = amount / \
            api_url_for_currencies[currency][original_currency]
        return f'{converted_amount:.2f}' if remove_currency_from_csv else f'{currency_symbol} {converted_amount:.2f}'
    except Exception as e:
        logging.warning(f"Price conversion failed for '{price_data}': {e}")
        return '0.00'


def parse_amazon(target_url):
    data = []
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        page = browser.new_page()
        page.goto(target_url)
        try:
            items = page.query_selector_all('div.a-section.a-spacing-small')
            for item in items:
                if item.query_selector('h2.a-size-mini > a > span'):
                    href = item.query_selector(
                        'h2.a-size-mini > a').get_attribute('href')
                    item_data = {
                        'Name': item.query_selector('h2.a-size-mini > a > span').inner_text(),
                        'Price': convert_price(item.query_selector('span.a-price > span.a-offscreen').inner_text(), 'amazon'),
                        'Link': f'https://amazon.com{href}'
                    }
                    data.append(item_data)
            browser.close()
        except AttributeError as e:
            logging.warning(f"Skipping item due to missing data: {e}")
    return data


def parse_ebay(soup: BeautifulSoup):
    data = []
    items = soup.find_all('li', class_='s-item s-item__pl-on-bottom')
    for item in items:
        if item.find('div', class_='s-item__title').text.strip() != 'Shop on eBay':
            try:
                item_data = {
                    'Name': item.find('div', class_='s-item__title').text.strip(),
                    'Price': convert_price(item.find('span', class_='s-item__price').text.strip(), 'ebay'),
                    'Link': item.find('a', href=True)['href']
                }
                data.append(item_data)
            except AttributeError as e:
                logging.warning(f"Skipping item due to missing data: {e}")
    return data


def fetch_html(url: str, headers: dict = None):
    try:
        response = requests.get(url)
        response.raise_for_status()
        return response.text
    except requests.RequestException as e:
        logging.error(f"Error fetching {url}: {e}")
        return None


def parse_html(html: str, target_url: str):
    soup = BeautifulSoup(html, 'html.parser')
    if 'ebay' in target_url:
        return parse_ebay(soup)
    return []


def scrape_website(target_url: str, headers: dict = None, pages: int = 1, sleep_time: int = 1):
    all_data = []
    for page in range(1, pages + 1):
        url = f"{target_url}&page={page}"
        logging.info(f"Scraping {url}")
        if 'amazon' in url:
            all_data.extend(parse_amazon(url))
        else:
            html = fetch_html(url, headers)
            if html:
                all_data.extend(parse_html(html, url))
        time.sleep(sleep_time)
    return all_data


def save_to_csv(data: list[dict], filename: str):
    if not data:
        return None

    # ✅ Always use /tmp for Cloud Run / GCP containers
    output_dir = "/tmp/output"
    os.makedirs(output_dir, exist_ok=True)

    output_path = os.path.join(output_dir, filename)
    keys = data[0].keys()

    with open(output_path, mode="w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=keys)
        writer.writeheader()
        writer.writerows(data)

    return output_path  # return path so you know where it is
# def save_to_csv(data: list[dict], filename: str):
#     if not data:
#         return

#     output_dir = "/usr/src/app/output"
#     os.makedirs(output_dir, exist_ok=True)  # ✅ create folder if missing

#     output_path = os.path.join(output_dir, filename)
#     keys = data[0].keys()

#     with open(output_path, mode="w", newline="", encoding="utf-8") as file:
#         writer = csv.DictWriter(file, fieldnames=keys)
#         writer.writeheader()
#         writer.writerows(data)

#     return output_path  # return path for confirmation

# # def save_to_csv(data: list[dict], filename: str):
# #     if not data:
# #         return
# #     output_path = os.path.join('/usr/src/app/output', filename)
# #     keys = data[0].keys()
# #     with open(output_path, mode='w', newline='', encoding='utf-8') as file:
# #         writer = csv.writer(file)
# #         writer.writerow(keys)
# #         for row in data:
# #             writer.writerow(row.values())


def pie_graph(data: list[dict], filename: str):
    if not data:
        return
    output_path = os.path.join('/usr/src/app/output', filename)
    prices = [float(item['Price'].replace(
        currency_symbol, '').split(',')[0]) for item in data]
    numpy_prices = np.array(prices).reshape(-1, 1)
    kmeans = KMeans(n_clusters=5, random_state=0).fit(numpy_prices)
    labels = kmeans.predict(numpy_prices)
    unique_labels, counts = np.unique(labels, return_counts=True)
    price_ranges = [(int(numpy_prices[labels == label].min()), int(
        numpy_prices[labels == label].max())) for label in unique_labels]
    labels = [f'{currency_symbol}{price_min}-{price_max}' for price_min,
              price_max in price_ranges]
    plt.figure(figsize=(12, 9), facecolor='black')
    plt.pie(counts, autopct='%1.1f%%', startangle=140, textprops={
            'color': 'black', 'fontsize': 16}, wedgeprops={'edgecolor': 'black'})
    plt.title(f'Price Distribution (in {currency})', color='white', size=22)
    plt.legend(labels, loc='upper right', bbox_to_anchor=(
        1.2, 1), fontsize='x-large', labelcolor='white')
    plt.tight_layout()
    plt.savefig(output_path)


def run_scraper(product_name, currency_code, remove_symbol, pages):
    global remove_currency_from_csv, currency, currency_symbol, api_url_for_currencies
    search_field = product_name.lower().replace(" ", "_")
    if not search_field:
        return "Enter a product name.", None, None

    currency = currency_code.lower()
    if currency not in symbols_hash_map.values():
        return "Invalid currency.", None, None

    currency_symbol = [k for k, v in symbols_hash_map.items()
                       if v == currency][0]
    remove_currency_from_csv = not remove_symbol
    pages = int(pages) if pages.isdigit() else 3

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    csv_file = f"scraped_{search_field}_{timestamp}.csv"
    graph_file = f"graph_{search_field}_{timestamp}.png"

    urls = [
        f'https://amazon.com/s?k={search_field}&s=exact-aware-popularity-rank',
        f'https://ebay.com/sch/i.html?_nkw={search_field}'
    ]

    all_data = []
    api_url_for_currencies = requests.get(
        f'https://cdn.jsdelivr.net/npm/@fawazahmed0/currency-api@latest/v1/currencies/{currency}.json').json()
    for url in urls:
        all_data.extend(scrape_website(url, headers=headers, pages=pages))

    save_to_csv(all_data, csv_file)
    pie_graph(all_data, graph_file)

    return f"Done! Files saved in output directory: {csv_file}, {graph_file}", f"/usr/src/app/output/{csv_file}", f"/usr/src/app/output/{graph_file}"


with gr.Blocks(title="Web Scraper") as demo:
    gr.Markdown("# Web Scraper\nScrape product data from Amazon and eBay.")
    with gr.Row():
        product_input = gr.Textbox(
            label="Product Name", placeholder="e.g., laptop")
        currency_input = gr.Dropdown(choices=list(
            symbols_hash_map.values()), label="Currency", value="usd")
        symbol_checkbox = gr.Checkbox(
            label="Keep Currency Symbol", value=False)
        pages_input = gr.Textbox(label="Pages", value="3")
    submit_btn = gr.Button("Scrape")
    output_text = gr.Textbox(label="Status")
    output_csv = gr.File(label="Download CSV")
    output_graph = gr.Image(label="Price Graph")

    submit_btn.click(run_scraper, [product_input, currency_input, symbol_checkbox, pages_input], [
                     output_text, output_csv, output_graph])

demo.launch()
