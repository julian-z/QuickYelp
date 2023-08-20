# shell.py - Julian Zulfikar
# --------------------------------------
# Shell implementation of the program.

import requests
from collections import defaultdict
from unidecode import unidecode
from lxml import html
from html import unescape
import asyncio
import aiohttp

import os
import re
import json
import time
from random import randint

import openai
from langchain.document_loaders import TextLoader
from langchain.chat_models import ChatOpenAI
from langchain.embeddings import OpenAIEmbeddings
from langchain.vectorstores import FAISS
from langchain.chains import RetrievalQA

openai.api_key = os.environ.get('OPENAI_API_KEY')
YELP_FUSION_KEY = os.environ.get('YELP_FUSION_KEY')

DEBUGGING = False


def clean(input_string):
    """
    Helper function to remove HTML syntax.
    """
    cleaned_string = unescape(input_string)
    tree = html.fromstring(cleaned_string)
    cleaned_string = tree.text_content()
    cleaned_string = " ".join(cleaned_string.split())
    return cleaned_string


def convert_yelp_dollar_signs(rating: str) -> str:
    """
    Translate Yelp price range from dollar signs.
    """
    if len(rating) == 1:
        return "Under 10 dollars. Yelp rates this price range as 1 dollar sign out of 4."
    elif len(rating) == 2:
        return "Between 11 to 30 dollars. Yelp rates this price range as 2 dollar signs out of 4."
    elif len(rating) == 3:
        return "Between 31 to 60 dollars. Yelp rates this price range as 3 dollar signs out of 4."
    elif len(rating) == 4:
        return "Above 61 dollars. Yelp rates this price range as 4 dollar signs, the priciest it can be."
    else:
        return "No price range provided"


async def fetch_url(session, url):
    """
    Fetch url asynchronously.
    """
    print("REQUESTING", url)
    
    async with session.get(url) as response:
        if response.status == 200:
            data = await response.text()
            print("RECEIVED", url)
        else:
            print("ERROR -- STATUS CODE:", response.status)
            data = f"! ERROR REQUESTING {url} !"
    
    # Decrease request rate
    await asyncio.sleep(5)
    return data


async def request_review_urls(review_urls):
    """
    Run multiple requests concurrently.
    """
    async with aiohttp.ClientSession() as session:
        tasks = []
        for url in review_urls:
            task = asyncio.create_task(fetch_url(session, url))
            tasks.append(task)
        return await asyncio.gather(*tasks)


