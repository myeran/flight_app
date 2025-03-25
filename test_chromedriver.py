import os
import logging
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from webdriver_manager.chrome import ChromeDriverManager

# הגדרת לוגים
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

def test_chromedriver():
    try:
        # מוריד מחדש את ChromeDriver לגרסה התואמת ל-Chrome המותקן
        logger.info("מוריד את ChromeDriver...")
        driver_path = ChromeDriverManager().install()
        logger.debug(f"נתיב ה-ChromeDriver: {driver_path}")

        # בדיקת קיום הקובץ
        if not os.path.exists(driver_path):
            logger.error(f"הקובץ {driver_path} לא נמצא!")
            return False

        # בדיקת ותיקון הרשאות
        if not os.access(driver_path, os.X_OK):
            logger.warning(f"אין הרשאות הפעלה ל-{driver_path}, מתקן...")
            os.chmod(driver_path, 0o755)
            if not os.access(driver_path, os.X_OK):
                logger.error(f"לא ניתן לתקן את ההרשאות ל-{driver_path}")
                return False
            else:
                logger.debug("הרשאות תוקנו בהצלחה")

        # הגדרת השירות והאפשרויות
        service = Service(executable_path=driver_path)
        options = webdriver.ChromeOptions()
        options.add_argument('--headless')
        options.add_argument('--no-sandbox')
        options.add_argument('--disable-dev-shm-usage')
        options.add_argument('user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36')

        # ניסיון לפתוח את הדפדפן
        logger.debug("מנסה לפתוח את ChromeDriver...")
        driver = webdriver.Chrome(service=service, options=options)
        logger.debug("ChromeDriver נפתח בהצלחה!")

        # ניסיון לגשת לדף
        logger.debug("מנסה לגשת ל-Google...")
        driver.get("https://www.google.com")
        logger.debug(f"כותרת הדף: {driver.title}")

        # סגירה
        driver.quit()
        logger.debug("ChromeDriver נסגר בהצלחה")
        return True

    except Exception as e:
        logger.error(f"שגיאה ב-ChromeDriver: {str(e)}")
        return False

if __name__ == "__main__":
    logger.info("בודק את תקינות ChromeDriver...")
    if test_chromedriver():
        logger.info("ChromeDriver עובד כראוי!")
    else:
        logger.error("ChromeDriver לא עובד!")