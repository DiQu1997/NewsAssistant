# News Assistant
## Context
News Assistant is a project from my personal interest. There are tons of events happening everyday and millions of news generated for them. It's so hard for people to figure out what's going on in a long term. How does an event evolving, what happened before today. Also which information is reliable, how could I handle so many evolving news everyday. I don't want to search them everyday for every event, I don't want to read a long articles with many informations that I already know. This is what news assistant is about. I want to build an automatic, AI-powered news assistant, that store daily news, cluster them, sort out the history of each event, show me what happened today, and what happened for a specific story, with reliable source.

### terminology:
news: A single news article {index, author, website, publication date, title, content, content vector, short summary, event tags list, entity tags list}

event: A list of news index sorted by news publication time, related entities, a short summary of 

entity: A list of news index sorted by news publication time, related events, a short summary in time order

## Feature
### 1. Daily news letter:
 with customized topic / interesting area. Each news will have the title, summary, link, related tag like the people in the news, event related to the news
### 2. Search: 
User can send a specific query and get a list of news related, although in this case it's just an ai-optimized search-engine in all news website. What we can do is specific two types of query: **Event** and **Entity**, entity could be company, country, people, etc. In this query we can provide a summary, timeline, relationship graph and some other data visualization.
### 3. List: 
User could query a list of current hot topics with summary and some simple timeline

## Implementation:
### i. Frontend: 
1. Email: Email can serve our daily news letter. We can also use email as query entry. With AI-support we can allow user to send query to our backend via email and return with an email. Main advantage: Easy implementation in frontend interface.
2. Web: Including REST-API and web page for visualization
3. Message (optional): Same as email but shorter news letter.

### ii. Backend:
#### REST server: 
What language and what framework? 
#### News processing server
There could be different type of frontend server and having a separate news processing unit is good for modularity and upgrade. The news processing server should provide grpc API for frontend server to get news data.
### Database
which database? What kind of operations it needs to the database. This is gonna be trick honestly.
This is one of the most important problem. The database should be able to store and retrieve news, and also support vector search and clustering.

1. What do I store: title, content, author, publication time, content_vector, topic (multi layer), key entities related to te event
2. Most frequent operation: Append daily news, query for certain event or entities. 

#### Requirements:
1. Vector search: We need to store the content vector and be able to search for similar vectors efficiently.
2. Cluster: We need to store the cluster of news, and be able to add news to a cluster, and search for similar clusters efficiently.

#### Options:
1. SQL database: Good for storing, but lack efficiency support on vector search, clustering
2. SQL database for content store + vector index for clustering and searching: How to do vector indexing?
3. NoSQL database: Good for storing and key-value search, but lack efficiency support on vector search, clustering, and listing
4. Vector database: Need more research on it

Relational database: Good for storing, but lack efficiency support on vector search, clustering

### iii. Workflow:
1. Every day or every few hours, the server should poll the latest news
2. For all latest news, we need to do some processing:
   1. Use NewsDataIo Get the content vector
   2. Get the key entities, vector in the event
   3. Use LLM to get the vector for this news
   4. Assign it to an event cluster, the cluster should contains the index in stead of the entire news. Multiple types of clusters are needed: cluster of an event, cluster of an entity

# Next Step:
Research on the database and vector search, clustering.