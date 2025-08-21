import os
import csv
import time
import locale
import logging
import requests
import numpy as np
from bs4 import BeautifulSoup
from fastapi import FastAPI, HTTPException, Depends
from fastapi.responses import FileResponse
from pydantic import BaseModel
from typing import List, Dict
from playwright.async_api import async_playwright, Playwright, Browser, BrowserContext, Page
from sklearn.cluster import KMeans
import matplotlib.pyplot as plt

# Setup logging
logging.basicConfig(level=logging.INFO,
                    format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# FastAPI app
app = FastAPI(title="Ecommerce Scraper API")

# Pydantic model for request


class ScrapeRequest(BaseModel):
    search_field: str
    currency: str = "usd"
    pages_to_scrape: int = 3
    remove_currency_from_csv: bool = True

# Pydantic model for response


class ScrapeResponse(BaseModel):
    message: str
    records: int
    csv_file: str
    graph_file: str


# Global configuration
locale.setlocale(locale.LC_ALL, '')
headers = {
    'User-Agent': 'Mozilla/5.0 (X11; Ubuntu; Linux x86_64; rv:91.0) Gecko/20100101 Firefox/91.0'
}
symbols_hash_map = {
    '$': 'usd', '€': 'eur', '£': 'gbp', '¥': 'jpy', '₩': 'krw',
    '₹': 'inr', '₽': 'rub', '₱': 'php', 'R$': 'brl', '₿': 'btc'
}
api_all_currencies = requests.get(
    'https://cdn.jsdelivr.net/npm/@fawazahmed0/currency-api@latest/v1/currencies.json').json()

# Dependency to manage Playwright async browser


async def get_browser_context() -> tuple[Browser, BrowserContext, Page]:
    playwright = await async_playwright().start()
    browser = await playwright.chromium.launch(headless=True)
    context = await browser.new_context(
        user_agent=headers['User-Agent'],
        locale='en-US',
        viewport={'width': 1366, 'height': 768}
    )
    page = await context.new_page()
    try:
        yield browser, context, page
    finally:
        await context.close()
        await browser.close()
        await playwright.stop()


def convert_price(price_data: str, source_url: str, currency: str, currency_symbol: str, remove_currency: bool) -> str:
    try:
        price_data = price_data.replace(u'\xa0', ' ').strip()
        original_symbol = ''.join(c for c in price_data.split(
        )[0] if not c.isdigit() and c not in ('.', ',')).strip() or '$'
        original_currency = symbols_hash_map.get(original_symbol, 'usd')
        if 'to' in price_data.lower():
            price_parts = price_data.split('to')[0]
        else:
            price_parts = price_data
        numeric_part = ''.join(
            c for c in price_parts if c.isdigit() or c == '.')
        amount = float(numeric_part) if numeric_part else 0.0
        api_url_for_currencies = requests.get(
            f'https://cdn.jsdelivr.net/npm/@fawazahmed0/currency-api@latest/v1/currencies/{currency}.json').json()
        converted_amount = amount / \
            api_url_for_currencies[currency][original_currency]
        return f'{converted_amount:.2f}' if remove_currency else f'{currency_symbol} {converted_amount:.2f}'
    except Exception as e:
        logger.warning(f"Price conversion failed for '{price_data}': {e}")
        return '0.00'


async def parse_amazon(page: Page, target_url: str, currency: str, currency_symbol: str, remove_currency: bool) -> List[Dict]:
    data = []
    try:
        await page.goto(target_url, wait_until="domcontentloaded", timeout=30000)
        await page.wait_for_selector('div.a-section.a-spacing-small', timeout=10000)
        items = await page.query_selector_all('div.a-section.a-spacing-small')
        for item in items:
            title_elem = await item.query_selector('h2.a-size-mini > a > span')
            if title_elem:
                price_elem = await item.query_selector('span.a-price > span.a-offscreen')
                link_elem = await item.query_selector('h2.a-size-mini > a')
                item_data = {
                    'Name': await title_elem.inner_text() if title_elem else 'N/A',
                    'Price': convert_price(
                        await price_elem.inner_text() if price_elem else '0.00',
                        'amazon', currency, currency_symbol, remove_currency
                    ),
                    'Link': f'https://amazon.com{await link_elem.get_attribute("href")}' if link_elem else 'N/A'
                }
                data.append(item_data)
    except Exception as e:
        logger.warning(f"Error parsing Amazon page {target_url}: {e}")
    return data


def parse_ebay(soup: BeautifulSoup, currency: str, currency_symbol: str, remove_currency: bool) -> List[Dict]:
    data = []
    items = soup.find_all('li', class_='s-item s-item__pl-on-bottom')
    for item in items:
        if item.find('div', class_='s-item__title').text.strip() != 'Shop on eBay':
            try:
                item_data = {
                    'Name': item.find('div', class_='s-item__title').text.strip(),
                    'Price': convert_price(
                        item.find('span', class_='s-item__price').text.strip(),
                        'ebay', currency, currency_symbol, remove_currency
                    ),
                    'Link': item.find('a', href=True)['href']
                }
                data.append(item_data)
            except AttributeError as e:
                logger.warning(f"Skipping item due to missing data: {e}")
    return data


def parse_html(html: str, target_url: str, currency: str, currency_symbol: str, remove_currency: bool) -> List[Dict]:
    soup = BeautifulSoup(html, 'html.parser')
    if 'ebay' in target_url:
        return parse_ebay(soup, currency, currency_symbol, remove_currency)
    logger.warning(f"No parsing logic for {target_url}")
    return []


def fetch_html(url: str, headers: dict = None) -> str | None:
    try:
        response = requests.get(url, headers=headers)
        response.raise_for_status()
        return response.text
    except requests.RequestException as e:
        logger.error(f"Error fetching {url}: {e}")
        return None


async def scrape_website(target_url: str, headers: dict, pages: int, currency: str, currency_symbol: str, remove_currency: bool, sleep_time: int = 1) -> List:
    all_data = []
    for page_num in range(1, pages + 1):
        url = f"{target_url}&page={page_num}"
        logger.info(f"Scraping {url}")
        if url.startswith('https://amazon'):
            async with async_playwright() as pw:
                browser = await pw.chromium.launch(headless=True)
                context = await browser.new_context(user_agent=headers['User-Agent'])
                page = await context.new_page()
                data = await parse_amazon(page, url, currency, currency_symbol, remove_currency)
                all_data.extend(data)
                await context.close()
                await browser.close()
        else:
            html = fetch_html(url, headers)
            if html:
                data = parse_html(html, target_url, currency,
                                  currency_symbol, remove_currency)
                all_data.extend(data)
                logger.info(
                    f"Page {page_num} scraped successfully, {len(data)} items found.")
        time.sleep(sleep_time)  # Keep sync sleep for simplicity
    return all_data


def save_to_csv(data: List[Dict], filename: str = 'output.csv') -> None:
    if not data:
        logger.warning("No data to save.")
        return
    os.makedirs(os.path.dirname(filename) or '.', exist_ok=True)
    keys = data[0].keys() if data and isinstance(data[0], dict) else []
    try:
        with open(filename, mode='w', newline='', encoding='utf-8') as file:
            writer = csv.DictWriter(file, fieldnames=keys)
            writer.writeheader()
            for row in data:
                writer.writerow(row)
        logger.info(f"Data saved to {filename}")
    except Exception as e:
        logger.error(f"Failed to save CSV: {e}")
        raise


def pie_graph(data: List[Dict], filename: str, currency: str, currency_symbol: str, search_field: str) -> None:
    if not data:
        logger.warning("No data to create a pie graph.")
        return
    logger.info("Making a pie graph from the data scraped...")
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
    price_ranges = [
        (int(numpy_prices[labels == label].min()),
         int(numpy_prices[labels == label].max()))
        for label in unique_labels
    ]
    labels = [
        f'Around {currency_symbol}{price_min}-{price_max}' for price_min, price_max in price_ranges]
    plt.figure(figsize=(12, 9), facecolor='black')
    plt.pie(counts, labels=None, autopct='%1.1f%%', startangle=140, textprops={
            'color': 'black', 'fontsize': 16}, wedgeprops={'edgecolor': 'black'})
    plt.title(
        f'Distribution of prices (in {currency}) for {search_field} (using K-Means)', color='white', size=22)
    plt.legend(bbox_to_anchor=(1.2, 1), labels=labels, loc='upper right', fontsize='x-large',
               labelcolor='white', frameon=True, edgecolor='white', facecolor='none')
    plt.tight_layout()
    os.makedirs(os.path.dirname(filename) or '.', exist_ok=True)
    plt.savefig(filename)
    plt.close()
    logger.info(f"Pie graph saved as {filename}")


@app.post("/scrape", response_model=ScrapeResponse)
async def scrape_endpoint(request: ScrapeRequest, browser_context: tuple[Browser, BrowserContext, Page] = Depends(get_browser_context)):
    """Scrape ecommerce websites and generate CSV and pie chart."""
    search_field = request.search_field.lower()
    if not search_field:
        raise HTTPException(
            status_code=400, detail="Search field cannot be empty")

    currency = request.currency.lower()
    if currency not in symbols_hash_map.values():
        supported_currencies = "\n".join(
            f'{k} ({v})' for k, v in api_all_currencies.items() if k in symbols_hash_map.values())
        raise HTTPException(
            status_code=400, detail=f"Unsupported currency: {currency}. Supported currencies:\n{supported_currencies}")

    currency_symbol = [k for k, v in symbols_hash_map.items()
                       if v == currency][0]
    pages_to_scrape = request.pages_to_scrape
    if pages_to_scrape < 1:
        raise HTTPException(
            status_code=400, detail="Pages to scrape must be at least 1")

    # urls_to_scrape = [
    #     f'https://amazon.com/s?k={search_field}&s=exact-aware-popularity-rank',
    #     f'https://ebay.com/sch/i.html?_nkw={search_field}'
    # ]
    urls_to_scrape = [
        f'https://amazon.com/s?k={search_field}&s=exact-aware-popularity-rank'
    ]
    timestamp = time.strftime("%Y%m%d_%H%M%S")
    csv_file = f"/usr/src/app/output/scraped_{search_field}_{timestamp}.csv"
    graph_file = f"/usr/src/app/output/graph_{search_field}_{timestamp}.png"

    try:
        all_scraped_data = []
        api_url_for_currencies = requests.get(
            f'https://cdn.jsdelivr.net/npm/@fawazahmed0/currency-api@latest/v1/currencies/{currency}.json').json()
        for url in urls_to_scrape:
            data = await scrape_website(
                url, headers, pages_to_scrape, currency, currency_symbol, request.remove_currency_from_csv
            )
            all_scraped_data.extend(data)

        if not all_scraped_data:
            raise HTTPException(status_code=404, detail="No data scraped")

        save_to_csv(all_scraped_data, csv_file)
        pie_graph(all_scraped_data, graph_file, currency,
                  currency_symbol, search_field)
        return {
            "message": f"Scraping completed. Data saved to {csv_file}, graph saved to {graph_file}",
            "records": len(all_scraped_data),
            "csv_file": os.path.basename(csv_file),
            "graph_file": os.path.basename(graph_file)
        }
    except Exception as e:
        logger.error(f"Scraping failed: {e}")
        raise HTTPException(
            status_code=500, detail=f"Scraping failed: {str(e)}")


@app.get("/download/csv")
async def download_csv(filename: str):
    """Download a generated CSV file."""
    filepath = f"/usr/src/app/output/{filename}"
    if os.path.exists(filepath):
        return FileResponse(filepath, filename=filename, media_type='text/csv')
    raise HTTPException(status_code=404, detail=f"File {filename} not found")


@app.get("/download/graph")
async def download_graph(filename: str):
    """Download a generated pie chart image."""
    filepath = f"/usr/src/app/output/{filename}"
    if os.path.exists(filepath):
        return FileResponse(filepath, filename=filename, media_type='image/png')
    raise HTTPException(status_code=404, detail=f"File {filename} not found")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)

