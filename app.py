# app.py - Julian Zulfikar
# --------------------------------------
# Flask implementation.

from flask import Flask, render_template, request, jsonify, session
from utilities import get_unique_uid
from censored_words import wordset
from flask_session import Session
from urllib.parse import urlparse
from datetime import timedelta
import redis

import bleach
import random
import tempfile
import os

import openai
from langchain.document_loaders import TextLoader
from langchain.chat_models import ChatOpenAI
from langchain.embeddings import OpenAIEmbeddings
from langchain.vectorstores import FAISS
from langchain.chains import RetrievalQA

from shell import validate_url, scrape_yelp_page, format_business_data

app = Flask(__name__)

# DEVELOPMENT: Uncomment this to test locally (Start Redis server in Ubuntu and set API env vars)
app = Flask(__name__)
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY')
app.config['SESSION_TYPE'] = 'redis'
app.config['SESSION_PERMANENT'] = False
app.config['SESSION_USE_SIGNER'] = True
app.config['SESSION_KEY_PREFIX'] = 'quickyelp:'
app.config['SESSION_REDIS'] = redis.StrictRedis(host='127.0.0.1', port=6379, db=0)
Session(app)

# # PRODUCTION (1/5): Uncomment this for deployment environment
# app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY')
# redis_url = urlparse(os.environ.get("REDIS_URL"))
# app.config['SESSION_TYPE'] = 'redis'
# app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(minutes=10)
# app.config['SESSION_PERMANENT'] = True
# app.config['SESSION_USE_SIGNER'] = True
# app.config['SESSION_KEY_PREFIX'] = 'quickyelp:'
# app.config['SESSION_REDIS'] = redis_client = redis.Redis(host=redis_url.hostname, port=redis_url.port, password=redis_url.password, ssl=True, ssl_cert_reqs=None)
# Session(app)

DEBUGGING = False # Avoid utilizing Yelp Fusion and OpenAI
AI_REPLIES = [
    "Oops! It seems like the Yelp URL you entered is not valid. Please try again.",
    "Sorry, but the Yelp URL you provided is incorrect or unsupported. Please double-check and retry.",
    "Uh-oh! The Yelp URL you entered doesn't seem to work. Please provide a valid URL and try again.",
    "We encountered an issue with the Yelp URL you provided. Please make sure it's correct and retry.",
    "Hmmm... It appears the Yelp URL you entered is not valid. Kindly check it and try once more."
]
SAMPLE_LINKS = [
    "https://www.yelp.com/biz/nep-cafe-by-kei-concepts-fountain-valley-4",
    "https://www.yelp.com/biz/baekjeong-irvine-irvine-2",
    "https://www.yelp.com/biz/cucina-enoteca-irvine-irvine-2",
    "https://www.yelp.com/biz/omomo-tea-shoppe-irvine",
    "https://www.yelp.com/biz/eureka-irvine-2",
    "https://www.yelp.com/biz/curry-house-coco-ichibanya-irvine",
    "https://www.yelp.com/biz/85-c-bakery-cafe-irvine-irvine",
    "https://www.yelp.com/biz/pepper-lunch-irvine",
    "https://www.yelp.com/biz/stacks-pancake-house-irvine-2",
    "https://www.yelp.com/biz/poached-kitchen-irvine-2",
    "https://www.yelp.com/biz/yup-dduk-irvine-irvine",
    "https://www.yelp.com/biz/orobae-irvine",
    "https://www.yelp.com/biz/breakfast-republic-irvine-2",
    "https://www.yelp.com/biz/daves-hot-chicken-irvine-2"
]


