from flask import Flask, render_template, request, jsonify
import random  # For random replies

app = Flask(__name__)


# Mock function to interact with OpenAI (replace with actual implementation)
def interact_with_openai(query):
    replies = ["Certainly!", "I'm here to help!", "Ask me anything!"]
    import time
    time.sleep(2)
    return random.choice(replies)


@app.route("/", methods=["GET", "POST"])
def index():
    chat_history = []  # Initialize an empty chat history
    
    if request.method == "POST":
        if "url" in request.form and "num_pages" in request.form:
            # This is the initial form submission for starting the chatbot
            url = request.form.get("url")
            num_pages = int(request.form.get("num_pages"))
            
            # Perform data scraping here using the provided URL and num_pages
            pass
            
            # For demonstration purposes, we'll use mock data
            business_data = {
                "name": "Example Business",
                "history": "A brief history of the business...",
                "specialties": "Specialties of the business...",
                "reviews": {
                    "5": ["Excellent service!", "Highly recommended!"],
                    "4": ["Good experience.", "Will visit again."],
                    "3": ["Average service.", "Could be better."],
                }
            }
            
            return render_template("chat.html", business_data=business_data, chat_history=[], chatbot_reply=None)
        else:
            # This is a question asked in the chat box
            query = request.form.get("query")

            if len(query) <= 200:
                # Perform interaction with OpenAI and get a chatbot reply
                chatbot_reply = interact_with_openai(query)
            else:
                # Query is too long
                chatbot_reply = f"Sorry! Your message ({len(query)} characters) is too long. The maximum is 200 characters."

            chat_history = request.form.getlist("chat_history[]")
            chat_history.append("USR" + query)
            chat_history.append("BOT" + chatbot_reply)
            
            return jsonify({"chat_history": chat_history, "chatbot_reply": chatbot_reply})
    
    return render_template("index.html")


if __name__ == "__main__":
    app.run(debug=True)

