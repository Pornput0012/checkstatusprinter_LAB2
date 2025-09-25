from apscheduler.schedulers.blocking import BlockingScheduler
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
from fastapi import FastAPI, Request
from linebot.v3 import WebhookHandler

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
USER_ID = os.getenv("USER_ID")

configuration = Configuration(access_token=LINE_CHANNEL_ACCESS_TOKEN)
handler = WebhookHandler(LINE_CHANNEL_SECRET)

credentials = ServiceAccountCredentials.from_json_keyfile_name("credentials.json", SCOPES)

client = gspread.authorize(credentials)

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
    """ส่ง text message ปกติ"""
    try:
        with ApiClient(configuration) as api_client:
            line_bot_api = MessagingApi(api_client)
            line_bot_api.push_message(
                PushMessageRequest(
                    to=USER_ID,
                    messages=[TextMessage(text=message_text)]
                )
            )
        print(f"Text message sent: {message_text}")
    except Exception as e:
        print(f"Error sending text message: {e}")

def handle_flex_message(printer_1_data, printer_2_data):
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
        
        with ApiClient(configuration) as api_client:
            line_bot_api = MessagingApi(api_client)
            flex_message = json.dumps(flex_content)
            message = FlexMessage(
                alt_text="Printer Status", 
                contents=FlexContainer.from_json(flex_message)
            )
            line_bot_api.push_message(
                PushMessageRequest(
                    to=USER_ID,
                    messages=[message]
                )
            )
        print("Flex message sent successfully")
    except Exception as e:
        print(f"Error sending flex message: {e}")


def add_new_row(sheet_name, new_row):
    sheet = client.open_by_url(sheet_url).worksheet(sheet_name)
    sheet.append_row(new_row)

def checkNetworkPrinter(printer_url,worksheet):
    try:
        response_printer = requests.get(printer_url, timeout=10)
        response_printer.raise_for_status()

        soup_printer = BeautifulSoup(response_printer.text, "lxml")
        toners_printer = soup_printer.find_all("img", class_="tonerremain")

        new_row = [datetime.now(tz).strftime("%d/%m/%Y")]
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
        return {
            "success": False,
            "message": "ไม่สามารถเชื่อมต่อกับเครื่องพิมพ์ได้"
        }
    except requests.exceptions.Timeout:
        return {
            "success": False,
            "message": "การเชื่อมต่อหมดเวลา"
        }
    except requests.exceptions.HTTPError | requests.exceptions.RequestException:
        return {
            "success": False,
            "message": "ไม่สามารถเชื่อมต่อกับเครื่องพิมพ์ได้"
        }
    except Exception as e:
        return {
            "success": False,
            "message": "เกิดข้อผิดพลาดที่ไม่คาดคิด"
        }

def job():
    result_printer_1 = checkNetworkPrinter(printer_1_url, worksheet_printer_1)
    result_printer_2 = checkNetworkPrinter(printer_2_url, worksheet_printer_2)
    
    print(f"Printer 1: {result_printer_1}")
    print(f"Printer 2: {result_printer_2}")
    
    # ตรวจสอบผลลัพธ์และส่งข้อความ
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

    # ส่งข้อความตามผลลัพธ์
    if success_count > 0:
        # มีข้อมูลสำเร็จอย่างน้อย 1 เครื่อง ส่ง FlexMessage
        handle_flex_message(printer_1_data, printer_2_data)
        
        # ถ้ามี error บางเครื่อง ส่ง TextMessage เพิ่มเติม
        if error_messages:
            error_text = "❌ มีปัญหากับเครื่องพิมพ์:\n" + "\n".join(error_messages)
            send_text_message(error_text)
    else:
        # ทุกเครื่องมีปัญหา ส่ง TextMessage เท่านั้น
        error_text = "❌ ไม่สามารถเชื่อมต่อกับเครื่องพิมพ์ได้:\n" + "\n".join(error_messages)
        send_text_message(error_text)



job()

scheduler = BlockingScheduler(timezone=tz)

scheduler.add_job(job, CronTrigger(hour=7, minute=30, timezone=tz))

print("เริ่มทำงาน scheduler แล้ว (กด Ctrl+C เพื่อหยุด)...")
scheduler.start()

# if __name__ == '__main__':
#     import uvicorn
#     uvicorn.run(app, host="0.0.0.0", port=8000)