@app.route("/", methods=["GET", "POST"])
def index():
    global DEBUGGING, AI_REPLIES, SAMPLE_LINKS
    chat_history = []

    # # PRODUCTION (2/5): Rate limiting
    # uid = get_unique_uid(request)
    # cur_rate = redis_client.get(uid)
    # if cur_rate and int(cur_rate) >= 5:
    #     return handle_rate_limit_error()

    if request.method == "POST":

        # # PRODUCTION (3/5): Rate limiting
        # if not redis_client.exists(uid):
        #     redis_client.setex(uid, 60, 1)
        # else:
        #     redis_client.incr(uid)
        #     if int(redis_client.get(uid)) >= 5:
        #         redis_client.expire(uid, 30)
        #     else:
        #         redis_client.expire(uid, 60)

        # Handle URL/Number popup
        if "url" in request.form:
            # Initial form submission for starting the chatbot
            url = request.form.get("url")
            num_pages = 2

            # Re-prompt user if url or num_pages is not valid
            if not validate_url(url):
                return render_template("index.html", error_message=AI_REPLIES[random.randint(0, len(AI_REPLIES)-1)], sample_link=SAMPLE_LINKS[random.randint(0, len(SAMPLE_LINKS)-1)])

            # Perform data scraping here using the provided URL and num_pages
            else:
                initial_response = None

                if not DEBUGGING:             
                    business_data = scrape_yelp_page(url, num_pages, web_app=True)
                    business_info, business_reviews = format_business_data(business_data, web_app=True)
                    info_temp_file = tempfile.NamedTemporaryFile(mode='w', delete=False)
                    review_temp_file = tempfile.NamedTemporaryFile(mode='w', delete=False)
                    with info_temp_file as f:
                        f.write(business_info)
                        # DEBUGGING PURPOSES: See what data the chatbot is trained on
                        # with open("webapp_data_info.txt", 'w') as f:
                        #     f.write(business_info)

                    with review_temp_file as f:
                        f.write(business_reviews)
                        # DEBUGGING PURPOSES: See what data the chatbot is trained on
                        # with open("webapp_data_rev.txt", 'w') as f:
                        #     f.write(business_reviews)

                    try:
                        # Initiate FAISS indexes to utilize for querying
                        info_path = info_temp_file.name
                        review_path = review_temp_file.name
                        info_loader = TextLoader(info_path)
                        review_loader = TextLoader(review_path)
                        info_docs = info_loader.load_and_split()
                        review_docs = review_loader.load_and_split()
                        info_db = FAISS.from_documents(info_docs, embedding=OpenAIEmbeddings())
                        review_db = FAISS.from_documents(review_docs, embedding=OpenAIEmbeddings())

                        print("STORING INFO_DB IN SESSION")
                        session['info_db'] = info_db.serialize_to_bytes()
                        print("STORING REVIEW_DB IN SESSION")
                        session['review_db'] = review_db.serialize_to_bytes()

                        try:
                            print("TRYING TO CLEAN UP TEMPFILES")
                            os.remove(info_path)
                            os.remove(review_path)
                        except Exception as e:
                            print("ERROR TRYING TO CLEAN UP TEMPFILES", e)

                    except Exception as e:
                        initial_response = "Notice: Data retrieval has failed. Please return to the homepage by clicking the top left logo and try again. ❌"
                        print(repr(e))
                else:
                    print("MOCKING SCRAPING")
                    import time
                    for i in range(num_pages):
                        print("SCRAPING PAGE", i+1)
                        # time.sleep(6.5)
                    print("MOCK SCRAPE DONE")
                    business_data = {
                        "name": "Restaurant", 
                        "history": random.choice(["History", None]),
                        "specialties": random.choice(["Specialties", None]),
                        "location": random.choice(["Restaurant", None]),
                        "phone": random.choice(["123-456-7890", None]),
                        "categories": random.choice([["Food"], None]),
                        "overall_rating": random.choice(["5.0", None]),
                        "price_range": random.choice(["Money", None]),
                        "hours": random.choice([["Open"], None]),
                        "is_open_now": random.choice([True, None]),
                        "transactions": random.choice(["Transactions", None]),
                        "reviews": {'5': ["Great!"], '4': ["Good!"], '3': ["Decent."]}
                    }
                    # business_data = {
                    #     "name": None,
                    #     "history": None,
                    #     "specialties": None,
                    #     "location": None,
                    #     "phone": None,
                    #     "categories": None,
                    #     "overall_rating": None,
                    #     "price_range": None,
                    #     "hours": None,
                    #     "is_open_now": None,
                    #     "transactions": None,
                    #     "reviews": {}
                    # }

                initial_response = craft_initial_response(business_data) if not initial_response else initial_response
                return render_template("chat.html", initial_response=initial_response, url=url, business_data=business_data)
        
        # Handle chatbot queries
        else:
            query = request.form.get("query")

            # Prevent spam queries
            if len(query) <= 200:

                # Query our vector index after sanitizing
                query = bleach.clean(query, tags=[], attributes={}, strip=True)

                for word in wordset:
                    if word in query.lower():
                        query = '*' * len(query)
                        chatbot_reply = f"Your message has been flagged: \"{word[0]}{'*'*(len(word)-1)}\" ❌"
                        break
                else:
                    if not DEBUGGING:
                        chatbot_reply = None
                        
                        # Try to get databases from session
                        info_db = session.get('info_db')
                        review_db = session.get('review_db')
                        if not info_db or not review_db:
                            chatbot_reply = "Notice: Chatbot data has failed to load, the chat may have reached its 10 minute time limit. Please return to the homepage and try again. To read why this time limit is in place, read via the popup on the homepage. ❌"
                            if not info_db:
                                print("INFO_DB NOT FOUND IN SESSION")
                            if not review_db:
                                print("REVIEW_DB NOT FOUND IN SESSION")
                        else:
                            try:
                                # Create FAISS database
                                info_db = FAISS.deserialize_from_bytes(embeddings=OpenAIEmbeddings(), serialized=info_db)
                                review_db = FAISS.deserialize_from_bytes(embeddings=OpenAIEmbeddings(), serialized=review_db)

                                # Query using LangChain's RetrievalQA
                                info_qa = RetrievalQA.from_chain_type(llm=ChatOpenAI(temperature=0.5), chain_type="stuff", retriever=info_db.as_retriever())
                                review_qa = RetrievalQA.from_chain_type(llm=ChatOpenAI(temperature=0.5), chain_type="stuff", retriever=review_db.as_retriever())
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
                                chatbot_reply = llm.choices[0].message.content
                            except Exception as e:
                                chatbot_reply = "Notice: Chatbot has failed to query, the chat may have reached its 10 minute time limit. Please return to the homepage and try again. To read why this time limit is in place, read via the popup on the homepage. ❌"
                                print(repr(e))
                        
                    else:
                        replies = ["Certainly!", "I'm here to help!", "Ask me anything!", "I am QuickYelp!"]
                        import time
                        time.sleep(1)
                        chatbot_reply = random.choice(replies)
            
            # Query is too long
            else:
                chatbot_reply = f"Sorry! Your message ({len(query)} characters) is too long. The maximum is 200 characters."

            # Append sanitized query and chatbot reply, return to React
            chat_history = request.form.getlist("chat_history[]")
            chat_history.append("USR" + query)
            chat_history.append("BOT" + chatbot_reply)
            return jsonify({"sanitized_user_query": query, "chat_history": chat_history, "chatbot_reply": chatbot_reply})
    
    print("CLEANING UP SESSION")
    try:
        if session.get('info_db'):
            session.pop('info_db')
        if session.get('review_db'):
            session.pop('review_db')
        
        # # PRODUCTION (4/5): Uncomment this for deployment, keep commented if testing locally
        # if redis_client:
        #     if redis_client.exists('info_db'):
        #         redis_client.delete('info_db')
        #     if redis_client.exists('review_db'):
        #         redis_client.delete('review_db')
    except Exception as e:
        print("ERROR REMOVING DATABASES FROM SESSION", e)
        raise e
    else:
        print("CLEANUP SUCCESS")
    return render_template("index.html", error_message="", sample_link=SAMPLE_LINKS[random.randint(0, len(SAMPLE_LINKS)-1)])


