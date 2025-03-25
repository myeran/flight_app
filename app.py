from flask import Flask, request, render_template, jsonify
import requests
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import NoSuchElementException, TimeoutException
from webdriver_manager.chrome import ChromeDriverManager
from datetime import datetime, timedelta
import json
import os
import logging
import time
import shutil
import threading 
from twilio.rest import Client

app = Flask(__name__)

# הגדרת לוגים
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

CACHE_FILE = 'flight_cache.json'
CACHE_DURATION = timedelta(hours=24)
SELECTED_FLIGHTS = {}
LAST_RUN_TIME = None

# הגדרות Twilio לשליחת SMS
TWILIO_ACCOUNT_SID = os.environ.get('TWILIO_ACCOUNT_SID')
TWILIO_AUTH_TOKEN = os.environ.get('TWILIO_AUTH_TOKEN')
TWILIO_PHONE_NUMBER = os.environ.get('TWILIO_PHONE_NUMBER')
USER_PHONE_NUMBER = os.environ.get('USER_PHONE_NUMBER')
ENABLE_SMS = False

client = Client(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)

def setup_driver(headless=False):
    try:
        driver_path = ChromeDriverManager().install()
        logger.debug(f"נתיב ה-ChromeDriver שנמצא: {driver_path}")
        
        if not os.path.exists(driver_path):
            logger.error(f"הקובץ {driver_path} לא נמצא!")
            raise Exception(f"ChromeDriver לא נמצא בנתיב: {driver_path}")
        
        if not os.access(driver_path, os.X_OK):
            logger.warning(f"אין הרשאות הפעלה ל-{driver_path}, מתקן...")
            os.chmod(driver_path, 0o755)
        
        service = Service(executable_path=driver_path)
        options = webdriver.ChromeOptions()
        if headless:
            options.add_argument('--headless')
        options.add_argument('--no-sandbox')
        options.add_argument('--disable-dev-shm-usage')
        options.add_argument('user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36')
        driver = webdriver.Chrome(service=service, options=options)
        driver.maximize_window()
        logger.debug("ChromeDriver נטען בהצלחה")
        return driver
    except Exception as e:
        logger.error(f"שגיאה בהגדרת ChromeDriver: {str(e)}")
        raise

