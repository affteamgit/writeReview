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
    "https://www.googleapis.com/auth/spreadsheets.readonly",
    "https://www.googleapis.com/auth/documents",
    "https://www.googleapis.com/auth/drive"
]

DOCS_DRIVE_SCOPES = ["https://www.googleapis.com/auth/documents", "https://www.googleapis.com/auth/drive"]

def get_service_account_credentials():
    return Credentials.from_service_account_info(st.secrets["service_account"], scopes=SCOPES)

def get_file_content_from_drive(drive_service, folder_id, filename):
    """Get content of a file from Google Drive folder."""
    try:
        # Search for the file in the specified folder
        query = f"name = '{filename}' and '{folder_id}' in parents and trashed = false"
        results = drive_service.files().list(q=query, spaces='drive', fields='files(id, name, mimeType)').execute()
        files = results.get('files', [])
        
        if not files:
            raise Exception(f"File {filename} not found in folder")
            
        file_id = files[0]['id']
        mime_type = files[0]['mimeType']
        
        # Check if it's a Google Docs file
        if mime_type in ['application/vnd.google-apps.document', 'application/vnd.google-apps.spreadsheet']:
            # Export as plain text
            content = drive_service.files().export(
                fileId=file_id,
                mimeType='text/plain'
            ).execute()
            return content.decode('utf-8')
        else:
            # Download regular file
            content = drive_service.files().get_media(fileId=file_id).execute()
            return content.decode('utf-8')
            
    except Exception as e:
        print(f"Error reading file {filename}: {str(e)}")
        return None

# GET SHEET
def get_selected_casino_data():
    creds = get_service_account_credentials()
    sheets = build("sheets", "v4", credentials=creds)
    casino = sheets.spreadsheets().values().get(spreadsheetId=SPREADSHEET_ID, range=f"{SHEET_NAME}!B1").execute().get("values", [[""]])[0][0].strip()
    rows = sheets.spreadsheets().values().get(spreadsheetId=SPREADSHEET_ID, range=f"{SHEET_NAME}!B2:O").execute().get("values", [])
    sections = {
        "General": (2, 3, 4),
        "Payments": (5, 6, 7),
        "Games": (8, 9, 10),
        "Responsible Gambling": (11, 12, 13),
    }
    data = {}
    for sec, (mi, ti, si) in sections.items():
        main = "\n".join(r[mi] for r in rows if len(r) > mi and r[mi].strip())
        top = "\n".join(r[ti] for r in rows if len(r) > ti and r[ti].strip())
        sim = "\n".join(r[si] for r in rows if len(r) > si and r[si].strip())
        data[sec] = {"main": main or "[No data provided]", "top": top or "[No top comparison available]", "sim": sim or "[No similar comparison available]"}
    return casino, data

# AI CLIENTS
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
    return anthropic.messages.create(model="claude-opus-4-20250514", max_tokens=800, temperature=0.5, messages=[{"role": "user", "content": prompt}]).content[0].text.strip()

def write_review_link_to_sheet(link):
    """Write the review link to cell B7 in the spreadsheet."""
    creds = get_service_account_credentials()
    sheets = build("sheets", "v4", credentials=creds)
    body = {"values": [[link]]}
    sheets.spreadsheets().values().update(
        spreadsheetId=SPREADSHEET_ID, 
        range=f"{SHEET_NAME}!B7", 
        valueInputOption="RAW", 
        body=body
    ).execute()