# import os
# import csv
# import time
# import locale
# import logging
# import requests
# import numpy as np
# from bs4 import BeautifulSoup
# from fastapi import FastAPI, HTTPException, Depends
# from fastapi.responses import FileResponse
# from pydantic import BaseModel
# from typing import List, Dict
# from playwright.sync_api import sync_playwright, Playwright, Browser, BrowserContext, Page
# from sklearn.cluster import KMeans
# import matplotlib.pyplot as plt

# # Setup logging
# logging.basicConfig(level=logging.INFO,
#                     format='%(asctime)s - %(levelname)s - %(message)s')
# logger = logging.getLogger(__name__)

# # FastAPI app
# app = FastAPI(title="Ecommerce Scraper API")

# # Pydantic model for request


# class ScrapeRequest(BaseModel):
#     search_field: str
#     currency: str = "usd"
#     pages_to_scrape: int = 3
#     remove_currency_from_csv: bool = True

# # Pydantic model for response


# class ScrapeResponse(BaseModel):
#     message: str
#     records: int
#     csv_file: str
#     graph_file: str


# # Global configuration
# locale.setlocale(locale.LC_ALL, '')
# headers = {
#     'User-Agent': 'Mozilla/5.0 (X11; Ubuntu; Linux x86_64; rv:91.0) Gecko/20100101 Firefox/91.0'
# }
# symbols_hash_map = {
#     '$': 'usd', '€': 'eur', '£': 'gbp', '¥': 'jpy', '₩': 'krw',
#     '₹': 'inr', '₽': 'rub', '₱': 'php', 'R$': 'brl', '₿': 'btc'
# }
# api_all_currencies = requests.get(
#     'https://cdn.jsdelivr.net/npm/@fawazahmed0/currency-api@latest/v1/currencies.json').json()

