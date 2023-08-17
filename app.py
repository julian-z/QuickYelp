# app.py - Julian Zulfikar
# --------------------------------------
# Flask implementation.

from flask import Flask, render_template, request, jsonify
import random
import json
import tempfile
import os

from api_key import OPENAI_KEY
from langchain.document_loaders import TextLoader
from langchain.indexes import VectorstoreIndexCreator
from langchain.chat_models import ChatOpenAI

from shell import validate_url, scrape_yelp_page, format_business_data

os.environ["OPENAI_API_KEY"] = OPENAI_KEY
app = Flask(__name__)

LOADER = None
INDEX = None
DEBUGGING = True # Avoid utilizing Yelp Fusion and OpenAI


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
    
    return "✅ "+res[:-2] if found else "❌ Notice: Data retrieval has failed. Please report this instance to jzulfika@uci.edu if the issue persists."


@app.route("/", methods=["GET", "POST"])
def index():
    ai_replies = [
        "Oops! It seems like the Yelp URL you entered is not valid. Please try again.",
        "Sorry, but the Yelp URL you provided is incorrect or unsupported. Please double-check and retry.",
        "Uh-oh! The Yelp URL you entered doesn't seem to work. Please provide a valid URL and try again.",
        "We encountered an issue with the Yelp URL you provided. Please make sure it's correct and retry.",
        "Hmmm... It appears the Yelp URL you entered is not valid. Kindly check it and try once more."
    ]
    sample_links = [
        "https://www.yelp.com/biz/nep-cafe-by-kei-concepts-fountain-valley-4",
        "https://www.yelp.com/biz/baekjeong-irvine-irvine-2",
        "https://www.yelp.com/biz/cucina-enoteca-irvine-irvine-2",
        "https://www.yelp.com/biz/omomo-tea-shoppe-irvine",
        "https://www.yelp.com/biz/eureka-irvine-2",
        "https://www.yelp.com/biz/curry-house-coco-ichibanya-irvine",
        "https://www.yelp.com/biz/85-c-bakery-cafe-irvine-irvine",
        "https://www.yelp.com/biz/pepper-lunch-irvine",
        "https://www.yelp.com/biz/stacks-pancake-house-irvine-2"
    ]
    chat_history = []

    global INDEX, LOADER, DEBUGGING
    if request.method == "POST":
        if "url" in request.form and "num_pages" in request.form:
            # Initial form submission for starting the chatbot
            url = request.form.get("url")
            num_pages = int(request.form.get("num_pages"))

            # Re-prompt user if url or num_pages is not valid
            if not validate_url(url):
                return render_template("index.html", error_message=ai_replies[random.randint(0, len(ai_replies)-1)], sample_link=sample_links[random.randint(0, len(sample_links)-1)])

            # Perform data scraping here using the provided URL and num_pages
            else:
                if not DEBUGGING:             
                    business_data = scrape_yelp_page(url, num_pages, web_app=True)
                    training_data = format_business_data(business_data, web_app=True)
                    temp_file = tempfile.NamedTemporaryFile(mode='w', delete=False)
                    with temp_file as f:
                        f.write(training_data)

                        # DEBUGGING PURPOSES: See what data the chatbot is trained on
                        # with open("webapp_data.txt", 'w') as f:
                        #     f.write(training_data)

                    temp_file_path = temp_file.name
                    LOADER = TextLoader(temp_file_path)
                    INDEX = VectorstoreIndexCreator().from_loaders([LOADER])
                    os.remove(temp_file_path)
                else:
                    print("MOCKING SCRAPING")
                    import time
                    time.sleep(num_pages)
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

                initial_response = craft_initial_response(business_data)
                return render_template("chat.html", initial_response=initial_response)
        
        else:
            query = request.form.get("query")

            if len(query) <= 200:
                # Perform interaction with OpenAI and get a chatbot reply
                if not DEBUGGING:
                    chatbot_reply = INDEX.query(query, llm=ChatOpenAI())
                else:
                    replies = ["Certainly!", "I'm here to help!", "Ask me anything!", "I am QuickYelp!"]
                    import time
                    time.sleep(2)
                    chatbot_reply = random.choice(replies)
            else:
                # Query is too long
                chatbot_reply = f"Sorry! Your message ({len(query)} characters) is too long. The maximum is 200 characters."

            chat_history = request.form.getlist("chat_history[]")
            chat_history.append("USR" + query)
            chat_history.append("BOT" + chatbot_reply)
            return jsonify({"chat_history": chat_history, "chatbot_reply": chatbot_reply})
    
    LOADER = INDEX = None
    return render_template("index.html", error_message="", sample_link=sample_links[random.randint(0, len(sample_links)-1)])


if __name__ == "__main__":
    app.run(debug=True)

