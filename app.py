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

import asyncio
import bleach
import random
import tempfile
from time import perf_counter, sleep
import os

from langchain.document_loaders import TextLoader
from langchain.chat_models import ChatOpenAI
from langchain.embeddings import OpenAIEmbeddings
from langchain.vectorstores import FAISS
from langchain.chains import RetrievalQA

from shell import retrieve_yelp_info, format_business_data, run_query

app = Flask(__name__)

DEBUGGING = False # Avoid utilizing Yelp Fusion and OpenAI
PRODUCTION = False # Deployment vs local testing

# PRODUCTION (1/6): Setup
if PRODUCTION:
    app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY')
    redis_url = urlparse(os.environ.get("REDIS_URL"))
    app.config['SESSION_TYPE'] = 'redis'
    app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(minutes=10)
    app.config['SESSION_PERMANENT'] = True
    app.config['SESSION_USE_SIGNER'] = True
    app.config['SESSION_KEY_PREFIX'] = 'quickyelp:'
    app.config['SESSION_REDIS'] = redis_client = redis.Redis(host=redis_url.hostname, port=redis_url.port, password=redis_url.password, ssl=True, ssl_cert_reqs=None)
    Session(app)

# DEVELOPMENT: Setup (Start Redis server in Ubuntu and set API env vars)
else:
    app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY')
    app.config['SESSION_TYPE'] = 'redis'
    app.config['SESSION_PERMANENT'] = False
    app.config['SESSION_USE_SIGNER'] = True
    app.config['SESSION_KEY_PREFIX'] = 'quickyelp:'
    app.config['SESSION_REDIS'] = redis.StrictRedis(host='127.0.0.1', port=6379, db=0)
    Session(app)

