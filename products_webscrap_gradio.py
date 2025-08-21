import sys
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

# Existing setup code remains unchanged
remove_currency_from_csv = True
locale.setlocale(locale.LC_ALL, '')
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
api_all_currencies = requests.get('https://cdn.jsdelivr.net/npm/@fawazahmed0/currency-api@latest/v1/currencies.json').json()
headers = {'User-Agent': 'Mozilla/5.0 (X11; Ubuntu; Linux x86_64; rv:91.0) Gecko/20100101 Firefox/91.0'}
symbols_hash_map = {
    '$': 'usd', '€': 'eur', '£': 'gbp', '¥': 'jpy', '₩': 'krw',
    '₹': 'inr', '₽': 'rub', '₱': 'php', 'R$': 'brl', '₿': 'btc'
}

# Existing functions (convert_price, parse_amazon, parse_ebay, etc.) remain unchanged
# I'll only show the modified/new parts below for brevity

def convert_price(price_data: str, source_url: str) -> str:
    try:
        price_data = price_data.replace(u'\xa0', ' ').strip()
        original_symbol = ''.join(c for c in price_data.split()[0] if not c.isdigit() and c not in ('.', ',')).strip()
        if not original_symbol:
            original_symbol = '$'
        original_currency = symbols_hash_map.get(original_symbol, 'usd')
        if 'to' in price_data.lower():
            price_parts = price_data.split('to')[0]
        else:
            price_parts = price_data
        numeric_part = ''.join(c for c in price_parts if c.isdigit() or c == '.')
        amount = float(numeric_part) if numeric_part else 0.0
        converted_amount = amount / api_url_for_currencies[currency][original_currency]
        return f'{converted_amount:.2f}' if remove_currency_from_csv else f'{currency_symbol} {converted_amount:.2f}'
    except Exception as e:
        logging.warning(f"Price conversion failed for '{price_data}': {e}")
        return '0.00'

def parse_amazon(target_url) -> list[dict]:
    data = []
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
                        'Link': f'https://amazon.com{item.query_selector('h2.a-size-mini > a').get_attribute('href')}'
                    }
                    data.append(item_data)
            browser.close()
        except AttributeError as e:
            logging.warning(f"Skipping item due to missing data: {e}")
    return data

def parse_ebay(soup: BeautifulSoup) -> list[dict]:
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

def fetch_html(url: str, headers: dict = None) -> str | None:
    try:
        response = requests.get(url)
        response.raise_for_status()
        return response.text
    except requests.RequestException as e:
        logging.error(f"Error fetching {url}: {e}")
        return None

def parse_html(html: str, target_url: str) -> list[dict]:
    soup = BeautifulSoup(html, 'html.parser')
    if 'ebay' in target_url:
        return parse_ebay(soup)
    else:
        logging.warning(f"No parsing logic for {target_url}")
        return []

def scrape_website(target_url: str, headers: dict = None, pages: int = 1, sleep_time: int = 1) -> list:
    all_data = []
    for page in range(1, pages + 1):
        url = f"{target_url}&page={page}"
        logging.info(f"Scraping {url}")
        if url.startswith('https://amazon'):
            all_data.extend(parse_amazon(url))
        else:
            html = fetch_html(url, headers)
            if html:
                data = parse_html(html, target_url)
                all_data.extend(data)
                logging.info(f"Page {page} scraped successfully, {len(data)} items found.")
        time.sleep(sleep_time)
    return all_data

def save_to_csv(data: list[dict], filename: str = 'output.csv'):
    if not data:
        logging.warning("No data to save.")
        return
    keys = data[0].keys()
    with open(filename, mode='w', newline='', encoding='utf-8') as file:
        writer = csv.writer(file)
        writer.writerow(keys)
        for row in data:
            writer.writerow(row.values())
    logging.info(f"Data saved to {filename}")

