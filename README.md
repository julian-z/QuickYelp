![](https://github.com/julian-z/QuickYelp/blob/main/static/images/quickyelp_logo_white_bordered_small.png)
Developed by Julian Zulfikar, August 2023

# Purpose 🚀
QuickYelp is a dynamic AI chatbot which scans through the information and reviews of a given Yelp business, then answers questions based on its training data. With this program, users are able to save a ton of time from having to manually read through the reviews themselves. Thus, our goal is to offer an easy and efficient way to retrieve a quick overview of a restaurant, as well as answer questions to the best of its ability.

# How It Works 🧠
QuickYelp is powered by three main APIs:

1. Yelp Fusion API
2. OpenAI API
3. LangChain

We leverage Yelp Fusion to retrieve data related to the business in question. Following this, LangChain is utilized to feed documents to OpenAI's language model, GPT-3.5.

Once a user submits a query through LangChain's RetrievalQA chain, the query goes through two FAISS (Facebook AI Similarity Search) indexes:
- Index containing the Yelp business information (name, phone, hours, etc)
- Index containing the Yelp business reviews (ordered by Yelp Sort)

Both chatbot replies are received, then fed once more to OpenAI's GPT-3.5 language model. The replies are merged together to form a reply based on the provided information as well as the context found in user reviews, in order to return the most relevant reply possible.

![](https://github.com/julian-z/QuickYelp/blob/main/static/images/query.gif)

# Tech Stack 🤖
- Python
    - Flask
    - Redis
    - LXML
    - Asyncio
- HTML/CSS
    - Tailwind CSS
- JavaScript
    - React

# Screenshots 🎥
Demo Video: https://youtu.be/IsDUfRyTwc8

Screenshots as of 8/24/23:
![](https://github.com/julian-z/QuickYelp/blob/main/static/images/home.png)
![](https://github.com/julian-z/QuickYelp/blob/main/static/images/chat1.png)
![](https://github.com/julian-z/QuickYelp/blob/main/static/images/chat2.png)

# Files 📁
- app.py: Flask implementation of the application
- shell.py: Shell implementation, as well as the main back-end functionality
- index.html: Home page; pop-up form
- chat.html: Chat page, makes asynchronous calls to app.py

# Conclusion 👋
Open to suggestions! Email me at jzulfika@uci.edu
