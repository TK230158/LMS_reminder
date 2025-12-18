import re
import requests
from datetime import datetime, timedelta
from playwright.sync_api import sync_playwright
import os
from dotenv import load_dotenv

load_dotenv()

SLACK_WEBHOOK_URL = "https://hooks.slack.com/triggers/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"
SESSION_FILE = "session.json"

class LMSBot:
    def __init__(self, browser):
        if os.path.exists(SESSION_FILE):
            self.context = browser.new_context(
                storage_state=SESSION_FILE,
                locale="ja-JP",
                viewport={"width": 1280, "height": 800},
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/122.0.0.0 Safari/537.36"
            )
            print("Using saved session.")
        else:
            self.context = browser.new_context(
                locale="ja-JP",
                viewport={"width": 1280, "height": 800},
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/122.0.0.0 Safari/537.36"
            )
            print("No session found.")

        self.page = self.context.new_page()

    def login(self, login_url, cal_url, user, pw):
            print(f"Directly accessing calendar: {cal_url}")
            self.page.goto(cal_url, wait_until="networkidle")

            if "login" in self.page.url:
                print("Session expired or invalid. Moving to login page...")

                self.page.goto(login_url, wait_until="domcontentloaded")
                self.page.locator("#username").fill(user)
                self.page.locator("#password").fill(pw)
                self.page.locator('button[type="submit"]').first.click()
                self.page.wait_for_load_state("networkidle")
                
                self.context.storage_state(path=SESSION_FILE)
                print("New session saved.")
                
                self.page.goto(cal_url, wait_until="networkidle")
                return True
            
            print("Session is still valid. Accessed calendar directly.")
            return True
    
    def go_to_calendar(self, url):
        self.page.goto(url, wait_until="networkidle")

    def get_attendance_data(self):
        items_locator = self.page.locator('[data-event-eventtype="attendance"]')
        count = items_locator.count()
        results = []

        for i in range(count):
            item = self.page.locator('[data-event-eventtype="attendance"]').nth(i)
            text = item.inner_text()
            
            link_locator = item.get_by_role("link", name="活動に移動する")
            if link_locator.count() == 0:
                link_locator = item.locator("a.card-link")
            
            activity_url = link_locator.get_attribute("href") if link_locator.count() > 0 else ""
            
            final_url = activity_url 

            if activity_url:
                self.page.goto(activity_url)
                attendance_link = self.page.locator('.statuscol.cell.c2').get_by_role("link", name="出欠を送信する")
                

                if attendance_link.count() > 0:
                    found_href = attendance_link.get_attribute("href")
                    if found_href:
                        final_url = found_href
                
                self.page.go_back()
                self.page.wait_for_selector('[data-event-eventtype="attendance"]')

            lines = [l.strip() for l in text.split('\n') if l.strip()]
            times = re.findall(r'(\d{2}:\d{2})', lines[1] if len(lines) > 1 else "")
            start = times[0] if len(times) > 0 else ""
            end = times[1] if len(times) > 1 else ""
            title = lines[3] if len(lines) > 3 else "Unknown"

            results.append({
                "title": title,
                "url": final_url,
                "start_time": start,
                "end_time": end
            })
            
        return results

def send_slack(event):
    payload = {
        "title": event["title"],
        "start_time": event["start_time"],
        "end_time": event["end_time"],
        "url": event["url"]
    }
    requests.post(SLACK_WEBHOOK_URL, json=payload)
    print(f"Sent: {event['title']}")

def main():
    CONFIG = {
        "login_url": "https://lms-tokyo.iput.ac.jp/login/index.php",
        "cal_url": "https://lms-tokyo.iput.ac.jp/calendar/view.php?view=day",
        "user": "TK230158",
        "pass": "Chi4kun1pass",
    }

    if not CONFIG["user"] or not CONFIG["pass"]:
        print("Error: environment variables LMS_USER and LMS_PASS must be set.")
        return

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        bot = LMSBot(browser)

        if bot.login(CONFIG["login_url"], CONFIG["cal_url"], CONFIG["user"], CONFIG["pass"]):
            events = bot.get_attendance_data()

            now = datetime.now().replace(microsecond=0)
            for e in events:
                if not e["start_time"]: continue
                
                start_dt = datetime.strptime(e["start_time"], "%H:%M").replace(
                    year=now.year, month=now.month, day=now.day
                )
                end_dt = datetime.strptime(e["end_time"], "%H:%M").replace(
                    year=now.year, month=now.month, day=now.day
                )
                
                # 通知開始は5分前から
                lead_time = start_dt - timedelta(minutes=5)
                
                print(f"チェック中: {e['title']} (範囲: {lead_time.strftime('%H:%M')} ~ {end_dt.strftime('%H:%M')})")

                # 今が「5分前」から「授業終了」までの間ならSlack！
                if lead_time <= now <= end_dt:
                    send_slack(e)
                else:
                    print(f"時間外だゆん: {e['title']}")

        browser.close()

if __name__ == "__main__":
    main()