def pie_graph(data: list[dict], filename: str):
    if not data:
        logging.warning("No data to create a pie graph.")
        return
    logging.info("Making a pie graph from the data scraped...")
    names = []
    prices = []
    for item in data:
        if ',' in item['Price']:
            for value in item['Price'].replace(currency_symbol, '').split(', '):
                names.append(item['Name'])
                prices.append(float(value))
        else:
            names.append(item['Name'])
            prices.append(float(item['Price'].replace(currency_symbol, '')))
    numpy_prices = np.array(prices).reshape(-1, 1)
    kmeans = KMeans(n_clusters=5, random_state=0).fit(numpy_prices)
    labels = kmeans.predict(numpy_prices)
    unique_labels, counts = np.unique(labels, return_counts=True)
    price_ranges = [(int(numpy_prices[labels == label].min()), int(numpy_prices[labels == label].max())) for label in unique_labels]
    labels = [f'Around {currency_symbol}{price_min}-{price_max}' for price_min, price_max in price_ranges]
    plt.figure(figsize=(12, 9), facecolor='black')
    plt.pie(counts, labels=None, autopct='%1.1f%%', startangle=140, textprops={'color': 'black', 'fontsize': 16}, wedgeprops={'edgecolor': 'black'})
    plt.title(f'Distribution of prices (in {currency}) for {search_field} (using K-Means)', color='white', size=22)
    plt.legend(bbox_to_anchor=(1.2, 1), labels=labels, loc='upper right', fontsize='x-large', labelcolor='white', frameon=True, edgecolor='white', facecolor='none')
    plt.tight_layout()
    plt.savefig(filename)
    logging.info(f"Pie graph saved as {filename}")

# New Gradio wrapper function
def run_scraper(product_name, currency_code, remove_symbol, pages):
    global remove_currency_from_csv, currency, currency_symbol, search_field, api_url_for_currencies
    search_field = product_name.lower()
    if not search_field:
        return "Please enter a product name.", None, None

    currency = currency_code.lower()
    if currency not in symbols_hash_map.values():
        supported = "\n".join(f'{k} ({v})' for k, v in api_all_currencies.items() if k in symbols_hash_map.values())
        return f"Invalid currency code. Supported currencies:\n{supported}", None, None

    currency_symbol = [k for k, v in symbols_hash_map.items() if v == currency][0]
    remove_currency_from_csv = not remove_symbol  # Checkbox: True means keep symbol, so invert for remove_currency_from_csv
    pages = int(pages) if pages.isdigit() else 3

    urls_to_scrape = [
        f'https://amazon.com/s?k={search_field}&s=exact-aware-popularity-rank',
        f'https://ebay.com/sch/i.html?_nkw={search_field}'
    ]

    all_scraped_data = []
    api_url_for_currencies = requests.get(f'https://cdn.jsdelivr.net/npm/@fawazahmed0/currency-api@latest/v1/currencies/{currency}.json').json()
    for url in urls_to_scrape:
        scraped_data = scrape_website(url, headers=headers, pages=pages)
        all_scraped_data.extend(scraped_data)

    csv_file = "scraped_data.csv"
    graph_file = "scraped_data_graph.png"
    save_to_csv(all_scraped_data, csv_file)
    pie_graph(all_scraped_data, graph_file)

    return "Scraping completed successfully!", csv_file, graph_file

# Gradio Interface
with gr.Blocks(title="Web Scraper") as demo:
    gr.Markdown("# Web Scraper\nEnter details to scrape product data from Amazon and eBay.")
    with gr.Row():
        product_input = gr.Textbox(label="Product Name", placeholder="e.g., computer")
        currency_input = gr.Dropdown(
            choices=list(symbols_hash_map.values()), label="Currency Code", value="usd"
        )
        symbol_checkbox = gr.Checkbox(label="Keep Currency Symbol", value=False)
        pages_input = gr.Textbox(label="Number of Pages", value="3", placeholder="e.g., 3")
    submit_btn = gr.Button("Scrape")
    output_text = gr.Textbox(label="Status")
    output_csv = gr.File(label="Download CSV")
    output_graph = gr.Image(label="Price Distribution Graph")

    submit_btn.click(
        fn=run_scraper,
        inputs=[product_input, currency_input, symbol_checkbox, pages_input],
        outputs=[output_text, output_csv, output_graph]
    )

demo.launch(share=True)