from django.core.management.base import BaseCommand
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from webdriver_manager.chrome import ChromeDriverManager
import time
import re

class Command(BaseCommand):
    help = 'Verify Google Maps selectors'

    def handle(self, *args, **options):
        options = webdriver.ChromeOptions()
        options.add_argument("--headless")
        options.add_argument("--no-sandbox")
        options.add_argument("--disable-dev-shm-usage")
        options.add_argument("--window-size=1920,1080")
        options.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")
        
        service = Service(ChromeDriverManager().install())
        driver = webdriver.Chrome(service=service, options=options)

        try:
            # Direct link to Seagull
            url = "https://www.google.com/maps/place/Seagull+Lead+NewCairo/data=!4m7!3m6!1s0x145823b829b0aa77:0xe6711b861da6e8c7!8m2!3d30.0292717!4d31.4766873!16s%2Fg%2F11s0t5_ghl!19sChIJd6qwKbgjWBQRx-imHYYbceY?authuser=0&hl=en"
            self.stdout.write(f"Navigating to {url}")
            driver.get(url)
            
            time.sleep(10) 
            
            self.stdout.write("Scanning for text...")
            
            elements = driver.find_elements(By.XPATH, "//*[contains(text(), 'reviews')]")
            for elem in elements:
                try:
                    txt = elem.text
                    tag = elem.tag_name
                    parent = elem.find_element(By.XPATH, "..").tag_name
                    self.stdout.write(f"[TEXT MATCH] Tag: {tag}, Text: '{txt}'")
                except:
                    pass

        except Exception as e:
            self.stdout.write(f"Error: {e}")
        finally:
            driver.quit()
