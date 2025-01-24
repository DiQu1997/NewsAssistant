import logging
import time

import FreeNewsScraper
import GuardianNewsScrapper
import SQLiteDBManger
from queries import *
import argparse
import json
import os

import pyvirtualdisplay

from langchain.prompts import ChatPromptTemplate

news_analysis_prompt = ChatPromptTemplate.from_messages([
    ("system", 
    """You are a professional news editor. You are given an article content.
        From the news, extract the following information:
        What is the news about (key message)?
        Organization or People involved in the news and how are they involved or what happened to them
        What's the impact level of the news?
        What's the sentiment of the news?
        The return format should be json format without extra type indicator with the following keys:
        - key_message: the key message of the news
        - entities: [
                "organization or people": organization or people involved in the news,
                "how involved": how are they involved or what happened to them
        ] (if there is no organization or people involved, the list should be empty)
        - impact_level: the impact level of the news (low, medium, high)
        - sentiment: the sentiment of the news (positive, negative, neutral)
    """),
    ("user", "The content is:\n{content}")
])

def get_LLM_AI_key(llm_model, api_key_file):
    with open(api_key_file, "r") as file:
        api_key_dict = json.load(file)
        if llm_model.startswith("GPT"):
            return api_key_dict["openai"]
        elif llm_model.startswith("Claude"):
            return api_key_dict["anthropic"]
        elif llm_model.startswith("Gemini"):
            return api_key_dict["gemini_api"]
        else:
            raise ValueError(f"Unsupported model: {llm_model}")

def create_db_manager(db_file, logger):
    return SQLiteDBManger.SQLiteDBManger(db_file=db_file, logger=logger)

def create_table(db_manager, table_query, logger):
    db_manager.query(table_query)

# TODO: Add recent 5 day's news link to prevent duplication
def get_news_source_with_scrapegraphai(news_source, api_key):
    news_link_result = FreeNewsScraper.news_headline_link_extractor(news_source, api_key)
    news_content_result = FreeNewsScraper.news_content_extractor(news_source, news_link_result, api_key)
    return news_content_result

def get_news_source_with_guardian(news_source, api_key):
    news_content_result = GuardianNewsScrapper.scrape_guardian_news()
    return news_content_result

def process_news(all_news, news_analyer, news_analysis_prompt):
    for news in all_news:
        news_analysis_result = news_analyer.invoke(news_analysis_prompt.format(content=news))
        analysis_result = json.loads(news_analysis_result.content)
        news["key_message"] = analysis_result["key_message"]
        news["entities"] = analysis_result["entities"]
        news["impact_level"] = analysis_result["impact_level"]
        news["sentiment"] = analysis_result["sentiment"]
    return all_news

def store_news_to_db(news_content_result, db_manager, source_url, file_path, logger):
    if not os.path.exists(file_path):
        os.makedirs(file_path, exist_ok=True)

    for news in news_content_result:
        # Extract data from news content 
        title = news.get('title', 'Unknown' )
        author = news.get('author', 'Unknown')
        link = news.get('link', '')
        timestamp = news.get('timestamp', '')
        content = news.get('content', '')
        if content is None:
            continue
        
        # Create a unique file path for content storage
        full_file_path = f"{file_path}/{timestamp}_{title[:100]}.txt"
        logger.info(f"Storing news to file: {full_file_path}")
        # Save content to file
        if not os.path.exists(full_file_path):
            with open(full_file_path, 'w', encoding='utf-8') as f:
                f.write(content)
            
        # Insert into database
        news_data = (
            title,
            author,
            link,
            timestamp,
            "content/" + f"{timestamp}_{title[:30]}.txt"
        )
        
        try:
            db_manager.query(INSERT_NEWS_ARTICLE, news_data)
            logger.info(f"Successfully stored article: {title}")
        except Exception as e:
            logger.error(f"Error storing article {title}: {e}")

def create_logger():
    logger = logging.getLogger(__name__)
    logger.setLevel(logging.INFO)
    handler = logging.StreamHandler()
    handler.setLevel(logging.INFO)
    formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    handler.setFormatter(formatter)
    logger.addHandler(handler)
    return logger

def main():
    args = argparse.ArgumentParser()
    args.add_argument("--db_file", type=str, default="news_data.db", help="数据库文件名")
    args.add_argument("--file_path", type=str, default="content", help="文件存储路径")
    args.add_argument("--llm_model", type=str, default="GPT", help="模型来源")
    args.add_argument("--api_key_file", type=str, default="api_key.json", help="API密钥文件")
    args = args.parse_args()

    print("Start collecting news")
    # 创建日志记录器
    logger = create_logger()
    logger.info("Logger created")

    # 创建数据库管理器
    db_manager = create_db_manager(args.db_file, logger)
    create_table(db_manager, CREATE_NEWS_ARTICLES_TABLE, logger)

    os.environ['PYVIRTUALDISPLAY_DISPLAYFD'] = '0'
    # Start the virtual display
    display = pyvirtualdisplay.Display(visible=0, size=(1400, 900))
    display.start()
     
    while True:
        #try:
            # Get news from different sources
        reuters_news = get_news_source_with_scrapegraphai("https://www.reuters.com/", get_LLM_AI_key(args.llm_model, args.api_key_file))
        store_news_to_db(reuters_news["news"], db_manager, "https://www.reuters.com/", args.file_path, logger)
            
        cnn_news = get_news_source_with_scrapegraphai("https://www.cnn.com/news", get_LLM_AI_key(args.llm_model, args.api_key_file))
        store_news_to_db(cnn_news["news"], db_manager, "https://www.cnn.com/", args.file_path, logger)
            
        guardian_news = get_news_source_with_guardian("https://www.theguardian.com/us", get_LLM_AI_key(args.llm_model, args.api_key_file))
        # Convert Guardian news format to match others
        guardian_formatted = [{
            'title': title,
            'author': content[2],
            'link': f"https://www.theguardian.com/us/{title.lower().replace(' ', '-')}",
            'timestamp': content[0],
            'content': content[1]
        } for title, content in guardian_news.items()]
        store_news_to_db(guardian_formatted, db_manager, "https://www.theguardian.com/", args.file_path, logger)
        #except Exception as e:
        #    logger.error(f"Error in main loop: {e}")  # Wait 5 minutes before retrying on error
       
        # Add sleep to prevent overwhelming the sources
        time.sleep(3600 * 6)  # Run every 6 hour

if __name__ == "__main__":
    main()
    print("End collecting news")


        
