import os
import openai
import requests
import json
import streamlit as st
from google.oauth2.service_account import Credentials   
from googleapiclient.discovery import build
from anthropic import Anthropic
from pathlib import Path
import re

# CONFIG 

OPENAI_API_KEY      = st.secrets["OPENAI_API_KEY"]
GROK_API_KEY        = st.secrets["GROK_API_KEY"]
ANTHROPIC_API_KEY   = st.secrets["ANTHROPIC_API_KEY"]
COINMARKETCAP_API_KEY = st.secrets["COINMARKETCAP_API_KEY"]

SPREADSHEET_ID = st.secrets["SPREADSHEET_ID"]
SHEET_NAME     = st.secrets["SHEET_NAME"]

FOLDER_ID = st.secrets["FOLDER_ID"]
GUIDELINES_FOLDER_ID = st.secrets["GUIDELINES_FOLDER_ID"]

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/documents",
    "https://www.googleapis.com/auth/drive"
]

def get_service_account_credentials():
    return Credentials.from_service_account_info(st.secrets["service_account"], scopes=SCOPES)

def get_file_content_from_drive(drive_service, folder_id, filename):
    try:
        query = f"name = '{filename}' and '{folder_id}' in parents and trashed = false"
        results = drive_service.files().list(q=query, spaces='drive', fields='files(id, name, mimeType)').execute()
        files = results.get('files', [])
        if not files:
            raise Exception(f"File {filename} not found in folder")
        file_id = files[0]['id']
        mime_type = files[0]['mimeType']
        if mime_type in ['application/vnd.google-apps.document', 'application/vnd.google-apps.spreadsheet']:
            content = drive_service.files().export(fileId=file_id, mimeType='text/plain').execute()
            return content.decode('utf-8')
        else:
            content = drive_service.files().get_media(fileId=file_id).execute()
            return content.decode('utf-8')
    except Exception as e:
        return None

def get_selected_casino():
    creds = get_service_account_credentials()
    sheets = build("sheets", "v4", credentials=creds)
    return sheets.spreadsheets().values().get(spreadsheetId=SPREADSHEET_ID, range=f"{SHEET_NAME}!B1").execute().get("values", [[""]])[0][0].strip()

def write_review_link_to_sheet(link):
    creds = get_service_account_credentials()
    sheets = build("sheets", "v4", credentials=creds)
    body = {"values": [[link]]}
    sheets.spreadsheets().values().update(spreadsheetId=SPREADSHEET_ID, range=f"{SHEET_NAME}!B7", valueInputOption="RAW", body=body).execute()

def get_selected_casino_data(casino_name):
    creds = get_service_account_credentials()
    sheets = build("sheets", "v4", credentials=creds)
    rows = sheets.spreadsheets().values().get(spreadsheetId=SPREADSHEET_ID, range=f"{SHEET_NAME}!B2:O").execute().get("values", [])
    sections = {
        "General": (2, 3, 4),
        "Payments": (5, 6, 7),
        "Games": (8, 9, 10),
        "Responsible Gambling": (11, 12, 13),
    }
    for row in rows:
        if row and row[0].strip() == casino_name:
            data = {}
            for sec, (mi, ti, si) in sections.items():
                main = row[mi] if len(row) > mi else ""
                top = row[ti] if len(row) > ti else ""
                sim = row[si] if len(row) > si else ""
                data[sec] = {
                    "main": main or "[No data provided]",
                    "top": top or "[No top comparison available]",
                    "sim": sim or "[No similar comparison available]"
                }
            return casino_name, data
    raise ValueError(f"Casino '{casino_name}' not found in sheet")

client = openai.OpenAI(api_key=OPENAI_API_KEY)
anthropic = Anthropic(api_key=ANTHROPIC_API_KEY)

def call_openai(prompt):
    return client.chat.completions.create(model="gpt-4o", messages=[{"role": "user", "content": prompt}], temperature=0.5, max_tokens=800).choices[0].message.content.strip()

def call_grok(prompt):
    headers = {"Content-Type": "application/json", "Authorization": f"Bearer {GROK_API_KEY}"}
    payload = {"model": "grok-3", "messages": [{"role": "user", "content": prompt}], "temperature": 0.5, "max_tokens": 800}
    j = requests.post("https://api.x.ai/v1/chat/completions", json=payload, headers=headers).json()
    return j.get("choices", [{}])[0].get("message", {}).get("content", "[Grok failed]").strip()