def handle_rate_limit_error():
    error_message = "Notice: You are sending requests too fast! Please wait at least 30 seconds before sending your next request. This cooldown is applied to avoid spam abuse of the website. ❌"

    if request.method == "POST":
        if "url" in request.form:
            print("RATE LIMIT EXCEEDED IN POPUP")
            return render_template("index.html", error_message=error_message, sample_link=random.choice(SAMPLE_LINKS))
        else:
            print("RATE LIMIT EXCEEDED IN CHAT")
            query = request.form.get("query")

            if len(query) <= 200:
                query = bleach.clean(query, tags=[], attributes={}, strip=True)

                for word in wordset:
                    if word in query.lower():
                        query = '*' * len(query)
                        break

            chat_history = request.form.getlist("chat_history[]")
            chat_history.append("USR" + query)
            chat_history.append("BOT" + error_message)
            return jsonify({"sanitized_user_query": query, "chat_history": chat_history, "chatbot_reply": error_message})

    print("RATE LIMIT EXCEEDED IN POPUP")
    return render_template("index.html", error_message=error_message, sample_link=random.choice(SAMPLE_LINKS))


@app.route("/cleanup", methods=["POST"])
def cleanup():
    """
    Clean the session databases.
    """
    print("CLEANING UP SESSION")
    try:
        if session.get('info_db'):
            session.pop('info_db')
        if session.get('review_db'):
            session.pop('review_db')
        
        # # PRODUCTION (5/5): Uncomment this for deployment, keep commented if testing locally
        # if redis_client:
        #     if redis_client.exists('info_db'):
        #         redis_client.delete('info_db')
        #     if redis_client.exists('review_db'):
        #         redis_client.delete('review_db')
    except Exception as e:
        print("ERROR REMOVING DATABASES FROM SESSION", e)
        raise e
    else:
        print("CLEANUP SUCCESS")

    return "SUCCESS"


def craft_initial_response(business_data: dict) -> str:
    """
    Present a string which shows what data has been retrieved from the Yelp scrape.
    """
    found = False
    res = "Successfully retrieved: "

    if business_data["name"]:
        res += "Name, "
        found = True
    if business_data["history"]:
        res += "History/About, "
        found = True
    if business_data["location"]:
        res += " Location, "
        found = True
    if business_data["phone"]:
        res += "Phone, "
        found = True
    if business_data["hours"]:
        res += "Hours, "
        found = True
    if business_data["reviews"]:
        res += "Reviews, "
        found = True
    
    return res[:-2]+" ✅" if found else "Notice: Data retrieval has failed. Please return to the homepage by clicking the top left logo and try again. ❌"


if __name__ == "__main__":
    app.run(host='0.0.0.0', port=5000, debug=True)