# # Dependency to manage Playwright browser


# def get_browser_context() -> tuple[Browser, BrowserContext, Page]:
#     playwright = sync_playwright().start()
#     browser = playwright.chromium.launch(headless=True)
#     context = browser.new_context(
#         user_agent=headers['User-Agent'],
#         locale='en-US',
#         viewport={'width': 1366, 'height': 768}
#     )
#     page = context.new_page()
#     try:
#         yield browser, context, page
#     finally:
#         context.close()
#         browser.close()
#         playwright.stop()


# def convert_price(price_data: str, source_url: str, currency: str, currency_symbol: str, remove_currency: bool) -> str:
#     try:
#         price_data = price_data.replace(u'\xa0', ' ').strip()
#         original_symbol = ''.join(c for c in price_data.split(
#         )[0] if not c.isdigit() and c not in ('.', ',')).strip() or '$'
#         original_currency = symbols_hash_map.get(original_symbol, 'usd')
#         if 'to' in price_data.lower():
#             price_parts = price_data.split('to')[0]
#         else:
#             price_parts = price_data
#         numeric_part = ''.join(
#             c for c in price_parts if c.isdigit() or c == '.')
#         amount = float(numeric_part) if numeric_part else 0.0
#         api_url_for_currencies = requests.get(
#             f'https://cdn.jsdelivr.net/npm/@fawazahmed0/currency-api@latest/v1/currencies/{currency}.json').json()
#         converted_amount = amount / \
#             api_url_for_currencies[currency][original_currency]
#         return f'{converted_amount:.2f}' if remove_currency else f'{currency_symbol} {converted_amount:.2f}'
#     except Exception as e:
#         logger.warning(f"Price conversion failed for '{price_data}': {e}")
#         return '0.00'


