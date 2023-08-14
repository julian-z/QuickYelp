# shell.py - Julian Zulfikar
# --------------------------------------
# Shell implementation of the program.

import requests
from collections import defaultdict
from unidecode import unidecode
from lxml import html
from html import unescape
import json
import time
import re
from random import randint

import os
from api_key import OPENAI_KEY, YELP_FUSION_KEY
from langchain.document_loaders import TextLoader
from langchain.indexes import VectorstoreIndexCreator
from langchain.chat_models import ChatOpenAI

os.environ["OPENAI_API_KEY"] = OPENAI_KEY


def clean(input_string):
    """
    Helper function to remove HTML syntax.
    """
    cleaned_string = unescape(input_string)
    tree = html.fromstring(cleaned_string)
    cleaned_string = tree.text_content()
    cleaned_string = " ".join(cleaned_string.split())
    return cleaned_string


def scrape_yelp_page(base_url: str, num_pages: int) -> dict:
    """
    Scrapes the first "num_pages" review pages of a Yelp URL and stores into a JSON object.
        Resulting JSON object is written into business_data.txt
    """
    # Construct URLs to first 5 review pages
    review_urls = [base_url]

    def _generate_review_url(base_url, start_value):
        return base_url + f'&start={start_value}' if '?' in base_url else base_url + f'?start={start_value}'

    for start_value in range(10, num_pages*10, 10):
        review_urls.append(_generate_review_url(base_url, start_value))

    # Store information in business_data
    business_data = {
        "name": None, 
        "history": None,
        "specialties": None,
        "location": None,
        "reviews": defaultdict(list),
        "yelp_fusion_api_business_match": None,
        "yelp_fusion_api_business_details": None
    }

    # Scrape reviews and retrieve business information
    for i, url in enumerate(review_urls):

        print(f"SCRAPING PAGE {i+1}:", url)

        try:
            # Avoid making high-frequency requests to Yelp. Ethical programming!
            time.sleep(1)
            response = requests.get(url)

            if response.status_code == 200:
                # Get source code
                source_code = unidecode(response.text)
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
                            location_as_dict = eval(location)
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
                            business_data["reviews"][rating].append(clean(comment))
                        except Exception as e:
                            print(f"ERROR RETRIEVING REVIEW #{i}:", e)
                            errors += 1
                    
                    # If 10 errors happened, there are no more reviews
                    if errors == 10:
                        break

                except Exception as e:
                    print("ERROR RETRIEVING REVIEWS:", e)
            
            else:
                print("ERROR -- STATUS CODE:", response.status_code)

        except Exception as e:
            print("ERROR:", e)
            raise e

    # Try to call to Yelp Fusion API: Business Match
    # https://docs.developer.yelp.com/reference/v3_business_match
    if business_data["name"] and type(business_data["location"]) == dict:
        try:
            yf_url = f"https://api.yelp.com/v3/businesses/matches?name={business_data['name']}&address1={business_data['location']['streetAddress']}" + \
            f"&city={business_data['location']['addressLocality']}&state={business_data['location']['addressRegion']}&country={business_data['location']['addressCountry']}" + \
            f"&limit=1&match_threshold=default"
            api_call = requests.get(yf_url, headers={"Authorization": "Bearer "+YELP_FUSION_KEY})

            if api_call.status_code == 200:
                business_data["yelp_fusion_api_business_match"] = api_call.json()
            else:
                print("API (1) STATUS CODE", api_call.status_code)
        except Exception as e:
            print("ERROR CALLING FUSION (1):", e)
    else:
        print("NO FUSION CALL:", business_data["name"], business_data["location"])
    
    # Try to call Yelp Fusion API: Business Details
    # https://docs.developer.yelp.com/reference/v3_business_info
    if business_data["yelp_fusion_api_business_match"]:
        try:
            yf_url = f"https://api.yelp.com/v3/businesses/{business_data['yelp_fusion_api_business_match']['businesses'][0]['id']}"
            api_call = requests.get(yf_url, headers={"Authorization": "Bearer "+YELP_FUSION_KEY})

            if api_call.status_code == 200:
                business_data["yelp_fusion_api_business_details"] = api_call.json()
            else:
                print("API (2) STATUS CODE", api_call.status_code)
        except Exception as e:
            print("ERROR CALLING FUSION (2):", e)

    # Dump business_data JSON object
    with open("business_data.txt", 'w') as f:
        json.dump(business_data, f)
    
    return business_data


def validate_url(url):
    """
    Helper function to validate Yelp URL.
    """
    return re.match(r'^https?://(?:www\.)?yelp\.com/biz/[\w-]+(?:-\w+)?(?:\?[\w=&-]*)?$', url)


if __name__ == "__main__":
    # base_url = 'https://www.yelp.com/biz/wingstop-opening-soon-sacramento'
    # base_url = 'https://www.yelp.com/biz/kikis-chicken-place-sacramento-15?page_src=related_bizes'
    # base_url = 'https://www.yelp.com/biz/nick-the-greek-elk-grove-elk-grove'

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
    business_data = scrape_yelp_page(base_url, num_pages)
    print("Done scraping!")
    print('-'*100)
    
    # DEBUGGING PURPOSES: Open business_data.txt instead
    # with open("business_data.txt", 'r') as f:
    #     business_data = json.loads(f.read())

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

    # Feed to OpenAI
    loader = TextLoader("business_data.txt")
    index = VectorstoreIndexCreator().from_loaders([loader])

    # Initiate ChatBot
    while True:
        query = input("Ask a question about the business (Q to quit): ")
        if query == 'Q': break
        res = index.query(query, llm=ChatOpenAI())
        print(res)
        print('-'*100)
    
