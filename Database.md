# Database Design

## Overview
To better utilize my already paid storage in Google Drive, I decide to use SQLite as my database so that multiple clients can access the database concurrently through Google Drive. It contains 3 tables:
- raw Data: the original informations' metadata. It contains a pointer to the raw data content to avoid large data in database for SQLite
- Event Data: an event is a collection of news. It contains a pointer to the news data and the event name.
- Entity Data: an entity is a collection of news. It contains a pointer to the news data and the entity name.

## Concurrency
SQLite is a file-based database, so it is not designed for concurrent access. To support consistency, I use a lock file to ensure that only one client can access the database at a time.
The design of the lock file is as follows:
- A lock file is created and exists all time
- The content of the lock file is the lock time and lock client id
- Each time the lock is valid for 1 hour
- When a client wants to access the database, it first checks if the lock file exists. If it does, it checks if the lock time is within the time limit. If it is, it means that another client is accessing the database, so it waits for the lock file to be released.
- If the lock time is not within the time limit, it means the lock is expired, so it overwrites the lock file with the current time and client id.
- After write, the client will wait for a configurable time(15 seconds by default) to ensure the lock is overwritten by the another client.
- After the configurable waiting time, the client will check if the lock is still valid. If it is, it means the lock is not overwritten by the another client, then it will continue to connect to the database.

## News Data

- Title: string, the title of the news
- Content-Pointer: int
- URL: string
- Source: string
- Date: datetime

### Event Data
- Event Name: string
- Event Description: string
- Event start date: datetime
- Event end date: datetime
- Event location: string

### Entity Data
- Entity Name: string
- Entity Description: string

### Event-News
- Event Name: string
- News Pointer: int

### Entity-News
- Entity Name: string
- News Pointer: int

### Event-Entity
- Event Name: string
- Entity Name: string
- Entity relation in Event: string