# FORMATTED INSERTION (CLEAN)
def insert_parsed_text_with_formatting(docs_service, doc_id, review_text):
    import re

    # Parse the text into clean text and extract formatting positions
    plain_text = ""
    formatting_requests = []
    cursor = 1  # Google Docs uses 1-based index after the title

    pattern = r'(\*\*(.*?)\*\*|\[([^\]]+?)\]\((https?://[^\)]+)\))'
    last_end = 0

    for match in re.finditer(pattern, review_text):
        start, end = match.span()
        before_text = review_text[last_end:start]
        plain_text += before_text
        cursor_start = cursor + len(before_text)

        if match.group(2):  # Bold (**text**)
            bold_text = match.group(2)
            plain_text += bold_text
            formatting_requests.append({
                "updateTextStyle": {
                    "range": {"startIndex": cursor_start, "endIndex": cursor_start + len(bold_text)},
                    "textStyle": {"bold": True},
                    "fields": "bold"
                }
            })
            cursor += len(before_text) + len(bold_text)

        elif match.group(3) and match.group(4):  # Link [text](url)
            link_text = match.group(3)
            url = match.group(4)
            plain_text += link_text
            formatting_requests.append({
                "updateTextStyle": {
                    "range": {"startIndex": cursor_start, "endIndex": cursor_start + len(link_text)},
                    "textStyle": {"link": {"url": url}},
                    "fields": "link"
                }
            })
            cursor += len(before_text) + len(link_text)

        last_end = end

    remaining_text = review_text[last_end:]
    plain_text += remaining_text

    # Insert clean plain text
    docs_service.documents().batchUpdate(
        documentId=doc_id,
        body={"requests": [{"insertText": {"location": {"index": 1}, "text": plain_text}}]}
    ).execute()

    title_line = plain_text.split('\n', 1)[0]
    title_start = 1
    title_end = title_start + len(title_line)

    formatting_requests.insert(0, {
        "updateParagraphStyle": {
            "range": {"startIndex": title_start, "endIndex": title_end},
            "paragraphStyle": {"namedStyleType": "TITLE"},
            "fields": "namedStyleType"
        }
    })

    # Apply inline bold & links
    if formatting_requests:
        docs_service.documents().batchUpdate(
            documentId=doc_id,
            body={"requests": formatting_requests}
        ).execute()

    doc = docs_service.documents().get(documentId=doc_id).execute()
    header_requests = []
    bullet_requests = []

    section_titles = ["General", "Payments", "Games", "Responsible Gambling"]
    rg_start = None
    rg_end = None

    content = doc.get('body', {}).get('content', [])

    # Identify Responsible Gambling section range
    for idx, element in enumerate(content):
        if 'paragraph' in element:
            paragraph = element['paragraph']
            paragraph_text = ''.join(
                elem['textRun']['content']
                for elem in paragraph.get('elements', [])
                if 'textRun' in elem
            ).strip()

            start_index = element.get('startIndex')
            end_index = element.get('endIndex')

            if paragraph_text in section_titles:
                if paragraph_text == "Responsible Gambling":
                    rg_start = end_index
                elif rg_start and not rg_end:
                    rg_end = start_index

                if start_index is not None and end_index is not None:
                    header_requests.append({
                        "updateTextStyle": {
                            "range": {"startIndex": start_index, "endIndex": end_index - 1},
                            "textStyle": {"bold": True, "fontSize": {"magnitude": 16, "unit": "PT"}},
                            "fields": "bold,fontSize"
                        }
                    })

    # Look for "- " lines in Responsible Gambling and convert to bullets
    for element in content:
        if 'paragraph' not in element:
            continue
        start_index = element.get('startIndex')
        end_index = element.get('endIndex')
        if not start_index or not end_index:
            continue

        # Must be within Responsible Gambling section
        if rg_start and rg_end and not (rg_start < start_index < rg_end):
            continue

        paragraph_text = ''.join(
            e['textRun']['content']
            for e in element['paragraph']['elements']
            if 'textRun' in e
        ).strip()

        if paragraph_text.startswith("- "):
            bullet_requests.append({
                "createParagraphBullets": {
                    "range": {"startIndex": start_index, "endIndex": end_index - 1},
                    "bulletPreset": "BULLET_DISC"
                }
            })

    if header_requests:
        docs_service.documents().batchUpdate(
            documentId=doc_id,
            body={"requests": header_requests}
        ).execute()

    if bullet_requests:
        docs_service.documents().batchUpdate(
            documentId=doc_id,
            body={"requests": bullet_requests}
        ).execute()

# CREATE DOC + FORMATTING
def create_google_doc_in_folder(docs_service, drive_service, folder_id, doc_title, review_text):
    doc_id = docs_service.documents().create(body={"title": doc_title}).execute()["documentId"]
    insert_parsed_text_with_formatting(docs_service, doc_id, review_text)

    file = drive_service.files().get(fileId=doc_id, fields="parents").execute()
    previous_parents = ",".join(file.get('parents', []))
    drive_service.files().update(fileId=doc_id, addParents=folder_id, removeParents=previous_parents, fields="id, parents").execute()
    return doc_id

