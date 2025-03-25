import json
import time
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, WebDriverException, NoSuchElementException

def setup_driver():
    """הגדרת הדרייבר של Chrome עם אפשרויות מתאימות"""
    chrome_options = Options()
    # הסר את ההערה מהשורה הבאה אם אתה רוצה מצב headless
    # chrome_options.add_argument("--headless")
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")
    chrome_options.add_argument("--disable-gpu")
    chrome_options.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36")
    
    service = Service("/opt/homebrew/bin/chromedriver")
    try:
        driver = webdriver.Chrome(service=service, options=chrome_options)
        driver.maximize_window()
        return driver
    except WebDriverException as e:
        print(f"שגיאה בהגדרת הדרייבר: {e}")
        return None

def scrape_flights_and_proceed():
    """גרידת פרטי טיסות, בחירת טיסה והמשך לדף הבא"""
    driver = setup_driver()
    if not driver:
        return []

    url = (
        "https://www.israir.co.il/reservation/search/domestic-flights/he/results"
        "?origin=ETM&destination=TLV&startDate=23/03/2025&eilatResident=1&searchTime=2025-03-20T07:23:50.459Z"
    )
    
    print(f"ניגש לכתובת: {url}")
    driver.get(url)

    # המתנה לטעינת הדף ולזיהוי אלמנטים
    try:
        WebDriverWait(driver, 20).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, ".flight-result-item-card--domestic"))
        )
        print("כרטיסי הטיסות נטענו בהצלחה.")
    except TimeoutException:
        print("חריגה מזמן ההמתנה: כרטיסי הטיסות לא נמצאו.")
        print("תוכן הדף שנטען:")
        with open("debug_page.html", "w", encoding="utf-8") as f:
            f.write(driver.page_source)
        print("ה-HTML נשמר ל-debug_page.html")
        driver.quit()
        return []

    # איתור כרטיסי הטיסות
    flight_cards = driver.find_elements(By.CSS_SELECTOR, ".flight-result-item-card--domestic")
    flights = []

    for index, card in enumerate(flight_cards):
        try:
            # חילוץ שעות המראה ונחיתה
            time_blocks = card.find_elements(By.CSS_SELECTOR, ".flight-text-block--primary .flight-text-block__bottom-text--primary")
            departure_time = time_blocks[0].text.strip() if len(time_blocks) > 0 else "לא נמצא"
            arrival_time = time_blocks[1].text.strip() if len(time_blocks) > 1 else "לא נמצא"

            # חילוץ מחיר
            price_elem = card.find_element(By.CSS_SELECTOR, ".flight-result-price__top span:last-child")
            price = price_elem.text.strip() if price_elem else "לא נמצא"

            # חילוץ מספר טיסה
            flight_num_elem = card.find_element(By.CSS_SELECTOR, ".flight-text-block__top-text--powered-by")
            flight_number = flight_num_elem.text.strip().split('[')[-1].split(']')[0] if flight_num_elem else "לא נמצא"

            flight_data = {
                "flight_number": flight_number,
                "departure_time": departure_time,
                "arrival_time": arrival_time,
                "price": price,
                "origin": "ETM",
                "destination": "TLV",
                "date": "23/03/2025"
            }
            flights.append(flight_data)
            print(f"טיסה {index + 1}: {flight_data}")
        except Exception as e:
            print(f"שגיאה בחילוץ פרטי טיסה {index + 1}: {e}")
            continue

    # שמירת התוצאות לקובץ JSON
    try:
        with open("flight_cache.json", "w", encoding="utf-8") as f:
            json.dump(flights, f, ensure_ascii=False, indent=4)
        print("התוצאות נשמרו בהצלחה ל-flight_cache.json")
    except Exception as e:
        print(f"שגיאה בשמירת הקובץ: {e}")

    # בחירת הטיסה הראשונה (אם לא נבחרה כבר)
    if flight_cards:
        try:
            select_button = flight_cards[0].find_element(By.CSS_SELECTOR, ".purchase-block-button-group__button")
            button_text = select_button.find_element(By.TAG_NAME, "span").text.strip()
            if button_text == "בחירה":
                select_button.click()
                print("לחצתי על כפתור 'בחירה' עבור הטיסה הראשונה.")
            else:
                print("הטיסה הראשונה כבר נבחרה (מצב 'בחרת').")
        except NoSuchElementException as e:
            print(f"שגיאה בבחירת הטיסה: {e}")
            print("תוכן הכרטיס הראשון:")
            print(flight_cards[0].get_attribute("outerHTML"))
            driver.quit()
            return flights

        # המתנה קצרה לאחר הלחיצה
        time.sleep(2)

        # לחיצה על "המשיכו לפרטים והזמנה"
        try:
            continue_button = WebDriverWait(driver, 10).until(
                EC.element_to_be_clickable((By.XPATH, "//button[contains(@class, 'reservation-domestic-flights-booking--btn')]"))
            )
            continue_button.click()
            print("לחצתי על 'המשיכו לפרטים והזמנה'.")
        except TimeoutException as e:
            print(f"שגיאה בלחיצה על 'המשיכו לפרטים והזמנה': {e}")
            print("תוכן הדף לאחר בחירת הטיסה:")
            with open("debug_page_after_selection.html", "w", encoding="utf-8") as f:
                f.write(driver.page_source)
            print("ה-HTML נשמר ל-debug_page_after_selection.html")
            driver.quit()
            return flights

        # המתנה לטעינת הדף הבא
        time.sleep(3)
        print("הגעתי לדף הבא. תוכן הדף:")
        with open("next_page.html", "w", encoding="utf-8") as f:
            f.write(driver.page_source)
        print("ה-HTML של הדף הבא נשמר ל-next_page.html")

    driver.quit()
    return flights

def main():
    """פונקציה ראשית להרצת הסקריפט"""
    print("מתחיל לגרד טיסות...")
    flights = scrape_flights_and_proceed()
    
    if not flights:
        print("לא נמצאו טיסות או שהייתה שגיאה בגרידה.")
    else:
        print(f"נמצאו {len(flights)} טיסות.")

if __name__ == "__main__":
    main()