def scrape_yelp_page(base_url: str, num_pages: int, web_app: bool = False):
    """
    Scrapes the first "num_pages" review pages of a Yelp URL and stores into a JSON object.
        Resulting JSON object is written into business_data.txt
    """
    # Construct URLs to first 5 review pages
    def _generate_review_url(base_url, start_value):
        return base_url + f'&start={start_value}' if '?' in base_url else base_url + f'?start={start_value}'
    review_urls = [base_url]+[_generate_review_url(base_url, start_value) for start_value in range(10, num_pages*10, 10)]
    
    # Replace review_urls with response objects
    review_responses = asyncio.run(request_review_urls(review_urls))
    print("RESPONSES RECEIVED, PARSING DATA")

    # Store information in business_data
    business_data = {
        "name": None, 
        "history": None,
        "specialties": None,
        "location": None,
        "phone": None,
        "categories": None,
        "overall_rating": None,
        "price_range": None,
        "hours": None,
        "is_open_now": None,
        "transactions": None,
        "reviews": defaultdict(list)
    }

    # Scrape reviews and retrieve business information
    for i, response in enumerate(review_responses):

        print(f"PARSING PAGE {i+1}:", review_urls[i])
        if response[:7] == "! ERROR":
            print("ERROR PARSING THIS PAGE")
        else:
            try:
                # Get source code
                source_code = unidecode(response)
                if not web_app:
                    with open("source_code.txt", 'w') as f:
                        f.write(source_code)

                # DEBUGGING PURPOSES: Use static source_code
                # source_code = ""
                # with open("source_code.txt", 'r') as f:
                #     source_code = f.read()
                
                # Try to extract JSON object
                start = source_code.index('<!--{"locale"')
                end = source_code.index('}}-->', start)
                yelp_json_str = unidecode(source_code[start+4:end]+'}}')
                if not web_app:
                    with open("json_obj.txt", 'w') as f:
                        f.write(yelp_json_str)

                yelp_json = None
                try:
                    yelp_json = json.loads(yelp_json_str)
                except Exception as e:
                    print("ERROR EXTRACTING JSON:", e)
                    raise e

                # Try to extract business information
                if not business_data["name"]:
                    name = None
                    try:
                        name = yelp_json["legacyProps"]["bizDetailsProps"]["bizDetailsPageProps"]["fromTheBusinessProps"]["fromTheBusinessContentProps"]["businessName"]
                    except Exception as e:
                        print("ERROR GETTING NAME:", e)
                    business_data["name"] = name

                if not business_data["history"]:
                    history = None
                    try:
                        history = yelp_json["legacyProps"]["bizDetailsProps"]["bizDetailsPageProps"]["fromTheBusinessProps"]["fromTheBusinessContentProps"]["historyText"]
                    except Exception as e:
                        print("ERROR GETTING HISTORY:", e)
                    business_data["history"] = history

                if not business_data["specialties"]:
                    specialties = None
                    try:
                        specialties = yelp_json["legacyProps"]["bizDetailsProps"]["bizDetailsPageProps"]["fromTheBusinessProps"]["fromTheBusinessContentProps"]["specialtiesText"] 
                    except Exception as e:
                        print("ERROR GETTING SPECIALTIES:", e)
                    business_data["specialties"] = specialties
                
                if not business_data["location"]:
                    location = None
                    try:
                        start = source_code.index("streetAddress")
                        end = source_code.index("}", start)
                        location = '{"'+source_code[start:end+1]

                        try:
                            location_as_dict = json.loads(location)
                            location = location_as_dict
                        except Exception as e:
                            print("ERROR CONVERTING LOCATION TO DICT", e, location)
                            business_data["location"] = location

                    except Exception as e:
                        print("ERROR GETTING LOCATION:", e)
                    business_data["location"] = location

                # Try to extract reviews
                try:
                    errors = 0

                    for i in range(10):
                        try:
                            rating = yelp_json["legacyProps"]["bizDetailsProps"]["bizDetailsPageProps"]["reviewFeedQueryProps"]["reviews"][i]["rating"]
                            comment = yelp_json["legacyProps"]["bizDetailsProps"]["bizDetailsPageProps"]["reviewFeedQueryProps"]["reviews"][i]["comment"]["text"]
                            business_data["reviews"][str(rating)].append(clean(comment))
                        except Exception as e:
                            print(f"ERROR RETRIEVING REVIEW #{i}:", e)
                            errors += 1
                    
                    # If 10 errors happened, there are no more reviews
                    if errors == 10:
                        break

                except Exception as e:
                    print("ERROR RETRIEVING REVIEWS:", e)

            except Exception as e:
                print("ERROR:", e)
                raise e

    print("CALLING YELP FUSION API TO MATCH BUSINESS")
    # Try to call to Yelp Fusion API: Business Match
    # https://docs.developer.yelp.com/reference/v3_business_match
    yelp_fusion_api_business_match = None

    # If the name was not provided by the business, use the URL to do a Business Match
    if not business_data["name"]:
        cur = base_url.index("/biz/")+5
        business_data["name"] = ""
        while cur < len(base_url):
            if base_url[cur] not in {'/', '?'}:
                business_data["name"] += base_url[cur]
                cur += 1
            else:
                break

    # Perform Business Match using location
    if business_data["name"] and type(business_data["location"]) == dict:
        try:
            yf_url = f"https://api.yelp.com/v3/businesses/matches?name={business_data['name']}&address1={business_data['location']['streetAddress']}" + \
            f"&city={business_data['location']['addressLocality']}&state={business_data['location']['addressRegion']}&country={business_data['location']['addressCountry']}" + \
            f"&limit=1&match_threshold=default"
            api_call = requests.get(yf_url, headers={"Authorization": "Bearer "+YELP_FUSION_KEY})

            if api_call.status_code == 200:
                yelp_fusion_api_business_match = api_call.json()
            else:
                print("API (1) STATUS CODE", api_call.status_code)
        except Exception as e:
            print("ERROR CALLING FUSION (1):", e)
    else:
        print("NO FUSION CALL:", business_data["name"], business_data["location"])

    print("CALLING YELP FUSION API FOR BUSINESS DETAILS")
    # Try to call Yelp Fusion API: Business Details
    # https://docs.developer.yelp.com/reference/v3_business_info
    yelp_fusion_api_business_details = None
    if yelp_fusion_api_business_match:
        try:
            yf_url = f"https://api.yelp.com/v3/businesses/{yelp_fusion_api_business_match['businesses'][0]['id']}"
            api_call = requests.get(yf_url, headers={"Authorization": "Bearer "+YELP_FUSION_KEY})

            if api_call.status_code == 200:
                yelp_fusion_api_business_details = api_call.json()
            else:
                print("API (2) STATUS CODE", api_call.status_code)
        except Exception as e:
            print("ERROR CALLING FUSION (2):", e)

    # Store API data into business_details
    if yelp_fusion_api_business_details:
        try: business_data["name"] = yelp_fusion_api_business_details["name"]
        except Exception as e: print("ERROR GETTING NAME FROM API", e)
        try: business_data["phone"] = yelp_fusion_api_business_details["display_phone"]
        except Exception as e: print("ERROR GETTING PHONE FROM API", e)
        try: business_data["categories"] = [data["title"] for data in yelp_fusion_api_business_details["categories"]]
        except Exception as e: print("ERROR GETTING CATEGORIES FROM API", e)
        try: business_data["overall_rating"] = yelp_fusion_api_business_details["rating"]
        except Exception as e: print("ERROR GETTING RATING FROM API", e)
        try: business_data["price_range"] = convert_yelp_dollar_signs(yelp_fusion_api_business_details["price"])
        except Exception as e: print("ERROR GETTING PRICING FROM API", e)
        try: business_data["hours"] = yelp_fusion_api_business_details["hours"]
        except Exception as e: print("ERROR GETTING HOURS FROM API", e)
        try: business_data["is_open_now"] = yelp_fusion_api_business_details["hours"][0]["is_open_now"]
        except Exception as e: print("ERROR GETTING OPEN STATUS FROM API", e)
        try: business_data["transactions"] = yelp_fusion_api_business_details["transactions"]
        except Exception as e: print("ERROR GETTING TRANSACTIONS FROM API", e)

    # Dump business_data JSON object
    if not web_app:
        with open("business_data.txt", 'w') as f:
            json.dump(business_data, f)
    
    return business_data