def scrape_flights(args):
    date, origin, destination, direction = args
    cache_key = f"{date}_{origin}_{destination}_{direction}"
    current_time = datetime.now().strftime('%H:%M:%S')
    
    if os.path.exists(CACHE_FILE):
        try:
            with open(CACHE_FILE, 'r', encoding='utf-8') as f:
                cache = json.load(f)
            if not isinstance(cache, dict):
                logger.warning("קובץ הקאש פגום, מאתחל מחדש")
                cache = {}
            if cache_key in cache:
                if 'timestamp' in cache[cache_key] and 'data' in cache[cache_key]:
                    if (datetime.now() - datetime.strptime(cache[cache_key]['timestamp'], '%Y-%m-%d %H:%M:%S')) < CACHE_DURATION:
                        logger.debug(f"שימוש בנתונים מהקאש עבור {cache_key}")
                        flight_data = cache[cache_key]['data']
                        for flight in flight_data:
                            flight['last_checked'] = current_time
                        return flight_data
                else:
                    logger.warning(f"מבנה לא תקין בקאש עבור {cache_key}, נתעלם ממנו")
        except (json.JSONDecodeError, ValueError) as e:
            logger.error(f"שגיאה בקריאת קובץ הקאש: {str(e)}, מאתחל מחדש")
            cache = {}
    
    url = f"https://www.israir.co.il/reservation/search/domestic-flights/he/results?origin={origin}&destination={destination}&startDate={date}&eilatResident=1"
    driver = setup_driver(headless=True)
    try:
        logger.debug(f"מנסה לגשת לכתובת עם Selenium: {url}")
        driver.get(url)
        
        WebDriverWait(driver, 15).until(
            EC.presence_of_element_located((By.CLASS_NAME, "flight-result-item-card--domestic"))
        )
        time.sleep(3)
        
        flight_cards = driver.find_elements(By.CSS_SELECTOR, ".flight-result-item-card--domestic")
        logger.debug(f"נמצאו {len(flight_cards)} טיסות ב-HTML עם Selenium")
        
        if not flight_cards:
            logger.warning("לא נמצאו טיסות בדף")
            with open('debug_html.html', 'w', encoding='utf-8') as f:
                f.write(driver.page_source)
            flight_data = [{
                'direction': direction,
                'date': date,
                'departure_time': 'אין טיסות',
                'arrival_time': 'N/A',
                'price': 'N/A',
                'seats_left': 'N/A',
                'duration': 'N/A',
                'flight_code': 'N/A',
                'airline': 'N/A',
                'origin': origin,
                'destination': destination,
                'index': 0,
                'booking_url': None,
                'last_checked': current_time,
                'changed': False,
                'is_full': False
            }]
        else:
            flight_data = []
            for index, card in enumerate(flight_cards):
                try:
                    logger.debug(f"מחלץ נתונים עבור טיסה {index}")
                    
                    time_blocks = card.find_elements(By.CSS_SELECTOR, ".flight-text-block--primary .flight-text-block__bottom-text--primary")
                    departure_time = time_blocks[0].text.strip() if len(time_blocks) > 0 else "לא נמצא זמן"
                    arrival_time = time_blocks[1].text.strip() if len(time_blocks) > 1 else "לא נמצא זמן הגעה"
                    logger.debug(f"טיסה {index}: departure_time={departure_time}, arrival_time={arrival_time}")
                    
                    price_elem = card.find_element(By.CSS_SELECTOR, ".flight-result-price__top--domestic span:last-child")
                    price = price_elem.text.strip() if price_elem else "לא נמצא מחיר"
                    logger.debug(f"טיסה {index}: price={price}")
                    
                    seats_elem = card.find_element(By.CSS_SELECTOR, ".purchase-block-button-group__top")
                    seats_left = seats_elem.text.strip() if seats_elem else "לא נמצא מידע על מקומות"
                    is_full = seats_left in ["אין מקומות", "0", "מלאה", "לא נמצא מידע על מקומות"]
                    if is_full:
                        seats_left = "טיסה מלאה"
                    logger.debug(f"טיסה {index}: seats_left={seats_left}, is_full={is_full}")
                    
                    duration_elem = card.find_element(By.CSS_SELECTOR, ".flight-text-block--sm .flight-text-block__top-text--primary")
                    duration = duration_elem.text.strip() if duration_elem else "לא נמצא משך"
                    logger.debug(f"טיסה {index}: duration={duration}")
                    
                    flight_code_elem = card.find_element(By.CSS_SELECTOR, ".flight-text-block__top-text--powered-by")
                    flight_code_text = flight_code_elem.text.strip()
                    flight_code = flight_code_text.split('[')[-1].split(']')[0] if '[' in flight_code_text else "לא נמצא קוד טיסה"
                    logger.debug(f"טיסה {index}: flight_code={flight_code}")
                    
                    airline_elem = card.find_element(By.CSS_SELECTOR, ".flight-text-block__bottom-text--powered-by .dib")
                    airline = airline_elem.text.strip() if airline_elem else "לא נמצאה חברה"
                    logger.debug(f"טיסה {index}: airline={airline}")
                    
                    booking_url = None
                    try:
                        select_button = card.find_element(By.CSS_SELECTOR, ".purchase-block-button-group__button")
                        button_html = driver.execute_script("return arguments[0].outerHTML;", select_button)
                        if 'data-deal-id' in button_html:
                            deal_id = select_button.get_attribute('data-deal-id')
                            booking_url = f"https://www.israir.co.il/reservation/deal/searchDomesticFlight/he/{deal_id}"
                        elif 'onclick' in button_html:
                            onclick = select_button.get_attribute('onclick')
                            if onclick and 'window.open' in onclick:
                                start = onclick.find("'") + 1
                                end = onclick.find("'", start)
                                booking_url = onclick[start:end]
                    except NoSuchElementException:
                        logger.debug(f"טיסה {index}: לא נמצא כפתור בחירה")
                    
                    flight_data.append({
                        'direction': direction,
                        'date': date,
                        'departure_time': departure_time,
                        'arrival_time': arrival_time,
                        'price': price,
                        'seats_left': seats_left,
                        'duration': duration,
                        'flight_code': flight_code,
                        'airline': airline,
                        'origin': origin,
                        'destination': destination,
                        'index': index,
                        'booking_url': booking_url,
                        'last_checked': current_time,
                        'changed': False,
                        'is_full': is_full
                    })
                    logger.debug(f"טיסה {index} נוספה ל-flight_data: {flight_data[-1]}")
                except Exception as e:
                    logger.error(f"שגיאה בחילוץ פרטי טיסה {index}: {str(e)}")
                    continue
        
        cache = {}
        if os.path.exists(CACHE_FILE):
            try:
                with open(CACHE_FILE, 'r', encoding='utf-8') as f:
                    cache = json.load(f)
                if not isinstance(cache, dict):
                    cache = {}
            except json.JSONDecodeError:
                cache = {}
            shutil.copy(CACHE_FILE, CACHE_FILE + '.bak')
        cache[cache_key] = {
            'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            'data': flight_data
        }
        with open(CACHE_FILE, 'w', encoding='utf-8') as f:
            json.dump(cache, f, ensure_ascii=False)
        
        logger.debug(f"Returning flight_data: {flight_data}")
        return flight_data
    
    except Exception as e:
        logger.error(f"שגיאה בגרידה עם Selenium: {str(e)}")
        with open('debug_html_error.html', 'w', encoding='utf-8') as f:
            f.write(driver.page_source)
        flight_data = [{
            'direction': direction,
            'date': date,
            'departure_time': 'N/A',
            'arrival_time': 'N/A',
            'price': 'N/A',
            'seats_left': 'N/A',
            'duration': 'N/A',
            'flight_code': 'N/A',
            'airline': 'N/A',
            'origin': origin,
            'destination': destination,
            'index': 0,
            'booking_url': None,
            'last_checked': current_time,
            'changed': False,
            'is_full': False
        }]
        return flight_data
    finally:
        driver.quit()

