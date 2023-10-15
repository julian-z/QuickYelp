# shell.py - Julian Zulfikar
# --------------------------------------
# Shell implementation of the program.

import requests
from collections import defaultdict
from unidecode import unidecode
from lxml import html
from html import unescape
import urllib.parse

import os
import re
import json
import time

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
        return "Under 10 dollars. Yelp rates this price range as 1 dollar sign out of 4"
    elif len(rating) == 2:
        return "Between 11 to 30 dollars. Yelp rates this price range as 2 dollar signs out of 4"
    elif len(rating) == 3:
        return "Between 31 to 60 dollars. Yelp rates this price range as 3 dollar signs out of 4"
    elif len(rating) == 4:
        return "Above 61 dollars. Yelp rates this price range as 4 dollar signs, the priciest it can be"
    else:
        return "No price range provided"


def retrieve_yelp_info(name: str, location: str, web_app: bool = False):
    """
    Searches for the business on Yelp via Yelp Fusion API.
        Constructs a dictionary filled with data regarding the business.
    """
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
        "url": None,
        "image_url": None,
        "reviews": defaultdict(list)
    }

    # Try to call Yelp Fusion API: Business Search
    # https://docs.developer.yelp.com/reference/v3_business_search
    print("CALLING YELP FUSION API FOR BUSINESS SEARCH")
    print("NAME:", name)
    print("LOCATION:", location)
    yelp_fusion_api_business_search = None
    try:
        yf_url = f"https://api.yelp.com/v3/businesses/search?location={urllib.parse.quote(clean(location))}&term={urllib.parse.quote(clean(name))}&sort_by=best_match&limit=1"
        api_call = requests.get(yf_url, headers={"Authorization": "Bearer "+YELP_FUSION_KEY})

        attempts = 0
        while attempts < 3:
            if api_call.status_code == 200:
                yelp_fusion_api_business_search = api_call.json()
                break
            else:
                print("API (1) STATUS CODE", api_call.status_code)
                print(api_call.json())
                attempts += 1
    except Exception as e:
        print("ERROR CALLING FUSION (1):", e)
    else:

        # If API call was valid, process data
        if yelp_fusion_api_business_search and yelp_fusion_api_business_search["businesses"]:

            # Retrieve business from API call
            business = yelp_fusion_api_business_search["businesses"][0]

            # Store data into business_data
            try: business_data["name"] = business["name"]
            except Exception as e: print("ERROR GETTING NAME FROM API", e)
            try: business_data["phone"] = business["display_phone"]
            except Exception as e: print("ERROR GETTING PHONE FROM API", e)
            try: business_data["categories"] = [data["title"] for data in business["categories"]]
            except Exception as e: print("ERROR GETTING CATEGORIES FROM API", e)
            try: business_data["overall_rating"] = business["rating"]
            except Exception as e: print("ERROR GETTING RATING FROM API", e)
            try: business_data["price_range"] = convert_yelp_dollar_signs(business["price"])
            except Exception as e: print("ERROR GETTING PRICING FROM API", e)
            try: business_data["transactions"] = business["transactions"]
            except Exception as e: print("ERROR GETTING TRANSACTIONS FROM API", e)
            try: business_data["url"] = business["url"]
            except Exception as e: print("ERROR GETTING URL FROM API", e)
            try: business_data["image_url"] = business["image_url"]
            except Exception as e: print("ERROR GETTING IMAGE URL FROM API", e)
            try: business_data["location"] = business["location"]["display_address"]
            except Exception as e: print("ERROR GETTING LOCATION FROM API", e)

            # Retrieve base URL
            try:
                base_url = business["url"]
                cur = base_url.index("/biz/")+5
                yelp_url = "https://www.yelp.com/biz/"
                while cur < len(base_url):
                    if base_url[cur] not in {'/', '?'}:
                        yelp_url += base_url[cur]
                        cur += 1
                    else:
                        break
                
                content = []
                for i, url in enumerate([yelp_url, yelp_url+"?start=10", yelp_url+"?start=20"]):
                    print("REQUESTING", url)
                    response = requests.get(url)
                    print("RECEIVED")
                    if response.status_code == 200:
                        content.append(response.text)
                    else:
                        print("ERROR -- STATUS CODE:", response.status)
                        raise Exception
                    
                    if i != 2:
                        time.sleep(1)
                business_data["url"] = yelp_url
                
            except Exception as e:
                print("ERROR SEARCH URL", e)

            else:

                # Retrieve first 30 reviews and retrieve online business information
                for response in content:
                    try:
                        # Get source code
                        source_code = unidecode(response)
                        if not web_app:
                            with open("source_code.txt", 'w') as f:
                                f.write(source_code)
                        
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

                        # Try to extract business history and specialties
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

                        # Try to extract reviews
                        for i in range(10):
                            try:
                                rating = yelp_json["legacyProps"]["bizDetailsProps"]["bizDetailsPageProps"]["reviewFeedQueryProps"]["reviews"][i]["rating"]
                                comment = yelp_json["legacyProps"]["bizDetailsProps"]["bizDetailsPageProps"]["reviewFeedQueryProps"]["reviews"][i]["comment"]["text"]
                                business_data["reviews"][str(rating)].append(clean(comment))
                            except Exception as e:
                                print(f"ERROR RETRIEVING REVIEW #{i}:", e)
                    
                    except Exception as e:
                        print("ERROR SCRAPING:", e)

        # Try to call Yelp Fusion API: Business Details
        # https://docs.developer.yelp.com/reference/v3_business_info
        print("CALLING YELP FUSION API FOR BUSINESS DETAILS")
        yelp_fusion_api_business_details = None
        try:
            yf_url = f"https://api.yelp.com/v3/businesses/{business['id']}"
            api_call = requests.get(yf_url, headers={"Authorization": "Bearer "+YELP_FUSION_KEY})

            attempts = 0
            while attempts < 3:
                if api_call.status_code == 200:
                    yelp_fusion_api_business_details = api_call.json()
                    break
                else:
                    print("API (2) STATUS CODE", api_call.status_code)
                    attempts += 1
        except Exception as e:
            print("ERROR CALLING FUSION (2):", e)
        
        # Store hours
        if yelp_fusion_api_business_details:
            try: business_data["hours"] = yelp_fusion_api_business_details["hours"]
            except Exception as e: print("ERROR GETTING HOURS FROM API", e)
            try: business_data["is_open_now"] = yelp_fusion_api_business_details["hours"][0]["is_open_now"]
            except Exception as e: print("ERROR GETTING OPEN STATUS FROM API", e)

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


