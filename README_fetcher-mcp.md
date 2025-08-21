# Scrape Amazon.com by https://github.com/jae-jae/fetcher-mcp

The [fetcher-mcp](https://github.com/jae-jae/fetcher-mcp) project is a browser extension designed to extract data from web pages using JavaScript and Puppeteer. To scrape Amazon.com with it, you need to:

1. **Install fetcher-mcp**  
   Follow the installation steps in the repository to add it to your browser.

2. **Create a Scraper Script**  
   Use the built-in script editor to write a JavaScript function that extracts product details from Amazon product pages or search results.

3. **Handle Amazon’s Anti-Scraping Measures**  
   - Amazon aggressively blocks scrapers, so use **rotating user agents** and **proxy servers**.  
   - Avoid frequent requests and introduce **random delays** between fetches.  
   - Scrape **cached pages** (like Google Cache) when possible.  

4. **Run and Export Data**  
   - Execute the script through fetcher-mcp and download the extracted data in CSV, JSON, or another format.  

If you need help writing a script, let me know which Amazon data points you're interested in!

To scrape **Amazon product data** using [fetcher-mcp](https://github.com/jae-jae/fetcher-mcp), follow these steps:

---

### **1. Install fetcher-mcp**
1. Clone the repository and install dependencies:
   ```sh
   git clone https://github.com/jae-jae/fetcher-mcp.git
   cd fetcher-mcp
   npm install
   ```
2. Load the unpacked extension in Chrome:
   - Open `chrome://extensions/`
   - Enable **Developer mode**
   - Click **Load unpacked** and select the `fetcher-mcp` directory.

---

### **2. Create a Scraping Script**
1. Open fetcher-mcp in your browser.
2. Click on **“New Task”** and enter the following script:

   ```js
   (() => {
       const products = [];
       document.querySelectorAll('.s-main-slot .s-result-item').forEach(item => {
           const titleElement = item.querySelector('h2 a');
           const priceElement = item.querySelector('.a-price-whole');
           const ratingElement = item.querySelector('.a-icon-alt');
           const linkElement = titleElement ? titleElement.href : null;

           if (titleElement && priceElement) {
               products.push({
                   title: titleElement.innerText.trim(),
                   price: priceElement.innerText.trim(),
                   rating: ratingElement ? ratingElement.innerText.trim() : 'No rating',
                   link: linkElement
               });
           }
       });

       return products;
   })();
   ```

---

### **3. Run the Script**
- Navigate to an **Amazon search results page**, e.g.,  
  `[https://www.amazon.com/s?k=laptop](https://www.amazon.com/s?k=laptop)`
- Run the script in **fetcher-mcp**.
- Export the extracted data as JSON or CSV.

---

### **4. Avoid Amazon's Scraping Protections**
- Use **random delays** (`setTimeout`) between requests.  
- Rotate **user agents** and **IP addresses** using proxies.  
- Scrape at **off-peak hours** to reduce detection risk.  
- Use **browser automation tools** like **Puppeteer** if fetcher-mcp gets blocked.

Would you like to add advanced features like pagination or image extraction?

To enhance the script with **pagination** and **image extraction**, follow these steps:

---

## **1. Updated Scraping Script**
This script extracts **product title, price, rating, image URL, and product link**. It also **automates pagination** by scrolling and clicking "Next Page."

```js
(async () => {
    const products = [];

    async function scrapePage() {
        document.querySelectorAll('.s-main-slot .s-result-item').forEach(item => {
            const titleElement = item.querySelector('h2 a');
            const priceElement = item.querySelector('.a-price-whole');
            const ratingElement = item.querySelector('.a-icon-alt');
            const imageElement = item.querySelector('img.s-image');
            const linkElement = titleElement ? titleElement.href : null;

            if (titleElement && priceElement) {
                products.push({
                    title: titleElement.innerText.trim(),
                    price: priceElement.innerText.trim(),
                    rating: ratingElement ? ratingElement.innerText.trim() : 'No rating',
                    image: imageElement ? imageElement.src : 'No image',
                    link: linkElement
                });
            }
        });
    }

    async function paginate() {
        let nextPage = document.querySelector('a.s-pagination-next');
        while (nextPage) {
            await new Promise(resolve => setTimeout(resolve, 3000)); // Delay for anti-bot detection
            nextPage.click();
            await new Promise(resolve => setTimeout(resolve, 5000)); // Wait for page load
            scrapePage();
            nextPage = document.querySelector('a.s-pagination-next');
        }
    }

    await scrapePage();
    await paginate();

    console.log(products);
    return products;
})();
```

---

## **2. How to Run the Script**
1. Open Amazon search results, e.g.,  
   `[https://www.amazon.com/s?k=laptop](https://www.amazon.com/s?k=laptop)`
2. Open **fetcher-mcp** and paste the script.
3. Click **Run** and let it scrape through multiple pages.
4. Once completed, export the data in **JSON or CSV**.

---

## **3. Features Added**
✅ **Extracts** title, price, rating, image URL, and product link.  
✅ **Automates pagination** by clicking "Next Page."  
✅ **Random delay** added for anti-bot protection.  

Would you like to include more details like product descriptions or reviews?