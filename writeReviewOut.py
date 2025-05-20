import os
import openai
import requests
import json
from google.oauth2.service_account import Credentials
from google.oauth2 import service_account
from googleapiclient.discovery import build
from anthropic import Anthropic
from pathlib import Path
import re
import streamlit as st

OPENAI_API_KEY = st.secrets["OPENAI_API_KEY"]
GROK_API_KEY = st.secrets["GROK_API_KEY"]
ANTHROPIC_API_KEY = st.secrets["ANTHROPIC_API_KEY"]
COINMARKETCAP_API_KEY = st.secrets["COINMARKETCAP_API_KEY"]

SPREADSHEET_ID = st.secrets["SPREADSHEET_ID"]
SHEET_NAME = st.secrets["SHEET_NAME"]
FOLDER_ID = st.secrets["FOLDER_ID"]

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets.readonly",
    "https://www.googleapis.com/auth/documents",
    "https://www.googleapis.com/auth/drive"
]

DOCS_DRIVE_SCOPES = ["https://www.googleapis.com/auth/documents", "https://www.googleapis.com/auth/drive"]


service_account_info = json.loads(
    base64.b64decode(st.secrets["service_account"]).decode("utf-8")
)
credentials_info = json.loads(
    base64.b64decode(st.secrets["credentials"]).decode("utf-8")

def get_service_account_credentials():
    return service_account.Credentials.from_service_account_info(
        service_account_info,
        scopes=SCOPES
    )

# Guidelines
GPT_GUIDELINES = """
- Keep each paragraph under 40 words.
- Use a conversational tone, as if explaining to a friend.
- Focus on clarity and avoid vague statements.
- Wherever you mention number of accepted cryptocurrencies, withdrawal limits, withdrawal processing time, KYC verification time, bold the feature or phrase using Google Docs formatting (**bold**). Only bold the features - not the whole sentence.
- Use real comparisons to other casinos from Top or Similar Casinos to explain good or bad features.
- When comparing to other casinos, always start the sentence with "In comparison" or "For example", so that it is clear that the reviewed casino is being compared to another casino; always accompany comparisons with values for the compared casino from Top and Similar Casinos columns.
- Include one judgment or takeaway per paragraph.
- Use active voice. Write in first person (“I”), and address the reader as “you.”
- Always highlight how a feature benefits or affects the reader ("you").
- Instead of "players" or "users", use "you" - For example, instead of "This feature benefits players" use "This feature benefits you".
- Do not address the reader at the beginning of the paragraphs.
- When comparing casino information to a criteria, never mention the criteria itself.
- Wherever you mention a brand name in comparison, add an internal link next to the compared casino (the links are provided next to Top and Similar casino names).
- Occasionally, when the reviewed casino is doing something right, give it a compliment in this fassion: "Props to (casinoname) for...", "I like this about (casinoname)..." (do not be repetitive).
- Never use Em dash ("—").
- Only mention broken images and links or annoying pop-ups IF the casino has them. If the casino does not have them, do not mention anything about broken images or links or annoying pop-ups. This is because we do not want to mention negative features where there are none.
- ALWAYS wrap the phrase to be bolded using **double asterisks**.
- ALWAYS insert links using [Text](https://example.com) format.
- Never use raw links like [https://example.com].
- If you are comparing casinos, always mention the name as [CasinoName](https://link).
- Never write only the link without wrapping it.
"""

GROK_GUIDELINES = """
- Be professional when writing and go straight to the point. Do not use vague words or phrases you would not use in an office. Max 40 words per paragraph.
- Talk like you’ve played there — real opinions, real tone.
- If something sucks, say it. If it shines, brag about it.
- Wherever you mention self-exclusion, additional responsible gambling tools, cooling-off option, without or with contacting support, bold the feature or phrase using Google Docs formatting (**bold**). Only bold the features - not the whole sentence.
- No fake politeness. You’re here to help the reader avoid garbage.
- Compare it to the Top and Similar Casinos.
- When comparing to other casinos, always start the sentence with "In comparison" or "For example", so that it is clear that the reviewed casino is being compared to another casino; always accompany comparisons with values for the compared casino from Top and Similar Casinos columns.
- Talk to the reader like they’re your skeptical friend.
- Use “I” and “you” — make it personal, and make it count.
- Instead of "players" or "users", use "you" - For example, instead of "This feature benefits players" use "This feature benefits you".
- Do not address the reader at the beginning of the paragraphs.
- Do not disclose your emotions about the casino features.
- When comparing casino information to a criteria, never mention the criteria itself.
- Wherever you mention a brand name in comparison, add an internal link next to the compared casino (the links are provided next to Top and Similar casino names).
- Never use Em dash ("—").
- Occasionally, when the reviewed casino is doing something right, give it a compliment in this fassion: "I’ve got to hand it to (casinoname)...", "Hats off to (casinoname)...", "I really like this about (casinoname)..." (do not be repetitive).
- Only mention broken images and links or annoying pop-ups IF the casino has them. If the casino does not have them, do not mention anything about broken images or links or annoying pop-ups. This is because we do not want to mention negative features where there are none.
- ALWAYS wrap the phrase to be bolded using **double asterisks**.
- ALWAYS insert links using [Text](https://example.com) format.
- Never use raw links like [https://example.com].
- If you are comparing casinos, always mention the name as [CasinoName](https://link).
- Never write only the link without wrapping it.
"""

CLAUDE_GUIDELINES = """
- Write concise paragraphs, ideally under 40 words.
- Do not include heading/titles at the start of the reviews.
- Maintain a professional but conversational tone.
- ONLY When writing the review for payments and games sections, use commas for grouping numbers by thousands.
- Address both strengths and weaknesses honestly and respectfully.
- Wherever you mention vpn friendlyness, anonymous crypto casino, year of establishment, years of experience, number of restricted countries, modern website, number of accepted cryptocurrencies, withdrawal limits values (BTC or USD), withdrawal processing time, KYC verification time, number of games, number of providers, provably fair games, in-house games, game filters, additional filters, bold this feature or phrase using Google Docs formatting (**bold**). Only bold the features - not the whole sentence.
- When comparing to other casinos, always start the sentence with "In comparison" or "For example", so that it is clear that the reviewed casino is being compared to another casino; always accompany comparisons with values for the compared casino from Top and Similar Casinos columns.
- DO NOT make comparisons about KYC verification speed.
- If there are BTC values in the payments section (withdrawal limits), only have the BTC values in the review (no USD values).
- Focus on how each feature impacts the user experience or trust.
- Offer constructive insights, not just opinions.
- Use first person (“I”) for reviewer perspective, and address the reader directly (“you”).
- Instead of "players" or "users", use "you" - For example, instead of "This feature benefits players" use "This feature benefits you".
- Do not address the reader at the beginning of the paragraphs.
- When comparing casino information to a criteria, never mention the criteria itself.
- Wherever you mention a brand name in comparison, add an internal link next to the compared casino (the links are provided next to Top and Similar casino names).
- When comparing reviewed casino's number of cryptocurrencies to another casino, ALWAYS use "more than (numberOfCryptocurrencies)". For example, if you say: "(casinoname) has x cryptocurrencies, this is good, for example (casinoname) also has more than x cryptocurrencies.
- When writing the review for the payments section and you mention cryptocurrencies, always write "more than (numberofcryptocurrencies) when the (numberofcryptocurrencies) is >10, as the number of cryptocurrencies is always increasing.
- Never use Em dash ("—").
- Occasionally, when the reviewed casino is doing something right, give it a compliment in this fassion: "I’ve got to hand it to (casinoname)...", "Hats off to (casinoname)...", "I really like this about (casinoname)" (do not be repetitive).
- Only mention broken images and links or annoying pop-ups IF the casino has them. If the casino does not have them, do not mention anything about broken images or links or annoying pop-ups. This is because we do not want to mention negative features where there are none."S
- ALWAYS insert links using [Text](https://example.com) format.
- Never use raw links like [https://example.com].
- If you are comparing casinos, always mention the name as [CasinoName](https://link).
- Never write only the link without wrapping it.
"""

# STRUCTURES
STRUCTURE_GPT = json.loads(Path("structureGPT.json").read_text(encoding="utf-8"))
STRUCTURE_GROK = json.loads(Path("structureGROK.json").read_text(encoding="utf-8"))
STRUCTURE_CLAUDE = json.loads(Path("structureCLAUDE.json").read_text(encoding="utf-8"))

PROMPT_TEMPLATE = """Write a review of "{casino}" focusing on "{section}".
Follow these GUIDELINES:
{guidelines}

Use this STRUCTURE:
{structure}

Casino data:
{main}

Top Casinos comparison:
{top}

Similar Casinos comparison:
{sim}

If any BTC values appear, convert them internally to USD before comparing to other casinos, but do not mention USD in the review text. Only mention the BTC amounts.
"""

# GET SHEET
def get_selected_casino_data():
    creds = Credentials.from_service_account_info(
    credentials_info,
    scopes= SCOPES)
        
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
    return anthropic.messages.create(model="claude-3-7-sonnet-20250219", max_tokens=800, temperature=0.5, messages=[{"role": "user", "content": prompt}]).content[0].text.strip()

# FORMATTED INSERTION (CLEAN)
def insert_parsed_text_with_formatting(docs_service, doc_id, review_text):
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

    #  Insert clean plain text first
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
    section_titles = ["General", "Payments", "Games", "Responsible Gambling"]

    for element in doc.get('body', {}).get('content', []):
        if 'paragraph' in element:
            paragraph = element['paragraph']
            paragraph_text = ''.join(
                elem['textRun']['content']
                for elem in paragraph.get('elements', [])
                if 'textRun' in elem
            ).strip()

            if paragraph_text in section_titles:
                # Find the exact start and end from element indexes
                start_index = element.get('startIndex')
                end_index = element.get('endIndex')
                if start_index is not None and end_index is not None:
                    header_requests.append({
                        "updateTextStyle": {
                            "range": {"startIndex": start_index, "endIndex": end_index - 1},  # exclude trailing newline
                            "textStyle": {"bold": True, "fontSize": {"magnitude": 16, "unit": "PT"}},
                            "fields": "bold,fontSize"
                        }
                    })

    if header_requests:
        docs_service.documents().batchUpdate(
            documentId=doc_id,
            body={"requests": header_requests}
        ).execute()


# CREATE DOC + FORMATTING
def create_google_doc_in_folder(docs_service, drive_service, folder_id, doc_title, review_text):
    doc_id = docs_service.documents().create(body={"title": doc_title}).execute()["documentId"]
    insert_parsed_text_with_formatting(docs_service, doc_id, review_text)

    file = drive_service.files().get(fileId=doc_id, fields="parents").execute()
    previous_parents = ",".join(file.get('parents', []))
    drive_service.files().update(fileId=doc_id, addParents=folder_id, removeParents=previous_parents, fields="id, parents").execute()
    print(f"✅ Review Google Doc created: https://docs.google.com/document/d/{doc_id}")

# MAIN
def main():
    user_creds = get_service_account_credentials()
    docs_service = build("docs", "v1", credentials=user_creds)
    drive_service = build("drive", "v3", credentials=user_creds)

    price = requests.get("https://pro-api.coinmarketcap.com/v1/cryptocurrency/quotes/latest", headers={"Accepts": "application/json", "X-CMC_PRO_API_KEY": COINMARKETCAP_API_KEY}, params={"symbol": "BTC", "convert": "USD"}).json().get("data", {}).get("BTC", {}).get("quote", {}).get("USD", {}).get("price")
    btc_str = f"1 BTC = ${price:,.2f}" if price else "[BTC price unavailable]"

    casino, secs = get_selected_casino_data()
    ai_map = {
        "General": (CLAUDE_GUIDELINES, STRUCTURE_CLAUDE, call_claude),
        "Payments": (CLAUDE_GUIDELINES, STRUCTURE_CLAUDE, call_claude),
        "Games": (CLAUDE_GUIDELINES, STRUCTURE_CLAUDE, call_claude),
        "Responsible Gambling": (GROK_GUIDELINES, STRUCTURE_GROK, call_grok),
    }

    out = [f"{casino} review\n"]
    for sec, content in secs.items():
        guidelines, struct_map, fn = ai_map[sec]
        structure = struct_map.get(sec, "No structure defined")
        prompt = PROMPT_TEMPLATE.format(casino=casino, section=sec, guidelines=guidelines, structure=structure, main=content["main"], top=content["top"], sim=content["sim"], btc_value=btc_str)
        review = fn(prompt)
        out.append(f"{sec}\n{review}\n")

    create_google_doc_in_folder(docs_service, drive_service, FOLDER_ID, f"{casino} Review", "\n".join(out))

if __name__ == "__main__":
    main()