def monitor_selected_flights():
    while True:
        current_time = datetime.now().strftime('%H:%M:%S')
        if SELECTED_FLIGHTS:
            logger.debug(f"בודק טיסות שנבחרו: {SELECTED_FLIGHTS}")
            for flight_key, flight in list(SELECTED_FLIGHTS.items()):
                date, origin, destination, direction, index = flight_key.split('_')
                result = scrape_flights((date, origin, destination, direction))
                if result and len(result) > int(index):
                    current_flight = result[int(index)]
                    prev_seats = flight.get('seats_left', 'לא ידוע')
                    curr_seats = current_flight['seats_left']
                    
                    if prev_seats != curr_seats:
                        logger.debug(f"שינוי זוהה בטיסה שנבחרה {flight_key}: {prev_seats} -> {curr_seats}")
                        flight['changed'] = True
                        message = f"שינוי במספר המקומות בטיסה {flight['flight_code']} ב-{date} מ-{origin} ל-{destination} בשעה {flight['departure_time']}: {prev_seats} -> {curr_seats}"
                        if ENABLE_SMS:
                            send_sms(message)
                    else:
                        flight['changed'] = False
                    
                    flight['seats_left'] = curr_seats
                    flight['last_checked'] = current_time
                    flight['is_full'] = current_flight['is_full']
                    flight['price'] = current_flight['price']
        time.sleep(60)

def send_sms(message):
    try:
        client.messages.create(
            body=message,
            from_=TWILIO_PHONE_NUMBER,
            to=USER_PHONE_NUMBER
        )
        logger.debug(f"SMS נשלח: {message}")
    except Exception as e:
        logger.error(f"שגיאה בשליחת SMS: {str(e)}")

@app.route('/', methods=['GET', 'POST'])
def home():
    global LAST_SEARCH_FLIGHTS
    LAST_SEARCH_FLIGHTS = getattr(app, 'last_search_flights', None)
    
    if request.method == 'POST':
        start_date = request.form['start_date']
        end_date = request.form['end_date']
        
        try:
            start = datetime.strptime(start_date, '%d/%m/%Y')
            end = datetime.strptime(end_date, '%d/%m/%Y')
            
            if start > end:
                return render_template('flights.html', error="תאריך התחלה חייב להיות לפני תאריך סיום", flights=None, last_run=LAST_RUN_TIME, monitored_flights={})
            
            tasks = []
            current = start
            while current <= end:
                date_str = current.strftime("%d/%m/%Y")
                tasks.append((date_str, "ETM", "TLV", "הלוך"))
                tasks.append((date_str, "TLV", "ETM", "חזור"))
                current += timedelta(days=1)
            
            all_flights = []
            for task in tasks:
                result = scrape_flights(task)
                for flight in result:
                    flight['key'] = f"{flight['date']}_{flight['origin']}_{flight['destination']}_{flight['direction']}_{flight['index']}"
                    if flight['key'] in SELECTED_FLIGHTS:
                        selected_flight = SELECTED_FLIGHTS[flight['key']]
                        flight['seats_left'] = selected_flight['seats_left']
                        flight['last_checked'] = selected_flight['last_checked']
                        flight['changed'] = selected_flight['changed']
                        flight['is_full'] = selected_flight['is_full']
                        flight['price'] = selected_flight['price']
                    if 'last_checked' not in flight or flight['last_checked'] is None:
                        flight['last_checked'] = datetime.now().strftime('%H:%M:%S')
                    all_flights.append(flight)
            
            logger.debug(f"כל הטיסות שנאספו: {all_flights}")
            LAST_SEARCH_FLIGHTS = all_flights
            app.last_search_flights = all_flights
            return render_template('flights.html', flights=all_flights, error=None, last_run=LAST_RUN_TIME, monitored_flights={})
        
        except ValueError:
            return render_template('flights.html', error="פורמט תאריך לא תקין. השתמש ב-dd/mm/yyyy", flights=LAST_SEARCH_FLIGHTS, last_run=LAST_RUN_TIME, monitored_flights={})
    
    return render_template('flights.html', flights=LAST_SEARCH_FLIGHTS, error=None, last_run=LAST_RUN_TIME, monitored_flights={})

