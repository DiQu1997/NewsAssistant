# queries.py

# Create Tables
CREATE_NEWS_ARTICLES_TABLE = """
CREATE TABLE IF NOT EXISTS news_articles (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL,
    author_name TEXT,
    original_link TEXT UNIQUE NOT NULL,
    created_time TIMESTAMP,
    file_path TEXT UNIQUE NOT NULL
);
"""

CREATE_ENTITIES_TABLE = """
CREATE TABLE IF NOT EXISTS entities (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    type TEXT NOT NULL
);
"""

CREATE_ENTITY_ARTICLE_RELATIONSHIP_TABLE = """
CREATE TABLE IF NOT EXISTS entity_article_relationships (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    entity_id INTEGER NOT NULL,
    news_id INTEGER NOT NULL,
    relation_type TEXT NOT NULL,
    related_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (entity_id) REFERENCES entities(id),
    FOREIGN KEY (news_id) REFERENCES news_articles(id),
    UNIQUE(entity_id, news_id, relation_type)
);
"""

CREATE_EVENTS_TABLE = """
CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    description TEXT,
    start_time TIMESTAMP,
    end_time TIMESTAMP,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
"""

CREATE_EVENT_ARTICLE_RELATIONSHIP_TABLE = """
CREATE TABLE IF NOT EXISTS event_article_relationships (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    event_id INTEGER NOT NULL,
    news_id INTEGER NOT NULL,
    intermediate_state TEXT,
    related_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (event_id) REFERENCES events(id),
    FOREIGN KEY (news_id) REFERENCES news_articles(id),
    UNIQUE(event_id, news_id)
);
"""

# Insert Queries
INSERT_NEWS_ARTICLE = """
INSERT INTO news_articles (title, author_name, original_link, created_time, file_path)
VALUES (?, ?, ?, ?, ?);
"""

INSERT_RAW_CONTENT = """
INSERT INTO raw_content (file_path, file_size, file_format)
VALUES (?, ?, ?);
"""

INSERT_ENTITY = """
INSERT INTO entities (name, type)
VALUES (?, ?);
"""

INSERT_ENTITY_ARTICLE_RELATIONSHIP = """
INSERT INTO entity_article_relationships (entity_id, news_id, relation_type)
VALUES (?, ?, ?);
"""

INSERT_EVENT = """
INSERT INTO events (name, description, start_time, end_time)
VALUES (?, ?, ?, ?);
"""

INSERT_EVENT_ARTICLE_RELATIONSHIP = """
INSERT INTO event_article_relationships (event_id, news_id, intermediate_state)
VALUES (?, ?, ?);
"""

# Select Queries
SELECT_ARTICLE_BY_LINK = """
SELECT id FROM news_articles WHERE original_link = ?;
"""

SELECT_ALL_UNSCRAPED_ARTICLES = """
SELECT id, original_link FROM news_articles WHERE is_scraped = 0;
"""

SELECT_ENTITIES_BY_ARTICLE = """
SELECT e.name, e.type, ear.relation_type, ear.related_at
FROM entities e
JOIN entity_article_relationships ear ON e.id = ear.entity_id
WHERE ear.news_id = ?;
"""

SELECT_EVENTS_BY_ARTICLE = """
SELECT ev.name, ev.description, ev.start_time, ev.end_time, ear.intermediate_state, ear.related_at
FROM events ev
JOIN event_article_relationships ear ON ev.id = ear.event_id
WHERE ear.news_id = ?;
"""

SELECT_NEWS_LINK_BY_SOURCE = """
SELECT original_link FROM news_articles WHERE original_link LIKE ?;
"""

# Update Queries
UPDATE_SCRAPED_STATUS = """
UPDATE news_articles SET is_scraped = 1, scraped_at = ? WHERE id = ?;
"""

# Delete Queries (if needed)
DELETE_ARTICLE = """
DELETE FROM news_articles WHERE id = ?;
"""