# def parse_amazon(page: Page, target_url: str, currency: str, currency_symbol: str, remove_currency: bool) -> List[Dict]:
#     data = []
#     page.goto(target_url)
#     try:
#         items = page.query_selector_all('div.a-section.a-spacing-small')
#         for item in items:
#             if item.query_selector('h2.a-size-mini > a > span'):
#                 item_data = {
#                     'Name': item.query_selector('h2.a-size-mini > a > span').inner_text(),
#                     'Price': convert_price(
#                         item.query_selector(
#                             'span.a-price > span.a-offscreen').inner_text(),
#                         'amazon', currency, currency_symbol, remove_currency
#                     ),
#                     'Link': f'https://amazon.com{item.query_selector('h2.a-size-mini > a').get_attribute('href')}'
#                 }
#                 data.append(item_data)
#     except AttributeError as e:
#         logger.warning(f"Skipping item due to missing data: {e}")
#     return data


# def parse_ebay(soup: BeautifulSoup, currency: str, currency_symbol: str, remove_currency: bool) -> List[Dict]:
#     data = []
#     items = soup.find_all('li', class_='s-item s-item__pl-on-bottom')
#     for item in items:
#         if item.find('div', class_='s-item__title').text.strip() != 'Shop on eBay':
#             try:
#                 item_data = {
#                     'Name': item.find('div', class_='s-item__title').text.strip(),
#                     'Price': convert_price(
#                         item.find('span', class_='s-item__price').text.strip(),
#                         'ebay', currency, currency_symbol, remove_currency
#                     ),
#                     'Link': item.find('a', href=True)['href']
#                 }
#                 data.append(item_data)
#             except AttributeError as e:
#                 logger.warning(f"Skipping item due to missing data: {e}")
#     return data


