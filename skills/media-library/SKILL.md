---
name: media-library
description: Answer questions about movies, television shows, and music available in the household Emby media library.
---

# Media Library

## Purpose

Help the user find movies, television series, seasons, and episodes
in their household Emby media library.

## Available tools

- `search_movies`: Search the Emby library for candidate movie titles.
  - Requires `title`.

- `search_series`: Search the Emby library for candidate television series.
  - Requires `title`.

- `get_seasons`: List available seasons of a television series.
  - Requires `series_id` obtained from `search_series`.

- `get_episodes`: List available episodes in a specific season.
  - Requires `series_id` and `season_id` obtained from previous tool results.

## Television lookup workflow

To check whether a television series is available:

1. Call `search_series` with the requested title.
2. Identify the correct series from the returned candidates.

To check which seasons are available:

1. Find the series using `search_series`.
2. Call `get_seasons` using the returned series ID.
3. Report the available season numbers.

To check whether a specific episode is available:

1. Find the series using `search_series`.
2. Call `get_seasons` using the returned series ID.
3. Identify the requested season by its `number` field.
4. Call `get_episodes` using the series ID and season ID.
5. Identify the requested episode by its `episode` field.
6. Report whether the episode was found.

## Important information

Emby's search may return partial matches.

A returned movie or television series is not necessarily the title
the user requested.

Distinguish between confirmed title matches and loosely related results.

Television series names may include a release year, such as
"Foundation (2021)". Account for this when comparing titles.

Never invent Emby IDs. Use IDs returned by previous tool calls.

Do not assume a season contains every episode merely because
the season exists.

If no matching title, season, or episode is found, explain what
could not be found in the library.

Base availability claims on actual Emby results.

## Music library

Use these tools to answer questions about music available in Emby.

### Available tools

- `search_artists(name)`: Search for music artists by name. Returns artist names, sorting names, and Emby artist IDs.
- `get_artist_tracks(artist_id)`: List tracks associated with an artist.
- `get_artist_albums(artist_id)`: List albums associated with an artist.
- `get_album_tracks(album_id)`: List tracks belonging to an album.

### Investigation workflow

For questions about an artist's songs:

1. Call `search_artists` using the requested artist name.
2. Identify the correct artist from the results.
3. Call `get_artist_tracks` using the returned artist ID.
4. Report the available tracks and their albums.

For questions about an artist's albums:

1. Call `search_artists`.
2. Call `get_artist_albums` using the returned artist ID.
3. Report the available albums.

For questions about tracks on a particular album:

1. Call `search_artists`.
2. Call `get_artist_albums`.
3. Identify the requested album.
4. Call `get_album_tracks` using its album ID.

### Important rules

- Never invent artist, album, or track IDs.
- Preserve distinct album versions, even when their titles are similar.
- Preserve separate track records, even when their titles match.
- Different Emby track IDs establish separate library records, not necessarily different recordings or versions. 
- Artist names may differ between Emby's artist records and track metadata.
- Do not assume that a partial artist-name match identifies the requested artist.
- Only report music confirmed by Emby's tool results.