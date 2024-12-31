import logging

import FreeNewsScraper
import GuardianNewsScrapper
import SQLiteDBManger

import json

news_source = ["Reuters", "BBC", "Guardian"]

def get_LLM_AI_key(llm_model):
    with open(args.api_key_file, "r") as file:
        api_key_dict = json.load(file)
        if llm_model.startswith("GPT"):
            return api_key_dict["openai"]
        elif llm_model.startswith("Claude"):
            return api_key_dict["anthropic"]
        elif llm_model.startswith("Gemini"):
            return api_key_dict["gemini_api"]
        else:
            raise ValueError(f"Unsupported model: {llm_model}")

def get_news_source_with_scrapegraphai(news_source, api_key):
    news_link_result = FreeNewsScraper.news_headline_link_extractor(news_source, api_key)
    news_content_result = FreeNewsScraper.news_content_extractor(news_link_result, api_key)
    return news_content_result

def get_news_source_with_guardian(news_source, api_key):
    news_content_result = GuardianNewsScrapper.scrape_guardian_news(news_source, api_key)
    return news_content_result

def store_news_to_db(news_content_result, db_manager):

def create_logger():
    logger = logging.getLogger(__name__)
    logger.setLevel(logging.INFO)
    handler = logging.StreamHandler()
    handler.setLevel(logging.INFO)
    formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    handler.setFormatter(formatter)
    logger.addHandler(handler)
    return logger

if __name__ == "__main__":

    args = argparse.ArgumentParser()
    args.add_argument("--db_file", type=str, default="news_data.db", help="数据库文件名")
    args.add_argument("--llm_model", type=str, default="GPT", help="模型来源")
    args.add_argument("--api_key_file", type=str, default="api_key.json", help="API密钥文件")
    args = args.parse_args()

    # 创建日志记录器
    logger = create_logger()
    logger.info("Logger created")

    # 创建数据库管理器
    db_manager = SQLiteDBManger(db_file=args.db_file, logger=logger)

    os.environ['PYVIRTUALDISPLAY_DISPLAYFD'] = '0'
    # Start the virtual display
    display = Display(visible=0, size=(1400, 900))
    display.start()
     
    while True:
        try:
        # 获取新闻
        news = FreeNewsScraper.get_news(args.news_source)
        # 将新闻存储到数据库
        db_manager.store_news(news)

        reuters_news = get_news_source_with_scrapegraphai("https://www.reuters.com/", get_LLM_AI_key(args.llm_model))
        bbc_news = get_news_source_with_scrapegraphai("https://www.bbc.com/news", get_LLM_AI_key(args.llm_model))
        guardian_news = get_news_source_with_guardian("https://www.theguardian.com/us", get_LLM_AI_key(args.llm_model))

        
