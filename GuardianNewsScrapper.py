import re
from bs4 import BeautifulSoup
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
import requests
import time
import random

import re
from datetime import datetime
from bs4 import BeautifulSoup

def scrape_guardian_news_content(url, driver):
    # A: 抓取新闻内容
    # b: 获取标题
    title = extract_title_from_url(url)
    print(f"文章标题: {title}")
    
    # c: 获取内容、时间和作者
    content, time, author = extract_content_time_and_author(driver, url)
    
    return title, (time, content, author)

def extract_title_from_url(url):
    return url.split('/')[-1].replace('-', ' ').title()

def extract_content_time_and_author(driver, url):
    driver.get(url)
    soup = BeautifulSoup(driver.page_source, "html.parser")
    main_section = soup.find('main')
    
    if not main_section:
        print("未找到 'main' 标签")
        return None, None, None
    
    maincontent_div = main_section.find('div', id='maincontent')
    
    if not maincontent_div:
        print("未找到 id 为 'maincontent' 的 div")
        return None, None, None
    
    # 提取时间
    time_pattern = r"Last modified on (\w{3} \d{1,2} \w{3} \d{4} \d{2}\.\d{2} \w{3})"
    time_match = re.search(time_pattern, soup.text)
    if time_match:
        time = time_match.group(1)
    else:
        time = datetime.now().strftime("%a %d %b %Y %H.%M %Z")
    
    # 提取作者
    author_tag = soup.find('a', rel='author')
    author = author_tag.text if author_tag else "unknow author"
    
    paragraphs = maincontent_div.find_all('p')
    content = []
    
    for p in paragraphs:
        text = ''.join(child.strip() for child in p.contents if isinstance(child, str))
        if text:
            content.append(text + "\n")
    
    return ' '.join(content), time, author

def scrape_news(url):
    try:
        return scrape_guardian_news_content(url, driver)
    except Exception as e:
        print(f"抓取 {url} 时出错: {str(e)}")
        return None

def find_sections(soup, exclude_sections):
    sections = []
    for section in soup.find_all('section'):
        section_id = section.get('id')
        if section_id == 'in-pictures':
            break
        if section_id and section_id not in exclude_sections:
            print(section_id)
            sections.append(section)
    return sections

def extract_links_from_container(soup, section_id):
    container_id = f"container-{section_id}"
    container = soup.find('div', id=container_id)
    
    if not container:
        print(f"\nsection id: {section_id}")
        print(f"未找到对应的container (id: {container_id})")
        return []
    
    links = container.find_all('a', href=True)
    valid_links = [link['href'] for link in links if link['href'].startswith('/') and not link['href'].endswith('#comments')]
    
    print(f"\nsection id: {section_id}")
    print(f"找到 {len(valid_links)} 个有效链接:")
    for link in valid_links:
        print(f"  - {link}")
    
    return valid_links

def scrape_news_articles(links, base_url, scrape_function, driver):
    scraped_news = {}
    for link in links:
        full_url = f"{base_url}{link}"
        news_content = scrape_function(full_url, driver)
        if news_content:
            scraped_news[news_content[0]] = news_content[1]
            print(f"    成功抓取: {news_content[0]}")
        else:
            print(f"    抓取失败: {full_url}")
        
        wait_time = random.uniform(1, 3)
        time.sleep(wait_time)
    return scraped_news

def print_scraped_news(scraped_news):
    print(f"\n抓取完成。总共抓取了 {len(scraped_news)} 条新闻。")
    print("\n抓取的新闻标题:")
    for title, content in scraped_news.items():
        print(f"- {title}")
        print(content)
        print()

def extract_headline_links(soup):
    headlines_container = soup.find('div', id='container-headlines')
    if not headlines_container:
        print("未找到 id 为 container-headlines 的 div")
        return {}

    headlines_uls = headlines_container.find_all('ul', limit=2)
    if not headlines_uls:
        print("在 container-headlines 下未找到 ul 元素")
        return {}

    first_ul_hrefs = [link.get('href') for link in headlines_uls[0].find_all('a')]
    second_ul_hrefs = [link.get('href') for link in headlines_uls[1].find_all('a')]

    print("第一个 ul 的链接 (头条新闻):")
    for href in first_ul_hrefs:
        print(f"  - {href}")

    print("\n第二个 ul 的链接:")
    for href in second_ul_hrefs:
        print(f"  - {href}")

    return {
        "头条新闻": first_ul_hrefs,
        "其他头条新闻": second_ul_hrefs
    }

def scrape_guardian_news():
    # A: 初始化设置
    # b: 设置常量和配置
    guardian_exclude_section = ["headlines", "wellness", "soccer", "sports", "podcasts", "lifestyle", "take-part", "from-our-global-editions", "video"]
    url = 'https://www.theguardian.com/us'
    
    # c: 初始化WebDriver
    options = Options()
    options.add_argument("--headless")
    driver = webdriver.Chrome(options=options)
    
    # A: 获取页面内容
    # b: 获取页面源代码
    driver.get(url)
    soup = BeautifulSoup(driver.page_source, "html.parser")
    
    # c: 提取头条新闻链接
    headline_links = extract_headline_links(soup)
    
    # d: 查找其他section
    sections = find_sections(soup, guardian_exclude_section)
    
    # A: 提取链接
    print("\n为每个section查找对应的container并提取链接:")
    all_valid_links = []
    for section in sections:
        section_id = section.get('id')
        valid_links = extract_links_from_container(soup, section_id)
        all_valid_links.extend(valid_links)

    # 将头条新闻链接添加到all_valid_links
    for category, urls in headline_links.items():
        all_valid_links.extend(urls)

    # A: 抓取新闻
    print("\n开始抓取新闻:")
    scraped_news = scrape_news_articles(all_valid_links, "https://www.theguardian.com", scrape_guardian_news_content, driver)
    return scraped_news

# 执行主函数
# guardian_news = scrape_guardian_news()