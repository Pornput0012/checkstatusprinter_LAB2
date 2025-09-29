from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from oauth2client.service_account import ServiceAccountCredentials
from datetime import datetime
from dotenv import load_dotenv
import pytz
import os
import gspread
import requests
from bs4 import BeautifulSoup
from linebot.v3.messaging import (
    Configuration, ApiClient, MessagingApi, PushMessageRequest,
    TextMessage, FlexMessage, FlexContainer
)
import logging
import json
from fastapi import FastAPI, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse
from linebot.v3 import WebhookHandler
import sqlite3

app = FastAPI()
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

load_dotenv()
tz = pytz.timezone("Asia/Bangkok")
sheet_url = os.getenv("SHEET_URL")
SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]
STATUS_PING = {
    "success": "Success",
    "timeout": "Request Timeout",
    "error": "Host unreachable / Error",
}
printer_1_url = os.getenv("PRINTER_1")
printer_2_url = os.getenv("PRINTER_2")

worksheet_printer_1 = os.getenv("WORKSHEET_PRINTER_1")
worksheet_printer_2 = os.getenv("WORKSHEET_PRINTER_2")

LINE_CHANNEL_SECRET = os.getenv("LINE_CHANNEL_SECRET")
LINE_CHANNEL_ACCESS_TOKEN = os.getenv("LINE_ACCESS_TOKEN")

configuration = Configuration(access_token=LINE_CHANNEL_ACCESS_TOKEN)
handler = WebhookHandler(LINE_CHANNEL_SECRET)

credentials = ServiceAccountCredentials.from_json_keyfile_name("credentials.json", SCOPES)

client = gspread.authorize(credentials)

# Database path - ใช้ volume หรือ local directory
DB_PATH = '/app/data/users.db' if os.path.exists('/app/data') else 'users.db'

