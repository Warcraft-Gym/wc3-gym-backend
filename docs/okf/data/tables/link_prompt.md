---
type: Data Model
title: link_prompt
description: A suggestion that an earlier player is a login, answered once by that login, or the notice that another login verified a tag and took it.
resource: ../../../../app/models/link_prompt.py
tags: [auth, data]
generated: { by: claude-code/claude-opus-5-5, at: 2026-09-24T13:20:36Z }
verified: { by: process:test_okf, at: 2026-09-24T13:20:36Z }
sources:
  - id: model
    resource: ../../../../app/models/link_prompt.py
    title: LinkPrompt
  - id: migration
    resource: ../../../../migrations/versions/c3e9a7d1f205_add_the_link_prompt_table.py
    title: The table
  - id: service
    resource: ../../../../app/services/link_prompts.py
    title: Suggest, claim, verify, and the open prompts of a login
  - id: import
    resource: ../../../../app/services/season_import.py
    title: The workbook import that writes suggestions
  - id: routes
    resource: ../../../../app/api/routes/users.py
    title: The member prompt routes
---

# Schema

| Column | Type | Null | Meaning |
|---|---|---|---|
| `id` | INTEGER | no | Primary key. |
| `kind` | VARCHAR | no | `suggest` or `taken`. |
| `person_id` | INTEGER | yes | The earlier player a suggestion names: a person with no login. |
| `user_id` | INTEGER | yes | The login a prompt speaks to, when `tag` does not name it: a Discord-name suggestion, or a `taken` notice. |
| `tag` | VARCHAR | yes | The tag the prompt is about. A suggestion with a tag speaks to the login that holds it. |
| `reason` | VARCHAR | no | `sheet`: the sheet's tag, which a login holds unverified. `probable`: a name-search guess from the workbook's `Suggested Tag` column. `discord`: the sheet's or an earlier player's Discord name. `bnet`: a Battle.net verify took the tag. |
| `created_at` | TIMESTAMP | no | When the prompt was written, UTC. |
| `closed_at` | TIMESTAMP | yes | When it closed, UTC. Null while open. |
| `outcome` | VARCHAR | yes | `accepted`, `dismissed`, `joined` or `seen`. |

# Keys and joins

Primary key `id`. Foreign keys `person_id` and `user_id` to [users](users.md), deleted with the person. Index on each. A merge repoints both columns like every user id column.

# Rules

- Only a tag Battle.net verified on a login joins an earlier player to it unasked. A weaker hint is a suggestion.
- The workbook import: a row whose real tag a login holds unverified is an earlier player, found again by its open `sheet` suggestion, and written without that tag; the login gets the suggestion. A row naming the login's own Discord id is that login. A new person's Discord name that a login holds is left off the person and becomes a `discord` suggestion to that login. A `Suggested Tag` cell writes a `probable` suggestion and no tag row. New tag rows are dated from the season's start date.
- The member signup: typing a tag an earlier player holds claims that player at once, unverified; a login with a profile joins it. An earlier player holding only the member's Discord name lets go of the name and becomes a `discord` suggestion. See [user_battle_tag](user_battle_tag.md).
- A login sees a suggestion that speaks to it alone. An earlier player whose open suggestions speak to two or more logins is shown to none.
- Only the login's own answer closes a prompt; reading it closes nothing. Accepting a suggestion merges the earlier player into the login, unverified; a merge stop answers 409. Dismissing closes it for good.
- A Battle.net verify joins every earlier player an open `sheet` suggestion on that tag names; `probable` ones stay suggestions. A verify that takes a tag another login held unverified writes that login a `taken` notice.

# Routes

| Route | Does |
|---|---|
| `GET /users/me/prompts` | The member's open prompts: `{id, kind, tag, person_id, name, seasons}`, where `seasons` names the earlier player's season signups. |
| `POST /users/me/prompts/{id}` `{accept}` | `true` accepts a suggestion; `false` dismisses it, or closes a notice. Answers the member's user read. A prompt that is not the member's is 404. |