def run_query(qa, query):
    """
    Perform a query on the given QA chain.
    """
    print('-'*50)
    print("QUERY:", query)
    print("CALLING QA CHAIN")
    res = qa.run(query)
    print("RECEIVED ANSWER:", res[:50]+'...')
    print('-'*50)
    return res


def merge_queries(res_1, res_2, query):
    """
    Merge the two LangChain results.
    """
    merge_request = {
        "role": "system", 
        "content": f"Merge these two chatbot replies to answer the query: {query}\n\n" + \
                   f"Reply 1: {res_1}\n\n" + \
                   f"Reply 2: {res_2}\n\n" + \
                   "If either reply says they do not know the answer, please disregard it.\n" + \
                   "If both replies do not know the answer, please say either message."
    }

    print('-'*50)
    print("CALLING OPENAI API TO MERGE")
    llm = openai.ChatCompletion.create(
        model="gpt-4", 
        temperature=0, 
        messages=[merge_request]
    )
    print("RECEIVED OPENAI MERGED MESSAGE")
    print("RESULT:", llm.choices[0].message.content[:50]+'...')
    print('-'*50)

    return llm.choices[0].message.content


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

        while True:
            name = input("Business Name: ")
            if name:
                name = unidecode(name)
                break
            else:
                print("Sorry, the name must not be blank.")
        print('-'*100)

        while True:
            location = input("Location (Can input city, state, address, etc): ")
            if 1 <= len(location) <= 250:
                location = unidecode(location)
                break
            else:
                print("Sorry, the location must be between 1 and 250 characters.")
        print('-'*100)

        # Retrieve Yelp business info
        print("Scraping reviews...")
        start = time.perf_counter()
        business_data = retrieve_yelp_info(name, location)
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
        info_qa = RetrievalQA.from_chain_type(llm=ChatOpenAI(temperature=0), chain_type="stuff", retriever=info_db.as_retriever())
        review_qa = RetrievalQA.from_chain_type(llm=ChatOpenAI(temperature=0), chain_type="stuff", retriever=review_db.as_retriever())
        end = time.perf_counter()
        print("Elapsed time to load db: ", end-start)

        # Asynchronously call info and review chains
        start = time.perf_counter()
        res_1, res_2 = run_query(info_qa, query), run_query(review_qa, query)
        res = merge_queries(res_1, res_2, query)
        end = time.perf_counter()
        print("Elapsed time to query: ", end-start)
        print(res)
        print('-' * 100)