# def parse_html(html: str, target_url: str, currency: str, currency_symbol: str, remove_currency: bool) -> List[Dict]:
#     soup = BeautifulSoup(html, 'html.parser')
#     if 'ebay' in target_url:
#         return parse_ebay(soup, currency, currency_symbol, remove_currency)
#     logger.warning(f"No parsing logic for {target_url}")
#     return []


# def fetch_html(url: str, headers: dict = None) -> str | None:
#     try:
#         response = requests.get(url, headers=headers)
#         response.raise_for_status()
#         return response.text
#     except requests.RequestException as e:
#         logger.error(f"Error fetching {url}: {e}")
#         return None


# def scrape_website(target_url: str, headers: dict, pages: int, currency: str, currency_symbol: str, remove_currency: bool, sleep_time: int = 1) -> List:
#     all_data = []
#     for page in range(1, pages + 1):
#         url = f"{target_url}&page={page}"
#         logger.info(f"Scraping {url}")
#         if url.startswith('https://amazon'):
#             with sync_playwright() as pw:
#                 browser = pw.chromium.launch(headless=True)
#                 context = browser.new_context(user_agent=headers['User-Agent'])
#                 page_obj = context.new_page()
#                 data = parse_amazon(page_obj, url, currency,
#                                     currency_symbol, remove_currency)
#                 all_data.extend(data)
#                 context.close()
#                 browser.close()
#         else:
#             html = fetch_html(url, headers)
#             if html:
#                 data = parse_html(html, target_url, currency,
#                                   currency_symbol, remove_currency)
#                 all_data.extend(data)
#                 logger.info(
#                     f"Page {page} scraped successfully, {len(data)} items found.")
#         time.sleep(sleep_time)
#     return all_data


# def save_to_csv(data: List[Dict], filename: str = 'output.csv') -> None:
#     if not data:
#         logger.warning("No data to save.")
#         return
#     os.makedirs(os.path.dirname(filename) or '.', exist_ok=True)
#     keys = data[0].keys() if data and isinstance(data[0], dict) else []
#     try:
#         with open(filename, mode='w', newline='', encoding='utf-8') as file:
#             writer = csv.DictWriter(file, fieldnames=keys)
#             writer.writeheader()
#             for row in data:
#                 writer.writerow(row)
#         logger.info(f"Data saved to {filename}")
#     except Exception as e:
#         logger.error(f"Failed to save CSV: {e}")
#         raise


# def pie_graph(data: List[Dict], filename: str, currency: str, currency_symbol: str, search_field: str) -> None:
#     if not data:
#         logger.warning("No data to create a pie graph.")
#         return
#     logger.info("Making a pie graph from the data scraped...")
#     names = []
#     prices = []
#     for item in data:
#         if ',' in item['Price']:
#             for value in item['Price'].replace(currency_symbol, '').split(', '):
#                 names.append(item['Name'])
#                 prices.append(float(value))
#         else:
#             names.append(item['Name'])
#             prices.append(float(item['Price'].replace(currency_symbol, '')))
#     numpy_prices = np.array(prices).reshape(-1, 1)
#     kmeans = KMeans(n_clusters=5, random_state=0).fit(numpy_prices)
#     labels = kmeans.predict(numpy_prices)
#     unique_labels, counts = np.unique(labels, return_counts=True)
#     price_ranges = [
#         (int(numpy_prices[labels == label].min()),
#          int(numpy_prices[labels == label].max()))
#         for label in unique_labels
#     ]
#     labels = [
#         f'Around {currency_symbol}{price_min}-{price_max}' for price_min, price_max in price_ranges]
#     plt.figure(figsize=(12, 9), facecolor='black')
#     plt.pie(counts, labels=None, autopct='%1.1f%%', startangle=140, textprops={
#             'color': 'black', 'fontsize': 16}, wedgeprops={'edgecolor': 'black'})
#     plt.title(
#         f'Distribution of prices (in {currency}) for {search_field} (using K-Means)', color='white', size=22)
#     plt.legend(bbox_to_anchor=(1.2, 1), labels=labels, loc='upper right', fontsize='x-large',
#                labelcolor='white', frameon=True, edgecolor='white', facecolor='none')
#     plt.tight_layout()
#     os.makedirs(os.path.dirname(filename) or '.', exist_ok=True)
#     plt.savefig(filename)
#     plt.close()
#     logger.info(f"Pie graph saved as {filename}")


