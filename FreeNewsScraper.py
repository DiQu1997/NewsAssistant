import os
import json
from pyvirtualdisplay import Display
from selenium import webdriver
from webdriver_manager.chrome import ChromeDriverManager
from bs4 import BeautifulSoup
from scrapegraphai.graphs import SmartScraperGraph
from datetime import datetime
# Set environment variable for pyvirtualdisplay to prevent hanging

import nest_asyncio
nest_asyncio.apply()

import argparse

def news_headline_link_extractor(news_source, openai_api_key):
    graph_config = {
        "llm": {
            "api_key": openai_api_key,
            "model": "openai/gpt-4o-mini",
        },
        "verbose": True,
        "headless": False,
    }

    smart_scraper_graph = SmartScraperGraph(
        prompt="Grab the all the news link and its title",
        source=news_source,
        config=graph_config
    )

    result = smart_scraper_graph.run()
    return result

def news_content_extractor(news_link_result, openai_api_key):
    graph_config = {
        "llm": {
            "api_key": openai_api_key,
            "model": "openai/gpt-4o-mini",
        },
        "verbose": True,
        "headless": False,
    }

    for result in news_link_result['news']:
        if not result['link'].startswith('http'):
            result['link'] = news_source.rstrip('/') + '/' + result['link'].lstrip('/')
        print(f"处理链接: {result['link']}")
        try:
            content_graph = SmartScraperGraph(
                prompt="Grab the full news content, title, and author",
                source=result['link'],
                config=graph_config
            )
            content_result = content_graph.run()
            result['content'] = content_result['content']
            result['timestamp'] = datetime.now().strftime("%Y-%m-%d")
            result['author'] = content_result['author']
        except Exception as e:
            print(f"Error processing link {result['link']}: {e}")
            result['content'] = None
            result['timestamp'] = None
            result['author'] = None
            continue
            
    return news_link_result

if __name__ == "__main__":
    # 创建参数解析器
    parser = argparse.ArgumentParser(description='新闻抓取工具')
    parser.add_argument('--news_source', type=str, default="https://www.reuters.com/", help='新闻源URL')

    # 解析命令行参数
    args = parser.parse_args()
    news_source = args.news_source

    os.environ['PYVIRTUALDISPLAY_DISPLAYFD'] = '0'
    # Start the virtual display
    display = Display(visible=0, size=(1400, 900))
    display.start()

    with open("~/api_key.json", "r") as file:
        api_key_dict = json.load(file)
        OPENAI_API_KEY = api_key_dict["openai"]
    
    news_link_result = news_headline_link_extractor(news_source, OPENAI_API_KEY)
    news_content_result = news_content_extractor(news_link_result, OPENAI_API_KEY)
    
    # 将结果写入JSON文件

    news_source_name = news_source.split("//")[1].split(".")[1]
    with open(f"{news_source_name}_{datetime.now().strftime('%Y-%m-%d')}.json", "w", encoding="utf-8") as file:
        json.dump(news_content_result, file, ensure_ascii=False, indent=4)

   # Stop the virtual display
    display.stop()