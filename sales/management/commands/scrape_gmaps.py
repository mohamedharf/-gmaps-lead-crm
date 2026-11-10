from django.core.management.base import BaseCommand
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from webdriver_manager.chrome import ChromeDriverManager
import time
import random
import re
import logging
from django.core.cache import cache
from selenium_stealth import stealth

from sales.models import Lead, ContactDetails, OutreachStatus

logger = logging.getLogger(__name__)

USER_AGENTS = [
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Edge/120.0.0.0 Safari/537.36',
    'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Safari/605.1.15',
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:121.0) Gecko/20100101 Firefox/121.0',
]

class Command(BaseCommand):
    help = 'Scrape Google Maps for leads in a city'

    def add_arguments(self, parser):
        parser.add_argument('keyword', type=str, help='Search keyword (e.g., "Pizza")')
        parser.add_argument('city', type=str, help='City name (e.g., "Cairo")')
        parser.add_argument('--limit', type=int, default=None, help='Max number of NEW entries to scrape. If 0 or empty, runs indefinitely.')
        parser.add_argument('--dataset_id', type=str, default=None, help='ID of Dataset to save leads into.')

    def db_log(self, msg, style_func=None):
        """Helper to write to stdout and persistent DB log"""
        from sales.models import ScraperLog
        if style_func:
            self.stdout.write(style_func(msg))
        else:
            self.stdout.write(msg)
        ScraperLog.objects.create(message=msg)

    def handle(self, *args, **options):
        keyword = options['keyword']
        city = options['city']
        limit = options['limit']
        dataset_id = options.get('dataset_id')
        if limit == 0:
            limit = None # Logic for infinite

        search_query = f"{keyword} in {city}"
        
        # Initialize Cache Progress
        cache.set('scraper_is_running', True, timeout=86400)
        cache.set('scraper_total_target', limit if limit else 0, timeout=86400)
        cache.set('scraper_saved_count', 0, timeout=86400)

        limit_text = f"Max: {limit} new items" if limit else "Infinite Mode (Until end of results)"
        self.db_log(f"Starting sales for: {search_query} ({limit_text})", self.style.SUCCESS)

        # Setup Chrome Options
        chrome_options = webdriver.ChromeOptions()
        chrome_options.add_argument("--headless") 
        chrome_options.add_argument("--no-sandbox")
        chrome_options.add_argument("--disable-dev-shm-usage")
        chrome_options.add_argument("--disable-gpu")
        chrome_options.add_argument("--window-size=1920,1080")
        
        selected_ua = random.choice(USER_AGENTS)
        chrome_options.add_argument(f"user-agent={selected_ua}")
        self.db_log(f"Using User-Agent: {selected_ua}")
        
        self.db_log("Initializing WebDriver...")
        try:
            service = Service(ChromeDriverManager().install())
            driver = webdriver.Chrome(service=service, options=chrome_options)
            self.db_log("Chrome launched successfully!", self.style.SUCCESS)
        except Exception as e:
            self.db_log(f"FAILED to launch Chrome: {e}", self.style.ERROR)
            return
        
        # Stealth Mode
        stealth(driver,
            languages=["en-US", "en"],
            vendor="Google Inc.",
            platform="Win32",
            webgl_vendor="Intel Inc.",
            renderer="Intel Iris OpenGL Engine",
            fix_hairline=True,
        )
        
        try:
            self.db_log("Navigating to Google Maps...")
            encoded_query = search_query.replace(" ", "+")
            driver.get(f"https://www.google.com/maps/search/{encoded_query}?hl=en")
            
            try:
                consent_button = WebDriverWait(driver, 3).until(
                    EC.element_to_be_clickable((By.XPATH, "//button[contains(., 'Accept all') or contains(., 'I agree')]"))
                )
                consent_button.click()
            except:
                pass
            
            self.db_log("Waiting for results...")
            
            try:
                scrollable_div = WebDriverWait(driver, 10).until(
                    EC.presence_of_element_located((By.CSS_SELECTOR, "div[role='feed']"))
                )
            except:
                self.stdout.write(self.style.WARNING("Could not find feed div, might be a single result or network issue."))
                time.sleep(3)
                scrollable_div = None

            if scrollable_div:
                self.db_log("Found feed. Scouting for items...")
                
                # Sets to track
                scraped_hrefs = set() # Track what we've processed in this session
                saved_count = 0
                
                previous_len = 0
                max_scroll_attempts = 10 
                scroll_attempt = 0
                
                # Infinite Loop condition
                while True:
                    # Break Check: Limit reached
                    if limit and saved_count >= limit:
                        self.stdout.write(self.style.SUCCESS(f"Reached limit of {limit} new entries."))
                        break
                    
                    # STOP SIGNAL CHECK
                    if cache.get('stop_scraping'):
                        self.db_log(self.style.WARNING("Stop signal received. Halting sales."))
                        break

                    # Collect visible items
                    elements = driver.find_elements(By.CSS_SELECTOR, "a[href*='/maps/place/']")
                    visible_hrefs = []
                    
                    for elem in elements:
                        href = elem.get_attribute("href")
                        visible_hrefs.append(href)
                    
                    # Logic: Process NEW items that we haven't seen in this session yet
                    # We process them batch by batch as they appear to avoid huge lists
                    
                    new_in_view = [h for h in visible_hrefs if h not in scraped_hrefs]
                    
                    for href in new_in_view:
                        if limit and saved_count >= limit: break
                        if cache.get('stop_scraping'): break
                        
                        scraped_hrefs.add(href) # Mark as seen
                        
                        # --- SMART DEDUPLICATION ---
                        # Extract ID from URL
                        match = re.search(r'!1s(0x[0-9a-f]+:[0-9a-f]*)', href)
                        gmaps_id = match.group(1) if match else href
                        
                        if Lead.objects.filter(gmaps_id=gmaps_id).exists():
                            # Skip Duplicate WITHOUT visiting
                            # self.stdout.write(f"Skipping known duplicate: {gmaps_id}") 
                            continue
                        
                        # Visit
                        self.stdout.write(f"Scraping new item [{saved_count+1}]: {href}")
                        
                        # Store current handle to switch back
                        # Actually we are in the same tab, so we just 'get(href)' then 'back'?
                        # Using back() is risky in infinite scroll (might reset scroll).
                        # Better to open new tab or just get() and re-find feed?
                        # Re-finding feed is hard. 
                        # Best practice for feeds: Open in new tab.
                        
                        driver.execute_script("window.open('');")
                        driver.switch_to.window(driver.window_handles[1])
                        driver.get(href)
                        
                        # --- SCRAPE DETAILS ---
                        try:
                            try:
                                name_elem = WebDriverWait(driver, 5).until(
                                    EC.presence_of_element_located((By.TAG_NAME, "h1"))
                                )
                                name = name_elem.text
                            except:
                                name = "Unknown"

                            # Extract other fields (Simplified for brevity but robust)
                            rating = 0.0
                            try:
                                star_elem = driver.find_element(By.XPATH, "//*[@role='img' and contains(@aria-label, 'stars')]")
                                match = re.search(r'(\d+(\.\d+)?)', star_elem.get_attribute("aria-label"))
                                if match: rating = float(match.group(1))
                            except: pass

                            reviews_count = 0
                            try:
                                text_elements = driver.find_elements(By.XPATH, "//*[contains(text(), 'reviews') or contains(text(), 'review')]")
                                for elem in text_elements:
                                    if "Local Guide" in elem.text: continue
                                    match = re.search(r'(\d[\d,]*)\s+reviews?', elem.text)
                                    if match: 
                                        reviews_count = int(match.group(1).replace(",", ""))
                                        break
                            except: pass
                            
                            address = ""
                            try: address = driver.find_element(By.CSS_SELECTOR, "button[data-item-id='address']").get_attribute("aria-label").replace("Address: ", "")
                            except: pass

                            phone = ""
                            try: phone = driver.find_element(By.CSS_SELECTOR, "button[data-item-id^='phone']").get_attribute("aria-label").replace("Phone: ", "")
                            except: pass

                            website_url = None
                            has_website = False
                            social_url, social_platform, whatsapp_url = None, None, None
                            
                            try:
                                website_btn = driver.find_element(By.CSS_SELECTOR, "a[data-item-id='authority']")
                                raw_url = website_btn.get_attribute("href")
                                if "facebook.com" in raw_url: social_url=raw_url; social_platform='facebook'
                                elif "instagram.com" in raw_url: social_url=raw_url; social_platform='instagram'
                                elif "wa.me" in raw_url: whatsapp_url=raw_url
                                else: website_url=raw_url; has_website=True
                            except: pass

                            size = 'UNKNOWN'
                            if reviews_count > 0:
                                if reviews_count < 50: size = 'STARTUP'
                                elif reviews_count < 500: size = 'MEDIUM'
                                else: size = 'LARGE'

                            # Phone Deduplication
                            if phone and ContactDetails.objects.filter(phone_primary=phone).exists():
                                self.stdout.write(self.style.WARNING(f"   -> Duplicate phone {phone}. Skipping save."))
                            else:
                                # SAVE
                                rest, created = Lead.objects.update_or_create(
                                    gmaps_id=gmaps_id,
                                    defaults={
                                        'name': name, 'city': city, 'address': address,
                                        'rating': rating, 'reviews_count': reviews_count,
                                        'photos_count': 0, 'business_size': size,
                                        'has_website': has_website, 'website_url': website_url,
                                        'dataset_id': dataset_id
                                    }
                                )
                                if created:
                                    cd = ContactDetails.objects.create(lead=rest, phone_primary=phone)
                                    OutreachStatus.objects.create(lead=rest)
                                    if social_url: 
                                        cd.social_links={social_platform: social_url}; cd.save()
                                    if whatsapp_url: 
                                        cd.phone_whatsapp=whatsapp_url; cd.save()
                                    
                                    saved_count += 1
                                    cache.set('scraper_saved_count', saved_count, timeout=86400)
                                    self.db_log(f"   -> Saved: {name} (Total New: {saved_count})", self.style.SUCCESS)
                        
                        except Exception as e:
                            self.stdout.write(self.style.ERROR(f"Error extracting: {e}"))
                        
                        # Close tab and switch back
                        driver.close()
                        driver.switch_to.window(driver.window_handles[0])
                        time.sleep(1) # Brief pause

                    # Scroll logic
                    driver.execute_script("arguments[0].scrollTop = arguments[0].scrollHeight", scrollable_div)
                    time.sleep(random.uniform(2.5, 4.0))

                    # End of List logic
                    if len(visible_hrefs) == previous_len:
                        scroll_attempt += 1
                        if scroll_attempt > max_scroll_attempts:
                            self.stdout.write(self.style.WARNING("No new items found for a while. End of list?"))
                            break
                    else:
                        scroll_attempt = 0
                    
                    previous_len = len(visible_hrefs)

        except Exception as e:
            error_msg = f"Critical Error: {e}"
            self.stdout.write(self.style.ERROR(error_msg))
            driver.save_screenshot("debug_crash.png")
            self.notify_admins("Scraper Failed", error_msg)
        
        finally:
            self.db_log("Closing driver...")
            cache.set('scraper_is_running', False, timeout=86400)
            
            # Notify on success if we didn't crash
            try:
                saved_count = cache.get('scraper_saved_count', 0)
                self.notify_admins("Scraper Finished", f"Scraping completed. {saved_count} new leads were saved.")
            except Exception:
                pass
                
            driver.quit()

    def notify_admins(self, title, message):
        """Helper to notify all admin users about scraper status"""
        from notifications.utils import create_notification
        from django.contrib.auth.models import User
        
        admins = User.objects.filter(is_staff=True)
        for admin in admins:
            create_notification(
                recipient=admin,
                sender=None, # System Notification
                notification_type='SCRAPER_STATUS',
                title=title,
                message=message,
                target_url='/data/'
            )