def init_db():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT UNIQUE NOT NULL,
            name TEXT
        )
    ''')
    conn.commit()
    conn.close()

def add_user(user_id, name=None):
    """เพิ่มผู้ใช้ใหม่"""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    try:
        cursor.execute('INSERT INTO users (user_id, name) VALUES (?, ?)', (user_id, name))
        conn.commit()
        return True
    except sqlite3.IntegrityError:
        return False 
    finally:
        conn.close()

def get_all_users():
    conn = sqlite3.connect('users.db')
    cursor = conn.cursor()
    cursor.execute('SELECT user_id, name FROM users')
    users = cursor.fetchall()
    conn.close()
    return users

def delete_user(user_id):
    conn = sqlite3.connect('users.db')
    cursor = conn.cursor()
    cursor.execute('DELETE FROM users WHERE user_id = ?', (user_id,))
    deleted = cursor.rowcount > 0
    conn.commit()
    conn.close()
    return deleted

init_db()

@app.post("/webhook")
async def webhook(request: Request):
    body = await request.json()    
    if body.get('events'):
        for event in body['events']:
            source = event.get('source', {})
            if source.get('type') == 'group':
                group_id = source.get('groupId')
                print(f"Group ID: {group_id}")
            elif source.get('type') == 'user':
                user_id = source.get('userId')
                print(f"User ID: {user_id}")
    
    return 'OK'

@app.get("/check")
async def check_printers():
    try:
        job_7am()  # ใช้ job_7am สำหรับทดสอบ (ส่งทั้ง flex และ text)
        return {"status": "success", "message": "ตรวจสอบสถานะเครื่องพิมพ์เรียบร้อยแล้ว"}
    except Exception as e:
        return {"status": "error", "message": f"เกิดข้อผิดพลาด: {str(e)}"}

@app.get("/users", response_class=HTMLResponse)
async def users_page():
    users = get_all_users()
    
    html_content = f"""
    <!DOCTYPE html>
    <html lang="th">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>จัดการผู้ใช้ LINE Bot</title>
        <script src="https://cdn.tailwindcss.com"></script>
        <script src="https://cdn.tailwindcss.com?plugins=forms"></script>
    </head>
    <body class="bg-gray-50 min-h-screen">
        <div class="max-w-4xl mx-auto py-8 px-4">
            <div class="bg-white rounded-lg shadow-md p-6 mb-6">
                <h1 class="text-2xl font-bold text-gray-800 mb-6">จัดการผู้ใช้ LINE Bot</h1>
                
                <!-- Add User Form -->
                <div class="bg-blue-50 rounded-lg p-4 mb-6">
                    <h2 class="text-lg font-semibold text-blue-800 mb-4">เพิ่มผู้ใช้ใหม่</h2>
                    <form method="POST" action="/users" class="space-y-4">
                        <div>
                            <label for="user_id" class="block text-sm font-medium text-gray-700 mb-1">
                                LINE User ID <span class="text-red-500">*</span>
                            </label>
                            <input type="text" id="user_id" name="user_id" required
                                   class="w-full px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent"
                                   placeholder="เช่น U1234567890abcdef...">
                        </div>
                        <div>
                            <label for="name" class="block text-sm font-medium text-gray-700 mb-1">
                                ชื่อ (ไม่บังคับ)
                            </label>
                            <input type="text" id="name" name="name"
                                   class="w-full px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent"
                                   placeholder="ชื่อผู้ใช้">
                        </div>
                        <button type="submit" 
                                class="bg-blue-600 hover:bg-blue-700 text-white font-medium py-2 px-4 rounded-md transition duration-200">
                            เพิ่มผู้ใช้
                        </button>
                    </form>
                </div>
                
                <!-- Users List -->
                <div>
                    <h2 class="text-lg font-semibold text-gray-800 mb-4">รายการผู้ใช้ทั้งหมด ({len(users)} คน)</h2>
                    {"<div class='bg-gray-100 rounded-lg p-4 text-gray-600'>ยังไม่มีผู้ใช้</div>" if not users else ""}
                    {"".join([f'''
                    <div class="bg-white border border-gray-200 rounded-lg p-4 mb-3 flex justify-between items-center">
                        <div>
                            <div class="font-medium text-gray-800">{user[1] or "ไม่ระบุชื่อ"}</div>
                            <div class="text-sm text-gray-600 font-mono">{user[0]}</div>
                        </div>
                        <form method="POST" action="/users/delete" class="inline">
                            <input type="hidden" name="user_id" value="{user[0]}">
                            <button type="submit" 
                                    onclick="return confirm('คุณต้องการลบผู้ใช้นี้หรือไม่?')"
                                    class="bg-red-500 hover:bg-red-600 text-white text-sm px-3 py-1 rounded transition duration-200">
                                ลบ
                            </button>
                        </form>
                    </div>
                    ''' for user in users])}
                </div>
                
                <!-- Test Button -->
                <div class="mt-6 pt-4 border-t border-gray-200">
                    <button onclick="testPrinter()" 
                            class="bg-green-600 hover:bg-green-700 text-white font-medium py-2 px-4 rounded-md transition duration-200">
                        check status printer
                    </button>
                </div>
            </div>
        </div>
        
        <script>
            async function testPrinter() {{
                try {{
                    const response = await fetch('/check');
                    const data = await response.json();
                    alert(data.message);
                }} catch (error) {{
                    alert('เกิดข้อผิดพลาด: ' + error.message);
                }}
            }}
        </script>
    </body>
    </html>
    """
    return html_content

@app.post("/users")
async def add_user_endpoint(user_id: str = Form(...), name: str = Form(None)):
    if add_user(user_id.strip(), name.strip() if name else None):
        return RedirectResponse(url="/users", status_code=303)
    else:
        return HTMLResponse(
            f'<script>alert("ผู้ใช้นี้มีอยู่แล้ว!"); window.location.href="/users";</script>',
            status_code=400
        )

@app.post("/users/delete")
async def delete_user_endpoint(user_id: str = Form(...)):
    if delete_user(user_id):
        return RedirectResponse(url="/users", status_code=303)
    else:
        return HTMLResponse(
            f'<script>alert("ไม่พบผู้ใช้นี้!"); window.location.href="/users";</script>',
            status_code=404
        )

def create_printer_bubble(printer_name, ink_levels):
    """
    สร้าง bubble สำหรับเครื่องพิมพ์
    ink_levels = [M, C, Y, BK] ตามลำดับ
    """
    colors = ["M", "C", "Y", "BK"]
    color_configs = {
        "M": {"backgroundColor": "#ff00ff", "borderColor": "#ff00ff"},
        "C": {"backgroundColor": "#00FFFF", "borderColor": "#00FFFF"}, 
        "Y": {"backgroundColor": "#FFFF00", "borderColor": "#FFFF00"},
        "BK": {"backgroundColor": "#000000", "borderColor": "#000000"}
    }
    
    contents = []
    for i, color in enumerate(colors):
        color_config = color_configs[color]
        content = {
            "type": "box",
            "layout": "horizontal",
            "contents": [
                {
                    "type": "text",
                    "text": color,
                    "flex": 0
                },
                {
                    "type": "box",
                    "layout": "vertical",
                    "contents": [
                        {"type": "filler"},
                        {
                            "type": "box",
                            "layout": "vertical",
                            "contents": [],
                            "width": "12px",
                            "height": "12px",
                            "backgroundColor": color_config["backgroundColor"],
                            "borderWidth": "2px",
                            "borderColor": color_config["borderColor"],
                            "cornerRadius": "30px"
                        },
                        {"type": "filler"}
                    ]
                },
                {
                    "type": "text",
                    "text": str(ink_levels[i])
                }
            ],
            "spacing": "lg"
        }
        contents.append(content)
    
    bubble = {
        "type": "bubble",
        "header": {
            "type": "box",
            "layout": "vertical",
            "contents": [
                {
                    "type": "text",
                    "text": "LAB2",
                    "color": "#ffffff66"
                },
                {
                    "type": "text",
                    "text": printer_name,
                    "color": "#FFFFFF",
                    "size": "xl",
                    "weight": "bold"
                }
            ],
            "height": "100px",
            "backgroundColor": "#0367D3"
        },
        "body": {
            "type": "box",
            "layout": "vertical",
            "contents": contents
        }
    }
    return bubble

def send_text_message(message_text):
    """ส่ง text message ปกติให้ทุก userId ในฐานข้อมูล"""
    users = get_all_users()
    if not users:
        print("ไม่มีผู้ใช้ในฐานข้อมูล")
        return
    
    success_count = 0
    for user_id, name in users:
        try:
            with ApiClient(configuration) as api_client:
                line_bot_api = MessagingApi(api_client)
                line_bot_api.push_message(
                    PushMessageRequest(
                        to=user_id,
                        messages=[TextMessage(text=message_text)]
                    )
                )
            success_count += 1
            print(f"Text message sent to {name or user_id}: {message_text}")
        except Exception as e:
            print(f"Error sending text message to {name or user_id}: {e}")
    
    print(f"Text message sent successfully to {success_count}/{len(users)} users")

def handle_flex_message(printer_1_data, printer_2_data):
    users = get_all_users()
    if not users:
        print("ไม่มีผู้ใช้ในฐานข้อมูล")
        return
    
    try:
        bubbles = []
        
        # เพิ่ม bubble สำหรับ printer 1
        if printer_1_data:
            bubble1 = create_printer_bubble("Printer_1", printer_1_data)
            bubbles.append(bubble1)
        
        # เพิ่ม bubble สำหรับ printer 2
        if printer_2_data:
            bubble2 = create_printer_bubble("Printer_2", printer_2_data)
            bubbles.append(bubble2)
        
        if not bubbles:
            print("No printer data to send")
            return
        
        # สร้าง flex content
        if len(bubbles) == 1:
            # ส่ง bubble เดียว
            flex_content = bubbles[0]
        else:
            # ส่ง carousel
            flex_content = {
                "type": "carousel",
                "contents": bubbles
            }
        
        success_count = 0
        for user_id, name in users:
            try:
                with ApiClient(configuration) as api_client:
                    line_bot_api = MessagingApi(api_client)
                    flex_message = json.dumps(flex_content)
                    message = FlexMessage(
                        alt_text="Printer Status", 
                        contents=FlexContainer.from_json(flex_message)
                    )
                    line_bot_api.push_message(
                        PushMessageRequest(
                            to=user_id,
                            messages=[message]
                        )
                    )
                success_count += 1
                print(f"Flex message sent to {name or user_id}")
            except Exception as e:
                print(f"Error sending flex message to {name or user_id}: {e}")
        
        print(f"Flex message sent successfully to {success_count}/{len(users)} users")
    except Exception as e:
        print(f"Error preparing flex message: {e}")


def add_new_row(sheet_name, new_row):
    sheet = client.open_by_url(sheet_url).worksheet(sheet_name)
    sheet.append_row(new_row, value_input_option="USER_ENTERED")

def checkNetworkPrinter(printer_url,worksheet):
    try:
        response_printer = requests.get(printer_url, timeout=10)
        response_printer.raise_for_status()

        soup_printer = BeautifulSoup(response_printer.text, "lxml")
        toners_printer = soup_printer.find_all("img", class_="tonerremain")

        new_row = [datetime.now(tz).strftime("%m/%d/%Y %H:%M:00")]

        ink_levels = []

        for img in toners_printer:
            height = img.get("height")
            if height and height.isdigit():
                max_ink = os.getenv("MAX_INK")
                percentage = int((int(height) * 100) / int(max_ink))
                mapped_value = round(percentage / 10) * 10
                mapped_value = max(0, min(100, mapped_value))
                new_row.append(mapped_value)
                ink_levels.append(mapped_value)
        new_row.append(STATUS_PING["success"])
        add_new_row(worksheet,new_row)
        return {
            "success": True,
            "data": ink_levels
        }            
    except requests.exceptions.ConnectionError:
        new_row = [datetime.now(tz).strftime("%m/%d/%Y %H:%M:00"),0,0,0,0,STATUS_PING["error"]]
        add_new_row(worksheet,new_row)
        return {
            "success": False,
            "message": "ไม่สามารถเชื่อมต่อกับเครื่องพิมพ์ได้"
        }
    except requests.exceptions.Timeout:
        new_row = [datetime.now(tz).strftime("%m/%d/%Y %H:%M:00"),0,0,0,0,STATUS_PING["timeout"]]
        add_new_row(worksheet,new_row)
        return {
            "success": False,
            "message": "การเชื่อมต่อหมดเวลา"
        }
    except (requests.exceptions.HTTPError,requests.exceptions.RequestException):
        new_row = [datetime.now(tz).strftime("%m/%d/%Y %H:%M:00"),0,0,0,0,STATUS_PING["error"]]
        add_new_row(worksheet,new_row)
        return {
            "success": False,
            "message": "ไม่สามารถเชื่อมต่อกับเครื่องพิมพ์ได้"
        }
    except Exception as e:
        new_row = [datetime.now(tz).strftime("%m/%d/%Y %H:%M:00"),0,0,0,0,STATUS_PING["error"]]
        add_new_row(worksheet,new_row)
        return {
            "success": False,
            "message": "เกิดข้อผิดพลาดที่ไม่คาดคิด"
        }

def job_7am():
    """ทำงานเวลา 7:00 น. - ส่งทั้ง flex message และ text message"""
    result_printer_1 = checkNetworkPrinter(printer_1_url, worksheet_printer_1)
    result_printer_2 = checkNetworkPrinter(printer_2_url, worksheet_printer_2)
    
    success_count = 0
    error_messages = []
    
    printer_1_data = None
    printer_2_data = None
    
    if result_printer_1["success"]:
        success_count += 1
        printer_1_data = result_printer_1["data"]
    else:
        error_messages.append(f"Printer 1: {result_printer_1['message']}")
    
    if result_printer_2["success"]:
        success_count += 1
        printer_2_data = result_printer_2["data"]
    else:
        error_messages.append(f"Printer 2: {result_printer_2['message']}")

    # ส่งทั้ง flex message และ text message
    if success_count > 0:
        handle_flex_message(printer_1_data, printer_2_data)
        
        if error_messages:
            error_text = "❌ มีปัญหากับเครื่องพิมพ์:\n" + "\n".join(error_messages)
            send_text_message(error_text)
    else:
        error_text = "❌ ไม่สามารถเชื่อมต่อกับเครื่องพิมพ์ได้:\n" + "\n".join(error_messages)
        send_text_message(error_text)

def job_check_connection():
    """ทำงานเวลา 7:30-16:30 น. - แจ้งเตือนเฉพาะเมื่อเชื่อมต่อไม่ได้"""
    result_printer_1 = checkNetworkPrinter(printer_1_url, worksheet_printer_1)
    result_printer_2 = checkNetworkPrinter(printer_2_url, worksheet_printer_2)
    
    error_messages = []
    
    if not result_printer_1["success"]:
        error_messages.append(f"❌ Printer 1: {result_printer_1['message']}")
    
    if not result_printer_2["success"]:
        error_messages.append(f"❌ Printer 2: {result_printer_2['message']}")

    if error_messages:
        error_text = "⚠️ แจ้งเตือนปัญหาเครื่องพิมพ์:\n" + "\n".join(error_messages)
        send_text_message(error_text)
    else:
        print("✅ ทุกเครื่องพิมพ์เชื่อมต่อได้ปกติ - ไม่ส่งข้อความ")

if __name__ == '__main__':
    import uvicorn
    
    scheduler = BackgroundScheduler(timezone=tz)

    # 7:00 น. เฉพาะวันจันทร์-ศุกร์
    scheduler.add_job(job_7am, CronTrigger(hour=7, minute=0, day_of_week='mon-fri', timezone=tz))

    # 7:30-16:30 น. ทุกชั่วโมงที่ 30 นาที เฉพาะวันจันทร์-ศุกร์
    scheduler.add_job(job_check_connection, CronTrigger(hour='7-16', minute=30, day_of_week='mon-fri', timezone=tz))

    scheduler.start()

    print("เริ่มทำงาน scheduler และ web server แล้ว...")
    print("📅 ตารางงาน:")
    print("   - 07:00 น. (จันทร์-ศุกร์) = ส่งข้อมูลสถานะเครื่องพิมพ์แบบเต็ม (Flex + Text)")
    print("   - 07:30-16:30 น. (จันทร์-ศุกร์ ทุกชั่วโมง) = แจ้งเตือนเฉพาะเมื่อเชื่อมต่อไม่ได้ (Text)")

    try:
        uvicorn.run(app, host="0.0.0.0", port=8000)
    except KeyboardInterrupt:
        scheduler.shutdown()
        print("หยุดการทำงานแล้ว")