def format_business_data(business_data: dict, web_app: bool = False) -> str:
    """
    Formats business_data into a readable text file for training LangChain/ChatGPT.
    """
    # Provide context for chatbot
    bg_context = "You are QuickYelp, a chatbot which is able to answer questions about a given Yelp business. \n"+ \
        "The content provided is the background context/information of the business/restaurant that can be found on the Yelp page. \n"+ \
        "Beware: some content is formatted in JSON format.\n\n"
    reviews = "You are QuickYelp, a chatbot which is able to answer questions about a given Yelp business. \n"+ \
        "The content provided is the reviews of the business/restaurant from the experience of Yelp users who have visited the service.\n" + \
        "Think of ratings from 4-5 stars as positive, and 1-3 stars as negative.\n\n"

    sections = ["name", "history", "specialties", "location", "phone", "categories",
                "overall_rating", "price_range" , "hours", "transactions"]
    special = {"specialties", "categories"}
    bg_context += "You are provided the following information about the business:\n"

    # Format business_data sections
    for section in sections:
        if section in special:
            content = f"The {section} are"
        elif section == "price_range":
            content = "The price range in dollars/Yelp dollar signs of their items/menu is"
        elif section == "overall_rating":
            content = "The overall rating of the business calculated by Yelp reviews is"
        elif section == "history":
            content = "The background history/origin of the business is"
        elif section == "name":
            content = "The name/title of the business is"
        elif section == "location":
            content = "The business location (address, city, state, country) is listed as"
        elif section == "hours":
            content = "The hours of operation are"
        elif section == "transactions":
            content = "The transaction methods the business offers are"
        elif section == "phone":
            content = "The contact/phone number is"
        else:
            content = f"The {section} is"

        if business_data[section]:
            if section == "hours":
                content += f": {business_data[section]} (formatted in JSON)."
                if business_data["is_open_now"]:
                    content += "The business is open right now."
                else:
                    content += "The business is not open right now."
            else:
                content += f": \"{business_data[section]}\"."
        else:
            content += f" not provided by the business."
        
        bg_context += content+'\n'
    bg_context += '\n\n'

    # Format reviews
    if len(business_data["reviews"]):
        review_count = 1
        for rating in ['5', '4', '3', '2', '1']:
            if rating in business_data["reviews"].keys():
                content = ""
                for review in business_data['reviews'][rating]:
                    content += f'{rating} Stars ({"Positive" if int(rating) > 3 else "Negative"}) - Review {review_count}: {review}\n'
                    review_count += 1
                reviews += content
    else:
        reviews += "The reviews are not provided at all. This is a MAJOR error!"

    # Write into files
    if not web_app:
        with open("business_information.txt", 'w') as f:
            f.write(unidecode(bg_context))
        with open("business_reviews.txt", 'w') as f:
            f.write(unidecode(reviews))
    else:
        return bg_context, reviews


