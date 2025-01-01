# 1. Database Overview

Your database will consist of several interrelated tables to handle different aspects of your news data:
1. **News Articles**: Stores metadata about each news article.
2. **Raw Content**: Stores pointers to the raw content files stored externally (e.g., Google Drive).
3. **Entities**: Stores information about entities (people, organizations) mentioned in the articles.
4. **Events**: Stores information about events related to the articles.
5. **Entity-Article Relationships**: Manages the many-to-many relationships between entities and articles.
6. **Event-Article Relationships**: Manages the relationships between events and articles.
7. **Scraping Status**: Tracks the scraping status of each article.

## 2. Detailed Table Structures

### A. News Articles Table

**Purpose**: Store metadata about each news article.

**Table Name**: `news_articles`

**Columns**:

| Column Name   | Data Type  | Constraints                                | Description                                      |
|---------------|------------|--------------------------------------------|--------------------------------------------------|
| id            | SERIAL     | PRIMARY KEY                                | Unique identifier for each article.              |
| unique_id     | UUID       | UNIQUE, NOT NULL                           | Universally unique identifier for the article.   |
| title         | VARCHAR(512) | NOT NULL                                 | Title of the news article.                       |
| author_name   | VARCHAR(255) |                                          | Name of the author (if available).               |
| original_link | VARCHAR(2048) | NOT NULL, UNIQUE                        | URL to the original news article.                |
| published_at  | TIMESTAMP  |                                            | Publication date and time of the article.        |
| raw_content_id| INTEGER    | FOREIGN KEY referencing raw_content(id)    | Links to the raw content file.                   |
| scraped_at    | TIMESTAMP  | NOT NULL, DEFAULT CURRENT_TIMESTAMP        | Timestamp when the article was scraped.          |
| created_at    | TIMESTAMP  | NOT NULL, DEFAULT CURRENT_TIMESTAMP        | Record creation timestamp.                       |
| updated_at    | TIMESTAMP  | NOT NULL, DEFAULT CURRENT_TIMESTAMP        | Record update timestamp.                         |

**Indexes**:
- `unique_id`: For quick lookups and ensuring uniqueness.
- `original_link`: To prevent duplicate entries and speed up searches.

### B. Raw Content Table

**Purpose**: Store pointers to raw content files to reduce database size.

**Table Name**: `raw_content`

**Columns**:

| Column Name | Data Type    | Constraints                                | Description                                      |
|-------------|--------------|--------------------------------------------|--------------------------------------------------|
| id          | SERIAL       | PRIMARY KEY                                | Unique identifier for each raw content.          |
| file_path   | VARCHAR(2048)| NOT NULL, UNIQUE                           | Path or URL to the raw content file (e.g., Google Drive link). |
| file_size   | BIGINT       |                                            | Size of the raw content file in bytes.           |
| file_format | VARCHAR(50)  |                                            | Format of the raw content (e.g., PDF, TXT).      |
| created_at  | TIMESTAMP    | NOT NULL, DEFAULT CURRENT_TIMESTAMP        | Record creation timestamp.                       |
| updated_at  | TIMESTAMP    | NOT NULL, DEFAULT CURRENT_TIMESTAMP        | Record update timestamp.                         |

**Indexes**:
- `file_path`: For quick access and ensuring uniqueness.

### C. Entities Table

**Purpose**: Store information about entities (people, organizations) mentioned in articles.

**Table Name**: `entities`

**Columns**:

| Column Name | Data Type    | Constraints                                | Description                                      |
|-------------|--------------|--------------------------------------------|--------------------------------------------------|
| id          | SERIAL       | PRIMARY KEY                                | Unique identifier for each entity.               |
| name        | VARCHAR(255) | NOT NULL                                   | Name of the entity (e.g., person or organization).|
| type        | VARCHAR(50)  | NOT NULL                                   | Type of entity (e.g., Person, Organization).     |
| created_at  | TIMESTAMP    | NOT NULL, DEFAULT CURRENT_TIMESTAMP        | Record creation timestamp.                       |
| updated_at  | TIMESTAMP    | NOT NULL, DEFAULT CURRENT_TIMESTAMP        | Record update timestamp.                         |

**Indexes**:
- `name`: To speed up searches and ensure quick lookups.

### D. Events Table

**Purpose**: Store information about events related to the articles.

**Table Name**: `events`

**Columns**:

| Column Name | Data Type    | Constraints                                | Description                                      |
|-------------|--------------|--------------------------------------------|--------------------------------------------------|
| id          | SERIAL       | PRIMARY KEY                                | Unique identifier for each event.                |
| name        | VARCHAR(255) | NOT NULL                                   | Name or title of the event.                      |
| description | TEXT         |                                            | Detailed description of the event.               |
| start_time  | TIMESTAMP    |                                            | Start time of the event.                         |
| created_at  | TIMESTAMP    | NOT NULL, DEFAULT CURRENT_TIMESTAMP        | Record creation timestamp.                       |
| updated_at  | TIMESTAMP    | NOT NULL, DEFAULT CURRENT_TIMESTAMP        | Record update timestamp.                         |

**Indexes**:
- `name`: For quick searches and lookups.

### E. Entity-Article Relationships Table

**Purpose**: Manage many-to-many relationships between entities and articles, recording their interactions over time.

**Table Name**: `entity_article_relationships`

**Columns**:

| Column Name   | Data Type  | Constraints                                | Description                                      |
|---------------|------------|--------------------------------------------|--------------------------------------------------|
| id            | SERIAL     | PRIMARY KEY                                | Unique identifier for each relationship.         |
| entity_id     | INTEGER    | FOREIGN KEY referencing entities(id), NOT NULL | Links to the related entity.                     |
| news_id       | INTEGER    | FOREIGN KEY referencing news_articles(id), NOT NULL | Links to the related news article.               |
| relation_type | VARCHAR(50)| NOT NULL                                   | Type of relation (e.g., Mentioned, Involved).    |
| related_at    | TIMESTAMP  | NOT NULL, DEFAULT CURRENT_TIMESTAMP        | Timestamp when the relationship was identified.  |

