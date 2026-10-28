---
name: media-library
description: Answer questions about movies available in the household media library.
---

# Media Library

## Purpose

Help the user find movies in their household media library.

## Available tools

- `search_movies`: Search the Emby library for candidate movie titles.

## Important information

Emby's search may return partial matches.

A returned movie is not necessarily the movie the user requested.

Distinguish between confirmed title matches and loosely related results.

If no matching title is found, explain that the requested movie
could not be found in the library.