def validate_url(url):
    """
    Helper function to validate Yelp URL. Accepts mobile, yelp.to, and desktop links.
    """
    return re.match(r'^https?://(?:www\.)?yelp\.com/biz/[\w-]+(?:-\w+)?(?:\?[\w=&-]*)?$', url) or \
        re.match(r'^https://m\.yelp\.com/biz/[\w-]+(?:-\w+)?(?:\?.*)?$', url) or \
        re.match(r'^https://yelp\.to/[a-zA-Z0-9]+$', url)


if __name__ == "__main__":
    """
    DEBUGGING PURPOSES: Test links
    https://www.yelp.com/biz/nick-the-greek-elk-grove-elk-grove
    https://www.yelp.com/biz/wingstop-opening-soon-sacramento
    https://www.yelp.com/biz/kikis-chicken-place-sacramento-15?page_src=related_bizes
    https://m.yelp.com/biz/world-wrapps-san-ramon?primary_source=biz_details&secondary_source=nav_bar&share_id=4C78CAD6-084F-41A2-A4CE-D42CCE3A0133&uid=q-o2wstFFth7bN91gMDSkA&utm_source=ishare
    https://yelp.to/gMUOLofNOg
    """
    if not DEBUGGING:
        print('-'*100)
        print("QuickYelp - AI Yelp Review ChatBot")
        print("Developed by Julian Zulfikar, 2023\n")
        print("Questions or persisting issues? E-mail: jzulfika@uci.edu")
        print('-'*100)

        ai_replies_1 = [
            "Oops! It seems like the Yelp URL you entered is not valid. Please try again.",
            "Sorry, but the Yelp URL you provided is incorrect or unsupported. Please double-check and retry.",
            "Uh-oh! The Yelp URL you entered doesn't seem to work. Please provide a valid URL and try again.",
            "We encountered an issue with the Yelp URL you provided. Please make sure it's correct and retry.",
            "Hmmm... It appears the Yelp URL you entered is not valid. Kindly check it and try once more."
        ]
        while True:
            base_url = input("URL: ")
            if validate_url(base_url):
                break
            else:
                print(ai_replies_1[randint(0, 4)])
        print('-'*100)

        ai_replies_2 = [
            "Oops! The input should be a whole number (e.g., 1, 2, ...).",
            "Oh no! Please provide only a whole number (e.g., 7, 3, ...).",
            "My apologies! Only integers (e.g., 1, 2, ...) are allowed for this input.",
            "Uh-oh! You can only enter whole numbers (e.g., 4, 5, ...).",
            "Woopsie! The value should be an integer (e.g., 3, 8, ...)."
        ]
        ai_replies_3 = [
            "My apologies! The integer should fall within the range of 0 to 5 (inclusive).",
            "Oops! Please provide an integer between 0 and 5 (inclusive).",
            "Oh no! The number must be between 0 and 5 (inclusive) to proceed.",
            "Woopsie! The value should be an integer from 0 to 5 (inclusive).",
            "Uh-oh! Please enter an integer between 0 and 5 (inclusive)."
        ]
        while True:
            num_pages = input("Number of review pages to scrape (Max 5): ")

            try:
                num_pages = int(num_pages)
            except:
                print(ai_replies_2[randint(0, 4)])
                continue

            if not (0 <= num_pages <= 5):
                print(ai_replies_3[randint(0, 4)])
                continue
            else:
                break
        print('-'*100)

        # Scrape website
        print("Scraping reviews...")
        start = time.perf_counter()
        business_data = scrape_yelp_page(base_url, num_pages)
        end = time.perf_counter()
        print(f"Done scraping! Elapsed time: {end-start:.2f} seconds")
        print('-'*100)
    
    else:
        # DEBUGGING PURPOSES: Load business_data.txt
        with open("business_data.txt", 'r') as f:
            business_data = json.loads(f.read())

    print("Business Information:")
    print("Name:", business_data["name"])
    print('~ '*50)
    print("History:", business_data["history"])
    print('~ '*50)
    print("Specialties:", business_data["specialties"])
    print('~ '*50)
    print("Location:", business_data["location"])
    print('-' * 100)
    for stars, comments in sorted(business_data["reviews"].items()):
        print("RATING:", stars)
        for i, c in enumerate(comments):
            print(f"{i+1}:", c)
        print('-' * 100)
    
    # Format business_data
    format_business_data(business_data)
    with open("business_information.txt", 'r') as f:
        business_information = f.read()
    with open("business_reviews.txt", 'r') as f:
        business_reviews = f.read()

    # Create FAISS database
    info_loader = TextLoader("business_information.txt")
    review_loader = TextLoader("business_reviews.txt")
    info_docs = info_loader.load_and_split()
    review_docs = review_loader.load_and_split()
    info_db = FAISS.from_documents(info_docs, embedding=OpenAIEmbeddings())
    review_db = FAISS.from_documents(review_docs, embedding=OpenAIEmbeddings())

    # Initiate ChatBot
    while True:
        query = input("Ask a question about the business (Q to quit): ")
        if query == 'Q': break

        # Query using LangChain's RetrievalQA
        start = time.perf_counter()
        info_qa = RetrievalQA.from_chain_type(llm=ChatOpenAI(temperature=0.5), chain_type="stuff", retriever=info_db.as_retriever())
        review_qa = RetrievalQA.from_chain_type(llm=ChatOpenAI(temperature=0.5), chain_type="stuff", retriever=review_db.as_retriever())
        end = time.perf_counter()
        print("Elapsed time to load db: ", end-start)
        start = time.perf_counter()
        res_1 = info_qa.run(query)
        res_2 = review_qa.run(query)
        merge_request = {
            "role": "system", 
                 "content": f"Please merge these two chatbot replies to answer the query: {query}\n\n" + \
                        f"Reply 1 (Based on Yelp's business information): {res_1}\n\n" + \
                        f"Reply 2 (Based on Yelp reviews): {res_2}\n\n" + \
                        "If either reply says they do not know the answer, please disregard it.\n" + \
                        "If both replies do not know the answer, please say either message."
        }
        llm = openai.ChatCompletion.create(
            model="gpt-3.5-turbo", 
            temperature=0.5, 
            messages=[merge_request]
        )
        res = llm.choices[0].message.content
        end = time.perf_counter()
        print("Elapsed time to query: ", end-start)
        
        print(res)
        print('-'*100)