# @app.post("/scrape", response_model=ScrapeResponse)
# async def scrape_endpoint(request: ScrapeRequest, browser_context: tuple[Browser, BrowserContext, Page] = Depends(get_browser_context)):
#     """Scrape ecommerce websites and generate CSV and pie chart."""
#     search_field = request.search_field.lower()
#     if not search_field:
#         raise HTTPException(
#             status_code=400, detail="Search field cannot be empty")

#     currency = request.currency.lower()
#     if currency not in symbols_hash_map.values():
#         supported_currencies = "\n".join(
#             f'{k} ({v})' for k, v in api_all_currencies.items() if k in symbols_hash_map.values())
#         raise HTTPException(
#             status_code=400, detail=f"Unsupported currency: {currency}. Supported currencies:\n{supported_currencies}")

#     currency_symbol = [k for k, v in symbols_hash_map.items()
#                        if v == currency][0]
#     pages_to_scrape = request.pages_to_scrape
#     if pages_to_scrape < 1:
#         raise HTTPException(
#             status_code=400, detail="Pages to scrape must be at least 1")

#     urls_to_scrape = [
#         f'https://amazon.com/s?k={search_field}&s=exact-aware-popularity-rank',
#         f'https://ebay.com/sch/i.html?_nkw={search_field}'
#     ]
#     timestamp = time.strftime("%Y%m%d_%H%M%S")
#     csv_file = f"/usr/src/app/output/scraped_{search_field}_{timestamp}.csv"
#     graph_file = f"/usr/src/app/output/graph_{search_field}_{timestamp}.png"

#     try:
#         all_scraped_data = []
#         api_url_for_currencies = requests.get(
#             f'https://cdn.jsdelivr.net/npm/@fawazahmed0/currency-api@latest/v1/currencies/{currency}.json').json()
#         for url in urls_to_scrape:
#             data = scrape_website(
#                 url, headers, pages_to_scrape, currency, currency_symbol, request.remove_currency_from_csv
#             )
#             all_scraped_data.extend(data)

#         if not all_scraped_data:
#             raise HTTPException(status_code=404, detail="No data scraped")

#         save_to_csv(all_scraped_data, csv_file)
#         pie_graph(all_scraped_data, graph_file, currency,
#                   currency_symbol, search_field)
#         return {
#             "message": f"Scraping completed. Data saved to {csv_file}, graph saved to {graph_file}",
#             "records": len(all_scraped_data),
#             "csv_file": csv_file,
#             "graph_file": graph_file
#         }
#     except Exception as e:
#         logger.error(f"Scraping failed: {e}")
#         raise HTTPException(
#             status_code=500, detail=f"Scraping failed: {str(e)}")


# @app.get("/download/csv")
# async def download_csv(filename: str):
#     """Download a generated CSV file."""
#     filepath = f"/usr/src/app/output/{filename}"
#     if os.path.exists(filepath):
#         return FileResponse(filepath, filename=filename, media_type='text/csv')
#     raise HTTPException(status_code=404, detail=f"File {filename} not found")


# @app.get("/download/graph")
# async def download_graph(filename: str):
#     """Download a generated pie chart image."""
#     filepath = f"/usr/src/app/output/{filename}"
#     if os.path.exists(filepath):
#         return FileResponse(filepath, filename=filename, media_type='image/png')
#     raise HTTPException(status_code=404, detail=f"File {filename} not found")

# if __name__ == "__main__":
#     import uvicorn
#     uvicorn.run(app, host="0.0.0.0", port=8000)

# # import csv
# # import time
# # import locale
# # import logging
# # import requests
# # import numpy as np
# # from bs4 import BeautifulSoup
# # from playwright.async_api import async_playwright
# # from sklearn.cluster import KMeans
# # import matplotlib.pyplot as plt
# # from datetime import datetime
# # import os
# # from fastapi import FastAPI, Form, Request
# # from fastapi.responses import HTMLResponse, FileResponse
# # from fastapi.staticfiles import StaticFiles
# # from fastapi.templating import Jinja2Templates
# # import asyncio

# # app = FastAPI()
# # app.mount("/static", StaticFiles(directory="static"), name="static")
# # app.mount("/output", StaticFiles(directory="output"), name="output")
# # templates = Jinja2Templates(directory="templates")

