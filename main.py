import re
import requests
import os
from datetime import datetime, timedelta
from playwright.sync_api import sync_playwright
from dotenv import load_dotenv

load_dotenv()

# --- Configurations ---
SLACK_WEBHOOK_URL = os.getenv("SLACK_WEBHOOK_URL")
SESSION_FILE = "session.json"
LOGIN_URL = "https://lms-tokyo.iput.ac.jp/login/index.php"
CALENDAR_URL = "https://lms-tokyo.iput.ac.jp/calendar/view.php?view=day"
USER_ID = os.getenv("LMS_USER")
USER_PASS = os.getenv("LMS_PASS")

class LMSBot:
    def __init__(self, browser):
        # Create context with saved session if it exists
        ctx_args = {
            "locale": "ja-JP",
            "viewport": {"width": 1280, "height": 800},
            "user_agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/122.0.0.0 Safari/537.36"
        }
        if os.path.exists(SESSION_FILE):
            ctx_args["storage_state"] = SESSION_FILE
            print("Session loaded.")
        
        self.context = browser.new_context(**ctx_args)
        self.page = self.context.new_page()

    def navigate(self, url):
        """Navigate to URL without timeout error."""
        self.page.goto(url, wait_until="domcontentloaded", timeout=0)

    def login(self):
        print(f"Opening calendar...")
        self.navigate(CALENDAR_URL)

        if "login" in self.page.url:
            print("Logging in...")
            self.navigate(LOGIN_URL)
            self.page.locator("#username").fill(USER_ID)
            self.page.locator("#password").fill(USER_PASS)
            self.page.locator('button[type="submit"]').first.click()
            self.page.wait_for_load_state("domcontentloaded", timeout=0)
            
            # Save session for next time
            self.context.storage_state(path=SESSION_FILE)
            self.navigate(CALENDAR_URL)
        else:
            print("Session is valid.")
        return True

    def fetch_events(self):
        items = self.page.locator('[data-event-eventtype="attendance"]')
        results = []

        for i in range(items.count()):
            item = items.nth(i)
            text = item.inner_text()
            
            # Find activity link
            link_loc = item.get_by_role("link", name="活動に移動する")
            if link_loc.count() == 0:
                link_loc = item.locator("a.card-link")
            
            href = link_loc.get_attribute("href") if link_loc.count() > 0 else ""
            final_url = href

            if href:
                self.navigate(href)
                # Check for direct attendance submission link
                submit_btn = self.page.locator('.statuscol.cell.c2').get_by_role("link", name="出欠を送信する")
                if submit_btn.count() > 0:
                    submit_btn.click()

                self.navigate(CALENDAR_URL)
                

            # Parse time and title
            lines = [l.strip() for l in text.split('\n') if l.strip()]
            times = re.findall(r'(\d{2}:\d{2})', lines[1] if len(lines) > 1 else "")
            
            results.append({
                "title": lines[3] if len(lines) > 3 else "Unknown",
                "url": final_url,
                "start": times[0] if len(times) > 0 else "",
                "end": times[1] if len(times) > 1 else ""
            })
        return results

def send_slack(event):
    payload = {
        "title": event["title"],
        "start_time": event["start"],
        "end_time": event["end"],
        "url": event["url"]
    }
    requests.post(SLACK_WEBHOOK_URL, json=payload)
    print(f"Slack sent: {event['title']}")

def main():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        bot = LMSBot(browser)

        if bot.login():
            events = bot.fetch_events()
            now = datetime.now().replace(microsecond=0)

            for e in events:
                if not e["start"]: continue
                
                # Setup date objects for comparison
                start_dt = datetime.strptime(e["start"], "%H:%M").replace(year=now.year, month=now.month, day=now.day)
                end_dt = datetime.strptime(e["end"], "%H:%M").replace(year=now.year, month=now.month, day=now.day)
                lead_time = start_dt - timedelta(minutes=5)
                
                print(f"Checking: {e['title']} ({e['start']} - {e['end']})")

                # Condition: Current time is between 5 mins before start and the start of class
                print(f"Now: {now}, Lead Time: {lead_time}, Start: {start_dt}")
                if lead_time <= now <= start_dt:
                    send_slack(e)
                else:
                    print("Status: Waiting (Not in time range)")

        browser.close()

if __name__ == "__main__":
    main()