def call_claude(prompt):
    return anthropic.messages.create(model="claude-3-7-sonnet-20250219", max_tokens=800, temperature=0.5, messages=[{"role": "user", "content": prompt}]).content[0].text.strip()

def find_existing_doc(drive_service, folder_id, title):
    query = f"name='{title}' and '{folder_id}' in parents and trashed=false"
    results = drive_service.files().list(q=query, fields="files(id, name)").execute()
    files = results.get("files", [])
    return files[0]["id"] if files else None

def insert_parsed_text_with_formatting(docs_service, doc_id, review_text):
    docs_service.documents().batchUpdate(documentId=doc_id, body={"requests": [{"insertText": {"location": {"index": 1}, "text": review_text}}]}).execute()

def create_google_doc_in_folder(docs_service, drive_service, folder_id, doc_title, review_text):
    doc_id = docs_service.documents().create(body={"title": doc_title}).execute()["documentId"]
    insert_parsed_text_with_formatting(docs_service, doc_id, review_text)
    file = drive_service.files().get(fileId=doc_id, fields="parents").execute()
    previous_parents = ",".join(file.get('parents', []))
    drive_service.files().update(fileId=doc_id, addParents=folder_id, removeParents=previous_parents, fields="id, parents").execute()
    return doc_id

def main():
    st.set_page_config(page_title="Review Generator", layout="centered", initial_sidebar_state="collapsed")
    st.markdown("## Review is being written!")

    try:
        user_creds = get_service_account_credentials()
        docs_service = build("docs", "v1", credentials=user_creds)
        drive_service = build("drive", "v3", credentials=user_creds)

        price = requests.get("https://pro-api.coinmarketcap.com/v1/cryptocurrency/quotes/latest", headers={"Accepts": "application/json", "X-CMC_PRO_API_KEY": COINMARKETCAP_API_KEY}, params={"symbol": "BTC", "convert": "USD"}).json().get("data", {}).get("BTC", {}).get("quote", {}).get("USD", {}).get("price")
        btc_str = f"1 BTC = ${price:,.2f}" if price else "[BTC price unavailable]"

        casino = get_selected_casino()
        casino, secs = get_selected_casino_data(casino)

        section_configs = {
            "General": ("BaseGuidelinesClaude", "StructureTemplateGeneral", call_claude),
            "Payments": ("BaseGuidelinesClaude", "StructureTemplatePayments", call_claude),
            "Games": ("BaseGuidelinesClaude", "StructureTemplateGames", call_claude),
            "Responsible Gambling": ("BaseGuidelinesGrok", "StructureTemplateResponsible", call_grok),
        }

        prompt_template = get_file_content_from_drive(drive_service, GUIDELINES_FOLDER_ID, "PromptTemplate")
        if not prompt_template:
            return

        out = [f"{casino} review\n"]
        for sec, content in secs.items():
            guidelines_file, structure_file, fn = section_configs[sec]
            guidelines = get_file_content_from_drive(drive_service, GUIDELINES_FOLDER_ID, guidelines_file)
            structure = get_file_content_from_drive(drive_service, GUIDELINES_FOLDER_ID, structure_file)
            if not guidelines or not structure:
                continue
            prompt = prompt_template.format(
                casino=casino,
                section=sec,
                guidelines=guidelines,
                structure=structure,
                main=content["main"],
                top=content["top"],
                sim=content["sim"],
                btc_value=btc_str
            )
            review = fn(prompt)
            out.append(f"{sec}\n{review}\n")

        doc_title = f"{casino} Review"
        existing_doc_id = find_existing_doc(drive_service, FOLDER_ID, doc_title)
        if existing_doc_id:
            drive_service.files().delete(fileId=existing_doc_id).execute()

        doc_id = create_google_doc_in_folder(docs_service, drive_service, FOLDER_ID, doc_title, "\n".join(out))
        doc_url = f"https://docs.google.com/document/d/{doc_id}"
        write_review_link_to_sheet(doc_url)

    except Exception as e:
        print("Error:", e)

if __name__ == "__main__":
    main()