# # remove_currency_from_csv = True
# # locale.setlocale(locale.LC_ALL, '')
# # logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
# # api_all_currencies = requests.get('https://cdn.jsdelivr.net/npm/@fawazahmed0/currency-api@latest/v1/currencies.json').json()
# # headers = {'User-Agent': 'Mozilla/5.0 (X11; Ubuntu; Linux x86_64; rv:91.0) Gecko/20100101 Firefox/91.0'}
# # symbols_hash_map = {
# #     '$': 'usd', '€': 'eur', '£': 'gbp', '¥': 'jpy', '₩': 'krw',
# #     '₹': 'inr', '₽': 'rub', '₱': 'php', 'R$': 'brl', '₿': 'btc'
# # }

# # def convert_price(price_data: str, source_url: str) -> str:
# #     try:
# #         price_data = price_data.replace(u'\xa0', ' ').strip()
# #         original_symbol = ''.join(c for c in price_data.split()[0] if not c.isdigit() and c not in ('.', ',')).strip() or '$'
# #         original_currency = symbols_hash_map.get(original_symbol, 'usd')
# #         numeric_part = ''.join(c for c in price_data.split('to')[0] if c.isdigit() or c == '.')
# #         amount = float(numeric_part) if numeric_part else 0.0
# #         converted_amount = amount / api_url_for_currencies[currency][original_currency]
# #         return f'{converted_amount:.2f}' if remove_currency_from_csv else f'{currency_symbol} {converted_amount:.2f}'
# #     except Exception as e:
# #         logging.warning(f"Price conversion failed for '{price_data}': {e}")
# #         return '0.00'

# # async def parse_amazon(target_url):
# #     data = []
# #     async with async_playwright() as pw:
# #         browser = await pw.chromium.launch(headless=True)
# #         page = await browser.new_page()
# #         await page.goto(target_url)
# #         try:
# #             items = await page.query_selector_all('div.a-section.a-spacing-small')
# #             for item in items:
# #                 if await item.query_selector('h2.a-size-mini > a > span'):
# #                     href = await (await item.query_selector('h2.a-size-mini > a')).get_attribute('href')
# #                     price_elem = await item.query_selector('span.a-price > span.a-offscreen')
# #                     price_text = await price_elem.inner_text() if price_elem else '0.00'
# #                     item_data = {
# #                         'Name': await (await item.query_selector('h2.a-size-mini > a > span')).inner_text(),
# #                         'Price': convert_price(price_text, 'amazon'),
# #                         'Link': f'https://amazon.com{href}'
# #                     }
# #                     data.append(item_data)
# #             await browser.close()
# #         except AttributeError as e:
# #             logging.warning(f"Skipping item due to missing data: {e}")
# #     return data

# # def parse_ebay(soup: BeautifulSoup):
# #     data = []
# #     items = soup.find_all('li', class_='s-item s-item__pl-on-bottom')
# #     for item in items:
# #         if item.find('div', class_='s-item__title').text.strip() != 'Shop on eBay':
# #             try:
# #                 item_data = {
# #                     'Name': item.find('div', class_='s-item__title').text.strip(),
# #                     'Price': convert_price(item.find('span', class_='s-item__price').text.strip(), 'ebay'),
# #                     'Link': item.find('a', href=True)['href']
# #                 }
# #                 data.append(item_data)
# #             except AttributeError as e:
# #                 logging.warning(f"Skipping item due to missing data: {e}")
# #     return data

# # def fetch_html(url: str, headers: dict = None):
# #     try:
# #         response = requests.get(url)
# #         response.raise_for_status()
# #         return response.text
# #     except requests.RequestException as e:
# #         logging.error(f"Error fetching {url}: {e}")
# #         return None

# # def parse_html(html: str, target_url: str):
# #     soup = BeautifulSoup(html, 'html.parser')
# #     if 'ebay' in target_url:
# #         return parse_ebay(soup)
# #     return []

# # async def scrape_website(target_url: str, headers: dict = None, pages: int = 1, sleep_time: int = 1):
# #     all_data = []
# #     for page in range(1, pages + 1):
# #         url = f"{target_url}&page={page}"
# #         logging.info(f"Scraping {url}")
# #         if 'amazon' in url:
# #             all_data.extend(await parse_amazon(url))
# #         else:
# #             html = fetch_html(url, headers)
# #             if html:
# #                 all_data.extend(parse_html(html, url))
# #         await asyncio.sleep(sleep_time)
# #     return all_data

# # def save_to_csv(data: list[dict], filename: str):
# #     if not data:
# #         return None
# #     output_dir = 'output'
# #     os.makedirs(output_dir, exist_ok=True)
# #     output_path = os.path.join(output_dir, filename)
# #     keys = data[0].keys()
# #     with open(output_path, mode='w', newline='', encoding='utf-8') as file:
# #         writer = csv.writer(file)
# #         writer.writerow(keys)
# #         for row in data:
# #             writer.writerow(row.values())
# #     return output_path