def find_existing_doc(drive_service, folder_id, title):
    query = f"name='{title}' and '{folder_id}' in parents and trashed=false"
    results = drive_service.files().list(q=query, fields="files(id, name)").execute()
    files = results.get("files", [])
    return files[0]["id"] if files else None

# MAIN
def main():
    st.set_page_config(page_title="Review Generator", layout="centered", initial_sidebar_state="collapsed")
    
    # Initialize session state
    if 'review_completed' not in st.session_state:
        st.session_state.review_completed = False
        st.session_state.review_url = None
        st.session_state.casino_name = None
    
    # If review is already completed, show the success message
    if st.session_state.review_completed:
        st.success("Review successfully written, check the sheet :)")
        if st.session_state.review_url:
            st.info(f"Review link: {st.session_state.review_url}")
        
        # Add a button to generate a new review
        if st.button("Write Review", type="primary"):
            st.session_state.review_completed = False
            st.session_state.review_url = None
            st.session_state.casino_name = None
            st.rerun()
        return
    
    # Get casino name first to show in the interface
    try:
        user_creds = get_service_account_credentials()
        casino, _ = get_selected_casino_data()
        st.session_state.casino_name = casino
    except Exception as e:
        st.error(f"❌ Error loading casino data: {e}")
        return
    
    # Show casino name and generate button
    st.markdown(f"## Ready to write a review for: **{casino}**")
    st.markdown("Click the button below to write the review.")
    
    # Only generate review when button is clicked
    if st.button("Write Review", type="primary", use_container_width=True):
        # Show progress message
        progress_placeholder = st.empty()
        progress_placeholder.markdown("## Writing review, please wait...")
        
        try:
            docs_service = build("docs", "v1", credentials=user_creds)
            drive_service = build("drive", "v3", credentials=user_creds)

            price = requests.get("https://pro-api.coinmarketcap.com/v1/cryptocurrency/quotes/latest", headers={"Accepts": "application/json", "X-CMC_PRO_API_KEY": COINMARKETCAP_API_KEY}, params={"symbol": "BTC", "convert": "USD"}).json().get("data", {}).get("BTC", {}).get("quote", {}).get("USD", {}).get("price")
            btc_str = f"1 BTC = ${price:,.2f}" if price else "[BTC price unavailable]"

            casino, secs = get_selected_casino_data()
            
            # Define section configurations
            section_configs = {
                "General": ("BaseGuidelinesClaude", "StructureTemplateGeneral", call_claude),
                "Payments": ("BaseGuidelinesClaude", "StructureTemplatePayments", call_claude),
                "Games": ("BaseGuidelinesClaude", "StructureTemplateGames", call_claude),
                "Responsible Gambling": ("BaseGuidelinesGrok", "StructureTemplateResponsible", call_grok),
            }

            # Get the prompt template from Google Drive
            prompt_template = get_file_content_from_drive(drive_service, GUIDELINES_FOLDER_ID, "PromptTemplate")
            if not prompt_template:
                st.error("Error: Could not fetch prompt template from Google Drive")
                return

            out = [f"{casino} review\n"]
            for sec, content in secs.items():
                guidelines_file, structure_file, fn = section_configs[sec]
                
                # Get guidelines and structure from Google Drive
                guidelines = get_file_content_from_drive(drive_service, GUIDELINES_FOLDER_ID, guidelines_file)
                structure = get_file_content_from_drive(drive_service, GUIDELINES_FOLDER_ID, structure_file)
                
                if not guidelines or not structure:
                    st.error(f"Error: Could not fetch required files for section {sec}")
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
                # Delete the old document
                drive_service.files().delete(fileId=existing_doc_id).execute()

            doc_id = create_google_doc_in_folder(docs_service, drive_service, FOLDER_ID, f"{casino} Review", "\n".join(out))
            doc_url = f"https://docs.google.com/document/d/{doc_id}"
            
            # Write the review link to the spreadsheet
            write_review_link_to_sheet(doc_url)
            
            # Mark review as completed and store the URL
            st.session_state.review_completed = True
            st.session_state.review_url = doc_url
            
            # Clear progress message and show success
            progress_placeholder.empty()
            st.rerun()

        except Exception as e:
            progress_placeholder.empty()
            st.error(f"❌ An error occurred: {e}")
    

if __name__ == "__main__":
    main()
