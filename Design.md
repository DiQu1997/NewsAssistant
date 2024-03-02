# News Assistant
## Introduction
News Assistant is a project from my personal interest. There are tons of events happening everyday and millions of news generated for them. It's so hard for people to figure out what's going on in a long term. How does an event evolving, what happened before today. Also which information is reliable, how could I handle so many evolving news everyday. I don't want to search them everyday for every event, I don't want to read a long articles with many informations that I already know. This is what news assistant is about. I want to build an automatic, AI-powered news assistant, that store daily news, cluster them, sort out the history of each event, show me what happened today, and what happened for a specific story, with reliable source.

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
#### RPC Server(?)
Hard to say if we need this. We will see. But if we do the only option is probably grpc.
### Database
which database? What kind of operations it needs to the database. This is gonna be trick honestly.