# # def pie_graph(data: list[dict], filename: str):
# #     if not data:
# #         return None
# #     output_dir = 'output'
# #     os.makedirs(output_dir, exist_ok=True)
# #     output_path = os.path.join(output_dir, filename)
# #     prices = [float(item['Price'].replace(currency_symbol, '').split(',')[0]) for item in data]
# #     numpy_prices = np.array(prices).reshape(-1, 1)
# #     kmeans = KMeans(n_clusters=5, random_state=0).fit(numpy_prices)
# #     labels = kmeans.predict(numpy_prices)
# #     unique_labels, counts = np.unique(labels, return_counts=True)
# #     price_ranges = [(int(numpy_prices[labels == label].min()), int(numpy_prices[labels == label].max())) for label in unique_labels]
# #     labels = [f'{currency_symbol}{price_min}-{price_max}' for price_min, price_max in price_ranges]
# #     plt.figure(figsize=(12, 9), facecolor='black')
# #     plt.pie(counts, autopct='%1.1f%%', startangle=140, textprops={'color': 'black', 'fontsize': 16}, wedgeprops={'edgecolor': 'black'})
# #     plt.title(f'Price Distribution (in {currency})', color='white', size=22)
# #     plt.legend(labels, loc='upper right', bbox_to_anchor=(1.2, 1), fontsize='x-large', labelcolor='white')
# #     plt.tight_layout()
# #     plt.savefig(output_path)
# #     plt.close()
# #     return output_path

# # async def run_scraper(product_name, currency_code, remove_symbol, pages):
# #     global remove_currency_from_csv, currency, currency_symbol, api_url_for_currencies
# #     search_field = product_name.lower().replace(" ", "_")
# #     if not search_field:
# #         return "Enter a product name.", None, None

# #     currency = currency_code.lower()
# #     if currency not in symbols_hash_map.values():
# #         return "Invalid currency.", None, None

# #     currency_symbol = [k for k, v in symbols_hash_map.items() if v == currency][0]
# #     remove_currency_from_csv = not remove_symbol
# #     pages = int(pages) if pages.isdigit() else 3

# #     timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
# #     csv_file = f"scraped_{search_field}_{timestamp}.csv"
# #     graph_file = f"graph_{search_field}_{timestamp}.png"

# #     urls = [
# #         f'https://amazon.com/s?k={search_field}&s=exact-aware-popularity-rank',
# #         f'https://ebay.com/sch/i.html?_nkw={search_field}'
# #     ]

# #     all_data = []
# #     api_url_for_currencies = requests.get(f'https://cdn.jsdelivr.net/npm/@fawazahmed0/currency-api@latest/v1/currencies/{currency}.json').json()
# #     for url in urls:
# #         all_data.extend(await scrape_website(url, headers=headers, pages=pages))

# #     csv_path = save_to_csv(all_data, csv_file)
# #     graph_path = pie_graph(all_data, graph_file)

# #     return f"Done! Files generated.", csv_file, graph_file

# # @app.get("/", response_class=HTMLResponse)
# # async def index(request: Request):
# #     return templates.TemplateResponse("index.html", {
# #         "request": request,
# #         "currencies": list(symbols_hash_map.values())
# #     })

# # @app.post("/scrape", response_class=HTMLResponse)
# # async def scrape(request: Request,
# #                  product_name: str = Form(...),
# #                  currency: str = Form(...),
# #                  keep_symbol: bool = Form(False),
# #                  pages: str = Form("3")):
# #     status, csv_file, graph_file = await run_scraper(product_name, currency, keep_symbol, pages)
# #     return templates.TemplateResponse("index.html", {
# #         "request": request,
# #         "currencies": list(symbols_hash_map.values()),
# #         "status": status,
# #         "csv_file": csv_file,
# #         "graph_file": graph_file
# #     })

# # @app.get("/download/{filename}")
# # async def download_file(filename: str):
# #     file_path = os.path.join("output", filename)
# #     if os.path.exists(file_path):
# #         return FileResponse(file_path)
# #     return {"error": "File not found"}

# # if __name__ == "__main__":
# #     import uvicorn
# #     uvicorn.run(app, host="0.0.0.0", port=8000