**Indexes**:
- Composite index on `(entity_id, news_id)` for efficient querying.

### F. Event-Article Relationships Table

**Purpose**: Manage relationships between events and articles, tracking which articles are related to which events.

**Table Name**: `event_article_relationships`

**Columns**:

| Column Name       | Data Type  | Constraints                                | Description                                      |
|-------------------|------------|--------------------------------------------|--------------------------------------------------|
| id                | SERIAL     | PRIMARY KEY                                | Unique identifier for each relationship.         |
| event_id          | INTEGER    | FOREIGN KEY referencing events(id), NOT NULL | Links to the related event.                      |
| news_id           | INTEGER    | FOREIGN KEY referencing news_articles(id), NOT NULL | Links to the related news article.               |
| intermediate_state| VARCHAR(255)|                                           | Status or intermediate state related to the event.|
| related_at        | TIMESTAMP  | NOT NULL, DEFAULT CURRENT_TIMESTAMP        | Timestamp when the relationship was identified.  |

**Indexes**:
- Composite index on `(event_id, news_id)` for efficient querying.

### G. Scraping Status Table

**Purpose**: Track the scraping status of each news article to manage duplicates and ongoing scraping processes.

**Table Name**: `scraping_status`

**Columns**:

| Column Name | Data Type    | Constraints                                | Description                                      |
|-------------|--------------|--------------------------------------------|--------------------------------------------------|
| id          | SERIAL       | PRIMARY KEY                                | Unique identifier for each scraping status entry.|
| news_id     | INTEGER      | FOREIGN KEY referencing news_articles(id), UNIQUE, NOT NULL | Links to the related news article.               |
| is_scraped  | BOOLEAN      | NOT NULL, DEFAULT FALSE                    | Indicates whether the article has been scraped.  |
| scraped_at  | TIMESTAMP    |                                            | Timestamp when the article was scraped.          |
| created_at  | TIMESTAMP    | NOT NULL, DEFAULT CURRENT_TIMESTAMP        | Record creation timestamp.                       |
| updated_at  | TIMESTAMP    | NOT NULL, DEFAULT CURRENT_TIMESTAMP        | Record update timestamp.                         |

**Indexes**:
- `news_id`: Ensures one-to-one relationship with `news_articles` and facilitates quick lookups.

## 3. Relationships and Normalization

### A. Entity-Relationship Diagram (ERD)

Here’s a simplified ERD to visualize the relationships:

- `[news_articles] 1---M [entity_article_relationships] M---1 [entities]`
- `[news_articles] 1---M [event_article_relationships] M---1 [events]`
- `[news_articles] 1---1 [raw_content]`
- `[news_articles] 1---1 [scraping_status]`

### B. Normalization

The proposed schema follows Third Normal Form (3NF):
1. **First Normal Form (1NF)**: All tables have atomic columns with no repeating groups.
2. **Second Normal Form (2NF)**: All non-key attributes are fully functional dependent on the primary key.
3. **Third Normal Form (3NF)**: No transitive dependencies; non-key attributes do not depend on other non-key attributes.

## 4. Addressing Your Specific Questions

### A. Separate Scraping Status Table vs. Integrate into News Articles

**Option 1: Separate `scraping_status` Table**

**Advantages**:
- **Separation of Concerns**: Keeps scraping logic separate from article metadata.
- **Flexibility**: Allows tracking multiple scraping attempts or statuses per article in the future.
- **Scalability**: Easier to extend with additional scraping-related fields without cluttering the `news_articles` table.

**Option 2: Integrate Scraping Status into `news_articles` Table**

**Advantages**:
- **Simpler Schema**: Fewer tables to manage.
- **Performance**: Fewer joins when querying scraping status alongside article metadata.

**Implementation**:

Add the following columns to `news_articles`:

| Column Name | Data Type    | Constraints                                | Description                                      |
|-------------|--------------|--------------------------------------------|--------------------------------------------------|
| is_scraped  | BOOLEAN      | NOT NULL, DEFAULT FALSE                    | Indicates whether the article has been scraped.  |
| scraped_at  | TIMESTAMP    |                                            | Timestamp when the article was scraped.          |

**Recommendation**:

For simplicity and efficiency, especially if each article is scraped only once, integrate the scraping status into the `news_articles` table. This reduces the need for an additional table and simplifies queries.

**Revised `news_articles` Table**:

| Column Name | Data Type    | Constraints                                | Description                                      |
|-------------|--------------|--------------------------------------------|--------------------------------------------------|
| ...         | ...          | ...                                        | ...                                              |
| is_scraped  | BOOLEAN      | NOT NULL, DEFAULT FALSE                    | Indicates whether the article has been scraped.  |
| scraped_at  | TIMESTAMP    |                                            | Timestamp when the article was scraped.          |
| ...         | ...          | ...                                        | ...                                              |

**Pros**:
- **Simpler Queries**: Fetch scraping status directly with article data.
- **Easier Maintenance**: Fewer tables to manage.

**Cons**:
- **Less Flexibility**: Harder to track multiple scraping attempts without additional fields.

**Conclusion**:

If your scraping process involves a single scrape per article, integrating the scraping status into the `news_articles` table is the most efficient approach. If you anticipate needing to track multiple scraping attempts or more detailed scraping information, consider maintaining a separate `scraping_status` table.

## 5. Sample Schema in SQL

Here’s how you might define these tables using SQL (assuming PostgreSQL):