@app.route('/book_flight', methods=['POST'])
def book_flight():
    data = request.get_json()
    date = data.get('date')
    origin = data.get('origin')
    destination = data.get('destination')
    flight_index = int(data.get('index'))

    url = f"https://www.israir.co.il/reservation/search/domestic-flights/he/results?origin={origin}&destination={destination}&startDate={date}&eilatResident=1"
    driver = setup_driver(headless=False)
    try:
        logger.debug(f"מנסה לגשת לכתובת עם Selenium: {url}")
        driver.get(url)

        WebDriverWait(driver, 10).until(
            EC.presence_of_element_located((By.CLASS_NAME, "flight-result-item-card--domestic"))
        )

        flight_cards = driver.find_elements(By.CSS_SELECTOR, ".flight-result-item-card--domestic")
        if flight_index >= len(flight_cards):
            return jsonify({'status': 'error', 'message': 'טיסה לא נמצאה'})

        select_button = flight_cards[flight_index].find_element(By.CSS_SELECTOR, ".purchase-block-button-group__button")
        button_text = select_button.text.strip()
        if "בחירה" in button_text:
            select_button.click()
            logger.debug(f"לחצתי על כפתור 'בחירה' עבור טיסה {flight_index}.")
        
        time.sleep(2)

        continue_button = WebDriverWait(driver, 10).until(
            EC.element_to_be_clickable((By.XPATH, "//button[contains(@class, 'reservation-domestic-flights-booking--btn')]"))
        )
        continue_button.click()
        logger.debug("לחצתי על 'המשיכו לפרטים והזמנה'.")

        time.sleep(3)
        return jsonify({'status': 'success', 'message': 'הגעתי לדף ההזמנה. הדפדפן נשאר פתוח.'})

    except Exception as e:
        logger.error(f"שגיאה בתהליך ההזמנה: {str(e)}")
        driver.quit()
        return jsonify({'status': 'error', 'message': 'שגיאה בתהליך ההזמנה'})

@app.route('/reset_cache', methods=['POST'])
def reset_cache():
    if os.path.exists(CACHE_FILE):
        os.remove(CACHE_FILE)
        logger.debug("קובץ הקאש נמחק")
        return jsonify({'status': 'success', 'message': 'קובץ הקאש נמחק'})
    return jsonify({'status': 'success', 'message': 'אין קובץ קאש למחיקה'})

@app.route('/add_selected_flight', methods=['POST'])
def add_selected_flight():
    flight = request.get_json()
    flight_key = f"{flight['date']}_{flight['origin']}_{flight['destination']}_{flight['direction']}_{flight['index']}"
    if flight_key not in SELECTED_FLIGHTS:
        SELECTED_FLIGHTS[flight_key] = flight
        logger.debug(f"טיסה נוספה לבדיקה כל דקה: {flight_key}")
    return jsonify({'status': 'success', 'message': 'טיסה נוספה לבדיקה'})

@app.route('/remove_selected_flight', methods=['POST'])
def remove_selected_flight():
    flight = request.get_json()
    flight_key = f"{flight['date']}_{flight['origin']}_{flight['destination']}_{flight['direction']}_{flight['index']}"
    if flight_key in SELECTED_FLIGHTS:
        del SELECTED_FLIGHTS[flight_key]
        logger.debug(f"טיסה הוסרה מבדיקה כל דקה: {flight_key}")
    return jsonify({'status': 'success', 'message': 'טיסה הוסרה מבדיקה'})

@app.route('/get_selected_flights', methods=['GET'])
def get_selected_flights():
    return jsonify(list(SELECTED_FLIGHTS.values()))

if __name__ == '__main__':
    selected_monitor_thread = threading.Thread(target=monitor_selected_flights, daemon=True)
    selected_monitor_thread.start()
    app.run(host='0.0.0.0', port=8000, debug=False)
    #end