# app.py - Julian Zulfikar
# --------------------------------------
# Flask implementation.

from flask import Flask, render_template, request, jsonify
from flask_wtf import FlaskForm
from wtforms import StringField
from wtforms.validators import DataRequired, URL
from flask_wtf.csrf import CSRFProtect
from flask_limiter import Limiter, RateLimitExceeded
from flask_limiter.util import get_remote_address
from censored_words import wordset
import bleach

import random
import tempfile
import os

from api_key import OPENAI_KEY, SECRET_KEY
from langchain.document_loaders import TextLoader
from langchain.indexes import VectorstoreIndexCreator
from langchain.chat_models import ChatOpenAI

from shell import validate_url, scrape_yelp_page, format_business_data

os.environ["OPENAI_API_KEY"] = OPENAI_KEY

app = Flask(__name__)
csrf = CSRFProtect(app)
limiter = Limiter(get_remote_address, app=app, storage_uri="memory://") # TO-DO: Configure storage when deployed
app.config['SECRET_KEY'] = SECRET_KEY

LOADER = None
INDEX = None
DEBUGGING = True # Avoid utilizing Yelp Fusion and OpenAI
RATE_LIMIT_MIN = '8'
RATE_LIMIT_DAY = '150'
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


class URLForm(FlaskForm):
    url = StringField('Yelp URL', validators=[DataRequired(), URL()])


@app.route("/", methods=["GET", "POST"])
@limiter.limit(f"{RATE_LIMIT_MIN}/minute")
@limiter.limit(f"{RATE_LIMIT_DAY}/day")
def index():
    chat_history = []
    global INDEX, LOADER, DEBUGGING, AI_REPLIES, SAMPLE_LINKS
    if request.method == "POST":

        # Handle URL/Number popup
        if "url" in request.form and "num_pages" in request.form:

            # Utilize Flask-WTF for security precautions
            url_form = URLForm(request.form)
            if url_form.validate_on_submit():

                # Initial form submission for starting the chatbot
                url = request.form.get("url")
                num_pages = int(request.form.get("num_pages"))

                # Re-prompt user if url or num_pages is not valid
                if not validate_url(url):
                    return render_template("index.html", error_message=AI_REPLIES[random.randint(0, len(AI_REPLIES)-1)], sample_link=SAMPLE_LINKS[random.randint(0, len(SAMPLE_LINKS)-1)], form=url_form)

                # Perform data scraping here using the provided URL and num_pages
                else:
                    initial_response = None

                    if not DEBUGGING:             
                        business_data = scrape_yelp_page(url, num_pages, web_app=True)
                        training_data = format_business_data(business_data, web_app=True)
                        temp_file = tempfile.NamedTemporaryFile(mode='w', delete=False)
                        with temp_file as f:
                            f.write(training_data)

                            # DEBUGGING PURPOSES: See what data the chatbot is trained on
                            # with open("webapp_data.txt", 'w') as f:
                            #     f.write(training_data)

                        try:
                            temp_file_path = temp_file.name
                            LOADER = TextLoader(temp_file_path)
                            INDEX = VectorstoreIndexCreator().from_loaders([LOADER])
                            os.remove(temp_file_path)
                        except:
                            initial_response = "❌ Notice: Data retrieval has failed. Please report this instance to jzulfika@uci.edu."
                    else:
                        print("MOCKING SCRAPING")
                        import time
                        for i in range(num_pages):
                            print("SCRAPING PAGE", i+1)
                            time.sleep(6.5)
                        LOADER = "Mock Loader"
                        INDEX = "Mock Index"
                        print("MOCK SCRAPE DONE")
                        business_data = {
                            "name": random.choice(["Restaurant", None]), 
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

                    initial_response = craft_initial_response(business_data) if not initial_response else initial_response
                    return render_template("chat.html", initial_response=initial_response)
            
            else:
                return render_template("index.html", error_message=AI_REPLIES[random.randint(0, len(AI_REPLIES)-1)], sample_link=SAMPLE_LINKS[random.randint(0, len(SAMPLE_LINKS)-1)], form=url_form)
        
        # Handle chatbot queries
        else:
            query = request.form.get("query")

            if len(query) <= 200:
                # Query our vector index after sanitizing
                query = bleach.clean(query, tags=[], attributes={}, strip=True)

                for word in wordset:
                    if word in query.lower():
                        query = '*' * len(query)
                        chatbot_reply = f"❌ Your message has been marked as inappropriate: \"{word[0]}{'*'*(len(word)-1)}\""
                        break
                else:
                    if not DEBUGGING:
                        chatbot_reply = None
                        try:
                            chatbot_reply = INDEX.query(query, llm=ChatOpenAI())
                        except:
                            chatbot_reply = "❌ Notice: Chatbot has failed to query. Please report this instance to jzulfika@uci.edu."
                    else:
                        replies = ["Certainly!", "I'm here to help!", "Ask me anything!", "I am QuickYelp!"]
                        import time
                        time.sleep(1)
                        chatbot_reply = random.choice(replies)
            else:
                # Query is too long
                chatbot_reply = f"Sorry! Your message ({len(query)} characters) is too long. The maximum is 200 characters."

            chat_history = request.form.getlist("chat_history[]")
            chat_history.append("USR" + query)
            chat_history.append("BOT" + chatbot_reply)
            return jsonify({"sanitized_user_query": query, "chat_history": chat_history, "chatbot_reply": chatbot_reply})
    
    LOADER = INDEX = None
    url_form = URLForm(request.form)
    return render_template("index.html", error_message="", sample_link=SAMPLE_LINKS[random.randint(0, len(SAMPLE_LINKS)-1)], form=url_form)


@app.errorhandler(RateLimitExceeded)
def handle_rate_limit_error(e):
    error_message = f"❌ Notice: Rate limit of requests has been exceeded ({RATE_LIMIT_MIN} links per minute, {RATE_LIMIT_DAY} per day). Please try later or slow down incoming requests."

    if request.method == "POST":
        if "url" in request.form and "num_pages" in request.form:
            return render_template("index.html", error_message=error_message, sample_link=random.choice(SAMPLE_LINKS), form=URLForm(request.form))
        else:
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

    return render_template("index.html", error_message=error_message, sample_link=random.choice(SAMPLE_LINKS), form=URLForm(request.form))


def craft_initial_response(business_data: dict) -> str:
    """
    Present a string which shows what data has been retrieved from the Yelp scrape.
    """
    found = False
    res = "✅ Successfully retrieved: "

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
    
    return res[:-2] if found else "❌ Notice: Data retrieval has failed. Please report this instance to jzulfika@uci.edu if the issue persists."


if __name__ == "__main__":
    app.run(debug=True)