AI_REPLIES = [
    "Sorry, the location should contain at least 1 character and at most 250 characters.",
    "Uh-oh! The length of the location you provided doesn't meet the required range (1-250 characters).",
    "We encountered an issue with the location you entered. It needs to be between 1 and 250 characters.",
    "Hmmm... It appears the length of the location you entered doesn't match the expected range (1-250 characters)."
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
STARS = {
    '0.0': ".././static/images/stars/0.png",
    '0.5': ".././static/images/stars/0.png",
    '1.0': ".././static/images/stars/1.png",
    '1.5': ".././static/images/stars/1-5.png",
    '2.0': ".././static/images/stars/2.png",
    '2.5': ".././static/images/stars/2-5.png",
    '3.0': ".././static/images/stars/3.png",
    '3.5': ".././static/images/stars/3-5.png",
    '4.0': ".././static/images/stars/4.png",
    '4.5': ".././static/images/stars/4-5.png",
    '5.0': ".././static/images/stars/5.png"
}


@app.route("/", methods=["GET", "POST"])
def index():
    global DEBUGGING, PRODUCTION, AI_REPLIES, SAMPLE_LINKS, STARS
    chat_history = []

    # PRODUCTION (2/6): Rate limiting
    if PRODUCTION:
        uid = get_unique_uid(request)
        cur_rate = redis_client.get(uid)
        if cur_rate and int(cur_rate) >= 5:
            return handle_rate_limit_error()

    if request.method == "POST":

        # PRODUCTION (3/6): Rate limiting
        if PRODUCTION:
            if not redis_client.exists(uid):
                redis_client.setex(uid, 60, 1)
            else:
                redis_client.incr(uid)
                if int(redis_client.get(uid)) >= 5:
                    redis_client.expire(uid, 30)
                else:
                    redis_client.expire(uid, 60)

        # Handle URL/Number popup
        if "name" in request.form and "location" in request.form:
            # Initial form submission for starting the chatbot
            name = request.form.get("name")
            location = request.form.get("location")

            # Re-prompt user if url or num_pages is not valid
            if len(location) > 250:
                return render_template("index.html", error_message=AI_REPLIES[random.randint(0, len(AI_REPLIES)-1)], sample_link=SAMPLE_LINKS[random.randint(0, len(SAMPLE_LINKS)-1)])

            # Perform data scraping here using the provided URL and num_pages
            else:
                start_time = perf_counter()

                initial_response = None

                if not DEBUGGING:             
                    business_data = retrieve_yelp_info(name, location, web_app=True)

                    for section in business_data:
                        if business_data[section]:
                            break
                    else:
                        return render_template("index.html", error_message="It seems that we could not find a Yelp business which matched your query. Please double-check and try again.", sample_link=SAMPLE_LINKS[random.randint(0, len(SAMPLE_LINKS)-1)])
                    
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
                    print("MOCKING RETRIEVAL")
                    import time
                    for i in range(2):
                        print("RETRIEVING PAGE", i+1)
                        # sleep(6.5)
                    print("MOCK RETRIEVAL DONE")
                    business_data = {
                        "name": "Bert's Restaurant", 
                        "history": random.choice(["History", None]),
                        "specialties": random.choice(["Specialties", None]),
                        "location": ["123 Bert St", "California"],
                        "phone": random.choice(["123-456-7890", None]),
                        "categories": random.choice([["Food"], None]),
                        "overall_rating": 5.0,
                        "price_range": random.choice(["Money", None]),
                        "hours": random.choice([["Open"], None]),
                        "is_open_now": random.choice([True, None]),
                        "transactions": random.choice(["Transactions", None]),
                        "url": "https://www.yelp.com/",
                        "image_url": "https://s3-media2.fl.yelpcdn.com/bphoto/WauUEdASvfaEVqGtkWWe7Q/o.jpg",
                        "reviews": {'5': ["Great!"], '4': ["Good!"], '3': ["Decent."]}
                    }

                # Format for business preview
                business_data["overall_rating"] = "" if not business_data["overall_rating"] else STARS[str(business_data["overall_rating"])]
                business_data["image_url"] = "" if not business_data["image_url"] else business_data["image_url"]
                business_data["name"] = "" if not business_data["name"] else business_data["name"]
                business_data["location"] = "" if not business_data["location"] else ', '.join(business_data["location"])
                initial_response = craft_initial_response(business_data) if not initial_response else initial_response

                # PRODUCTION (4/6): Chat count
                if PRODUCTION:
                    redis_client.incr('chats')
                    print("CHAT COUNT:", redis_client.get('chats'))

                end_time = perf_counter()
                print("Elapsed time: ", end_time-start_time)

                return render_template("chat.html", initial_response=initial_response, business_data=business_data)
        
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
                                chatbot_reply = asyncio.run(run_query(info_qa, review_qa, query))
                            except Exception as e:
                                chatbot_reply = "Notice: Chatbot has failed to query, the chat may have reached its 10 minute time limit. Please return to the homepage and try again. To read why this time limit is in place, read via the popup on the homepage. ❌"
                                print(repr(e))
                        
                    else:
                        replies = ["Certainly!", "I'm here to help!", "Ask me anything!", "I am QuickYelp!"]
                        sleep(1)
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
        
        # PRODUCTION (5/6): Uncomment this for deployment, keep commented if testing locally
        if PRODUCTION:    
            if redis_client:
                if redis_client.exists('info_db'):
                    redis_client.delete('info_db')
                if redis_client.exists('review_db'):
                    redis_client.delete('review_db')
    except Exception as e:
        print("ERROR REMOVING DATABASES FROM SESSION", e)
        raise e
    else:
        print("CLEANUP SUCCESS")
    return render_template("index.html", error_message="", sample_link=SAMPLE_LINKS[random.randint(0, len(SAMPLE_LINKS)-1)])


def handle_rate_limit_error():
    error_message = "Notice: You are sending requests too fast! Please wait at least 30 seconds before sending your next request. This cooldown is applied to avoid spam abuse of the website. ❌"

    if request.method == "POST":
        if "name" in request.form and "location" in request.form:
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
        
        # PRODUCTION (6/6): Uncomment this for deployment, keep commented if testing locally
        if PRODUCTION:
            if redis_client:
                if redis_client.exists('info_db'):
                    redis_client.delete('info_db')
                if redis_client.exists('review_db'):
                    redis_client.delete('review_db')
    except Exception as e:
        print("ERROR REMOVING DATABASES FROM SESSION", e)
        raise e
    else:
        print("CLEANUP SUCCESS")

    return "SUCCESS"


def craft_initial_response(business_data: dict) -> str:
    """
    Present a string which shows what data has been retrieved from the Yelp retrieval.
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

